"""Unit tests for the Jev_Secret loader (task 2.2).

These tests exercise ``lambda/jev_secret.py`` fully offline. No real AWS call is
made and no real API key is ever read: ``boto3.client`` is replaced with a fake
that records how many times it was invoked and returns scripted responses for
both backends (SSM Parameter Store and Secrets Manager).

What is covered:

* Both backends return a key: SSM ``get_parameter(WithDecryption=True)`` and
  Secrets Manager ``get_secret_value`` accepting a raw string AND a JSON object
  with an ``api_key`` field.
* A second ``get_jev_key()`` call does not re-read the secret - the key is
  cached for the execution environment, so the fake client is invoked only once
  across two calls.
* A failed read makes Jev report "not configured", logs only an error category
  (no key value, no full exception message), and is remembered for the failure
  window so a second call does not re-hit AWS.
* Recorded mode (``JEV_MODE=recorded``) needs no secret: ``jev_status`` reports
  ``mode="recorded"`` and ``configured=True`` without any AWS call.
* ``jev_status`` never calls the Jev API and never exposes the key value.

Validates: Requirements 9.1, 9.7, 9.8, 15.2
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pytest
from botocore.exceptions import ClientError

import jev_secret


# --------------------------------------------------------------------------- #
# Fake boto3 client plumbing.
# --------------------------------------------------------------------------- #
# ``jev_secret`` calls ``boto3.client("ssm")`` / ``boto3.client("secretsmanager")``
# and then ``get_parameter`` / ``get_secret_value`` on the returned object. We
# replace ``jev_secret.boto3.client`` with a factory that hands back a fake
# client scripted per service name, and we count every factory invocation so a
# test can assert the secret was read exactly once.


class _FakeSsmClient:
    """Stand-in for an SSM client returning one scripted SecureString value."""

    def __init__(self, value: Any, error: Optional[Exception]) -> None:
        self._value = value
        self._error = error
        self.get_parameter_calls: List[Dict[str, Any]] = []

    def get_parameter(self, **kwargs: Any) -> Dict[str, Any]:
        self.get_parameter_calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return {"Parameter": {"Value": self._value}}


class _FakeSecretsManagerClient:
    """Stand-in for a Secrets Manager client returning one scripted secret."""

    def __init__(self, secret_string: Any, error: Optional[Exception]) -> None:
        self._secret_string = secret_string
        self._error = error
        self.get_secret_value_calls: List[Dict[str, Any]] = []

    def get_secret_value(self, **kwargs: Any) -> Dict[str, Any]:
        self.get_secret_value_calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return {"SecretString": self._secret_string}


class _FakeBoto3:
    """Records every ``client(service)`` call and returns a scripted fake.

    ``factory_calls`` counts how many times ``client(...)`` was invoked so a
    test can prove the cache prevents a second AWS read. Each service name maps
    to a single pre-built fake client.
    """

    def __init__(self, clients: Dict[str, Any]) -> None:
        self._clients = clients
        self.factory_calls: List[str] = []

    def client(self, service_name: str, *args: Any, **kwargs: Any) -> Any:
        self.factory_calls.append(service_name)
        try:
            return self._clients[service_name]
        except KeyError:  # pragma: no cover - a test asked for an unscripted client
            raise AssertionError(
                f"Unexpected boto3.client({service_name!r}); none scripted"
            )

    @property
    def factory_call_count(self) -> int:
        return len(self.factory_calls)


def _install_ssm(
    monkeypatch: pytest.MonkeyPatch,
    value: Any = "sk-live-ssm-key",
    error: Optional[Exception] = None,
) -> _FakeBoto3:
    """Replace boto3 in jev_secret with an SSM-only fake and return it."""
    client = _FakeSsmClient(value=value, error=error)
    fake = _FakeBoto3({"ssm": client})
    monkeypatch.setattr(jev_secret, "boto3", fake)
    return fake


def _install_secrets_manager(
    monkeypatch: pytest.MonkeyPatch,
    secret_string: Any = "sk-live-sm-key",
    error: Optional[Exception] = None,
) -> _FakeBoto3:
    """Replace boto3 in jev_secret with a Secrets-Manager-only fake."""
    client = _FakeSecretsManagerClient(secret_string=secret_string, error=error)
    fake = _FakeBoto3({"secretsmanager": client})
    monkeypatch.setattr(jev_secret, "boto3", fake)
    return fake


@pytest.fixture(autouse=True)
def _fresh_cache() -> Any:
    """Start and end every test with a clean module cache.

    The loader caches across the execution environment, so without this a key
    read by one test would mask an AWS call that should have happened in the
    next. The autouse ``_isolate_jev_env`` fixture (conftest) already clears all
    ``JEV_*`` environment variables.
    """
    jev_secret._reset_cache_for_tests()
    yield
    jev_secret._reset_cache_for_tests()


# --------------------------------------------------------------------------- #
# SSM backend.
# --------------------------------------------------------------------------- #


def test_ssm_backend_reads_securestring_with_decryption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SSM backend reads the parameter with WithDecryption=True (Req 9.1)."""
    monkeypatch.setenv("JEV_SECRET_NAME", "/jev/api-key")
    monkeypatch.setenv("JEV_SECRET_TYPE", "ssm")
    fake = _install_ssm(monkeypatch, value="sk-live-ssm-key")

    key = jev_secret.get_jev_key()

    assert key == "sk-live-ssm-key"
    ssm_client = fake._clients["ssm"]
    assert len(ssm_client.get_parameter_calls) == 1
    call = ssm_client.get_parameter_calls[0]
    assert call["Name"] == "/jev/api-key"
    assert call["WithDecryption"] is True


def test_ssm_is_the_default_backend_when_type_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no JEV_SECRET_TYPE the loader defaults to SSM."""
    monkeypatch.setenv("JEV_SECRET_NAME", "/jev/api-key")
    fake = _install_ssm(monkeypatch, value="sk-default-ssm")

    key = jev_secret.get_jev_key()

    assert key == "sk-default-ssm"
    assert fake.factory_calls == ["ssm"]


# --------------------------------------------------------------------------- #
# Secrets Manager backend.
# --------------------------------------------------------------------------- #


def test_secrets_manager_accepts_a_raw_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Secrets Manager returning a raw string yields that string as the key."""
    monkeypatch.setenv("JEV_SECRET_NAME", "jev/api-key")
    monkeypatch.setenv("JEV_SECRET_TYPE", "secretsmanager")
    fake = _install_secrets_manager(monkeypatch, secret_string="sk-raw-string-key")

    key = jev_secret.get_jev_key()

    assert key == "sk-raw-string-key"
    sm_client = fake._clients["secretsmanager"]
    assert len(sm_client.get_secret_value_calls) == 1
    assert sm_client.get_secret_value_calls[0]["SecretId"] == "jev/api-key"


def test_secrets_manager_accepts_json_with_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A JSON object with an api_key field yields that field as the key."""
    monkeypatch.setenv("JEV_SECRET_NAME", "jev/api-key")
    monkeypatch.setenv("JEV_SECRET_TYPE", "secretsmanager")
    payload = json.dumps({"api_key": "sk-json-key", "other": "ignored"})
    _install_secrets_manager(monkeypatch, secret_string=payload)

    key = jev_secret.get_jev_key()

    assert key == "sk-json-key"


# --------------------------------------------------------------------------- #
# Caching: a second call does not re-read (Requirement 9.8).
# --------------------------------------------------------------------------- #


def test_second_call_uses_cache_and_does_not_re_read_ssm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two get_jev_key() calls read the SSM parameter only once (Req 9.8)."""
    monkeypatch.setenv("JEV_SECRET_NAME", "/jev/api-key")
    monkeypatch.setenv("JEV_SECRET_TYPE", "ssm")
    fake = _install_ssm(monkeypatch, value="sk-cached-ssm")

    first = jev_secret.get_jev_key()
    second = jev_secret.get_jev_key()

    assert first == second == "sk-cached-ssm"
    # The client factory and the parameter read each happened exactly once.
    assert fake.factory_call_count == 1
    assert len(fake._clients["ssm"].get_parameter_calls) == 1


def test_second_call_uses_cache_and_does_not_re_read_secrets_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two get_jev_key() calls read the secret only once (Req 9.8)."""
    monkeypatch.setenv("JEV_SECRET_NAME", "jev/api-key")
    monkeypatch.setenv("JEV_SECRET_TYPE", "secretsmanager")
    fake = _install_secrets_manager(monkeypatch, secret_string="sk-cached-sm")

    first = jev_secret.get_jev_key()
    second = jev_secret.get_jev_key()

    assert first == second == "sk-cached-sm"
    assert fake.factory_call_count == 1
    assert len(fake._clients["secretsmanager"].get_secret_value_calls) == 1


# --------------------------------------------------------------------------- #
# Failed read: not configured, category-only log, remembered (Req 9.7).
# --------------------------------------------------------------------------- #


def test_failed_read_reports_not_configured_and_logs_category_only(
    monkeypatch: pytest.MonkeyPatch, log_capture: Any
) -> None:
    """A read failure yields None, and the log shows only the error category.

    The raw secret value and the full exception message must never appear in
    the captured log output (Requirement 9.5/9.7).
    """
    monkeypatch.setenv("JEV_SECRET_NAME", "/jev/api-key")
    monkeypatch.setenv("JEV_SECRET_TYPE", "ssm")
    secret_value = "sk-should-never-be-logged"
    error = ClientError(
        {
            "Error": {
                "Code": "AccessDeniedException",
                # A realistic, sensitive-looking message that must not leak.
                "Message": f"User is not authorized; value={secret_value}",
            }
        },
        "GetParameter",
    )
    _install_ssm(monkeypatch, error=error)

    key = jev_secret.get_jev_key()

    assert key is None
    # jev_status agrees that Jev is not configured after the failure.
    assert jev_secret.jev_status() == {"configured": False, "mode": "live"}

    # The log carries the stable error category...
    assert log_capture.contains("ClientError:AccessDeniedException")
    # ...but never the secret value or the full exception message.
    assert not log_capture.contains(secret_value)
    assert not log_capture.contains("not authorized")


def test_failed_read_is_remembered_for_the_failure_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After a failure, a second call within the window does not re-hit AWS.

    jev_status() also calls get_jev_key(); across the explicit call plus the
    status check the SSM parameter is read exactly once (Req 9.7).
    """
    monkeypatch.setenv("JEV_SECRET_NAME", "/jev/api-key")
    monkeypatch.setenv("JEV_SECRET_TYPE", "ssm")
    error = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "denied"}},
        "GetParameter",
    )
    fake = _install_ssm(monkeypatch, error=error)

    assert jev_secret.get_jev_key() is None
    # Second explicit call and a status check both fall in the failure window.
    assert jev_secret.get_jev_key() is None
    assert jev_secret.jev_status()["configured"] is False

    # The parameter was read exactly once despite three configured calls.
    assert len(fake._clients["ssm"].get_parameter_calls) == 1


def test_empty_name_is_not_configured_and_makes_no_aws_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty secret name means not configured and triggers no client call."""
    monkeypatch.setenv("JEV_SECRET_NAME", "   ")  # whitespace-only -> empty
    monkeypatch.setenv("JEV_SECRET_TYPE", "ssm")
    fake = _install_ssm(monkeypatch)

    assert jev_secret.get_jev_key() is None
    assert jev_secret.jev_status() == {"configured": False, "mode": "live"}
    assert fake.factory_call_count == 0


def test_empty_secret_value_is_treated_as_not_configured(
    monkeypatch: pytest.MonkeyPatch, log_capture: Any
) -> None:
    """A reachable-but-empty value is treated as not configured, logged safely."""
    monkeypatch.setenv("JEV_SECRET_NAME", "/jev/api-key")
    monkeypatch.setenv("JEV_SECRET_TYPE", "ssm")
    _install_ssm(monkeypatch, value="   ")  # whitespace-only value

    assert jev_secret.get_jev_key() is None
    # No key value could leak since there was none; log stays category-only.
    assert "sk-" not in log_capture.text


# --------------------------------------------------------------------------- #
# Recorded mode: no secret required (Requirement 15.2).
# --------------------------------------------------------------------------- #


def test_recorded_mode_reports_configured_without_a_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recorded mode needs no secret: configured=True, mode=recorded (Req 15.2)."""
    monkeypatch.setenv("JEV_MODE", "recorded")
    # No JEV_SECRET_NAME set at all. Install a fail-loud boto3 so any AWS call
    # would surface as an error.
    fake = _install_ssm(monkeypatch)

    status = jev_secret.jev_status()

    assert status == {"configured": True, "mode": "recorded"}
    # Recorded mode must not read any secret from AWS.
    assert fake.factory_call_count == 0


def test_recorded_mode_ignores_a_configured_secret_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even with a secret name set, recorded mode does not read it."""
    monkeypatch.setenv("JEV_MODE", "recorded")
    monkeypatch.setenv("JEV_SECRET_NAME", "/jev/api-key")
    fake = _install_ssm(monkeypatch, value="sk-should-not-be-read")

    status = jev_secret.jev_status()

    assert status == {"configured": True, "mode": "recorded"}
    assert fake.factory_call_count == 0


# --------------------------------------------------------------------------- #
# jev_status never leaks the key and never calls the Jev API.
# --------------------------------------------------------------------------- #


def test_jev_status_configured_true_without_exposing_the_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With a readable secret, status is configured but holds no key value."""
    monkeypatch.setenv("JEV_SECRET_NAME", "/jev/api-key")
    monkeypatch.setenv("JEV_SECRET_TYPE", "ssm")
    secret_value = "sk-live-ssm-key"
    _install_ssm(monkeypatch, value=secret_value)

    status = jev_secret.jev_status()

    assert status == {"configured": True, "mode": "live"}
    # The status dict exposes only booleans/strings, never the key value.
    assert secret_value not in json.dumps(status)


def test_jev_status_does_not_leak_key_from_cache(
    monkeypatch: pytest.MonkeyPatch, log_capture: Any
) -> None:
    """A cached key is never serialised into the status or the logs."""
    secret_value = "sk-super-secret-cached"
    monkeypatch.setenv("JEV_SECRET_NAME", "/jev/api-key")
    # Seed the cache directly, as a successful read would, with no AWS call.
    monkeypatch.setattr(jev_secret, "_cached_key", secret_value, raising=False)

    status = jev_secret.jev_status()

    assert status["configured"] is True
    assert status["mode"] == "live"
    assert secret_value not in json.dumps(status)
    assert not log_capture.contains(secret_value)
