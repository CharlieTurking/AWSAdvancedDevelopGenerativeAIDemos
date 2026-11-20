"""
Demo 8 — Semantic caching for generative AI
(AWS Advanced Dev with GenAI, Module 7; slides 37-39, Question 2 option D).

Users ask the same thing with different wording ("How do I reset my password?"
vs. "What's the process for changing my login credentials?"). Traditional exact
-match caching misses the paraphrase and pays the foundation model again. A
semantic cache embeds the query (Amazon Titan Embeddings) and serves a cached
answer when the nearest stored query is within a cosine-similarity threshold.

Locally the vector store is in-memory. The AWS/production variant (Q2 answer D)
swaps it for Amazon ElastiCache (Redis) + RediSearch.

Run locally:
    pip install -r requirements.txt
    streamlit run app.py
"""

from __future__ import annotations

import os
import sys

import pandas as pd
import streamlit as st

# Make the repo-root shared helpers importable when launched via
# `streamlit run app.py` from inside this demo folder.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from model_catalog import model_selectbox  # noqa: E402

from bedrock_client import (
    DEFAULT_EMBED_MODEL_ID,
    DEFAULT_MODEL_ID,
    DEFAULT_REGION,
    PRICE_PER_1K_INPUT,
    PRICE_PER_1K_OUTPUT,
    answer as llm_answer,
    embed as bedrock_embed,
)
from cache import ExactCache, SemanticCache, offline_embed
from sample_queries import SAMPLE_QUERIES

st.set_page_config(page_title="Semantic Cache × Bedrock", page_icon="🧠", layout="wide")

SYSTEM = "You are a concise customer-support assistant. Answer in 2-3 sentences."

# A fixed, representative cost for one avoided foundation-model call, so savings
# can be shown even in offline mode (where no real tokens are billed).
ASSUMED_TOKENS_PER_MISS = 350  # input+output of a typical support answer


# Good default thresholds differ by embedding model: real Titan vectors score
# true matches higher than the crude offline fallback, so they want a stricter cut.
THRESHOLD_BEDROCK = 0.80
THRESHOLD_OFFLINE = 0.62


def init_state():
    if "exact" not in st.session_state:
        st.session_state.exact = ExactCache()
    if "semantic" not in st.session_state:
        st.session_state.semantic = SemanticCache()
    if "log" not in st.session_state:
        st.session_state.log = []  # per-query decisions for the table/chart


init_state()


with st.sidebar:
    st.header("Configuration")
    use_bedrock = st.toggle(
        "Use Bedrock (Titan embeddings + Claude)",
        value=True,
        help="Off = offline fallback embeddings, no AWS calls (for rehearsal).",
    )
    region = st.text_input("AWS region", value=DEFAULT_REGION)
    model_id = model_selectbox("Bedrock LLM model ID", "llm", DEFAULT_MODEL_ID)
    embed_model_id = model_selectbox("Titan embedding model ID", "embedding", DEFAULT_EMBED_MODEL_ID)
    st.divider()
    default_threshold = THRESHOLD_BEDROCK if use_bedrock else THRESHOLD_OFFLINE
    threshold = st.slider(
        "Semantic similarity threshold",
        0.50, 0.99, default_threshold, 0.01,
        # Key depends on the mode so switching Bedrock on/off resets the slider
        # to that mode's sensible default instead of keeping the old value.
        key=f"threshold_{'bedrock' if use_bedrock else 'offline'}",
        help=(
            "Higher = stricter matching (fewer hits, less risk of a wrong hit). "
            "Good values differ by embedding model — the default follows the "
            "selected mode (Bedrock vs. offline)."
        ),
    )
    st.session_state.semantic.threshold = threshold
    st.divider()
    if st.button("Reset caches", use_container_width=True):
        for k in ("exact", "semantic", "log"):
            st.session_state.pop(k, None)
        init_state()
        st.rerun()
    st.caption(
        f"Illustrative pricing: ${PRICE_PER_1K_INPUT}/1K in, "
        f"${PRICE_PER_1K_OUTPUT}/1K out."
    )


def embed_query(text: str) -> list[float]:
    if use_bedrock:
        return bedrock_embed(text, model_id=embed_model_id, region=region)
    return offline_embed(text)


def get_answer(query: str) -> tuple[str, int]:
    """Return (answer_text, tokens_billed). Offline mode returns a stub."""
    if use_bedrock:
        res = llm_answer(query, model_id=model_id, region=region, system=SYSTEM)
        return res.text, res.input_tokens + res.output_tokens
    return (f"[offline stub answer for: {query}]", ASSUMED_TOKENS_PER_MISS)


def process(query: str):
    """Run one query through BOTH caches, calling the model only on a semantic miss."""
    exact = st.session_state.exact
    semantic = st.session_state.semantic

    exact_hit = exact.lookup(query) is not None

    vector = embed_query(query)
    sem_answer, matched, score = semantic.lookup(query, vector)

    if sem_answer is None:
        # Semantic miss -> pay the foundation model, then populate both caches.
        text, tokens = get_answer(query)
        semantic.put(query, text, vector)
        exact.put(query, text)
        decision = "miss → model call"
        billed = tokens
    else:
        text = sem_answer
        decision = f"hit ← “{matched}” ({score:.2f})"
        billed = 0  # served from cache, no model tokens

    st.session_state.log.append(
        {
            "Query": query,
            "Exact cache": "hit" if exact_hit else "miss",
            "Semantic cache": decision,
            "Model tokens billed": billed,
            "Best score": round(score, 3),
        }
    )
    return text, decision, score


st.title("🧠 Semantic caching for generative AI")
st.markdown(
    "Module 7 · slides 38-39 · Question 2. Exact-match caching misses paraphrased "
    "questions; a **semantic cache** matches on meaning and serves the cached "
    "answer — cutting latency, tokens, and cost toward the slide's **60-80%** target."
)

tab_single, tab_stream = st.tabs(["Try one query", "Run the sample stream"])

with tab_single:
    st.caption(
        "Tip: ask a question, then ask it again in different words. Exact cache "
        "misses the reword; the semantic cache hits it."
    )
    q = st.text_input("Customer query", value="How do I reset my password?")
    if st.button("Look up", type="primary"):
        try:
            text, decision, score = process(q)
        except Exception as e:  # noqa: BLE001
            st.error(f"Bedrock call failed: {e}")
            st.info(
                "Turn off 'Use Bedrock' in the sidebar to rehearse offline, or "
                "check model access / credentials / IAM bedrock:InvokeModel."
            )
            st.stop()
        if decision.startswith("hit"):
            st.success(f"Semantic cache {decision}")
        else:
            st.warning("Semantic cache miss — called the foundation model and cached it.")
        st.write(text)

with tab_stream:
    st.caption(
        "Replays a stream of real-world-style queries where users phrase the same "
        "intent differently (password reset, order tracking, refunds)."
    )
    if st.button("Run sample stream", type="primary"):
        try:
            for query, _group in SAMPLE_QUERIES:
                process(query)
        except Exception as e:  # noqa: BLE001
            st.error(f"Bedrock call failed: {e}")
            st.info("Turn off 'Use Bedrock' to rehearse offline, or check access.")
            st.stop()

# ---- Metrics + log (shared by both tabs) -------------------------------------
exact = st.session_state.exact
semantic = st.session_state.semantic

if semantic.total:
    st.divider()
    st.subheader("Results")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Queries processed", f"{semantic.total}")
    c2.metric("Exact-match hit rate", f"{exact.hit_rate * 100:.0f}%")
    c3.metric("Semantic hit rate", f"{semantic.hit_rate * 100:.0f}%")
    saved_calls = semantic.hits
    c4.metric("Model calls avoided", f"{saved_calls}")

    total_billed = sum(r["Model tokens billed"] for r in st.session_state.log)
    # What exact-match caching would have billed: a call for every semantic hit too.
    avg_per_miss = (
        total_billed / semantic.misses if semantic.misses else ASSUMED_TOKENS_PER_MISS
    )
    would_have_billed = total_billed + saved_calls * avg_per_miss
    token_savings = (
        (1 - total_billed / would_have_billed) * 100 if would_have_billed else 0.0
    )

    chart_df = pd.DataFrame(
        {
            "Cache": ["Exact match", "Semantic"],
            "Hit rate %": [exact.hit_rate * 100, semantic.hit_rate * 100],
        }
    ).set_index("Cache")
    st.bar_chart(chart_df)

    if semantic.hit_rate >= 0.6:
        st.success(
            f"🎯 Semantic hit rate **{semantic.hit_rate * 100:.0f}%** is in the "
            f"slide's 60-80% range, avoiding ~{token_savings:.0f}% of model tokens "
            f"vs. exact-match caching."
        )
    else:
        st.info(
            f"Semantic hit rate **{semantic.hit_rate * 100:.0f}%**. Lower the "
            "similarity threshold in the sidebar to catch more paraphrases "
            "(watch for false hits across different intents)."
        )

    with st.expander("Per-query decisions", expanded=True):
        st.dataframe(
            pd.DataFrame(st.session_state.log),
            use_container_width=True,
            hide_index=True,
        )
