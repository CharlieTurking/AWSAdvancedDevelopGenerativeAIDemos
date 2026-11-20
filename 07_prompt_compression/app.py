"""
Demo 1 — Prompt compression without losing effectiveness
(AWS Advanced Dev with GenAI, Module 7, slide 12).

Reproduces the slide's "Before: 160 tokens -> After: 64 tokens, 60% reduction"
idea live against Amazon Bedrock:

  1. Compress a verbose prompt with a rule-based compressor.
  2. Count tokens before/after.
  3. Send BOTH prompts to the same Bedrock model.
  4. Show token savings, cost savings, latency, and both answers side by side
     so you can confirm quality is preserved.

Run locally:
    pip install -r requirements.txt
    streamlit run app.py
"""

from __future__ import annotations

import os
import sys

import streamlit as st

# Make the repo-root shared helpers importable when launched via
# `streamlit run app.py` from inside this demo folder.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from model_catalog import model_selectbox, supports_temperature  # noqa: E402

from bedrock_client import (
    DEFAULT_MODEL_ID,
    DEFAULT_REGION,
    PRICE_PER_1K_INPUT,
    PRICE_PER_1K_OUTPUT,
    LLMResult,
    converse,
)
from compression import compress

st.set_page_config(page_title="Prompt Compression × Bedrock", page_icon="🗜️", layout="wide")

# The exact example from slide 12.
SLIDE_EXAMPLE = (
    "Please analyze the following customer feedback and provide a detailed "
    "summary of the main themes, sentiment analysis, and actionable "
    "recommendations for improvement."
)

SAMPLE_FEEDBACK = (
    "\n\nFeedback:\n"
    "1. The checkout page crashed twice before my order went through.\n"
    "2. Support answered in under a minute, which was great.\n"
    "3. Shipping took 9 days even though 3-day was promised.\n"
    "4. The mobile app is beautiful but drains my battery fast.\n"
    "5. Loyalty points never showed up after my last two purchases."
)


@st.cache_resource(show_spinner="Loading tokenizer...")
def get_token_counter():
    import tiktoken

    enc = tiktoken.get_encoding("cl100k_base")
    return lambda text: len(enc.encode(text))


with st.sidebar:
    st.header("Configuration")
    region = st.text_input("AWS region", value=DEFAULT_REGION)
    model_id = model_selectbox(
        "Bedrock model ID",
        "llm",
        DEFAULT_MODEL_ID,
        help="Must be enabled in Bedrock → Model access for this region.",
    )
    max_tokens = st.slider("Max output tokens", 128, 2048, 512, 64)
    temp_supported = supports_temperature(model_id)
    temperature = st.slider("Temperature", 0.0, 1.0, 0.2, 0.1,
                            disabled=not temp_supported)
    if not temp_supported:
        st.caption("Fixed by model — this model ignores the temperature parameter.")
    st.divider()
    st.caption(
        f"Illustrative pricing: ${PRICE_PER_1K_INPUT}/1K input, "
        f"${PRICE_PER_1K_OUTPUT}/1K output. Override with env vars "
        "PRICE_PER_1K_INPUT / PRICE_PER_1K_OUTPUT."
    )
    st.caption(
        "AWS credentials come from the standard chain "
        "(env vars, ~/.aws/credentials, or an attached role)."
    )

st.title("🗜️ Prompt compression without losing effectiveness")
st.markdown(
    "Compress a verbose prompt, then ask **the same Bedrock "
    "model** both versions and compare tokens, cost, latency, and answer quality."
)

append_feedback = st.toggle(
    "Append sample feedback to the prompt (so there's real content to analyze)",
    value=True,
)

base_prompt = st.text_area(
    "Verbose prompt",
    value=SLIDE_EXAMPLE + (SAMPLE_FEEDBACK if append_feedback else ""),
    height=240,
)
prompt = base_prompt

count = get_token_counter()
compressed = compress(base_prompt)

raw_tokens = count(prompt)
comp_tokens = count(compressed)
reduction = (1 - comp_tokens / max(raw_tokens, 1)) * 100

c1, c2, c3 = st.columns(3)
c1.metric("Before (tokens)", f"{raw_tokens}")
c2.metric("After (tokens)", f"{comp_tokens}", f"-{raw_tokens - comp_tokens}")
c3.metric("Token reduction", f"{reduction:.0f}%")

with st.expander("See the compressed prompt", expanded=True):
    st.code(compressed, language="text")

run = st.button("Run both prompts on Bedrock", type="primary", use_container_width=True)


def _render(col, title: str, res: LLMResult):
    with col:
        st.subheader(title)
        st.caption(
            f"{res.latency_s:.2f}s · in {res.input_tokens} tok · "
            f"out {res.output_tokens} tok · ~${res.cost_usd:.5f}"
        )
        st.write(res.text)


if run:
    try:
        col_a, col_b = st.columns(2)
        with st.spinner("Calling Bedrock (verbose prompt)..."):
            baseline = converse(
                prompt,
                model_id=model_id,
                region=region,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        with st.spinner("Calling Bedrock (compressed prompt)..."):
            compact = converse(
                compressed,
                model_id=model_id,
                region=region,
                max_tokens=max_tokens,
                temperature=temperature,
            )
    except Exception as e:  # noqa: BLE001 - surface any AWS/credential error to the UI
        st.error(f"Bedrock call failed: {e}")
        st.info(
            "Check: model access enabled in this region, credentials present, "
            "and IAM allows bedrock:InvokeModel for the inference profile."
        )
        st.stop()

    _render(col_a, "Baseline (verbose)", baseline)
    _render(col_b, "Compressed", compact)

    # Compare using the authoritative input-token counts Bedrock billed.
    in_saved = baseline.input_tokens - compact.input_tokens
    in_reduction = (1 - compact.input_tokens / max(baseline.input_tokens, 1)) * 100
    cost_saved = baseline.cost_usd - compact.cost_usd

    st.divider()
    m1, m2, m3 = st.columns(3)
    m1.metric("Input tokens billed (baseline)", f"{baseline.input_tokens}")
    m2.metric(
        "Input tokens billed (compressed)",
        f"{compact.input_tokens}",
        f"-{in_saved}",
    )
    m3.metric("Per-call cost saved", f"${cost_saved:.5f}")

    st.success(
        f"Input-token savings on this call: **{in_reduction:.0f}%**. "
        "Scroll up to confirm both answers cover the same themes, sentiment, "
        "and recommendations."
    )
