# Local SHAP Explainability Demo

Explains a loan-approval model **entirely on your machine** — no AWS account,
no cost, no setup beyond `pip install`. It demonstrates the same ideas that
Amazon SageMaker Clarify provides (Clarify uses SHAP under the hood), making
it a reliable choice for a live session.

## What it shows (maps to Module 6 slides)

| Demo output | Slide | Idea |
|---|---|---|
| Global summary / bar plot | 41 (left) | "How the model works" — overall feature importance |
| Local waterfall for one applicant | 41 (right) | "Why this result" — per-decision attribution |
| Group-disparity table/chart | 42 | Bias detection across a sensitive attribute |

## The data

`generate_data.py` creates a **synthetic, non-PII** loan dataset (fixed seed,
fully reproducible). Features: `applicant_income`, `loan_amount`,
`credit_history_length`, `debt_to_income`, `num_open_accounts`, and
`age_group` (the sensitive attribute used for the bias view). Label:
`approved`. A mild, intentional `age_group` skew is baked in so the bias
report has something real to surface.

## Setup

```bash
cd ~/06_explanability_SHAP/01_local_shap
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run — one shot (easiest)

```bash
./run_all.sh                 # venv + deps + pipeline, then launches Streamlit
./run_all.sh --no-app        # pipeline only (writes PNGs to outputs/)
./run_all.sh --row 7         # explain a different applicant row
```

`run_all.sh` creates the `.venv` and installs requirements on first run, so you
can skip the manual setup above if you use it.

## Run — scripted (writes PNGs for slides)

```bash
python train_model.py            # trains, saves artifacts/model.pkl + X_test.csv
python explain_shap.py --row 0   # writes global + local plots to outputs/
```

Pass a different `--row` to explain a different applicant.

## Run — interactive (recommended for live)

```bash
streamlit run app.py
```

Three tabs: **Global** (overall importance), **Local** (pick any applicant,
see the decision and its waterfall), and **Bias / disparity**.

## Suggested live flow (~4 min)

1. **Global** tab: "income and debt-to-income dominate the model."
2. **Local** tab: slide to a denied applicant: "denied mainly because of high
   debt-to-income and low credit history."
3. **Bias** tab: "the model approves one age group more than the other — this
   is the gap you'd investigate and mitigate."

## Files

- `generate_data.py` — synthetic dataset generator
- `train_model.py` — trains the classifier, saves artifacts
- `explain_shap.py` — writes global + local SHAP PNGs and a bias table
- `app.py` — interactive Streamlit version
- `run_all.sh` — one-shot: venv + pipeline + optional Streamlit launch
- `requirements.txt`

## Note on NumPy

The stack is pinned to **NumPy 2.x** (`numpy==2.1.3`) with `pyarrow==17.0.0`.
Newer pyarrow releases require NumPy ≥ 2.0, so pinning both avoids the
`ImportError: pyarrow requires NumPy 2.0 or newer` that occurs when an old
NumPy is paired with a drifting (unpinned) pyarrow.
