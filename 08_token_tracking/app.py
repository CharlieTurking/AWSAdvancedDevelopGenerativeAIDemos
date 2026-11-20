"""
Demo A — Real-time token tracking and alerting
(AWS Advanced Dev with GenAI, Module 8, slides 5 & 7).

A live dashboard that tracks token consumption from Amazon Bedrock calls and
drives the slide-7 traffic-light status system:

    🟢 Normal   0-80%  of quota
    🟡 Warning  80-95% of quota
    🔴 Critical >95%   of quota

It shows the real-time monitoring layer (token metrics, cost-trend projection,
alert status), granular breakdowns by App and User segment (slide 7 custom-metric
dimensions), and an intelligent alert engine whose recommended action is tuned by
business-hours context. Optionally publishes the same custom metrics to CloudWatch.

Run locally:
    pip install -r requirements.txt
    streamlit run app.py
"""

from __future__ import annotations

import os
import random
import sys
import time
from datetime import datetime

import pandas as pd
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
    converse,
)
from tracking import (
    USE_CASE_RATIOS,
    Record,
    Tracker,
    analyze_alert,
)

st.set_page_config(page_title="Token Tracking × Bedrock", page_icon="📊", layout="wide")

APPS = ["chatbot", "summarizer", "code-assist"]
SEGMENTS = ["free", "pro", "enterprise"]

# Prompts used by the live-load generator, grouped by use case (slide 5 ratios).
SAMPLE_PROMPTS = {
    "Q&A": [
        "What is Amazon Bedrock?",
        "How does an inference profile work?",
        "Explain token-based pricing in one sentence.",
    ],
    "Summarization": [
        "Summarize: " + ("Amazon Bedrock is a fully managed service that offers "
        "a choice of high-performing foundation models from leading AI companies "
        "through a single API, along with capabilities to build generative AI "
        "applications with security, privacy, and responsible AI. " * 4),
    ],
}


def init_state():
    if "tracker" not in st.session_state:
        st.session_state.tracker = Tracker()


init_state()


with st.sidebar:
    st.header("Configuration")
    simulate = st.toggle(
        "Simulate (no Bedrock calls)",
        value=True,
        help="On = generate synthetic token usage offline. Off = real Bedrock calls.",
    )
    region = st.text_input("AWS region", value=DEFAULT_REGION)
    model_id = model_selectbox("Bedrock model ID", "llm", DEFAULT_MODEL_ID)
    st.divider()
    quota = st.number_input(
        "Token quota (window)", min_value=1_000, value=100_000, step=1_000,
        help="The quota the traffic-light status is measured against.",
    )
    st.session_state.tracker.quota_tokens = int(quota)
    st.divider()
    st.subheader("CloudWatch (optional)")
    push_cw = st.toggle("Publish custom metrics to CloudWatch", value=False)
    cw_namespace = st.text_input("Namespace", value="AI/TokenTracking", disabled=not push_cw)
    st.divider()
    business_hours = st.checkbox(
        "Within business hours", value=True,
        help="Context the alert engine uses to tune the recommended action.",
    )
    if st.button("Reset tracker", use_container_width=True):
        st.session_state.pop("tracker", None)
        init_state()
        st.rerun()
    st.caption(
        f"Illustrative pricing: ${PRICE_PER_1K_INPUT}/1K in, "
        f"${PRICE_PER_1K_OUTPUT}/1K out."
    )

st.title("📊 Real-time token tracking and alerting")
st.markdown(
    "Module 8 · slides 5 & 7. Generate load, watch token consumption against a "
    "quota, and see the **traffic-light status** flip 🟢 → 🟡 → 🔴 with the "
    "intelligent alert engine's recommended action."
)


def _simulated_tokens(use_case: str) -> tuple[int, int]:
    """Synthetic input/output counts honoring the slide-5 ratios."""
    if use_case == "Summarization":
        inp = random.randint(800, 1500)
        out = int(inp / USE_CASE_RATIOS["Summarization"])  # ~10:1 input:output
    else:  # Q&A ~1:1
        inp = random.randint(20, 120)
        out = int(inp * random.uniform(0.8, 1.4))
    return inp, max(out, 1)


def generate_calls(n: int):
    """Add n records to the tracker (simulated or real Bedrock)."""
    tracker = st.session_state.tracker
    for _ in range(n):
        app = random.choice(APPS)
        segment = random.choices(SEGMENTS, weights=[5, 3, 2])[0]
        use_case = random.choice(list(SAMPLE_PROMPTS))

        if simulate:
            inp, out = _simulated_tokens(use_case)
            cost = inp / 1000 * PRICE_PER_1K_INPUT + out / 1000 * PRICE_PER_1K_OUTPUT
            latency = random.uniform(0.3, 1.5)
        else:
            prompt = random.choice(SAMPLE_PROMPTS[use_case])
            res = converse(prompt, model_id=model_id, region=region)
            inp, out, cost, latency = (
                res.input_tokens, res.output_tokens, res.cost_usd, res.latency_s
            )

        rec = Record(
            app=app,
            user_segment=segment,
            input_tokens=inp,
            output_tokens=out,
            latency_s=latency,
            cost_usd=cost,
            ts=time.time(),
        )
        tracker.add(rec)

        if push_cw:
            try:
                from cloudwatch import publish

                publish(
                    region=region, app=app, user_segment=segment,
                    input_tokens=inp, output_tokens=out, cost_usd=cost,
                    namespace=cw_namespace,
                )
            except Exception as e:  # noqa: BLE001
                st.warning(f"CloudWatch publish failed (continuing): {e}")


col_run1, col_run2 = st.columns(2)
with col_run1:
    batch = st.number_input("Calls per batch", 1, 100, 10)
with col_run2:
    st.write("")
    st.write("")
    go = st.button("Generate load", type="primary", use_container_width=True)

if go:
    try:
        with st.spinner(f"Generating {int(batch)} calls..."):
            generate_calls(int(batch))
    except Exception as e:  # noqa: BLE001
        st.error(f"Bedrock call failed: {e}")
        st.info("Turn on 'Simulate' to run offline, or check model access / credentials.")
        st.stop()

# ---------------------------------------------------------------------------
# Real-time monitoring layer
# ---------------------------------------------------------------------------
tracker = st.session_state.tracker

if tracker.request_count == 0:
    st.info("No usage yet. Click **Generate load** to start tracking.")
    st.stop()

level, emoji, frac = tracker.status()

st.subheader("Real-time monitoring layer")
m1, m2, m3, m4 = st.columns(4)
m1.metric("Total tokens", f"{tracker.total_tokens:,}")
m2.metric("Quota used", f"{frac * 100:.0f}%")
m3.metric("Est. cost", f"${tracker.total_cost:.4f}")
m4.metric("Tokens/min", f"{tracker.tokens_per_minute():,.0f}")

# Traffic-light banner.
st.progress(min(frac, 1.0))
if level == "Critical":
    st.error(f"{emoji} **{level}** — over 95% of quota ({frac * 100:.0f}%).")
elif level == "Warning":
    st.warning(f"{emoji} **{level}** — 80–95% of quota ({frac * 100:.0f}%).")
else:
    st.success(f"{emoji} **{level}** — under 80% of quota ({frac * 100:.0f}%).")

# Cost-trend projection.
eta = tracker.project_to_quota()
if eta is None:
    st.caption("Burn rate not yet established (need more calls over time).")
elif eta == 0.0:
    st.caption("Quota already reached or exceeded.")
else:
    st.caption(f"At the current burn rate, the quota is reached in ~{eta:.1f} min.")

# ---------------------------------------------------------------------------
# Intelligent alert engine
# ---------------------------------------------------------------------------
st.subheader("Intelligent alert engine")
alert = analyze_alert(level, business_hours)
a1, a2, a3 = st.columns(3)
a1.metric("Notify?", "Yes" if alert["notify"] else "No")
a2.metric("Channel", alert["channel"])
a3.metric("Status level", f"{emoji} {level}")
st.caption(f"Recommended action: {alert['action']}")

# ---------------------------------------------------------------------------
# Granular breakdowns (slide 7 custom-metric dimensions)
# ---------------------------------------------------------------------------
st.subheader("Granular visibility")
col_app, col_seg = st.columns(2)

with col_app:
    st.caption("Tokens by App")
    app_agg = tracker.by_dimension("app")
    df_app = pd.DataFrame(
        [{"App": k, "Tokens": v["tokens"]} for k, v in app_agg.items()]
    ).set_index("App")
    st.bar_chart(df_app)

with col_seg:
    st.caption("Tokens by User segment")
    seg_agg = tracker.by_dimension("user_segment")
    df_seg = pd.DataFrame(
        [{"Segment": k, "Tokens": v["tokens"]} for k, v in seg_agg.items()]
    ).set_index("Segment")
    st.bar_chart(df_seg)

# Input vs output split (slide 5 token economics).
st.caption("Input vs. output tokens (slide 5: Q&A ~1:1, Summarization ~10:1 input:output)")
io_df = pd.DataFrame(
    {"Kind": ["Input", "Output"], "Tokens": [tracker.total_input, tracker.total_output]}
).set_index("Kind")
st.bar_chart(io_df)

with st.expander("Recent calls"):
    rows = [
        {
            "time": datetime.fromtimestamp(r.ts).strftime("%H:%M:%S"),
            "app": r.app,
            "segment": r.user_segment,
            "in": r.input_tokens,
            "out": r.output_tokens,
            "latency_s": round(r.latency_s, 2),
            "cost_usd": round(r.cost_usd, 5),
        }
        for r in tracker.records[-25:][::-1]
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
