"""Hypothesis generators for the jev-router-comparison property tests.

These strategies describe the input spaces the correctness properties quantify
over (see design.md "Generators"). They intentionally emit plain Python data
(dicts, strings, bytes, sets) rather than importing the yet-to-be-written
``jev_client`` dataclasses, so this module is importable on its own and the
property-test tasks (1.3-1.6, 3.2-3.11, 5.x) can adapt the data into whatever
concrete types their module under test exposes.

Public generators:
    jev_outcomes()   - a valid answer, a categorised error, or "not configured"
    health_states()  - any subset of the catalogue as the healthy-model set
    bad_bodies()     - response bytes that must map to ``invalid_response``
    queries()        - arbitrary query text within the 10,000 char limit
    api_keys()       - printable key-like strings, length 8-64
"""

from __future__ import annotations

import json
import math
from typing import Any, Dict, FrozenSet, List

from hypothesis import strategies as st

# --------------------------------------------------------------------------- #
# The Candidate_Catalogue model IDs (design.md: Candidate_Catalogue).
# Kept here as literals so strategies do not depend on importing the Lambda
# modules. The full model IDs deliberately include ".", ":" and "-" so the
# generators exercise the real option-key format.
# --------------------------------------------------------------------------- #
CATALOGUE_IDS: List[str] = [
    "us.anthropic.claude-haiku-4-5-20251001-v1:0",  # Claude Haiku 4.5
    "openai.gpt-oss-20b-1:0",                        # GPT-OSS 20B
    "amazon.nova-pro-v1:0",                          # Nova Pro
    "amazon.nova-lite-v1:0",                         # Nova Lite
    "amazon.nova-micro-v1:0",                        # Nova Micro
]

# Error categories call_jev is allowed to produce.
ERROR_CATEGORIES: List[str] = ["timeout", "http_error", "invalid_response"]

# A sentinel kind for the "Jev is not configured" outcome. Outcomes are tagged
# dicts so tests can pattern-match on ``kind`` without importing jev_client.
NOT_CONFIGURED: Dict[str, Any] = {"kind": "not_configured"}


# --------------------------------------------------------------------------- #
# queries()
# --------------------------------------------------------------------------- #
@st.composite
def queries(draw: st.DrawFn, max_size: int = 10_000) -> str:
    """Arbitrary Unicode query text within the request size limit.

    Includes whitespace-only and very short strings so tests cover the edges
    around validation. Surrogate code points are excluded because they cannot
    be JSON-encoded, which would be a test-harness artefact rather than a real
    query.
    """
    return draw(
        st.text(
            alphabet=st.characters(
                blacklist_categories=("Cs",),  # exclude lone surrogates
            ),
            min_size=0,
            max_size=max_size,
        )
    )


# --------------------------------------------------------------------------- #
# api_keys()
# --------------------------------------------------------------------------- #
@st.composite
def api_keys(draw: st.DrawFn) -> str:
    """Printable, key-shaped strings of length 8-64.

    Used both as the Bearer value and embedded into fake exception messages so
    the non-leakage properties can prove the key never reaches logs, responses,
    or error text.
    """
    return draw(
        st.text(
            alphabet=st.characters(
                min_codepoint=33,   # '!' - printable, no spaces/control chars
                max_codepoint=126,  # '~'
            ),
            min_size=8,
            max_size=64,
        )
    )


# --------------------------------------------------------------------------- #
# health_states()
# --------------------------------------------------------------------------- #
@st.composite
def health_states(draw: st.DrawFn) -> FrozenSet[str]:
    """Any subset of the catalogue as the healthy-model set.

    Includes the empty set (the all-unhealthy edge case the policy must handle
    by falling back / propagating the Custom_Router error).
    """
    chosen = draw(
        st.lists(
            st.sampled_from(CATALOGUE_IDS),
            unique=True,
            min_size=0,
            max_size=len(CATALOGUE_IDS),
        )
    )
    return frozenset(chosen)


# --------------------------------------------------------------------------- #
# jev_outcomes()
# --------------------------------------------------------------------------- #
@st.composite
def _probabilities(draw: st.DrawFn) -> Dict[str, float]:
    """A probability map over the catalogue IDs, each value in [0, 1].

    Values are drawn independently in [0, 1]; they are not normalised to sum to
    1 on purpose, so the policy is exercised against both tidy and untidy
    distributions.
    """
    probs: Dict[str, float] = {}
    for model_id in CATALOGUE_IDS:
        probs[model_id] = draw(
            st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)
        )
    return probs


@st.composite
def valid_answers(draw: st.DrawFn) -> Dict[str, Any]:
    """A structurally valid Jev answer as a tagged dict.

    The ``choice`` is sometimes a catalogue member and sometimes arbitrary text
    so that both the "recognised" and "unrecognised" policy branches are hit.
    """
    use_catalogue_choice = draw(st.booleans())
    if use_catalogue_choice:
        choice = draw(st.sampled_from(CATALOGUE_IDS))
    else:
        choice = draw(st.text(min_size=1, max_size=40))

    confidence = draw(
        st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)
    )
    include_hc = draw(st.booleans())
    high_consequence = (
        draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
        if include_hc
        else None
    )

    return {
        "kind": "answer",
        "choice": choice,
        "probabilities": draw(_probabilities()),
        "confidence": confidence,
        "high_consequence": high_consequence,
        "model_version": draw(st.one_of(st.none(), st.text(min_size=1, max_size=20))),
    }


@st.composite
def jev_errors(draw: st.DrawFn) -> Dict[str, Any]:
    """A categorised Jev error as a tagged dict.

    ``http_error`` carries a status code; the others carry ``None`` to match
    the design's error mapping.
    """
    category = draw(st.sampled_from(ERROR_CATEGORIES))
    if category == "http_error":
        status_code = draw(st.sampled_from([401, 422, 429, 500, 502, 529]))
    else:
        status_code = None
    return {"kind": "error", "category": category, "status_code": status_code}


@st.composite
def jev_outcomes(draw: st.DrawFn) -> Dict[str, Any]:
    """One of: a valid answer, a categorised error, or "not configured".

    This is the top-level outcome space the router-level properties quantify
    over (Property 7, Property 13, Property 17, ...).
    """
    return draw(
        st.one_of(
            valid_answers(),
            jev_errors(),
            st.just(NOT_CONFIGURED),
        )
    )


# --------------------------------------------------------------------------- #
# bad_bodies()
# --------------------------------------------------------------------------- #
def _non_json_bytes() -> st.SearchStrategy[bytes]:
    """Bytes that are not valid JSON."""
    return st.one_of(
        st.just(b""),
        st.just(b"not json at all"),
        st.just(b"{unclosed"),
        st.binary(min_size=1, max_size=32).filter(_is_not_json),
    )


def _is_not_json(data: bytes) -> bool:
    try:
        json.loads(data.decode("utf-8"))
        return False
    except Exception:
        return True


@st.composite
def _wrong_type_json(draw: st.DrawFn) -> bytes:
    """Valid JSON whose top-level type is not an object."""
    value = draw(
        st.one_of(
            st.integers(),
            st.floats(allow_nan=False, allow_infinity=False),
            st.text(max_size=10),
            st.lists(st.integers(), max_size=3),
            st.booleans(),
            st.none(),
        )
    )
    return json.dumps(value).encode("utf-8")


@st.composite
def _missing_answers(draw: st.DrawFn) -> bytes:
    """A JSON object lacking the expected ``answers.model_choice`` structure."""
    shape = draw(
        st.sampled_from(
            [
                {},
                {"model": "jev-1.13.0"},
                {"answers": {}},
                {"answers": {"other_question": {"choice": "x"}}},
                {"answers": "not-an-object"},
            ]
        )
    )
    return json.dumps(shape).encode("utf-8")


@st.composite
def _out_of_range_or_nonfinite(draw: st.DrawFn) -> bytes:
    """A well-structured answer whose numbers are out of range or non-finite.

    ``NaN`` and infinities are not valid JSON per the strict spec, so they are
    written into the string directly (parsers in the module under test may
    accept them with the default float handling, which is exactly what the
    ``invalid_response`` path must reject).
    """
    bad_number = draw(
        st.sampled_from(["NaN", "Infinity", "-Infinity", "-0.5", "1.5", "42"])
    )
    choice = draw(st.sampled_from(CATALOGUE_IDS))
    # Hand-assemble so we can embed the non-finite literals verbatim.
    body = (
        '{"model": "jev-1.13.0", "answers": {"model_choice": '
        '{"type": "choice", "choice": "' + choice + '", '
        '"probabilities": {"' + choice + '": ' + bad_number + '}, '
        '"confidence": ' + bad_number + '}}}'
    )
    return body.encode("utf-8")


@st.composite
def _wrong_choice_type(draw: st.DrawFn) -> bytes:
    """A structurally present answer whose ``choice`` is not a string."""
    non_string_choice = draw(
        st.sampled_from(["123", "true", "null", "[\"a\"]", "{\"k\": 1}"])
    )
    body = (
        '{"answers": {"model_choice": '
        '{"type": "choice", "choice": ' + non_string_choice + ', '
        '"probabilities": {}, "confidence": 0.9}}}'
    )
    return body.encode("utf-8")


@st.composite
def bad_bodies(draw: st.DrawFn) -> bytes:
    """Response bytes that ``parse_response`` must reject as invalid.

    Covers non-JSON, JSON of the wrong top-level type, missing answer keys,
    non-string ``choice``, and out-of-range / non-finite numbers (Property 6).
    """
    return draw(
        st.one_of(
            _non_json_bytes(),
            _wrong_type_json(),
            _missing_answers(),
            _wrong_choice_type(),
            _out_of_range_or_nonfinite(),
        )
    )
