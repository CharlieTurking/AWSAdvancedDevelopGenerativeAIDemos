"""Integration test for ``AwsClient.query_circuit`` against a mocked DynamoDB client (task 4.3).

Validates: Requirements 5.1
"""

from unittest.mock import MagicMock

import boto3
from botocore.stub import Stubber

from app import AwsClient

TABLE = "circuit-table"
SERVICE = "HelloWorldFunction"
NOW = 1_700_000_000
EXPRESSION = "ServiceName = :s AND ExpireTimeStamp > :t"
VALUES = {":s": {"S": SERVICE}, ":t": {"N": str(NOW)}}


def _client_with_ddb(ddb) -> AwsClient:
    """Build an AwsClient without touching boto3.Session, injecting the DynamoDB client."""
    client = AwsClient.__new__(AwsClient)
    client.ddb = ddb
    return client


def test_query_circuit_issues_expected_query_and_returns_items():
    ddb = MagicMock()
    items = [{"ServiceName": {"S": SERVICE}, "ExpireTimeStamp": {"N": str(NOW + 60)}}]
    ddb.query.return_value = {"Items": items, "Count": 1}

    result = _client_with_ddb(ddb).query_circuit(TABLE, SERVICE, NOW)

    ddb.query.assert_called_once_with(
        TableName=TABLE,
        KeyConditionExpression=EXPRESSION,
        ExpressionAttributeValues=VALUES,
        ConsistentRead=True,
    )
    assert result == items


def test_query_circuit_returns_empty_list_when_no_items_key():
    ddb = MagicMock()
    ddb.query.return_value = {}

    assert _client_with_ddb(ddb).query_circuit(TABLE, SERVICE, NOW) == []


def test_query_circuit_request_is_valid_against_dynamodb_api_model():
    """A botocore Stubber validates the request shape and exact parameters."""
    ddb = boto3.client(
        "dynamodb",
        region_name="us-east-1",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )
    items = [{"ServiceName": {"S": SERVICE}, "ExpireTimeStamp": {"N": str(NOW + 5)}}]
    with Stubber(ddb) as stubber:
        stubber.add_response(
            "query",
            {"Items": items, "Count": 1},
            expected_params={
                "TableName": TABLE,
                "KeyConditionExpression": EXPRESSION,
                "ExpressionAttributeValues": VALUES,
                "ConsistentRead": True,
            },
        )
        result = _client_with_ddb(ddb).query_circuit(TABLE, SERVICE, NOW)
        stubber.assert_no_pending_responses()

    assert result == items
