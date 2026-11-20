# Demo H — LLM-as-a-judge rubric scorer with bias controls slides 36, 37, 38

> AWS *Advanced Development with Generative AI* · **Module 9**, slides 36, 37, 38

A local Streamlit app that uses an LLM as an evaluation judge and guards against
the reliability problems the deck warns about.

- **Rubric scoring (slides 36, 38):** score any answer 1–5 on **accuracy**,
  **relevance**, **completeness**, **clarity**, and **faithfulness**, using
  anchor examples (reference points / quality levels) and a low-temperature judge
  for stable, repeatable scoring.
- **Position-bias control (slide 37):** for a pairwise "A vs B" comparison, the
  app runs the judge **both ways** — A-first and B-first. If the winner flips when
  the order is swapped, the judge has **position bias** and the verdict is flagged
  as order-dependent/unreliable (the slide-37 mitigation message points to
  randomization / ensemble judging).

## Run

```bash
cd ~/AdvDevGenAI/09_llm_judge
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

### Two modes

- **Simulate (default, no AWS):** an offline overlap-based judge scores against
  the reference. The offline comparator is deliberately order-independent, so the
  position-bias check shows a clean "no bias" result you can contrast with live
  behavior.
- **Live Bedrock:** turn *Simulate* off. The judge is a Claude model via
  `Converse` at temperature 0. This is where position bias can actually appear —
  swap-ordering sometimes flips the winner on genuinely close answer pairs.

Prerequisites for live mode:
- AWS credentials on the standard chain.
- Bedrock model access for the judge model.
- IAM permission for `bedrock:InvokeModel` on the inference profile.

No AWS resources are created, so there is nothing to tear down.

## How to drive the demo

1. **Rubric scoring tab:** score Answer A (good) then paste Answer B (wrong) and
   watch the per-dimension scores drop — especially accuracy and faithfulness.
2. **Pairwise tab:** compare two close answers in live mode and run the
   both-orderings check. On genuinely close pairs you can sometimes catch the
   winner flipping — the demo flags it as position bias. Clear-cut pairs stay
   consistent.

## Files

| File | Purpose |
|------|---------|
| `app.py` | Streamlit UI (rubric tab + pairwise/bias tab) |
| `judge.py` | Rubric + pairwise prompts, parsing, position-bias verdict |
| `sample_data.py` | Sample questions, references, answer pairs |
| `bedrock_client.py` | `Converse` wrapper (low-temperature judge) |

## Notes / caveats

- Position bias is one of several biases on slide 37 (also recency, verbosity,
  confirmation, domain, source). This demo implements the position-bias check
  because it's the most directly demonstrable; the others are listed in the deck
  as mitigation targets.
- A single swap check is a lightweight probe, not a full bias audit. Production
  judging should add ensemble judges and human calibration (slide 37).

## Cost note

Rubric scoring makes one judge call; the pairwise check makes two (one per
ordering). Live mode incurs Bedrock per-token charges; no custom pricing is shown
in this demo's UI.
