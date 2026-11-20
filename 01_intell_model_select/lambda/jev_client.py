"""
Jev API client for the intelligent model selection demo.

Jev (TypeSafe System One) is a decision service. It receives a `state` and typed
`questions` and returns a typed answer with probabilities and confidence. It never
runs a model. This client builds the request payload, performs the HTTP call using
only the Python standard library, and parses the typed answer back into a small
immutable result.

Design constraints (see .kiro/specs/jev-router-comparison/design.md, "Jev_Client"):

- Standard library only. No new bundled dependency is added to lambda/requirements.txt.
- The HTTP call is POST to JEV_URL with an `Authorization: Bearer <key>` header and a
  JSON body. Headers and the key are never logged.
- A wall-clock deadline is enforced by running the blocking `urlopen` in a single worker
  thread and waiting with `future.result(timeout=...)`. A per-socket timeout alone does
  not bound total time.
- Failures never raise out of `call_jev`. They are mapped to a categorised `JevError`
  with one of `timeout`, `http_error`, or `invalid_response`.
- Exceptions that may embed request details are reduced to their class name before logging.
"""

import json
import logging
import math
import os
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from pathlib import Path
from typing import (
    Any,
    Callable,
    Collection,
    Dict,
    Mapping,
    Optional,
    Union,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants and configuration
# ---------------------------------------------------------------------------

JEV_URL = "https://api.typesafe.ai/v1/systemone"

# Keys for the typed questions sent to Jev and the answers it returns.
CHOICE_KEY = "model_choice"
HIGH_CONSEQUENCE_KEY = "high_consequence"

# Pinned, versioned model ID. The docs advise pinning a versioned ID rather than an
# alias because aliases can move. Configurable through JEV_MODEL.
DEFAULT_JEV_MODEL = "jev-1.13.0"

# Default wall-clock request timeout in seconds, configurable through JEV_TIMEOUT_SECONDS.
DEFAULT_TIMEOUT_SECONDS = 5.0

# Path to the recorded responses used by recorded mode.
_RECORDINGS_PATH = Path(__file__).with_name("jev_recordings.json")


def get_jev_model() -> str:
    """Return the pinned Jev model ID from the environment, defaulting safely."""
    model = os.environ.get("JEV_MODEL", "").strip()
    return model or DEFAULT_JEV_MODEL


def get_timeout_seconds() -> float:
    """
    Return the request timeout in seconds from JEV_TIMEOUT_SECONDS.

    An unparsable or out-of-range value falls back to the default and logs a warning,
    so a bad configuration never breaks a request.
    """
    raw = os.environ.get("JEV_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except (TypeError, ValueError):
        logger.warning("Invalid JEV_TIMEOUT_SECONDS; using default %.1fs", DEFAULT_TIMEOUT_SECONDS)
        return DEFAULT_TIMEOUT_SECONDS
    if not math.isfinite(value) or value <= 0:
        logger.warning("Out-of-range JEV_TIMEOUT_SECONDS; using default %.1fs", DEFAULT_TIMEOUT_SECONDS)
        return DEFAULT_TIMEOUT_SECONDS
    return value


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class JevAnswer:
    """A successfully parsed Jev answer. Holds no secret and no request details."""

    choice: str  # selected option, raw from Jev
    probabilities: Dict[str, float]  # option -> probability, each in [0, 1]
    confidence: float  # in [0, 1]
    high_consequence: Optional[float]  # noul probability, None if not asked
    model_version: Optional[str]  # versioned model ID reported by Jev


@dataclass(frozen=True)
class JevError:
    """
    A categorised Jev failure. Never holds the key, headers, or request body.

    `category` is one of "timeout", "http_error", or "invalid_response".
    `status_code` is the HTTP status when one exists.
    `detail` is a short, safe tag (for example "no_recording"); it never contains
    secrets, query text, or raw exception messages.
    """

    category: str
    status_code: Optional[int] = None
    detail: Optional[str] = None


JevOutcome = Union[JevAnswer, JevError]


# ---------------------------------------------------------------------------
# Capability-derived option descriptions
# ---------------------------------------------------------------------------


def describe_capability(capabilities: Any) -> str:
    """
    Build a short, human-readable description of a model from its ModelCapabilities.

    The description is derived entirely from the capability profile so the catalogue
    has a single source of truth. It names the strongest capabilities, the relative
    cost, and the typical latency. The input is the ModelCapabilities dataclass from
    router.py; it is read, never modified.
    """
    named = [
        ("reasoning", getattr(capabilities, "reasoning_capability", 0.0)),
        ("creativity", getattr(capabilities, "creativity_capability", 0.0)),
        ("code", getattr(capabilities, "code_capability", 0.0)),
        ("analysis", getattr(capabilities, "analysis_capability", 0.0)),
    ]
    # Strengths are the two highest-scoring capabilities.
    strengths = sorted(named, key=lambda item: item[1], reverse=True)[:2]
    strength_text = ", ".join(name for name, _ in strengths)

    cost_score = float(getattr(capabilities, "cost_score", 0.5))
    if cost_score <= 0.33:
        cost_text = "low cost"
    elif cost_score <= 0.66:
        cost_text = "moderate cost"
    else:
        cost_text = "higher cost"

    latency_ms = int(getattr(capabilities, "avg_response_time_ms", 0))

    return (
        f"Strongest at {strength_text}; {cost_text}; "
        f"typical latency about {latency_ms} ms."
    )


# ---------------------------------------------------------------------------
# Request building
# ---------------------------------------------------------------------------

# The characteristic keys forwarded to Jev. These mirror the signals the
# Custom_Router derives from QueryAnalyzer, so Jev sees the same information.
_CHARACTERISTIC_KEYS = (
    "length",
    "complexity_score",
    "estimated_tokens",
    "requires_reasoning",
    "requires_creativity",
    "requires_code",
    "requires_analysis",
)

_CHOICE_INSTRUCTIONS = (
    "Which model is the best fit for answering this query? "
    "Consider the query text and its characteristics, and choose the single "
    "option whose capabilities best match the request."
)

_HIGH_CONSEQUENCE_INSTRUCTIONS = (
    "Does answering this query have high-consequence outcomes, where an incorrect "
    "or low-quality answer could cause significant harm?"
)


def build_request(
    query_text: str,
    characteristics: Mapping[str, Any],
    catalogue: Mapping[str, str],
    model: str,
    include_high_consequence: bool,
) -> Dict[str, Any]:
    """
    Build the JSON-serialisable request payload for the Jev API.

    Args:
        query_text: The raw query text, forwarded as `state.query`.
        characteristics: Derived query characteristics (from QueryAnalyzer). Only the
            known characteristic keys are forwarded.
        catalogue: Mapping of model ID -> short capability description. The option keys
            of the Choice question are exactly these model IDs.
        model: The pinned, versioned model ID (for example "jev-1.13.0").
        include_high_consequence: When true, add the `noul` high-consequence question.

    Returns:
        A plain dict ready for JSON serialisation, with `model`, `state`, and `questions`.
    """
    forwarded = {
        key: characteristics[key]
        for key in _CHARACTERISTIC_KEYS
        if key in characteristics
    }

    questions: Dict[str, Any] = {
        CHOICE_KEY: {
            "type": "choice",
            "instructions": _CHOICE_INSTRUCTIONS,
            "criteria": {model_id: description for model_id, description in catalogue.items()},
        }
    }

    if include_high_consequence:
        questions[HIGH_CONSEQUENCE_KEY] = {
            "type": "noul",
            "instructions": _HIGH_CONSEQUENCE_INSTRUCTIONS,
        }

    return {
        "model": model,
        "state": {
            "query": query_text,
            "characteristics": forwarded,
        },
        "questions": questions,
    }


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def _is_valid_probability(value: Any) -> bool:
    """A probability must be a finite real number in [0, 1]. Bools are rejected."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    number = float(value)
    return math.isfinite(number) and 0.0 <= number <= 1.0


def parse_response(body: bytes, catalogue_ids: Collection[str]) -> JevOutcome:
    """
    Parse a successful Jev response body into a JevAnswer, or a JevError on any problem.

    Catalogue membership of the choice is NOT checked here; that belongs to the
    Routing_Policy. `catalogue_ids` is used only to ignore extra probability keys.

    Rejected as "invalid_response": non-JSON, wrong top-level type, a missing
    `answers.model_choice`, a `choice` that is not a string, non-numeric / NaN /
    out-of-range probabilities or confidence, and a wrongly typed noul probability.
    """
    try:
        parsed = json.loads(body)
    except (ValueError, TypeError):
        return JevError("invalid_response")

    if not isinstance(parsed, dict):
        return JevError("invalid_response")

    answers = parsed.get("answers")
    if not isinstance(answers, dict):
        return JevError("invalid_response")

    choice_answer = answers.get(CHOICE_KEY)
    if not isinstance(choice_answer, dict):
        return JevError("invalid_response")

    choice = choice_answer.get("choice")
    if not isinstance(choice, str) or isinstance(choice, bool):
        return JevError("invalid_response")

    confidence = choice_answer.get("confidence")
    if not _is_valid_probability(confidence):
        return JevError("invalid_response")

    raw_probabilities = choice_answer.get("probabilities")
    if not isinstance(raw_probabilities, dict):
        return JevError("invalid_response")

    allowed = set(catalogue_ids)
    probabilities: Dict[str, float] = {}
    for option, value in raw_probabilities.items():
        if not isinstance(option, str):
            return JevError("invalid_response")
        # Validate every probability so NaN / out-of-range anywhere is rejected,
        # then keep only catalogue options in the result.
        if not _is_valid_probability(value):
            return JevError("invalid_response")
        if option in allowed:
            probabilities[option] = float(value)

    # Optional noul high-consequence answer.
    high_consequence: Optional[float] = None
    noul_answer = answers.get(HIGH_CONSEQUENCE_KEY)
    if noul_answer is not None:
        if not isinstance(noul_answer, dict):
            return JevError("invalid_response")
        noul_value = noul_answer.get("noul")
        if not _is_valid_probability(noul_value):
            return JevError("invalid_response")
        high_consequence = float(noul_value)

    model_version = parsed.get("model")
    if model_version is not None and not isinstance(model_version, str):
        model_version = None

    return JevAnswer(
        choice=choice,
        probabilities=probabilities,
        confidence=float(confidence),
        high_consequence=high_consequence,
        model_version=model_version,
    )


# ---------------------------------------------------------------------------
# HTTP transport and call
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _TransportResult:
    """The raw result of one transport call: an HTTP status and a response body."""

    status: int
    body: bytes


def _urllib_transport(payload: Dict[str, Any], api_key: str, timeout_s: float) -> _TransportResult:
    """
    Perform one POST to the Jev API with urllib.

    This is the only place the key is used, and only to build the Authorization header.
    The headers are never logged. A per-socket timeout is passed as a secondary guard;
    the wall-clock deadline in `call_jev` is the authoritative bound.

    Raises urllib / socket exceptions on failure; `call_jev` maps them to categories.
    """
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        JEV_URL,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        status = getattr(response, "status", None)
        if status is None:
            status = response.getcode()
        return _TransportResult(status=int(status), body=response.read())


def call_jev(
    payload: Dict[str, Any],
    api_key: str,
    timeout_s: float,
    transport: Callable[[Dict[str, Any], str, float], _TransportResult] = _urllib_transport,
    catalogue_ids: Optional[Collection[str]] = None,
) -> JevOutcome:
    """
    Call the Jev API and return a parsed answer or a categorised error. Never raises.

    A single worker thread runs the blocking transport, and the wall-clock deadline is
    enforced with `future.result(timeout=timeout_s)`. When the deadline expires the call
    returns `JevError("timeout")` immediately; the abandoned thread finishes on its own.

    Error mapping:
      - deadline expiry, socket timeout, timeout-caused URLError -> "timeout"
      - non-2xx HTTP status (401, 422, 429, 529, ...)           -> "http_error" + status
      - other network / HTTP errors                              -> "http_error", status None
      - bad body, wrong types, NaN, out-of-range, missing answer -> "invalid_response"

    `transport` is injectable so tests never touch the network. `catalogue_ids` is passed
    through to `parse_response`; when omitted, every catalogue option in the body is kept.
    """
    if catalogue_ids is None:
        catalogue_ids = _extract_catalogue_ids(payload)

    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(transport, payload, api_key, timeout_s)
        try:
            result = future.result(timeout=timeout_s)
        except FutureTimeoutError:
            # Deadline expired. Abandon the worker; the pool shuts down without waiting.
            logger.warning("Jev call exceeded the %.3fs deadline", timeout_s)
            return JevError("timeout")
        except urllib.error.HTTPError as exc:
            status = getattr(exc, "code", None)
            logger.warning("Jev HTTP error: status=%s", status)
            return JevError("http_error", status_code=_safe_status(status))
        except urllib.error.URLError as exc:
            # A URLError wrapping a timeout maps to "timeout"; anything else is a
            # network-level http_error with no status.
            if _is_timeout_reason(getattr(exc, "reason", None)):
                logger.warning("Jev call timed out (URLError)")
                return JevError("timeout")
            logger.warning("Jev network error: %s", type(exc).__name__)
            return JevError("http_error", status_code=None)
        except TimeoutError:
            logger.warning("Jev call timed out")
            return JevError("timeout")
        except Exception as exc:  # noqa: BLE001 - never let the Jev path raise
            logger.warning("Jev call failed: %s", type(exc).__name__)
            return JevError("http_error", status_code=None)
    finally:
        # Do not block on an abandoned worker when the deadline has expired.
        executor.shutdown(wait=False)

    if not 200 <= result.status < 300:
        logger.warning("Jev returned non-2xx status: %s", result.status)
        return JevError("http_error", status_code=result.status)

    return parse_response(result.body, catalogue_ids)


def _extract_catalogue_ids(payload: Dict[str, Any]) -> Collection[str]:
    """Pull the option keys from the Choice question so extra probabilities are ignored."""
    try:
        criteria = payload["questions"][CHOICE_KEY]["criteria"]
        if isinstance(criteria, dict):
            return list(criteria.keys())
    except (KeyError, TypeError):
        pass
    return ()


def _safe_status(status: Any) -> Optional[int]:
    """Coerce an HTTP status to int, or None if it is not a plain integer."""
    if isinstance(status, bool):
        return None
    if isinstance(status, int):
        return status
    try:
        return int(status)
    except (TypeError, ValueError):
        return None


def _is_timeout_reason(reason: Any) -> bool:
    """Return True when a URLError reason represents a timeout."""
    if isinstance(reason, TimeoutError):
        return True
    # socket.timeout is an alias of OSError with "timed out" text on older runtimes.
    text = str(reason).lower() if reason is not None else ""
    return "timed out" in text or "timeout" in text


# ---------------------------------------------------------------------------
# Recorded mode
# ---------------------------------------------------------------------------


def _normalise_query(query: str) -> str:
    """Trim, case-fold, and collapse internal whitespace for recorded-mode matching."""
    return " ".join(query.strip().casefold().split())


def load_recording(query: str) -> JevOutcome:
    """
    Return a recorded Jev answer for `query` in recorded mode, or a no-recording error.

    The recordings file (lambda/jev_recordings.json) is a list of
    {"query_normalised": ..., "response": <parsed-response shape>} entries. Matching is by
    normalised exact text (trimmed, case-folded, whitespace-collapsed). A miss returns
    `JevError("invalid_response", detail="no_recording")`, which the Routing_Policy turns
    into a fallback whose reasoning states that no recording matched. No HTTP call is made.
    """
    target = _normalise_query(query)
    try:
        raw = _RECORDINGS_PATH.read_bytes()
    except OSError:
        logger.warning("Jev recordings file is unavailable")
        return JevError("invalid_response", detail="no_recording")

    try:
        entries = json.loads(raw)
    except (ValueError, TypeError):
        logger.warning("Jev recordings file is not valid JSON")
        return JevError("invalid_response", detail="no_recording")

    if not isinstance(entries, list):
        return JevError("invalid_response", detail="no_recording")

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        recorded_query = entry.get("query_normalised")
        if not isinstance(recorded_query, str):
            continue
        if _normalise_query(recorded_query) != target:
            continue
        response = entry.get("response")
        if not isinstance(response, dict):
            continue
        # The recorded response uses the exact parsed-response wire shape, so it is
        # parsed through the same path as a live response.
        catalogue_ids = _catalogue_ids_from_response(response)
        return parse_response(json.dumps(response).encode("utf-8"), catalogue_ids)

    return JevError("invalid_response", detail="no_recording")


def _catalogue_ids_from_response(response: Mapping[str, Any]) -> Collection[str]:
    """Derive catalogue option keys from a recorded response's probabilities."""
    try:
        probabilities = response["answers"][CHOICE_KEY]["probabilities"]
        if isinstance(probabilities, dict):
            return list(probabilities.keys())
    except (KeyError, TypeError):
        pass
    return ()
