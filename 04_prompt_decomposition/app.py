"""Prompt Decomposition Demo — Module 4 (Prompt Engineering and Governance).

A three-act Streamlit demo built on the Module 4 deck:
  Act 1 (page 1): a naive single prompt gives a shallow answer.
  Act 2 (page 2): decompose the question across Technical / Business / Risk
                  dimensions (slide 19).
  Act 3 (page 3): run each dimension through the 6-step chain-of-thought
                  reasoning structure (slide 18), then synthesize.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import streamlit as st

import scenario
from shared import init_state, shared_sidebar

st.set_page_config(
    page_title="Prompt Decomposition Demo",
    page_icon="🧩",
    layout="wide",
)

init_state()
shared_sidebar()

# --- Home content -----------------------------------------------------------
st.title("🧩 Prompt Decomposition Demo")
st.subheader("Module 4 · Prompt Engineering and Governance")

st.markdown(
    """
Take **one messy, open-ended business question** and watch structure turn it
into something actionable. The demo runs in three acts, one per page in the
sidebar:

| Page | Act | What it shows | Deck slide |
|------|-----|---------------|------------|
| **1 · Naive Baseline** | Act 1 | A single raw prompt → a generic, unstructured answer | Slide 18 "Before" |
| **2 · Dimensional Decomposition** | Act 2 | Split the question into Technical / Business / Risk | Slide 19 |
| **3 · Step-by-Step Reasoning** | Act 3 | Run each dimension through a 6-step reasoning chain, then synthesize | Slide 18 "After" |

Work through the pages in order for the full narrative, or jump straight to
any act.
"""
)

st.divider()

col1, col2 = st.columns(2)
with col1:
    st.markdown("### The business question")
    st.session_state.question = st.text_area(
        "Edit the scenario once here — all three pages use it.",
        value=st.session_state.question,
        height=140,
    )
with col2:
    st.markdown("### Business context")
    st.caption("Facts fed into the reasoning chain on Act 3.")
    st.session_state.context = st.text_area(
        "Context facts",
        value=st.session_state.context,
        height=140,
        label_visibility="collapsed",
    )

st.info(
    "Set your AWS region and model in the sidebar, then open **Page 1** to start.",
    icon="👈",
)
