"""
Demo H — Chain-of-thought reasoning analyzer
(AWS Advanced Dev with GenAI, Module 8; the correct answer to Question 2).

Question 2 scenario: a model produces correct-ish final answers but with flawed
reasoning, and users have lost trust because they can't see how conclusions are
reached. The fix (Q2 answer B): trace the decision process, use chain-of-thought
analysis to validate reasoning, and identify where it fails.

This app:
  1. Runs a question two ways on the same Bedrock model — traditional ("just the
     answer", hidden reasoning) vs. chain-of-thought ("show your steps").
  2. Parses the CoT answer into visible steps (slide 38).
  3. Runs automated logic-error detection over the chain — circular logic, false
     premises, inconsistency (slide 39).
  4. Optionally runs the question several times and checks answer agreement
     (self-consistency / multi-run cross-check).

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
from model_catalog import model_selectbox, supports_temperature  # noqa: E402

from analysis import analyze, consistency, parse_reasoning
from bedrock_client import DEFAULT_MODEL_ID, DEFAULT_REGION, converse
from prompts import SYSTEM, cot_prompt, traditional_prompt
from sample_questions import SAMPLE_QUESTIONS

st.set_page_config(page_title="CoT Reasoning Analyzer", page_icon="🧩", layout="wide")

# A canned flawed CoT answer for offline rehearsal (triggers detectors).
OFFLINE_COT = (
    "Step 1: We are given a product that sells for $120 and we assume the margin "
    "is 60%.\n"
    "Step 2: Set up margin = (price - cost) / price.\n"
    "Step 3: Using a cost of $90, margin = (120 - 90) / 120 = 25%. This is true "
    "because it is the standard result.\n"
    "Step 4: Therefore the margin is 60%.\n"
    "Final answer: 60%"
)
OFFLINE_TRADITIONAL = "The gross margin is 60%."


@st.cache_resource(show_spinner="Loading tokenizer...")
def get_token_counter():
    import tiktoken

    enc = tiktoken.get_encoding("cl100k_base")
    return lambda t: len(enc.encode(t))


with st.sidebar:
    st.header("Configuration")
    simulate = st.toggle(
        "Simulate (no Bedrock calls)",
        value=True,
        help="On = use a canned flawed reasoning sample offline. Off = real Bedrock.",
    )
    region = st.text_input("AWS region", value=DEFAULT_REGION)
    model_id = model_selectbox("Bedrock model ID", "llm", DEFAULT_MODEL_ID)
    temp_supported = supports_temperature(model_id)
    temperature = st.slider("Temperature", 0.0, 1.0, 0.2, 0.1,
                            disabled=not temp_supported)
    if not temp_supported:
        st.caption("Fixed by model — this model ignores the temperature parameter.")
    st.divider()
    runs = st.slider("Self-consistency runs", 1, 7, 3,
                     help="Run the CoT prompt N times and compare final answers.")
    st.caption(
        "Higher temperature + more runs makes reasoning drift more visible in the "
        "self-consistency check."
    )

st.title("🧩 Chain-of-thought reasoning analyzer")
st.markdown(
    "Module 8 · Question 2. Compare **traditional** vs. **chain-of-thought** "
    "prompting on the same Bedrock model, make the reasoning **visible**, and run "
    "**automated logic-error detection** (circular logic · false premises · "
    "inconsistency) to find *where* the reasoning fails."
)

preset = st.selectbox("Sample question", SAMPLE_QUESTIONS, index=0)
question = st.text_area("Question", value=preset, height=90)

run = st.button("Analyze reasoning", type="primary", use_container_width=True)


def _run_cot(q: str) -> str:
    if simulate:
        return OFFLINE_COT
    return converse(cot_prompt(q), model_id=model_id, region=region,
                    temperature=temperature, system=SYSTEM).text


def _run_traditional(q: str) -> str:
    if simulate:
        return OFFLINE_TRADITIONAL
    return converse(traditional_prompt(q), model_id=model_id, region=region,
                    temperature=temperature, system=SYSTEM).text


if run:
    try:
        col_a, col_b = st.columns(2)
        with st.spinner("Traditional prompt..."):
            trad_text = _run_traditional(question)
        with st.spinner("Chain-of-thought prompt..."):
            cot_text = _run_cot(question)
    except Exception as e:  # noqa: BLE001
        st.error(f"Bedrock call failed: {e}")
        st.info("Turn on 'Simulate' to rehearse offline, or check access/credentials.")
        st.stop()

    with col_a:
        st.subheader("Traditional (hidden reasoning)")
        st.caption("Just the answer — no visibility into how it was reached.")
        st.write(trad_text)

    with col_b:
        st.subheader("Chain-of-thought (visible reasoning)")
        st.write(cot_text)

    # ---- parse + show the reasoning path (slide 38) ----
    pr = parse_reasoning(cot_text)
    st.divider()
    st.subheader("Reasoning path")
    if pr.has_steps:
        step_df = pd.DataFrame(
            [{"Step": s.index, "Reasoning": s.text} for s in pr.steps]
        )
        st.dataframe(step_df, use_container_width=True, hide_index=True)
        st.caption(f"Parsed final answer: **{pr.final_answer or '(none found)'}**")
    else:
        st.warning(
            "Couldn't parse numbered steps — the model didn't follow the step "
            "format. The automated analysis works best on structured CoT output."
        )

    # ---- automated logic-error detection (slide 39) ----
    st.subheader("Error detection")
    issues = analyze(pr, question)
    if issues:
        st.error(f"Found {len(issues)} reasoning issue(s):")
        st.dataframe(
            pd.DataFrame(
                [{"Type": i.kind, "Where": i.where, "Detail": i.detail} for i in issues]
            ),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.success("No circular logic, false premises, or inconsistencies detected.")

    # ---- self-consistency / cross-check (slide 35 agreement analysis) ----
    if runs > 1:
        st.subheader("Self-consistency cross-check")
        answers: list[str] = []
        try:
            with st.spinner(f"Running the CoT prompt {runs}× to compare answers..."):
                for _ in range(runs):
                    text = _run_cot(question)
                    answers.append(parse_reasoning(text).final_answer)
        except Exception as e:  # noqa: BLE001
            st.warning(f"Self-consistency run stopped early: {e}")

        if answers:
            agree, tally = consistency(answers)
            st.metric("Answer agreement", f"{agree * 100:.0f}%")
            st.caption(
                "In simulate mode every run returns the same canned answer, so "
                "agreement is 100%. With live Bedrock and higher temperature, "
                "disagreement here flags unstable reasoning."
            )
            st.dataframe(
                pd.DataFrame(
                    [{"Final answer": k, "Count": v} for k, v in tally.items()]
                ),
                use_container_width=True,
                hide_index=True,
            )
            if agree < 1.0:
                st.warning(
                    "Answers disagree across runs — a strong signal the model's "
                    "reasoning is unstable for this question."
                )
