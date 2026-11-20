"""Property tests for ``derive_circuit_state`` circuit-state derivation.

These tests import the pure helper from ``app.py`` (made importable via ``conftest.py``)
and verify that the derived OPEN/CLOSED circuit state matches the "unexpired item exists"
condition across arbitrary low-level DynamoDB ``CircuitBreaker`` item lists and times.
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from app import derive_circuit_state


# Epoch values stay within a plausible-but-wide positive range so comparisons are
# meaningful without risking overflow or degenerate generation.
_EPOCH = st.integers(min_value=0, max_value=4_000_000_000)


def _item(expire_epoch, service="svc", status="OPEN"):
    """Build a low-level DynamoDB ``CircuitBreaker`` item shape.

    ``ExpireTimeStamp`` is encoded as ``{"N": "<epoch-int-as-string>"}``, matching how the
    DynamoDB low-level ``query`` returns Number attributes. Extra attributes (``ServiceName``,
    ``CircuitStatus``) are included to confirm the helper ignores everything but the TTL.
    """
    return {
        "ServiceName": {"S": service},
        "CircuitStatus": {"S": status},
        "ExpireTimeStamp": {"N": str(expire_epoch)},
    }


# A list of items, each described by its integer expire epoch.
_ITEMS = st.lists(_EPOCH, max_size=20).map(lambda epochs: [_item(e) for e in epochs])


# Feature: streamlit-circuit-breaker-ui, Property 8: Circuit state is OPEN exactly when an unexpired item exists
# Validates: Requirements 5.2, 5.3
@settings(max_examples=200)
@given(items=_ITEMS, now_epoch=_EPOCH)
def test_derive_circuit_state_open_iff_unexpired_item_exists(items, now_epoch):
    """``derive_circuit_state`` is OPEN iff some item's ``ExpireTimeStamp > now_epoch``.

    For any set of queried ``CircuitBreaker`` items and any current time, the derived state
    is OPEN if and only if at least one item is unexpired (its ``ExpireTimeStamp`` is strictly
    greater than ``now_epoch``); otherwise it is CLOSED.
    """
    has_unexpired = any(int(item["ExpireTimeStamp"]["N"]) > now_epoch for item in items)
    expected = "OPEN" if has_unexpired else "CLOSED"

    assert derive_circuit_state(items, now_epoch) == expected


# Feature: streamlit-circuit-breaker-ui, Property 8: Circuit state is OPEN exactly when an unexpired item exists
# Validates: Requirements 5.2, 5.3
@settings(max_examples=100)
@given(now_epoch=_EPOCH)
def test_derive_circuit_state_empty_is_closed(now_epoch):
    """With no items there is nothing unexpired, so the circuit is CLOSED."""
    assert derive_circuit_state([], now_epoch) == "CLOSED"
