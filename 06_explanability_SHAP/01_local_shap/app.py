"""Interactive Streamlit version of the local SHAP explainability demo.

Lets you train the model, see the global feature importance, pick any
applicant and see the local "why this decision" waterfall, and view the
group-disparity (bias) table - all live, no AWS.

Run:
    streamlit run app.py
"""

import os
import pickle

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import shap
import streamlit as st
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import train_test_split

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

st.set_page_config(page_title="Local SHAP Explainability", layout="wide")
st.title("Explainability with SHAP (local, no AWS)")
st.caption(
    "Mirrors what SageMaker Clarify does under the hood: global feature "
    "importance ('how the model works'), local attributions ('why this "
    "result'), and a group-disparity bias view."
)


@st.cache_resource
def build_model():
    df = generate()
    X = df[FEATURES]
    y = df[TARGET]
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=RANDOM_SEED, stratify=y
    )
    model = GradientBoostingClassifier(random_state=RANDOM_SEED)
    model.fit(X_train, y_train)
    explainer = shap.TreeExplainer(model)
    explanation = explainer(X_test.reset_index(drop=True))
    return model, X_test.reset_index(drop=True), explanation


model, X_test, explanation = build_model()

tab_global, tab_local, tab_bias = st.tabs(
    ["Global (overall)", "Local (one applicant)", "Bias / disparity"]
)

with tab_global:
    st.subheader("How the model works overall")
    st.write(
        "Each point is one applicant. Features are ranked by overall impact "
        "on the model's output."
    )
    fig = plt.figure()
    shap.summary_plot(explanation.values, X_test, show=False)
    st.pyplot(fig, bbox_inches="tight")
    plt.close(fig)

with tab_local:
    st.subheader("Why this specific result")
    row = st.slider("Pick an applicant (test-set row)", 0, len(X_test) - 1, 0)

    pred = int(model.predict(X_test.iloc[[row]])[0])
    proba = float(model.predict_proba(X_test.iloc[[row]])[0, 1])
    decision = "APPROVED" if pred == 1 else "DENIED"
    st.metric("Model decision", decision, f"approval probability {proba:.1%}")

    col1, col2 = st.columns([1, 2])
    with col1:
        st.write("**Applicant features**")
        st.dataframe(X_test.iloc[row].rename("value"))
    with col2:
        fig = plt.figure()
        shap.plots.waterfall(explanation[row], show=False)
        st.pyplot(fig, bbox_inches="tight")
        plt.close(fig)

with tab_bias:
    st.subheader("Group disparity (bias detection)")
    st.write(
        "Predicted approval rate for each value of the sensitive attribute "
        "`age_group` (0 = under 40, 1 = 40 and over). A non-trivial gap is "
        "the signal you would investigate and mitigate."
    )
    df_pred = X_test.copy()
    df_pred["predicted_approved"] = model.predict(X_test)
    rates = (
        df_pred.groupby("age_group")["predicted_approved"].mean().round(3)
    )
    st.bar_chart(rates)
    disparity = float(rates.max() - rates.min())
    st.metric("Disparity (max - min approval rate)", f"{disparity:.3f}")
