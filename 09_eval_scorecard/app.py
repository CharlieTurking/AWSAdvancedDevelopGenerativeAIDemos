"""
Demo A+B — Multi-dimensional evaluation scorecard with consistency testing
(AWS Advanced Dev with GenAI, Module 9, slides 6, 7, 9).

Scores model responses across the slide-6 evaluation pyramid using the slide-7
techniques, and compares models on a slide-9 radar chart:

  - Functional correctness + accuracy  -> LLM-as-a-judge rubric (fact verification)
  - Relevance/accuracy                 -> semantic similarity (Titan embeddings)
  - Consistency/reliability            -> multi-query variance testing   (Demo B)

Run locally:
    pip install -r requirements.txt
    streamlit run app.py
"""

from __future__ import annotations

import math
import os
import sys

import pandas as pd
import streamlit as st

# Make the repo-root shared helpers importable when launched via
# `streamlit run app.py` from inside this demo folder.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from model_catalog import model_selectbox, supports_temperature  # noqa: E402

from bedrock_client import (
    DEFAULT_EMBED_MODEL_ID,
    DEFAULT_MODEL_ID,
    DEFAULT_REGION,
    converse,
    embed,
)
from evaluation import (
    DimensionScores,
    build_judge_prompt,
    consistency_from_embeddings,
    consistency_from_text,
    cosine,
    parse_judge,
    relevance_from_similarity,
    score_to_100,
    JUDGE_SYSTEM,
)
from sample_data import DEFAULT_MODELS, SAMPLES

st.set_page_config(page_title="AI Evaluation Scorecard", page_icon="📐", layout="wide")


def _offline_embed(text: str) -> list[float]:
    """Deterministic hashed bag-of-words vector for offline mode."""
    dim = 128
    vec = [0.0] * dim
    for w in text.lower().split():
        vec[hash(w) % dim] += 1.0
    return vec


def _offline_judge(answer: str, reference: str) -> dict:
    """Crude offline judge: word overlap with the reference -> 1-5 scores."""
    aw = {w for w in answer.lower().split() if len(w) > 3}
    rw = {w for w in reference.lower().split() if len(w) > 3}
    overlap = len(aw & rw) / len(rw) if rw else 0.0
    score = 1 + round(overlap * 4)
    return {"functional_correctness": score, "accuracy": score,
            "rationale": f"offline: {overlap*100:.0f}% reference-term overlap"}


with st.sidebar:
    st.header("Configuration")
    simulate = st.toggle("Simulate (no Bedrock calls)", value=True,
                         help="On = canned responses + offline scoring. Off = live Bedrock.")
    region = st.text_input("AWS region", value=DEFAULT_REGION)
    model_id = model_selectbox("Generation/judge model ID", "llm", DEFAULT_MODEL_ID)
    embed_model_id = model_selectbox("Embedding model ID", "embedding", DEFAULT_EMBED_MODEL_ID)
    st.divider()
    consistency_runs = st.slider("Consistency runs (multi-query test)", 2, 7, 3,
                                 help="Demo B: run each model N times, measure answer variance.")
    gen_temp_supported = supports_temperature(model_id)
    gen_temp = st.slider("Generation temperature", 0.0, 1.0, 0.7, 0.1,
                         help="Higher temp surfaces more variance in the consistency test.",
                         disabled=not gen_temp_supported)
    if not gen_temp_supported:
        st.caption("Fixed by model — this model ignores the temperature parameter, "
                   "so generation and judge calls use its default sampling.")
    else:
        st.caption("The LLM judge always runs at low temperature for stable scoring.")

st.title("📐 Multi-dimensional AI evaluation scorecard")
st.markdown(
    "Module 9 · slides 6, 7, 9. Score answers across **functional correctness**, "
    "**relevance/accuracy**, and **consistency/reliability**, then compare models "
    "on a radar chart. Consistency uses **multi-query variance testing**."
)

question = st.selectbox("Question", list(SAMPLES))
sample = SAMPLES[question]
reference = st.text_area("Reference answer (ground truth)", value=sample["reference"], height=80)

run = st.button("Evaluate models", type="primary", use_container_width=True)


def embed_fn(text: str) -> list[float]:
    return _offline_embed(text) if simulate else embed(text, model_id=embed_model_id, region=region)


def generate(model_label: str) -> str:
    if simulate:
        return sample["offline"][model_label]
    return converse(question, model_id=model_id, region=region, temperature=gen_temp).text


def judge(answer: str) -> dict:
    if simulate:
        return _offline_judge(answer, reference)
    prompt = build_judge_prompt(question, answer, reference)
    out = converse(prompt, model_id=model_id, region=region, temperature=0.0, system=JUDGE_SYSTEM)
    return parse_judge(out.text)


def evaluate_model(label: str) -> tuple[DimensionScores, str, list[str]]:
    # Primary answer (used for correctness + relevance scoring).
    primary = generate(label)

    # Functional correctness + accuracy via LLM judge.
    verdict = judge(primary)
    functional = score_to_100(verdict.get("functional_correctness", 3))
    accuracy = score_to_100(verdict.get("accuracy", 3))

    # Relevance via semantic similarity to the reference.
    sim = cosine(embed_fn(primary), embed_fn(reference))
    relevance = relevance_from_similarity(sim)
    # Blend accuracy into the relevance/accuracy dimension (slide 6 groups them).
    relevance_accuracy = (relevance + accuracy) / 2

    # Consistency via multi-query variance (Demo B).
    answers = [primary]
    for _ in range(consistency_runs - 1):
        answers.append(generate(label))
    if simulate:
        consistency, mean_sim = consistency_from_text(answers)
    else:
        consistency, mean_sim = consistency_from_embeddings([embed_fn(a) for a in answers])

    ds = DimensionScores(
        functional=functional,
        relevance=relevance_accuracy,
        consistency=consistency,
        detail={
            "rationale": verdict.get("rationale", ""),
            "similarity_to_reference": round(sim, 3),
            "consistency_mean_sim": round(mean_sim, 3),
            "runs": len(answers),
        },
    )
    return ds, primary, answers


def gauge_cols(ds: DimensionScores):
    g1, g2, g3 = st.columns(3)
    g1.metric("Relevance/accuracy", f"{ds.relevance:.0f}%")
    g2.metric("Functional correctness", f"{ds.functional:.0f}%")
    g3.metric("Consistency", f"{ds.consistency:.0f}%")
    for g, val in ((g1, ds.relevance), (g2, ds.functional), (g3, ds.consistency)):
        g.progress(min(val / 100, 1.0))


if run:
    try:
        results: dict[str, DimensionScores] = {}
        answers_by_model: dict[str, list[str]] = {}
        for label in DEFAULT_MODELS:
            with st.spinner(f"Evaluating {label}..."):
                ds, primary, answers = evaluate_model(label)
            results[label] = ds
            answers_by_model[label] = answers

            st.subheader(label)
            st.caption(primary)
            gauge_cols(ds)
            with st.expander(f"{label} — scoring detail"):
                st.json(ds.detail)
                st.write("Consistency-test answers:")
                for i, a in enumerate(answers, 1):
                    st.text(f"run {i}: {a}")
            st.divider()
    except Exception as e:  # noqa: BLE001
        st.error(f"Bedrock call failed: {e}")
        st.info("Turn on 'Simulate' to run offline, or check model access/credentials.")
        st.stop()

    # ---- scorecard table ----
    st.subheader("Scorecard")
    table = pd.DataFrame([ds.as_row(label) for label, ds in results.items()])
    st.dataframe(table, use_container_width=True, hide_index=True)

    # ---- slide-9 radar chart ----
    st.subheader("Model comparison (radar)")
    try:
        import plotly.graph_objects as go

        axes = ["Functional correctness", "Relevance/accuracy", "Consistency/reliability"]
        fig = go.Figure()
        for label, ds in results.items():
            vals = [ds.functional, ds.relevance, ds.consistency]
            fig.add_trace(go.Scatterpolar(
                r=vals + [vals[0]], theta=axes + [axes[0]], fill="toself", name=label
            ))
        fig.update_layout(
            polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
            showlegend=True, height=450,
        )
        st.plotly_chart(fig, use_container_width=True)
    except Exception:  # noqa: BLE001 - plotly optional; fall back to a bar chart
        chart_df = table.set_index("Model")[
            ["Functional correctness", "Relevance/accuracy", "Consistency/reliability"]
        ]
        st.bar_chart(chart_df)

    best = max(results.items(), key=lambda kv: kv[1].overall)
    st.success(f"Highest overall score: **{best[0]}** ({best[1].overall:.0f}%).")
