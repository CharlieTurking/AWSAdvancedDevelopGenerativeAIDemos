"""Property test for fallback-indicator consistency in the Jev_Router.

Feature: jev-router-comparison, Property 12: Fallback indicator and
``router_used`` agree.

For ANY ``JevRouter.route`` result -- across every Jev outcome (any model ID
choice, any confidence, any probability map, any error category, or "not
configured") and ANY combination of model health states -- the two signals the
response exposes must stay in lock step:

* ``result.fallback`` is True  iff  ``result.router_used == "custom"``  and
  ``result.fallback_reason`` is not None; and
* ``result.fallback`` is False iff  ``result.router_used == "jev"``     and
  ``result.fallback_reason`` is None.

In other words the two booleans are each other's negation: a route is either an
accepted Jev decision (``router_used == "jev"``, no fallback, no reason) or a
declared Fallback to the Custom_Router (``router_used == "custom"``, fallback,
with a reason). There is no third state and the flags never disagree.

The test quantifies over the full outcome space using the shared Hypothesis
generators ``jev_outcomes()`` and ``health_states()`` from tests/strategies.py,
mapping the tagged-dict outcomes into the real ``JevAnswer`` / ``JevError`` /
``None`` values the router consumes, and driving ``configured`` accordingly
(the "not configured" sentinel means ``configured=False`` and no Jev call).
It drives ``JevRouter.route`` exactly as test_prop_route_invariant.py does: a
fake router (``model_capabilities`` / ``query_analyzer``), a ``custom_provider``
returning a fake Custom_Router decision, and per-example monkeypatching of
``jev_router.jev_status``, ``get_jev_key``, ``call_jev``, and
``get_confidence_threshold`` via ``pytest.MonkeyPatch.context()``.

Validates: Requirements 4.7, 4.8.
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

from strategies import health_states, jev_outcomes


# --------------------------------------------------------------------------- #
# A Custom_Router fallback model that is deliberately outside the catalogue, so
# an accepted Jev choice and a Fallback are clearly distinguishable.
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# Minimal router object for JevRouter. Only model_capabilities / query_analyzer
# are read, and only when a Jev call is actually built -- which the test bypasses
# by patching call_jev, so an empty capability map is enough.
# --------------------------------------------------------------------------- #
@dataclass
class _Capability:
    provider: _FakeProvider


class _FakeRouter:
    def __init__(self) -> None:
        self.model_capabilities: Dict[str, _Capability] = {
            model_id: _Capability(_FakeProvider("prov-" + model_id[:4]))
            for model_id in CANDIDATE_CATALOGUE
        }
        self.query_analyzer = None


# --------------------------------------------------------------------------- #
# Translate a tagged-dict outcome into (configured, JevOutcome | None).
# --------------------------------------------------------------------------- #
def _to_real_outcome(outcome: Dict[str, Any]):
    """Map a jev_outcomes() tagged dict to (configured, JevOutcome | None)."""
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


# --------------------------------------------------------------------------- #
# Property 12.
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
def test_fallback_indicator_and_router_used_agree(
    outcome: Dict[str, Any],
    healthy: FrozenSet[str],
    threshold: float,
    configured_flag: bool,
) -> None:
    """``fallback`` is True iff ``router_used`` is ``custom``; False iff ``jev``.

    Quantifies over every outcome kind (answer / error / not configured), every
    choice string, confidence, probability map, error category, every health
    subset, every threshold in [0, 1], and a free ``configured`` flag. The
    ``not_configured`` sentinel always forces ``configured=False``; for other
    outcomes the generated flag decides whether the Jev answer is consulted,
    exercising the no-call branch for answers and errors too.
    """
    want_configured, real_outcome = _to_real_outcome(outcome)
    configured = want_configured and configured_flag

    mode = "live"

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

    # router_used is one of exactly the two declared values.
    assert result.router_used in ("custom", "jev"), (
        f"router_used must be 'custom' or 'jev', got {result.router_used!r}"
    )

    # The biconditional at the heart of Property 12: the two signals agree.
    assert (result.fallback is True) == (result.router_used == "custom"), (
        f"fallback={result.fallback!r} disagrees with "
        f"router_used={result.router_used!r}"
    )
    assert (result.fallback is False) == (result.router_used == "jev"), (
        f"fallback={result.fallback!r} disagrees with "
        f"router_used={result.router_used!r}"
    )

    # fallback_reason tracks the indicator: present exactly on a fallback.
    if result.fallback:
        assert result.router_used == "custom"
        assert result.fallback_reason is not None, (
            "a fallback must name a fallback_reason"
        )
    else:
        assert result.router_used == "jev"
        assert result.fallback_reason is None, (
            "an accepted Jev decision must have no fallback_reason"
        )
