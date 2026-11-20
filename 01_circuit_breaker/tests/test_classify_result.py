"""Property tests for ``classify_result`` status classification.

These tests import the pure helper from ``app.py`` (made importable via ``conftest.py``)
and verify the terminal-status classification contract across both the known Step Functions
statuses and arbitrary other strings.
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from app import classify_result, TERMINAL_FAIL


# Known Step Functions execution statuses the classifier recognizes explicitly.
_KNOWN_STATUSES = ("SUCCEEDED", "FAILED", "TIMED_OUT", "ABORTED", "RUNNING")


# Feature: streamlit-circuit-breaker-ui, Property 7: Terminal status classification is correct
# Validates: Requirements 4.2
@settings(max_examples=200)
@given(
    status=st.one_of(
        # Cover every known status explicitly...
        st.sampled_from(_KNOWN_STATUSES),
        # ...and arbitrary other strings that must fall through to UNKNOWN.
        st.text(),
    )
)
def test_classify_result_terminal_status_classification(status):
    """``classify_result`` maps each status to the correct result label.

    SUCCEEDED -> SUCCESS, each terminal-fail status -> FAIL, RUNNING -> RUNNING,
    and any other value -> UNKNOWN.
    """
    result = classify_result(status)

    if status == "SUCCEEDED":
        assert result == "SUCCESS"
    elif status in TERMINAL_FAIL:
        assert result == "FAIL"
    elif status == "RUNNING":
        assert result == "RUNNING"
    else:
        assert result == "UNKNOWN"


# Feature: streamlit-circuit-breaker-ui, Property 7: Terminal status classification is correct
# Validates: Requirements 4.2
@settings(max_examples=100)
@given(status=st.sampled_from(sorted(TERMINAL_FAIL)))
def test_classify_result_terminal_fail_maps_to_fail(status):
    """Every terminal-failure status classifies as FAIL."""
    assert classify_result(status) == "FAIL"
