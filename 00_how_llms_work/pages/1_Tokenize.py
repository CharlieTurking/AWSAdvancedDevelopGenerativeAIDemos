# Page 1: text -> tokens -> IDs
import pandas as pd
import streamlit as st

import core
import ui

st.title("1. Tokenize: text becomes numbers")
st.caption(
    "A model cannot read letters. A tokenizer cuts the text into pieces (tokens) from a fixed "
    "vocabulary and replaces each piece with its ID number. This uses the GPT-2 tokenizer (50,257 tokens)."
)
text = ui.sentence_input("tokenize")
toks = core.tokenize(text)

c1, c2, c3 = st.columns(3)
c1.metric("Characters", len(text))
c2.metric("Words (split on spaces)", len(text.split()))
c3.metric("Tokens", len(toks))

st.markdown("**Your sentence as tokens** (a dot marks a leading space, which belongs to the token):")
st.markdown(ui.chips_html([t["text"] for t in toks]), unsafe_allow_html=True)
st.markdown("**The same tokens as IDs** (this is what the model actually receives):")
st.code(str([t["id"] for t in toks]))
st.dataframe(
    pd.DataFrame(
        {
            "position": range(len(toks)),
            "token": [repr(t["text"]) for t in toks],
            "id": [t["id"] for t in toks],
            "leading space": [t["leading_space"] for t in toks],
        }
    ),
    hide_index=True,
    width="stretch",
)

st.subheader("Tokens are not words")
st.caption("Try these. Notice the leading spaces, the split rare words and the chopped-up numbers.")
rows = []
for ex in core.token_examples():
    pieces = [t["text"] for t in core.tokenize(ex)]
    rows.append((ex, pieces))
for ex, pieces in rows:
    a, b = st.columns([1, 3])
    a.code(repr(ex) if ex.startswith(" ") else ex)
    b.markdown(ui.chips_html(pieces) + f" &nbsp; **{len(pieces)}** token(s)", unsafe_allow_html=True)
st.markdown(
    "- `\" the\"` (with a space) and `\"the\"` are **different tokens** with different IDs.\n"
    "- Common words are one token. Rare words and names are split into sub-words.\n"
    "- Numbers are cut into arbitrary chunks, one reason models are shaky at arithmetic."
)

st.subheader("Why it matters")
st.markdown(
    "- **Context window:** the limit (for example 128k) is counted in tokens, not words or characters.\n"
    "- **Cost and speed:** you pay per input and output token. Different models use different tokenizers, "
    "so the same text has different token counts (here: GPT-2's)."
)

ui.code_expander("tokenizing with tiktoken", core.tokenize, core.count_tokens)
ui.presenter_notes(
    """
- Start with the default sentence and ask "how many tokens?" before revealing the number.
- Edit the sentence live: add a rare word, a hostname or a number and watch it split.
- Point out that the model never sees letters. Only the ID list goes in.
- Rule of thumb for English: about 3/4 of a word per token. Code and non-English text cost more tokens.
- Link to cost: a long prompt is billed per token, so tokens are the unit of money and of the context window.
"""
)
