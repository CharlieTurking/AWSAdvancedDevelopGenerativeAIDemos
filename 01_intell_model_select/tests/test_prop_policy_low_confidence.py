"""Property test for the low-confidence fallback branch of the Routing_Policy.

# Feature: jev-router-comparison, Property 9: Low confidence falls back.
# For any JevAnswer whose choice is a Candidate_Catalogue member but whose
# confidence is strictly below the Confidence_Threshold, and any threshold in
# (0, 1], ``apply_policy`` falls back (model_id None, fallback True,
# fallback_reason == REASON_LOW_CONFIDENCE) and the reasoning names both the
# received confidence and the threshold.
#
# The healthy set deliberately *includes* the chosen model. Rule 4 (confidence)
# runs before rule 5 (healthy accept) in the policy ladder, so even a healthy
# choice must fall back when its confidence is too low. Generating the choice as
# healthy proves the confidence check happens first.

Validates: Requirements 4.3
"""

from __future__ import annotations

from typing import Dict

from hypothesis import given, settings
from hypothesis import strategies as st

from jev_router import (
    CANDIDATE_CATALOGUE,
    REASON_LOW_CONFIDENCE,
    apply_policy,
)
from jev_client import JevAnswer

from strategies import CATALOGUE_IDS


# --------------------------------------------------------------------------- #
# Generators.
# --------------------------------------------------------------------------- #
# A threshold strictly in (0, 1]: positive so that [0, threshold) is a non-empty
# confidence range, and at most 1 to stay a valid Confidence_Threshold.
_thresholds = st.floats(
    min_value=0.0,
    max_value=1.0,
    exclude_min=True,
    allow_nan=False,
    allow_infinity=False,
)


@st.composite
def _low_confidence_cases(draw: st.DrawFn) -> Dict[str, object]:
    """A catalogue choice, a threshold in (0, 1], and a confidence below it.

    The confidence is drawn from [0, threshold) with the upper bound excluded so
    the strict ``confidence < threshold`` inequality always holds. An arbitrary
    probability map over the catalogue is attached so the answer is structurally
    complete; it does not affect the low-confidence decision.
    """
    choice = draw(st.sampled_from(CATALOGUE_IDS))
    threshold = draw(_thresholds)
    confidence = draw(
        st.floats(
            min_value=0.0,
            max_value=threshold,
            exclude_max=True,
            allow_nan=False,
            allow_infinity=False,
        )
    )

    probabilities: Dict[str, float] = {
        model_id: draw(
            st.floats(
                min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False
            )
        )
        for model_id in CATALOGUE_IDS
    }

    return {
        "choice": choice,
        "threshold": threshold,
        "confidence": confidence,
        "probabilities": probabilities,
    }


# --------------------------------------------------------------------------- #
# Property 9: low confidence falls back, naming confidence and threshold.
# --------------------------------------------------------------------------- #
@settings(max_examples=300)
@given(case=_low_confidence_cases())
def test_low_confidence_falls_back(case: Dict[str, object]) -> None:
    choice = case["choice"]
    threshold = case["threshold"]
    confidence = case["confidence"]
    probabilities = case["probabilities"]

    # Sanity: the generator must produce a genuinely below-threshold confidence.
    assert confidence < threshold

    answer = JevAnswer(
        choice=choice,
        probabilities=probabilities,
        confidence=confidence,
        high_consequence=None,
        model_version=None,
    )

    # The healthy set INCLUDES the choice, so a decision to fall back can only be
    # due to the confidence check (rule 4), which precedes the healthy-accept
    # rule (rule 5).
    decision = apply_policy(
        answer,
        configured=True,
        catalogue_ids=CANDIDATE_CATALOGUE,
        healthy={choice},
        threshold=threshold,
    )

    # Falls back to the Custom_Router with the low-confidence reason.
    assert decision.model_id is None
    assert decision.fallback is True
    assert decision.fallback_reason == REASON_LOW_CONFIDENCE

    # The reasoning names both the received confidence and the threshold. Match
    # against the same formatting the policy uses so the assertion tracks the
    # values, not an incidental substring.
    reasoning_text = " ".join(decision.reasoning)
    assert f"{confidence:.3f}" in reasoning_text
    assert f"{threshold:.3f}" in reasoning_text
