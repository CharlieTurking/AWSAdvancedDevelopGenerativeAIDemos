# How LLMs work: from a sentence to the next token
> AWS *Advanced Development with Generative AI* · **Course opener, before Module 1**

For IT professionals who use GenAI but have not seen inside it. Type one sentence and
follow it through every stage: tokens, IDs, embeddings, vector search, attention,
real next-token prediction, and how a model learns those weights in the first place. Each page has plain-language captions, a "Show the code"
expander with the real Python behind it, and a presenter-notes expander.

## What runs where
| Stage | Component | Where |
|-------|-----------|-------|
| Tokenize | `tiktoken` GPT-2 byte-pair encoding | local |
| Token vectors | GPT-2 small (124M) input embedding table | local, CPU |
| Word similarity, analogies, vector search | `all-MiniLM-L6-v2` (384 dims) | local, CPU |
| Attention | GPT-2 small attention weights (eager attention) | local, CPU |
| Generate | GPT-2 small, next-token probabilities | local, CPU |
| Training | tiny numpy next-word model, trained in seconds on a built-in text | local, CPU, no download |
The demo is **fully offline** once the models are downloaded. No AWS, no Bedrock, no credentials.

## Run
```bash
source ~/AdvDevGenAI/.venv/bin/activate
cd ~/AdvDevGenAI/00_how_llms_work
streamlit run app.py
```
It uses the shared root venv. Dependencies (`torch`, `transformers`, `sentence-transformers`)
are in the root `requirements.txt`; `requirements.txt` here lists the same for standalone use.

### First run: model download
GPT-2 (~500 MB, used by Embed, Attention and Generate) and all-MiniLM-L6-v2 (~90 MB, Embed and Vector search) are downloaded once into `~/.cache/huggingface`.
The Training page needs no download. If a model is missing, the page says so and offers a **Download** button. To pre-download
(run this before class, it needs internet):
```bash
python -c "from transformers import AutoModelForCausalLM, AutoTokenizer as T; T.from_pretrained('gpt2'); AutoModelForCausalLM.from_pretrained('gpt2')
from sentence_transformers import SentenceTransformer as S; S('sentence-transformers/all-MiniLM-L6-v2')"
```

## Pages
| Page | What to show |
|------|--------------|
| The whole pipeline | Five numbered cards (Tokenize, Embed, Transformer, Predict, Repeat), the training band and common misconceptions |
| 1. Tokenize | Coloured tokens, IDs, counts. Tokens are not words. Context window and cost |
| 2. Embed | Each token as a real vector, heat-strip, word similarity, king - man + woman |
| 3. Vector search | Keyword vs semantic search over 36 IT sentences, 2D PCA map, top-k with scores, then animated IVF and HNSW approximate-search walk-throughs and a speed-vs-accuracy chart |
| 4. Attention | Real GPT-2 attention weights: pick a token (try 'it'), layer and head or the average over heads, shaded chips, bar chart, causal heatmap, a previous-token head and a first-token head |
| 5. Generate | GPT-2 top-10 next tokens, temperature (focused / balanced / chaotic) / top-k / top-p, greedy vs sampling, auto-generate |
| 6. Training | A tiny next-word model learning from 352 words: animated loss curve, learning-rate and epoch sliders, predictions going from gibberish to `memory`, word vectors moving |

The starting sentence (default "The server went down because the database ran out of") is shared by all pages.

## Honest caveats
- GPT-2 is a 2019 model with 124M parameters, far smaller than modern LLMs. Same mechanism, much weaker predictions.
- The 2D map uses PCA, which discards most of the information. The ranking table is the real result.
- King - man + woman comes from static word vectors (word2vec, GloVe). Here a sentence model approximates it for single words. The page shows the true result, including failures.
- Attention weights are not an explanation of the model's reasoning, and real heads are messier than textbook diagrams. The 'it' to 'server' link exists in a couple of heads only.
- The training toy is word-level, has about 11 thousand weights, memorises its 352 words and has no transformer. It shows the loop, not how well real models generalise.

## Files
| File | Purpose |
|------|---------|
| `app.py` | Navigation only |
| `core.py` | Tokenizing, embedding, search, attention and next-token functions (no Streamlit) |
| `models.py` | Cached model loaders (GPT-2 with eager attention so weights can be read) and download helper |
| `training.py`, `train_plots.py` | The tiny numpy next-word model and its Plotly figures |
| `ann.py`, `ann_plots.py` | Toy IVF and HNSW indexes on 2D points, and their animated Plotly figures |
| `ui.py` | Shared widgets: sentence box, token chips, code and notes expanders |
| `pages/` | One file per page: Home, Tokenize, Embed, Vector search, Attention, Generate, Training |
| `data/corpus.json` | 36 short IT sentences (plus a few unrelated) for vector search |
| `data/analogy_words.json` | ~150 candidate words for the arithmetic demo |
| `data/training_text.txt` | 352-word IT-themed text the toy model trains on |
