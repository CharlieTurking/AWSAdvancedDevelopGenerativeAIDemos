"""Shared pytest fixtures for the jev-router-comparison test suite.

Responsibilities of this module:

* Put ``lambda/`` on ``sys.path`` so test modules can ``import jev_client``,
  ``import jev_router`` etc. exactly the way the Lambda runtime does (the
  Lambda unpacks every module flat at the root of the package).
* Provide a fake Jev transport that records every call and can be scripted to
  return response bodies, non-2xx statuses, raise transport errors, or sleep
  past a deadline.
* Provide a "fail if called" transport for proving that a code path makes no
  HTTP call (e.g. Jev not configured, recorded mode, cache hit).
* Provide a log-capture fixture that collects records emitted by the Lambda
  modules so tests can assert that secrets and query text never leak.

All tests run fully offline: no fixture here ever touches the network or reads
a real API key.
"""

from __future__ import annotations

import io
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

import pytest

# --------------------------------------------------------------------------- #
# Make the Lambda source importable.
# --------------------------------------------------------------------------- #
# The Lambda package keeps every module flat under ``lambda/`` (that directory
# also vendors boto3). Tests import those modules by their bare name, so we put
# ``lambda/`` at the front of sys.path. This mirrors the Lambda runtime, where
# the handler modules live at the root of the deployment package.
_LAMBDA_DIR = (Path(__file__).resolve().parent.parent / "lambda").resolve()
if str(_LAMBDA_DIR) not in sys.path:
    sys.path.insert(0, str(_LAMBDA_DIR))


# --------------------------------------------------------------------------- #
# Fake Jev transport.
# --------------------------------------------------------------------------- #
# ``jev_client.call_jev`` accepts an injectable ``transport`` callable so tests
# never hit the network. The real transport wraps ``urllib.request.urlopen``;
# it is handed the request URL, the JSON-encoded body (bytes), the header map,
# and the per-call timeout, and it returns a ``TransportResponse`` describing
# the HTTP outcome (status + body bytes). A transport may instead raise to
# simulate a network error, or sleep to simulate a slow endpoint so the
# wall-clock deadline in ``call_jev`` can fire.


@dataclass(frozen=True)
class TransportResponse:
    """A minimal HTTP response returned by a fake transport.

    Attributes:
        status: HTTP status code the fake endpoint "returned".
        body: Raw response body bytes (what ``parse_response`` will receive).
    """

    status: int
    body: bytes


@dataclass
class RecordedCall:
    """One transport invocation, captured for later assertions."""

    url: Optional[str]
    method: Optional[str]
    headers: Dict[str, str]
    body: Optional[bytes]
    timeout: Optional[float]

    @property
    def authorization(self) -> Optional[str]:
        """Return the ``Authorization`` header if present (case-insensitive)."""
        for key, value in self.headers.items():
            if key.lower() == "authorization":
                return value
        return None


# A scripted action is either:
#   * a TransportResponse (returned to call_jev),
#   * an Exception instance (raised to simulate a transport failure), or
#   * a float/int (seconds to sleep before returning the default response),
# and `default_action` is used once the scripted queue is exhausted.
TransportAction = Union[TransportResponse, Exception, float, int]


class FakeJevTransport:
    """Scriptable, call-recording stand-in for the real urllib transport.

    The fake is intentionally permissive about the call signature it accepts so
    task 1.2 can bind to it however ``call_jev`` passes arguments. It inspects
    whatever positional/keyword arguments arrive and records the URL, method,
    headers, body, and timeout it can find. Each invocation consumes the next
    scripted action; when the script is empty the ``default_action`` is used.

    Example (return a body):
        transport = FakeJevTransport(default_action=TransportResponse(200, b"{}"))

    Example (one 429 then a success):
        transport = FakeJevTransport(actions=[
            TransportResponse(429, b""),
            TransportResponse(200, good_body),
        ])

    Example (raise a network error):
        transport = FakeJevTransport(actions=[ConnectionResetError("boom")])

    Example (sleep past the deadline so call_jev reports a timeout):
        transport = FakeJevTransport(default_action=2.0,
                                     response_after_sleep=TransportResponse(200, b"{}"))
    """

    def __init__(
        self,
        actions: Optional[List[TransportAction]] = None,
        default_action: Optional[TransportAction] = None,
        response_after_sleep: Optional[TransportResponse] = None,
    ) -> None:
        self._actions: List[TransportAction] = list(actions or [])
        self._default: TransportAction = (
            default_action
            if default_action is not None
            else TransportResponse(200, b"{}")
        )
        self._response_after_sleep = (
            response_after_sleep
            if response_after_sleep is not None
            else TransportResponse(200, b"{}")
        )
        self.calls: List[RecordedCall] = []
        self._lock = threading.Lock()

    @property
    def call_count(self) -> int:
        return len(self.calls)

    @property
    def last_call(self) -> Optional[RecordedCall]:
        return self.calls[-1] if self.calls else None

    def _record(self, args: tuple, kwargs: dict) -> None:
        """Best-effort extraction of the request details from any call shape."""
        url: Optional[str] = kwargs.get("url")
        body: Optional[bytes] = kwargs.get("body") or kwargs.get("data")
        headers: Dict[str, str] = dict(kwargs.get("headers") or {})
        method: Optional[str] = kwargs.get("method")
        timeout: Optional[float] = kwargs.get("timeout")

        # Also scan positional args so we do not depend on call_jev's exact
        # calling convention (string -> url, bytes -> body, dict -> headers,
        # number -> timeout).
        for arg in args:
            if isinstance(arg, str) and url is None:
                url = arg
            elif isinstance(arg, (bytes, bytearray)) and body is None:
                body = bytes(arg)
            elif isinstance(arg, dict) and not headers:
                headers = {str(k): str(v) for k, v in arg.items()}
            elif isinstance(arg, (int, float)) and not isinstance(arg, bool) and timeout is None:
                timeout = float(arg)

        with self._lock:
            self.calls.append(
                RecordedCall(
                    url=url,
                    method=method,
                    headers=headers,
                    body=bytes(body) if body is not None else None,
                    timeout=timeout,
                )
            )

    def __call__(self, *args: Any, **kwargs: Any) -> TransportResponse:
        self._record(args, kwargs)

        action: TransportAction
        with self._lock:
            action = self._actions.pop(0) if self._actions else self._default

        if isinstance(action, Exception):
            raise action
        if isinstance(action, (int, float)) and not isinstance(action, bool):
            time.sleep(float(action))
            return self._response_after_sleep
        if isinstance(action, TransportResponse):
            return action
        raise TypeError(f"Unsupported scripted transport action: {action!r}")


class FailIfCalledTransport:
    """Transport that fails the test if invoked.

    Use this to prove a path makes no HTTP call: Jev not configured, recorded
    mode, or a cached secret. Any invocation raises AssertionError, which
    surfaces as a test failure rather than being swallowed by ``call_jev``'s
    error mapping.
    """

    def __init__(self) -> None:
        self.calls: List[RecordedCall] = []

    def __call__(self, *args: Any, **kwargs: Any) -> TransportResponse:  # noqa: D401
        raise AssertionError(
            "Jev transport was called but no HTTP call was expected for this path"
        )


@pytest.fixture
def fake_transport_factory() -> Callable[..., FakeJevTransport]:
    """Return a factory so a test can build a transport with its own script."""

    def _make(
        actions: Optional[List[TransportAction]] = None,
        default_action: Optional[TransportAction] = None,
        response_after_sleep: Optional[TransportResponse] = None,
    ) -> FakeJevTransport:
        return FakeJevTransport(
            actions=actions,
            default_action=default_action,
            response_after_sleep=response_after_sleep,
        )

    return _make


@pytest.fixture
def fake_transport() -> FakeJevTransport:
    """A ready-to-use transport that returns ``200 {}`` for every call."""
    return FakeJevTransport()


@pytest.fixture
def fail_if_called_transport() -> FailIfCalledTransport:
    """A transport that fails the test if any HTTP call is attempted."""
    return FailIfCalledTransport()


# --------------------------------------------------------------------------- #
# Log capture.
# --------------------------------------------------------------------------- #
# A dedicated capture fixture (rather than only pytest's caplog) so tests can
# assert over the fully formatted log text - the form a secret or query string
# would actually leak in. It attaches a handler to the root logger and returns
# a small helper that exposes both the raw records and the rendered lines.


@dataclass
class LogCapture:
    """Collects formatted log output emitted during a test."""

    handler: logging.Handler
    stream: io.StringIO
    records: List[logging.LogRecord] = field(default_factory=list)

    @property
    def text(self) -> str:
        """All captured log output rendered as a single string."""
        return self.stream.getvalue()

    @property
    def lines(self) -> List[str]:
        """Captured log output split into non-empty lines."""
        return [line for line in self.text.splitlines() if line]

    def contains(self, needle: str) -> bool:
        """True if ``needle`` appears anywhere in the captured output."""
        return needle in self.text

    def clear(self) -> None:
        self.records.clear()
        self.stream.seek(0)
        self.stream.truncate(0)


class _RecordCollectingHandler(logging.Handler):
    """Logging handler that both renders to a stream and keeps the records."""

    def __init__(self, stream: io.StringIO, records: List[logging.LogRecord]) -> None:
        super().__init__()
        self._stream = stream
        self._records = records

    def emit(self, record: logging.LogRecord) -> None:
        self._records.append(record)
        try:
            msg = self.format(record)
        except Exception:  # pragma: no cover - formatting should not fail tests
            msg = record.getMessage()
        self._stream.write(msg + "\n")


@pytest.fixture
def log_capture() -> Any:
    """Capture all log output at DEBUG level for leak and content assertions.

    Yields a :class:`LogCapture`. The handler is attached to the root logger so
    it catches records from every Lambda module regardless of logger name, then
    is cleanly detached (and the root level restored) on teardown.
    """
    stream = io.StringIO()
    records: List[logging.LogRecord] = []
    handler = _RecordCollectingHandler(stream, records)
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(
        logging.Formatter("%(levelname)s:%(name)s:%(message)s")
    )

    root = logging.getLogger()
    previous_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)

    capture = LogCapture(handler=handler, stream=stream, records=records)
    try:
        yield capture
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)


# --------------------------------------------------------------------------- #
# Environment isolation.
# --------------------------------------------------------------------------- #
# Jev modules read configuration from environment variables (JEV_SECRET_NAME,
# JEV_MODE, thresholds, ...). This autouse fixture clears those for every test
# so a developer's shell cannot accidentally configure a real secret or flip
# modes mid-suite. Individual tests opt back in via monkeypatch.setenv.

_JEV_ENV_VARS = (
    "JEV_SECRET_NAME",
    "JEV_SECRET_TYPE",
    "JEV_MODE",
    "JEV_MODEL",
    "JEV_CONFIDENCE_THRESHOLD",
    "JEV_TIMEOUT_SECONDS",
    "JEV_HIGH_CONSEQUENCE_SIGNAL",
)


@pytest.fixture(autouse=True)
def _isolate_jev_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure no ambient Jev configuration leaks into a test."""
    for name in _JEV_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
