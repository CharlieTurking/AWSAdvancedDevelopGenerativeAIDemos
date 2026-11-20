"""Example/edge UI tests via Streamlit AppTest with a fake boto3 session (no live AWS).

Covers Requirements 1.5, 3.1, 4.3, 4.4, 5.5, 6.1, 8.3, 8.4 (task 11.4).
``boto3.Session`` is monkeypatched, so the real ``AwsClient`` runs against fakes.
"""

import datetime
import os

import boto3
import pytest
from botocore.exceptions import ClientError
from streamlit.testing.v1 import AppTest

_APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")

SM_ARN = "arn:aws:states:us-east-1:1:stateMachine:CircuitBreakerStateMachine-abc"
TABLE = "CircuitBreaker"
HELLO = "stack-HelloWorldFunction-111"
TEST = "stack-TestCircuitBreakerFunction-222"


def _resources():
    return [
        {"LogicalResourceId": "CircuitBreakerStateMachine",
         "ResourceType": "AWS::StepFunctions::StateMachine", "PhysicalResourceId": SM_ARN},
        {"LogicalResourceId": "CircuitBreakerTable",
         "ResourceType": "AWS::DynamoDB::Table", "PhysicalResourceId": TABLE},
        {"LogicalResourceId": "HelloWorldFunction",
         "ResourceType": "AWS::Lambda::Function", "PhysicalResourceId": HELLO},
        {"LogicalResourceId": "TestCircuitBreakerFunction",
         "ResourceType": "AWS::Lambda::Function", "PhysicalResourceId": TEST},
    ]


def _client_error(code, msg, op="Op"):
    return ClientError({"Error": {"Code": code, "Message": msg}}, op)


class FakeAws:
    """Shared recorder/config for the fake cloudformation/stepfunctions/dynamodb clients."""

    def __init__(self):
        self.stack_calls = []
        self.start_calls = []
        self.describe_calls = []
        self.query_calls = []
        self.describe_status = "SUCCEEDED"
        self.describe_error = None
        self.query_items = []
        self.query_error = None
        self._n = 0

    # cloudformation
    def list_stack_resources(self, StackName, **kw):
        self.stack_calls.append(StackName)
        return {"StackResourceSummaries": _resources()}

    # stepfunctions
    def start_execution(self, stateMachineArn, input):
        self.start_calls.append((stateMachineArn, input))
        self._n += 1
        return {
            "executionArn": f"arn:aws:states:us-east-1:1:execution:sm:exec{self._n}",
            "startDate": datetime.datetime(2024, 1, 1, 0, 0, self._n),
        }

    def describe_execution(self, executionArn):
        self.describe_calls.append(executionArn)
        if self.describe_error:
            raise self.describe_error
        return {"status": self.describe_status}

    # dynamodb
    def query(self, **kw):
        self.query_calls.append(kw)
        if self.query_error:
            raise self.query_error
        return {"Items": self.query_items}


@pytest.fixture
def aws(monkeypatch):
    fake = FakeAws()

    class FakeSession:
        def __init__(self, region_name=None):
            self.region_name = region_name

        def client(self, name):
            return fake

    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setattr(boto3, "Session", FakeSession)
    return fake


def _run():
    at = AppTest.from_file(_APP, default_timeout=30).run()
    assert not at.exception
    return at


def _texts(elements):
    return [e.value for e in elements]


def _stack_input(at):
    return next(t for t in at.sidebar.text_input if t.label == "Stack Name")


# --- 1.5 resolved-resources panel -------------------------------------------------------


def test_resolved_resources_panel_shows_arn_table_and_targets(aws):
    at = _run()
    codes = _texts(at.sidebar.code)
    assert codes == [SM_ARN, TABLE, HELLO, TEST]
    assert any("Resolved resources" in s.value for s in at.sidebar.subheader)
    assert any("State machine ARN" in t.value for t in at.sidebar.text)
    assert any("DynamoDB table" in t.value for t in at.sidebar.text)
    assert any("Target Lambdas" in t.value for t in at.sidebar.text)


# --- 3.1 target selector ----------------------------------------------------------------


def test_target_selector_lists_exactly_the_two_targets(aws):
    at = _run()
    sb = at.selectbox[0]
    assert list(sb.options) == ["HelloWorldFunction", "TestCircuitBreakerFunction"]
    assert not sb.disabled
    assert not at.button[0].disabled


# --- 4.3 result line --------------------------------------------------------------------


def test_result_line_shows_success_with_execution_id(aws):
    aws.describe_status = "SUCCEEDED"
    at = _run()
    at.button[0].click().run()
    assert not at.exception
    assert aws.start_calls == [(SM_ARN, '{"TargetLambda": "%s"}' % HELLO)]
    assert "exec1: SUCCESS" in _texts(at.markdown)


def test_result_line_shows_fail_for_timed_out(aws):
    aws.describe_status = "TIMED_OUT"
    at = _run()
    at.selectbox[0].select("TestCircuitBreakerFunction")
    at.button[0].click().run()
    assert "exec1: FAIL" in _texts(at.markdown)


def test_no_result_line_before_any_execution(aws):
    at = _run()
    assert not any(": SUCCESS" in v or ": FAIL" in v or ": RUNNING" in v for v in _texts(at.markdown))


# --- 4.4 polling error -> UNKNOWN -------------------------------------------------------


def test_polling_error_marks_unknown_and_shows_error(aws):
    aws.describe_error = _client_error("Throttling", "slow down", "DescribeExecution")
    at = _run()
    at.button[0].click().run()
    assert not at.exception
    assert any("Throttling" in e.value and "slow down" in e.value for e in at.error)
    row = at.dataframe[0].value.iloc[0]
    assert (row["status"], row["result"]) == ("UNKNOWN", "UNKNOWN")
    assert "exec1: UNKNOWN" in _texts(at.markdown)


# --- 5.5 circuit read error -> UNKNOWN badge --------------------------------------------


def test_circuit_read_error_renders_unknown_badge_and_error(aws):
    aws.query_error = _client_error("AccessDenied", "no ddb", "Query")
    at = _run()
    assert any("AccessDenied" in e.value and "no ddb" in e.value for e in at.error)
    assert any(f"Circuit for {HELLO}: UNKNOWN" in w.value for w in at.warning)


def test_circuit_badge_open_and_closed_without_error(aws):
    aws.query_items = []
    at = _run()
    assert any(f"Circuit for {HELLO}: CLOSED" in s.value for s in at.success)
    far_future = str(int(datetime.datetime(2100, 1, 1).timestamp()))
    aws.query_items = [{"ExpireTimeStamp": {"N": far_future}}]
    at = _run()
    assert any(f"Circuit for {HELLO}: OPEN" in e.value for e in at.error)


# --- 6.1 history table ------------------------------------------------------------------


def test_history_table_columns_and_most_recent_first(aws):
    at = _run()
    at.button[0].click().run()
    at.button[0].click().run()
    df = at.dataframe[0].value
    assert list(df.columns) == ["short_id", "target", "start_time", "status", "result"]
    assert list(df["short_id"]) == ["exec2", "exec1"]
    assert set(df["target"]) == {HELLO}


# --- 8.3 / 8.4 stack-name control and re-resolution -------------------------------------


def test_stack_name_control_present_with_default(aws):
    at = _run()
    from app import DEFAULT_STACK_NAME

    assert _stack_input(at).value == DEFAULT_STACK_NAME
    assert aws.stack_calls[-1] == DEFAULT_STACK_NAME


def test_changing_stack_name_re_resolves_with_new_name(aws):
    at = _run()
    aws.stack_calls.clear()
    _stack_input(at).set_value("other-stack").run()
    assert not at.exception
    assert aws.stack_calls and set(aws.stack_calls) == {"other-stack"}
