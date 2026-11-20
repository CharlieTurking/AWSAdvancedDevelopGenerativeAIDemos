"""Act 1 — Naive baseline.

Send the raw business question as a single prompt. The point is to show the
"Before (Traditional approach)" from slide 18: an answer with no structure,
no stakeholder awareness, and nothing actionable.
"""

from __future__ import annotations

import streamlit as st

import scenario
from shared import shared_sidebar
from bedrock_client import BedrockError, converse, converse_stream

st.set_page_config(page_title="Act 1 · Naive Baseline", page_icon="1️⃣", layout="wide")
shared_sidebar()

st.title("1️⃣ Act 1 — The naive baseline")
st.caption("Slide 18 · *Before (Traditional approach): \"The answer is 42\"*")

st.markdown(
    "We hand the model the raw question with no structure. Expect a generic "
    "\"it depends, here are some pros and cons\" answer — the problem the rest "
    "of the demo fixes."
)

question = st.session_state.question
st.markdown("#### The prompt we send")
prompt = scenario.naive_prompt(question)
st.code(prompt, language="text")

if st.button("Run naive prompt", type="primary"):
    try:
        st.markdown("#### Response")
        if st.session_state.stream:
            st.write_stream(
                converse_stream(
                    region=st.session_state.region,
                    model_id=st.session_state.model_id,
                    prompt=prompt,
                    temperature=st.session_state.temperature,
                    max_tokens=st.session_state.max_tokens,
                )
            )
        else:
            with st.spinner("Calling Bedrock..."):
                text = converse(
                    region=st.session_state.region,
                    model_id=st.session_state.model_id,
                    prompt=prompt,
                    temperature=st.session_state.temperature,
                    max_tokens=st.session_state.max_tokens,
                )
            st.markdown(text)
    except BedrockError as exc:
        st.error(str(exc))

st.divider()
st.markdown(
    "**Talking point:** no audience targeting, no cost/risk breakdown, not "
    "actionable. Next page: give it structure. 👉 *Act 2 · Dimensional "
    "Decomposition*"
)
