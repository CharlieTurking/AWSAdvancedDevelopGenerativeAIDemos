"""Property test (and example) for recorded-mode recording lookups.

Feature: jev-router-comparison, Property 18: An unmatched recording falls back.

In recorded mode (``jev_status`` reports ``configured=True, mode="recorded"``),
``JevRouter.route`` does NOT call the live transport -- it looks a recording up
through ``jev_client.load_recording``. This test drives the router in recorded
mode and asserts two things:

* Property 18 (miss): for ANY query, when ``load_recording`` reports that no
  recording matched (a ``JevError`` tagged ``no_recording``), the router falls
  back to the Custom_Router. The result has ``fallback=True``,
  ``router_used="custom"``, and reasoning that states no recording matched.
  No live Jev call is ever made.  **Validates: Requirements 15.5**

* Example (hit, Requirement 15.1): when a matching recording exists,
  ``load_recording`` returns the recorded ``JevAnswer`` and the router accepts
  it (``router_used="jev"``, ``mode == "recorded"``) -- again with NO transport
  / HTTP call.

The recording lookup itself is exercised by the client-level tests; here we
monkeypatch ``jev_router.load_recording`` so the property quantifies over the
router's handling of a miss vs a hit, and ``jev_router.call_jev`` is replaced
with a fail-if-called sentinel so any attempt to reach the network fails the
test loudly (the recorded path must never call it).

Validates: Requirements 15.1, 15.5.
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

from strategies import CATALOGUE_IDS, health_states, queries


# --------------------------------------------------------------------------- #
# A Custom_Router fallback decision outside the catalogue, so a fallback is
# unambiguously distinguishable from an accepted Jev choice.
# --------------------------------------------------------------------------- #
FALLBACK_MODEL_ID = "test.custom-only-fallback-model-v1:0"
FALLBACK_PROVIDER = "nova"


@dataclass
class _FakeProvider:
    value: str


@dataclass
class _FakeCustomDecision:
    """Stand-in for router.RoutingDecision with the fields route() reads."""

    selected_model_id: str
    selected_provider: _FakeProvider
    confidence_score: float = 0.5
    decision_reasoning: List[str] = field(default_factory=lambda: ["custom reasoning"])


def _custom_provider() -> _FakeCustomDecision:
    return _FakeCustomDecision(
        selected_model_id=FALLBACK_MODEL_ID,
        selected_provider=_FakeProvider(FALLBACK_PROVIDER),
    )


@dataclass
class _Capability:
    provider: _FakeProvider


class _FakeRouter:
    """Minimal router: only model_capabilities / query_analyzer are read."""

    def __init__(self) -> None:
        self.model_capabilities: Dict[str, _Capability] = {
            model_id: _Capability(_FakeProvider("prov-" + model_id[:4]))
            for model_id in CANDIDATE_CATALOGUE
        }
        self.query_analyzer = None


def _fail_if_called(*args: Any, **kwargs: Any):
    """Transport/HTTP sentinel: recorded mode must never call Jev live."""
    raise AssertionError(
        "call_jev was invoked in recorded mode, but no live Jev call is allowed"
    )


def _recorded_status() -> Dict[str, Any]:
    return {"configured": True, "mode": "recorded"}


# --------------------------------------------------------------------------- #
# Property 18: an unmatched recording falls back.
# --------------------------------------------------------------------------- #
@settings(max_examples=300)
@given(
    query=queries(),
    healthy=health_states(),
    threshold=st.floats(
        min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False
    ),
)
def test_unmatched_recording_falls_back(
    query: str,
    healthy: FrozenSet[str],
    threshold: float,
) -> None:
    """A recording miss falls back and states that no recording matched.

    For every query and every health state, when ``load_recording`` reports a
    ``no_recording`` miss the router must use the Custom_Router fallback: the
    result is a declared fallback (``fallback=True``, ``router_used="custom"``,
    ``fallback_reason`` present, ``model_id`` the Custom decision) whose
    reasoning states that no recording matched. The live transport is never
    touched.
    """
    def _miss(_query: str) -> JevError:
        # Exactly what jev_client.load_recording returns on a miss.
        return JevError("invalid_response", detail="no_recording")

    router = JevRouter(_FakeRouter())
    snapshot = HealthSnapshot(healthy_models=healthy)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(jev_router, "jev_status", _recorded_status)
        mp.setattr(jev_router, "load_recording", _miss)
        # The recorded path must not reach the network / secret at all.
        mp.setattr(jev_router, "call_jev", _fail_if_called)
        mp.setattr(jev_router, "get_jev_key", _fail_if_called)
        mp.setattr(jev_router, "get_confidence_threshold", lambda: threshold)

        result = router.route(
            query_text=query,
            snapshot=snapshot,
            custom_provider=_custom_provider,
        )

    # Declared fallback to the Custom_Router.
    assert result.fallback is True
    assert result.router_used == "custom"
    assert result.fallback_reason is not None
    assert result.model_id == FALLBACK_MODEL_ID
    assert result.model_id not in set(CANDIDATE_CATALOGUE)

    # The result is still labelled recorded (the mode the request ran in).
    assert result.mode == "recorded"

    # The reasoning states that no recording matched. The policy surfaces the
    # ``no_recording`` detail; accept either the tagged form or the spaced
    # phrasing so the assertion tracks intent, not an exact string.
    reasoning_text = " ".join(result.reasoning).lower()
    assert ("no_recording" in reasoning_text) or ("no recording" in reasoning_text), (
        f"reasoning does not state that no recording matched: {result.reasoning!r}"
    )


# --------------------------------------------------------------------------- #
# Example (Requirement 15.1): a matching recording returns the recorded answer
# with NO transport / HTTP call.
# --------------------------------------------------------------------------- #
def test_matching_recording_returns_recorded_answer_no_transport() -> None:
    """A recording hit is accepted as a Jev decision, with no live call.

    ``load_recording`` returns a recorded ``JevAnswer`` for the (healthy)
    catalogue model; the router accepts it (``router_used="jev"``), reports
    ``mode == "recorded"``, surfaces the recorded confidence/probabilities, and
    never calls the live transport.
    """
    recorded_choice = CATALOGUE_IDS[0]  # Claude Haiku 4.5
    recorded_answer = JevAnswer(
        choice=recorded_choice,
        probabilities={recorded_choice: 0.92},
        confidence=0.92,
        high_consequence=None,
        model_version="jev-1.13.0",
    )

    def _hit(_query: str) -> JevAnswer:
        return recorded_answer

    # The chosen model is healthy so the policy accepts it directly.
    snapshot = HealthSnapshot(healthy_models=frozenset(CANDIDATE_CATALOGUE))
    router = JevRouter(_FakeRouter())

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(jev_router, "jev_status", _recorded_status)
        mp.setattr(jev_router, "load_recording", _hit)
        # Prove no live call happens: any transport/secret access fails the test.
        mp.setattr(jev_router, "call_jev", _fail_if_called)
        mp.setattr(jev_router, "get_jev_key", _fail_if_called)
        mp.setattr(jev_router, "get_confidence_threshold", lambda: 0.6)

        result = router.route(
            query_text="which model should answer this?",
            snapshot=snapshot,
            custom_provider=_custom_provider,
        )

    # Accepted Jev decision from the recording.
    assert result.fallback is False
    assert result.fallback_reason is None
    assert result.router_used == "jev"
    assert result.model_id == recorded_choice
    assert result.mode == "recorded"

    # The recorded answer's figures are surfaced.
    assert result.jev_confidence == pytest.approx(0.92)
    assert result.probabilities.get(recorded_choice) == pytest.approx(0.92)
    assert result.confidence == pytest.approx(0.92)
