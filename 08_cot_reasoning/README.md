# Demo H — Chain-of-thought reasoning analyzer - Slide 38

> AWS *Advanced Development with Generative AI* · **Module 8**
> (slides 36–39 — and the **correct answer to Question 2**, option B)

The Question 2 scenario: a foundation model doing financial analysis produces
correct-ish final answers but with flawed reasoning, and users have lost trust
because they can't see how conclusions are reached. The fix: trace the decision
process, use chain-of-thought analysis to validate the reasoning, and identify
where it fails.

This local Streamlit app:

1. Runs a question **two ways** on the same Bedrock model — traditional ("just the
   answer", hidden reasoning) vs. **chain-of-thought** ("show your steps"),
   mirroring slide 38.
2. Parses the CoT answer into **visible steps** (the reasoning-transparency flow,
   slides 36–37).
3. Runs **automated logic-error detection** over the chain (slide 39):
   **circular logic**, **false premises**, **inconsistency**.
4. Optionally runs the question several times and checks **answer agreement**
   (self-consistency / multi-run cross-check, slide 35 flavor) to flag unstable
   reasoning.

The error detectors are transparent heuristics (not a black box), so you can
explain in the session *why* each issue was flagged.

## Run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

### Two modes

- **Simulate (default, no AWS):** uses a canned, deliberately flawed CoT sample
  that trips the detectors (it assumes the margin instead of deriving it, uses a
  fabricated cost, justifies a step by restating it, and ends inconsistent with
  its own math). Great for rehearsing the full flow with no credentials.
- **Live Bedrock:** turn *Simulate* off. Both prompts hit Bedrock (`Converse`),
  and the self-consistency check actually re-runs the model.

Prerequisites for live mode:
- AWS credentials on the standard chain (env vars, `~/.aws/credentials`, or SSO).
- Bedrock model access enabled in your region for the model ID
  (`us.anthropic.claude-haiku-4-5-20251001-v1:0` by default — matches the course).
- IAM permission for `bedrock:InvokeModel` on the inference profile.

No AWS resources are created in either mode, so there is nothing to tear down.

## How to drive the demo

1. In **Simulate** mode, click **Analyze reasoning**. The error-detection table
   should list a circular-logic, false-premise, and inconsistency finding — walk
   through why each fired.
2. Switch to **live Bedrock**, pick the compound-growth or rate-blending sample
   (models slip on these), raise the temperature, and set self-consistency runs to
   5–7. Watch for answer disagreement across runs.
3. Contrast the traditional vs. CoT panels to make the "hidden vs. visible
   reasoning" point (slide 38) concrete.

## Files

| File | Purpose |
|------|---------|
| `app.py` | Streamlit UI (dual prompt, step view, error detection, consistency) |
| `prompts.py` | Traditional vs. chain-of-thought prompt templates |
| `analysis.py` | Step parser + logic-error detectors + self-consistency |
| `sample_questions.py` | Financial-analysis sample questions |
| `bedrock_client.py` | `bedrock-runtime:Converse` wrapper + token/cost helpers |

## Caveats

- The detectors are heuristics tuned for structured, numeric financial reasoning.
  They catch the common slide-39 patterns but are not a formal logic verifier —
  expect occasional false positives/negatives on free-form answers.
- Automated analysis works best when the model follows the numbered `Step N:`
  format; the app warns if it can't parse steps.

## Cost note

Live mode incurs Bedrock per-token charges per call (and the self-consistency
check multiplies that by the number of runs). The dollar figures use illustrative
public prices (`PRICE_PER_1K_INPUT` / `PRICE_PER_1K_OUTPUT`), not your actual bill.
