# Demo 2 — Sliding-window context pruning for long conversations

> AWS *Advanced Development with Generative AI* · **Module 7**
> (slides 11, 13, 14 — and the **correct answer to Question 1**)

The Question 1 scenario: a customer-support chatbot on Claude Haiku keeps the
**entire** conversation history in the context window. Costs climb fast past ~15
turns, and the CFO wants a **40% cost cut without losing quality**.

This Streamlit app answers the same final query two ways against the same Bedrock
model and compares them:

- **Baseline** — full conversation history (today's behaviour).
- **Pruned** — a sliding window (last *N* turns) **plus** turns the system itself
  flags as important **plus** optionally the most semantically-relevant older turns.

It shows per-call input tokens (as billed by Bedrock), cost, and latency, charts
full vs. pruned, and checks whether the **40% target** is met while the pruned
answer still resolves the user's reference to an issue from **turn 2**.

The bundled 16-turn conversation ends with the user asking about the damaged item
and order number first mentioned at turn 2. Nothing is user-pinned: the system
scores each turn (structured IDs, money/dates, commitments, and relevance to the
final query) and automatically keeps turn 2 (order number) and turn 5 (refund
promise), showing why the sliding window alone isn't enough.

## Files

| File | Purpose |
|------|---------|
| `app.py` | Streamlit UI |
| `pruning.py` | Sliding-window + auto-importance scoring + semantic selection logic |
| `sample_conversation.py` | The 16-turn support chat and final query |
| `bedrock_client.py` | `bedrock-runtime:Converse` wrapper + token/cost helpers |
| `Dockerfile` | Container image for the AWS deployment option |
| `deploy/deploy.sh` | Deploy to AWS App Runner |
| `deploy/teardown.sh` | **Remove every AWS resource** the deploy created |
| `deploy/config.sh` | Names/region shared by deploy + teardown |

## Option A — run locally (Streamlit)

```bash
cd ~/AdvDevGenAI/07_context_pruning
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Prerequisites:
- AWS credentials on the standard chain (env vars, `~/.aws/credentials`, or SSO).
- Bedrock model access enabled in your region for the model ID
  (`us.anthropic.claude-haiku-4-5-20251001-v1:0` by default — matches the course).
- IAM permission for `bedrock:InvokeModel` on the inference profile.

Relevance scoring uses offline keyword overlap by default, so no extra model
access is needed. No AWS resources are created in this mode — nothing to tear down.

## Option B — run in AWS (App Runner)

```bash
# needs: awscli v2, docker, credentials that can create ECR/IAM/App Runner
./deploy/deploy.sh
```

Creates (all named with the `APP_NAME` prefix from `deploy/config.sh`): an ECR
repository, an IAM instance role (Bedrock access), an IAM access role (ECR pull),
and an App Runner service. It prints the public URL when the service is `RUNNING`
(first deploy ~3–5 min).

### Tear down (required to stop charges)

```bash
./deploy/teardown.sh
```

Deletes the App Runner service, both IAM roles (and policies), and the ECR
repository with its images. Idempotent — safe to re-run.

### Config overrides

```bash
export AWS_REGION=us-west-2
export BEDROCK_MODEL_ID=us.anthropic.claude-haiku-4-5-20251001-v1:0
export APP_NAME=my-pruning-demo   # changes every resource name
```

## Cost note

App Runner bills for provisioned container memory/CPU while the service exists,
plus Bedrock per-token charges per call. Run `teardown.sh` when done. The dollar
figures in the UI use illustrative public prices
(`PRICE_PER_1K_INPUT` / `PRICE_PER_1K_OUTPUT`), not your actual bill.
