"""Produce SHAP explanations for the trained loan model.

This mirrors what SageMaker Clarify does under the hood (Clarify uses SHAP
for feature attribution) but runs entirely locally with no AWS calls:

- GLOBAL explanation  -> "how the model works overall"  (deck slide 41, left)
    A beeswarm/summary plot ranking features by overall impact.
- LOCAL explanation   -> "why this result specifically" (deck slide 41, right)
    A waterfall plot for a single applicant showing how each feature pushed
    that one decision toward approve or deny.
- A simple group-disparity table -> the "bias detection" idea (slide 42).

Outputs are written as PNGs to ./outputs so they can be dropped straight
into slides.
"""

import argparse
import os
import pickle

import matplotlib

matplotlib.use("Agg")  # headless: write files, don't try to open a window
import matplotlib.pyplot as plt
import pandas as pd
import shap


def load_model(model_path: str):
    with open(model_path, "rb") as f:
        bundle = pickle.load(f)
    return bundle["model"], bundle["features"]


def global_explanation(explainer, shap_values, X, out_dir):
    """Beeswarm summary: which features matter most across all predictions."""
    plt.figure()
    shap.summary_plot(shap_values, X, show=False)
    path = os.path.join(out_dir, "global_summary.png")
    plt.tight_layout()
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"[global] wrote {path}")

    # Also a plain bar chart of mean |SHAP| for an at-a-glance ranking.
    plt.figure()
    shap.summary_plot(shap_values, X, plot_type="bar", show=False)
    path_bar = os.path.join(out_dir, "global_importance_bar.png")
    plt.tight_layout()
    plt.savefig(path_bar, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"[global] wrote {path_bar}")


def local_explanation(explanation, X, row_index, out_dir):
    """Waterfall for a single applicant: why THIS decision."""
    plt.figure()
    shap.plots.waterfall(explanation[row_index], show=False)
    path = os.path.join(out_dir, f"local_waterfall_row{row_index}.png")
    plt.tight_layout()
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"[local ] wrote {path}")

    print(f"\nApplicant at test-row {row_index}:")
    print(X.iloc[row_index].to_string())


def bias_table(X, model):
    """A minimal 'bias detection' view: approval rate predicted by the model
    for each value of the sensitive attribute (age_group). This is the local
    analogue of a Clarify post-training bias metric."""
    preds = model.predict(X)
    df = X.copy()
    df["predicted_approved"] = preds
    rates = df.groupby("age_group")["predicted_approved"].mean().round(3)
    print("\nPredicted approval rate by sensitive attribute (age_group):")
    print(rates.to_string())
    disparity = rates.max() - rates.min()
    print(f"\nDisparity (max - min approval rate): {disparity:.3f}")
    print(
        "A non-trivial disparity is the signal you would investigate and "
        "mitigate (deck slide 42)."
    )


def main():
    parser = argparse.ArgumentParser(description="SHAP explanations.")
    parser.add_argument("--model", default="artifacts/model.pkl")
    parser.add_argument("--xtest", default="artifacts/X_test.csv")
    parser.add_argument("--out-dir", default="outputs")
    parser.add_argument(
        "--row",
        type=int,
        default=0,
        help="Test-set row index to explain locally.",
    )
    args = parser.parse_args()

    if not os.path.exists(args.model):
        raise SystemExit(
            f"Model not found at {args.model}. Run train_model.py first."
        )

    model, features = load_model(args.model)
    X = pd.read_csv(args.xtest)[features]

    os.makedirs(args.out_dir, exist_ok=True)

    # TreeExplainer is exact and fast for tree ensembles.
    explainer = shap.TreeExplainer(model)
    explanation = explainer(X)            # modern SHAP Explanation object
    shap_values = explanation.values      # for the summary plots

    global_explanation(explainer, shap_values, X, args.out_dir)
    local_explanation(explanation, X, args.row, args.out_dir)
    bias_table(X, model)

    print("\nDone. PNGs are in:", os.path.abspath(args.out_dir))


if __name__ == "__main__":
    main()
