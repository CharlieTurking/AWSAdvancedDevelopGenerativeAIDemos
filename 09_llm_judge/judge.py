"""
LLM-as-a-judge with bias controls (Module 9, slides 36, 37, 38).

Two modes:
  1. Rubric scoring (single answer): score 1-5 on the slide-36 dimensions
     (accuracy, relevance, completeness, clarity, faithfulness) with anchor
     examples (slide 38) and low temperature (slide 36).
  2. Pairwise comparison with position-bias control (slide 37): judge "A vs B",
     then judge again with the order swapped. If the winner flips, the judge has
     position bias and the result is unreliable (report a tie / flag it).
"""

from __future__ import annotations

import json
import re

DIMENSIONS = ["accuracy", "relevance", "completeness", "clarity", "faithfulness"]

JUDGE_SYSTEM = (
    "You are a meticulous evaluation judge. Apply the rubric exactly and return "
    "ONLY valid JSON. Do not add commentary outside the JSON."
)

# Slide 38: define criteria + anchor examples (reference points / quality levels).
RUBRIC_ANCHORS = (
    "Score each dimension 1-5 using these anchors:\n"
    "  5 = excellent (fully correct, directly on-topic, complete, clear, fully grounded)\n"
    "  3 = acceptable (mostly correct with minor gaps)\n"
    "  1 = poor (incorrect, off-topic, or unsupported)\n"
)

RUBRIC_TEMPLATE = """Evaluate the AI answer against the question{ref_hint}.

Question:
{question}

{reference_block}AI answer:
{answer}

{anchors}
Dimensions:
- accuracy: factually correct and precise
- relevance: directly addresses the question
- completeness: covers the important aspects
- clarity: well-organized and easy to understand
- faithfulness: grounded in the reference/context (no fabrication)

Return ONLY this JSON:
{{"accuracy": <1-5>, "relevance": <1-5>, "completeness": <1-5>, "clarity": <1-5>, "faithfulness": <1-5>, "rationale": "<one sentence>"}}
"""

PAIRWISE_TEMPLATE = """Compare two AI answers to the same question and pick the better one.

Question:
{question}

{reference_block}Answer {a_label}:
{a_text}

Answer {b_label}:
{b_text}

Judge on overall accuracy, relevance, completeness, clarity, and faithfulness.
Return ONLY this JSON:
{{"winner": "{a_label}" or "{b_label}" or "tie", "rationale": "<one sentence>"}}
"""


def build_rubric_prompt(question: str, answer: str, reference: str | None) -> str:
    ref = f"Reference answer (ground truth):\n{reference}\n\n" if reference else ""
    hint = " and reference" if reference else ""
    return RUBRIC_TEMPLATE.format(
        question=question, answer=answer, reference_block=ref,
        anchors=RUBRIC_ANCHORS, ref_hint=hint,
    )


def build_pairwise_prompt(question, a_label, a_text, b_label, b_text, reference):
    ref = f"Reference answer (ground truth):\n{reference}\n\n" if reference else ""
    return PAIRWISE_TEMPLATE.format(
        question=question, reference_block=ref,
        a_label=a_label, a_text=a_text, b_label=b_label, b_text=b_text,
    )


def _extract_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


def parse_rubric(text: str) -> dict:
    data = _extract_json(text)
    out = {}
    for d in DIMENSIONS:
        try:
            out[d] = max(1, min(5, int(round(float(data.get(d, 3))))))
        except (TypeError, ValueError):
            out[d] = 3
    out["rationale"] = str(data.get("rationale", ""))[:300]
    return out


def rubric_overall(scores: dict) -> float:
    vals = [scores[d] for d in DIMENSIONS]
    return sum(vals) / len(vals)


def parse_pairwise(text: str, a_label: str, b_label: str) -> str:
    data = _extract_json(text)
    w = str(data.get("winner", "tie")).strip()
    if w == a_label:
        return a_label
    if w == b_label:
        return b_label
    return "tie"


def position_bias_verdict(forward_winner: str, swapped_winner: str) -> dict:
    """Compare the two orderings. If the winner is consistent across the swap,
    there's no position bias. If it flips, the judge is order-biased."""
    if forward_winner == "tie" or swapped_winner == "tie":
        consistent = forward_winner == swapped_winner
    else:
        consistent = forward_winner == swapped_winner
    return {
        "forward_winner": forward_winner,
        "swapped_winner": swapped_winner,
        "position_bias_detected": not consistent,
        "reliable_winner": forward_winner if consistent else "tie (order-dependent)",
    }
