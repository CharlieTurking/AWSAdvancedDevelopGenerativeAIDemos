# Page 2: mask the PII that Amazon Comprehend finds
import pandas as pd
import streamlit as st
from botocore.exceptions import BotoCoreError, ClientError

from comprehend_utils import detect_pii, load_pii_samples, mask_text, show_code, sidebar

st.title("Mask PII with Amazon Comprehend")

region, language_code = sidebar()

st.caption(
    "Comprehend finds *where* the PII is (type, score, start and end offset). The masking "
    "itself is a few lines of Python that replace those spans, so you decide how it looks."
)
show_code(detect_pii, mask_text)
st.caption(
    "Comprehend can also redact for you with an asynchronous batch job "
    "(`start_pii_entities_detection_job` with `Mode='ONLY_REDACTION'`) that reads from and "
    "writes to S3. This page uses the synchronous call and masks locally so the result is instant."
)

# --- Input ---
samples = load_pii_samples()
choice = st.selectbox("Sample text", ["(write your own)"] + list(samples))
text = st.text_area(
    "Text to mask",
    value=samples.get(choice, ""),
    height=220,
    key=f"mask_input_{choice}",   # new key per sample so the box refreshes when you switch
)

if st.button("Detect PII", type="primary", disabled=not text.strip()):
    try:
        with st.spinner("Calling Amazon Comprehend..."):
            response = detect_pii(text, region, language_code)
        st.session_state["mask_result"] = {"text": text, "entities": response["Entities"]}
    except (BotoCoreError, ClientError) as e:
        st.error(f"Comprehend call failed: {e}")
    except Exception as e:
        st.error(f"Unexpected error: {e}")

# --- Result: tweak the masking without calling Comprehend again ---
result = st.session_state.get("mask_result")
if result:
    source_text, entities = result["text"], result["entities"]

    if not entities:
        st.success("No PII entities detected, so there is nothing to mask.")
        st.stop()

    st.subheader("Masking options")
    c1, c2, c3 = st.columns(3)
    style_label = c1.radio(
        "Replace PII with",
        ["Entity type, e.g. [EMAIL]", "Mask characters, e.g. ******", "[REDACTED]"],
    )
    style = {"E": "type", "M": "mask", "[": "redacted"}[style_label[0]]
    mask_char = c1.text_input("Mask character", value="*", max_chars=1, disabled=style != "mask") or "*"
    min_score = c2.slider(
        "Minimum confidence", 0.0, 1.0, 0.5, 0.05,
        help="Entities scoring below this are left as they are. Try raising it above 0.7.",
    )
    detected_types = sorted({e["Type"] for e in entities})
    only_types = set(c3.multiselect("PII types to mask", detected_types, default=detected_types))

    masked, n_masked = mask_text(
        source_text, entities, style=style, mask_char=mask_char,
        min_score=min_score, only_types=only_types,
    )

    left, right = st.columns(2)
    left.subheader("Original")
    left.code(source_text, language=None, wrap_lines=True)
    right.subheader(f"Masked ({n_masked} of {len(entities)} entities)")
    right.code(masked, language=None, wrap_lines=True)

    st.subheader("What Comprehend found")
    table = pd.DataFrame(
        [
            {
                "Type": e["Type"],
                "Text": source_text[e["BeginOffset"]:e["EndOffset"]],
                "Score": round(e["Score"], 3),
                "Masked": e["Score"] >= min_score and e["Type"] in only_types,
            }
            for e in sorted(entities, key=lambda e: e["BeginOffset"])
        ]
    )
    st.dataframe(table, hide_index=True)
