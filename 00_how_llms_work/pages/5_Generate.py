# Page 5: real next-token prediction with GPT-2
import plotly.express as px
import streamlit as st

import core
import models
import ui

st.title("5. Generate: one token at a time")
st.caption(
    "The model turns the text so far into a score for every token in its vocabulary (50,257 of them). "
    "Those scores become probabilities. One token is chosen, appended, and the loop repeats."
)
st.info(
    "This is GPT-2 small, a 2019 model with 124M parameters, far smaller than today's LLMs and much "
    "less accurate. The step you see here is the same mechanism."
)
base = ui.sentence_input("generate")
gpt2, gtok = ui.require_model(models.load_gpt2, "GPT-2", models.GPT2_NAME, "500 MB")

# reset generated text when the base sentence changes
if st.session_state.get("gen_base") != base:
    st.session_state["gen_base"] = base
    st.session_state["gen_text"] = base
    st.session_state["gen_added"] = []
    st.session_state["gen_last"] = None
    st.session_state["gen_runs"] = None

c1, c2, c3 = st.columns(3)
temperature = c1.slider("Temperature", 0.1, 2.0, 1.0, 0.1, help="Low: sharper, safer. High: flatter, more surprising.")
top_k = c2.slider("Top-k (0 = off)", 0, 100, 0, help="Keep only the k most likely tokens.")
top_p = c3.slider("Top-p", 0.1, 1.0, 1.0, 0.05, help="Keep the smallest set of tokens whose probability adds up to p.")
st.caption(
    "Rule of thumb: **focused** below about 0.5 (almost always the top tokens, repeatable), **balanced** around 1.0, "
    "**chaotic** above about 1.5 (the long tail starts to win; for the default prompt the top 10 hold under 20% of the probability)."
)
d1, d2 = st.columns(2)
greedy = d1.toggle("Greedy (always take the most likely token)", value=False)
seed_txt = d2.text_input("Seed (optional, repeats a sampled run)", "")
seed = int(seed_txt) if seed_txt.strip().lstrip("-").isdigit() else None

text = st.session_state["gen_text"]
dist = core.next_token_distribution(text, gpt2, gtok, temperature, top_k, top_p, n=10)

st.subheader("Text so far")
added = st.session_state["gen_added"]
shown = "".join(
    f'<span style="background:#ffe08a;color:#111;padding:1px 3px;border-radius:4px;">{ui.html.escape(p)}</span>'
    for p in added
)
st.markdown(
    f'<div style="font-size:1.3rem;">{ui.html.escape(base)}{shown}<span style="color:#888;"> ▍</span></div>',
    unsafe_allow_html=True,
)

st.subheader("What comes next? Top 10 candidates")
fig = px.bar(
    x=[t["prob"] for t in dist["tokens"]][::-1],
    y=[repr(t["text"]) for t in dist["tokens"]][::-1],
    labels={"x": "probability", "y": "candidate token"},
    text=[f"{t['prob']:.1%}" for t in dist["tokens"]][::-1],
)
fig.update_layout(height=420, margin=dict(t=10))
st.plotly_chart(fig, width="stretch")
top10 = sum(t["prob"] for t in dist["tokens"])
m1, m2, m3 = st.columns(3)
m1.metric("Probability held by these 10", f"{top10:.1%}")
m2.metric("Uncertainty (entropy, bits)", f"{dist['entropy']:.2f}")
last = st.session_state["gen_last"]
m3.metric("Last chosen token's probability", f"{last:.1%}" if last is not None else "-")
st.caption(
    "The chart shows the distribution after temperature, top-k and top-p. "
    "Everything outside the top 10 shares the rest of the probability, and the 'long tail' is huge."
)


def append(steps):
    for s in steps:
        st.session_state["gen_added"].append(s["text"])
        st.session_state["gen_last"] = s["prob"]
        st.session_state["gen_text"] += s["text"]


b1, b2, b3 = st.columns([1, 2, 1])
if b1.button("Pick next token", type="primary"):
    _, steps = core.generate_n(text, 1, gpt2, gtok, temperature, top_k, top_p, greedy, seed)
    append(steps)
    st.rerun()
n_auto = b2.slider("Tokens to auto-generate", 1, 30, 10)
if b2.button(f"Auto-generate {n_auto} tokens"):
    with st.spinner("Generating ..."):
        _, steps = core.generate_n(text, n_auto, gpt2, gtok, temperature, top_k, top_p, greedy, seed)
    append(steps)
    st.rerun()
if b3.button("Reset"):
    st.session_state["gen_base"] = None
    st.rerun()

st.subheader("Same prompt, five runs")
st.caption("With sampling on, each run draws different tokens. With greedy on, all five are identical.")
if st.button("Run the same prompt 5 times (12 tokens each)"):
    with st.spinner("Generating 5 continuations ..."):
        runs = [
            core.generate_n(base, 12, gpt2, gtok, temperature, top_k, top_p, greedy, None if seed is None else seed + i)[0]
            for i in range(5)
        ]
    st.session_state["gen_runs"] = runs
for r in st.session_state.get("gen_runs") or []:
    st.markdown(f"- {r}")

ui.code_expander("logits to probabilities to a chosen token", core.next_token_distribution, core.pick_next_token, core.generate_n)
ui.presenter_notes(
    """
- Before clicking, ask the room to guess the next word. The model's top guess is not a fact lookup, it is the most likely continuation.
- Click "Pick next token" a few times and watch the bar chart change as the text grows.
- Greedy gives one answer every time. Sampling is why a chatbot answers differently each time you ask.
- Slide temperature down (flat to sharp) and up. Show top-k and top-p cutting off the long tail.
- GPT-2 will wander and be wrong. That is expected for a 2019, 124M-parameter model. Modern LLMs do the same step with far better predictions.
- This is not retrieval: no document was looked up. The text came from the probabilities.
- The transformer step that computes these scores is on page 4 (Attention). How its weights were learned is on page 6 (Training).
"""
)
