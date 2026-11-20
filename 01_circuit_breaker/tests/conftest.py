"""Shared pytest configuration for the circuit breaker dashboard tests.

Streamlit re-executes ``app.py`` top to bottom on every run, so importing the module must
not launch any Streamlit rendering or perform live AWS calls at import time. The module is
written so that ``import app`` only defines helpers/classes (the UI runs inside ``main()``),
which keeps the pure logic testable without a running Streamlit server or AWS credentials.

This file makes the sibling ``app.py`` importable as ``app`` from the test suite by putting
the package root (``01_circuit_breaker/``) on ``sys.path``.
"""

import os
import sys

import pytest

# Directory that contains app.py (the parent of this tests/ package).
_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)


@pytest.fixture
def app_module():
    """Import and return the ``app`` module without launching Streamlit."""
    import app

    return app
