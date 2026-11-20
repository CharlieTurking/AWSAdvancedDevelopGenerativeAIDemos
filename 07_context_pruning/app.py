"""
Demo 2 — Sliding-window context pruning for long conversations
(AWS Advanced Dev with GenAI, Module 7; the correct answer to Question 1).

Scenario (straight from Question 1): a customer-support chatbot on Claude Haiku
keeps the ENTIRE conversation history in the context window. Costs balloon past
~15 turns. The CFO wants a 40% cost cut without losing quality.

This app answers the SAME final query two ways against the same Bedrock model:
  A. Baseline  — full conversation history (today's behaviour).
  B. Pruned    — sliding window (last N turns) + system-detected "important" turns
                 + optional semantically-relevant older turns.

It charts tokens/cost per turn for both and checks whether we hit the 40% target
while the pruned answer still resolves the user's reference to an earlier issue.

Run locally:
    pip install -r requirements.txt
    streamlit run app.py
"""

from __future__ import annotations

import pandas as pd
import os
import sys

import streamlit as st

# Make the repo-root shared helpers importable when launched via
# `streamlit run app.py` from inside this demo folder.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from model_catalog import model_selectbox  # noqa: E402

from bedrock_client import (
    DEFAULT_MODEL_ID,
    DEFAULT_REGION,
    PRICE_PER_1K_INPUT,
    PRICE_PER_1K_OUTPUT,
    TurnResult,
    converse_messages,
)
from pruning import (
    build_full_messages,
    build_messages,
    select_turns,
)
from sample_conversation import CONVERSATION, FINAL_QUERY

st.set_page_config(page_title="Context Pruning × Bedrock", page_icon="✂️", layout="wide")

SYSTEM = (
    "You are a helpful customer-support assistant. Answer using the conversation "
    "so far. If you don't have a detail the user refers to, say so plainly."
)


@st.cache_resource(show_spinner="Loading tokenizer...")
def get_token_counter():
    import tiktoken

    enc = tiktoken.get_encoding("cl100k_base")
    return lambda text: len(enc.encode(text))


def messages_text(messages: list[dict]) -> str:
    parts = []
    for m in messages:
        parts.append(f"[{m['role']}] " + " ".join(c["text"] for c in m["content"]))
    return "\n".join(parts)


with st.sidebar:
    st.header("Configuration")
    region = st.text_input("AWS region", value=DEFAULT_REGION)
    model_id = model_selectbox("Bedrock model ID", "llm", DEFAULT_MODEL_ID)
    st.divider()
    st.subheader("Pruning strategy")
    window = st.slider("Sliding window (recent turns to keep)", 1, 12, 5)
    auto_importance = st.checkbox(
        "Auto-detect important older turns", value=True,
        help="The system scores each turn (IDs, money/dates, commitments, "
        "relevance) and keeps the high scorers — no user pinning.",
    )
    importance_threshold = st.slider(
        "Importance threshold", 0.0, 1.0, 0.5, 0.05,
        help="Minimum computed score for an older turn to be auto-kept.",
    )
    semantic_extra = st.slider("Extra relevant older turns (semantic)", 0, 5, 0)
    st.caption(
        "All scoring is offline (keyword overlap + heuristics). This variant: "
        "recent window + system-detected important turns + semantic recall."
    )
    st.divider()
    st.caption(
        f"Illustrative pricing: ${PRICE_PER_1K_INPUT}/1K in, "
        f"${PRICE_PER_1K_OUTPUT}/1K out."
    )

st.title("✂️ Sliding-window context pruning for long conversations")
st.markdown(
    "Let us see how we can change a 16-turn support chat where the user ends by "
    "referencing an issue from **turn 2**. Compare **full history** vs. a "
    "**pruned context** on the same Bedrock model — "
    "cost cut without breaking the answer."
)

# ---- Show the conversation + which turns the strategy keeps -------------------
count = get_token_counter()

result = select_turns(
    CONVERSATION,
    FINAL_QUERY,
    window=window,
    auto_importance=auto_importance,
    importance_threshold=importance_threshold,
    semantic_extra=semantic_extra,
)
kept = result.kept()

st.subheader("Conversation & pruning decision")
rows = []
for t in CONVERSATION:
    status = "✅ kept" if t.index in kept else "✂️ pruned"
    rows.append(
        {
            "Turn": t.index,
            "User said": (t.user[:60] + "…") if len(t.user) > 60 else t.user,
            "Importance": f"{result.importance.get(t.index, 0.0):.2f}",
            "Decision": status,
            "Why": result.reason.get(t.index, "—"),
        }
    )
st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

st.info(f"**Final user query:** {FINAL_QUERY}")

# ---- Token preview (local estimate, before any API call) ----------------------
full_msgs = build_full_messages(CONVERSATION, FINAL_QUERY)
pruned_msgs = build_messages(CONVERSATION, FINAL_QUERY, kept)

full_est = count(SYSTEM + messages_text(full_msgs))
pruned_est = count(SYSTEM + messages_text(pruned_msgs))
est_reduction = (1 - pruned_est / max(full_est, 1)) * 100

c1, c2, c3 = st.columns(3)
c1.metric("Full-history tokens (est.)", f"{full_est}")
c2.metric("Pruned tokens (est.)", f"{pruned_est}", f"-{full_est - pruned_est}")
c3.metric("Estimated reduction", f"{est_reduction:.0f}%",
          help="Local tiktoken estimate before calling Bedrock.")

run = st.button("Run both on Bedrock", type="primary", use_container_width=True)


def _render(col, title: str, res: TurnResult, context_msgs: list[dict]):
    with col:
        st.subheader(title)
        st.caption(
            f"{res.latency_s:.2f}s · in {res.input_tokens} tok · "
            f"out {res.output_tokens} tok · ~${res.cost_usd:.5f}"
        )
        st.write(res.text)
        with st.expander("Context sent to the model"):
            st.text(messages_text(context_msgs))


if run:
    try:
        col_a, col_b = st.columns(2)
        with st.spinner("Bedrock — full history..."):
            baseline = converse_messages(
                full_msgs, model_id=model_id, region=region, system=SYSTEM
            )
        with st.spinner("Bedrock — pruned context..."):
            pruned = converse_messages(
                pruned_msgs, model_id=model_id, region=region, system=SYSTEM
            )
    except Exception as e:  # noqa: BLE001
        st.error(f"Bedrock call failed: {e}")
        st.info(
            "Check model access in this region, credentials, and that IAM allows "
            "bedrock:InvokeModel for the inference profile."
        )
        st.stop()

    _render(col_a, "Baseline (full history)", baseline, full_msgs)
    _render(col_b, "Pruned (sliding window)", pruned, pruned_msgs)

    # Authoritative comparison from Bedrock-reported input tokens.
    in_saved = baseline.input_tokens - pruned.input_tokens
    in_reduction = (1 - pruned.input_tokens / max(baseline.input_tokens, 1)) * 100
    cost_saved = baseline.cost_usd - pruned.cost_usd

    st.divider()
    m1, m2, m3 = st.columns(3)
    m1.metric("Input tokens billed (full)", f"{baseline.input_tokens}")
    m2.metric("Input tokens billed (pruned)", f"{pruned.input_tokens}", f"-{in_saved}")
    m3.metric("Input-token reduction", f"{in_reduction:.0f}%")

    chart_df = pd.DataFrame(
        {
            "Strategy": ["Full history", "Pruned"],
            "Input tokens": [baseline.input_tokens, pruned.input_tokens],
        }
    ).set_index("Strategy")
    st.bar_chart(chart_df)

    if in_reduction >= 40:
        st.success(
            f"🎯 Hit the CFO target: **{in_reduction:.0f}%** input-token reduction "
            f"(saving ~${cost_saved:.5f} on this call). Verify the pruned answer "
            "still names order ORD-48213 and the refund-to-card detail."
        )
    else:
        st.warning(
            f"Only **{in_reduction:.0f}%** reduction — below the 40% target. "
            "Try a smaller sliding window or fewer semantic extras in the sidebar."
        )
