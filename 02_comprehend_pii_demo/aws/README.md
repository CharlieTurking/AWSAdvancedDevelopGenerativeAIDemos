# Amazon Comprehend demo on AWS

The Streamlit demo in the parent folder, as a deployed website (same three pages: PII detection, Mask PII,
Spot possible bias). The local Streamlit version is unchanged and still works.

```
Browser --> CloudFront --> private S3 bucket   (index.html, app.js, styles.css, sample_data/)
   |
   +-----> API Gateway --> Lambda --> Amazon Comprehend
```

| Path | What it is |
|---|---|
| `website/` | Plain HTML, CSS and JS. No build step, no external libraries. |
| `lambda_functions/api_handler.py` | The only code that calls Comprehend. Routes: `/pii`, `/mask`, `/sentiment`, `/toxicity`, `/info`. |
| `../comprehend_core.py` | The Comprehend calls and masking logic, **shared** with the Streamlit demo. `app.py` copies it into the Lambda package at synth time. |
| `../sample_data/` | The demo data, **shared** with Streamlit. Copied into the site at synth time. |
| `stack/comprehend_demo_stack.py` | The CDK stack (about 150 lines). |
| `scripts/` | `deploy.sh`, `teardown.sh`, `dev_server.py`. |

The "Show the code that calls Comprehend" panels are filled by the Lambda (`GET /info`) with the real source of
the functions it runs, so the code on screen is the code that executes.

## Try it without deploying

```bash
source ~/AdvDevGenAI/.venv/bin/activate
python aws/scripts/dev_server.py        # http://127.0.0.1:8000
```

Serves the site and runs the real Lambda handler locally, calling Comprehend with your AWS credentials.

## Deploy and remove

```bash
cd ~/AdvDevGenAI/02_comprehend_pii_demo/aws
scripts/deploy.sh --synth-only      # build and validate, create nothing
scripts/deploy.sh --allow-my-ip     # deploy; the API only answers to this machine's public IP
scripts/deploy.sh                   # deploy with a public (throttled) API
scripts/teardown.sh                 # delete everything
```

Needs the shared venv, Node (via `.nvmrc`, same as the BDA demo), the CDK CLI and AWS credentials. A new
account/region needs `scripts/deploy.sh --bootstrap` once. The website URL is printed at the end and saved to
`outputs.json` (git-ignored). A new CloudFront distribution can take a few minutes to start serving.

## Cost and safety

- The page itself is harmless; the **API is what spends money** (Comprehend is billed per use). Anyone with the API
  URL can call it unless you restrict it.
- `--allow-ip` / `--allow-my-ip` adds an API Gateway resource policy that denies every other address. It suits a known
  network. If you present from somewhere else, run `deploy.sh --allow-my-ip` again from there.
- Without an allow-list the API is public. The stage throttle (10 requests/second, burst 20) and the Lambda's input limits
  (10,000 characters of text, 1,000 bytes per sentiment/toxicity item) slow abuse down but are **not a spend cap**.
  Tear the stack down when you are finished.
- The Lambda's role can only call `DetectPiiEntities`, `BatchDetectSentiment` and `DetectToxicContent`.
- Request text is PII by design in this demo. It is never logged, and API Gateway access logging is off. Use made-up data.
