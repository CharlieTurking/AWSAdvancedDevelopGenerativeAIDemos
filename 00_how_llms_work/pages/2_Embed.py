# Page 2: token IDs -> vectors, word similarity, vector arithmetic
import json
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

import core
import models
import ui

DATA = Path(__file__).resolve().parent.parent / "data"

st.title("2. Embed: every token becomes a vector")
st.caption(
    "An ID is just a label. The model looks up a list of numbers for it (a vector). "
    "Think of a vector as coordinates in a meaning-space: tokens used in similar ways end up close together."
)
text = ui.sentence_input("embed")
toks = core.tokenize(text)
if not toks:
    st.info("Type a sentence above.")
    st.stop()

gpt2, gtok = ui.require_model(models.load_gpt2, "GPT-2", models.GPT2_NAME, "500 MB")
vecs = core.token_vectors([t["id"] for t in toks], gpt2)

st.caption("Where do these numbers come from? They are learned during training, see page 6.")
st.subheader("Your tokens as vectors")
c1, c2, c3 = st.columns(3)
c1.metric("Tokens", len(toks))
c2.metric("Dimensions per vector", vecs.shape[1])
c3.metric("Numbers for this sentence", vecs.size)
st.caption(
    "These are rows of GPT-2's real input embedding table (768 numbers per token). "
    "Only the first 8 of 768 are shown below. Individual numbers have no human-readable meaning; "
    "the meaning is in the pattern across all of them."
)
labels = [f"{i}: {t['text']!r}" for i, t in enumerate(toks)]
table = pd.DataFrame(vecs[:, :8], index=labels, columns=[f"d{i}" for i in range(8)])
st.dataframe(table.style.format("{:.3f}"), width="stretch")

n_dims = st.slider("Heat-strip: how many dimensions to draw", 16, 256, 64, step=16)
fig = px.imshow(
    vecs[:, :n_dims],
    y=labels,
    color_continuous_scale="RdBu_r",
    zmin=-float(np.abs(vecs[:, :n_dims]).max()),
    zmax=float(np.abs(vecs[:, :n_dims]).max()),
    aspect="auto",
    labels={"x": "dimension", "color": "value"},
)
fig.update_layout(height=max(250, 40 * len(toks) + 100), margin=dict(t=20))
st.plotly_chart(fig, width="stretch")
with st.expander("How to read this heat-strip", expanded=True):
    st.markdown(
        f"""
**What you are looking at.** This is the raw data, drawn as a picture instead of a table.

- **Each row** is one token from your sentence. The row is that token's vector: the {vecs.shape[1]} numbers
  GPT-2 looks up for it. (You are seeing the first {n_dims} of them; the slider changes how many.)
- **Each column** is one dimension, a single number in the vector. Column 3 is the same dimension for every row.
- **Colour** is the value of that number. Red is positive, blue is negative, white is close to zero.
  The deeper the colour, the further from zero. All cells share one scale, so you can compare colours across rows.

**How to interpret it.**

1. **Rows that look different are different tokens.** Every token gets its own pattern, like a barcode. If you
   type the same token twice (try repeating a word), those rows are identical, because a token ID always looks up the same vector.
2. **There is no meaning in a single column.** Dimension 3 is not "is it a noun" or "is it technical". The meaning
   is spread across the whole row, and only appears when you compare rows with each other, which is what
   similarity search does.
3. **Do not expect obvious visual matches here.** These are GPT-2's *input* vectors. They are the starting point, before
   the model has mixed in any context, and related words (for example `server` and `database`) are only
   hard to tell apart by eye. The numbers do show a link (cosine about 0.49 for `server` and `database`, against
   0.27 for `server` and `banana`), but the pattern is faint. The next section uses a model built for comparing meaning, and the difference is clear.
4. **The numbers are learned, not designed.** Nobody chose them. They were adjusted during training until they
   helped predict the next token (see the Training page).

**What to take away.** To a model, a word is a position described by hundreds of numbers. "Similar meaning" means
"the two rows point in a similar direction", which is measured with a single number called cosine similarity.
        """
    )

st.divider()
minilm = ui.require_model(models.load_minilm, "all-MiniLM-L6-v2", models.MINILM_NAME, "90 MB")


@st.cache_resource(show_spinner="Embedding the word list ...")
def word_list_vectors(_model):
    words = json.loads((DATA / "analogy_words.json").read_text())
    return words, core.embed_texts(words, _model)


st.subheader("Closeness = similarity")
st.caption(
    "Numbers on this page below come from **all-MiniLM-L6-v2** (384 dimensions), a model built "
    "to compare meaning, not from GPT-2. Cosine similarity is 1 for the same direction, near 0 for unrelated."
)
a, b = st.columns(2)
w1 = a.text_input("Word or phrase 1", "server", key="sim1")
w2 = b.text_input("Word or phrase 2", "database", key="sim2")
if w1.strip() and w2.strip():
    v = core.embed_texts([w1, w2], minilm)
    st.metric("Cosine similarity", f"{core.cosine(v[0], v[1]):.3f}")
st.caption("Try 'server' vs 'database', then 'server' vs 'banana'.")

st.subheader("Vector arithmetic: king - man + woman")
st.markdown(
    "The famous trick: subtract the 'man' direction from 'king', add 'woman', and land near 'queen'. "
    "Below the computed vector is compared with a list of ~150 candidate words and the closest are shown. "
    "The three input words are excluded, otherwise the nearest word is often one of them."
)
words, wvecs = word_list_vectors(minilm)
presets = {
    "king - man + woman": ("king", "man", "woman"),
    "paris - france + italy": ("paris", "france", "italy"),
    "bigger - big + small": ("bigger", "big", "small"),
    "walked - walk + swim (expected 'swam')": ("walked", "walk", "swim"),
    "doctor - man + woman": ("doctor", "man", "woman"),
}
choice = st.selectbox("Example", list(presets) + ["Your own"])
if choice == "Your own":
    x, y, z = st.columns(3)
    wa, wb, wc = x.text_input("A", "king"), y.text_input("minus B", "man"), z.text_input("plus C", "woman")
else:
    wa, wb, wc = presets[choice]
if all(s.strip() for s in (wa, wb, wc)):
    ranked = core.word_arithmetic(wa, wb, wc, words, wvecs, lambda xs: core.embed_texts(xs, minilm))
    st.markdown(f"**{wa} - {wb} + {wc}** is closest to:")
    st.dataframe(
        pd.DataFrame(ranked[:5], columns=["word", "cosine"]).style.format({"cosine": "{:.3f}"}),
        hide_index=True,
    )
st.warning(
    "Honest caveat: this trick was made famous by static word vectors (word2vec, GloVe). "
    "all-MiniLM-L6-v2 is a sentence model, so single words are only an approximation, and the "
    "result is the real output, not a rigged one. It works for some analogies and fails for others "
    "(try the 'walked - walk + swim' example). 'doctor - man + woman' returning 'nurse' shows how "
    "vectors absorb the biases in their training text."
)

ui.code_expander("looking up and comparing vectors", core.token_vectors, core.embed_texts, core.cosine, core.word_arithmetic)
ui.presenter_notes(
    """
- Say it plainly: an embedding is a list of numbers, a position in a space with hundreds of dimensions.
- The heat-strip is the real data. No single column means anything; the whole row does.
- Reading it: rows are tokens, columns are dimensions, red is positive, blue is negative, white is near zero. Repeat a word in the sentence and show the two rows are identical. Say honestly that GPT-2's input vectors do not look alike for related words; similarity shows up properly in the MiniLM section below.
- Two models appear here. GPT-2's table feeds the generator. MiniLM is a separate model built for comparing meaning. Do not let the room blur them.
- King - man + woman: show it working, then show the failure example. The point is "directions in space carry meaning", not "this is a reliable feature".
- The doctor/nurse result is a good moment to discuss bias in training data.
"""
)
