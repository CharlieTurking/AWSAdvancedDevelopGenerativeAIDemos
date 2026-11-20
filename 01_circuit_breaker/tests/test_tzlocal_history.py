"""Regression test: boto3 returns ``startDate`` with dateutil's ``tzlocal()``.

pyarrow (used by ``st.dataframe``) cannot serialize ``tzlocal()``, which crashed the
Execution History table against live AWS. ``build_record`` must normalize to UTC.
"""

import datetime
import os

from dateutil.tz import tzlocal
from streamlit.testing.v1 import AppTest

from app import build_record

_APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
_ARN = "arn:aws:states:us-east-1:1:execution:sm:abc123"


def test_build_record_normalizes_tzlocal_to_utc():
    local = datetime.datetime(2026, 11, 4, 10, 25, 19, tzinfo=tzlocal())
    rec = build_record({"executionArn": _ARN, "startDate": local}, "target")
    assert rec.start_time.tzinfo is datetime.timezone.utc
    assert rec.start_time == local  # same instant


def test_history_table_renders_with_boto3_style_start_date(monkeypatch):
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    rec = build_record(
        {"executionArn": _ARN, "startDate": datetime.datetime.now(tzlocal())}, "target"
    )
    at = AppTest.from_file(_APP, default_timeout=30)
    at.session_state["history"] = [rec]
    at.run()
    assert not at.exception
    assert list(at.dataframe[0].value["short_id"]) == ["abc123"]
