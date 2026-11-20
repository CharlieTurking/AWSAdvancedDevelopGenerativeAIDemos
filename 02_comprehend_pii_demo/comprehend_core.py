"""Amazon Comprehend calls and the local processing of their results.

No Streamlit and no web framework in this module, so the same code runs in the
local Streamlit demo and inside the AWS Lambda behind the deployed website
(aws/). Both show these functions to the audience by printing their real source
with `inspect.getsource`, so the code on screen is always the code that runs.
"""

from __future__ import annotations

import boto3

# Comprehend API limits for the batch calls used below.
SENTIMENT_BATCH_SIZE = 25   # batch_detect_sentiment: max 25 documents per call
TOXICITY_BATCH_SIZE = 10    # detect_toxic_content: max 10 text segments per call


# --------------------------------------------------------------------------
# Comprehend calls
# --------------------------------------------------------------------------

def get_comprehend_client(region_name: str):
    return boto3.client("comprehend", region_name=region_name)


def detect_pii(text: str, region_name: str, language: str = "en"):
    """Find PII in text. Returns entity types, scores and character offsets."""
    client = get_comprehend_client(region_name)
    return client.detect_pii_entities(
        Text=text,
        LanguageCode=language,
    )


def detect_sentiments(texts: list[str], region_name: str, language: str = "en"):
    """Sentiment for many documents, 25 per call. Returns one result per text."""
    client = get_comprehend_client(region_name)
    results = []
    for start in range(0, len(texts), SENTIMENT_BATCH_SIZE):
        batch = texts[start:start + SENTIMENT_BATCH_SIZE]
        response = client.batch_detect_sentiment(TextList=batch, LanguageCode=language)
        if response["ErrorList"]:
            raise RuntimeError(f"Comprehend rejected a document: {response['ErrorList'][0]}")
        results.extend(response["ResultList"])  # returned in input order
    return results


def detect_toxicity(texts: list[str], region_name: str, language: str = "en"):
    """Toxicity labels for many text segments, 10 per call."""
    client = get_comprehend_client(region_name)
    results = []
    for start in range(0, len(texts), TOXICITY_BATCH_SIZE):
        batch = texts[start:start + TOXICITY_BATCH_SIZE]
        response = client.detect_toxic_content(
            TextSegments=[{"Text": t} for t in batch],
            LanguageCode=language,
        )
        results.extend(response["ResultList"])
    return results


# --------------------------------------------------------------------------
# Local processing of Comprehend results (no AWS calls)
# --------------------------------------------------------------------------

def mask_text(
    text: str,
    entities: list[dict],
    style: str = "type",
    mask_char: str = "*",
    min_score: float = 0.0,
    only_types: set[str] | None = None,
) -> tuple[str, int]:
    """Replace each detected PII span in `text`. Returns (masked_text, spans_masked).

    Comprehend returns where the PII is (BeginOffset/EndOffset); the masking itself
    happens here. style: "type" -> [EMAIL], "mask" -> ******, "redacted" -> [REDACTED].
    """
    spans = sorted(
        (e["BeginOffset"], e["EndOffset"], e["Type"])
        for e in entities
        if e["Score"] >= min_score and (only_types is None or e["Type"] in only_types)
    )

    # Merge overlapping spans so no part of a PII value is left visible.
    merged: list[list] = []
    for begin, end, entity_type in spans:
        if merged and begin < merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([begin, end, entity_type])

    masked = text
    # Work from the end of the text so earlier offsets stay valid.
    for begin, end, entity_type in reversed(merged):
        if style == "mask":
            replacement = mask_char * (end - begin)
        elif style == "redacted":
            replacement = "[REDACTED]"
        else:
            replacement = f"[{entity_type}]"
        masked = masked[:begin] + replacement + masked[end:]
    return masked, len(merged)


def net_sentiment(result: dict) -> float:
    """Positive score minus Negative score: +1 very positive, -1 very negative."""
    scores = result["SentimentScore"]
    return scores["Positive"] - scores["Negative"]
