"""Unit tests for the Jev object added to the /health response (task 5.5).

These tests verify `handle_health_check` adds a `jev` object of the exact shape
`{configured, mode, confidence_threshold}` sourced from `jev_status()` and
`get_confidence_threshold()`, that it is built without calling the Jev API, and
that the key value never appears in the response.

Validates: Requirements 8.1, 8.2, 8.3, 15.2

The handler's AWS-backed components are replaced with lightweight fakes so the
test runs fully offline.
"""

from __future__ import annotations

import json
from typing import Any, Dict

import pytest

import lambda_handler


class _FakeHealthMonitor:
    """Minimal stand-in that returns a static system-health overview."""

    def get_system_health_overview(self) -> Dict[str, Any]:
        return {
            "system_health": {
                "overall_status": "healthy",
                "healthy_models": 3,
                "total_models": 3,
            },
            "provider_health": {},
            "circuit_breakers": {
                "total_breakers": 0,
                "open_breakers": 0,
                "half_open_breakers": 0,
            },
            "cache_performance": {},
        }


class _FakeRouter:
    def get_routing_statistics(self) -> Dict[str, Any]:
        return {
            "total_routing_decisions": 0,
            "average_confidence": 0.0,
            "provider_distribution": {},
        }


@pytest.fixture
def offline_components(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace get_components() so the health check never touches AWS."""
    fake = (object(), _FakeHealthMonitor(), _FakeRouter())
    monkeypatch.setattr(lambda_handler, "get_components", lambda: fake)


def test_health_includes_jev_object_with_exact_shape(offline_components: None) -> None:
    """The health response carries jev: {configured, mode, confidence_threshold}."""
    health = lambda_handler.handle_health_check()

    assert "jev" in health
    jev = health["jev"]
    assert set(jev.keys()) == {"configured", "mode", "confidence_threshold"}
    assert isinstance(jev["configured"], bool)
    assert jev["mode"] in ("live", "recorded")
    assert isinstance(jev["confidence_threshold"], float)


def test_unconfigured_default_is_live_and_not_configured(offline_components: None) -> None:
    """With no secret configured, jev reports not-configured, live, default 0.6."""
    # The autouse env-isolation fixture clears all JEV_* vars, so this is the
    # unconfigured, live, default-threshold baseline.
    health = lambda_handler.handle_health_check()

    assert health["jev"] == {
        "configured": False,
        "mode": "live",
        "confidence_threshold": 0.6,
    }


def test_recorded_mode_reports_configured_true(
    offline_components: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Recorded mode needs no secret, so configured is True and mode is recorded."""
    monkeypatch.setenv("JEV_MODE", "recorded")
    jev_secret = __import__("jev_secret")
    jev_secret._reset_cache_for_tests()

    health = lambda_handler.handle_health_check()

    assert health["jev"]["mode"] == "recorded"
    assert health["jev"]["configured"] is True


def test_configured_threshold_is_reflected(
    offline_components: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The confidence_threshold comes from JEV_CONFIDENCE_THRESHOLD."""
    monkeypatch.setenv("JEV_CONFIDENCE_THRESHOLD", "0.8")

    health = lambda_handler.handle_health_check()

    assert health["jev"]["confidence_threshold"] == 0.8


def test_health_does_not_leak_the_key(
    offline_components: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even when a key is cached, it never appears in the health response.

    jev_status() must not call the Jev API and must not include the key value.
    We seed the module-level cache directly (no AWS call) and assert the secret
    string is absent from the serialised response while configured is True.
    """
    secret_value = "sk-super-secret-typesafe-key-value"
    jev_secret = __import__("jev_secret")
    jev_secret._reset_cache_for_tests()
    # Seed the cache as a successful read would, without any network/AWS call.
    monkeypatch.setattr(jev_secret, "_cached_key", secret_value, raising=False)

    health = lambda_handler.handle_health_check()

    assert health["jev"]["configured"] is True
    serialised = json.dumps(health, default=str)
    assert secret_value not in serialised

    jev_secret._reset_cache_for_tests()
