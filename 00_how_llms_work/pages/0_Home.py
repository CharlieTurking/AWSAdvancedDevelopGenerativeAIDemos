# Home: the whole pipeline and common misconceptions
import streamlit as st

import ui

ui.init_state()
st.title("How LLMs work")
st.caption(
    "Start of the course. Everything runs on this machine with small real models. "
    "No AWS account or internet is needed once the models are downloaded."
)

st.subheader("The whole pipeline")
steps = [
    ("Tokenize", "text becomes IDs, one number per piece"),
    ("Embed", "each ID becomes a vector"),
    ("Transformer", "attention mixes the context into every vector"),
    ("Predict", "a probability for every token in the vocabulary"),
    ("Repeat", "pick one, append it, go again"),
]
cards = "".join(
    f'<div style="flex:1;min-width:150px;background:#eef3fb;color:#111;border:1px solid #9bb3d6;'
    f'border-radius:8px;padding:10px;text-align:center;"><div style="font-size:1.5rem;font-weight:700;color:#2f5fa8;">{i + 1}</div>'
    f'<b>{t}</b><br><small>{d}</small></div>'
    + ('<div style="align-self:center;font-size:1.4rem;">&rarr;</div>' if i < len(steps) - 1 else "")
    for i, (t, d) in enumerate(steps)
)
st.markdown(f'<div style="display:flex;flex-wrap:wrap;gap:4px;">{cards}</div>', unsafe_allow_html=True)
st.markdown(
    '<div style="margin-top:8px;background:#fff4e0;color:#111;border:1px solid #e0b46c;border-radius:8px;padding:10px;text-align:center;">'
    "<b>Training: how the weights got there.</b> Billions of guesses, slowly less wrong. "
    "The embedding table and the transformer weights in steps 2 and 3 were learned this way.</div>",
    unsafe_allow_html=True,
)
st.write("")
st.markdown(
    "The last step feeds back into the first: the chosen token is added to the text and the "
    "whole loop runs again. A reply is that loop run many times. "
    "Vector search (page 3) uses the same embedding idea, with a separate sentence-embedding model."
)
st.subheader("Walk through it")
links = [
    ("pages/1_Tokenize.py", "1. Tokenize", "🔤", "How text becomes IDs, and why tokens are not words."),
    ("pages/2_Embed.py", "2. Embed", "📐", "How each ID becomes a vector: coordinates in meaning-space."),
    ("pages/3_Vector_Search.py", "3. Vector search", "🔎", "Why 'outage' is found when you search 'server is down'."),
    ("pages/4_Attention.py", "4. Attention", "🔦", "Which earlier tokens each token looks at, from real GPT-2 weights."),
    ("pages/5_Generate.py", "5. Generate", "✍", "Real next-token probabilities from GPT-2, one step at a time."),
    ("pages/6_Training.py", "6. Training", "🏋", "A tiny model learning next-word prediction in front of you."),
]
for row in (links[:3], links[3:]):
    for col, (path, label, icon, blurb) in zip(st.columns(3), row):
        with col:
            st.page_link(path, label=label, icon=icon)
            st.caption(blurb)
st.subheader("Common misconceptions")
st.markdown(
    """
- **"It looks up the answer."** No. It predicts the next token from probabilities, one token at a time.
- **"It stores the text it was trained on."** Not as documents. Training squeezes patterns into numeric weights.
  It can still reproduce some passages it saw many times, but there is no database to query.
- **"It understands like a person."** It is very good at statistical patterns in text. Whether that is understanding is debated; do not assume it.
- **"The same prompt gives the same answer."** Not when sampling is on. The next token is drawn from a distribution (see the Generate page).
- **"It learns from my chat."** The weights are frozen. Anything it 'remembers' is the text sent in the current context window.
- **"Hallucination is a bug."** It is the normal mechanism: the model picks a likely-sounding token whether or not it is true.
- **"Attention is how the model explains itself."** Attention weights show where information can flow between tokens. They are not a reliable account of why the model answered as it did (see the Attention page).
- **"Embeddings and generation are the same thing."** Embedding models turn text into vectors for search. Generative models turn text into next-token probabilities. They are separate models that share the same idea.
"""
)

st.info(
    "First run: the demo needs two small models, **GPT-2** (~500 MB) and **all-MiniLM-L6-v2** (~90 MB). "
    "Each page offers a download button if its model is missing. After that nothing leaves this machine."
)
st.caption(
    "GPT-2 is a 2019 model with 124M parameters, far smaller than today's LLMs. "
    "It makes the same kind of next-token step, so it shows the mechanism honestly."
)
ui.presenter_notes(
    """
- Ask the room first: "what happens between pressing Enter and the first word appearing?" Collect answers, then show the pipeline.
- Walk the five cards left to right once, then point at "Repeat". Then the orange band: training is how the weights in cards 2 and 3 got their values.
- Everything on the later pages is one card in this row. Page 3 (vector search) is the side road that uses embeddings for retrieval.
- Spend the most time on the misconceptions. Ask for a show of hands on each.
- Be precise on storage: weights are a lossy compression of training data, so some text can be recovered. It is not a document store.
- Run each page once before class so the models are cached.
"""
)
