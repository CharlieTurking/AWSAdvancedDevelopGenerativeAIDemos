"""Shared scenario defaults and prompt templates for the demo.

Everything the three pages need to stay consistent lives here: the default
business question, the three decomposition dimensions (from slide 19 of the
Module 4 deck), and the six-step reasoning structure (from slide 18).
"""

from __future__ import annotations

# Default open-ended business question. Deliberately big and ambiguous so the
# value of decomposition is obvious.
DEFAULT_QUESTION = (
    "We are a mid-size retailer running our e-commerce platform in an on-prem "
    "data center. Should we migrate the platform to AWS?"
)

# Default business context facts fed into the reasoning chain (Act 3).
DEFAULT_CONTEXT = (
    "- Current annual online revenue: $40M\n"
    "- Estimated one-time migration cost: $2M\n"
    "- Projected annual infrastructure savings after migration: $600K\n"
    "- Current data center lease expires in 18 months\n"
    "- Engineering team: 25 people, limited cloud experience\n"
    "- Peak traffic events (holiday sales) currently cause outages"
)

# ---------------------------------------------------------------------------
# Slide 19: Complex problem decomposition techniques
# Technical / Business / Risk dimensions, each with a focus and a stakeholder.
# ---------------------------------------------------------------------------
DIMENSIONS = {
    "Technical": {
        "focus": "Architecture",
        "sub_questions": ["Current state", "Target state", "Complexity"],
        "stakeholder": "IT teams",
    },
    "Business": {
        "focus": "Cost-benefit",
        "sub_questions": ["ROI analysis", "Timeline", "Resources"],
        "stakeholder": "Leadership",
    },
    "Risk": {
        "focus": "Mitigation",
        "sub_questions": ["Technical risks", "Business continuity", "Compliance"],
        "stakeholder": "Risk officers",
    },
}

# ---------------------------------------------------------------------------
# Act 1: naive baseline prompt
# ---------------------------------------------------------------------------
def naive_prompt(question: str) -> str:
    return question


# ---------------------------------------------------------------------------
# Act 2: decomposition prompt (does NOT answer, only splits the problem)
# ---------------------------------------------------------------------------
DECOMPOSITION_SYSTEM = (
    "You are a senior cloud migration advisor. You structure ambiguous "
    "business questions before answering them."
)


def decomposition_prompt(question: str) -> str:
    return (
        f'Decompose the following question into three analysis dimensions: '
        f"Technical, Business, and Risk.\n\n"
        f'Question: "{question}"\n\n'
        "For each dimension provide:\n"
        "1. Primary focus (one phrase)\n"
        "2. The 3-4 key sub-questions that must be answered\n"
        "3. The primary stakeholder who owns this dimension\n\n"
        "Do NOT answer the sub-questions yet. Only produce the decomposition. "
        "Format the output as three clearly labeled sections."
    )


# ---------------------------------------------------------------------------
# Act 3: step-by-step reasoning per dimension (slide 18 structure)
# ---------------------------------------------------------------------------
REASONING_SYSTEM = (
    "You are a senior cloud migration advisor. You reason step by step and "
    "always expose your reasoning trail before giving a recommendation."
)

REASONING_STEPS = [
    "Problem Analysis",
    "Context Assessment",
    "Option Evaluation",
    "Decision Logic",
    "Confidence Assessment",
    "Recommendation",
]


def reasoning_prompt(question: str, dimension: str, context: str) -> str:
    meta = DIMENSIONS[dimension]
    steps = "\n".join(f"{i}. {s}" for i, s in enumerate(REASONING_STEPS, start=1))
    return (
        f"Analyze the {dimension.upper()} dimension of this decision.\n\n"
        f'Decision: "{question}"\n'
        f"Dimension focus: {meta['focus']}\n"
        f"Primary stakeholder: {meta['stakeholder']}\n\n"
        f"Relevant context:\n{context}\n\n"
        "Reason step by step using exactly these numbered sections:\n"
        f"{steps}\n\n"
        "In Option Evaluation, compare at least three concrete options "
        "(e.g. lift-and-shift, re-architect, phased migration). "
        "In Confidence Assessment, give a data-quality percentage and a "
        "model-confidence percentage. End with a clear, single recommendation "
        f"tailored to the {meta['stakeholder']} stakeholder."
    )


def synthesis_prompt(question: str, dimension_outputs: dict[str, str]) -> str:
    sections = "\n\n".join(
        f"### {dim} analysis\n{text}" for dim, text in dimension_outputs.items()
    )
    return (
        "You are preparing a one-page executive recommendation.\n\n"
        f'Decision: "{question}"\n\n'
        "Below are three independent dimensional analyses. Synthesize them "
        "into a single executive recommendation with: (1) a one-line verdict, "
        "(2) the top rationale from each dimension, (3) the key risk to watch, "
        "and (4) a recommended next step.\n\n"
        f"{sections}"
    )
