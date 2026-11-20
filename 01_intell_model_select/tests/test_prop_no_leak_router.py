"""Property test for secret and query non-leakage in the Jev_Router.

Feature: jev-router-comparison, Property 17: Secrets and query text never leak.

For ANY API key string, ANY query text, and ANY Jev outcome (a valid answer, a
categorised error, "not configured", or an unexpected exception on the Jev path
whose message embeds the key and the query), neither

* the API key, nor
* the full query text

appears in either

* the log output captured during ``JevRouter.route`` (``log_capture.text``), or
* the serialised ``RoutingResult`` (``json.dumps(dataclasses.asdict(result))`` --
  its ``reasoning`` list, every field, and every nested value).

The query LENGTH may be logged (the summary line logs ``query_len``), but the
query TEXT must not. To make that distinction checkable, the generated query is
seeded with a rare sentinel token that could only appear in the output if the
raw query text leaked; we assert the sentinel's absence from logs and from the
serialised result.

The test drives ``JevRouter.route`` with the fake-router + ``custom_provider`` +
per-example monkeypatch pattern from ``tests/test_prop_route_invariant.py``:

* ``jev_status`` is patched so Jev is configured (and, for the recorded branch,
  so ``mode`` is reported) -- this exercises the path that actually reads the
  key and calls Jev.
* ``get_jev_key`` is patched to return the distinctive key.
* ``call_jev`` is patched to return the generated outcome (no real transport),
  or, for one generated branch, to RAISE an exception whose message contains
  both the key and the sentinel -- the design requires the router's catch-all to
  reduce such exceptions to their class name, so neither value may escape.

Validates: Requirements 8.3, 9.5, 11.2 (and 14.13).
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import jev_router
from jev_router import CANDIDATE_CATALOGUE, HealthSnapshot, JevRouter
from jev_client import JevAnswer, JevError

from strategies import api_keys, health_states, queries


# --------------------------------------------------------------------------- #
# A rare sentinel token woven into every generated query.
# --------------------------------------------------------------------------- #
# The token is deliberately unusual so it cannot appear in the router's own
# reasoning strings, model IDs, or the fixed summary-line template. If it shows
# up in the logs or the serialised result, the only possible source is the raw
# query text -- which is exactly the leak this property forbids. The query
# length may still be logged, and a sentinel-bearing query only inflates that
# length; it never reveals the token.
SENTINEL = "Zx9QyLeakSentinel_\u2603_7fQ"

# A rare, fixed marker prepended to every generated key. ``api_keys()`` can draw
# short, common strings (for example "00000000") that coincidentally equal a
# generated Jev ``choice`` or ``model_version`` -- those values legitimately
# appear in the router's reasoning and are NOT the secret leaking. Prefixing the
# key with this marker makes it distinctive, so the only way the key string can
# reach the logs or the result is a genuine leak of the secret itself.
KEY_MARKER = "Kx4SecretMarker_\u2622_9wZ-"


# --------------------------------------------------------------------------- #
# Minimal Custom_Router decision + provider (mirrors test_prop_route_invariant).
# The fallback reasoning the provider returns MUST NOT contain the key or the
# sentinel, so a leak detected by the test can only come from the router itself.
# --------------------------------------------------------------------------- #
@dataclass
class _FakeProvider:
    value: str


@dataclass
class _FakeCustomDecision:
    selected_model_id: str
    selected_provider: _FakeProvider
    confidence_score: float = 0.5
    decision_reasoning: List[str] = field(
        default_factory=lambda: ["custom router reasoning (no secret, no query)"]
    )


FALLBACK_MODEL_ID = "test.custom-only-fallback-model-v1:0"


def _custom_provider() -> _FakeCustomDecision:
    return _FakeCustomDecision(
        selected_model_id=FALLBACK_MODEL_ID,
        selected_provider=_FakeProvider("nova"),
    )


# --------------------------------------------------------------------------- #
# Minimal router object (only model_capabilities / query_analyzer are touched,
# and the Jev call is patched out so neither is actually exercised).
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
# Outcome strategy local to this property.
# --------------------------------------------------------------------------- #
# Four branches, each of which must keep the key and the sentinel out of logs
# and the result:
#   * "answer"         - a structurally valid JevAnswer (accepted or rejected).
#   * "error"          - a categorised JevError.
#   * "not_configured" - no call made; jev_status reports not configured.
#   * "raise"          - call_jev raises an exception whose message embeds BOTH
#                        the key and the sentinel, exercising the catch-all that
#                        must log only the class name.
_PROBS = st.fixed_dictionaries(
    {
        model_id: st.floats(
            min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False
        )
        for model_id in CANDIDATE_CATALOGUE
    }
)


@st.composite
def _leak_outcomes(draw: st.DrawFn) -> Dict[str, Any]:
    kind = draw(
        st.sampled_from(["answer", "error", "not_configured", "raise"])
    )
    if kind == "answer":
        choice = draw(
            st.one_of(st.sampled_from(list(CANDIDATE_CATALOGUE)), st.text(max_size=40))
        )
        return {
            "kind": "answer",
            "choice": choice,
            "probabilities": draw(_PROBS),
            "confidence": draw(
                st.floats(
                    min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False
                )
            ),
            "high_consequence": draw(
                st.one_of(
                    st.none(),
                    st.floats(
                        min_value=0.0,
                        max_value=1.0,
                        allow_nan=False,
                        allow_infinity=False,
                    ),
                )
            ),
            "model_version": draw(st.one_of(st.none(), st.text(max_size=20))),
        }
    if kind == "error":
        category = draw(st.sampled_from(["timeout", "http_error", "invalid_response"]))
        status = (
            draw(st.sampled_from([401, 422, 429, 500, 502, 529]))
            if category == "http_error"
            else None
        )
        return {"kind": "error", "category": category, "status_code": status}
    if kind == "raise":
        return {"kind": "raise"}
    return {"kind": "not_configured"}


# --------------------------------------------------------------------------- #
# Property 17.
# --------------------------------------------------------------------------- #
# The ``log_capture`` fixture is function-scoped, so Hypothesis does not reset it
# between generated inputs. That is fine here: we explicitly ``clear()`` the
# capture at the start of each example so every input is checked against only its
# own log output. Suppress the (correct, but here handled) health check.
@settings(
    max_examples=300,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    outcome=_leak_outcomes(),
    healthy=health_states(),
    key=api_keys(),
    query_prefix=queries(max_size=200),
    query_suffix=queries(max_size=200),
    threshold=st.floats(
        min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False
    ),
    recorded=st.booleans(),
)
def test_key_and_query_never_leak(
    log_capture: Any,
    outcome: Dict[str, Any],
    healthy: FrozenSet[str],
    key: str,
    query_prefix: str,
    query_suffix: str,
    threshold: float,
    recorded: bool,
) -> None:
    """The key and the raw query text never reach the logs or the result.

    Quantifies over every outcome kind, every health subset, a distinctive key,
    a sentinel-bearing query, any threshold, and both live/recorded modes. The
    ``not_configured`` outcome forces ``configured=False`` (no key read, no
    call); every other outcome runs the configured path that reads the key and
    calls Jev.
    """
    # Reset the shared capture so this example is judged only against its own log
    # output (the fixture is not reset between generated inputs).
    log_capture.clear()

    # Make the key distinctive so it cannot collide with other generated values
    # (choice / model_version) that legitimately appear in the router's reasoning.
    key = f"{KEY_MARKER}{key}"

    # Weave the sentinel into the middle of arbitrary query text so a leak of any
    # substring of the real query would surface the token.
    query_text = f"{query_prefix}{SENTINEL}{query_suffix}"

    kind = outcome["kind"]
    configured = kind != "not_configured"
    mode = "recorded" if recorded else "live"

    def _fake_jev_status() -> Dict[str, Any]:
        return {"configured": configured, "mode": mode}

    # Map the generated outcome to what route() consumes, or raise with a message
    # that embeds BOTH the key and the sentinel to prove the catch-all scrubs it.
    real_outcome: Optional[Any]
    if kind == "answer":
        real_outcome = JevAnswer(
            choice=outcome["choice"],
            probabilities=dict(outcome["probabilities"]),
            confidence=outcome["confidence"],
            high_consequence=outcome["high_consequence"],
            model_version=outcome["model_version"],
        )
    elif kind == "error":
        real_outcome = JevError(
            category=outcome["category"], status_code=outcome["status_code"]
        )
    else:
        real_outcome = None  # not_configured and raise do not return a value

    def _fake_call_jev(*args: Any, **kwargs: Any):
        if kind == "raise":
            # An exception whose message leaks the key and the query; the router's
            # catch-all must reduce it to the class name only.
            raise RuntimeError(f"boom key={key} query={query_text}")
        return real_outcome

    # In recorded mode route() calls load_recording instead of call_jev; patch it
    # the same way so the recorded branch is covered too.
    def _fake_load_recording(q: str):
        if kind == "raise":
            raise RuntimeError(f"boom key={key} query={query_text}")
        return real_outcome

    router = JevRouter(_FakeRouter())
    snapshot = HealthSnapshot(healthy_models=healthy)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(jev_router, "jev_status", _fake_jev_status)
        mp.setattr(jev_router, "get_jev_key", lambda: key)
        mp.setattr(jev_router, "call_jev", _fake_call_jev)
        mp.setattr(jev_router, "load_recording", _fake_load_recording)
        mp.setattr(jev_router, "get_confidence_threshold", lambda: threshold)

        result = router.route(
            query_text=query_text,
            snapshot=snapshot,
            custom_provider=_custom_provider,
        )

    # ---- The captured logs must not contain the key or the raw query text. -----
    log_text = log_capture.text
    assert key not in log_text, "the API key leaked into the log output"
    assert SENTINEL not in log_text, "the raw query text leaked into the log output"

    # The query LENGTH is allowed in the logs; confirm the summary line was emitted
    # so the no-leak assertion is meaningful (we did log something) and the length
    # it reports matches the real query without exposing the text.
    assert f"query_len={len(query_text)}" in log_text

    # ---- The serialised result must not contain the key or the raw query text. -
    serialised = json.dumps(dataclasses.asdict(result), default=str)
    assert key not in serialised, "the API key leaked into the RoutingResult"
    assert SENTINEL not in serialised, "the raw query text leaked into the RoutingResult"
