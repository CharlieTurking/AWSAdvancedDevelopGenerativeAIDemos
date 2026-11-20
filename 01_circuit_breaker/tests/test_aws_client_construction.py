"""Smoke tests for ``AwsClient`` construction (task 4.2).

With ``boto3.Session`` mocked, verify that the wrapper builds one session using the
environment Region and derives the cloudformation, stepfunctions and dynamodb clients
from it. No network access or AWS credentials are needed.

Validates: Requirements 2.1, 8.1
"""

from unittest.mock import MagicMock, patch

import app
from app import AwsClient, get_region


def _build(region):
    """Construct AwsClient under a patched boto3.Session; return (client, Session mock)."""
    with patch("app.boto3.Session") as session_cls:
        client = AwsClient(region)
    return client, session_cls


def test_session_built_with_region():
    client, session_cls = _build("us-west-2")

    session_cls.assert_called_once_with(region_name="us-west-2")
    assert client._session is session_cls.return_value


def test_clients_created_from_the_session():
    client, session_cls = _build("eu-central-1")
    session = session_cls.return_value

    created = [c.args[0] for c in session.client.call_args_list]
    assert sorted(created) == ["cloudformation", "dynamodb", "stepfunctions"]
    assert client.cfn is session.client.return_value
    assert client.sfn is session.client.return_value
    assert client.ddb is session.client.return_value


def test_clients_are_distinct_per_service():
    with patch("app.boto3.Session") as session_cls:
        session_cls.return_value.client.side_effect = lambda name: MagicMock(name=name)
        client = AwsClient("us-east-1")

    assert len({id(client.cfn), id(client.sfn), id(client.ddb)}) == 3


def test_region_from_injected_env_is_used_for_session():
    region = get_region({"AWS_DEFAULT_REGION": "ap-southeast-2"})
    _, session_cls = _build(region)

    session_cls.assert_called_once_with(region_name="ap-southeast-2")


def test_region_falls_back_to_aws_region_env():
    region = get_region({"AWS_REGION": "us-east-2"})
    _, session_cls = _build(region)

    session_cls.assert_called_once_with(region_name="us-east-2")


def test_get_region_unset_returns_none():
    assert get_region({}) is None
    assert app.get_region({"AWS_DEFAULT_REGION": "  "}) is None
