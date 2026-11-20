"""
Rule-based prompt compression used by the demo.

This is intentionally lightweight (no ML model needed) so the demo runs
instantly and offline. It reproduces the slide-12 idea: strip filler/politeness
words, collapse verbose phrasing, and keep the task-bearing content. For a
heavier ML approach (LLMLingua) see the sibling `prompt-compression/` demo.
"""

from __future__ import annotations

import re

# Filler / politeness tokens that add tokens without adding task value.
FILLER_WORDS = {
    "please",
    "kindly",
    "could",
    "would",
    "you",
    "the",
    "a",
    "an",
    "following",
    "detailed",
    "comprehensive",
    "very",
    "really",
    "just",
    "simply",
    "basically",
    "actually",
    "in order to",
    "for me",
    "if possible",
    "as well as",
}

# Verbose phrase -> concise replacement.
PHRASE_MAP = {
    r"\bprovide (a |an )?(detailed |comprehensive )?summary of\b": "summarize",
    r"\bperform (a |an )?analysis of\b": "analyze",
    r"\bconduct (a |an )?analysis of\b": "analyze",
    r"\bmake (a |an )?list of\b": "list",
    r"\bgive me\b": "",
    r"\bi would like you to\b": "",
    r"\bi want you to\b": "",
    r"\bcan you\b": "",
    r"\bactionable recommendations for improvement\b": "recommendations",
    r"\bmain themes\b": "themes",
    r"\bsentiment analysis\b": "sentiment",
    r"\bcustomer feedback\b": "feedback",
}


def compress(prompt: str) -> str:
    """Return a shorter, semantically-equivalent prompt."""
    text = prompt.strip()

    # 1. Collapse verbose phrases.
    for pattern, repl in PHRASE_MAP.items():
        text = re.sub(pattern, repl, text, flags=re.IGNORECASE)

    # 2. Drop standalone filler words (word-boundary, case-insensitive).
    #    Sort longest-first so multi-word fillers match before single words.
    for word in sorted(FILLER_WORDS, key=len, reverse=True):
        text = re.sub(rf"(?<!\w){re.escape(word)}(?!\w)", "", text, flags=re.IGNORECASE)

    # 3. Normalise whitespace and dangling punctuation.
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.:;!?])", r"\1", text)
    text = re.sub(r"[,:]\s*$", "", text)
    text = re.sub(r"\s*,\s*,", ",", text)

    return text.strip().strip(",. ").strip()
