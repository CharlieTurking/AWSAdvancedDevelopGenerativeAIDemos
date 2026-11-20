from hypothesis import given, settings, strategies as st

from app import (
    STATUS_AWS_ERROR,
    STATUS_NO_CREDENTIALS,
    STATUS_READY,
    STATUS_REGION_NOT_CONFIGURED,
    STATUS_RESOURCE_MISSING,
    STATUS_STACK_NOT_FOUND,
    can_start,
)

NON_READY = [
    STATUS_REGION_NOT_CONFIGURED,
    STATUS_NO_CREDENTIALS,
    STATUS_STACK_NOT_FOUND,
    STATUS_RESOURCE_MISSING,
    STATUS_AWS_ERROR,
]


# Feature: streamlit-circuit-breaker-ui, Property 4: No connectivity blocks starting executions
# Validates: Requirements 2.5
@settings(max_examples=100)
@given(status=st.one_of(st.sampled_from(NON_READY), st.text()).filter(lambda s: s != STATUS_READY))
def test_non_ready_status_blocks_start(status):
    assert can_start(status) is False


def test_ready_allows_start():
    assert can_start(STATUS_READY) is True
