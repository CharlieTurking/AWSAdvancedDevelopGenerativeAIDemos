"""
Sliding-window context pruning with AUTOMATIC importance detection
— Module 7, Question 1, variant where the SYSTEM (not the user) decides which
older turns matter.

Strategy:
  - ALWAYS keep the current user query.
  - Keep the last N conversation turns (the sliding window).
  - Keep older turns the system judges "important" on its own, using offline
    heuristics (identifiers, commitments, money/dates, relevance to the current
    query). No user pinning required.
  - Optionally pull in older turns that are semantically relevant to the current
    query (keyword overlap), so references to earlier issues still resolve.

A "turn" here is one user+assistant exchange.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Turn:
    index: int  # 1-based turn number
    user: str
    assistant: str


@dataclass
class PruneResult:
    kept_indices: list[int] = field(default_factory=list)
    reason: dict[int, str] = field(default_factory=dict)  # index -> why kept
    importance: dict[int, float] = field(default_factory=dict)  # index -> score

    def kept(self) -> set[int]:
        return set(self.kept_indices)


def _keyword_overlap(a: str, b: str) -> float:
    """Cheap lexical similarity (Jaccard over lowercased word sets).
    Used as the offline fallback when embeddings aren't available."""
    wa = {w for w in a.lower().split() if len(w) > 3}
    wb = {w for w in b.lower().split() if len(w) > 3}
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


# --- Signals the system uses to auto-detect important turns -------------------

# Structured identifiers: order numbers, SKUs, tracking codes, emails, long IDs.
_ID_PATTERNS = [
    re.compile(r"\b[A-Z]{2,}-?\d{3,}\b"),          # ORD-48213, SKU12345
    re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),    # email addresses
    re.compile(r"#\d{3,}\b"),                        # #4821 ticket/order refs
    re.compile(r"\b\d{4}[- ]?\d{4}[- ]?\d{4}\b"),    # card-like / long numbers
]

# Money and dates — concrete figures the user tends to refer back to.
_MONEY_DATE_PATTERNS = [
    re.compile(r"[$£€]\s?\d+(?:[.,]\d+)?"),
    re.compile(r"\b\d+\s?(?:business\s)?days?\b", re.I),
    re.compile(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b"),
]

# Commitments / policy statements that constrain future answers.
_COMMITMENT_TERMS = (
    "refund", "replacement", "replace", "return", "cancel", "cancelled",
    "warranty", "guarantee", "we'll", "we will", "you can", "eligible",
    "prepaid", "free", "no cost", "original payment", "original card",
)


def score_importance(turn: "Turn", current_query: str) -> float:
    """Heuristic, offline importance score for a single turn, in [0, 1].

    The SYSTEM uses this instead of a user-set 'pinned' flag. Higher means more
    worth keeping even when the turn falls outside the recent window.
    """
    text = f"{turn.user} {turn.assistant}"
    lower = text.lower()
    score = 0.0

    # Structured identifiers are the strongest signal — users reference these.
    if any(p.search(text) for p in _ID_PATTERNS):
        score += 0.6

    # Concrete money/date figures.
    if any(p.search(text) for p in _MONEY_DATE_PATTERNS):
        score += 0.25

    # Commitments / policy the assistant made. Several distinct commitment
    # terms in one turn (e.g. "refund" + "original payment" + "replacement")
    # is a strong signal the user will refer back to it.
    hits = sum(1 for term in _COMMITMENT_TERMS if term in lower)
    score += min(hits, 4) * 0.12

    # Relevance to what the user is asking right now — weighted heavily so a
    # turn that directly answers the final query outranks merely adjacent ones.
    score += 0.9 * _keyword_overlap(current_query, text)

    return min(score, 1.0)


def select_turns(
    history: list[Turn],
    current_query: str,
    *,
    window: int = 5,
    auto_importance: bool = True,
    importance_threshold: float = 0.5,
    semantic_extra: int = 0,
    similarity_fn=None,
    sim_threshold: float = 0.15,
) -> PruneResult:
    """Decide which historical turns to keep.

    window               : number of most-recent turns to always keep.
    auto_importance      : let the system keep older turns whose computed
                           importance score clears `importance_threshold`.
    importance_threshold : minimum auto-importance score to keep an older turn.
    semantic_extra       : up to this many additional older turns, chosen by
                           relevance to current_query (falls back to keyword
                           overlap when similarity_fn is None).
    similarity_fn        : optional callable(query, text) -> float in [0,1].
    """
    result = PruneResult()
    if not history:
        return result

    n = len(history)
    recent_cutoff = n - window

    sim = similarity_fn or _keyword_overlap

    # Rank older turns by relevance for the optional semantic top-up.
    scored_old: list[tuple[float, int]] = []
    for i, turn in enumerate(history):
        # Record the computed importance for every turn (used by the UI too).
        imp = score_importance(turn, current_query)
        result.importance[turn.index] = imp

        is_recent = i >= recent_cutoff
        if is_recent:
            result.kept_indices.append(turn.index)
            result.reason[turn.index] = "recent (sliding window)"
            continue
        if auto_importance and imp >= importance_threshold:
            result.kept_indices.append(turn.index)
            result.reason[turn.index] = f"auto-important ({imp:.2f})"
            continue
        # Candidate for semantic top-up.
        score = sim(current_query, f"{turn.user} {turn.assistant}")
        scored_old.append((score, i))

    if semantic_extra > 0 and scored_old:
        scored_old.sort(reverse=True)
        for score, i in scored_old[:semantic_extra]:
            if score < sim_threshold:
                break
            turn = history[i]
            if turn.index not in result.reason:
                result.kept_indices.append(turn.index)
                result.reason[turn.index] = f"semantic match ({score:.2f})"

    result.kept_indices.sort()
    return result


def build_messages(
    history: list[Turn],
    current_query: str,
    kept: set[int],
) -> list[dict]:
    """Build the Bedrock Converse `messages` list from the kept turns + query."""
    messages: list[dict] = []
    for turn in history:
        if turn.index in kept:
            messages.append({"role": "user", "content": [{"text": turn.user}]})
            messages.append({"role": "assistant", "content": [{"text": turn.assistant}]})
    messages.append({"role": "user", "content": [{"text": current_query}]})
    return messages


def build_full_messages(history: list[Turn], current_query: str) -> list[dict]:
    """Baseline: send the ENTIRE history (what the Q1 scenario does today)."""
    return build_messages(history, current_query, {t.index for t in history})
