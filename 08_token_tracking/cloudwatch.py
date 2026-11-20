"""
Optional CloudWatch custom-metrics publisher (Module 8, slide 7).

Publishes token metrics with App / UserSegment dimensions to a custom namespace
so you can build CloudWatch dashboards and alarms on them. This is the only part
of the demo that touches a billable AWS surface beyond Bedrock
(`cloudwatch:PutMetricData`). Custom metrics are not deletable — they simply
stop being published and age out — so there is no teardown for the data itself.
The deploy script's teardown removes the IAM role and any alarms it created.
"""

from __future__ import annotations

import os

DEFAULT_NAMESPACE = os.environ.get("CW_NAMESPACE", "AI/TokenTracking")


def get_client(region: str):
    import boto3

    return boto3.client("cloudwatch", region_name=region)


def publish(
    *,
    region: str,
    app: str,
    user_segment: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    namespace: str = DEFAULT_NAMESPACE,
) -> None:
    """Publish one call's metrics. Raises on failure so the UI can surface it."""
    client = get_client(region)
    dims = [{"Name": "App", "Value": app}, {"Name": "UserSegment", "Value": user_segment}]
    client.put_metric_data(
        Namespace=namespace,
        MetricData=[
            {"MetricName": "InputTokens", "Value": input_tokens, "Unit": "Count", "Dimensions": dims},
            {"MetricName": "OutputTokens", "Value": output_tokens, "Unit": "Count", "Dimensions": dims},
            {"MetricName": "TotalTokens", "Value": input_tokens + output_tokens, "Unit": "Count", "Dimensions": dims},
            {"MetricName": "EstimatedCostUSD", "Value": cost_usd, "Unit": "None", "Dimensions": dims},
        ],
    )
