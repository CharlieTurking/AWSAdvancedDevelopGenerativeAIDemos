"""
Prompt templates for the reasoning demo (Module 8, slides 36 & 38).

Two styles:
  - traditional : "just give the answer" (hidden reasoning)
  - chain-of-thought : "think step by step, show your reasoning" with a numbered,
    machine-parseable step format so we can analyze the reasoning path (slides
    37-39).
"""

from __future__ import annotations

# Financial-analysis flavor to match Question 2's scenario.
SYSTEM = (
    "You are a financial analysis assistant. Be precise with numbers and state "
    "any assumptions you make."
)

TRADITIONAL_INSTRUCTION = (
    "Answer the following question. Give only the final answer, concisely.\n\n"
    "Question: {question}"
)

# The numbered "Step N:" format is what analysis.py parses.
COT_INSTRUCTION = (
    "Think through this step by step, showing your reasoning.\n"
    "Format your response EXACTLY as:\n"
    "Step 1: <identify the known quantities and what is asked>\n"
    "Step 2: <analyze / set up the calculation>\n"
    "Step 3: <reason through the math, showing numbers>\n"
    "Step 4: <conclude>\n"
    "Final answer: <the answer on its own line>\n\n"
    "Question: {question}"
)


def traditional_prompt(question: str) -> str:
    return TRADITIONAL_INSTRUCTION.format(question=question)


def cot_prompt(question: str) -> str:
    return COT_INSTRUCTION.format(question=question)
