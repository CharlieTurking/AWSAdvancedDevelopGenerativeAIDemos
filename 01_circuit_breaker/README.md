# Demo 1 — Circuit breaker with AWS Step Functions
> AWS *Advanced Development with Generative AI* · **Module 1**

A Streamlit front page for a circuit breaker that is **implemented in AWS Step
Functions**. The backend is the AWS sample
[circuit-breaker-netcore-blog](https://aws.amazon.com/blogs/compute/using-the-circuit-breaker-pattern-with-aws-step-functions-and-amazon-dynamodb/)
(vendored in `circuit-breaker-netcore-blog/`): a state machine, four .NET 6
Lambdas and a DynamoDB table. The dashboard starts executions, shows whether the
circuit is OPEN or CLOSED, and charts the circuit tripping and recovering.

## How the circuit breaker works

1. You start the state machine with `{"TargetLambda": "<function name>"}`.
2. **Get Circuit Status** queries the `CircuitBreaker` DynamoDB table for an
   unexpired item for that service. If one exists the circuit is **OPEN** and
   the execution fails immediately.
3. Otherwise **Execute Lambda** calls the target (12 s task timeout, retried
   up to 3 times with exponential backoff).
4. If the call still fails, **Update Circuit Status** writes an item with
   `ExpireTimeStamp = now + 20 s` and the execution fails. Calls during those
   20 seconds fail fast, then the circuit closes again.

Two targets are provided:

| Target | Behaviour |
|--------|-----------|
| `HelloWorldFunction` | Succeeds. The circuit stays CLOSED. |
| `TestCircuitBreakerFunction` | Sleeps 15 s, so it always times out and trips the circuit. |

## What the dashboard shows

- **Sidebar:** Region (from the environment), an editable Stack Name, status
  messages, and the resolved state machine ARN, table and target Lambda names.
- **Controls:** a target selector and a **Start Execution** button, disabled
  unless the backend was resolved successfully.
- **Result line:** `<execution id>: SUCCESS | FAIL | RUNNING | UNKNOWN`.
- **Circuit badge:** OPEN / CLOSED / UNKNOWN for the selected target, read from
  DynamoDB.
- **Execution history:** id, target, start time, status and result, newest first.
- **Timeline:** a step chart of OPEN/CLOSED over time per service.
- The page auto-refreshes every 2 seconds to poll executions and the circuit.

The app talks to **live AWS only** (no simulation mode) and discovers the state
machine, table and Lambdas from the CloudFormation stack at runtime.

## Files

| File | Purpose |
|------|---------|
| `app.py` | The Streamlit dashboard (single file) |
| `requirements.txt` | Python dependencies |
| `tests/` | Property-based, unit and Streamlit `AppTest` tests |
| `circuit-breaker-netcore-blog/` | The deployable backend (SAM and CDK) |
| `.nvmrc` | Node version (used by the CDK option) |

## Step 1 — deploy the backend

Prerequisites: an AWS account with credentials configured, the
[SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)
and the .NET 6 SDK.

```bash
cd circuit-breaker-netcore-blog/circuit-breaker
sam build
sam deploy --guided      # use the stack name: circuit-breaker-stack
```

A CDK deployment is also available; see `circuit-breaker-netcore-blog/README.md`.
Use `circuit-breaker-stack` as the stack name, or enter whatever name you used
in the dashboard's **Stack Name** box.

## Step 2 — run the dashboard

```bash
cd ~/AdvDevGenAI/01_circuit_breaker
export AWS_DEFAULT_REGION=us-east-1      # the region you deployed to
source ../.venv/bin/activate             # shared venv, or create a local one
# pip install -r requirements.txt          # only needed for a local venv
streamlit run app.py
```

The shared environment at `~/AdvDevGenAI/.venv` already contains everything.
For a standalone one: `python3 -m venv .venv && source .venv/bin/activate`.

AWS permissions the credentials need: `cloudformation:ListStackResources`,
`states:StartExecution`, `states:DescribeExecution` and `dynamodb:Query` on the
`CircuitBreaker` table.

## Demo script

1. Select **HelloWorldFunction** and click **Start Execution**. The result is
   `SUCCESS` and the badge stays **CLOSED**.
2. Select **TestCircuitBreakerFunction** and start an execution. It retries,
   times out and ends as `FAIL`. This takes about a minute because of the
   retries.
3. Watch the badge flip to **OPEN** and a point appear on the timeline.
4. While it is OPEN, start another execution against the same target. It fails
   straight away without calling the Lambda.
5. After about 20 seconds the badge returns to **CLOSED**.

## Troubleshooting

| Message in the sidebar | Cause |
|------------------------|-------|
| AWS Region is not configured | Set `AWS_DEFAULT_REGION` or `AWS_REGION` and restart |
| AWS credentials are unavailable | Configure credentials (env vars, profile or SSO) |
| CloudFormation stack not found | Wrong stack name or region |
| Required resources are missing | The stack lacks the expected logical ids: `CircuitBreakerStateMachine`, `CircuitBreakerTable`, `HelloWorldFunction`, `TestCircuitBreakerFunction` |

The circuit state is read with a consistent query, but DynamoDB TTL deletes
expired items lazily. The dashboard compares `ExpireTimeStamp` with the current
time, so the badge closes on time regardless.

## Tests

```bash
cd ~/AdvDevGenAI/01_circuit_breaker
../.venv/bin/python -m pytest tests/ -q
```

The tests use fakes and need no AWS access. They cover resource resolution,
error handling, execution history, circuit-state logic and the UI. The
dashboard itself has been tested only against these fakes, not a live stack.

## Clean up

```bash
sam delete --stack-name circuit-breaker-stack --region <region>
```
