"""
Adapter layer: legacy COBOL copybook record -> JSON -> Bedrock prompt
(Module 10, slides 9 & 10; the correct answer to Question 1).

The adapter's three responsibilities (slide 9):
  - Data transformation : parse fixed-width COBOL fields into typed JSON
  - Authentication      : (represented by an API-key check in the demo)
  - Error handling      : raise typed errors the caller can surface

COBOL copybook stores data as fixed-width fields with implied decimals and
EBCDIC-style packed numerics. Here we model the common case: fixed-width ASCII
fields with a PIC-style picture clause, including implied decimal (V) scaling.
"""

from __future__ import annotations

from dataclasses import dataclass


class AdapterError(Exception):
    """Raised when a record can't be transformed."""


@dataclass
class Field:
    name: str
    start: int          # 1-based column start (like a copybook layout)
    length: int
    kind: str           # "text" | "int" | "decimal"
    decimals: int = 0   # implied decimal places for PIC 9(n)V9(d)


# A sample CUSTOMER-RECORD copybook layout (01 CUSTOMER-RECORD).
#   05 CUST-ID        PIC X(8).
#   05 CUST-NAME      PIC X(20).
#   05 TIER           PIC X(8).
#   05 BALANCE        PIC 9(7)V99.      -> implied 2 decimals
#   05 LAST-TXN-DAYS  PIC 9(4).
#   05 SEGMENT        PIC X(12).
COPYBOOK: list[Field] = [
    Field("cust_id", 1, 8, "text"),
    Field("name", 9, 20, "text"),
    Field("tier", 29, 8, "text"),
    Field("balance", 37, 9, "decimal", decimals=2),
    Field("last_txn_days", 46, 4, "int"),
    Field("segment", 50, 12, "text"),
]

RECORD_WIDTH = max(f.start - 1 + f.length for f in COPYBOOK)  # 61


def parse_copybook(record: str) -> dict:
    """Transform one fixed-width COBOL record into a typed JSON-ready dict."""
    if len(record) < RECORD_WIDTH:
        raise AdapterError(
            f"Record too short: got {len(record)} chars, need {RECORD_WIDTH}."
        )
    out: dict = {}
    for f in COPYBOOK:
        raw = record[f.start - 1 : f.start - 1 + f.length]
        if f.kind == "text":
            out[f.name] = raw.strip()
        elif f.kind == "int":
            digits = raw.strip()
            if not digits.isdigit():
                raise AdapterError(f"Field {f.name!r} is not numeric: {raw!r}")
            out[f.name] = int(digits)
        elif f.kind == "decimal":
            digits = raw.strip()
            if not digits.isdigit():
                raise AdapterError(f"Field {f.name!r} is not numeric: {raw!r}")
            val = int(digits)
            out[f.name] = round(val / (10 ** f.decimals), f.decimals)
        else:  # pragma: no cover - guarded by construction
            raise AdapterError(f"Unknown field kind {f.kind!r}")
    return out


def authenticate(api_key: str, expected: str) -> None:
    """Minimal auth check standing in for the slide-9 authentication step."""
    if not api_key or api_key != expected:
        raise AdapterError("Authentication failed: invalid or missing API key.")


def build_prompt(customer: dict) -> str:
    """Build the Bedrock prompt for personalized content from the JSON record."""
    return (
        "Write a short, warm personalized message (2-3 sentences) for this banking "
        "customer. Reference their tier and recent activity naturally; do not invent "
        "facts beyond the data.\n\n"
        f"Customer data (JSON):\n{customer}"
    )


def make_record(cust_id, name, tier, balance_cents, last_txn_days, segment) -> str:
    """Helper to assemble a valid fixed-width record (for the demo UI)."""
    def fit(s, n):
        return str(s)[:n].ljust(n)
    rec = (
        fit(cust_id, 8)
        + fit(name, 20)
        + fit(tier, 8)
        + str(balance_cents).zfill(9)
        + str(last_txn_days).zfill(4)
        + fit(segment, 12)
    )
    return rec
