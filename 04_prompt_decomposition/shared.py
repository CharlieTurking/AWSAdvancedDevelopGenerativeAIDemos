"""Shared session defaults and sidebar, with no page-rendering side effects.

Pages import `shared_sidebar` from here instead of from `app.py`, so importing
it does not also render the home page content.
"""

from __future__ import annotations

import os
import sys

import streamlit as st

# Make the repo-root shared helpers importable when launched via
# `streamlit run app.py` from inside this demo folder.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from model_catalog import model_selectbox, supports_temperature  # noqa: E402

import scenario

DEFAULTS = {
    "region": "us-east-1",
    "model_id":"global.anthropic.claude-haiku-4-5-20251001-v1:0",
    "temperature": 0.3,
    "max_tokens": 1500,
    "stream": True,
    "question": scenario.DEFAULT_QUESTION,
    "context": scenario.DEFAULT_CONTEXT,
}


def init_state() -> None:
    for key, value in DEFAULTS.items():
        st.session_state.setdefault(key, value)


def shared_sidebar() -> None:
    """Render the shared Bedrock config sidebar. Safe to call from any page."""
    init_state()
    with st.sidebar:
        st.header("Bedrock settings")
        st.session_state.region = st.text_input(
            "AWS region", value=st.session_state.region
        )
        st.session_state.model_id = model_selectbox(
            "Model ID", "llm", st.session_state.model_id,
            help="Any Bedrock model you have access to that supports Converse.",
        )
        temp_supported = supports_temperature(st.session_state.model_id)
        st.session_state.temperature = st.slider(
            "Temperature", 0.0, 1.0, value=float(st.session_state.temperature), step=0.1,
            disabled=not temp_supported,
        )
        if not temp_supported:
            st.caption("Fixed by model — this model ignores the temperature parameter.")
        st.session_state.max_tokens = st.slider(
            "Max tokens", 256, 4096, value=int(st.session_state.max_tokens), step=128
        )
        st.session_state.stream = st.toggle(
            "Stream responses", value=bool(st.session_state.stream)
        )
        st.divider()
        st.caption(
            "Credentials come from your environment (AWS CLI profile, env vars, "
            "or an IAM role). This app sends no secrets anywhere else."
        )
