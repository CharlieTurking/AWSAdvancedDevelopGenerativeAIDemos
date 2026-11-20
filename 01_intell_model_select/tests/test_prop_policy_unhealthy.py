"""Property test for unhealthy Jev choices (task 3.4).

# Feature: jev-router-comparison, Property 10: Unhealthy choices are never
# selected and are substituted only by qualifying candidates
#
# For any answer whose choice is a catalogue model that is NOT in the healthy
# set, with a confidence at or above the threshold, any probabilities, and any
# threshold, the pure Routing_Policy:
#   * never returns the unhealthy choice, and
#   * returns the highest-probability healthy catalogue candidate whose
#     probability is at least the threshold (ties broken by catalogue order),
#     or
#   * falls back (model_id is None, fallback_reason == REASON_UNHEALTHY_CHOICE)
#     when no such candidate exists.
# The reasoning names the action taken.

Validates: Requirements 4.4

Additional _Requirements: 4.4, 14.5

This test exercises the pure ``apply_policy`` from ``jev_router`` with
Hypothesis-generated answers, healthy subsets, and thresholds. It reuses
``health_states()`` from ``tests/strategies.py`` for the healthy-model sets and
builds the catalogue choice / confidence / probabilities so the unhealthy
branch (rule 6 of the policy ladder) is always the one under test.

The 14.5 example constructs a real ``ModelHealthMonitor`` from
``health_monitor`` (no network: the vendored boto3 client is created lazily and
no health check is ever performed) and forces one model's circuit breaker OPEN
by recording failures through the real ``CircuitBreakerState`` logic. The
healthy set handed to ``apply_policy`` is derived from each breaker's
``should_allow_request()`` exactly as the monitor itself gates requests, so the
example proves at the policy boundary that a model whose breaker is open is
excluded from ``healthy`` and therefore never selected.
"""

from __future__ import annotations

import os
from typing import Dict, FrozenSet

from hypothesis import given, settings
from hypothesis import strategies as st

# ``conftest.py`` puts ``lambda/`` on sys.path so these import by bare name,
# exactly as the Lambda runtime loads them.
from jev_client import JevAnswer
from jev_router import (
    CANDIDATE_CATALOGUE,
    REASON_UNHEALTHY_CHOICE,
    apply_policy,
)

from strategies import CATALOGUE_IDS, health_states


# Sanity: the test's catalogue literals and the module constant agree. If they
# ever drift, fail loudly rather than silently testing the wrong option space.
assert set(CATALOGUE_IDS) == set(CANDIDATE_CATALOGUE)


# --------------------------------------------------------------------------- #
# Generators
# --------------------------------------------------------------------------- #

# Probabilities in [0, 1] for each catalogue member. Drawn independently (not
# normalised) so both "a healthy candidate qualifies" and "none qualifies" are
# reachable for any threshold.
_PROB = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)


@st.composite
def probabilities(draw: st.DrawFn) -> Dict[str, float]:
    return {model_id: draw(_PROB) for model_id in CANDIDATE_CATALOGUE}


@st.composite
def thresholds(draw: st.DrawFn) -> float:
    # The Confidence_Threshold lives in (0, 1]; 0.6 is the configured default.
    return draw(
        st.floats(min_value=0.01, max_value=1.0, allow_nan=False, allow_infinity=False)
    )


def _expected_substitute(
    healthy: FrozenSet[str], probs: Dict[str, float], threshold: float
) -> str | None:
    """Recompute the policy's intended substitute independently of the module.

    Healthy catalogue members whose probability meets the threshold, picking the
    highest probability and breaking ties by catalogue order (the first maximal
    element in catalogue order).
    """
    best: str | None = None
    best_prob = -1.0
    for model_id in CANDIDATE_CATALOGUE:  # catalogue order
        if model_id not in healthy:
            continue
        p = probs.get(model_id, 0.0)
        if p >= threshold and p > best_prob:
            best = model_id
            best_prob = p
    return best


# --------------------------------------------------------------------------- #
# Property 10
# --------------------------------------------------------------------------- #


@settings(max_examples=400)
@given(
    data=st.data(),
    healthy=health_states(),
    probs=probabilities(),
    threshold=thresholds(),
    extra_confidence=st.floats(
        min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False
    ),
    high_consequence=st.one_of(st.none(), _PROB),
    model_version=st.one_of(st.none(), st.text(min_size=1, max_size=20)),
)
def test_unhealthy_choice_never_selected_and_substituted_only_when_qualifying(
    data: st.DataObject,
    healthy: FrozenSet[str],
    probs: Dict[str, float],
    threshold: float,
    extra_confidence: float,
    high_consequence: float | None,
    model_version: str | None,
) -> None:
    # The choice must be a catalogue model that is NOT healthy, so rule 6 (the
    # unhealthy branch) is exercised. Any catalogue member outside ``healthy``
    # qualifies as an unhealthy choice.
    unhealthy_catalogue = [m for m in CANDIDATE_CATALOGUE if m not in healthy]
    # ``health_states()`` can produce the full catalogue as healthy; in that
    # case there is no unhealthy choice to test, so skip via a filtered draw.
    choice = data.draw(st.sampled_from(unhealthy_catalogue)) if unhealthy_catalogue else None
    if choice is None:
        return  # no unhealthy catalogue member available for this healthy set

    # Confidence at or above the threshold so the low-confidence rule (rule 4)
    # does not pre-empt the unhealthy branch. Map [0, 1] into [threshold, 1].
    confidence = threshold + extra_confidence * (1.0 - threshold)

    answer = JevAnswer(
        choice=choice,
        probabilities=probs,
        confidence=confidence,
        high_consequence=high_consequence,
        model_version=model_version,
    )

    decision = apply_policy(
        answer,
        configured=True,
        catalogue_ids=CANDIDATE_CATALOGUE,
        healthy=healthy,
        threshold=threshold,
    )

    # The unhealthy choice is never selected.
    assert decision.model_id != choice

    expected = _expected_substitute(healthy, probs, threshold)

    if expected is not None:
        # A qualifying healthy candidate exists: substitute it, no fallback.
        assert decision.fallback is False
        assert decision.fallback_reason is None
        assert decision.model_id == expected
        # The substitute is healthy and a catalogue member.
        assert decision.model_id in healthy
        assert decision.model_id in CANDIDATE_CATALOGUE
        # Its probability meets the threshold.
        assert probs.get(decision.model_id, 0.0) >= threshold
        # The reasoning names the substitution action.
        reasoning = " ".join(decision.reasoning).lower()
        assert "substitut" in reasoning
    else:
        # No qualifying healthy candidate: fall back with the unhealthy reason.
        assert decision.fallback is True
        assert decision.model_id is None
        assert decision.fallback_reason == REASON_UNHEALTHY_CHOICE
        # The reasoning names the action (unhealthy -> custom router).
        reasoning = " ".join(decision.reasoning).lower()
        assert "unhealthy" in reasoning


# --------------------------------------------------------------------------- #
# Example (Requirement 14.5): a model with an open circuit breaker is excluded
# from the healthy set and is therefore never selected.
# --------------------------------------------------------------------------- #


def _healthy_from_monitor(monitor) -> FrozenSet[str]:
    """Derive the healthy, catalogue-filtered set from the monitor's breakers.

    A model is healthy here iff its real circuit breaker allows requests. This
    is the same gate the monitor applies before a health check, so the healthy
    set we feed the policy matches how the monitor treats an open breaker.
    """
    return frozenset(
        model_id
        for model_id in CANDIDATE_CATALOGUE
        if monitor.circuit_breakers[model_id].should_allow_request()
    )


def test_open_circuit_breaker_model_is_never_selected() -> None:
    # Build a real monitor. Creating the vendored boto3 client is lazy and makes
    # no network call; no health check is ever run in this test.
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    from bedrock_adapter import BedrockConverseAdapter
    from health_monitor import CircuitState, ModelHealthMonitor

    adapter = BedrockConverseAdapter()
    monitor = ModelHealthMonitor(adapter)

    # Force the first catalogue model's breaker OPEN through the real logic:
    # enough recorded failures to cross the failure threshold.
    open_model = CANDIDATE_CATALOGUE[0]
    breaker = monitor.circuit_breakers[open_model]
    for _ in range(breaker.config.failure_threshold):
        breaker.record_failure()

    # The real breaker is now open and blocks requests.
    assert breaker.state is CircuitState.OPEN
    assert breaker.should_allow_request() is False

    healthy = _healthy_from_monitor(monitor)
    # The open-breaker model is excluded from the healthy set.
    assert open_model not in healthy

    # Jev chooses the model whose breaker is open, with full confidence and the
    # highest probability on itself, so only the health gate can keep it out.
    threshold = 0.6
    probs = {model_id: 0.1 for model_id in CANDIDATE_CATALOGUE}
    probs[open_model] = 0.99
    answer = JevAnswer(
        choice=open_model,
        probabilities=probs,
        confidence=0.99,
        high_consequence=None,
        model_version="jev-1.13.0",
    )

    decision = apply_policy(
        answer,
        configured=True,
        catalogue_ids=CANDIDATE_CATALOGUE,
        healthy=healthy,
        threshold=threshold,
    )

    # The unhealthy (open-breaker) model is never selected.
    assert decision.model_id != open_model
    # It is either a qualifying healthy substitute or the fallback, never the
    # open-breaker model.
    if decision.model_id is not None:
        assert decision.model_id in healthy
    else:
        assert decision.fallback is True
        assert decision.fallback_reason == REASON_UNHEALTHY_CHOICE
