"""Unit tests for Jev_Router edge cases.

Feature: jev-router-comparison, task 3.12.

These example-based unit tests complement the property tests by pinning down three
specific edge behaviours of ``JevRouter.route``:

* **All candidates unhealthy (Req 4.10).** When the policy decides a Fallback and the
  injected ``custom_provider`` (standing in for the Custom_Router) raises the "no healthy
  models" ``RuntimeError`` the real Custom_Router raises in that condition, ``route`` must
  propagate that *same* error unchanged - same type and same message. The exact message
  string is taken from ``lambda/router.py`` (``"No healthy models available for
  routing"``); this test asserts the router re-raises it verbatim.

* **Decision logging (Req 11.1, 11.3).** On a normal route exactly one summary line is
  emitted, and it carries the mode, chosen model, confidence, latency, the fallback flag,
  and the query *length* (never the query text). On a client error an additional line logs
  the error category and status code and never the request headers. Assertions run over
  the formatted log text captured by the ``log_capture`` fixture.

* **Latency excludes post-decision work (Req 5.3).** ``latency_ms`` must measure only from
  the start of the Jev call through the Routing_Policy decision, not any work done after
  the ``RoutingResult`` is built. A fake monotonic clock is injected by monkeypatching
  ``jev_router.time.monotonic`` so the elapsed span the router records is fully controlled
  and independent of wall-clock work; the test asserts the recorded latency reflects only
  the decision window and is a non-negative integer.

The router is driven with the same fake-router + ``custom_provider`` + monkeypatch pattern
used by ``tests/test_prop_route_invariant.py``: ``jev_status``, ``get_jev_key``, and
``call_jev`` are patched so no HTTP call and no real secret read happens.

Validates: Requirements 4.10, 5.3, 11.1, 11.3.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

import pytest

import jev_router
from jev_router import CANDIDATE_CATALOGUE, HealthSnapshot, JevRouter
from jev_client import JevAnswer, JevError


# The exact message the Custom_Router raises when no healthy model exists, copied
# verbatim from lambda/router.py (``raise RuntimeError("No healthy models available
# for routing")``). route() must propagate this unchanged on a fallback.
NO_HEALTHY_MESSAGE = "No healthy models available for routing"


# --------------------------------------------------------------------------- #
# Minimal Custom_Router decision + providers.
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


def _raising_custom_provider() -> _FakeCustomDecision:
    """A Custom_Router provider that raises the real "no healthy models" error.

    Mirrors the Custom_Router's behaviour when every candidate is unhealthy: the
    exact ``RuntimeError`` from router.py. route() must re-raise it unchanged.
    """
    raise RuntimeError(NO_HEALTHY_MESSAGE)


def _custom_provider() -> _FakeCustomDecision:
    """A deterministic, non-raising Custom_Router fallback decision."""
    return _FakeCustomDecision(
        selected_model_id="amazon.nova-lite-v1:0",
        selected_provider=_FakeProvider("nova"),
    )


# --------------------------------------------------------------------------- #
# Minimal router object for JevRouter. model_capabilities / query_analyzer are
# only read when a real Jev call is built, which these tests bypass by patching
# call_jev, so a simple capability map is enough for provider lookups.
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


def _answer(choice: str, confidence: float) -> JevAnswer:
    """Build a JevAnswer that names ``choice`` as the single candidate."""
    return JevAnswer(
        choice=choice,
        probabilities={choice: confidence},
        confidence=confidence,
        high_consequence=None,
        model_version="jev-1.13.0",
    )


def _patch_live_configured(mp: pytest.MonkeyPatch, *, threshold: float) -> None:
    """Patch the Jev edge so route() runs live-configured without any HTTP/secret I/O."""
    mp.setattr(
        jev_router,
        "jev_status",
        lambda: {"configured": True, "mode": "live"},
    )
    mp.setattr(jev_router, "get_jev_key", lambda: "in-memory-test-key")
    mp.setattr(jev_router, "get_confidence_threshold", lambda: threshold)


# --------------------------------------------------------------------------- #
# Req 4.10: all candidates unhealthy -> propagate the Custom_Router error.
# --------------------------------------------------------------------------- #
def test_all_candidates_unhealthy_propagates_custom_router_error() -> None:
    """When the fallback provider raises "no healthy models", route() re-raises it.

    Health snapshot is empty (every candidate unhealthy), and Jev returns a confident
    catalogue choice. The policy cannot accept an unhealthy model and must fall back;
    the fallback provider then raises the Custom_Router's ``RuntimeError``. route() must
    propagate that exact error - same type and same message - unchanged (Req 4.10).
    """
    router = JevRouter(_FakeRouter())
    snapshot = HealthSnapshot(healthy_models=frozenset())  # nothing healthy
    chosen = CANDIDATE_CATALOGUE[0]

    with pytest.MonkeyPatch.context() as mp:
        _patch_live_configured(mp, threshold=0.6)
        mp.setattr(jev_router, "call_jev", lambda *a, **k: _answer(chosen, 0.95))

        with pytest.raises(RuntimeError) as excinfo:
            router.route(
                query_text="any query text",
                snapshot=snapshot,
                custom_provider=_raising_custom_provider,
            )

    # Same type (RuntimeError, not a subclass or a re-wrapped exception) and the exact
    # message the Custom_Router uses in router.py - propagated unchanged.
    assert type(excinfo.value) is RuntimeError
    assert str(excinfo.value) == NO_HEALTHY_MESSAGE


# --------------------------------------------------------------------------- #
# Req 11.1: exactly one summary line on a normal (accepted) route.
# --------------------------------------------------------------------------- #
def test_normal_route_emits_single_summary_line_with_required_fields(
    log_capture: Any,
) -> None:
    """A normal accepted route logs exactly one summary line with all required fields.

    The summary line must contain the mode, chosen model, confidence, latency, the
    fallback flag, and the query length (not the text). On a successful (non-error)
    route there is no error line, so exactly one Jev summary line is emitted (Req 11.1).
    """
    router = JevRouter(_FakeRouter())
    chosen = CANDIDATE_CATALOGUE[0]
    snapshot = HealthSnapshot(healthy_models=frozenset({chosen}))
    query = "summarise the quarterly report"

    with pytest.MonkeyPatch.context() as mp:
        _patch_live_configured(mp, threshold=0.6)
        mp.setattr(jev_router, "call_jev", lambda *a, **k: _answer(chosen, 0.9))

        result = router.route(
            query_text=query,
            snapshot=snapshot,
            custom_provider=_custom_provider,
        )

    assert result.router_used == "jev"
    assert result.fallback is False

    summary_lines = [ln for ln in log_capture.lines if "Jev route summary" in ln]
    assert len(summary_lines) == 1, (
        f"expected exactly one summary line, got {summary_lines!r}"
    )
    summary = summary_lines[0]

    # Required fields: mode, model, confidence, latency, fallback flag, query length.
    assert "mode=live" in summary
    assert f"model={chosen}" in summary
    assert "confidence=" in summary
    assert "latency_ms=" in summary
    assert "fallback=False" in summary
    assert f"query_len={len(query)}" in summary

    # Privacy: the query text itself is never logged, only its length.
    assert query not in log_capture.text

    # A successful route logs no error detail line.
    assert not any("Jev route error detail" in ln for ln in log_capture.lines)


# --------------------------------------------------------------------------- #
# Req 11.3: on a client error, an extra line logs category + status, no headers.
# --------------------------------------------------------------------------- #
def test_client_error_logs_category_and_status_without_headers(
    log_capture: Any,
) -> None:
    """A Jev client error adds a line naming the category and HTTP status, no headers.

    When call_jev reports a categorised ``JevError`` the router falls back, and in
    addition to the summary line it logs the error category and status code. The request
    headers (notably the ``Authorization`` / Bearer header) must never appear (Req 11.3).
    """
    router = JevRouter(_FakeRouter())
    chosen = CANDIDATE_CATALOGUE[0]
    snapshot = HealthSnapshot(healthy_models=frozenset({chosen}))
    query = "translate this paragraph"

    error = JevError(category="http_error", status_code=503, detail="server")

    with pytest.MonkeyPatch.context() as mp:
        _patch_live_configured(mp, threshold=0.6)
        mp.setattr(jev_router, "call_jev", lambda *a, **k: error)

        result = router.route(
            query_text=query,
            snapshot=snapshot,
            custom_provider=_custom_provider,
        )

    # The error forces a fallback.
    assert result.fallback is True
    assert result.fallback_reason == "http_error"
    assert result.router_used == "custom"

    summary_lines = [ln for ln in log_capture.lines if "Jev route summary" in ln]
    error_lines = [ln for ln in log_capture.lines if "Jev route error detail" in ln]
    assert len(summary_lines) == 1
    assert len(error_lines) == 1, (
        f"expected exactly one error detail line, got {error_lines!r}"
    )

    error_line = error_lines[0]
    assert "category=http_error" in error_line
    assert "status_code=503" in error_line

    # No headers / Authorization material anywhere in the captured output.
    text_lower = log_capture.text.lower()
    assert "authorization" not in text_lower
    assert "bearer" not in text_lower
    assert "in-memory-test-key" not in log_capture.text


# --------------------------------------------------------------------------- #
# Req 5.3: latency spans only the Jev call through the policy decision.
# --------------------------------------------------------------------------- #
class _FakeClock:
    """A controllable monotonic clock.

    ``tick`` advances the clock by a fixed step on every read. The first read (the
    router's ``start = time.monotonic()``) and the read at the latency measurement
    point (after the policy decision) differ by exactly one step, so the recorded
    latency is deterministic and independent of real wall-clock time. After the
    router stops reading the clock, any further ``advance`` calls - standing in for
    work done after the RoutingResult is built - must not change the recorded latency.
    """

    def __init__(self, step: float) -> None:
        self._now = 0.0
        self._step = step
        self.reads = 0

    def monotonic(self) -> float:
        self.reads += 1
        value = self._now
        self._now += self._step
        return value

    def advance(self, seconds: float) -> None:
        """Advance the clock as if post-decision work had taken ``seconds``."""
        self._now += seconds


def test_latency_measures_only_up_to_the_decision(log_capture: Any) -> None:
    """latency_ms reflects only the decision window, not post-decision work (Req 5.3).

    A fake monotonic clock advances by a fixed 0.25 s per read. The router reads the
    clock once at the start and once at the latency measurement point, so the recorded
    latency is exactly one step (250 ms) regardless of any later work. The test then
    advances the fake clock by a large amount - simulating slow post-decision work - and
    confirms the already-recorded ``latency_ms`` does not grow.
    """
    step_seconds = 0.25
    clock = _FakeClock(step=step_seconds)

    router = JevRouter(_FakeRouter())
    chosen = CANDIDATE_CATALOGUE[0]
    snapshot = HealthSnapshot(healthy_models=frozenset({chosen}))

    with pytest.MonkeyPatch.context() as mp:
        _patch_live_configured(mp, threshold=0.6)
        mp.setattr(jev_router, "call_jev", lambda *a, **k: _answer(chosen, 0.9))
        # Inject the fake clock in place of time.monotonic for the jev_router module.
        mp.setattr(jev_router.time, "monotonic", clock.monotonic)

        result = router.route(
            query_text="some query",
            snapshot=snapshot,
            custom_provider=_custom_provider,
        )

        recorded = result.latency_ms

        # Simulate heavy post-decision work: advance the clock far beyond the window.
        clock.advance(10.0)

    # Latency is a non-negative int ...
    assert isinstance(recorded, int)
    assert recorded >= 0

    # ... and reflects exactly the decision window (one 0.25 s step = 250 ms), proving
    # it was measured around the call and up to the decision, not later.
    assert recorded == int(step_seconds * 1000)

    # Post-decision clock advancement never changed the recorded value: latency_ms is
    # captured before any post-decision work and is immutable thereafter.
    assert result.latency_ms == recorded

    # The router read the clock exactly twice (start + decision point), confirming no
    # extra timing spans post-decision work.
    assert clock.reads == 2
