# Page 1: find PII in text using Amazon Comprehend
import json

import streamlit as st
from botocore.exceptions import BotoCoreError, ClientError

from comprehend_utils import detect_pii, get_comprehend_client, show_code, sidebar

st.title("Real-time PII Detection with Amazon Comprehend")

region, language_code = sidebar()

st.caption(
    "Comprehend's `DetectPiiEntities` API returns each PII entity's type, confidence "
    "score and character offsets. It does not change the text (see the next page for masking)."
)
show_code(get_comprehend_client, detect_pii)

# --- Main input area ---
st.subheader("Input text")

text = st.text_area(
    "Type or paste text containing possible PII",
    height=200,
    placeholder="Example: My name is John Smith and my phone number is 555-123-4567.",
)

auto_run = st.checkbox("Detect PII in real time (on every change)", value=True)
run_button = st.button("Detect PII now")


def render_pii_results(response):
    entities = response.get("Entities", [])
    if not entities:
        st.success("No PII entities detected.")
        return

    st.subheader("Detected PII entities")
    for e in entities:
        st.markdown(
            f"- **Type:** `{e.get('Type')}`  "
            f"**Score:** {e.get('Score'):.3f}  "
            f"**Offset:** {e.get('BeginOffset')}–{e.get('EndOffset')}"
        )

    st.subheader("Raw response (JSON)")
    st.code(json.dumps(response, indent=2), language="json")


def should_run_detection(text_value: str) -> bool:
    if not text_value or not text_value.strip():
        return False
    if auto_run:
        return True
    return run_button


# --- Real-time / on-demand detection ---
if should_run_detection(text):
    try:
        st.info("Calling Amazon Comprehend for PII detection...")
        resp = detect_pii(text, region, language_code)
        render_pii_results(resp)
    except (BotoCoreError, ClientError) as e:
        st.error(f"Comprehend call failed: {e}")
    except Exception as e:
        st.error(f"Unexpected error: {e}")
