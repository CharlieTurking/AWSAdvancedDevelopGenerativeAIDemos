# Demo A+B — Multi-dimensional evaluation scorecard (with consistency testing) Slides 6 & 9

> AWS *Advanced Development with Generative AI* · **Module 9**, slides 6, 7, 9

Scores model responses across the slide-6 evaluation pyramid and compares models
on a slide-9 radar chart. Combines two demo ideas:

- **Demo A — multi-dimensional scorecard:** score each answer on
  **functional correctness**, **relevance/accuracy**, and
  **consistency/reliability**, using the three slide-7 techniques.
- **Demo B — response consistency / variance:** fold directly into the
  consistency dimension by running each model several times and measuring how
  much its answers vary (multi-query testing).

| Dimension (slide 6) | Technique (slide 7) | How it's scored |
|---------------------|---------------------|-----------------|
| Functional correctness | Fact verification | LLM-as-a-judge rubric (1–5 → %) |
| Relevance/accuracy | Semantic similarity | Titan embedding cosine vs. reference, blended with judge accuracy |
| Consistency/reliability | Response variance | Mean pairwise similarity across N runs (Demo B) |

Outputs: slide-7 gauges per model, a scorecard table, and the slide-9 radar
chart comparing models.

## Run

```bash
cd ~/AdvDevGenAI/09_eval_scorecard/
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

### Two modes

- **Simulate (default, no AWS):** canned answers for two models, offline
  embeddings, and an offline overlap-based judge. The two sample models are
  intentionally different quality so the scorecard and radar show a clear gap.
- **Live Bedrock:** turn *Simulate* off. Generation + judging use Claude
  (`Converse`), relevance uses Titan embeddings. Raise the generation temperature
  to make the consistency test more revealing.

Prerequisites for live mode:
- AWS credentials on the standard chain.
- Bedrock model access for the generation/judge model and
  `amazon.titan-embed-text-v2:0`.
- IAM permission for `bedrock:InvokeModel` on those models / the inference profile.

No AWS resources are created, so there is nothing to tear down.

## Files

| File | Purpose |
|------|---------|
| `app.py` | Streamlit UI (per-model scoring, gauges, scorecard, radar) |
| `evaluation.py` | Dimension scoring, similarity, consistency, judge rubric |
| `sample_data.py` | Sample questions, references, canned offline answers |
| `bedrock_client.py` | Converse + Titan embeddings wrappers |

## Notes

- The LLM judge always runs at temperature 0 for stable scoring; only the
  *generation* temperature is adjustable (and drives the consistency test).
- The radar chart uses Plotly; if it isn't available the app falls back to a bar
  chart automatically.
- Scores are heuristic/relative — useful for comparison and teaching, not an
  absolute quality guarantee.

## Cost note

Live mode makes one generation call per consistency run per model, plus one judge
call per model. Dollar figures use illustrative public prices, not your bill.
