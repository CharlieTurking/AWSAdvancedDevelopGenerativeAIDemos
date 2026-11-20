# Demo 1 — Prompt compression without losing effectiveness

> AWS *Advanced Development with Generative AI* · **Module 7**, slide 12
> ("Before: 160 tokens → After: 64 tokens, 60% token reduction")

A Streamlit app that compresses a verbose prompt, then sends **both** the verbose
and compressed versions to the same Amazon Bedrock model so you can compare, in
real time:

- token count before vs. after (and the % reduction),
- the **actual** input tokens Bedrock billed for each call,
- per-call cost and latency,
- the two answers side by side — to prove quality is preserved.

The compressor is rule-based (strip filler/politeness words, collapse verbose
phrases), so the demo runs instantly with no ML model download. For a heavier
ML-based compressor (LLMLingua) see the sibling `prompt-compression/` folder.

## Files

| File | Purpose |
|------|---------|
| `app.py` | Streamlit UI |
| `compression.py` | Rule-based prompt compressor |
| `bedrock_client.py` | `bedrock-runtime:Converse` wrapper + token/cost helpers |
| `Dockerfile` | Container image for the AWS deployment option |
| `deploy/deploy.sh` | Deploy to AWS App Runner |
| `deploy/teardown.sh` | **Remove every AWS resource** the deploy created |
| `deploy/config.sh` | Names/region shared by deploy + teardown |

## Option A — run locally (Streamlit)

```bash
cd ~/AdvDevGenAI/07_prompt_compression
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Prerequisites:
- AWS credentials on the standard chain (env vars, `~/.aws/credentials`, or SSO).
- Bedrock model access enabled in your region for the model ID
  (`us.anthropic.claude-haiku-5-5` by default — matches the course).
- IAM permission for `bedrock:InvokeModel` on the inference profile.

No AWS resources are created in this mode, so there is nothing to tear down.

## Option B — run in AWS (App Runner)

A one-command containerized deployment that gives you a public HTTPS URL.

```bash
# needs: awscli v2, docker, credentials that can create ECR/IAM/App Runner
./deploy/deploy.sh
```

What it creates (all named with the `APP_NAME` prefix from `deploy/config.sh`):

- an **ECR repository** for the image,
- an **IAM instance role** so the container can call Bedrock,
- an **IAM access role** so App Runner can pull from ECR,
- an **App Runner service** (the public endpoint).

The script prints the URL when the service reaches `RUNNING` (first deploy ~3–5 min).

### Tear down (required to stop charges)

```bash
./deploy/teardown.sh
```

This deletes the App Runner service, both IAM roles (and their policies), and the
ECR repository with its images. It is idempotent — safe to re-run.

### Config overrides

Set these before running either script:

```bash
export AWS_REGION=us-west-2
export BEDROCK_MODEL_ID=us.anthropic.claude-haiku-5-5
export APP_NAME=my-compression-demo   # changes every resource name
```

## Cost note

App Runner bills for provisioned container memory/CPU while the service exists,
plus Bedrock per-token charges per call. Run `teardown.sh` when you're done. The
dollar figures shown in the UI use illustrative public prices (override via
`PRICE_PER_1K_INPUT` / `PRICE_PER_1K_OUTPUT`), not your actual bill.
