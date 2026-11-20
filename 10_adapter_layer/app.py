"""
Demo A — Adapter layer: legacy COBOL copybook -> JSON -> Bedrock
(AWS Advanced Dev with GenAI, Module 10, slides 9 & 10; answer to Question 1).

Question 1 scenario: Bedrock needs real-time access to customer data stored in a
legacy mainframe's COBOL copybook format. The correct pattern is an API facade
with a data-transformation layer (COBOL -> JSON), plus auth and error handling.

This app shows that adapter end to end:
  raw fixed-width record  ->  parse (transform)  ->  JSON  ->  Bedrock  ->  content

Run locally:
    pip install -r requirements.txt
    streamlit run app.py
"""

from __future__ import annotations

import json

import streamlit as st

from adapter import (
    COPYBOOK,
    RECORD_WIDTH,
    AdapterError,
    authenticate,
    build_prompt,
    make_record,
    parse_copybook,
)

import os
import sys

# Make the repo-root shared helpers importable when launched via
# `streamlit run app.py` from inside this demo folder.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from model_catalog import model_selectbox  # noqa: E402

from bedrock_client import DEFAULT_MODEL_ID, DEFAULT_REGION, converse

st.set_page_config(page_title="Adapter Layer × Bedrock", page_icon="🔌", layout="wide")

EXPECTED_KEY = "demo-key-123"

with st.sidebar:
    st.header("Configuration")
    simulate = st.toggle("Simulate (no Bedrock calls)", value=True,
                         help="On = canned generated message. Off = live Bedrock.")
    region = st.text_input("AWS region", value=DEFAULT_REGION)
    model_id = model_selectbox("Bedrock model ID", "llm", DEFAULT_MODEL_ID)
    st.divider()
    api_key = st.text_input("Adapter API key", value=EXPECTED_KEY, type="password",
                            help=f"Auth step (slide 9). Expected: {EXPECTED_KEY}")

st.title("🔌 Adapter layer: legacy COBOL → JSON → Bedrock")
st.markdown(
    "Module 10 · slides 9–10 · Question 1. The adapter does **data transformation** "
    "(fixed-width COBOL → JSON), **authentication**, and **error handling** before "
    "calling Amazon Bedrock for personalized content."
)

with st.expander("Copybook layout (01 CUSTOMER-RECORD)", expanded=False):
    st.table([
        {"Field": f.name, "Cols": f"{f.start}-{f.start + f.length - 1}",
         "Len": f.length, "Type": f.kind + (f"({f.decimals}dp)" if f.decimals else "")}
        for f in COPYBOOK
    ])
    st.caption(f"Total record width: {RECORD_WIDTH} characters.")

st.subheader("1. Legacy record (fixed-width COBOL copybook)")
st.caption("Edit the fields; the adapter assembles a valid fixed-width record.")
c1, c2, c3 = st.columns(3)
with c1:
    cust_id = st.text_input("CUST-ID", value="C0007421")
    name = st.text_input("CUST-NAME", value="Jamie Rivera")
with c2:
    tier = st.selectbox("TIER", ["GOLD", "SILVER", "BRONZE"])
    balance = st.number_input("BALANCE (dollars)", value=4820.55, step=100.0)
with c3:
    last_txn_days = st.number_input("LAST-TXN-DAYS", value=3, step=1, min_value=0)
    segment = st.text_input("SEGMENT", value="RETAIL")

record = make_record(cust_id, name, tier, int(round(balance * 100)),
                     int(last_txn_days), segment)
st.code(record, language="text")
st.caption(f"Record length: {len(record)} chars (expected {RECORD_WIDTH}).")

# Allow intentionally breaking the record to show error handling.
corrupt = st.checkbox("Inject a bad record (truncate) to demo error handling", value=False)
if corrupt:
    record = record[: RECORD_WIDTH - 10]

run = st.button("Run adapter → Bedrock", type="primary", use_container_width=True)

if run:
    # Step: authentication (slide 9).
    try:
        authenticate(api_key, EXPECTED_KEY)
    except AdapterError as e:
        st.error(f"🔒 {e}")
        st.stop()

    # Step: data transformation (slide 10).
    st.subheader("2. Transformed JSON")
    try:
        customer = parse_copybook(record)
    except AdapterError as e:
        st.error(f"⚠️ Transformation/error-handling step caught: {e}")
        st.info("Uncheck 'Inject a bad record' to run a valid record.")
        st.stop()
    st.json(customer)

    # Step: call Bedrock.
    st.subheader("3. Generated personalized content (Bedrock)")
    prompt = build_prompt(customer)
    if simulate:
        msg = (
            f"Hi {customer['name']}, thank you for being a valued {customer['tier']} "
            f"member. We noticed your most recent activity {customer['last_txn_days']} "
            "days ago — we're here whenever you need us."
        )
        st.write(msg)
        with st.expander("Prompt the adapter would send"):
            st.text(prompt)
    else:
        try:
            res = converse(prompt, model_id=model_id, region=region)
        except Exception as e:  # noqa: BLE001
            st.error(f"Bedrock call failed: {e}")
            st.info("Turn on 'Simulate' to run offline, or check access/credentials.")
            st.stop()
        st.caption(f"{res.latency_s:.2f}s · in {res.input_tokens} tok · out {res.output_tokens} tok")
        st.write(res.text)

    st.success(
        "Adapter flow complete: authenticate → transform (COBOL→JSON) → Bedrock. "
        "This is the API-facade + transformation pattern from Question 1."
    )
