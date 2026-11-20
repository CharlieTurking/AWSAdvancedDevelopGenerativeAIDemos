"""Property test for the completeness and validity of a Jev routing result.

Feature: jev-router-comparison, Property 13: Routing results are complete and
valid.

For ANY Jev outcome (a valid answer, a categorised error, or "not configured")
and ANY combination of model health states, ``JevRouter.route`` returns a
``RoutingResult`` that is fully populated and internally consistent:

* ``model_id`` is a non-empty string;
* ``provider`` is a string;
* ``confidence`` is a float in [0.0, 1.0];
* ``latency_ms`` is an int >= 0;
* ``reasoning`` is a non-empty list of strings;
* ``router_used`` is one of {"custom", "jev"};
* ``mode`` is one of {"live", "recorded"};
* ``probabilities`` is a dict (empty when Jev gave no usable answer);
* when the router actually consumed a Jev answer, ``probabilities`` equals that
  answer's probabilities and ``jev_confidence`` is set to the answer's
  confidence; and
* the reasoning records whether the decision came from Jev or from the Fallback
  (Requirement 5.4) -- exactly the branch indicated by ``router_used`` /
  ``fallback``.

The test quantifies over the full outcome space with the shared Hypothesis
generators ``jev_outcomes()`` and ``health_states()`` from tests/strategies.py,
mapping the tagged-dict outcomes into the real ``JevAnswer`` / ``JevError`` /
``None`` values the router consumes, and driving ``configured`` with a free
flag (the "not configured" sentinel always forces ``configured=False``). The
driving harness -- fake router, custom_provider, per-example monkeypatch of
``jev_status`` / ``get_jev_key`` / ``call_jev`` / ``get_confidence_threshold``
-- mirrors tests/test_prop_route_invariant.py.

Validates: Requirements 5.1, 5.2, 5.4, 2.4.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import jev_router
from jev_router import CANDIDATE_CATALOGUE, HealthSnapshot, JevRouter, RoutingResult
from jev_client import JevAnswer, JevError

from strategies import health_states, jev_outcomes


# --------------------------------------------------------------------------- #
# A Custom_Router fallback decision outside the catalogue (see route_invariant).
# --------------------------------------------------------------------------- #
FALLBACK_MODEL_ID = "test.custom-only-fallback-model-v1:0"
FALLBACK_PROVIDER = "nova"


@dataclass
class _FakeProvider:
    value: str


@dataclass
class _FakeCustomDecision:
    """Stand-in for router.RoutingDecision with just the fields route() reads."""

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


@dataclass
class _Capability:
    provider: _FakeProvider


class _FakeRouter:
    """Minimal router: only model_capabilities is read on an accepted choice."""

    def __init__(self) -> None:
        self.model_capabilities: Dict[str, _Capability] = {
            model_id: _Capability(_FakeProvider("prov-" + model_id[:4]))
            for model_id in CANDIDATE_CATALOGUE
        }
        self.query_analyzer = None


# --------------------------------------------------------------------------- #
# Translate a tagged-dict outcome into the real value route() will consume.
# --------------------------------------------------------------------------- #
def _to_real_outcome(outcome: Dict[str, Any]):
    """Map a jev_outcomes() tagged dict to (want_configured, JevOutcome | None)."""
    kind = outcome["kind"]
    if kind == "not_configured":
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


def _mentions_jev(reasoning: List[str]) -> bool:
    """True when the reasoning records the decision came from Jev."""
    return any("Decision came from Jev." == line for line in reasoning)


def _mentions_fallback(reasoning: List[str]) -> bool:
    """True when the reasoning records a fallback to the Custom_Router."""
    return any("Fallback to the custom router" in line for line in reasoning)


# --------------------------------------------------------------------------- #
# Property 13.
# --------------------------------------------------------------------------- #
@settings(max_examples=400)
@given(
    outcome=jev_outcomes(),
    healthy=health_states(),
    threshold=st.floats(
        min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False
    ),
    configured_flag=st.booleans(),
    mode=st.sampled_from(["live", "recorded"]),
)
def test_routing_result_is_complete_and_valid(
    outcome: Dict[str, Any],
    healthy: FrozenSet[str],
    threshold: float,
    configured_flag: bool,
    mode: str,
) -> None:
    """Every routing result is fully populated, valid, and self-consistent.

    Quantifies over every outcome kind (answer / error / not configured), every
    choice, confidence, probability map, and error category, every health
    subset, a free ``configured`` flag, and both reporting modes.
    """
    want_configured, real_outcome = _to_real_outcome(outcome)
    configured = want_configured and configured_flag

    def _fake_jev_status() -> Dict[str, Any]:
        return {"configured": configured, "mode": mode}

    def _fake_call_jev(*args: Any, **kwargs: Any):
        return real_outcome

    router = JevRouter(_FakeRouter())
    snapshot = HealthSnapshot(healthy_models=healthy)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(jev_router, "jev_status", _fake_jev_status)
        mp.setattr(jev_router, "get_jev_key", lambda: "in-memory-test-key")
        mp.setattr(jev_router, "call_jev", _fake_call_jev)
        mp.setattr(jev_router, "get_confidence_threshold", lambda: threshold)

        result = router.route(
            query_text="any query text",
            snapshot=snapshot,
            custom_provider=_custom_provider,
        )

    # Whether the router actually consumed OUR generated Jev answer. The router
    # only consults the patched ``call_jev`` in live mode; in recorded mode it
    # instead calls ``load_recording`` (which misses here and yields an error),
    # so our generated answer is not the outcome the policy sees. Hence an
    # answer is consumed only when configured AND live AND the outcome is an
    # answer. Errors and the not-configured sentinel never populate
    # probabilities / jev_confidence.
    consumed_answer: Optional[JevAnswer] = (
        real_outcome
        if configured and mode == "live" and isinstance(real_outcome, JevAnswer)
        else None
    )

    # ---- Core completeness / validity --------------------------------------
    assert isinstance(result, RoutingResult)

    assert isinstance(result.model_id, str)
    assert result.model_id != "", "model_id must be a non-empty string"

    assert isinstance(result.provider, str)

    assert isinstance(result.confidence, float)
    assert 0.0 <= result.confidence <= 1.0

    assert isinstance(result.latency_ms, int)
    assert not isinstance(result.latency_ms, bool)
    assert result.latency_ms >= 0

    assert isinstance(result.reasoning, list)
    assert len(result.reasoning) >= 1, "reasoning must be non-empty"
    assert all(isinstance(line, str) for line in result.reasoning)

    assert result.router_used in {"custom", "jev"}
    assert result.mode in {"live", "recorded"}
    # The router echoes the mode reported by jev_status unchanged.
    assert result.mode == mode

    assert isinstance(result.probabilities, dict)
    assert all(isinstance(k, str) for k in result.probabilities)
    assert all(isinstance(v, float) for v in result.probabilities.values())

    # ---- Reasoning records the decision origin (Req 5.4) -------------------
    if result.fallback:
        assert result.router_used == "custom"
        assert _mentions_fallback(result.reasoning), (
            "a fallback result must record the fallback in its reasoning"
        )
        assert not _mentions_jev(result.reasoning)
    else:
        assert result.router_used == "jev"
        assert _mentions_jev(result.reasoning), (
            "an accepted Jev result must record that the decision came from Jev"
        )
        assert not _mentions_fallback(result.reasoning)

    # ---- Jev-answer bookkeeping --------------------------------------------
    if consumed_answer is not None:
        # The result's probabilities equal Jev's probabilities (a copy, same data).
        assert result.probabilities == consumed_answer.probabilities
        # jev_confidence reflects what Jev reported, even when the answer was rejected.
        assert result.jev_confidence == consumed_answer.confidence
        assert result.high_consequence == consumed_answer.high_consequence
    else:
        # No usable Jev answer: probabilities is an empty dict and no jev_confidence.
        assert result.probabilities == {}
        assert result.jev_confidence is None
        assert result.high_consequence is None


# --------------------------------------------------------------------------- #
# Example: an accepted Jev choice carries the full, valid shape (5.1, 5.2, 2.4).
# --------------------------------------------------------------------------- #
def test_accepted_jev_choice_is_complete() -> None:
    """A concrete accepted answer yields a complete, Jev-sourced result."""
    chosen = CANDIDATE_CATALOGUE[0]
    answer = JevAnswer(
        choice=chosen,
        probabilities={chosen: 0.9},
        confidence=0.95,
        high_consequence=0.1,
        model_version="jev-1.13.0",
    )

    router = JevRouter(_FakeRouter())
    snapshot = HealthSnapshot(healthy_models=frozenset({chosen}))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            jev_router,
            "jev_status",
            lambda: {"configured": True, "mode": "live"},
        )
        mp.setattr(jev_router, "get_jev_key", lambda: "in-memory-test-key")
        mp.setattr(jev_router, "call_jev", lambda *a, **k: answer)
        mp.setattr(jev_router, "get_confidence_threshold", lambda: 0.6)

        result = router.route(
            query_text="hello",
            snapshot=snapshot,
            custom_provider=_custom_provider,
        )

    assert result.fallback is False
    assert result.router_used == "jev"
    assert result.model_id == chosen
    assert result.provider == "prov-" + chosen[:4]
    assert result.probabilities == {chosen: 0.9}
    assert result.jev_confidence == 0.95
    assert result.high_consequence == 0.1
    assert 0.0 <= result.confidence <= 1.0
    assert result.latency_ms >= 0
    assert _mentions_jev(result.reasoning)


# --------------------------------------------------------------------------- #
# Example: a fallback keeps the Jev probabilities for the UI while routing to
# the Custom_Router model (2.4 - the result is complete on both branches).
# --------------------------------------------------------------------------- #
def test_fallback_result_is_complete_and_keeps_jev_probabilities() -> None:
    """A rejected (low-confidence) answer still produces a complete result."""
    chosen = CANDIDATE_CATALOGUE[0]
    answer = JevAnswer(
        choice=chosen,
        probabilities={chosen: 0.2},
        confidence=0.1,  # below threshold -> fallback
        high_consequence=None,
        model_version=None,
    )

    router = JevRouter(_FakeRouter())
    snapshot = HealthSnapshot(healthy_models=frozenset({chosen}))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            jev_router,
            "jev_status",
            lambda: {"configured": True, "mode": "live"},
        )
        mp.setattr(jev_router, "get_jev_key", lambda: "in-memory-test-key")
        mp.setattr(jev_router, "call_jev", lambda *a, **k: answer)
        mp.setattr(jev_router, "get_confidence_threshold", lambda: 0.6)

        result = router.route(
            query_text="hello",
            snapshot=snapshot,
            custom_provider=_custom_provider,
        )

    assert result.fallback is True
    assert result.router_used == "custom"
    assert result.model_id == FALLBACK_MODEL_ID
    assert isinstance(result.provider, str)
    # The rejected answer's probabilities are retained so the UI can show why.
    assert result.probabilities == {chosen: 0.2}
    assert result.jev_confidence == 0.1
    assert result.reasoning and all(isinstance(x, str) for x in result.reasoning)
    assert _mentions_fallback(result.reasoning)
