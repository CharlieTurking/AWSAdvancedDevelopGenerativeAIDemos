"""
Jev_Secret loader for the TypeSafe API key.

This module reads the TypeSafe (Jev) API key from AWS Systems Manager Parameter
Store or AWS Secrets Manager, strictly inside the Lambda backend. The key is
cached in memory for the lifetime of the execution environment so it is not
re-read on every request.

Security properties enforced here:
- The key value is never logged, returned in status, or raised in an exception
  message. Failures log only an error *category* (for example
  ``ClientError:AccessDeniedException``).
- A failed read is remembered for a short window so a broken or missing secret
  does not add an AWS call to every request, and Jev is treated as "not
  configured" during that window.
- ``jev_status`` reports whether Jev is configured without ever calling the Jev
  API or exposing the key.

Configuration (environment variables set by SAM):
- ``JEV_SECRET_NAME``: SSM parameter name or Secrets Manager secret name/ARN.
  An empty value means Jev is not configured.
- ``JEV_SECRET_TYPE``: ``ssm`` (default) or ``secretsmanager``.
- ``JEV_MODE``: ``recorded`` enables offline recorded mode; any other value
  (or unset) means ``live``.
"""

import json
import logging
import os
import time
from typing import Any, Dict, Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)

# How long a failed secret read is remembered before we try again. During this
# window Jev is treated as not configured (Requirement 9.7).
_FAILURE_TTL_SECONDS = 60

# Module-level cache that lives for the duration of the Lambda execution
# environment (Requirement 9.8). A successful read stores the key; a failed
# read stores the time of failure so we can suppress repeated AWS calls.
_cached_key: Optional[str] = None
_last_failure_at: Optional[float] = None


def _secret_name() -> str:
    """Return the configured secret name, trimmed. Empty means not configured."""
    return (os.environ.get("JEV_SECRET_NAME") or "").strip()


def _secret_type() -> str:
    """Return the configured secret backend, defaulting to ``ssm``."""
    value = (os.environ.get("JEV_SECRET_TYPE") or "ssm").strip().lower()
    return value if value in ("ssm", "secretsmanager") else "ssm"


def _mode() -> str:
    """Return ``recorded`` when recorded mode is enabled, otherwise ``live``."""
    return "recorded" if (os.environ.get("JEV_MODE") or "").strip().lower() == "recorded" else "live"


def _error_category(exc: Exception) -> str:
    """
    Reduce an exception to a safe, loggable category.

    Never includes the secret value or the full exception message. For a
    botocore ``ClientError`` the AWS error code is appended because it is a
    stable, non-sensitive classifier (for example ``AccessDeniedException``).
    """
    if isinstance(exc, ClientError):
        code = exc.response.get("Error", {}).get("Code", "Unknown")
        return "ClientError:{}".format(code)
    return type(exc).__name__


def _read_ssm(name: str) -> Optional[str]:
    """Read a SecureString parameter from SSM Parameter Store."""
    client = boto3.client("ssm")
    response = client.get_parameter(Name=name, WithDecryption=True)
    value = response.get("Parameter", {}).get("Value")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _read_secrets_manager(name: str) -> Optional[str]:
    """
    Read a secret from AWS Secrets Manager.

    The stored value may be a raw string key or a JSON object with an
    ``api_key`` field; both forms are accepted.
    """
    client = boto3.client("secretsmanager")
    response = client.get_secret_value(SecretId=name)
    raw = response.get("SecretString")
    if not isinstance(raw, str) or not raw.strip():
        return None
    raw = raw.strip()
    # Try JSON with an api_key field; fall back to treating it as a raw key.
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return raw
    if isinstance(parsed, dict):
        api_key = parsed.get("api_key")
        if isinstance(api_key, str) and api_key.strip():
            return api_key.strip()
        return None
    # JSON that is not an object (e.g. a quoted string) -> use the raw value.
    return raw


def get_jev_key() -> Optional[str]:
    """
    Return the TypeSafe API key, or ``None`` when Jev is not configured or a
    recent read failed.

    The key is cached in memory for the life of the execution environment. A
    failed read is remembered for ``_FAILURE_TTL_SECONDS`` and treated as "not
    configured" during that window.
    """
    global _cached_key, _last_failure_at

    # Return the cached key if we already have one.
    if _cached_key is not None:
        return _cached_key

    name = _secret_name()
    if not name:
        # No secret configured at all.
        return None

    # Suppress repeated AWS calls while a recent failure is still remembered.
    if _last_failure_at is not None:
        if (time.monotonic() - _last_failure_at) < _FAILURE_TTL_SECONDS:
            return None
        # Window elapsed; clear it and try again.
        _last_failure_at = None

    backend = _secret_type()
    try:
        if backend == "secretsmanager":
            key = _read_secrets_manager(name)
        else:
            key = _read_ssm(name)
    except (ClientError, BotoCoreError, ValueError, TypeError) as exc:
        # Log only the error category, never the value or full message.
        logger.warning("Jev secret read failed: %s", _error_category(exc))
        _last_failure_at = time.monotonic()
        return None
    except Exception as exc:  # defensive: never let a secret read break a request
        logger.warning("Jev secret read failed: %s", _error_category(exc))
        _last_failure_at = time.monotonic()
        return None

    if not key:
        # Reachable but empty/malformed value: treat as not configured and
        # remember the failure so we do not re-read on every request.
        logger.warning("Jev secret read failed: %s", "EmptyOrMalformedValue")
        _last_failure_at = time.monotonic()
        return None

    _cached_key = key
    _last_failure_at = None
    return _cached_key


def jev_status() -> Dict[str, Any]:
    """
    Report whether Jev is configured and the current mode.

    Returns ``{"configured": bool, "mode": "live" | "recorded"}`` without
    calling the Jev API and without exposing the key value.

    In recorded mode no secret is required, so ``configured`` is reported as
    ``True`` regardless of the secret.
    """
    mode = _mode()
    if mode == "recorded":
        return {"configured": True, "mode": "recorded"}
    return {"configured": get_jev_key() is not None, "mode": "live"}


def _reset_cache_for_tests() -> None:
    """Clear the in-memory cache. Intended for use by the test suite only."""
    global _cached_key, _last_failure_at
    _cached_key = None
    _last_failure_at = None
