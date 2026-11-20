"""
Caches for the demo.

ExactCache     — traditional web-style caching: hit only on an exact (normalized)
                 string match. This is what the Question 2 scenario uses today and
                 why its hit rate is low.

SemanticCache  — generative-AI caching: store a query's embedding, and on lookup
                 return a cached answer when the nearest stored vector is within a
                 cosine-similarity threshold. Locally the vectors live in a plain
                 Python list; the AWS variant (Q2 option D) uses ElastiCache for
                 Redis + RediSearch for the vector index.

An offline embedding fallback (hashing bag-of-words) lets the demo run without
Bedrock access for rehearsal; it is similarity-aware enough to show the behaviour
but is NOT a substitute for Titan embeddings in a real system.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field


def normalize(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace — used as the exact key."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", "", text)
    return re.sub(r"\s+", " ", text)


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# ---------------------------------------------------------------------------
# Offline embedding fallback (only used when use_bedrock=False)
# ---------------------------------------------------------------------------
# This is a crude stand-in for a real embedding model. It maps words onto a small
# set of "concept" dimensions via a synonym lexicon so that same-intent
# paraphrases land near each other and different intents stay apart. It exists
# only so the demo can be rehearsed offline — Titan embeddings do this properly.
_CONCEPTS = {
    "password": {
        "password", "passwords", "credential", "credentials", "login", "logins",
        "signin", "signon", "pin", "passcode",
    },
    "change": {
        "change", "changing", "reset", "resetting", "update", "updating", "modify",
        "set", "new", "forgot", "forgotten", "recover", "recovering",
    },
    "order": {"order", "orders", "shipment", "shipments", "package", "parcel", "delivery"},
    "track": {"track", "tracking", "where", "status", "locate", "find"},
    "refund": {"refund", "refunds", "money", "back", "reimbursement", "reimburse"},
    "request": {"request", "get", "process", "how", "claim"},
    "shipping": {"ship", "shipping", "international", "internationally", "abroad", "overseas"},
    "hours": {"hours", "open", "opening", "business", "time", "times"},
}
# Word -> list of concept indices it activates.
_WORD2CONCEPTS: dict[str, list[int]] = {}
for _idx, (_concept, _words) in enumerate(_CONCEPTS.items()):
    for _w in _words:
        _WORD2CONCEPTS.setdefault(_w, []).append(_idx)

_DIM = len(_CONCEPTS)


def offline_embed(text: str) -> list[float]:
    """Deterministic concept-bag vector. Same-intent paraphrases -> similar vector.
    A rehearsal-only stand-in; NOT a substitute for Titan embeddings."""
    vec = [0.0] * _DIM
    for word in normalize(text).split():
        for idx in _WORD2CONCEPTS.get(word, ()):
            vec[idx] += 1.0
    return vec


@dataclass
class ExactCache:
    store: dict[str, str] = field(default_factory=dict)
    hits: int = 0
    misses: int = 0

    def lookup(self, query: str) -> str | None:
        key = normalize(query)
        if key in self.store:
            self.hits += 1
            return self.store[key]
        self.misses += 1
        return None

    def put(self, query: str, answer: str) -> None:
        self.store[normalize(query)] = answer

    @property
    def total(self) -> int:
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        return self.hits / self.total if self.total else 0.0


@dataclass
class CacheEntry:
    query: str
    answer: str
    vector: list[float]


@dataclass
class SemanticCache:
    threshold: float = 0.85
    entries: list[CacheEntry] = field(default_factory=list)
    hits: int = 0
    misses: int = 0

    def lookup(self, query: str, vector: list[float]):
        """Return (answer, matched_query, score) on a hit, else (None, None, best_score)."""
        best_score = 0.0
        best_entry: CacheEntry | None = None
        for entry in self.entries:
            score = cosine(vector, entry.vector)
            if score > best_score:
                best_score = score
                best_entry = entry
        if best_entry is not None and best_score >= self.threshold:
            self.hits += 1
            return best_entry.answer, best_entry.query, best_score
        self.misses += 1
        return None, None, best_score

    def put(self, query: str, answer: str, vector: list[float]) -> None:
        self.entries.append(CacheEntry(query=query, answer=answer, vector=vector))

    @property
    def total(self) -> int:
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        return self.hits / self.total if self.total else 0.0
