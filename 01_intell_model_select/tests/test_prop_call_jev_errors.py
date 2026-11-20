"""Property 6 and example tests for Jev failure mapping.

Feature: jev-router-comparison

This module covers ``jev_client.call_jev`` on the failure paths:

* Property 6: Failures map to a categorised error and never raise.
  For any non-2xx HTTP status, any malformed or structurally invalid body
  (non-JSON, missing keys, wrong types, NaN, out-of-range numbers), and any
  transport exception or timeout, ``call_jev`` returns a ``JevError`` whose
  category is one of ``timeout``, ``http_error``, or ``invalid_response`` and
  never lets an exception propagate. ``http_error`` carries the status code.
  (Validates Requirement 3.8.)

* Example (Requirement 3.2): the request uses method POST, the URL ``JEV_URL``,
  and an ``Authorization: Bearer <key>`` header. This is asserted against the
  real urllib transport with ``urlopen`` intercepted, so no network is touched
  and the actual header-building code runs.

* Example (Requirement 10.1): a sleeping transport returns ``JevError("timeout")``
  within the configured timeout plus 0.5 s.

Additional requirements exercised: 3.7 (wall-clock deadline bounds the call),
10.1 (fallback stays inside the latency budget).

All tests run offline. No real network call is made and no API key is read from
anywhere; keys are in-memory throwaway strings.
"""

from __future__ import annotations

import io
import json
import time
import urllib.error
import urllib.request
from typing import Any, List, Optional

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import jev_client
from jev_client import JEV_URL, JevAnswer, JevError, call_jev

from strategies import CATALOGUE_IDS, api_keys, bad_bodies

# The three categories call_jev is permitted to return on failure.
_ERROR_CATEGORIES = {"timeout", "http_error", "invalid_response"}

# A minimal, well-formed request payload. The Choice question's criteria keys are
# the catalogue IDs so call_jev derives the right catalogue_ids when parsing.
_PAYLOAD = {
    "model": "jev-1.13.0",
    "state": {"query": "hello", "characteristics": {}},
    "questions": {
        "model_choice": {
            "type": "choice",
            "instructions": "pick one",
            "criteria": {model_id: "desc" for model_id in CATALOGUE_IDS},
        }
    },
}


def _assert_is_error(outcome: Any) -> JevError:
    """Assert the outcome is a JevError with a valid category and return it."""
    assert isinstance(outcome, JevError), f"expected JevError, got {outcome!r}"
    assert outcome.category in _ERROR_CATEGORIES, (
        f"unexpected category {outcome.category!r}"
    )
    return outcome


# --------------------------------------------------------------------------- #
# Transport doubles kept local to this module so the assertions are explicit.
# --------------------------------------------------------------------------- #
def _status_transport(status: int) -> Any:
    """A transport returning a 2xx-shaped body but with the given status code."""

    def _transport(payload, api_key, timeout_s):
        return jev_client._TransportResult(status=status, body=b'{"answers": {}}')

    return _transport


def _body_transport(status: int, body: bytes) -> Any:
    """A transport returning a fixed status and body."""

    def _transport(payload, api_key, timeout_s):
        return jev_client._TransportResult(status=status, body=body)

    return _transport


def _raising_transport(exc: BaseException) -> Any:
    """A transport that raises the given exception."""

    def _transport(payload, api_key, timeout_s):
        raise exc

    return _transport


# --------------------------------------------------------------------------- #
# Property 6
# --------------------------------------------------------------------------- #
# Feature: jev-router-comparison, Property 6: Failures map to a categorised
# error and never raise.


@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(
    status=st.integers(min_value=100, max_value=599).filter(
        lambda s: not 200 <= s < 300
    ),
    key=api_keys(),
)
def test_non_2xx_status_maps_to_http_error(status: int, key: str) -> None:
    """Any non-2xx status becomes http_error carrying that status, no raise."""
    outcome = call_jev(_PAYLOAD, key, 5.0, transport=_status_transport(status))
    error = _assert_is_error(outcome)
    assert error.category == "http_error"
    assert error.status_code == status


@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(body=bad_bodies(), key=api_keys())
def test_malformed_body_maps_to_invalid_response(body: bytes, key: str) -> None:
    """A 2xx status with a malformed/invalid body becomes invalid_response."""
    outcome = call_jev(_PAYLOAD, key, 5.0, transport=_body_transport(200, body))
    error = _assert_is_error(outcome)
    assert error.category == "invalid_response"


# Transport exceptions the client may encounter, each with the category the
# design's error table assigns to it.
def _transport_exceptions() -> st.SearchStrategy[Any]:
    timeouts: List[Any] = [
        TimeoutError("slow"),
        urllib.error.URLError(TimeoutError("timed out")),
        urllib.error.URLError("the read operation timed out"),
    ]
    http_errors: List[Any] = [
        urllib.error.HTTPError(JEV_URL, 401, "Unauthorized", {}, None),
        urllib.error.HTTPError(JEV_URL, 422, "Unprocessable", {}, None),
        urllib.error.HTTPError(JEV_URL, 429, "Too Many Requests", {}, None),
        urllib.error.HTTPError(JEV_URL, 529, "Overloaded", {}, None),
        urllib.error.URLError("connection refused"),
        ConnectionResetError("boom"),
        OSError("network down"),
        ValueError("unexpected"),
    ]
    return st.sampled_from(
        [("timeout", e) for e in timeouts]
        + [("http_error", e) for e in http_errors]
    )


@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(case=_transport_exceptions(), key=api_keys())
def test_transport_exceptions_map_to_a_category(case: Any, key: str) -> None:
    """Any transport exception is caught and mapped; nothing propagates."""
    expected_category, exc = case
    outcome = call_jev(_PAYLOAD, key, 5.0, transport=_raising_transport(exc))
    error = _assert_is_error(outcome)
    assert error.category == expected_category
    # HTTPError instances carry a status; it must be surfaced.
    if isinstance(exc, urllib.error.HTTPError):
        assert error.status_code == exc.code


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(key=api_keys())
def test_deadline_expiry_maps_to_timeout(key: str) -> None:
    """A transport slower than the deadline yields a timeout error, no raise."""
    outcome = call_jev(
        _PAYLOAD,
        key,
        0.05,
        transport=lambda p, k, t: (time.sleep(1.0), jev_client._TransportResult(200, b"{}"))[1],
    )
    error = _assert_is_error(outcome)
    assert error.category == "timeout"


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(key=api_keys(), status=st.sampled_from([401, 422, 429, 500, 502, 529]))
def test_call_jev_never_raises_and_key_never_leaks(key: str, status: int) -> None:
    """call_jev returns an error (never raises) and the key never appears in it."""
    outcome = call_jev(_PAYLOAD, key, 5.0, transport=_status_transport(status))
    error = _assert_is_error(outcome)
    # The key must never be carried on the result object in any field.
    assert key not in repr(error)


# --------------------------------------------------------------------------- #
# Example: request uses POST, JEV_URL, and a Bearer Authorization header (3.2).
# --------------------------------------------------------------------------- #
class _FakeHTTPResponse(io.BytesIO):
    """A minimal stand-in for the urlopen context-manager response."""

    def __init__(self, status: int, body: bytes) -> None:
        super().__init__(body)
        self.status = status

    def getcode(self) -> int:  # pragma: no cover - only a fallback path uses this
        return self.status

    def __enter__(self) -> "_FakeHTTPResponse":
        return self

    def __exit__(self, *exc: Any) -> bool:
        self.close()
        return False


def test_request_uses_post_url_and_bearer_header(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real transport builds a POST to JEV_URL with an Authorization Bearer header."""
    captured: dict[str, Optional[urllib.request.Request]] = {"request": None}
    good_body = json.dumps(
        {
            "model": "jev-1.13.0",
            "answers": {
                "model_choice": {
                    "type": "choice",
                    "choice": CATALOGUE_IDS[0],
                    "probabilities": {CATALOGUE_IDS[0]: 1.0},
                    "confidence": 0.9,
                }
            },
        }
    ).encode("utf-8")

    def _fake_urlopen(request: urllib.request.Request, timeout: Optional[float] = None):
        captured["request"] = request
        return _FakeHTTPResponse(200, good_body)

    # Intercept urlopen so the REAL header-building transport runs with no network.
    monkeypatch.setattr(jev_client.urllib.request, "urlopen", _fake_urlopen)

    key = "sk-test-EXAMPLE-key-not-real"
    outcome = call_jev(_PAYLOAD, key, 5.0)  # default transport = _urllib_transport

    # A valid body parses to an answer, confirming the real path ran end to end.
    assert isinstance(outcome, JevAnswer)

    request = captured["request"]
    assert request is not None, "urlopen was never called"
    assert request.get_method() == "POST"
    assert request.full_url == JEV_URL
    authorization = request.get_header("Authorization")
    assert authorization == f"Bearer {key}"


# --------------------------------------------------------------------------- #
# Example: sleeping transport returns JevError("timeout") within timeout+0.5s (10.1).
# --------------------------------------------------------------------------- #
def test_sleeping_transport_times_out_within_budget(
    fake_transport_factory: Any,
) -> None:
    """A transport that sleeps well past the deadline yields a prompt timeout."""
    timeout_s = 0.2
    # The fake sleeps far longer than the deadline; call_jev must not wait for it.
    transport = fake_transport_factory(default_action=5.0)

    start = time.monotonic()
    outcome = call_jev(_PAYLOAD, "sk-test-EXAMPLE", timeout_s, transport=transport)
    elapsed = time.monotonic() - start

    error = _assert_is_error(outcome)
    assert error.category == "timeout"
    assert elapsed < timeout_s + 0.5, (
        f"timeout took {elapsed:.3f}s, over the {timeout_s}+0.5s budget"
    )
    # Exactly one transport call was attempted.
    assert transport.call_count == 1
