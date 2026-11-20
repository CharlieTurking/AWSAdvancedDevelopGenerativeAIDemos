"""
Bedrock Converse wrapper for the access-gate demo.

Only called AFTER the local access-control decision allows it. No persistent AWS
resources are created, so local mode has nothing to tear down.
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass

# Make the repo-root shared helpers importable regardless of launch directory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from model_catalog import build_inference_config, extract_text  # noqa: E402

DEFAULT_REGION = os.environ.get("AWS_REGION", "us-east-1")
DEFAULT_MODEL_ID = os.environ.get(
    "BEDROCK_MODEL_ID", "us.anthropic.claude-haiku-5-5"
)


@dataclass
class LLMResult:
    text: str
    input_tokens: int
    output_tokens: int
    latency_s: float


def get_client(region: str = DEFAULT_REGION):
    import boto3

    return boto3.client("bedrock-runtime", region_name=region)


def converse(
    prompt: str,
    *,
    model_id: str = DEFAULT_MODEL_ID,
    region: str = DEFAULT_REGION,
    max_tokens: int = 256,
    temperature: float = 0.3,
) -> LLMResult:
    client = get_client(region)
    t0 = time.time()
    resp = client.converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig=build_inference_config(model_id, max_tokens, temperature),
    )
    latency = time.time() - t0
    text = extract_text(resp)
    usage = resp.get("usage", {})
    return LLMResult(
        text=text,
        input_tokens=int(usage.get("inputTokens", 0)),
        output_tokens=int(usage.get("outputTokens", 0)),
        latency_s=latency,
    )
