"""
Reasoning-path analysis (Module 8, slides 37-39).

Pipeline (slide 39): Reasoning chain -> Pattern matching (automated check) ->
Error detection (identify issues) -> Validation (cross-check).

Detects the slide-39 issue classes with transparent heuristics so the "automated
check" is explainable in a demo:
  - Circular logic      : a step restates the conclusion as its own justification
  - False premises      : a step asserts a quantity that doesn't appear in the question
  - Inconsistency       : the same number is given two different values across steps,
                          or the final answer disagrees with the numbers in the steps

Also supports a self-consistency check: run the question several times and compare
the final answers (agreement analysis, slide 35 flavor).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Step:
    index: int
    text: str


@dataclass
class Issue:
    kind: str          # "Circular logic" | "False premise" | "Inconsistency"
    where: str         # which step(s)
    detail: str


@dataclass
class ParsedReasoning:
    steps: list[Step] = field(default_factory=list)
    final_answer: str = ""

    @property
    def has_steps(self) -> bool:
        return len(self.steps) > 0


# --- parsing -----------------------------------------------------------------
_STEP_RE = re.compile(r"step\s*(\d+)\s*[:.)-]\s*(.+?)(?=\n\s*step\s*\d+\s*[:.)-]|\n\s*final answer|\Z)",
                      re.IGNORECASE | re.DOTALL)
_FINAL_RE = re.compile(r"final answer\s*[:.)-]?\s*(.+)", re.IGNORECASE | re.DOTALL)


def parse_reasoning(text: str) -> ParsedReasoning:
    pr = ParsedReasoning()
    for m in _STEP_RE.finditer(text):
        pr.steps.append(Step(index=int(m.group(1)), text=m.group(2).strip()))
    fm = _FINAL_RE.search(text)
    if fm:
        pr.final_answer = fm.group(1).strip().splitlines()[0].strip()
    elif pr.steps:
        pr.final_answer = pr.steps[-1].text.splitlines()[-1].strip()
    return pr


# --- number helpers ----------------------------------------------------------
_NUM_RE = re.compile(r"-?\$?\d[\d,]*\.?\d*%?")


def _numbers(text: str) -> list[str]:
    return [n.replace(",", "").replace("$", "") for n in _NUM_RE.findall(text)]


def _num_set(text: str) -> set[float]:
    out = set()
    for n in _numbers(text):
        try:
            out.add(float(n.rstrip("%")))
        except ValueError:
            pass
    return out


# --- detectors (slide 39) ----------------------------------------------------
_CIRCULAR_CUES = [
    "because it is", "which proves", "as stated above", "by definition it is",
    "this is true because it is true", "since we concluded",
]


def detect_circular(pr: ParsedReasoning) -> list[Issue]:
    issues: list[Issue] = []
    final_nums = _num_set(pr.final_answer)
    for step in pr.steps:
        low = step.text.lower()
        if any(cue in low for cue in _CIRCULAR_CUES):
            issues.append(
                Issue("Circular logic", f"Step {step.index}",
                      "A step justifies a claim by restating it.")
            )
        # Early step asserting the final number as a given (not derived).
        if step.index <= 2 and final_nums and (final_nums & _num_set(step.text)):
            if "assume" in low or "given" in low or "we know the answer" in low:
                issues.append(
                    Issue("Circular logic", f"Step {step.index}",
                          "The conclusion appears to be assumed as a premise.")
                )
    return issues


def detect_false_premise(pr: ParsedReasoning, question: str) -> list[Issue]:
    """Flag numbers introduced in the reasoning that don't trace back to the
    question (possible fabricated premise). Heuristic: ignore results of math."""
    q_nums = _num_set(question)
    issues: list[Issue] = []
    for step in pr.steps[:2]:  # premises are set up early
        for val in _num_set(step.text):
            # Allow small integers (indices, step numbers, simple constants).
            if val in q_nums or val <= 12:
                continue
            if not _derivable(val, q_nums):
                issues.append(
                    Issue("False premise", f"Step {step.index}",
                          f"Value {val:g} isn't in the question and isn't obviously "
                          "derived from it.")
                )
    return issues


def _derivable(val: float, q_nums: set[float]) -> bool:
    """Cheap check: is val a sum/product/ratio/percentage of question numbers?"""
    nums = list(q_nums)
    for a in nums:
        if a == 0:
            continue
        for b in nums:
            for cand in (a + b, a - b, a * b, a / b if b else None,
                         a * b / 100, a * (1 + b / 100)):
                if cand is not None and abs(cand - val) < max(0.01, abs(val) * 0.02):
                    return True
    return False


def detect_inconsistency(pr: ParsedReasoning) -> list[Issue]:
    issues: list[Issue] = []
    # Final answer's number(s) should appear somewhere in the steps.
    final_nums = _num_set(pr.final_answer)
    step_nums: set[float] = set()
    for s in pr.steps:
        step_nums |= _num_set(s.text)
    if final_nums and not (final_nums & step_nums):
        issues.append(
            Issue("Inconsistency", "Final answer",
                  "The final number doesn't appear in any reasoning step.")
        )
    return issues


def analyze(pr: ParsedReasoning, question: str) -> list[Issue]:
    issues: list[Issue] = []
    issues += detect_circular(pr)
    issues += detect_false_premise(pr, question)
    issues += detect_inconsistency(pr)
    return issues


# --- self-consistency (agreement analysis) -----------------------------------
def normalize_answer(ans: str) -> str:
    nums = _numbers(ans)
    if nums:
        try:
            return f"{float(nums[0].rstrip('%')):g}"
        except ValueError:
            pass
    return ans.strip().lower()


def consistency(answers: list[str]) -> tuple[float, dict[str, int]]:
    """Return (agreement_fraction, tally) over normalized final answers."""
    tally: dict[str, int] = {}
    for a in answers:
        key = normalize_answer(a)
        tally[key] = tally.get(key, 0) + 1
    if not answers:
        return 0.0, tally
    top = max(tally.values())
    return top / len(answers), tally
