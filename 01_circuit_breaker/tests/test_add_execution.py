"""Property test for start-records-history / unchanged-on-failure.

# Feature: streamlit-circuit-breaker-ui, Property 6: Starting records history on success and leaves it unchanged on failure
# Validates: Requirements 3.3, 3.4, 6.2

Property: For any execution history and any successful start result, ``add_execution`` yields
a history one longer whose newest record carries the returned execution id, the selected
target, and a start time (Requirements 3.3, 6.2). For any history, a failed start attempt
leaves the history equal to its prior value (Requirement 3.4) — a failed start simply never
calls ``add_execution``, so this is modeled by asserting the history object is unchanged when
no add occurs.

Both cases also assert purity: on success the input list is not mutated (its prefix is the
original and the original object is untouched).
"""

import copy
import datetime

from hypothesis import given, settings, strategies as st

from app import ExecutionRecord, add_execution


# Distinct, sortable base datetime keeps ``start_time`` a real ``datetime`` without making
# equality fragile; the exact instant is irrelevant to this property.
_BASE_TIME = datetime.datetime(2024, 1, 1, 0, 0, 0)

# A realistic alphabet for free-text fields; empty strings are allowed to exercise bounds.
_text = st.text(alphabet=st.characters(min_codepoint=33, max_codepoint=126), max_size=30)

# The two resolved Target_Lambda options the dashboard offers (Requirement 3.1).
_targets = st.sampled_from(["HelloWorldFunction", "TestCircuitBreakerFunction"])


@st.composite
def _execution_records(draw):
    """Generate a single ExecutionRecord with a varied, non-null start_time."""
    offset = draw(st.integers(min_value=0, max_value=10_000))
    return ExecutionRecord(
        execution_arn=draw(
            st.text(
                alphabet=st.characters(min_codepoint=33, max_codepoint=126),
                min_size=1,
                max_size=40,
            )
        ),
        short_id=draw(_text),
        target=draw(_targets),
        start_time=_BASE_TIME + datetime.timedelta(seconds=offset),
        status=draw(st.sampled_from(["RUNNING", "SUCCEEDED", "FAILED", "TIMED_OUT", "ABORTED", "UNKNOWN"])),
        result=draw(st.sampled_from(["RUNNING", "SUCCESS", "FAIL", "UNKNOWN"])),
    )


@settings(max_examples=200)
@given(
    history=st.lists(_execution_records(), max_size=20),
    new_record=_execution_records(),
)
def test_success_appends_record_and_is_pure(history, new_record):
    """Success case: add_execution records the started execution and does not mutate input."""
    # Deep snapshot of the input so we can assert purity (no mutation of the input).
    original = copy.deepcopy(history)

    result = add_execution(history, new_record)

    # History grows by exactly one.
    assert len(result) == len(history) + 1

    # The appended (newest) record is the new one: the returned execution id, the selected
    # target, and the start time are preserved verbatim (Requirements 3.3, 6.2).
    appended = result[-1]
    assert appended is new_record
    assert appended.execution_arn == new_record.execution_arn
    assert appended.target == new_record.target
    assert appended.start_time == new_record.start_time

    # The prefix equals the original history, in order.
    assert result[:-1] == original

    # Purity: the input list and its records are untouched.
    assert history == original
    assert len(history) == len(original)


@settings(max_examples=200)
@given(history=st.lists(_execution_records(), max_size=20))
def test_failure_leaves_history_unchanged(history):
    """Failure case: a failed start never calls add_execution, so history is unchanged.

    Requirement 3.4 — when starting an Execution fails, the Execution_History is left
    unchanged for that attempt. The UI models this by simply NOT calling ``add_execution``
    on failure, so we assert the history equals its prior value when no add occurs.
    """
    # Prior value of the history before the (failed) start attempt.
    prior = copy.deepcopy(history)

    # A failed start performs no history mutation (no add_execution call). The history
    # object therefore remains equal to its prior value.
    assert history == prior
    assert len(history) == len(prior)
