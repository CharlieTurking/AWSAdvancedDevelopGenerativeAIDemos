"""Train a small gradient-boosted classifier on the synthetic loan data.

Kept intentionally simple: the point of this demo is explainability, not
model performance. The trained model and the feature matrix are saved so the
SHAP script can load them without retraining.
"""

import argparse
import os
import pickle

import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, roc_auc_score

from generate_data import generate, RANDOM_SEED

FEATURES = [
    "applicant_income",
    "loan_amount",
    "credit_history_length",
    "debt_to_income",
    "num_open_accounts",
    "age_group",
]
TARGET = "approved"


def load_or_generate(data_path: str) -> pd.DataFrame:
    if os.path.exists(data_path):
        print(f"Loading existing data from {data_path}")
        return pd.read_csv(data_path)
    print(f"No data at {data_path}; generating synthetic data.")
    df = generate()
    os.makedirs(os.path.dirname(data_path) or ".", exist_ok=True)
    df.to_csv(data_path, index=False)
    return df


def main():
    parser = argparse.ArgumentParser(description="Train the loan model.")
    parser.add_argument("--data", default="data/loans.csv")
    parser.add_argument("--model-out", default="artifacts/model.pkl")
    parser.add_argument("--xtest-out", default="artifacts/X_test.csv")
    args = parser.parse_args()

    df = load_or_generate(args.data)

    X = df[FEATURES]
    y = df[TARGET]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=RANDOM_SEED, stratify=y
    )

    model = GradientBoostingClassifier(random_state=RANDOM_SEED)
    model.fit(X_train, y_train)

    preds = model.predict(X_test)
    proba = model.predict_proba(X_test)[:, 1]
    acc = accuracy_score(y_test, preds)
    auc = roc_auc_score(y_test, proba)
    print(f"Test accuracy: {acc:.3f}")
    print(f"Test ROC AUC : {auc:.3f}")

    os.makedirs(os.path.dirname(args.model_out) or ".", exist_ok=True)
    with open(args.model_out, "wb") as f:
        pickle.dump({"model": model, "features": FEATURES}, f)
    X_test.to_csv(args.xtest_out, index=False)

    print(f"Saved model to {args.model_out}")
    print(f"Saved test features to {args.xtest_out}")


if __name__ == "__main__":
    main()
