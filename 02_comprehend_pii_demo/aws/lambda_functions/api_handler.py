"""API Gateway -> Lambda handler for the Amazon Comprehend demo website.

One function serves every route; the Comprehend calls themselves are in
comprehend_core.py, the same module the local Streamlit demo uses.

    POST /pii        {text}                         -> PII entities (calls Comprehend)
    POST /mask       {text, entities, ...options}   -> masked text   (no AWS call)
    POST /sentiment  {texts: [up to 25]}            -> sentiment     (calls Comprehend)
    POST /toxicity   {texts: [up to 10]}            -> toxicity      (calls Comprehend)
    GET  /info                                      -> limits + the real source code of the
                                                       functions, for the "show the code" panels

Request text is PII by design in this demo, so it is never written to the logs.
"""

from __future__ import annotations

import base64
import inspect
import json
import logging
import os

from botocore.exceptions import BotoCoreError, ClientError

import comprehend_core as core

logger = logging.getLogger()
logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "us-east-1")
LANGUAGE = "en"

# Input limits. They keep a public demo cheap and inside Comprehend's own limits.
MAX_BODY_BYTES = 256 * 1024
MAX_TEXT_CHARS = 10_000          # /pii and /mask
MAX_ITEM_BYTES = 1_000           # each text in /sentiment and /toxicity (toxicity segments max 1 KB)
MAX_MASK_ENTITIES = 1_000
MASK_STYLES = {"type", "mask", "redacted"}

LIMITS = {
    "maxTextChars": MAX_TEXT_CHARS,
    "maxItemBytes": MAX_ITEM_BYTES,
    "sentimentBatch": core.SENTIMENT_BATCH_SIZE,
    "toxicityBatch": core.TOXICITY_BATCH_SIZE,
}

# Functions shown on the website's "Show the code" panels (real source, via inspect).
SHOWN_FUNCTIONS = {
    "get_comprehend_client": core.get_comprehend_client,
    "detect_pii": core.detect_pii,
    "mask_text": core.mask_text,
    "detect_sentiments": core.detect_sentiments,
    "detect_toxicity": core.detect_toxicity,
    "net_sentiment": core.net_sentiment,
}

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------

def route_pii(body: dict) -> dict:
    text = _require_text(body.get("text"), "text", MAX_TEXT_CHARS)
    response = core.detect_pii(text, REGION, LANGUAGE)
    entities = [
        {
            "Type": e["Type"],
            "Score": e["Score"],
            "BeginOffset": e["BeginOffset"],
            "EndOffset": e["EndOffset"],
            "Text": text[e["BeginOffset"]:e["EndOffset"]],
        }
        for e in sorted(response["Entities"], key=lambda e: e["BeginOffset"])
    ]
    raw = {k: v for k, v in response.items() if k != "ResponseMetadata"}
    return {"entities": entities, "raw": raw}


def route_mask(body: dict) -> dict:
    text = _require_text(body.get("text"), "text", MAX_TEXT_CHARS)

    entities = body.get("entities")
    if not isinstance(entities, list) or len(entities) > MAX_MASK_ENTITIES:
        raise ApiError(400, f"'entities' must be a list of at most {MAX_MASK_ENTITIES} items")
    clean = []
    for e in entities:
        try:
            begin, end = int(e["BeginOffset"]), int(e["EndOffset"])
            clean.append({"Type": str(e["Type"]), "Score": float(e["Score"]),
                          "BeginOffset": begin, "EndOffset": end})
        except (KeyError, TypeError, ValueError):
            raise ApiError(400, "each entity needs Type, Score, BeginOffset and EndOffset")
        if not 0 <= begin < end <= len(text):
            raise ApiError(400, "entity offsets must lie inside the text")

    style = body.get("style", "type")
    if style not in MASK_STYLES:
        raise ApiError(400, f"'style' must be one of {sorted(MASK_STYLES)}")
    mask_char = body.get("mask_char") or "*"
    if not isinstance(mask_char, str) or len(mask_char) != 1:
        raise ApiError(400, "'mask_char' must be a single character")
    try:
        min_score = float(body.get("min_score", 0.0))
    except (TypeError, ValueError):
        raise ApiError(400, "'min_score' must be a number")
    types = body.get("types")
    if types is not None and not (isinstance(types, list) and all(isinstance(t, str) for t in types)):
        raise ApiError(400, "'types' must be a list of strings")

    masked, count = core.mask_text(
        text, clean, style=style, mask_char=mask_char, min_score=min_score,
        only_types=None if types is None else set(types),
    )
    return {"masked": masked, "count": count}


def route_sentiment(body: dict) -> dict:
    texts = _require_texts(body.get("texts"), core.SENTIMENT_BATCH_SIZE)
    results = core.detect_sentiments(texts, REGION, LANGUAGE)
    return {
        "results": [
            {
                "sentiment": r["Sentiment"],
                "scores": r["SentimentScore"],
                "net": round(core.net_sentiment(r), 4),
            }
            for r in results
        ]
    }


def route_toxicity(body: dict) -> dict:
    texts = _require_texts(body.get("texts"), core.TOXICITY_BATCH_SIZE)
    results = core.detect_toxicity(texts, REGION, LANGUAGE)
    return {
        "results": [
            {
                "toxicity": r["Toxicity"],
                "labels": {label["Name"]: label["Score"] for label in r["Labels"]},
            }
            for r in results
        ]
    }


def route_info(_body: dict) -> dict:
    return {
        "limits": LIMITS,
        "functions": {name: inspect.getsource(func) for name, func in SHOWN_FUNCTIONS.items()},
    }


ROUTES = {
    ("POST", "/pii"): route_pii,
    ("POST", "/mask"): route_mask,
    ("POST", "/sentiment"): route_sentiment,
    ("POST", "/toxicity"): route_toxicity,
    ("GET", "/info"): route_info,
}


# --------------------------------------------------------------------------
# Validation helpers
# --------------------------------------------------------------------------

def _require_text(value, name: str, max_chars: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ApiError(400, f"'{name}' is required and must be a non-empty string")
    if len(value) > max_chars:
        raise ApiError(400, f"'{name}' is too long (max {max_chars:,} characters)")
    return value


def _require_texts(value, max_items: int) -> list[str]:
    if not isinstance(value, list) or not 1 <= len(value) <= max_items:
        raise ApiError(400, f"'texts' must be a list of 1 to {max_items} items")
    for i, item in enumerate(value, start=1):
        if not isinstance(item, str) or not item.strip():
            raise ApiError(400, f"text {i} is empty")
        if len(item.encode("utf-8")) > MAX_ITEM_BYTES:
            raise ApiError(400, f"text {i} is too long (max {MAX_ITEM_BYTES:,} bytes)")
    return value


def _parse_body(event: dict) -> dict:
    raw = event.get("body")
    if not raw:
        return {}
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    if len(raw.encode("utf-8")) > MAX_BODY_BYTES:
        raise ApiError(413, "request body is too large")
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        raise ApiError(400, "request body is not valid JSON")
    if not isinstance(body, dict):
        raise ApiError(400, "request body must be a JSON object")
    return body


def _response(status: int, payload: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
        "body": json.dumps(payload),
    }


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def lambda_handler(event, context):
    method = event.get("httpMethod", "")
    path = (event.get("resource") or event.get("path") or "").rstrip("/") or "/"

    if method == "OPTIONS":   # normally answered by API Gateway itself
        return {"statusCode": 204, "headers": CORS_HEADERS, "body": ""}

    try:
        route = ROUTES.get((method, path))
        if route is None:
            raise ApiError(404, f"no route for {method} {path}")
        body = _parse_body(event)
        logger.info("route=%s %s", method, path)   # never log the request text: it is PII
        return _response(200, route(body))

    except ApiError as e:
        return _response(e.status, {"error": e.message})
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        message = e.response.get("Error", {}).get("Message", str(e))
        logger.warning("comprehend client error: %s", code)
        if code in ("ThrottlingException", "TooManyRequestsException"):
            return _response(429, {"error": "Comprehend is busy, please try again in a moment"})
        return _response(502, {"error": f"Comprehend error ({code}): {message}"})
    except (BotoCoreError, RuntimeError) as e:
        logger.warning("comprehend call failed: %s", type(e).__name__)
        return _response(502, {"error": f"Comprehend call failed: {e}"})
    except Exception:  # noqa: BLE001
        logger.exception("unexpected error")
        return _response(500, {"error": "internal error"})
