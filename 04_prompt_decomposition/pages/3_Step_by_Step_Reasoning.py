"""Act 3 — Step-by-step reasoning + synthesis.

Run a single dimension through the exact 6-step chain-of-thought structure
from slide 18 ("After (Chain-of-Thought)" / the Region X example), streaming
the reasoning trail live. Then synthesize all available dimension outputs into
one executive recommendation.
"""

from __future__ import annotations

import streamlit as st

import scenario
from shared import shared_sidebar
from bedrock_client import BedrockError, converse, converse_stream

st.set_page_config(
    page_title="Act 3 · Step-by-Step Reasoning", page_icon="3️⃣", layout="wide"
)
shared_sidebar()

st.title("3️⃣ Act 3 — Step-by-step reasoning")
st.caption("Slide 18 · *After (Chain-of-Thought)* — the 6-step reasoning trail")

question = st.session_state.question

# Show the 6-step structure from the slide.
st.markdown("#### The reasoning structure (slide 18)")
st.markdown(
    "  →  ".join(f"**{i}. {s}**" for i, s in enumerate(scenario.REASONING_STEPS, 1))
)

st.divider()

# --- Run reasoning for a chosen dimension, streaming -----------------------
st.markdown("#### Reason through one dimension")
dimension = st.radio(
    "Dimension", list(scenario.DIMENSIONS.keys()), horizontal=True
)
meta = scenario.DIMENSIONS[dimension]
st.caption(f"Focus: {meta['focus']} · Stakeholder: {meta['stakeholder']}")

prompt = scenario.reasoning_prompt(question, dimension, st.session_state.context)
with st.expander("Prompt sent"):
    st.code(prompt, language="text")

if st.button(f"Run {dimension} reasoning", type="primary"):
    try:
        st.markdown(f"#### {dimension} reasoning trail")
        if st.session_state.stream:
            text = st.write_stream(
                converse_stream(
                    region=st.session_state.region,
                    model_id=st.session_state.model_id,
                    prompt=prompt,
                    system=scenario.REASONING_SYSTEM,
                    temperature=st.session_state.temperature,
                    max_tokens=st.session_state.max_tokens,
                )
            )
        else:
            with st.spinner("Reasoning..."):
                text = converse(
                    region=st.session_state.region,
                    model_id=st.session_state.model_id,
                    prompt=prompt,
                    system=scenario.REASONING_SYSTEM,
                    temperature=st.session_state.temperature,
                    max_tokens=st.session_state.max_tokens,
                )
            st.markdown(text)
        # Persist so synthesis can use it.
        st.session_state.setdefault("dimension_outputs", {})[dimension] = text
    except BedrockError as exc:
        st.error(str(exc))

st.divider()

# --- Synthesis across all available dimensions -----------------------------
st.markdown("#### Synthesize into an executive recommendation")
outputs = st.session_state.get("dimension_outputs", {})
done = list(outputs.keys())

if not outputs:
    st.info(
        "Run reasoning for one or more dimensions above (or on Act 2) first. "
        "Synthesis combines whatever is available.",
        icon="ℹ️",
    )
else:
    st.caption(f"Dimensions ready to synthesize: {', '.join(done)}")
    if st.button("Synthesize recommendation"):
        syn_prompt = scenario.synthesis_prompt(question, outputs)
        try:
            st.markdown("#### Executive recommendation")
            if st.session_state.stream:
                st.write_stream(
                    converse_stream(
                        region=st.session_state.region,
                        model_id=st.session_state.model_id,
                        prompt=syn_prompt,
                        temperature=st.session_state.temperature,
                        max_tokens=st.session_state.max_tokens,
                    )
                )
            else:
                with st.spinner("Synthesizing..."):
                    text = converse(
                        region=st.session_state.region,
                        model_id=st.session_state.model_id,
                        prompt=syn_prompt,
                        temperature=st.session_state.temperature,
                        max_tokens=st.session_state.max_tokens,
                    )
                st.markdown(text)
        except BedrockError as exc:
            st.error(str(exc))
