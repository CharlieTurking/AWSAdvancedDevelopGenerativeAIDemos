"""Shared Amazon Bedrock Converse API helper for the prompt decomposition demo.

Centralizes client creation and the two call patterns used across pages:
- `converse` for a single blocking response
- `converse_stream` for token streaming (nicer for live demos)
"""

from __future__ import annotations

import os
import sys

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

# Make the repo-root shared helpers importable regardless of launch directory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from model_catalog import build_inference_config, extract_text  # noqa: E402


class BedrockError(Exception):
    """Raised when a Bedrock call fails, carrying a human-readable message."""


def get_client(region: str):
    """Create a Bedrock Runtime client for the given region.

    A generous read timeout is used because reasoning prompts can take a while.
    """
    config = Config(
        region_name=region,
        read_timeout=120,
        connect_timeout=10,
        retries={"max_attempts": 3, "mode": "standard"},
    )
    return boto3.client("bedrock-runtime", config=config)


def _build_messages(prompt: str) -> list[dict]:
    return [{"role": "user", "content": [{"text": prompt}]}]


def _inference_config(model_id: str, max_tokens: int, temperature: float) -> dict:
    # Omits `temperature` for models that reject it (see model_catalog).
    return build_inference_config(model_id, max_tokens, temperature)


def converse(
    region: str,
    model_id: str,
    prompt: str,
    system: str | None = None,
    max_tokens: int = 1500,
    temperature: float = 0.3,
) -> str:
    """Send one prompt and return the full text response."""
    client = get_client(region)
    kwargs = {
        "modelId": model_id,
        "messages": _build_messages(prompt),
        "inferenceConfig": _inference_config(model_id, max_tokens, temperature),
    }
    if system:
        kwargs["system"] = [{"text": system}]

    try:
        response = client.converse(**kwargs)
    except (ClientError, BotoCoreError) as exc:
        raise BedrockError(_friendly_error(exc)) from exc

    return extract_text(response)


def converse_stream(
    region: str,
    model_id: str,
    prompt: str,
    system: str | None = None,
    max_tokens: int = 1500,
    temperature: float = 0.3,
):
    """Yield text chunks as the model streams its response.

    Designed to be consumed by Streamlit's `st.write_stream`.
    """
    client = get_client(region)
    kwargs = {
        "modelId": model_id,
        "messages": _build_messages(prompt),
        "inferenceConfig": _inference_config(model_id, max_tokens, temperature),
    }
    if system:
        kwargs["system"] = [{"text": system}]

    try:
        response = client.converse_stream(**kwargs)
        for event in response["stream"]:
            if "contentBlockDelta" in event:
                delta = event["contentBlockDelta"]["delta"]
                if "text" in delta:
                    yield delta["text"]
    except (ClientError, BotoCoreError) as exc:
        raise BedrockError(_friendly_error(exc)) from exc


def _friendly_error(exc: Exception) -> str:
    """Turn a boto exception into something a presenter can read at a glance."""
    if isinstance(exc, ClientError):
        code = exc.response.get("Error", {}).get("Code", "Unknown")
        msg = exc.response.get("Error", {}).get("Message", str(exc))
        if code in ("AccessDeniedException", "ValidationException") and "model" in msg.lower():
            return (
                f"{code}: {msg}\n\n"
                "Tip: confirm the model ID is correct and that you have requested "
                "model access for it in the Bedrock console for this region."
            )
        if code == "ExpiredTokenException":
            return "Your AWS credentials have expired. Refresh them and try again."
        return f"{code}: {msg}"
    return f"Could not reach Bedrock: {exc}"
