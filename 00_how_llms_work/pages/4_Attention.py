# Page 4: which earlier tokens does each token look at? Real GPT-2 attention weights.
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import core
import models
import ui
PRESETS = {
    "Server rebooted (inspect 'it')": "The server rebooted because it ran out of memory",
    "Default sentence": ui.DEFAULT_SENTENCE,
}
st.title("4. Attention: how each token looks at the others")
st.caption(
    "After the embedding step every token is a vector on its own. Attention is the step where each token's "
    "vector is rebuilt as a weighted mix of the vectors of the tokens it is allowed to look at. "
    "The weights below are the real numbers from GPT-2 small, not a drawing."
)
def set_sentence(value):
    st.session_state["sentence"] = value
    st.session_state["sentence_widget_attention"] = value
ui.init_state()
pc = st.columns(len(PRESETS) + 2)
for col, (label, value) in zip(pc, PRESETS.items()):
    col.button(label, on_click=set_sentence, args=(value,), key=f"att_preset_{label}")
text = ui.sentence_input("attention")
gpt2, gtok = ui.require_model(models.load_gpt2, "GPT-2", models.GPT2_NAME, "500 MB")
@st.cache_data(show_spinner="Running GPT-2 ...")
def run_attention(text, _model, _tok):
    return core.attention_weights(text, _model, _tok)
res = run_attention(text, gpt2, gtok)
tokens, W = res["tokens"], res["weights"]
if not tokens:
    st.info("Type a sentence above.")
    st.stop()
if res["truncated"]:
    st.warning("Only the first 40 tokens are shown so the heatmap stays readable (this is this page's limit, not GPT-2's).")
T = len(tokens)
if T < 2:
    st.caption("One token can only look at itself. Add more words to see something interesting.")
n_layers, n_heads = W.shape[0], W.shape[1]
prev_scores, first_scores = core.head_pattern_scores(W) if T > 1 else (np.zeros(W.shape[:2]), np.zeros(W.shape[:2]))
(pl, ph, ps), (fl, fh, fs) = core.top_heads(prev_scores, 1)[0], core.top_heads(first_scores, 1)[0]
def jump(layer, head):
    st.session_state["att_layer"], st.session_state["att_head"], st.session_state["att_avg"] = layer, head, False
st.subheader("Pick what to look at")
c1, c2, c3 = st.columns(3)
# defaults live in session state so the jump buttons can change them without a widget-default clash
st.session_state.setdefault("att_layer", 4)
st.session_state.setdefault("att_head", 11)
st.session_state.setdefault("att_avg", False)
layer = c1.slider("Layer (0 = first, 11 = last)", 0, n_layers - 1, key="att_layer")
avg = c3.toggle("Average over all 12 heads", key="att_avg")
head = c2.slider("Head (0-11)", 0, n_heads - 1, key="att_head", disabled=avg)
if T > 1:
    j1, j2, _ = st.columns([1, 1, 2])
    j1.button(f"Jump to the most 'previous-token' head (L{pl} H{ph}, {ps:.2f})", on_click=jump, args=(pl, ph), key="att_jump_prev")
    j2.button(f"Jump to the most 'first-token' head (L{fl} H{fh}, {fs:.2f})", on_click=jump, args=(fl, fh), key="att_jump_first")
    st.caption("Layers and heads are numbered from 0. The two jump buttons are computed for your sentence, by scoring all 144 heads.")
default_idx = tokens.index(" it") if " it" in tokens else T - 1
tok_key = "att_tok_" + str(abs(hash(tuple(tokens))))
sel = st.radio(
    "Token to inspect (the one doing the looking)",
    list(range(T)), index=default_idx, horizontal=True, key=tok_key,
    format_func=lambda i: f"{i}: {tokens[i].replace(' ', '·')}",
)
h = None if avg else head
row = core.attention_row(W, layer, h, sel)
mode = "average of 12 heads" if avg else f"head {head}"
who = tokens[sel].strip() or repr(tokens[sel])
st.subheader(f"Where '{who}' (position {sel}) looks: layer {layer}, {mode}")
st.markdown(ui.weighted_chips_html(tokens, row, sel), unsafe_allow_html=True)
st.caption("Darker blue = more weight. Grey tokens come later in the sentence, so a causal model such as GPT-2 cannot look at them.")
m1, m2, m3 = st.columns(3)
m1.metric("Weight on itself", f"{row[sel]:.2f}")
m2.metric("Weight on token 0", f"{row[0]:.2f}" if sel > 0 else "-")
best = int(np.argmax(row))
m3.metric("Strongest target", f"{best}: {tokens[best].strip() or repr(tokens[best])}", f"{row[best]:.2f}", delta_color="off")
labels = [f"{i}: {tokens[i].replace(' ', '·')}" for i in range(sel + 1)]
bar = px.bar(x=labels, y=row[: sel + 1], text=[f"{v:.2f}" for v in row[: sel + 1]],
             labels={"x": "token being looked at", "y": "attention weight"})
bar.update_layout(height=320, margin=dict(t=10), yaxis_range=[0, 1.05])
st.plotly_chart(bar, width="stretch", key="att_bar")
st.subheader("All tokens at once: the attention heatmap")
M = core.attention_matrix(W, layer, h).astype(float)
M[np.triu_indices(T, 1)] = np.nan
axis = [f"{i}: {t.replace(' ', '·')}" for i, t in enumerate(tokens)]
heat = go.Figure(go.Heatmap(z=M, x=axis, y=axis, colorscale="Blues", zmin=0, zmax=1, colorbar=dict(title="weight"),
                            hovertemplate="reading %{y}<br>looking at %{x}<br>weight %{z:.3f}<extra></extra>"))
heat.add_shape(type="rect", x0=-0.5, x1=T - 0.5, y0=sel - 0.5, y1=sel + 0.5, line=dict(color="#EF553B", width=3))
heat.update_layout(height=max(380, 36 * T + 140), margin=dict(t=10),
                   xaxis=dict(title="token being looked at", side="top"),
                   yaxis=dict(title="token doing the looking", autorange="reversed"))
st.plotly_chart(heat, width="stretch", key="att_heat")
st.caption(
    "Each row is one token and adds up to 1. The empty top-right corner is the 'causal mask': a token never "
    "sees the future. The red outline is the row shown above."
)
st.subheader("What you are looking at")
st.markdown(
    """
- **Causal.** GPT-2 reads left to right when it generates, so a token only attends to itself and earlier tokens. That is why the heatmap is a lower triangle.
- **144 different patterns.** GPT-2 small has 12 layers with 12 heads each, and every head learned its own pattern. Some look at the previous token, some park almost everything on the first token (a harmless 'sink', because each row must add up to 1), and many are hard to describe. Use the jump buttons to see two clean ones.
- **Why it matters.** The result of each head is a weighted mix of the other tokens' vectors. That is how context from the whole sentence ends up inside each token's vector, so ` it` is no longer just the word 'it'.
- **Averaging blurs.** The average over heads is smoother and harder to read than any single head, because the heads do different jobs.
"""
)
st.warning(
    "Honest caveat: real attention is messier than the diagrams in slides. In some heads ` it` puts weight on "
    "` server`, but most of its weight usually sits on other tokens, and that is not clean coreference. "
    "Attention weights show where information *can* flow, not why the model gave a particular answer. "
    "They are not a full explanation of its reasoning."
)
ui.code_expander("real attention weights from GPT-2", core.attention_weights, core.attention_row, core.attention_matrix, core.head_pattern_scores)
ui.presenter_notes(
    """
- Load the 'Server rebooted' preset. ` it` is selected for you. Ask the room: what does 'it' refer to? A human says the server.
- First show the **average over heads**: a smear. Then switch it off and show single heads. Different heads, different pictures.
- Click the previous-token jump button (on these sentences layer 4, head 11, weight about 1.0 on the token just before). Then the first-token button (layer 5, head 1, about 1.0 on token 0). Both were checked on four sentences, they are properties of these sentences, not laws.
- Point at the triangle: a token cannot see the future. GPT-2 has no start token here, so the first real token becomes the sink.
- 'it' to 'server': on the rebooted sentence layer 4 head 3 puts about 0.55 on ` server` and layer 6 head 0 about 0.40. Most other heads do not. So there is a signal, but it is not clean.
- Finish on the caveat: attention weights are not an explanation. Do not let the room walk away thinking 'the model looked at server, therefore it understood'.
- Link back: each head's output is a weighted mix of vectors from page 2. Link forward: page 5 turns the final vectors into next-token probabilities, page 6 shows where the weights came from.
"""
)
