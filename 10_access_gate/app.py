"""
Demo D — Conditional / attribute-based access gate for Bedrock
(AWS Advanced Dev with GenAI, Module 10, slides 25, 26, 28).

An ABAC decision engine (slide 28) gates bedrock:InvokeModel on user attributes,
resource (model) risk tier, and environment (MFA / corporate network / compliant
device / source IP / business hours), mirroring the slide-25 conditional-access
IAM policy. The Bedrock call only happens if the decision is ALLOW.

Run locally:
    pip install -r requirements.txt
    streamlit run app.py
"""

from __future__ import annotations

import streamlit as st

import os
import sys

# Make the repo-root shared helpers importable when launched via
# `streamlit run app.py` from inside this demo folder.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from model_catalog import model_selectbox  # noqa: E402

from access_control import (
    CORPORATE_CIDR,
    HIGH_VALUE_DEPARTMENTS,
    MODELS,
    Environment,
    Principal,
    evaluate,
)
from bedrock_client import DEFAULT_MODEL_ID, DEFAULT_REGION, converse

st.set_page_config(page_title="Access Gate × Bedrock", page_icon="🛂", layout="wide")

ROLES = ["Data scientist", "Analyst", "Content writer", "Developer", "Admin"]
DEPARTMENTS = ["AI-Researchers", "Senior-Engineers", "Marketing", "Support", "Finance"]

with st.sidebar:
    st.header("Configuration")
    simulate = st.toggle("Simulate (no Bedrock calls)", value=True,
                         help="On = canned response if allowed. Off = real Bedrock.")
    region = st.text_input("AWS region", value=DEFAULT_REGION)
    model_id = model_selectbox("Bedrock model ID (when allowed)", "llm", DEFAULT_MODEL_ID)
    st.caption(
        "This evaluates the policy locally to teach how an IAM condition gates the "
        "call. It is not real IAM enforcement."
    )

st.title("🛂 Conditional / ABAC access gate for Bedrock")
st.markdown(
    "Module 10 · slides 25, 26, 28. The **ABAC decision engine** evaluates user + "
    "resource + environment + action and allows `bedrock:InvokeModel` only when the "
    "slide-25 conditions are met."
)

col_u, col_r, col_e = st.columns(3)
with col_u:
    st.subheader("User attributes")
    role = st.selectbox("Role", ROLES)
    department = st.selectbox("Department", DEPARTMENTS)
with col_r:
    st.subheader("Resource")
    model_label = st.selectbox("Model (risk tier)", list(MODELS))
    st.caption(f"Tier: **{MODELS[model_label].upper()}**")
with col_e:
    st.subheader("Environment")
    mfa = st.checkbox("MFA present", value=True)
    corp = st.checkbox("On corporate network", value=True)
    compliant = st.checkbox("Compliant device", value=True)
    source_ip = st.text_input("Source IP", value="203.0.113.17")
    business_hours = st.checkbox("Within business hours", value=True)

st.caption(
    f"High-value models require MFA + corporate network + compliant device + "
    f"department ∈ {sorted(HIGH_VALUE_DEPARTMENTS)} + source IP ∈ {CORPORATE_CIDR}."
)

evaluate_btn = st.button("Evaluate access", type="primary", use_container_width=True)

if evaluate_btn:
    principal = Principal(role=role, department=department)
    env = Environment(
        mfa_present=mfa, on_corporate_network=corp, compliant_device=compliant,
        source_ip=source_ip, business_hours=business_hours,
    )
    decision = evaluate(principal, model_label, env)

    st.subheader("Decision")
    if decision.allow:
        st.success("✅ ALLOW — all required conditions satisfied.")
    else:
        st.error(f"⛔ DENY — failing condition(s): {', '.join(decision.blocking)}")

    st.write("Policy evaluation trace:")
    for r in decision.reasons:
        st.write(r)

    st.divider()
    st.subheader("Bedrock call")
    if not decision.allow:
        st.info("Call blocked by the access gate — Bedrock is never invoked.")
        st.stop()

    prompt = "In one sentence, confirm access to this model is working."
    if simulate:
        st.write(f"[simulated] Access granted for {role} to {model_label}.")
    else:
        try:
            res = converse(prompt, model_id=model_id, region=region)
        except Exception as e:  # noqa: BLE001
            st.error(f"Bedrock call failed: {e}")
            st.info("Turn on 'Simulate' to run offline, or check access/credentials.")
            st.stop()
        st.caption(f"{res.latency_s:.2f}s · in {res.input_tokens} tok · out {res.output_tokens} tok")
        st.write(res.text)
