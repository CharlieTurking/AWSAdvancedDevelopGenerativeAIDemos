"""Generate a small, synthetic, non-PII loan-approval dataset.

The data is deliberately synthetic so the demo carries no privacy risk and is
fully reproducible (fixed random seed). A mild, intentional correlation is
baked in between some features and the approval label so that SHAP has a
clear signal to explain and the bias report has something to find.

Features
--------
- applicant_income      : annual income (currency units)
- loan_amount           : requested loan amount
- credit_history_length : years of credit history
- debt_to_income        : ratio 0.0 - 1.0
- num_open_accounts     : number of open credit accounts
- age_group             : 0 = under 40, 1 = 40 and over  (used as the
                          sensitive/facet attribute for the bias demo)

Label
-----
- approved : 1 = approved, 0 = denied
"""

import argparse
import numpy as np
import pandas as pd

RANDOM_SEED = 42


def generate(n_rows: int = 2000) -> pd.DataFrame:
    rng = np.random.default_rng(RANDOM_SEED)

    applicant_income = rng.normal(60_000, 20_000, n_rows).clip(12_000, 250_000)
    loan_amount = rng.normal(25_000, 12_000, n_rows).clip(1_000, 150_000)
    credit_history_length = rng.normal(10, 5, n_rows).clip(0, 40)
    debt_to_income = rng.normal(0.35, 0.15, n_rows).clip(0.0, 1.0)
    num_open_accounts = rng.integers(1, 15, n_rows)
    age_group = rng.integers(0, 2, n_rows)  # sensitive attribute

    # A latent "creditworthiness" score drives approval. Higher income and
    # longer credit history help; high loan amount and high debt-to-income
    # hurt. We add a small, deliberate age_group skew so the bias report has
    # a measurable disparity to surface (this is the thing you'd want to
    # DETECT and MITIGATE, per the deck).
    score = (
        0.000030 * applicant_income
        - 0.000018 * loan_amount
        + 0.060 * credit_history_length
        - 2.2 * debt_to_income
        + 0.05 * num_open_accounts
        + 0.45 * age_group          # intentional, mild disparity
        + rng.normal(0, 0.5, n_rows)
    )

    # Convert the latent score to a probability, then to a 0/1 label.
    prob = 1.0 / (1.0 + np.exp(-(score - score.mean())))
    approved = (prob > 0.5).astype(int)

    df = pd.DataFrame(
        {
            "applicant_income": applicant_income.round(0),
            "loan_amount": loan_amount.round(0),
            "credit_history_length": credit_history_length.round(1),
            "debt_to_income": debt_to_income.round(3),
            "num_open_accounts": num_open_accounts,
            "age_group": age_group,
            "approved": approved,
        }
    )
    return df


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic loan data.")
    parser.add_argument("--rows", type=int, default=2000, help="Number of rows.")
    parser.add_argument(
        "--out", default="data/loans.csv", help="Output CSV path."
    )
    args = parser.parse_args()

    import os

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    df = generate(args.rows)
    df.to_csv(args.out, index=False)

    approved_rate = df["approved"].mean()
    print(f"Wrote {len(df)} rows to {args.out}")
    print(f"Overall approval rate: {approved_rate:.1%}")
    print("Approval rate by age_group:")
    print(df.groupby("age_group")["approved"].mean().round(3).to_string())


if __name__ == "__main__":
    main()
