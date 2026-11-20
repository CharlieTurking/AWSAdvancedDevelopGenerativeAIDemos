"""Property test for most-recent-first Execution_History ordering.

# Feature: streamlit-circuit-breaker-ui, Property 10: History is ordered most-recent-first
# Validates: Requirements 6.4

Property: For any execution history, ``ordered_history`` returns a permutation of the input
sorted by ``start_time`` in non-increasing order (most recent first), and it does not mutate
the input list.
"""

import copy
import datetime

from hypothesis import given, settings, strategies as st

from app import ExecutionRecord, ordered_history


# A pool of datetimes with a bounded range so that ties (equal start_time values) occur
# frequently, exercising the stable-permutation and non-increasing guarantees together.
_start_times = st.datetimes(
    min_value=datetime.datetime(2020, 1, 1),
    max_value=datetime.datetime(2020, 1, 8),
)


@st.composite
def _execution_records(draw):
    """Generate a single ExecutionRecord with a varied start_time (ties allowed)."""
    suffix = draw(st.text(min_size=0, max_size=12))
    return ExecutionRecord(
        execution_arn=f"arn:aws:states:us-east-1:000000000000:execution:sm:{suffix}",
        short_id=suffix or "exec",
        target=draw(st.sampled_from(["HelloWorldFunction", "TestCircuitBreakerFunction"])),
        start_time=draw(_start_times),
        status=draw(st.sampled_from(["RUNNING", "SUCCEEDED", "FAILED", "TIMED_OUT", "ABORTED", "UNKNOWN"])),
        result=draw(st.sampled_from(["RUNNING", "SUCCESS", "FAIL", "UNKNOWN"])),
    )


def _multiset_key(rec):
    """A hashable identity for a record so lists can be compared as multisets."""
    return (rec.execution_arn, rec.short_id, rec.target, rec.start_time, rec.status, rec.result)


@settings(max_examples=200)
@given(history=st.lists(_execution_records(), max_size=30))
def test_ordered_history_is_sorted_permutation_and_pure(history):
    # Snapshot the input to verify purity (no mutation of the argument).
    before = copy.deepcopy(history)

    result = ordered_history(history)

    # 1. Permutation: the result contains exactly the same records (same multiset).
    def sorted_keys(items):
        return sorted(
            (_multiset_key(r) for r in items),
            key=lambda k: (k[3], k[0], k[1], k[2], k[4], k[5]),
        )

    assert sorted_keys(result) == sorted_keys(history)
    assert len(result) == len(history)

    # 2. Non-increasing: start_time values never increase across the result.
    times = [rec.start_time for rec in result]
    assert all(times[i] >= times[i + 1] for i in range(len(times) - 1))

    # 3. Purity: the input list order and contents are unchanged.
    assert history == before
    assert [_multiset_key(r) for r in history] == [_multiset_key(r) for r in before]
