"""
Demo B — Async queue + resilience patterns
(AWS Advanced Dev with GenAI, Module 10, slides 11 & 13; answer to Question 1).

The other half of Question 1: absorb peak load with an SQS-style queue and apply
the slide-13 resilience patterns. Clients get an immediate job ID; jobs land in a
queue (load leveling); a worker drains them, retrying failures with exponential
backoff + jitter, and a circuit breaker fast-fails when the dependency is
unhealthy.

Run locally:
    pip install -r requirements.txt
    streamlit run app.py
"""

from __future__ import annotations

import os
import random
import sys

import pandas as pd
import streamlit as st

# Make the repo-root shared helpers importable when launched via
# `streamlit run app.py` from inside this demo folder.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from model_catalog import model_selectbox  # noqa: E402

from bedrock_client import DEFAULT_MODEL_ID, DEFAULT_REGION, converse
from resilience import (
    CircuitBreaker,
    JobState,
    Stats,
    new_job,
    process_job,
)

st.set_page_config(page_title="Async Queue × Bedrock", page_icon="📬", layout="wide")

with st.sidebar:
    st.header("Configuration")
    simulate = st.toggle("Simulate (no Bedrock calls)", value=True,
                         help="On = fake worker with injectable failures. Off = real Bedrock.")
    region = st.text_input("AWS region", value=DEFAULT_REGION)
    model_id = model_selectbox("Bedrock model ID", "llm", DEFAULT_MODEL_ID)
    st.divider()
    st.subheader("Load & resilience")
    n_jobs = st.slider("Jobs to submit (peak burst)", 1, 50, 20)
    fail_rate = st.slider("Simulated failure rate", 0.0, 1.0, 0.3, 0.05,
                          help="Chance each simulated call fails (drives retries/breaker).")
    max_attempts = st.slider("Max attempts per job", 1, 6, 4)
    fail_threshold = st.slider("Circuit breaker trip threshold", 2, 10, 5,
                               help="Consecutive failures before the circuit opens.")

st.title("📬 Async queue + resilience patterns")
st.markdown(
    "Module 10 · slides 11 & 13 · Question 1. Submit a burst of jobs, get "
    "**immediate job IDs**, and watch the worker drain the queue with "
    "**exponential backoff + jitter** and a **circuit breaker**."
)

prompts = [
    "Summarize today's account activity in one sentence.",
    "Draft a friendly payment reminder.",
    "Explain overdraft protection briefly.",
    "Suggest a savings tip.",
]


def make_call():
    """Return a call(prompt)->str that either hits Bedrock or simulates failures."""
    if simulate:
        def call(prompt: str) -> str:
            if random.random() < fail_rate:
                raise RuntimeError("simulated dependency error (throttled/5xx)")
            return f"[ok] {prompt[:40]}"
        return call

    def call(prompt: str) -> str:
        return converse(prompt, model_id=model_id, region=region).text
    return call


go = st.button("Submit burst → drain queue", type="primary", use_container_width=True)

if go:
    # Client layer: immediate job IDs (slide 11).
    jobs = [new_job(random.choice(prompts)) for _ in range(n_jobs)]
    st.subheader("1. Queued (immediate job IDs returned)")
    st.caption(f"{len(jobs)} jobs accepted and queued for async processing.")

    breaker = CircuitBreaker(fail_threshold=fail_threshold, cooldown_s=1.0)
    stats = Stats()

    call = make_call()
    # Fast sleep so the demo doesn't actually block on backoff in the UI.
    fast_sleep = (lambda s: None) if simulate else __import__("time").sleep

    progress = st.progress(0.0)
    rows = []
    breaker_trace = []
    for i, job in enumerate(jobs, 1):
        try:
            process_job(job, call, breaker, stats,
                        max_attempts=max_attempts, sleep=fast_sleep)
        except Exception as e:  # noqa: BLE001
            st.error(f"Bedrock call failed hard: {e}")
            st.info("Turn on 'Simulate' to run offline, or check access/credentials.")
            st.stop()
        rows.append({
            "job_id": job.id,
            "state": job.state.value,
            "attempts": job.attempts,
            "retry_delays_s": ", ".join(str(d) for d in job.delays) or "-",
            "error": job.error or "-",
        })
        breaker_trace.append(breaker.state.value)
        progress.progress(i / len(jobs))

    # Processing results.
    st.subheader("2. Processing results")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Succeeded", stats.succeeded)
    m2.metric("Failed", stats.failed)
    m3.metric("Rejected (circuit open)", stats.rejected)
    m4.metric("Total attempts", stats.total_attempts)
    st.caption(
        f"Total retry backoff time: {stats.total_retry_delay:.2f}s "
        f"(applied as delays; fast-forwarded in simulate mode). "
        f"Final circuit state: {breaker.state.value}."
    )

    # Outcome distribution.
    dist = pd.DataFrame(
        {"Outcome": ["succeeded", "failed", "rejected"],
         "Count": [stats.succeeded, stats.failed, stats.rejected]}
    ).set_index("Outcome")
    st.bar_chart(dist)

    st.subheader("3. Per-job detail")
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    if stats.rejected:
        st.warning(
            f"🔌 The circuit breaker opened and fast-failed {stats.rejected} job(s) "
            "instead of hammering an unhealthy dependency — exactly the slide-13 "
            "resilience behavior. Lower the failure rate to keep it closed."
        )
    else:
        st.success(
            "All jobs drained without tripping the breaker. Raise the failure rate "
            "to see backoff + the circuit breaker kick in."
        )
