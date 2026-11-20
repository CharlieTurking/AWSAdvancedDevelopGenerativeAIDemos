# 06 — Explainability with SHAP / SageMaker Clarify

Demos for the **AI Governance & Compliance** pillar of Module 6 (AI Safety and
Security) — specifically model **explainability** and **bias detection**
(deck slides 39–42).

Two self-contained implementations of the same idea:

| Folder | What it is | AWS? | Cost |
|---|---|---|---|
| [`01_local_shap`](01_local_shap/) | Explains a loan model locally with the open-source SHAP library | No | None |
| [`02_sagemaker_clarify`](02_sagemaker_clarify/) | Runs real SageMaker Clarify bias + SHAP jobs (with teardown scripts) | Yes | Small |

Both use the **same synthetic, non-PII loan-approval dataset** and the same
sensitive attribute (`age_group`) so the story is consistent across the two.

## The through-line

- **Global explanation** — "how the model works" overall (slide 41, left)
- **Local explanation** — "why this result" for one applicant (slide 41, right)
- **Bias detection** — disparity across a sensitive group (slide 42)

## Recommended usage

Run **`01_local_shap`** live (fast, reliable, no cloud dependency). Keep
**`02_sagemaker_clarify`** for showing the genuine AWS artifacts, or hand it to
attendees to run in their own account. The AWS folder ships `destroy_aws.py`
and `destroy_aws.sh` — **always tear down after running it.**

See each subfolder's README for setup and run steps.
