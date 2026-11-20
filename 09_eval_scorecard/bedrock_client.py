"""
Bedrock wrapper for the multi-dimensional evaluation demo.

Uses:
  - Converse (Claude) for generation and LLM-as-a-judge scoring
  - InvokeModel (Titan embeddings) for semantic-similarity scoring

No persistent AWS resources are created, so local mode has nothing to tear down.
"""

from __future__ import annotations

import json
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
DEFAULT_EMBED_MODEL_ID = os.environ.get(
    "BEDROCK_EMBED_MODEL_ID", "amazon.titan-embed-text-v2:0"
)

PRICE_PER_1K_INPUT = float(os.environ.get("PRICE_PER_1K_INPUT", "0.001"))
PRICE_PER_1K_OUTPUT = float(os.environ.get("PRICE_PER_1K_OUTPUT", "0.005"))


@dataclass
class LLMResult:
    text: str
    input_tokens: int
    output_tokens: int
    latency_s: float

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
    max_tokens: int = 1024,
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


def embed(
    text: str,
    *,
    model_id: str = DEFAULT_EMBED_MODEL_ID,
    region: str = DEFAULT_REGION,
) -> list[float]:
    client = get_client(region)
    resp = client.invoke_model(modelId=model_id, body=json.dumps({"inputText": text}))
    return json.loads(resp["body"].read())["embedding"]
