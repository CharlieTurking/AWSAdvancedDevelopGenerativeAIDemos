# Demo 8 — Semantic caching for generative AI

> AWS *Advanced Development with Generative AI* · **Module 7**
> (slides 37–39 — and the **correct answer to Question 2**, option D)

Users ask the same thing with different wording:

- "How do I reset my password?"
- "What's the process for changing my login credentials?"

**Exact-match caching** (traditional web caching) treats those as different keys,
misses the paraphrase, and pays the foundation model again. A **semantic cache**
embeds the query with **Amazon Titan Embeddings**, stores the vector, and on
lookup serves a cached answer when the nearest stored query is within a
cosine-similarity threshold — cutting latency, tokens, and cost toward the
slide's **60–80% hit-rate** target.

This Streamlit app shows both caches side by side so the difference is visible:
the slide's own password example hits the semantic cache where exact match misses.

## What runs where

| Component | Local demo | AWS / production (Q2 answer D) |
|-----------|------------|--------------------------------|
| Embeddings | Amazon Titan via Bedrock | Amazon Titan via Bedrock |
| Vector store | in-memory Python list | Amazon ElastiCache (Redis) + RediSearch |
| Answer model | Claude via Bedrock Converse | Claude via Bedrock Converse |

The demo runs **fully locally** — the only AWS calls are Bedrock `InvokeModel`
(embeddings) and `Converse` (answers). No ElastiCache/Redis is needed to run it,
and no persistent AWS resources are created, so there is nothing to tear down.

## Run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Prerequisites for the default (Bedrock) mode:
- AWS credentials on the standard chain (env vars, `~/.aws/credentials`, or SSO).
- Bedrock model access enabled in your region for **both**:
  - `amazon.titan-embed-text-v2:0` (embeddings)
  - `us.anthropic.claude-haiku-4-5-20251001-v1:0` (answers)
- IAM permission for `bedrock:InvokeModel` on those models / the inference profile.

### Offline rehearsal (no AWS)

Flip **"Use Bedrock"** off in the sidebar. The app then uses a deterministic
hashed-bag-of-words embedding fallback and stub answers so you can rehearse the
flow with no credentials. It's similarity-aware enough to show hits vs. misses
but is **not** a substitute for Titan embeddings in a real system.

## How to drive the demo

1. **"Try one query" tab** — ask "How do I reset my password?", then ask it again
   as "What's the process for changing my login credentials?". The exact cache
   misses the reword; the semantic cache hits it and shows the matched query and
   similarity score.
2. **"Run the sample stream" tab** — replays a mix of paraphrased intents
   (password reset, order tracking, refunds) plus unrelated one-offs. Watch the
   semantic hit rate land in the 60–80% band while exact match stays low.
3. **Similarity threshold** (sidebar) — raise it for stricter matching (fewer
   hits, less risk of a wrong hit); lower it to catch more paraphrases. The
   default follows the selected mode, because good thresholds differ by embedding
   model: real Titan vectors score true matches higher (default **0.80**) than the
   crude offline fallback (default **0.62**). On the bundled stream both land the
   semantic hit rate in the slide's 60–80% band with no false cross-intent hits.

## Files

| File | Purpose |
|------|---------|
| `app.py` | Streamlit UI (single query + batch stream) |
| `cache.py` | `ExactCache`, `SemanticCache`, cosine similarity, offline embeddings |
| `bedrock_client.py` | Titan embeddings + Claude Converse wrappers |
| `sample_queries.py` | Paraphrased-intent query stream |

## Cost note

Each cache **miss** makes one Titan embedding call and one Claude answer call;
each **hit** makes only the embedding call (answer served from memory). The
dollar/token figures use illustrative public prices
(`PRICE_PER_1K_INPUT` / `PRICE_PER_1K_OUTPUT`), not your actual bill.
