"""
Real-time token tracking + traffic-light alerting (Module 8, slides 5 & 7).

Implements:
  - the traffic-light status system (slide 7):
        Normal   0-80%  of quota   (green)
        Warning  80-95% of quota   (amber)
        Critical >95%   of quota   (red)
  - custom metric dimensions (slide 7): tokens/min, per app, per user segment
  - cost-trend projection from current burn rate
  - the Q&A 1:1 vs summarization 10:1 output:input ratio reference (slide 5)
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

# Traffic-light thresholds as fractions of the quota (slide 7).
WARNING_FRACTION = 0.80
CRITICAL_FRACTION = 0.95

# Typical output:input token ratios by use case (slide 5), for the UI reference.
USE_CASE_RATIOS = {
    "Q&A": 1.0,            # ~1:1
    "Summarization": 10.0,  # ~10:1 (long input, short output) shown as input:output
}


@dataclass
class Record:
    """One tracked Bedrock call."""
    app: str
    user_segment: str
    input_tokens: int
    output_tokens: int
    latency_s: float
    cost_usd: float
    ts: float  # epoch seconds

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def status_for(used: int, quota: int) -> tuple[str, str, float]:
    """Return (level, emoji, fraction) for the traffic-light system."""
    frac = used / quota if quota else 0.0
    if frac > CRITICAL_FRACTION:
        return "Critical", "🔴", frac
    if frac >= WARNING_FRACTION:
        return "Warning", "🟡", frac
    return "Normal", "🟢", frac


@dataclass
class Tracker:
    """Accumulates records and computes the metrics the dashboard displays."""
    quota_tokens: int = 100_000
    records: list[Record] = field(default_factory=list)

    def add(self, rec: Record) -> None:
        self.records.append(rec)

    # ---- totals ----
    @property
    def total_tokens(self) -> int:
        return sum(r.total_tokens for r in self.records)

    @property
    def total_input(self) -> int:
        return sum(r.input_tokens for r in self.records)

    @property
    def total_output(self) -> int:
        return sum(r.output_tokens for r in self.records)

    @property
    def total_cost(self) -> float:
        return sum(r.cost_usd for r in self.records)

    @property
    def request_count(self) -> int:
        return len(self.records)

    # ---- traffic-light status ----
    def status(self) -> tuple[str, str, float]:
        return status_for(self.total_tokens, self.quota_tokens)

    # ---- granular breakdowns (slide 7 dimensions) ----
    def by_dimension(self, attr: str) -> dict[str, dict[str, float]]:
        """Group tokens/cost/requests by 'app' or 'user_segment'."""
        agg: dict[str, dict[str, float]] = defaultdict(
            lambda: {"tokens": 0, "cost": 0.0, "requests": 0}
        )
        for r in self.records:
            key = getattr(r, attr)
            agg[key]["tokens"] += r.total_tokens
            agg[key]["cost"] += r.cost_usd
            agg[key]["requests"] += 1
        return dict(agg)

    def tokens_per_minute(self) -> float:
        """Observed burn rate across the tracked window (tokens/min)."""
        if len(self.records) < 2:
            return float(self.total_tokens)
        span = self.records[-1].ts - self.records[0].ts
        if span <= 0:
            return float(self.total_tokens)
        return self.total_tokens / (span / 60.0)

    def project_to_quota(self) -> float | None:
        """Minutes until the quota is hit at the current burn rate, or None."""
        remaining = self.quota_tokens - self.total_tokens
        if remaining <= 0:
            return 0.0
        tpm = self.tokens_per_minute()
        if tpm <= 0:
            return None
        return remaining / tpm


def analyze_alert(level: str, within_business_hours: bool) -> dict:
    """Intelligent alert engine (slide 7): context analysis -> threshold logic
    -> action trigger. Business-hours context tunes the recommended action so we
    don't page anyone off-hours for a mere Warning."""
    if level == "Critical":
        return {
            "notify": True,
            "channel": "page on-call" if within_business_hours else "page on-call (after-hours)",
            "action": "Throttle / switch to smaller model to protect the quota",
        }
    if level == "Warning":
        return {
            "notify": within_business_hours,
            "channel": "Slack #ai-ops" if within_business_hours else "queue for next business hour",
            "action": "Monitor closely; prepare automated response",
        }
    return {"notify": False, "channel": "—", "action": "No action; nominal usage"}
