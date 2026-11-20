"""
Multi-dimensional evaluation engine (Module 9, slides 6, 7, 9).

Scores a model response across the slide-6 pyramid dimensions:
    - Functional correctness
    - Relevance / accuracy
    - Consistency / reliability

using the slide-7 techniques:
    - Semantic similarity  -> vector embeddings  (relevance)
    - Fact verification     -> LLM-as-judge rubric (accuracy / correctness)
    - Response variance     -> multi-query testing (consistency)  <-- Demo B

All scores are normalized to 0-100 so they can feed the slide-7 gauges and the
slide-9 radar chart.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field

DIMENSIONS = ["Functional correctness", "Relevance/accuracy", "Consistency/reliability"]


@dataclass
class DimensionScores:
    functional: float = 0.0      # 0-100
    relevance: float = 0.0       # 0-100
    consistency: float = 0.0     # 0-100
    detail: dict = field(default_factory=dict)

    def as_row(self, label: str) -> dict:
        return {
            "Model": label,
            "Functional correctness": round(self.functional, 1),
            "Relevance/accuracy": round(self.relevance, 1),
            "Consistency/reliability": round(self.consistency, 1),
            "Overall": round(self.overall, 1),
        }

    @property
    def overall(self) -> float:
        return (self.functional + self.relevance + self.consistency) / 3


# --- semantic similarity (relevance) -----------------------------------------
def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def relevance_from_similarity(sim: float) -> float:
    """Map cosine similarity (~0.3-0.95 typical) to a 0-100 relevance score."""
    return max(0.0, min(1.0, (sim - 0.3) / (0.95 - 0.3))) * 100


# --- consistency / variance (Demo B: multi-query testing) --------------------
def consistency_from_embeddings(vectors: list[list[float]]) -> tuple[float, float]:
    """Return (consistency_score_0_100, mean_pairwise_similarity).

    Runs the same query multiple times, embeds each answer, and measures how
    similar the answers are to each other. High similarity -> high consistency.
    """
    n = len(vectors)
    if n < 2:
        return 100.0, 1.0
    sims = []
    for i in range(n):
        for j in range(i + 1, n):
            sims.append(cosine(vectors[i], vectors[j]))
    mean_sim = sum(sims) / len(sims)
    # Map mean pairwise similarity (~0.5-1.0 typical) to 0-100.
    score = max(0.0, min(1.0, (mean_sim - 0.5) / 0.5)) * 100
    return score, mean_sim


def consistency_from_text(answers: list[str]) -> tuple[float, float]:
    """Offline fallback: Jaccard-based agreement over word sets."""
    n = len(answers)
    if n < 2:
        return 100.0, 1.0
    def wset(s: str) -> set[str]:
        return {w for w in re.findall(r"\w+", s.lower()) if len(w) > 3}
    sims = []
    for i in range(n):
        for j in range(i + 1, n):
            a, b = wset(answers[i]), wset(answers[j])
            sims.append(len(a & b) / len(a | b) if (a | b) else 1.0)
    mean_sim = sum(sims) / len(sims)
    return mean_sim * 100, mean_sim


# --- LLM-as-a-judge rubric (functional correctness + accuracy) ---------------
JUDGE_SYSTEM = (
    "You are a strict evaluation judge. Score an AI answer against a question "
    "and an optional reference answer. Return ONLY JSON."
)

JUDGE_TEMPLATE = """Evaluate the AI answer below.

Question:
{question}

{reference_block}
AI answer:
{answer}

Score each dimension from 1 (poor) to 5 (excellent):
- functional_correctness: Does it correctly do what was asked / is it factually right?
- accuracy: Is it precise and free of errors or unsupported claims?

Return ONLY this JSON (no prose):
{{"functional_correctness": <1-5>, "accuracy": <1-5>, "rationale": "<one sentence>"}}
"""


def build_judge_prompt(question: str, answer: str, reference: str | None) -> str:
    ref = f"Reference answer (ground truth):\n{reference}\n\n" if reference else ""
    return JUDGE_TEMPLATE.format(question=question, answer=answer, reference_block=ref)


def parse_judge(text: str) -> dict:
    """Extract the JSON object from a judge response; tolerate surrounding prose."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return {"functional_correctness": 3, "accuracy": 3, "rationale": "unparsed"}
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"functional_correctness": 3, "accuracy": 3, "rationale": "unparsed"}
    return data


def score_to_100(score_1_5: float) -> float:
    return max(1.0, min(5.0, float(score_1_5))) / 5 * 100
