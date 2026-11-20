"""Streamlit helpers for the Amazon Comprehend demo pages.

The Comprehend calls themselves live in comprehend_core.py (no Streamlit in there,
so the AWS Lambda in aws/ can use the same code). They are re-exported here so the
pages import everything from one place. The pages show those functions to the
audience with `show_code()`, which prints their real source via `inspect.getsource`.
"""

from __future__ import annotations

import inspect
import os
from pathlib import Path

import streamlit as st

from comprehend_core import (  # noqa: F401  (re-exported for the pages)
    SENTIMENT_BATCH_SIZE,
    TOXICITY_BATCH_SIZE,
    detect_pii,
    detect_sentiments,
    detect_toxicity,
    get_comprehend_client,
    mask_text,
    net_sentiment,
)

SAMPLE_DIR = Path(__file__).resolve().parent / "sample_data"


def sidebar() -> tuple[str, str]:
    """Shared AWS settings sidebar. Returns (region, language)."""
    st.sidebar.header("AWS Settings")
    region = st.sidebar.text_input(
        "AWS Region", value=os.getenv("AWS_REGION", "us-east-1"), key="region"
    )
    language = st.sidebar.selectbox(
        "Language",
        options=["en"],
        index=0,
        key="language",
        help="This demo uses English (en).",
    )
    return region, language


def show_code(*funcs, title: str = "Show the code that calls Comprehend", expanded: bool = True):
    """Display the real source of the given functions in an expander."""
    with st.expander(title, expanded=expanded):
        for func in funcs:
            st.code(inspect.getsource(func), language="python")


def load_pii_samples() -> dict[str, str]:
    """Read sample_data/pii_mask_samples.txt: '###' title line, samples split by '---'."""
    raw = (SAMPLE_DIR / "pii_mask_samples.txt").read_text(encoding="utf-8")
    samples = {}
    for block in raw.split("\n---\n"):
        title, _, body = block.strip().partition("\n")
        samples[title.lstrip("# ").strip()] = body.strip()
    return samples
