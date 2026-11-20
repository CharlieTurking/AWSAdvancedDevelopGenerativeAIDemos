"""Property test for targeted-row update of the execution history.

# Feature: streamlit-circuit-breaker-ui, Property 9: Updating an execution changes only the targeted row
# Validates: Requirements 6.3

Property: For any execution history and any execution id present in it, ``update_execution``
applied with a new status and result preserves the history length, changes only the matching
record's status and result (every other field of that record stays the same), and leaves
every other record unchanged. The operation is pure: neither the input list nor any of its
records is mutated.
"""

import copy
import datetime

from hypothesis import given, settings, strategies as st

from app import ExecutionRecord, update_execution


# Distinct, sortable base datetimes keep start_time a real ``datetime`` without making
# equality comparisons fragile; the exact instant is irrelevant to this property.
_BASE_TIME = datetime.datetime(2024, 1, 1, 0, 0, 0)

# Raw Step Functions statuses and their classified results. The property only cares that the
# new status/result are written verbatim, so any strings drawn from a realistic alphabet
# work; empty strings are allowed to exercise the boundary.
_STATUSES = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=126),
    max_size=20,
)
_RESULTS = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=126),
    max_size=20,
)


@st.composite
def _histories(draw):
    """Build a non-empty list of ExecutionRecord with unique execution_arn values.

    Returns the ``history`` list together with the index of the record selected for update
    and the new ``status``/``result`` to apply to it.
    """
    size = draw(st.integers(min_value=1, max_value=8))

    # Unique execution_arn values so exactly one record matches the targeted arn.
    arns = draw(
        st.lists(
            st.text(
                alphabet=st.characters(min_codepoint=33, max_codepoint=126),
                min_size=1,
                max_size=30,
            ),
            min_size=size,
            max_size=size,
            unique=True,
        )
    )

    history = []
    for i, arn in enumerate(arns):
        history.append(
            ExecutionRecord(
                execution_arn=arn,
                short_id=draw(st.text(max_size=12)),
                target=draw(st.sampled_from(["HelloWorldFunction", "TestCircuitBreakerFunction"])),
                start_time=_BASE_TIME + datetime.timedelta(seconds=i),
                status=draw(_STATUSES),
                result=draw(_RESULTS),
            )
        )

    target_index = draw(st.integers(min_value=0, max_value=size - 1))
    new_status = draw(_STATUSES)
    new_result = draw(_RESULTS)
    return history, target_index, new_status, new_result


@settings(max_examples=200)
@given(data=_histories())
def test_update_changes_only_targeted_row(data):
    history, target_index, new_status, new_result = data
    target_arn = history[target_index].execution_arn

    # Deep snapshot of the input so we can assert purity (no mutation of the input).
    original = copy.deepcopy(history)

    updated = update_execution(history, target_arn, new_status, new_result)

    # Length and order are preserved.
    assert len(updated) == len(history)

    # The matched record carries the new status/result; all other fields are unchanged.
    matched = updated[target_index]
    before = original[target_index]
    assert matched.status == new_status
    assert matched.result == new_result
    assert matched.execution_arn == before.execution_arn
    assert matched.short_id == before.short_id
    assert matched.target == before.target
    assert matched.start_time == before.start_time

    # Every other record is identical to the original (same values, position preserved).
    for i, (new_rec, old_rec) in enumerate(zip(updated, original)):
        if i == target_index:
            continue
        assert new_rec == old_rec

    # Purity: the input list and all of its records are untouched.
    assert history == original
    assert history[target_index].status == original[target_index].status
    assert history[target_index].result == original[target_index].result
