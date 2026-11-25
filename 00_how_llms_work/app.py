# How LLMs work: an offline teaching demo (course opener, before Module 1).
# This file only sets up navigation; each stage lives in pages/ and the
# logic lives in core.py (models are loaded in models.py).
import streamlit as st

st.set_page_config(page_title="How LLMs work", layout="wide")
pages = [
    st.Page("pages/0_Home.py", title="The whole pipeline", icon="🧭", default=True),
    st.Page("pages/1_Tokenize.py", title="1. Tokenize", icon="🔤"),
    st.Page("pages/2_Embed.py", title="2. Embed", icon="📐"),
    st.Page("pages/3_Vector_Search.py", title="3. Vector search", icon="🔎"),
    st.Page("pages/4_Attention.py", title="4. Attention", icon="🔦"),
    st.Page("pages/5_Generate.py", title="5. Generate", icon="✍"),
    st.Page("pages/6_Training.py", title="6. Training", icon="🏋"),
]
st.navigation(pages).run()
