"""Tests for the circuit breaker clock and explanation helpers."""

import datetime
import json
import os

from hypothesis import given, settings, strategies as st
from streamlit.testing.v1 import AppTest

from app import (
    ExecutionRecord,
    RetryPolicy,
    circuit_open_until,
    clock_config,
    load_retry_policy,
    phase_at,
    retry_schedule,
    trip_clock_target,
)

_APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
_UTC = datetime.timezone.utc


def _rec(name, target, offset, result="RUNNING"):
    return ExecutionRecord(
        execution_arn=f"arn:aws:states:r:1:execution:sm:{name}",
        short_id=name,
        target=target,
        start_time=datetime.datetime(2026, 1, 1, tzinfo=_UTC) + datetime.timedelta(seconds=offset),
        status=result,
        result=result,
    )


def test_load_retry_policy_reads_the_vendored_state_machine():
    assert load_retry_policy() == RetryPolicy(12, 3, 2, 1.5)


def test_load_retry_policy_falls_back_on_missing_file(tmp_path):
    assert load_retry_policy(str(tmp_path / "nope.json")) == RetryPolicy()


def test_load_retry_policy_uses_step_functions_defaults_for_missing_fields(tmp_path):
    asl = {"States": {"Execute Lambda": {"TimeoutSeconds": 5, "Retry": [{"ErrorEquals": ["x"]}]}}}
    path = tmp_path / "asl.json"
    path.write_text(json.dumps(asl))
    assert load_retry_policy(str(path)) == RetryPolicy(5, 3, 1, 2.0)


def test_default_schedule_matches_the_sample():
    phases = retry_schedule(RetryPolicy(12, 3, 2, 1.5))
    assert [d for _, d in phases] == [12, 2, 12, 3, 12, 4.5, 12]
    assert sum(d for _, d in phases) == 57.5
    assert phases[0][0].startswith("Attempt 1 of 4")


@settings(max_examples=100)
@given(
    timeout=st.floats(1, 60),
    retries=st.integers(0, 6),
    interval=st.floats(0.5, 10),
    backoff=st.floats(1, 3),
)
def test_schedule_has_one_attempt_more_than_retries(timeout, retries, interval, backoff):
    phases = retry_schedule(RetryPolicy(timeout, retries, interval, backoff))
    attempts = [p for p in phases if p[0].startswith("Attempt")]
    assert len(attempts) == retries + 1
    assert len(phases) == 2 * retries + 1


def test_phase_at_walks_the_schedule():
    phases = retry_schedule(RetryPolicy(12, 3, 2, 1.5))
    label, left_phase, left_total = phase_at(phases, 0)
    assert label.startswith("Attempt 1") and left_phase == 12 and left_total == 57.5
    label, left_phase, _ = phase_at(phases, 13)
    assert label.startswith("Waiting 2 s") and left_phase == 1
    assert phase_at(phases, 57.5) is None


def test_circuit_open_until_picks_latest_unexpired():
    items = [{"ExpireTimeStamp": {"N": str(n)}} for n in (90, 120, 150)]
    assert circuit_open_until(items, 100) == 150
    assert circuit_open_until(items, 200) is None
    assert circuit_open_until([], 100) is None


def test_trip_clock_target_is_latest_running_failing_call():
    hist = [_rec("a", "fail", 0), _rec("b", "fail", 5), _rec("c", "ok", 9), _rec("d", "fail", 7, "FAIL")]
    assert trip_clock_target(hist, "fail").short_id == "b"
    assert trip_clock_target(hist, "ok").short_id == "c"
    assert trip_clock_target([], "fail") is None


def test_clock_config_modes():
    policy = RetryPolicy(12, 3, 2, 1.5)
    running = [_rec("a", "fail", 0)]
    assert clock_config(running, "fail", 1_900_000_000, policy)["mode"] == "close"
    trip = clock_config(running, "fail", None, policy)
    assert trip["mode"] == "trip"
    assert trip["start"] == running[0].start_time.timestamp()
    assert len(trip["phases"]) == 7
    assert clock_config([], "fail", None, policy) == {"mode": "idle"}


def test_app_renders_explanation_without_region(monkeypatch):
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    at = AppTest.from_file(_APP, default_timeout=30).run()
    assert not at.exception
    assert any("How the circuit breaker works" in e.label for e in at.expander)
