"""Property test for the final-route invariant of the Jev_Router.

Feature: jev-router-comparison, Property 7: The final route is always a healthy
catalogue member or the declared Fallback.

For ALL Jev outcomes (any model ID choice, any confidence, any probabilities,
any error category, or "not configured") and ANY combination of model health
states, ``JevRouter.route`` returns a result that is exactly one of:

* an accepted Jev choice -- ``fallback`` is False, ``fallback_reason`` is None,
  ``router_used`` is ``"jev"``, and ``model_id`` is a healthy member of the
  Candidate_Catalogue; or
* a declared Fallback -- ``fallback`` is True, ``fallback_reason`` is not None,
  ``router_used`` is ``"custom"``, and ``model_id`` is the Custom_Router's
  fallback model (never an unhealthy model and never a model Jev invented).

The test quantifies over the full outcome space using the shared Hypothesis
generators ``jev_outcomes()`` and ``health_states()`` from tests/strategies.py,
mapping the tagged-dict outcomes into the real ``JevAnswer`` / ``JevError`` /
``None`` values the router consumes, and driving ``configured`` accordingly
(the "not configured" sentinel means ``configured=False`` and no Jev call).

Validates: Requirements 4.1, 4.9, 8.5 (and 14.8).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import jev_router
from jev_router import CANDIDATE_CATALOGUE, HealthSnapshot, JevRouter
from jev_client import JevAnswer, JevError

from strategies import CATALOGUE_IDS, health_states, jev_outcomes


# --------------------------------------------------------------------------- #
# A dedicated, unhealthy-and-not-a-catalogue-member fallback model.
# --------------------------------------------------------------------------- #
# The Custom_Router may legitimately pick a model outside the Candidate_Catalogue
# (the design notes it also knows Nova Lite / Nova Micro). Using a model ID that
# is neither in the catalogue nor in any healthy set proves the invariant's two
# branches are genuinely distinct: an accepted Jev choice must be a *healthy
# catalogue* member, while a fallback surfaces exactly the Custom decision.
FALLBACK_MODEL_ID = "test.custom-only-fallback-model-v1:0"
FALLBACK_PROVIDER = "nova"


# --------------------------------------------------------------------------- #
# Minimal Custom_Router decision + provider.
# --------------------------------------------------------------------------- #
@dataclass
class _FakeProvider:
    value: str


@dataclass
class _FakeCustomDecision:
    """A stand-in for router.RoutingDecision with just the fields route() reads."""

    selected_model_id: str
    selected_provider: _FakeProvider
    confidence_score: float = 0.5
    decision_reasoning: List[str] = field(default_factory=lambda: ["custom reasoning"])


def _custom_provider() -> _FakeCustomDecision:
    """Return a deterministic Custom_Router fallback decision."""
    return _FakeCustomDecision(
        selected_model_id=FALLBACK_MODEL_ID,
        selected_provider=_FakeProvider(FALLBACK_PROVIDER),
    )


# --------------------------------------------------------------------------- #
# Minimal router object for JevRouter (only model_capabilities / query_analyzer
# are read, and only when a Jev call is actually built -- which we bypass by
# patching call_jev, so an empty capability map is enough).
# --------------------------------------------------------------------------- #
@dataclass
class _Capability:
    provider: _FakeProvider


class _FakeRouter:
    def __init__(self) -> None:
        # Provider lookup for an accepted catalogue choice.
        self.model_capabilities: Dict[str, _Capability] = {
            model_id: _Capability(_FakeProvider("prov-" + model_id[:4]))
            for model_id in CANDIDATE_CATALOGUE
        }
        self.query_analyzer = None


# --------------------------------------------------------------------------- #
# Translate a tagged-dict outcome into the real value route() will consume.
# --------------------------------------------------------------------------- #
def _to_real_outcome(outcome: Dict[str, Any]):
    """Map a jev_outcomes() tagged dict to (configured, JevOutcome | None)."""
    kind = outcome["kind"]
    if kind == "not_configured":
        # Not configured: no call is made, the outcome is None.
        return False, None
    if kind == "error":
        return True, JevError(
            category=outcome["category"],
            status_code=outcome["status_code"],
        )
    if kind == "answer":
        return True, JevAnswer(
            choice=outcome["choice"],
            probabilities=dict(outcome["probabilities"]),
            confidence=outcome["confidence"],
            high_consequence=outcome["high_consequence"],
            model_version=outcome["model_version"],
        )
    raise AssertionError(f"unexpected outcome kind: {kind!r}")


# --------------------------------------------------------------------------- #
# Property 7.
# --------------------------------------------------------------------------- #
@settings(max_examples=400)
@given(
    outcome=jev_outcomes(),
    healthy=health_states(),
    threshold=st.floats(
        min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False
    ),
    configured_flag=st.booleans(),
)
def test_final_route_is_healthy_catalogue_member_or_fallback(
    outcome: Dict[str, Any],
    healthy: FrozenSet[str],
    threshold: float,
    configured_flag: bool,
) -> None:
    """The router's result is a healthy catalogue model or the declared Fallback.

    Quantifies over every outcome kind (answer / error / not configured), every
    choice string, confidence, probability map, error category, and every health
    subset, plus a free ``configured`` flag. ``not_configured`` always forces
    ``configured=False``; for other outcomes the generated flag decides whether
    the Jev answer is even consulted, exercising the no-call branch for answers
    and errors too.
    """
    want_configured, real_outcome = _to_real_outcome(outcome)
    # The sentinel pins configured False; otherwise the generated flag drives it
    # so the "configured but no usable call" path is also covered.
    configured = want_configured and configured_flag

    mode = "live"

    def _fake_jev_status() -> Dict[str, Any]:
        return {"configured": configured, "mode": mode}

    # Hand route() the generated outcome directly instead of making an HTTP call.
    def _fake_call_jev(*args: Any, **kwargs: Any):
        return real_outcome

    router = JevRouter(_FakeRouter())
    snapshot = HealthSnapshot(healthy_models=healthy)

    # A per-example monkeypatch context: the @given fixture is not reset between
    # generated inputs, so patches are applied and undone inside each example.
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(jev_router, "jev_status", _fake_jev_status)
        mp.setattr(jev_router, "get_jev_key", lambda: "in-memory-test-key")
        mp.setattr(jev_router, "call_jev", _fake_call_jev)
        # Pin the threshold deterministically for this example.
        mp.setattr(jev_router, "get_confidence_threshold", lambda: threshold)

        result = router.route(
            query_text="any query text",
            snapshot=snapshot,
            custom_provider=_custom_provider,
        )

    catalogue = set(CANDIDATE_CATALOGUE)

    if result.fallback:
        # ---- Declared Fallback branch -------------------------------------
        assert result.fallback is True
        assert result.fallback_reason is not None
        assert result.router_used == "custom"
        # The returned model is exactly the Custom_Router's fallback decision.
        assert result.model_id == FALLBACK_MODEL_ID
        # And therefore never a healthy catalogue member masquerading as a Jev
        # acceptance (the fallback model is deliberately outside the catalogue).
        assert result.model_id not in catalogue
    else:
        # ---- Accepted Jev choice branch -----------------------------------
        assert result.fallback is False
        assert result.fallback_reason is None
        assert result.router_used == "jev"
        # The route must be a *healthy* member of the Candidate_Catalogue.
        assert result.model_id in catalogue, (
            f"accepted model {result.model_id!r} is not in the catalogue"
        )
        assert result.model_id in healthy, (
            f"accepted model {result.model_id!r} is not healthy"
        )
        # Never a model Jev invented: an accepted choice is a catalogue member,
        # which by construction excludes any arbitrary choice string.
        assert result.model_id != FALLBACK_MODEL_ID

    # The invariant holds for every case regardless of branch: the final model is
    # either a healthy catalogue member or the declared fallback model.
    healthy_catalogue = catalogue & set(healthy)
    assert (result.model_id in healthy_catalogue) or (
        result.fallback and result.model_id == FALLBACK_MODEL_ID
    )

    # Confidence is always a valid probability.
    assert 0.0 <= result.confidence <= 1.0
