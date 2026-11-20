"""Act 2 — Dimensional decomposition.

Split the single question into Technical / Business / Risk dimensions, exactly
as slide 19 ("Complex problem decomposition techniques") lays out. First the
model produces the decomposition; then we fire one focused prompt per
dimension so each answer is scoped to a specific stakeholder.
"""

from __future__ import annotations

import streamlit as st

import scenario
from shared import shared_sidebar
from bedrock_client import BedrockError, converse

st.set_page_config(
    page_title="Act 2 · Dimensional Decomposition", page_icon="2️⃣", layout="wide"
)
shared_sidebar()

st.title("2️⃣ Act 2 — Decompose across dimensions")
st.caption("Slide 19 · *Complex problem decomposition techniques*")

question = st.session_state.question

# Show the matrix straight from the deck so the mapping is explicit.
st.markdown("#### The decomposition matrix (slide 19)")
st.table(
    {
        "Dimension": list(scenario.DIMENSIONS.keys()),
        "Primary focus": [d["focus"] for d in scenario.DIMENSIONS.values()],
        "Key sub-questions": [
            ", ".join(d["sub_questions"]) for d in scenario.DIMENSIONS.values()
        ],
        "Stakeholder": [d["stakeholder"] for d in scenario.DIMENSIONS.values()],
    }
)

st.divider()

# --- Step 2a: ask the model to produce the decomposition -------------------
st.markdown("#### Step A — Ask the model to decompose (not answer)")
decomp_prompt = scenario.decomposition_prompt(question)
with st.expander("Prompt sent"):
    st.code(decomp_prompt, language="text")

if st.button("Generate decomposition", type="primary"):
    try:
        with st.spinner("Decomposing..."):
            text = converse(
                region=st.session_state.region,
                model_id=st.session_state.model_id,
                prompt=decomp_prompt,
                system=scenario.DECOMPOSITION_SYSTEM,
                temperature=st.session_state.temperature,
                max_tokens=st.session_state.max_tokens,
            )
        st.session_state["decomposition_text"] = text
    except BedrockError as exc:
        st.error(str(exc))

if "decomposition_text" in st.session_state:
    st.markdown(st.session_state["decomposition_text"])

st.divider()

# --- Step 2b: one scoped prompt per dimension ------------------------------
st.markdown("#### Step B — Answer each dimension in isolation")
st.caption(
    "Each dimension gets its own focused prompt, so the answer is scoped to "
    "one stakeholder instead of one generic blob."
)

cols = st.columns(3)
for col, (dim, meta) in zip(cols, scenario.DIMENSIONS.items()):
    with col:
        st.markdown(f"**{dim}**  \n*{meta['focus']} · {meta['stakeholder']}*")
        if st.button(f"Analyze {dim}", key=f"analyze_{dim}"):
            prompt = scenario.reasoning_prompt(
                question, dim, st.session_state.context
            )
            try:
                with st.spinner(f"Analyzing {dim}..."):
                    text = converse(
                        region=st.session_state.region,
                        model_id=st.session_state.model_id,
                        prompt=prompt,
                        system=scenario.REASONING_SYSTEM,
                        temperature=st.session_state.temperature,
                        max_tokens=st.session_state.max_tokens,
                    )
                st.session_state.setdefault("dimension_outputs", {})[dim] = text
            except BedrockError as exc:
                st.error(str(exc))

# Render whatever dimensions have been produced so far.
outputs = st.session_state.get("dimension_outputs", {})
for dim in scenario.DIMENSIONS:
    if dim in outputs:
        with st.expander(f"{dim} analysis", expanded=False):
            st.markdown(outputs[dim])

if outputs:
    st.success(
        f"{len(outputs)} of 3 dimensions analyzed. These feed the synthesis on "
        "Act 3. 👉 *Act 3 · Step-by-Step Reasoning*"
    )
