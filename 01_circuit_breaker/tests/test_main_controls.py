"""Tests for the main controls, polling loop, and result line (task 11.2).

Requirements 2.5, 3.1, 3.2, 3.3, 3.4, 4.3, 4.4.
"""

import datetime
import os

from streamlit.testing.v1 import AppTest

from app import (
    AppConfig,
    Err,
    Ok,
    ExecutionRecord,
    ResolveResult,
    STATUS_READY,
    format_result_line,
    poll_running,
    short_id_from_arn,
    start_selected_execution,
    target_options,
)

_T0 = datetime.datetime(2024, 1, 1, 0, 0, 0)
_APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")


def _rec(name, offset, status="RUNNING", result="RUNNING"):
    return ExecutionRecord(
        execution_arn=f"arn:aws:states:us-east-1:1:execution:sm:{name}",
        short_id=name,
        target="t",
        start_time=_T0 + datetime.timedelta(seconds=offset),
        status=status,
        result=result,
    )


def test_target_options_uses_physical_names_with_logical_labels():
    cfg = AppConfig(
        status=STATUS_READY,
        resolve_result=ResolveResult(
            found={"state_machine": "arn", "table": "tbl", "hello": "h-123", "test": "t-456"},
            missing=[],
        ),
    )
    assert target_options(cfg) == [
        ("HelloWorldFunction", "h-123"),
        ("TestCircuitBreakerFunction", "t-456"),
    ]


def test_short_id_is_arn_suffix():
    assert short_id_from_arn("arn:aws:states:r:1:execution:sm:abc") == "abc"


class _Client:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response, error, []

    def start_execution(self, arn, input_json):
        self.calls.append((arn, input_json))
        if self.error:
            raise self.error
        return self.response


def test_start_success_adds_running_record():
    arn = "arn:aws:states:r:1:execution:sm:xyz"
    client = _Client(response={"executionArn": arn, "startDate": _T0})
    hist, err = start_selected_execution([], client, "sm-arn", "h-123")
    assert err is None
    assert client.calls == [("sm-arn", '{"TargetLambda": "h-123"}')]
    assert len(hist) == 1
    assert (hist[0].short_id, hist[0].status, hist[0].result) == ("xyz", "RUNNING", "RUNNING")
    assert hist[0].start_time == _T0


def test_start_failure_leaves_history_unchanged():
    from app import ClientError

    existing = [_rec("a", 0)]
    boom = ClientError({"Error": {"Code": "AccessDenied", "Message": "nope"}}, "StartExecution")
    hist, err = start_selected_execution(existing, _Client(error=boom), "sm", "t")
    assert hist == existing
    assert err.error_type == "AccessDenied"


def test_poll_updates_running_and_isolates_errors():
    a, b, c = _rec("a", 0), _rec("b", 1), _rec("c", 2, "SUCCEEDED", "SUCCESS")

    def describe(arn):
        if arn.endswith(":a"):
            return Ok({"status": "FAILED"})
        return Err("Throttling", "slow down")

    hist, errors = poll_running([a, b, c], describe)
    by_id = {r.short_id: r for r in hist}
    assert (by_id["a"].status, by_id["a"].result) == ("FAILED", "FAIL")
    assert (by_id["b"].status, by_id["b"].result) == ("UNKNOWN", "UNKNOWN")
    assert by_id["c"] == c
    assert [(sid, e.error_type) for sid, e in errors] == [("b", "Throttling")]


def test_poll_does_not_describe_finished_records():
    calls = []
    poll_running([_rec("x", 0, "SUCCEEDED", "SUCCESS")], lambda arn: calls.append(arn))
    assert calls == []


def test_format_result_line_latest():
    assert format_result_line([]) is None
    hist = [_rec("old", 0, "SUCCEEDED", "SUCCESS"), _rec("new", 5, "FAILED", "FAIL")]
    assert format_result_line(hist) == "new: FAIL"
    assert format_result_line([_rec("r", 9)]) == "r: RUNNING"


def test_app_runs_without_region_and_controls_disabled(monkeypatch):
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    at = AppTest.from_file(_APP).run()
    assert not at.exception
    assert at.button[0].disabled
    assert at.selectbox[0].disabled
    assert at.session_state["history"] == []
