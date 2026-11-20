"""Property test for Jev request construction (task 1.3).

# Feature: jev-router-comparison, Property 3: Request construction reflects the
# query, characteristics, and catalogue
#
# For any query text, derived characteristics, and catalogue, ``build_request``
# produces a payload whose ``state`` contains the query text and every
# characteristic value, whose ``model_choice`` question has exactly the
# catalogue model IDs as option keys with a non-empty description for each, and
# which contains a ``high_consequence`` boolean question if and only if the
# high-consequence signal is enabled.

Validates: Requirements 3.3, 3.4, 3.5

The test exercises the pure ``build_request`` function from ``jev_client`` with
Hypothesis-generated queries, characteristics, catalogues, and the
high-consequence flag. It reuses ``queries()`` and the real ``CATALOGUE_IDS``
from ``tests/strategies.py`` and composes characteristic and catalogue
generators from the characteristic keys the client forwards.
"""

from __future__ import annotations

from typing import Any, Dict

from hypothesis import given, settings
from hypothesis import strategies as st

# ``conftest.py`` puts ``lambda/`` on sys.path so these import by bare name,
# exactly as the Lambda runtime loads them.
import jev_client
from jev_client import CHOICE_KEY, HIGH_CONSEQUENCE_KEY, build_request

from strategies import CATALOGUE_IDS, queries


# --------------------------------------------------------------------------- #
# Generators composed from the catalogue and the client's characteristic keys.
# --------------------------------------------------------------------------- #

# The characteristic keys ``build_request`` forwards into ``state`` (mirrors the
# signals the Custom_Router derives from QueryAnalyzer). Kept in sync with
# jev_client._CHARACTERISTIC_KEYS so the test asserts on exactly what the client
# promises to forward.
_CHARACTERISTIC_KEYS = (
    "length",
    "complexity_score",
    "estimated_tokens",
    "requires_reasoning",
    "requires_creativity",
    "requires_code",
    "requires_analysis",
)


@st.composite
def characteristics(draw: st.DrawFn) -> Dict[str, Any]:
    """A derived-characteristics map over the keys the client forwards.

    Every forwarded key is present (so the property can assert that *every*
    characteristic value reaches ``state``). Numeric signals get realistic
    finite values and the ``requires_*`` signals are booleans.
    """
    finite_floats = st.floats(
        min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False
    )
    return {
        "length": draw(st.integers(min_value=0, max_value=10_000)),
        "complexity_score": draw(finite_floats),
        "estimated_tokens": draw(st.integers(min_value=0, max_value=5_000)),
        "requires_reasoning": draw(st.booleans()),
        "requires_creativity": draw(st.booleans()),
        "requires_code": draw(st.booleans()),
        "requires_analysis": draw(st.booleans()),
    }


@st.composite
def catalogues(draw: st.DrawFn) -> Dict[str, str]:
    """A non-empty mapping of catalogue model ID -> non-empty description.

    Option keys are drawn from the real Candidate_Catalogue IDs (which include
    ``.``, ``:`` and ``-``) so the option-key format is exercised. Descriptions
    are non-empty strings, matching what ``describe_capability`` produces.
    """
    model_ids = draw(
        st.lists(
            st.sampled_from(CATALOGUE_IDS),
            unique=True,
            min_size=1,
            max_size=len(CATALOGUE_IDS),
        )
    )
    descriptions = {}
    for model_id in model_ids:
        descriptions[model_id] = draw(st.text(min_size=1, max_size=120))
    return descriptions


# --------------------------------------------------------------------------- #
# Property 3
# --------------------------------------------------------------------------- #


@settings(max_examples=300)
@given(
    query_text=queries(),
    chars=characteristics(),
    catalogue=catalogues(),
    model=st.text(min_size=1, max_size=20),
    include_hc=st.booleans(),
)
def test_build_request_reflects_query_characteristics_and_catalogue(
    query_text: str,
    chars: Dict[str, Any],
    catalogue: Dict[str, str],
    model: str,
    include_hc: bool,
) -> None:
    payload = build_request(
        query_text=query_text,
        characteristics=chars,
        catalogue=catalogue,
        model=model,
        include_high_consequence=include_hc,
    )

    # --- state contains the query text and every characteristic value (3.3) ---
    state = payload["state"]
    assert state["query"] == query_text

    forwarded = state["characteristics"]
    for key, value in chars.items():
        assert key in forwarded, f"characteristic {key!r} was dropped from state"
        assert forwarded[key] == value

    # --- model_choice question has exactly the catalogue IDs as option keys,
    #     each with a non-empty description (3.4) ---
    questions = payload["questions"]
    assert CHOICE_KEY in questions
    choice_question = questions[CHOICE_KEY]
    assert choice_question["type"] == "choice"

    criteria = choice_question["criteria"]
    assert set(criteria.keys()) == set(catalogue.keys())
    for model_id, description in criteria.items():
        assert isinstance(description, str)
        assert description != "", f"empty description for option {model_id!r}"

    # --- high_consequence boolean question present iff the signal is enabled (3.5) ---
    assert (HIGH_CONSEQUENCE_KEY in questions) == include_hc
    if include_hc:
        hc_question = questions[HIGH_CONSEQUENCE_KEY]
        # The design maps the Boolean question to Jev's "noul" primitive.
        assert hc_question["type"] == "noul"

    # The pinned model ID is carried through unchanged.
    assert payload["model"] == model


def test_characteristic_keys_in_sync_with_client() -> None:
    """Guard: the test's forwarded-key list matches the client's constant.

    If jev_client changes which characteristics it forwards, this fails loudly
    rather than letting the property silently stop covering a key.
    """
    assert tuple(_CHARACTERISTIC_KEYS) == tuple(jev_client._CHARACTERISTIC_KEYS)
