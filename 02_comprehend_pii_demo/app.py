# Amazon Comprehend demo: PII detection, PII masking and bias signals.
# This file only sets up navigation; each page lives in pages/ and the
# Comprehend calls live in comprehend_utils.py.
import streamlit as st

st.set_page_config(page_title="Amazon Comprehend Demo", layout="wide")

pages = [
    st.Page("pages/1_PII_Detection.py", title="PII detection", icon="🔍", default=True),
    st.Page("pages/2_Mask_PII.py", title="Mask PII", icon="🙈"),
    st.Page("pages/3_Bias_Spotting.py", title="Spot possible bias", icon="⚖️"),
]

st.navigation(pages).run()
