"""Property 4: Request payload JSON round trip.

For any valid request payload produced by ``build_request``, serialising it to
JSON and parsing it back yields an equivalent payload.

**Validates: Requirements 3.9**

The payloads ``build_request`` returns are plain, JSON-serialisable dicts
(``model``, ``state``, ``questions``). This property fixes the contract that
nothing in the payload defeats a JSON round trip: no non-serialisable value,
no NaN/Infinity float that would survive ``json.dumps`` but change meaning, and
no key that is not a string once encoded. ``json.dumps`` followed by
``json.loads`` must return a structure equal to the original dict.

The generators here reuse ``queries()`` from ``tests/strategies.py`` for the
query text and ``CATALOGUE_IDS`` for the option keys, and build the derived
query characteristics locally over exactly the keys ``build_request`` forwards
(see ``jev_client._CHARACTERISTIC_KEYS``). Characteristics are drawn over a mix
of the realistic types the ``QueryAnalyzer`` emits (ints, bounded floats,
bools) plus extra keys that ``build_request`` must ignore, so the test exercises
the real forwarding behaviour rather than a hand-picked happy path.
"""

from __future__ import annotations

from typing import Any, Dict, List

import json

from hypothesis import given, settings
from hypothesis import strategies as st

from jev_client import build_request

from strategies import CATALOGUE_IDS, queries


# The characteristic keys build_request forwards into state.characteristics.
# Kept in sync with jev_client._CHARACTERISTIC_KEYS.
_NUMERIC_CHARACTERISTICS = ("length", "complexity_score", "estimated_tokens")
_BOOLEAN_CHARACTERISTICS = (
    "requires_reasoning",
    "requires_creativity",
    "requires_code",
    "requires_analysis",
)

# JSON-safe finite floats (no NaN / Infinity, which would not round-trip under
# strict JSON and are not something QueryAnalyzer ever emits).
_finite_floats = st.floats(allow_nan=False, allow_infinity=False, width=64)


@st.composite
def characteristics(draw: st.DrawFn) -> Dict[str, Any]:
    """A derived-characteristics map like the one QueryAnalyzer produces.

    Each known key is present with a plausibly typed value. A handful of extra
    keys with arbitrary JSON-safe values are added too; build_request forwards
    only the known keys, so these should never appear in the payload, and their
    presence should not affect the round trip.
    """
    chars: Dict[str, Any] = {}
    for key in _NUMERIC_CHARACTERISTICS:
        chars[key] = draw(
            st.one_of(st.integers(min_value=0, max_value=100_000), _finite_floats)
        )
    for key in _BOOLEAN_CHARACTERISTICS:
        chars[key] = draw(st.booleans())

    # Extra, irrelevant keys build_request must ignore.
    extra = draw(
        st.dictionaries(
            keys=st.text(min_size=1, max_size=12).filter(
                lambda k: k not in _NUMERIC_CHARACTERISTICS
                and k not in _BOOLEAN_CHARACTERISTICS
            ),
            values=st.one_of(
                _finite_floats,
                st.integers(),
                st.booleans(),
                st.text(max_size=20),
                st.none(),
            ),
            max_size=4,
        )
    )
    chars.update(extra)
    return chars


@st.composite
def catalogues(draw: st.DrawFn) -> Dict[str, str]:
    """A catalogue mapping model ID -> short, non-empty description.

    Option keys are a non-empty subset of the real Candidate_Catalogue IDs so
    the test uses the actual option-key format (which contains ``.``, ``:`` and
    ``-``).
    """
    ids: List[str] = draw(
        st.lists(st.sampled_from(CATALOGUE_IDS), min_size=1, unique=True)
    )
    return {
        model_id: draw(st.text(min_size=1, max_size=60)) for model_id in ids
    }


# A pinned, versioned model ID like the one jev_client defaults to, plus a few
# alternative shapes so the field is exercised beyond a single literal.
_models = st.one_of(
    st.just("jev-1.13.0"),
    st.from_regex(r"jev-[0-9]+\.[0-9]+\.[0-9]+", fullmatch=True),
    st.text(min_size=1, max_size=20),
)


@settings(max_examples=300)
@given(
    query_text=queries(),
    chars=characteristics(),
    catalogue=catalogues(),
    model=_models,
    include_high_consequence=st.booleans(),
)
def test_payload_json_round_trips(
    query_text: str,
    chars: Dict[str, Any],
    catalogue: Dict[str, str],
    model: str,
    include_high_consequence: bool,
) -> None:
    """A build_request payload equals itself after a JSON serialise/parse cycle."""
    payload = build_request(
        query_text=query_text,
        characteristics=chars,
        catalogue=catalogue,
        model=model,
        include_high_consequence=include_high_consequence,
    )

    # Serialise to JSON and parse it back. allow_nan=False makes the serialise
    # step itself assert there is no NaN/Infinity hiding in the payload, since
    # such a value round-trips through json.dumps' default mode but is not valid
    # JSON and would change meaning for any strict consumer (the Jev API).
    encoded = json.dumps(payload, allow_nan=False)
    decoded = json.loads(encoded)

    # Structural equivalence: the parsed payload equals the original dict.
    assert decoded == payload


@settings(max_examples=300)
@given(
    query_text=queries(),
    chars=characteristics(),
    catalogue=catalogues(),
    model=_models,
    include_high_consequence=st.booleans(),
)
def test_round_trip_is_idempotent(
    query_text: str,
    chars: Dict[str, Any],
    catalogue: Dict[str, str],
    model: str,
    include_high_consequence: bool,
) -> None:
    """Re-serialising the parsed payload reproduces the same structure again.

    This guards against a value that compares equal but serialises differently
    (for example an int/float ambiguity), ensuring the round trip is stable, not
    just equal once.
    """
    payload = build_request(
        query_text=query_text,
        characteristics=chars,
        catalogue=catalogue,
        model=model,
        include_high_consequence=include_high_consequence,
    )

    once = json.loads(json.dumps(payload, allow_nan=False))
    twice = json.loads(json.dumps(once, allow_nan=False))

    assert once == twice == payload
