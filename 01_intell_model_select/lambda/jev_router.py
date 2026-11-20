"""
Jev_Router and Routing_Policy for the intelligent model selection demo.

Jev is a decision service: it chooses among the candidate model IDs but never runs a
model. The Routing_Policy is the safety-critical part of the Jev path. It validates a
Jev answer against the Candidate_Catalogue, the Confidence_Threshold, and the current
health state, and decides whether to accept the Jev choice, substitute a healthy
candidate, or fall back to the Custom_Router.

Design constraints (see .kiro/specs/jev-router-comparison/design.md, section 3):

- `apply_policy` is a PURE function: no I/O, no clock, no logging. Network calls, secret
  reads, and health lookups all happen at the edge and are injected as arguments. This
  keeps the policy deterministic and the main target of the property-based tests.
- The Candidate_Catalogue is the three models named in the requirements, read from the
  Custom_Router's capability map (`router.model_capabilities` / `ModelType`). The IDs are
  a constant tuple here so no other module changes.
- The policy evaluates its rules in a fixed order; the first rule that applies decides the
  outcome (the ladder in the design's Architecture section).

This module defines the catalogue, the result/decision dataclasses, the pure
`apply_policy`, and the `JevRouter` that orchestrates the edge: configuration check,
request build, HTTP call (or recording lookup), policy evaluation, and fallback to the
Custom_Router through an injected provider.
"""

import logging
import math
import os
import time
from dataclasses import dataclass, field
from typing import (
    AbstractSet,
    Any,
    Callable,
    Collection,
    Dict,
    FrozenSet,
    List,
    Optional,
)

from bedrock_adapter import ModelType
from jev_client import (
    JevAnswer,
    JevError,
    JevOutcome,
    build_request,
    call_jev,
    describe_capability,
    get_jev_model,
    get_timeout_seconds,
    load_recording,
)
from jev_secret import get_jev_key, jev_status

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Candidate_Catalogue
# ---------------------------------------------------------------------------

# The candidate model IDs the Jev_Choice_Question offers, in catalogue order.
# Order matters: it is the deterministic tie-break when two healthy candidates share
# the highest Jev probability during an unhealthy substitution. The IDs are taken from
# the Custom_Router's ModelType enum (router.model_capabilities uses ModelType.<X>.value)
# so the two routers share one source of truth. router.py is imported, never modified.
CANDIDATE_CATALOGUE = (
    ModelType.CLAUDE_HAIKU_4_5.value,  # us.anthropic.claude-haiku-4-5-20251001-v1:0
    ModelType.GPT_OSS_20B.value,       # openai.gpt-oss-20b-1:0
    ModelType.NOVA_PRO.value,          # amazon.nova-pro-v1:0
    ModelType.NOVA_LITE.value,         # amazon.nova-lite-v1:0
    ModelType.NOVA_MICRO.value,        # amazon.nova-micro-v1:0
)

# ---------------------------------------------------------------------------
# Confidence_Threshold
# ---------------------------------------------------------------------------

DEFAULT_CONFIDENCE_THRESHOLD = 0.6


def get_confidence_threshold() -> float:
    """
    Return the Confidence_Threshold from JEV_CONFIDENCE_THRESHOLD, defaulting safely.

    The default is 0.6. An unparsable or out-of-range value (not a finite number in
    [0, 1]) falls back to the default and logs a warning, so a bad configuration never
    breaks a request.
    """
    raw = os.environ.get("JEV_CONFIDENCE_THRESHOLD", "").strip()
    if not raw:
        return DEFAULT_CONFIDENCE_THRESHOLD
    try:
        value = float(raw)
    except (TypeError, ValueError):
        logger.warning(
            "Invalid JEV_CONFIDENCE_THRESHOLD; using default %.2f",
            DEFAULT_CONFIDENCE_THRESHOLD,
        )
        return DEFAULT_CONFIDENCE_THRESHOLD
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        logger.warning(
            "Out-of-range JEV_CONFIDENCE_THRESHOLD; using default %.2f",
            DEFAULT_CONFIDENCE_THRESHOLD,
        )
        return DEFAULT_CONFIDENCE_THRESHOLD
    return value


# ---------------------------------------------------------------------------
# Result and decision types
# ---------------------------------------------------------------------------


@dataclass
class RoutingResult:
    """
    The outcome from one router for one query.

    Populated by `JevRouter.route` (later task) and by the Custom_Router adapter. On a
    fallback, `model_id`, `provider`, and `confidence` come from the Custom_Router
    decision, while `jev_confidence` and `probabilities` keep whatever Jev returned so the
    UI can show why the Jev answer was rejected.
    """

    router: str  # "custom" | "jev"
    model_id: str
    provider: str
    confidence: float  # in [0.0, 1.0]
    latency_ms: int
    reasoning: List[str]
    fallback: bool
    fallback_reason: Optional[str]  # "not_configured" | "timeout" | ... | None
    router_used: str  # "custom" | "jev"
    probabilities: Dict[str, float] = field(default_factory=dict)  # empty when Jev gave none
    jev_confidence: Optional[float] = None  # what Jev reported, even when rejected
    high_consequence: Optional[float] = None
    mode: str = "live"  # "live" | "recorded"


@dataclass(frozen=True)
class PolicyDecision:
    """
    The result of the Routing_Policy ladder.

    `model_id` is the accepted catalogue model ID, or None meaning "use the Fallback".
    `fallback` is True exactly when `model_id` is None. `fallback_reason` is a short,
    stable tag; `reasoning` is the human-readable explanation of the decision.
    """

    model_id: Optional[str]  # None means "use the Fallback"
    fallback: bool
    fallback_reason: Optional[str]
    reasoning: List[str]


# Stable fallback-reason tags.
REASON_NOT_CONFIGURED = "not_configured"
REASON_UNRECOGNISED = "unrecognised"
REASON_LOW_CONFIDENCE = "low_confidence"
REASON_UNHEALTHY_CHOICE = "unhealthy_choice"


# ---------------------------------------------------------------------------
# Routing_Policy
# ---------------------------------------------------------------------------


def apply_policy(
    outcome: Optional[JevOutcome],
    *,
    configured: bool,
    catalogue_ids: Collection[str],
    healthy: AbstractSet[str],
    threshold: float,
) -> PolicyDecision:
    """
    Decide whether to accept a Jev answer or fall back to the Custom_Router.

    PURE: no I/O, no clock, no logging. Everything the decision needs is passed in.

    Rules, in order (the first that applies decides):

      1. Not configured: fallback with reason `not_configured` (no call was made,
         `outcome` is None).
      2. The outcome is a JevError: fallback with the error category as the reason.
      3. The chosen option is not in the Candidate_Catalogue: fallback, reason
         `unrecognised`.
      4. The reported confidence is below the threshold: fallback, reason
         `low_confidence`. The reasoning names both the received confidence and the
         threshold.
      5. The chosen model is healthy: accept it.
      6. Otherwise the chosen model is unhealthy. Consider the healthy catalogue members
         and pick the one with the highest Jev probability whose probability is at least
         the threshold, breaking ties by catalogue order. If one exists, accept it
         (substitution). If none exists, fallback with reason `unhealthy_choice`.

    Args:
        outcome: The Jev outcome, or None when Jev was not configured / not called.
        configured: Whether the Jev_Secret is configured.
        catalogue_ids: The Candidate_Catalogue IDs, in catalogue order for the tie-break.
        healthy: The set of currently healthy model IDs (already catalogue-filtered by the
            caller, though this function intersects again defensively).
        threshold: The Confidence_Threshold in [0, 1].

    Returns:
        A PolicyDecision. `model_id is None` means use the Fallback.
    """
    # Preserve catalogue order for deterministic tie-breaking.
    catalogue_order = list(catalogue_ids)
    catalogue_set = set(catalogue_order)

    # Rule 1: not configured.
    if not configured:
        return PolicyDecision(
            model_id=None,
            fallback=True,
            fallback_reason=REASON_NOT_CONFIGURED,
            reasoning=["Jev is not configured; using the custom router."],
        )

    # Rule 2: the client reported a categorised error.
    if isinstance(outcome, JevError):
        reason = outcome.category
        detail = f" ({outcome.detail})" if getattr(outcome, "detail", None) else ""
        status = (
            f" HTTP status {outcome.status_code}."
            if getattr(outcome, "status_code", None) is not None
            else ""
        )
        return PolicyDecision(
            model_id=None,
            fallback=True,
            fallback_reason=reason,
            reasoning=[
                f"Jev client reported a {reason} error{detail}.{status} "
                "Using the custom router."
            ],
        )

    # From here on a valid JevAnswer is required. A None or unexpected type is treated
    # like a missing answer (defensive; call_jev never returns None in practice).
    if not isinstance(outcome, JevAnswer):
        return PolicyDecision(
            model_id=None,
            fallback=True,
            fallback_reason=REASON_UNRECOGNISED,
            reasoning=["Jev returned no usable answer; using the custom router."],
        )

    # Rule 3: the chosen option is not a catalogue member.
    if outcome.choice not in catalogue_set:
        return PolicyDecision(
            model_id=None,
            fallback=True,
            fallback_reason=REASON_UNRECOGNISED,
            reasoning=[
                f"Jev chose '{outcome.choice}', which is not a known candidate model; "
                "the answer was unrecognised. Using the custom router."
            ],
        )

    # Rule 4: confidence below the threshold.
    if outcome.confidence < threshold:
        return PolicyDecision(
            model_id=None,
            fallback=True,
            fallback_reason=REASON_LOW_CONFIDENCE,
            reasoning=[
                f"Jev confidence {outcome.confidence:.3f} is below the threshold "
                f"{threshold:.3f}; using the custom router."
            ],
        )

    # Rule 5: the chosen model is healthy. Accept it.
    if outcome.choice in healthy:
        return PolicyDecision(
            model_id=outcome.choice,
            fallback=False,
            fallback_reason=None,
            reasoning=[
                f"Accepted Jev choice '{outcome.choice}' with confidence "
                f"{outcome.confidence:.3f} (healthy)."
            ],
        )

    # Rule 6: the chosen model is unhealthy. Try to substitute a qualifying healthy
    # candidate, else fall back.
    # Candidates are the healthy catalogue members, ordered by catalogue order so that
    # ties on probability break deterministically.
    candidates = [
        model_id
        for model_id in catalogue_order
        if model_id in healthy and model_id in catalogue_set
    ]

    # Among candidates whose Jev probability meets the threshold, pick the highest. The
    # list is already in catalogue order and `max` keeps the first maximal element, so
    # the catalogue-order tie-break is preserved.
    qualifying = [
        model_id
        for model_id in candidates
        if outcome.probabilities.get(model_id, 0.0) >= threshold
    ]
    if qualifying:
        substitute = max(
            qualifying,
            key=lambda model_id: outcome.probabilities.get(model_id, 0.0),
        )
        return PolicyDecision(
            model_id=substitute,
            fallback=False,
            fallback_reason=None,
            reasoning=[
                f"Jev chose '{outcome.choice}', which is unhealthy; substituted the "
                f"highest-probability healthy candidate '{substitute}' "
                f"(probability {outcome.probabilities.get(substitute, 0.0):.3f} "
                f">= threshold {threshold:.3f})."
            ],
        )

    # No qualifying healthy candidate. Fall back.
    return PolicyDecision(
        model_id=None,
        fallback=True,
        fallback_reason=REASON_UNHEALTHY_CHOICE,
        reasoning=[
            f"Jev chose '{outcome.choice}', which is unhealthy, and no healthy candidate "
            f"had a probability at or above the threshold {threshold:.3f}; using the "
            "custom router."
        ],
    )


# ---------------------------------------------------------------------------
# High-consequence signal
# ---------------------------------------------------------------------------


def include_high_consequence() -> bool:
    """
    Return whether the optional high-consequence (``noul``) question is sent to Jev.

    Controlled by ``JEV_HIGH_CONSEQUENCE_SIGNAL``; only the literal value ``true``
    (case-insensitive, trimmed) enables it. Anything else, including unset, disables it.
    """
    return (os.environ.get("JEV_HIGH_CONSEQUENCE_SIGNAL") or "").strip().lower() == "true"


# ---------------------------------------------------------------------------
# Health snapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HealthSnapshot:
    """
    The healthy, catalogue-filtered model set seen by both routers for one request.

    Built once per jev/compare request by the handler so the Jev_Router, the policy, and
    the Custom_Router agree on the health state within the request (design "Health
    snapshot"). ``healthy_models`` is already intersected with the Candidate_Catalogue.
    """

    healthy_models: FrozenSet[str]


# ---------------------------------------------------------------------------
# Jev_Router
# ---------------------------------------------------------------------------


class JevRouter:
    """
    Orchestrates the Jev path: build the request, call Jev, apply the policy, and fall
    back to the Custom_Router when the Jev answer is unusable.

    The pure decision logic lives in `apply_policy`; this class performs the I/O at the
    edge (configuration check, HTTP call or recording lookup, timing, logging) and never
    changes the policy's purity or signature. The Custom_Router's `RoutingDecision` is
    obtained through an injected `custom_provider` callable so the handler can pass an
    already-computed decision in compare mode (so the Custom_Router runs once per request).
    """

    def __init__(self, router: Any) -> None:
        """
        Args:
            router: The IntelligentModelRouter instance. Read-only here: used for
                `model_capabilities` (to build capability-derived option descriptions)
                and `query_analyzer` (to derive the characteristics Jev sees). router.py
                is never modified.
        """
        self._router = router

    # -- catalogue helpers --------------------------------------------------

    def _build_catalogue(self) -> Dict[str, str]:
        """
        Build the Choice-question catalogue mapping {model_id: capability description}.

        Covers the three Candidate_Catalogue models, each description derived from the
        model's ModelCapabilities so the catalogue has a single source of truth. A model
        missing from the capability map is skipped defensively.
        """
        catalogue: Dict[str, str] = {}
        capabilities = getattr(self._router, "model_capabilities", {}) or {}
        for model_id in CANDIDATE_CATALOGUE:
            capability = capabilities.get(model_id)
            if capability is not None:
                catalogue[model_id] = describe_capability(capability)
        return catalogue

    def _provider_for(self, model_id: str) -> str:
        """Return the provider name for a catalogue model ID, or empty string if unknown."""
        capabilities = getattr(self._router, "model_capabilities", {}) or {}
        capability = capabilities.get(model_id)
        provider = getattr(capability, "provider", None)
        value = getattr(provider, "value", None)
        return value if isinstance(value, str) else ""

    # -- routing ------------------------------------------------------------

    def route(
        self,
        query_text: str,
        snapshot: HealthSnapshot,
        custom_provider: Callable[[], Any],
        threshold: Optional[float] = None,
    ) -> RoutingResult:
        """
        Route one query through Jev, falling back to the Custom_Router when needed.

        Steps (design section 3):
          1. Start a monotonic timer.
          2. Check configuration. If configured and live, build the request and call Jev;
             in recorded mode, look up the recording instead; if not configured, skip the
             call entirely (no HTTP).
          3. Run the pure `apply_policy`.
          4. On a fallback, obtain the Custom_Router decision through `custom_provider`.
          5. Stop the timer. Latency spans the Jev call through the policy decision,
             including a fresh Custom_Router decision in `jev` mode because the user waits
             for it.
          6. Build the `RoutingResult` and log one summary line.

        Any unexpected exception on the Jev path (outside `call_jev`, which never raises)
        is caught, treated as `invalid_response`, and logged by class name only. The
        Custom_Router's "no healthy models" RuntimeError from `custom_provider` is
        propagated unchanged.

        Args:
            query_text: The raw query text. Never logged.
            snapshot: The per-request healthy, catalogue-filtered model set.
            custom_provider: Zero-arg callable returning the Custom_Router RoutingDecision.

        Returns:
            A fully populated RoutingResult.
        """
        start = time.monotonic()

        status = jev_status()
        configured = bool(status.get("configured"))
        mode = status.get("mode", "live")
        # A per-request threshold override (e.g. from the UI slider) wins when
        # provided and valid; otherwise fall back to the configured default.
        threshold = (
            threshold
            if (threshold is not None and 0.0 <= threshold <= 1.0)
            else get_confidence_threshold()
        )
        healthy = set(snapshot.healthy_models)

        outcome: Optional[JevOutcome] = None

        # Step 2: perform the Jev call only when configured. Any unexpected failure on the
        # Jev path (characteristics, request build, recording read) is reduced to an
        # invalid_response so a Jev problem never breaks a request the Custom_Router can
        # complete. call_jev itself never raises.
        if configured:
            try:
                characteristics = self._derive_characteristics(query_text)
                catalogue = self._build_catalogue()

                if mode == "recorded":
                    outcome = load_recording(query_text)
                else:
                    key = get_jev_key()
                    if not key:
                        # Secret vanished between status and read; treat as not configured.
                        configured = False
                    else:
                        payload = build_request(
                            query_text=query_text,
                            characteristics=characteristics,
                            catalogue=catalogue,
                            model=get_jev_model(),
                            include_high_consequence=include_high_consequence(),
                        )
                        outcome = call_jev(
                            payload,
                            key,
                            get_timeout_seconds(),
                            catalogue_ids=list(catalogue.keys()),
                        )
            except Exception as exc:  # noqa: BLE001 - never let the Jev path raise
                logger.warning("Unexpected Jev path error: %s", type(exc).__name__)
                outcome = JevError("invalid_response", detail="unexpected")

        # Step 3: pure policy decision.
        decision = apply_policy(
            outcome,
            configured=configured,
            catalogue_ids=CANDIDATE_CATALOGUE,
            healthy=healthy,
            threshold=threshold,
        )

        # Capture what Jev returned (even when rejected) so the UI can show why.
        jev_confidence: Optional[float] = None
        probabilities: Dict[str, float] = {}
        high_consequence: Optional[float] = None
        if isinstance(outcome, JevAnswer):
            jev_confidence = outcome.confidence
            probabilities = dict(outcome.probabilities)
            high_consequence = outcome.high_consequence

        if decision.fallback:
            # Step 4: the Custom_Router produces the actual decision. Its "no healthy
            # models" RuntimeError propagates unchanged (Requirement 4.10).
            custom_decision = custom_provider()
            model_id = custom_decision.selected_model_id
            provider = getattr(custom_decision.selected_provider, "value", "")
            confidence = float(getattr(custom_decision, "confidence_score", 0.0) or 0.0)
            reasoning = list(decision.reasoning)
            reasoning.append(
                f"Fallback to the custom router, which selected '{model_id}'."
            )
            if getattr(custom_decision, "decision_reasoning", None):
                reasoning.extend(custom_decision.decision_reasoning)
            router_used = "custom"
        else:
            # Jev's choice (or a healthy substitute) was accepted.
            model_id = decision.model_id  # guaranteed non-None when not a fallback
            provider = self._provider_for(model_id)
            confidence = jev_confidence if jev_confidence is not None else threshold
            reasoning = list(decision.reasoning)
            reasoning.append("Decision came from Jev.")
            router_used = "jev"

        # Step 5: stop the timer. Latency spans the Jev call through the policy decision,
        # including the fresh Custom_Router decision on a jev-mode fallback.
        latency_ms = max(0, int((time.monotonic() - start) * 1000))

        result = RoutingResult(
            router="jev",
            model_id=model_id,
            provider=provider,
            confidence=max(0.0, min(1.0, float(confidence))),
            latency_ms=latency_ms,
            reasoning=reasoning,
            fallback=decision.fallback,
            fallback_reason=decision.fallback_reason,
            router_used=router_used,
            probabilities=probabilities,
            jev_confidence=jev_confidence,
            high_consequence=high_consequence,
            mode=mode,
        )

        # Step 6: one summary line. Never log the query text, headers, or the key; only
        # the query length. On a client error also log the category and status code.
        logger.info(
            "Jev route summary: mode=%s model=%s confidence=%.3f latency_ms=%d "
            "fallback=%s query_len=%d",
            mode,
            model_id,
            result.confidence,
            latency_ms,
            decision.fallback,
            len(query_text),
        )
        if isinstance(outcome, JevError):
            logger.info(
                "Jev route error detail: category=%s status_code=%s",
                outcome.category,
                outcome.status_code,
            )

        return result

    def _derive_characteristics(self, query_text: str) -> Dict[str, Any]:
        """
        Derive the characteristics Jev sees from the Custom_Router's QueryAnalyzer.

        Returns the subset of signals `build_request` forwards. The analyzer is read-only
        here. A plain dict is returned so the payload is JSON-serialisable.
        """
        analyzer = getattr(self._router, "query_analyzer", None)
        if analyzer is None:
            return {}
        chars = analyzer.analyze_query(query_text)
        return {
            "length": chars.length,
            "complexity_score": chars.complexity_score,
            "estimated_tokens": chars.estimated_tokens,
            "requires_reasoning": chars.requires_reasoning,
            "requires_creativity": chars.requires_creativity,
            "requires_code": chars.requires_code,
            "requires_analysis": chars.requires_analysis,
        }
