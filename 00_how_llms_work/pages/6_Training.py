# Page 6: where the numbers come from. A tiny next-word model learns in front of you (no download needed).
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import train_plots
import training
import ui
LRS = [0.01, 0.03, 0.1, 0.3, 1, 3, 10, 30, 100]
st.title("6. Training: billions of guesses, slowly less wrong")
st.caption(
    "Nobody typed in the numbers inside a model. They start random, and training repeats one loop: guess the next word, "
    "measure how wrong the guess was, nudge every weight a tiny step in the direction that would have been less wrong. "
    "Below, a real (but tiny) model does exactly that."
)
st.info(
    "Scale check. This toy has about **11 thousand** weights, learns from **352 words** and trains in about a second on a CPU. "
    "GPT-2 small has 124 million weights. Frontier models have hundreds of billions, learn from trillions of tokens and train "
    "for weeks on thousands of GPUs. The loop is the same. The toy predicts whole words with a small feed-forward network; "
    "real models predict sub-word tokens with a transformer."
)
st.subheader("Train it")
c1, c2, c3 = st.columns(3)
lr = c1.select_slider("Learning rate (size of each nudge)", options=LRS, value=1, key="train_lr")
epochs = c2.slider("Epochs (passes over the text)", 50, 1000, 300, step=50, key="train_epochs")
seed = int(c3.number_input("Random seed", 0, 9999, 0, step=1, key="train_seed"))
st.caption("Too low: it crawls and has barely learned when you stop. Too high: the nudges overshoot, the loss bounces around or stays high.")
@st.cache_data(show_spinner="Training ...")
def run_training(lr, epochs, seed):
    return training.train(lr, epochs, seed)
run = run_training(lr, epochs, seed)
L = run["losses"]
m1, m2, m3, m4 = st.columns(4)
m1.metric("Loss at the start", f"{L[0]:.2f}")
m2.metric("Loss at the end", f"{L[-1]:.2f}")
m3.metric("Weights in this model", f"{run['n_params']:,}")
m4.metric("Training time", f"{run['seconds']:.1f} s")
st.caption(
    f"**Loss is one number that says how wrong the model's guesses are.** Lower is better. "
    f"Knowing nothing and guessing at random among {len(run['vocab'])} words scores about {run['baseline']:.2f}. "
    "Press Play to watch it fall as the model learns."
)
with st.expander("What does 'average surprise, in nats' mean?", expanded=True):
    st.markdown(
        f"""
Training is a quiz. For every spot in the training text, the model sees the words so far and gives a probability to
every word in its vocabulary. We then look at **the probability it gave to the word that really came next**.

- **Surprise** is how shocked the model is by the true word. If it gave the real word a high probability, it is
  barely surprised (a low number). If it gave it a tiny probability, it is very surprised (a high number).
  The maths is `surprise = -ln(probability given to the true word)`.
- **Average** means we do this for every spot in the text and take the mean. That mean is the loss.
- **Nats** is just the unit, the way metres or miles are for distance. It is used because the maths uses the natural
  logarithm (`ln`). (With a base-2 logarithm the unit would be called bits.) You do not need to calculate in nats, only to know that a lower number is better.

| Probability the model gave the true word | Surprise (loss) | In words |
|---|---|---|
| 1 in {len(run['vocab'])} (about {100 / len(run['vocab']):.1f}%), a random guess | {run['baseline']:.2f} | Clueless. This is the starting line |
| 10% | 2.30 | Some idea |
| 50% | 0.69 | Fairly sure |
| 90% | 0.11 | Confident and right |
| 100% | 0.00 | Perfect |

**So the start of the curve (about {run['baseline']:.2f}) is the model guessing at random, and the end is it
giving the true next word a high probability.** Each training step nudges the weights in the direction that lowers this
number, which is why the line falls.

Two honest caveats. First, this loss is measured on the same short text the model trains on, so a very low value
partly means it has *memorised* that text. Real models are also judged on text they have never seen. Second,
loss measures the probability of the true word, not whether the output reads well, but for a language model the two are closely linked, and
this single number is the thing training is built to push down.
        """
    )
st.plotly_chart(train_plots.loss_figure(L, run["baseline"]), width="stretch", key="train_loss")
st.subheader("Compare learning rates")
cmp_lrs = sorted({LRS[0], lr, LRS[-3]})
cmp = go.Figure()
for v in cmp_lrs:
    cmp.add_trace(go.Scatter(y=run_training(v, epochs, seed)["losses"], mode="lines", name=f"learning rate {v:g}"))
cmp.update_layout(height=340, margin=dict(t=10), xaxis_title="epoch", yaxis_title="loss", legend=dict(orientation="h"))
st.plotly_chart(cmp, width="stretch", key="train_cmp")
st.caption("Same seed and epochs, only the learning rate differs. The lowest rate is still near the start when it stops. Try 10 or higher for the bouncing.")
st.divider()
st.subheader("What does it predict?")
st.caption(
    "The toy only knows its own 352 words (83 distinct words, including the full stop). Words it has never seen count as '<unk>', "
    "and only the last 4 words of the prompt are used. It can repeat patterns from its tiny text, nothing more."
)
prompt = ui.sentence_input("training")
words = training.tokenize_words(prompt)
_, w2i = training.build_vocab(training.tokenize_words(training.load_text()))
unknown = sorted({w for w in words if w not in w2i})
if unknown:
    st.warning("Not in the toy's vocabulary (treated as '<unk>'): " + ", ".join(unknown))
if not words:
    st.info("Type a sentence above.")
else:
    n = len(run["steps"])
    picks = [("Before training", 0), ("Part way", n // 3), ("End of training", n - 1)]
    panels = [(f"{name} (epoch {run['steps'][i]})", training.predict_top(run["snapshots"][i], words, run["vocab"], w2i)) for name, i in picks]
    st.plotly_chart(train_plots.predictions_figure(panels), width="stretch", key="train_pred")
    st.caption("Top 5 next words for the end of your sentence. Before training the 83 words are roughly equally likely: gibberish.")
    step = st.select_slider("Look at any other moment in training (epoch)", options=run["steps"], value=run["steps"][-1], key="train_step")
    top = training.predict_top(run["snapshots"][run["steps"].index(step)], words, run["vocab"], w2i)
    st.dataframe(pd.DataFrame(top, columns=["word", "probability"]).style.format({"probability": "{:.1%}"}), hide_index=True)
st.divider()
st.subheader("The word vectors, learned")
st.caption(
    "Each word's 16-number embedding starts random. This picture squashes the 16 numbers to 2 (PCA, fitted on the final weights so every frame "
    "shares the same axes) and shows the 25 most common words. Press Play. Page 2's vectors were learned the same way, just at a far larger scale."
)
xy = training.embedding_xy(run["snapshots"])
st.plotly_chart(train_plots.embedding_figure(xy, run["vocab"], run["steps"], range(1, 26)), width="stretch", key="train_emb")
st.caption(
    "Be careful reading it: the tiny model has little reason to arrange words by meaning. In a check on three seeds, groups such as "
    "server / database / service barely moved closer together. Real embedding tables, trained on trillions of tokens, organise much more."
)
st.markdown("**Honest caveats**")
st.markdown(
    """
- The toy memorises its text. It will give confident nonsense for anything outside it. This shows the training loop, not generalisation.
- Loss falling does not mean the model is *right*, only that its guesses on this text got less surprised.
- Real LLMs use sub-word tokens, a transformer and trillions of tokens, and add steps after this one (fine-tuning on instructions, preference tuning).
"""
)
ui.code_expander("the whole training loop", training.forward, training.loss_and_grads, training.train)
ui.presenter_notes(
    """
- Ask: "who decided the numbers inside the model?" Nobody. They start random.
- Press Play on the loss chart. Say the loop out loud: predict, measure error, nudge the weights, repeat. Point at the dashed line: that is random guessing.
- Slide the learning rate down (crawls) and up to 10 or more (bounces or stays high). Real training runs spend a lot of effort choosing this.
- Show the three prediction panels. Before: gibberish, every word about 1 in 83. After: `memory` on top, with `disk` and `connections` because the text has all three.
- The word picture: be honest that this tiny model does not cluster by meaning much. Point back to page 2: those vectors were learned the same way, with vastly more data.
- Scale numbers: about 11 thousand weights here, 124 million in GPT-2 small, hundreds of billions in frontier models; seconds vs weeks; 352 words vs trillions of tokens.
- Close: the same loop with a transformer and trillions of tokens is pre-training. This is where the numbers on pages 2 to 5 came from.
"""
)
