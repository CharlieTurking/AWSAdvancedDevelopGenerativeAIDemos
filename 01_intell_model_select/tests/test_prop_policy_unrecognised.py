"""Property test for the Routing_Policy "unrecognised answer" branch.

# Feature: jev-router-comparison, Property 8: Unrecognised answers fall back.
# For any choice string that is not in the Candidate_Catalogue, the
# Routing_Policy falls back and the reasoning states that the answer was
# unrecognised. This is rule 3 of the policy ladder (design.md section 3),
# which is checked BEFORE the confidence rule, so the confidence of the
# unrecognised answer is irrelevant and is generated freely here.

Validates: Requirements 4.2
"""

from __future__ import annotations

from typing import Dict

from hypothesis import given, settings
from hypothesis import strategies as st

from jev_router import (
    CANDIDATE_CATALOGUE,
    REASON_UNRECOGNISED,
    PolicyDecision,
    apply_policy,
)
from jev_client import JevAnswer

from strategies import CATALOGUE_IDS, health_states


# --------------------------------------------------------------------------- #
# Generators.
# --------------------------------------------------------------------------- #
# A choice string that is NOT a Candidate_Catalogue member. We draw arbitrary
# text and filter out the (measure-zero) chance of landing on a real catalogue
# id, so the generated answer always exercises the unrecognised branch.
_CATALOGUE_SET = frozenset(CANDIDATE_CATALOGUE)

_unit_float = st.floats(
    min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False
)


@st.composite
def unrecognised_choices(draw: st.DrawFn) -> str:
    """Any non-empty string that is not a catalogue model id."""
    return draw(
        st.text(min_size=1, max_size=60).filter(lambda s: s not in _CATALOGUE_SET)
    )


@st.composite
def _probabilities(draw: st.DrawFn) -> Dict[str, float]:
    """A probability map over the catalogue ids, each value in [0, 1]."""
    return {model_id: draw(_unit_float) for model_id in CATALOGUE_IDS}


@st.composite
def unrecognised_answers(draw: st.DrawFn) -> JevAnswer:
    """A structurally valid JevAnswer whose ``choice`` is not in the catalogue.

    Confidence is drawn freely across [0, 1] (including values at or above any
    threshold) because the catalogue check precedes the confidence check in the
    policy ladder, so the unrecognised outcome must not depend on it.
    """
    include_hc = draw(st.booleans())
    return JevAnswer(
        choice=draw(unrecognised_choices()),
        probabilities=draw(_probabilities()),
        confidence=draw(_unit_float),
        high_consequence=draw(_unit_float) if include_hc else None,
        model_version=draw(st.one_of(st.none(), st.text(min_size=1, max_size=20))),
    )


# Thresholds in (0, 1]: exclude 0.0 so the interval is open at the low end.
_thresholds = st.floats(
    min_value=0.0,
    max_value=1.0,
    exclude_min=True,
    allow_nan=False,
    allow_infinity=False,
)


# --------------------------------------------------------------------------- #
# Property 8: Unrecognised answers fall back.
# --------------------------------------------------------------------------- #
@settings(max_examples=300)
@given(
    answer=unrecognised_answers(),
    healthy=health_states(),
    threshold=_thresholds,
)
def test_unrecognised_answer_falls_back(
    answer: JevAnswer, healthy: frozenset, threshold: float
) -> None:
    decision = apply_policy(
        answer,
        configured=True,
        catalogue_ids=CANDIDATE_CATALOGUE,
        healthy=healthy,
        threshold=threshold,
    )

    assert isinstance(decision, PolicyDecision)

    # The choice really is outside the catalogue (generator invariant).
    assert answer.choice not in _CATALOGUE_SET

    # A fallback with no accepted model and the stable "unrecognised" reason.
    assert decision.model_id is None
    assert decision.fallback is True
    assert decision.fallback_reason == REASON_UNRECOGNISED

    # The reasoning explains the answer was unrecognised.
    joined = " ".join(decision.reasoning).lower()
    assert "unrecognised" in joined
