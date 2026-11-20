"""
Demo H — LLM-as-a-judge rubric scorer with bias controls
(AWS Advanced Dev with GenAI, Module 9, slides 36, 37, 38).

Two capabilities:
  1. Rubric scoring (slides 36, 38): score an answer 1-5 on accuracy, relevance,
     completeness, clarity, faithfulness, using anchor examples and low temperature.
  2. Position-bias control (slide 37): for a pairwise "A vs B" judgment, run the
     judge both ways (A-first and B-first). If the winner flips when the order is
     swapped, the judge has position bias and the result is unreliable.

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

from bedrock_client import DEFAULT_MODEL_ID, DEFAULT_REGION, converse
from judge import (
    DIMENSIONS,
    JUDGE_SYSTEM,
    build_pairwise_prompt,
    build_rubric_prompt,
    parse_pairwise,
    parse_rubric,
    position_bias_verdict,
    rubric_overall,
)
from sample_data import SAMPLES

st.set_page_config(page_title="LLM-as-a-Judge", page_icon="⚖️", layout="wide")


def _offline_rubric(answer: str, reference: str) -> dict:
    """Offline judge: word overlap with reference -> 1-5 across dimensions."""
    aw = {w for w in answer.lower().split() if len(w) > 3}
    rw = {w for w in reference.lower().split() if len(w) > 3}
    overlap = len(aw & rw) / len(rw) if rw else 0.0
    base = 1 + round(overlap * 4)
    scores = {d: max(1, min(5, base)) for d in DIMENSIONS}
    scores["rationale"] = f"offline: {overlap*100:.0f}% reference-term overlap"
    return scores


def _offline_pairwise(a_text: str, b_text: str, reference: str) -> str:
    """Offline: whichever answer overlaps the reference more wins. Order-independent
    (so the demo shows NO position bias offline)."""
    rw = {w for w in reference.lower().split() if len(w) > 3}
    def ov(t):
        tw = {w for w in t.lower().split() if len(w) > 3}
        return len(tw & rw) / len(rw) if rw else 0.0
    sa, sb = ov(a_text), ov(b_text)
    if abs(sa - sb) < 0.05:
        return "tie"
    return "A" if sa > sb else "B"


with st.sidebar:
    st.header("Configuration")
    simulate = st.toggle("Simulate (no Bedrock calls)", value=True,
                         help="On = offline overlap-based judge. Off = live Bedrock judge.")
    region = st.text_input("AWS region", value=DEFAULT_REGION)
    model_id = model_selectbox("Judge model ID", "llm", DEFAULT_MODEL_ID)
    st.caption("The judge runs at temperature 0 for stable scoring (slide 36).")

st.title("⚖️ LLM-as-a-judge with bias controls")
st.markdown(
    "Module 9 · slides 36–38. Score answers against a rubric with anchor examples, "
    "and guard against **position bias** by judging pairwise comparisons in both "
    "orderings — if the winner flips, the verdict is order-dependent and unreliable."
)

q = st.selectbox("Question", list(SAMPLES))
sample = SAMPLES[q]
reference = st.text_area("Reference answer (ground truth)", value=sample["reference"], height=70)

tab_rubric, tab_pairwise = st.tabs(["Rubric scoring", "Pairwise + position-bias check"])


def run_rubric(answer: str) -> dict:
    if simulate:
        return _offline_rubric(answer, reference)
    out = converse(build_rubric_prompt(q, answer, reference), model_id=model_id,
                   region=region, temperature=0.0, system=JUDGE_SYSTEM)
    return parse_rubric(out.text)


with tab_rubric:
    answer = st.text_area("Answer to score", value=sample["answer_a"], height=100)
    if st.button("Score answer", type="primary"):
        try:
            scores = run_rubric(answer)
        except Exception as e:  # noqa: BLE001
            st.error(f"Bedrock call failed: {e}")
            st.info("Turn on 'Simulate' to run offline, or check access/credentials.")
            st.stop()
        cols = st.columns(len(DIMENSIONS))
        for c, d in zip(cols, DIMENSIONS):
            c.metric(d.capitalize(), f"{scores[d]}/5")
        st.metric("Overall", f"{rubric_overall(scores):.1f}/5")
        st.caption(f"Rationale: {scores.get('rationale', '')}")


def run_pairwise(a_label, a_text, b_label, b_text) -> str:
    if simulate:
        # Offline comparator is order-independent; map to the labels given.
        winner = _offline_pairwise(
            a_text if a_label == "A" else b_text,
            b_text if a_label == "A" else a_text,
            reference,
        )
        # Normalize: offline returns 'A'/'B'/'tie' in A=first-arg terms.
        if winner == "tie":
            return "tie"
        first_is_a = a_label == "A"
        return a_label if (winner == "A") == first_is_a else b_label
    out = converse(
        build_pairwise_prompt(q, a_label, a_text, b_label, b_text, reference),
        model_id=model_id, region=region, temperature=0.0, system=JUDGE_SYSTEM,
    )
    return parse_pairwise(out.text, a_label, b_label)


with tab_pairwise:
    c1, c2 = st.columns(2)
    with c1:
        ans_a = st.text_area("Answer A", value=sample["answer_a"], height=120)
    with c2:
        ans_b = st.text_area("Answer B", value=sample["answer_b"], height=120)

    if st.button("Compare (both orderings)", type="primary"):
        try:
            # Forward: A presented first, B second.
            forward = run_pairwise("A", ans_a, "B", ans_b)
            # Swapped: present B first, A second, but keep A/B identity in labels.
            swapped = run_pairwise("B", ans_b, "A", ans_a)
        except Exception as e:  # noqa: BLE001
            st.error(f"Bedrock call failed: {e}")
            st.info("Turn on 'Simulate' to run offline, or check access/credentials.")
            st.stop()

        verdict = position_bias_verdict(forward, swapped)
        st.dataframe(
            pd.DataFrame([
                {"Ordering": "A first, B second", "Winner": verdict["forward_winner"]},
                {"Ordering": "B first, A second", "Winner": verdict["swapped_winner"]},
            ]),
            use_container_width=True, hide_index=True,
        )
        if verdict["position_bias_detected"]:
            st.error(
                "🚩 **Position bias detected** — the winner changed when the answer "
                "order was swapped. This verdict is order-dependent and unreliable. "
                "Mitigate with randomization / ensemble judging (slide 37)."
            )
        else:
            st.success(
                f"✅ No position bias — consistent winner: **{verdict['reliable_winner']}**."
            )
