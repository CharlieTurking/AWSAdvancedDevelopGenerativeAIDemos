"""Tests for circuit badge, history table, and timeline helpers (task 11.3).

Requirements 4.1, 5.1-5.5, 6.1, 6.4, 7.1, 7.4.
"""

import datetime
import os

from streamlit.testing.v1 import AppTest

from app import (
    Err,
    ExecutionRecord,
    Ok,
    history_rows,
    query_circuit_state,
    timeline_dataframe,
    tracked_targets,
    update_circuit_tracking,
)

_APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
_T0 = datetime.datetime(2024, 1, 1)


def _rec(name, target, offset):
    return ExecutionRecord(name, name, target, _T0 + datetime.timedelta(seconds=offset), "RUNNING", "RUNNING")


def test_no_timed_autorefresh():
    """Refresh is manual; the timed autorefresh interrupted slow live runs."""
    import app

    assert not hasattr(app, "st_autorefresh")


def test_tracked_targets_selected_first_deduped():
    hist = [_rec("a", "x", 0), _rec("b", "y", 1), _rec("c", "x", 2)]
    assert tracked_targets("y", hist) == ["y", "x"]
    assert tracked_targets(None, hist) == ["x", "y"]


def test_query_circuit_state_open_closed_unknown():
    items = [{"ExpireTimeStamp": {"N": "200"}}]
    assert query_circuit_state(lambda *a: Ok(items), "t", "s", 100) == ("OPEN", None)
    assert query_circuit_state(lambda *a: Ok([]), "t", "s", 100) == ("CLOSED", None)
    err = Err("X", "boom")
    assert query_circuit_state(lambda *a: err, "t", "s", 100) == ("UNKNOWN", err)


def test_unknown_does_not_overwrite_baseline_or_add_point():
    last, tl = update_circuit_tracking({}, [], "s", "CLOSED", 1)
    last, tl = update_circuit_tracking(last, tl, "s", "UNKNOWN", 2)
    assert last == {"s": "CLOSED"} and tl == [(1, "s", "CLOSED")]
    last, tl = update_circuit_tracking(last, tl, "s", "CLOSED", 3)
    assert len(tl) == 1
    last, tl = update_circuit_tracking(last, tl, "s", "OPEN", 4)
    assert tl[-1] == (4, "s", "OPEN")


def test_history_rows_columns_and_order():
    rows = history_rows([_rec("a", "x", 0), _rec("b", "x", 5)])
    assert [r["short_id"] for r in rows] == ["b", "a"]
    assert list(rows[0]) == ["short_id", "target", "start_time", "status", "result"]


def test_timeline_dataframe_values():
    df = timeline_dataframe([(1, "s", "OPEN"), (2, "s", "CLOSED")])
    assert list(df["value"]) == [1, 0]


def test_app_renders_without_region(monkeypatch):
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    at = AppTest.from_file(_APP).run()
    assert not at.exception
    assert any("Timeline" in s.value for s in at.subheader)
    assert any("Execution History" in s.value for s in at.subheader)
