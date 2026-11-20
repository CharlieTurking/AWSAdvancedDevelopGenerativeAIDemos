# Demo A — Real-time token tracking and alerting - Slide 7

> AWS *Advanced Development with Generative AI* · **Module 8**, slides 5 & 7
> (token economics + the traffic-light status system)

A live Streamlit dashboard that tracks token consumption from Amazon Bedrock
calls and drives the slide-7 **traffic-light status system**:

| Status | Quota used | Color |
|--------|-----------|-------|
| Normal | 0–80% | 🟢 |
| Warning | 80–95% | 🟡 |
| Critical | >95% | 🔴 |

It shows the slide-7 layers:

- **Real-time monitoring layer** — total tokens, % of quota, estimated cost,
  tokens/min, and a cost-trend projection (minutes until the quota is hit at the
  current burn rate).
- **Intelligent alert engine** — context analysis → threshold logic → action
  trigger. The recommended action is tuned by a *business-hours* toggle so a mere
  Warning off-hours doesn't page anyone.
- **Granular visibility** — tokens broken down by **App** and **User segment**
  (the slide-7 custom-metric dimensions), plus an input-vs-output split that
  reflects the slide-5 ratios (Q&A ~1:1, Summarization ~10:1 input:output).

## Run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

### Two modes

- **Simulate (default, no AWS):** the sidebar's *Simulate* toggle is on. The app
  generates synthetic token usage honoring the slide-5 use-case ratios, so you can
  demo the full traffic-light flow with no credentials.
- **Live Bedrock:** turn *Simulate* off. Each generated call hits Bedrock
  (`Converse`) and tracks the authoritative token counts it reports.

Prerequisites for live mode:
- AWS credentials on the standard chain (env vars, `~/.aws/credentials`, or SSO).
- Bedrock model access enabled in your region for the model ID
  (`us.anthropic.claude-haiku-4-5-20251001-v1:0` by default — matches the course).
- IAM permission for `bedrock:InvokeModel` on the inference profile.

### Optional: publish to CloudWatch

Flip **"Publish custom metrics to CloudWatch"** in the sidebar to push
`InputTokens` / `OutputTokens` / `TotalTokens` / `EstimatedCostUSD` (with `App`
and `UserSegment` dimensions) to a custom namespace (`AI/TokenTracking`). This is
the only part that touches a billable surface beyond Bedrock
(`cloudwatch:PutMetricData`). It needs IAM permission for that action; add
`cloudwatch:PutMetricData` to your credentials/role. Custom metrics are not
deletable — they simply stop updating and age out — so there is nothing to tear
down.

## Files

| File | Purpose |
|------|---------|
| `app.py` | Streamlit UI (load generator + monitoring layers) |
| `tracking.py` | Traffic-light status, burn-rate projection, alert engine, breakdowns |
| `bedrock_client.py` | `bedrock-runtime:Converse` wrapper + token/cost helpers |
| `cloudwatch.py` | Optional custom-metrics publisher |

## How to drive the demo

1. Keep **Simulate** on and set a small **Token quota** (e.g. 5,000).
2. Click **Generate load** a few times and watch the status move 🟢 → 🟡 → 🔴.
3. Toggle **Within business hours** off and regenerate — the alert engine changes
   the recommended channel/action for the same status level.
4. Compare the **by App** and **by User segment** charts, and the input-vs-output
   split, to the slide-5 token-economics ratios.

## Cost note

Live mode incurs Bedrock per-token charges per generated call; the CloudWatch
option incurs custom-metric charges. The dollar figures in the UI use illustrative
public prices (`PRICE_PER_1K_INPUT` / `PRICE_PER_1K_OUTPUT`), not your actual bill.
