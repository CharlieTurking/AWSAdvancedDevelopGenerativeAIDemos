"""
Bedrock Converse wrapper for the token-tracking demo.

Only uses `bedrock-runtime:Converse`. Returns the authoritative input/output
token counts Bedrock reports, which drive the real-time tracking and alerting.
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

# Illustrative public pricing (USD per 1K tokens) for Claude Haiku 5.5.
PRICE_PER_1K_INPUT = float(os.environ.get("PRICE_PER_1K_INPUT", "0.001"))
PRICE_PER_1K_OUTPUT = float(os.environ.get("PRICE_PER_1K_OUTPUT", "0.005"))


@dataclass
class LLMResult:
    text: str
    input_tokens: int
    output_tokens: int
    latency_s: float

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def cost_usd(self) -> float:
        return (
            self.input_tokens / 1000 * PRICE_PER_1K_INPUT
            + self.output_tokens / 1000 * PRICE_PER_1K_OUTPUT
        )


def get_client(region: str = DEFAULT_REGION):
    import boto3

    return boto3.client("bedrock-runtime", region_name=region)


def converse(
    prompt: str,
    *,
    model_id: str = DEFAULT_MODEL_ID,
    region: str = DEFAULT_REGION,
    max_tokens: int = 512,
    temperature: float = 0.3,
    system: str | None = None,
) -> LLMResult:
    client = get_client(region)
    kwargs = {
        "modelId": model_id,
        "messages": [{"role": "user", "content": [{"text": prompt}]}],
        "inferenceConfig": build_inference_config(model_id, max_tokens, temperature),
    }
    if system:
        kwargs["system"] = [{"text": system}]

    t0 = time.time()
    resp = client.converse(**kwargs)
    latency = time.time() - t0

    text = extract_text(resp)
    usage = resp.get("usage", {})
    return LLMResult(
        text=text,
        input_tokens=int(usage.get("inputTokens", 0)),
        output_tokens=int(usage.get("outputTokens", 0)),
        latency_s=latency,
    )
