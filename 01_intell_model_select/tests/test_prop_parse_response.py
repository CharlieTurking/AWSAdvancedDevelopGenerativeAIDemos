"""Property test for Jev response parsing.

# Feature: jev-router-comparison, Property 5: Valid responses parse to the
# matching answer. For any well-formed Jev response body with a choice, finite
# probabilities in [0, 1], and a confidence in [0, 1], ``parse_response`` returns
# a ``JevAnswer`` whose choice, probabilities, and confidence equal the values in
# the body. The companion half of the property drives ``bad_bodies()`` from
# tests/strategies.py: every malformed or structurally invalid body must map to
# ``JevError("invalid_response")``.

Validates: Requirements 3.6
"""

from __future__ import annotations

import json
import math
from typing import Any, Dict, List, Optional

from hypothesis import given, settings
from hypothesis import strategies as st

from jev_client import JevAnswer, JevError, parse_response

from strategies import CATALOGUE_IDS, bad_bodies


# --------------------------------------------------------------------------- #
# Valid-response generator.
# --------------------------------------------------------------------------- #
# Build wire-format bodies in the exact shape ``parse_response`` consumes:
#   {"model": <str|null>, "answers": {"model_choice":
#       {"type": "choice", "choice": <catalogue id>,
#        "probabilities": {<id>: p, ...}, "confidence": c}
#     [, "high_consequence": {"type": "noul", "noul": h}]}}
# ``parse_response`` keeps only catalogue options in the returned probabilities,
# so every probability key here is a catalogue id and we pass the full catalogue
# as ``catalogue_ids``; that makes the returned map equal the body's map.

_unit_float = st.floats(
    min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False
)


@st.composite
def valid_bodies(draw: st.DrawFn) -> Dict[str, Any]:
    """A structurally valid Jev response as a JSON-ready dict.

    Returns the dict (not bytes) so the test can compare the parsed answer field
    by field against the exact values that went into the body.
    """
    choice = draw(st.sampled_from(CATALOGUE_IDS))

    # Probabilities over an arbitrary subset of the catalogue, each in [0, 1].
    prob_ids = draw(
        st.lists(
            st.sampled_from(CATALOGUE_IDS),
            unique=True,
            min_size=0,
            max_size=len(CATALOGUE_IDS),
        )
    )
    probabilities: Dict[str, float] = {
        model_id: draw(_unit_float) for model_id in prob_ids
    }

    confidence = draw(_unit_float)

    choice_answer: Dict[str, Any] = {
        "type": "choice",
        "choice": choice,
        "probabilities": probabilities,
        "confidence": confidence,
    }

    answers: Dict[str, Any] = {"model_choice": choice_answer}

    # Optional noul high-consequence answer.
    include_hc = draw(st.booleans())
    high_consequence: Optional[float] = None
    if include_hc:
        high_consequence = draw(_unit_float)
        answers["high_consequence"] = {"type": "noul", "noul": high_consequence}

    model_version = draw(st.one_of(st.none(), st.text(min_size=1, max_size=20)))

    body: Dict[str, Any] = {"answers": answers}
    if model_version is not None:
        body["model"] = model_version

    return {
        "_body": body,
        "choice": choice,
        "probabilities": probabilities,
        "confidence": confidence,
        "high_consequence": high_consequence,
        "model_version": model_version,
    }


# --------------------------------------------------------------------------- #
# Property 5 (the match half): valid bodies parse to the matching JevAnswer.
# --------------------------------------------------------------------------- #
@settings(max_examples=200)
@given(case=valid_bodies())
def test_valid_response_parses_to_matching_answer(case: Dict[str, Any]) -> None:
    body_bytes = json.dumps(case["_body"]).encode("utf-8")

    # Pass the full catalogue so no probability key is dropped; the returned map
    # then equals the body's probability map exactly.
    result = parse_response(body_bytes, CATALOGUE_IDS)

    assert isinstance(result, JevAnswer), f"expected JevAnswer, got {result!r}"

    assert result.choice == case["choice"]
    assert result.confidence == case["confidence"]
    assert result.probabilities == case["probabilities"]
    assert result.high_consequence == case["high_consequence"]
    assert result.model_version == case["model_version"]

    # Field invariants from the dataclass contract.
    assert math.isfinite(result.confidence) and 0.0 <= result.confidence <= 1.0
    for value in result.probabilities.values():
        assert math.isfinite(value) and 0.0 <= value <= 1.0
    if result.high_consequence is not None:
        assert 0.0 <= result.high_consequence <= 1.0


# --------------------------------------------------------------------------- #
# Property 5 (the invalid half): malformed bodies map to invalid_response.
# --------------------------------------------------------------------------- #
@settings(max_examples=300)
@given(body=bad_bodies())
def test_bad_bodies_map_to_invalid_response(body: bytes) -> None:
    result = parse_response(body, CATALOGUE_IDS)

    assert isinstance(result, JevError), f"expected JevError, got {result!r}"
    assert result.category == "invalid_response"


# --------------------------------------------------------------------------- #
# Probability keys outside the catalogue are ignored, not rejected: a valid
# answer with an extra non-catalogue probability still parses, and the extra key
# is dropped from the result (design: parse_response uses catalogue_ids only to
# ignore extra probability keys).
# --------------------------------------------------------------------------- #
@settings(max_examples=100)
@given(
    choice=st.sampled_from(CATALOGUE_IDS),
    confidence=_unit_float,
    kept=_unit_float,
    extra=_unit_float,
)
def test_extra_probability_keys_are_ignored(
    choice: str, confidence: float, kept: float, extra: float
) -> None:
    body = {
        "answers": {
            "model_choice": {
                "type": "choice",
                "choice": choice,
                "probabilities": {choice: kept, "some.other.model-v1:0": extra},
                "confidence": confidence,
            }
        }
    }
    result = parse_response(json.dumps(body).encode("utf-8"), CATALOGUE_IDS)

    assert isinstance(result, JevAnswer)
    assert result.probabilities == {choice: kept}
