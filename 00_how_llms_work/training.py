# A tiny next-word model trained from scratch with plain numpy (no Streamlit, no downloads).
# Embedding table -> join the last 4 word vectors -> hidden layer (tanh) -> softmax over the vocabulary.
import re
import time
from pathlib import Path
import numpy as np
DATA = Path(__file__).resolve().parent / "data"
CTX = 4
DEMO_PROMPT = "the server went down because the database ran out of"
def load_text():
    return (DATA / "training_text.txt").read_text()
def tokenize_words(text):
    return re.findall(r"[a-z']+|\.", text.lower())
def build_vocab(words):
    """Index 0 is <unk> (any word the toy never saw). Most frequent words come first."""
    counts = {}
    for w in words:
        counts[w] = counts.get(w, 0) + 1
    vocab = ["<unk>"] + sorted(counts, key=lambda w: (-counts[w], w))
    return vocab, {w: i for i, w in enumerate(vocab)}
def encode(words, w2i):
    return [w2i.get(w, 0) for w in words]
def make_examples(ids, ctx=CTX):
    """Every window of `ctx` words (X) paired with the word that followed it (y)."""
    X = np.array([ids[i:i + ctx] for i in range(len(ids) - ctx)])
    y = np.array(ids[ctx:])
    return X, y
def init_params(V, ctx=CTX, dim=16, hidden=64, seed=0):
    rng = np.random.default_rng(seed)
    return {
        "E": rng.normal(0, 0.5, (V, dim)),
        "W1": rng.normal(0, 1 / np.sqrt(ctx * dim), (ctx * dim, hidden)),
        "b1": np.zeros(hidden),
        "W2": rng.normal(0, 0.05, (hidden, V)),
        "b2": np.zeros(V),
    }
def count_params(params):
    return int(sum(p.size for p in params.values()))
def softmax(z):
    z = z - z.max(axis=-1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=-1, keepdims=True)
def forward(params, X):
    """Context word ids -> one score (logit) per vocabulary word. Also returns values the backward pass needs."""
    a = params["E"][X].reshape(len(X), -1)       # look up and join the vectors
    h = np.tanh(a @ params["W1"] + params["b1"])  # hidden layer
    logits = np.clip(h @ params["W2"] + params["b2"], -50, 50)
    return logits, (a, h)
def loss_and_grads(params, X, y):
    """Cross-entropy loss (average surprise at the true next word) and its gradient for every weight."""
    logits, (a, h) = forward(params, X)
    p = softmax(logits)
    n = len(y)
    loss = float(-np.log(p[np.arange(n), y] + 1e-12).mean())
    dl = p.copy()
    dl[np.arange(n), y] -= 1
    dl /= n
    dh = dl @ params["W2"].T
    dz = dh * (1 - h ** 2)
    da = dz @ params["W1"].T
    dE = np.zeros_like(params["E"])
    np.add.at(dE, X.reshape(-1), da.reshape(-1, params["E"].shape[1]))
    grads = {"E": dE, "W1": a.T @ dz, "b1": dz.sum(0), "W2": h.T @ dl, "b2": dl.sum(0)}
    return loss, grads
def train(lr, epochs, seed=0, n_snapshots=40):
    """Full-batch gradient descent. Each epoch: predict, measure the error, nudge every weight."""
    t0 = time.perf_counter()
    words = tokenize_words(load_text())
    vocab, w2i = build_vocab(words)
    X, y = make_examples(encode(words, w2i))
    params = init_params(len(vocab), seed=seed)
    steps = sorted(set(np.linspace(0, epochs, min(n_snapshots, epochs + 1)).round().astype(int).tolist()))
    snapshots, losses = [], []
    for step in range(epochs + 1):
        loss, grads = loss_and_grads(params, X, y)
        losses.append(loss)
        if step in steps:
            snapshots.append({k: v.copy() for k, v in params.items()})
        if step < epochs:
            for k in params:
                params[k] -= lr * grads[k]
    return {
        "losses": np.nan_to_num(np.array(losses), nan=50.0, posinf=50.0),
        "steps": steps,
        "snapshots": snapshots,
        "vocab": vocab,
        "n_params": count_params(params),
        "n_examples": len(y),
        "n_words": len(words),
        "seconds": time.perf_counter() - t0,
        "baseline": float(np.log(len(vocab))),
    }
def predict_top(params, context_words, vocab, w2i, k=5):
    """Top-k next words for the last 4 words of a prompt. Unknown words become <unk>."""
    ids = encode([w.lower() for w in context_words], w2i)[-CTX:]
    ids = [0] * (CTX - len(ids)) + ids
    logits, _ = forward(params, np.array([ids]))
    p = softmax(logits)[0]
    order = np.argsort(-p)[:k]
    return [(vocab[i], float(p[i])) for i in order]
def embedding_xy(snapshots, vocab=None):
    """2D picture of the embedding table. PCA is fitted on the final snapshot and applied to all, so frames share axes."""
    final = snapshots[-1]["E"]
    mean = final.mean(axis=0)
    _, _, vt = np.linalg.svd(final - mean, full_matrices=False)
    return [(s["E"] - mean) @ vt[:2].T for s in snapshots]
