# Demo B — Async queue + resilience patterns slides 11 & 13

> AWS *Advanced Development with Generative AI* · **Module 10**, slides 11 & 13
> (the other half of the **Question 1** answer: SQS queuing for peak load)

Question 1's scenario has users hitting delays when the AI service processes
high-volume requests at peak. The answer pairs the adapter (Demo A) with
**request queuing** to absorb the burst. This app simulates that queue plus the
slide-13 **resilience patterns**:

- **Immediate job ID (slide 11):** each submitted request is accepted and gets a
  job ID right away (asynchronous request-reply).
- **Load leveling (slide 11):** a burst of jobs lands in an in-memory queue and is
  drained by a worker rather than all hitting the model at once.
- **Exponential backoff + jitter (slide 13):** failed calls are retried with
  full-jitter exponential backoff.
- **Circuit breaker (slide 13):** after N consecutive failures the circuit opens
  and jobs fast-fail (rejected) instead of hammering an unhealthy dependency; it
  probes for recovery after a cooldown.

## Run

```bash
cd ~/AdvDevGenAI/10_async_queue
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

- **Simulate (default, no AWS):** a fake worker with an adjustable **failure rate**
  so you can drive retries and trip the breaker on demand. Backoff delays are
  computed and reported but fast-forwarded so the UI stays responsive.
- **Live Bedrock:** turn *Simulate* off to drain the queue with real `Converse`
  calls (real failures, if any, flow through the same retry/breaker logic).

Prerequisites for live mode: AWS credentials, Bedrock model access,
`bedrock:InvokeModel`. No AWS resources are created; nothing to tear down.

## How to drive the demo

1. Set a **failure rate** of ~0.3 and submit a burst of 20 jobs — you'll see
   retries with backoff delays and some jobs still succeeding.
2. Push the failure rate to ~0.7 — the **circuit breaker trips open** and later
   jobs are **rejected (fast-fail)** rather than retried endlessly.
3. Drop it back to 0 — everything drains cleanly, breaker stays closed.

## Files

| File | Purpose |
|------|---------|
| `app.py` | Streamlit UI (submit burst, drain, charts, per-job detail) |
| `resilience.py` | Job model, backoff+jitter, circuit breaker, drain loop |
| `bedrock_client.py` | `Converse` wrapper |

## Note

This is an in-memory teaching model of the SQS→Lambda pattern, not the real
services. The queue, worker, backoff, and breaker are all local so the behavior is
visible and deterministic to drive; a production build would use Amazon SQS, AWS
Lambda concurrency, and a shared breaker store.
