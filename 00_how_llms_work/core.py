# Pure functions behind the demo pages (no Streamlit here, so a plain script can test them).
import re

import numpy as np
import tiktoken

_ENC = tiktoken.get_encoding("gpt2")  # the same byte-pair encoding GPT-2 uses


# ---------------------------------------------------------------- tokenization
def tokenize(text):
    """Split text into GPT-2 tokens. Returns a list of dicts."""
    out = []
    for tid in _ENC.encode(text):
        raw = _ENC.decode_single_token_bytes(tid)
        s = raw.decode("utf-8", errors="replace")
        out.append({"id": tid, "text": s, "bytes": len(raw), "leading_space": s.startswith(" ")})
    return out


def count_tokens(text):
    return len(_ENC.encode(text))


def token_examples():
    return [
        " the", "the", "unbelievability", "ChatGPT", "2024", "1234567",
        "db-prod-eu-west-1.internal.example.com", "DROP TABLE users;",
    ]


# ---------------------------------------------------------------- embeddings
def token_vectors(token_ids, gpt2_model):
    """Rows of GPT-2's input embedding matrix (wte) for the given token ids."""
    wte = gpt2_model.transformer.wte.weight.detach().cpu().numpy()
    return wte[list(token_ids)]


def embed_texts(texts, st_model):
    """Normalised sentence-transformer embeddings, shape (n, 384)."""
    return np.asarray(st_model.encode(list(texts), normalize_embeddings=True, show_progress_bar=False))


def cosine(a, b):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))


def cosine_matrix(a, b):
    a, b = np.atleast_2d(a), np.atleast_2d(b)
    a = a / np.linalg.norm(a, axis=1, keepdims=True)
    b = b / np.linalg.norm(b, axis=1, keepdims=True)
    return a @ b.T


def word_arithmetic(a, b, c, words, word_vecs, embed_fn, exclude=()):
    """Rank `words` by cosine to vec(a) - vec(b) + vec(c). word_vecs: (len(words), d)."""
    va, vb, vc = embed_fn([a, b, c])
    target = va - vb + vc
    sims = cosine_matrix(target, word_vecs)[0]
    skip = {w.lower() for w in (a, b, c, *exclude)}
    ranked = [(w, float(s)) for w, s in zip(words, sims) if w.lower() not in skip]
    return sorted(ranked, key=lambda x: -x[1])


# ---------------------------------------------------------------- vector search
def project_2d(corpus_vecs, query_vec):
    """PCA to 2D. The query is projected with the PCA fitted on the corpus only."""
    from sklearn.decomposition import PCA

    pca = PCA(n_components=2).fit(corpus_vecs)
    return (
        pca.transform(corpus_vecs),
        pca.transform(np.atleast_2d(query_vec))[0],
        float(pca.explained_variance_ratio_.sum()),
    )


def semantic_search(query_vec, corpus_vecs, k=5):
    sims = cosine_matrix(query_vec, corpus_vecs)[0]
    order = np.argsort(-sims)[:k]
    return [(int(i), float(sims[i])) for i in order]


_STOP = {"a", "an", "the", "is", "are", "was", "were", "and", "or", "of", "to", "in", "on", "for", "with", "by", "at", "after", "it", "our", "we"}


def _terms(text):
    return {t for t in re.split(r"[^a-z0-9]+", text.lower()) if t and t not in _STOP}


def keyword_search(query, corpus, k=5):
    """Score = number of shared (non-stopword) terms. Zero-score rows are dropped."""
    q = _terms(query)
    scored = [(i, len(q & _terms(t))) for i, t in enumerate(corpus)]
    scored = [x for x in scored if x[1] > 0]
    return sorted(scored, key=lambda x: (-x[1], x[0]))[:k]


# ---------------------------------------------------------------- generation
def _next_logits(text, model, tokenizer):
    import torch

    ids = tokenizer.encode(text, return_tensors="pt")
    if ids.shape[1] == 0:
        ids = torch.tensor([[tokenizer.eos_token_id]])
    with torch.no_grad():
        return model(ids).logits[0, -1].float()


def next_token_distribution(text, model, tokenizer, temperature=1.0, top_k=0, top_p=1.0, n=10):
    """Next-token probabilities after temperature, top-k and top-p.

    Returns dict(tokens=[{id,text,prob}] (top n, sorted), probs=full tensor, raw_sum, entropy, raw_top).
    """
    import torch

    logits = _next_logits(text, model, tokenizer)
    raw_probs = torch.softmax(logits, dim=-1)
    raw_top = int(raw_probs.argmax())
    t = max(float(temperature), 1e-4)
    probs = torch.softmax(logits / t, dim=-1)
    if top_k and top_k > 0:
        kth = torch.topk(probs, min(int(top_k), probs.numel())).values[-1]
        probs = torch.where(probs >= kth, probs, torch.zeros_like(probs))
    if top_p < 1.0:
        sp, si = torch.sort(probs, descending=True)
        cum = torch.cumsum(sp / sp.sum(), dim=0)
        drop = cum - sp / sp.sum() >= top_p  # keep the token that crosses top_p
        sp = torch.where(drop, torch.zeros_like(sp), sp)
        probs = torch.zeros_like(probs).scatter(0, si, sp)
    probs = probs / probs.sum()
    top = torch.topk(probs, n)
    ent = float(-(probs[probs > 0] * probs[probs > 0].log2()).sum())
    return {
        "tokens": [
            {"id": int(i), "text": tokenizer.decode([int(i)]), "prob": float(p)}
            for p, i in zip(top.values, top.indices)
        ],
        "probs": probs,
        "raw_sum": float(raw_probs.sum()),
        "raw_top": {"id": raw_top, "text": tokenizer.decode([raw_top]), "prob": float(raw_probs[raw_top])},
        "entropy": ent,
    }


def pick_next_token(dist, greedy=False, generator=None):
    """Choose one token id from a distribution: argmax if greedy, else sample."""
    import torch

    probs = dist["probs"]
    if greedy:
        tid = int(probs.argmax())
    else:
        tid = int(torch.multinomial(probs, 1, generator=generator))
    return {"id": tid, "prob": float(probs[tid])}


def generate_n(text, n, model, tokenizer, temperature=1.0, top_k=0, top_p=1.0, greedy=False, seed=None):
    """Generate n tokens one at a time. Returns (final_text, steps)."""
    import torch

    gen = None
    if seed is not None:
        gen = torch.Generator().manual_seed(int(seed))
    steps = []
    for _ in range(n):
        dist = next_token_distribution(text, model, tokenizer, temperature, top_k, top_p)
        tok = pick_next_token(dist, greedy, gen)
        piece = tokenizer.decode([tok["id"]])
        steps.append({"text": piece, "prob": tok["prob"], "entropy": dist["entropy"]})
        text += piece
    return text, steps
# ---------------------------------------------------------------- attention
def attention_weights(text, model, tokenizer, max_tokens=40):
    """Real GPT-2 attention. Returns dict(tokens, ids, weights (layers, heads, T, T), truncated)."""
    import torch
    ids = tokenizer.encode(text)
    truncated = len(ids) > max_tokens
    ids = ids[:max_tokens]
    if not ids:
        return {"tokens": [], "ids": [], "weights": np.zeros((0, 0, 0, 0), dtype=np.float32), "truncated": False}
    with torch.no_grad():
        out = model(torch.tensor([ids]), output_attentions=True)
    if not out.attentions or out.attentions[0] is None:
        raise ValueError("The model returned no attention weights. Load it with attn_implementation='eager'.")
    weights = torch.stack([a[0] for a in out.attentions]).float().numpy()
    return {"tokens": [tokenizer.decode([i]) for i in ids], "ids": ids, "weights": weights, "truncated": truncated}
def attention_matrix(weights, layer, head=None):
    """(T, T) matrix for one layer. Row i = how token i spreads its attention. head=None: mean over heads."""
    w = weights[layer]
    return w.mean(axis=0) if head is None else w[head]
def attention_row(weights, layer, head, query_idx):
    """How one token spreads its attention over the tokens up to and including itself."""
    row = attention_matrix(weights, layer, head)[query_idx].copy()
    row[query_idx + 1:] = 0.0
    return row
def head_pattern_scores(weights):
    """Per (layer, head): mean weight on the previous token, and on the first token (rows 1 onwards)."""
    T = weights.shape[-1]
    idx = np.arange(1, T)
    prev = weights[:, :, idx, idx - 1].mean(axis=-1)
    first = weights[:, :, idx, 0].mean(axis=-1)
    return prev, first
def top_heads(scores, n=3):
    flat = np.argsort(-scores, axis=None)[:n]
    return [(int(i // scores.shape[1]), int(i % scores.shape[1]), float(scores.flat[i])) for i in flat]
