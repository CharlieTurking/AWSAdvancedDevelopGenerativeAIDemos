"""Property 11 and example tests for the Routing_Policy on client errors.

Feature: jev-router-comparison

This module covers ``jev_router.apply_policy`` on the client-error path:

* Property 11: Client errors fall back and name the category.
  For any ``JevError`` category (``timeout``, ``http_error``, ``invalid_response``),
  with Jev configured, ``apply_policy`` returns a fallback decision
  (``model_id`` is None and ``fallback`` is True) whose ``fallback_reason``
  equals the error's category and whose reasoning text names that category.
  (Validates Requirement 4.5.)

* Example (Requirement 14.2): a ``timeout`` error falls back and the reasoning
  mentions the timeout.

* Example (Requirements 14.7, 4.6): when Jev is not configured
  (``apply_policy(None, configured=False, ...)``), the policy falls back with
  reason ``REASON_NOT_CONFIGURED`` and ``outcome`` is ``None`` so no HTTP call
  was ever made - the "no secret, no HTTP" path.

All tests run offline. ``apply_policy`` is a pure function: no network, no
secret read, no clock. The error outcomes are constructed directly as
``JevError`` instances (mapped from the shared ``jev_errors()`` strategy where a
generator is used), so nothing here touches the Jev API or reads a key.
"""

from __future__ import annotations

from typing import Any, Dict, FrozenSet

from hypothesis import given, settings
from hypothesis import strategies as st

from jev_client import JevError
from jev_router import CANDIDATE_CATALOGUE, REASON_NOT_CONFIGURED, apply_policy

from strategies import CATALOGUE_IDS, health_states, jev_errors

# The three categories a JevError may carry (design error mapping / strategies).
_ERROR_CATEGORIES = ("timeout", "http_error", "invalid_response")


def _jev_error_from_tagged(tagged: Dict[str, Any]) -> JevError:
    """Map a ``jev_errors()`` tagged dict to a real ``JevError``.

    ``jev_errors()`` yields ``{"kind": "error", "category": ..., "status_code": ...}``
    (``status_code`` is a code for ``http_error`` and ``None`` otherwise), which
    matches ``JevError(category, status_code)`` directly.
    """
    return JevError(
        category=tagged["category"],
        status_code=tagged.get("status_code"),
    )


# --------------------------------------------------------------------------- #
# Property 11
# --------------------------------------------------------------------------- #
# Feature: jev-router-comparison, Property 11: Client errors fall back and name
# the category. For any JevError category, the Routing_Policy falls back and the
# reasoning contains the category. (Validates Requirement 4.5.)


@settings(max_examples=200)
@given(
    tagged_error=jev_errors(),
    healthy=health_states(),
    threshold=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
)
def test_client_error_falls_back_and_names_category(
    tagged_error: Dict[str, Any],
    healthy: FrozenSet[str],
    threshold: float,
) -> None:
    """A JevError outcome (configured) falls back, reason == category, named in reasoning."""
    error = _jev_error_from_tagged(tagged_error)

    decision = apply_policy(
        error,
        configured=True,
        catalogue_ids=CANDIDATE_CATALOGUE,
        healthy=healthy,
        threshold=threshold,
    )

    # It is a fallback: no accepted model.
    assert decision.model_id is None
    assert decision.fallback is True

    # The fallback reason is exactly the error category.
    assert decision.fallback_reason == error.category
    assert error.category in _ERROR_CATEGORIES

    # The category appears in the human-readable reasoning.
    reasoning_text = " ".join(decision.reasoning)
    assert error.category in reasoning_text
    # And the reasoning is non-empty.
    assert decision.reasoning


@settings(max_examples=50)
@given(
    category=st.sampled_from(_ERROR_CATEGORIES),
    status_code=st.one_of(st.none(), st.sampled_from([401, 422, 429, 500, 529])),
    healthy=health_states(),
)
def test_each_category_is_named_regardless_of_status(
    category: str,
    status_code: Any,
    healthy: FrozenSet[str],
) -> None:
    """Every category, with or without a status code, falls back and is named."""
    error = JevError(category=category, status_code=status_code)

    decision = apply_policy(
        error,
        configured=True,
        catalogue_ids=CANDIDATE_CATALOGUE,
        healthy=healthy,
        threshold=0.6,
    )

    assert decision.fallback is True
    assert decision.model_id is None
    assert decision.fallback_reason == category
    assert category in " ".join(decision.reasoning)


# --------------------------------------------------------------------------- #
# Example: a timeout fallback mentions the timeout (Requirement 14.2).
# --------------------------------------------------------------------------- #
def test_timeout_fallback_mentions_timeout() -> None:
    """A timeout error falls back and the reasoning mentions the timeout."""
    error = JevError(category="timeout")

    decision = apply_policy(
        error,
        configured=True,
        catalogue_ids=CANDIDATE_CATALOGUE,
        healthy=frozenset(CATALOGUE_IDS),
        threshold=0.6,
    )

    assert decision.fallback is True
    assert decision.model_id is None
    assert decision.fallback_reason == "timeout"
    assert "timeout" in " ".join(decision.reasoning)


def test_http_error_fallback_names_http_error() -> None:
    """An http_error (with a status) falls back and names the category."""
    error = JevError(category="http_error", status_code=429)

    decision = apply_policy(
        error,
        configured=True,
        catalogue_ids=CANDIDATE_CATALOGUE,
        healthy=frozenset(CATALOGUE_IDS),
        threshold=0.6,
    )

    assert decision.fallback is True
    assert decision.fallback_reason == "http_error"
    assert "http_error" in " ".join(decision.reasoning)


# --------------------------------------------------------------------------- #
# Example: no secret -> no HTTP call and fallback (Requirements 14.7, 4.6).
# --------------------------------------------------------------------------- #
def test_not_configured_falls_back_without_a_call() -> None:
    """With no secret, apply_policy(None, configured=False, ...) falls back.

    The outcome passed in is ``None`` precisely because the Jev_Router skips the
    HTTP call when Jev is not configured, so this exercises the "no secret, no
    HTTP" path: the policy decides a fallback purely from ``configured=False``
    without ever seeing a Jev answer or error.
    """
    decision = apply_policy(
        None,
        configured=False,
        catalogue_ids=CANDIDATE_CATALOGUE,
        healthy=frozenset(CATALOGUE_IDS),
        threshold=0.6,
    )

    assert decision.fallback is True
    assert decision.model_id is None
    assert decision.fallback_reason == REASON_NOT_CONFIGURED
    assert decision.reasoning  # a human-readable explanation is present


@settings(max_examples=50)
@given(
    healthy=health_states(),
    threshold=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
)
def test_not_configured_ignores_health_and_threshold(
    healthy: FrozenSet[str],
    threshold: float,
) -> None:
    """Not-configured always falls back with REASON_NOT_CONFIGURED, no call implied."""
    decision = apply_policy(
        None,
        configured=False,
        catalogue_ids=CANDIDATE_CATALOGUE,
        healthy=healthy,
        threshold=threshold,
    )

    assert decision.fallback is True
    assert decision.model_id is None
    assert decision.fallback_reason == REASON_NOT_CONFIGURED
