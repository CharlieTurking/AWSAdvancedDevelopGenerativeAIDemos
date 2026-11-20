# GenAI Model Selection Demo
  CT Notes - fix model selections in bedrock_adapter.py AND fix api gateway endpoint in ./web/app.js
  
Educational demonstration of provider-agnostic GenAI architecture for AWS Technical Training.

## Overview

This demo showcases intelligent model selection and routing across multiple GenAI providers (Anthropic Claude, Meta Llama, AWS Nova) through a unified AWS Bedrock Converse API interface.

## Features

- **Provider-Agnostic Architecture**: Single interface works identically across all providers
- **Intelligent Routing**: Automatic model selection based on health, performance, and query characteristics
- **Fault Tolerance**: Circuit breakers and automatic failover when providers fail
- **Real-time Monitoring**: Live provider status and performance metrics
- **Instructor Controls**: Simulate provider failures for educational demonstrations
- **Interactive Code Viewers**: Click architecture diagram components to see actual Lambda code

## Quick Start

### Prerequisites

- AWS CLI configured with appropriate credentials
- AWS SAM CLI installed ([Installation Guide](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html))
- Access to AWS Bedrock models in your account

### Deployment

```bash
# Deploy the entire stack
./deploy-sam.sh
```

That's it! The script will:
1. Build the Lambda function with dependencies
2. Deploy infrastructure using SAM
3. Upload website files to S3
4. Configure CloudFront distribution
5. Display your website URL

### Manual Deployment

```bash
# Build
sam build

# Deploy
sam deploy --resolve-s3 --capabilities CAPABILITY_IAM

# Get outputs
sam list stack-outputs --stack-name genai-model-selection-demo
```

## Architecture

- **Frontend**: Static web app (HTML/CSS/JavaScript) served via CloudFront
- **API**: API Gateway with Lambda integration
- **Compute**: Python Lambda function with intelligent routing logic
- **AI Providers**: AWS Bedrock Converse API (Anthropic, Meta, Nova)
- **Monitoring**: CloudWatch logs and metrics

## Project Structure

```
├── lambda/                 # Lambda function code
│   ├── lambda_handler.py  # Main handler
│   ├── bedrock_adapter.py # Unified Bedrock interface
│   ├── router.py          # Intelligent routing
│   ├── health_monitor.py  # Health checks
│   └── requirements.txt   # Python dependencies
├── web/                   # Frontend files
│   ├── index.html
│   ├── app.js
│   └── styles.css
├── template.yaml          # SAM template
├── samconfig.toml         # SAM configuration
└── deploy-sam.sh          # Deployment script
```

## Usage

1. Open the website URL provided after deployment
2. Submit queries through the interface
3. Watch automatic provider selection and routing
4. Use Instructor Controls to simulate failures
5. Click architecture diagram components to view code

## Jev Router Comparison

This demo includes an optional second router, **Jev**, that you can compare against the built-in Custom_Router. Jev (TypeSafe's System One decision service) does not run a model itself. It receives the query and its derived characteristics, returns a typed decision with per-model probabilities and a confidence score, and the Lambda then validates that decision against the candidate catalogue, a confidence threshold, and current model health before using it.

### Router modes

Requests accept an optional `router_mode` field. The three options are:

- **`custom`** (default, used when the field is omitted): the existing `IntelligentModelRouter` picks a model from health, performance, and query characteristics. The response keeps its existing shape.
- **`jev`**: the Jev_Router asks Jev for a decision and applies a deterministic routing policy. If Jev is unusable (not configured, timed out, errored, low confidence, unrecognised model, or the chosen model is unhealthy) the Lambda falls back to the Custom_Router and says so. The response adds a `router_used` field to `routing_info`.
- **`compare`**: both routers run against the same health snapshot and the same query, and the response includes a `routing_comparison` object. No model runs unless you also send `execute_router`.

The key difference: the Custom_Router is a local heuristic that always chooses one of the available models, while the Jev_Router delegates the decision to an external service and then guards that decision with a policy that can fall back to Custom. Comparing them shows where an external decision service agrees or disagrees with the local heuristic.

### Works without a key

The demo runs fully without a TypeSafe key. When no key is configured, `GET /health` reports Jev as `"configured": false`, the web UI disables the Jev and Compare options and labels them "not configured", and Custom mode behaves exactly as before. You only need a key if you want to exercise Jev.

### Privacy note

When Jev or Compare mode is used, the **query text is sent to TypeSafe** (`https://api.typesafe.ai`) along with the derived query characteristics, so Jev can make its decision. Custom mode never sends the query off the AWS account. The web UI shows this notice whenever Jev or Compare is selected. (In the optional recorded mode, the query is not sent; see below.)

### Creating the Jev secret

The stack does **not** create or store the key. You create it yourself in AWS Systems Manager Parameter Store or AWS Secrets Manager, and only the secret *name* is ever passed to the deployment. Read the key value from a hidden prompt or a file so it never lands in your shell history or in the repository.

Parameter Store (SecureString), value read from a hidden prompt:

```bash
# Prompt for the key without echoing it or leaving it in shell history
read -rs -p "TypeSafe API key: " JEV_KEY && echo

aws ssm put-parameter \
  --name /genai-demo/jev-api-key \
  --type SecureString \
  --value "$JEV_KEY"

unset JEV_KEY
```

Secrets Manager, value read from a file (delete the file afterwards):

```bash
# Write the key into a local file (e.g. with your editor), then:
aws secretsmanager create-secret \
  --name genai-demo/jev-api-key \
  --secret-string "file://jev-key.txt"

rm jev-key.txt
```

Do not type the key directly on the command line and do not commit it anywhere.

### Deploying with the secret name

Pass only the secret **name** to the deployment. The Lambda reads the value at runtime using the stack's IAM permissions.

```bash
# Parameter Store
sam deploy --parameter-overrides \
  JevSecretName=/genai-demo/jev-api-key \
  JevSecretType=ssm

# Secrets Manager
sam deploy --parameter-overrides \
  JevSecretName=genai-demo/jev-api-key \
  JevSecretType=secretsmanager
```

The `deploy-sam.sh` script passes these overrides automatically when the `JEV_SECRET_NAME` environment variable is set (it holds a name, never a key):

```bash
export JEV_SECRET_NAME=/genai-demo/jev-api-key
export JEV_SECRET_TYPE=ssm   # or secretsmanager
./deploy-sam.sh
```

### Configuration

| Environment variable | Default | Purpose |
|---|---|---|
| `JEV_SECRET_NAME` | `""` (empty) | Name of the SSM parameter or Secrets Manager secret holding the key. Empty means Jev is not configured. |
| `JEV_SECRET_TYPE` | `ssm` | Secret backend: `ssm` or `secretsmanager`. |
| `JEV_CONFIDENCE_THRESHOLD` | `0.3` | Default minimum confidence Jev must report before its choice is accepted. Below this the Lambda falls back to Custom. Can be overridden per request via the `confidence_threshold` body field or the UI slider. |
| `JEV_TIMEOUT_SECONDS` | `5` | Wall-clock deadline for the Jev call. On timeout the Lambda falls back to Custom. |

### Request fields

Both fields are optional and added to the existing `POST /query` body:

- `router_mode`: `"custom"` (default), `"jev"`, or `"compare"`.
- `execute_router`: `"custom"` or `"jev"`. Only meaningful in `compare` mode; it names which router's chosen model actually runs. Omit it to compare routing decisions without running any model.
- `confidence_threshold`: a number in `0.0`-`1.0`. Overrides `JEV_CONFIDENCE_THRESHOLD` for this one request. When omitted, the configured default is used. The web UI exposes this as a "Jev confidence threshold" slider that initialises from `/health` and lets a presenter watch Jev accept its choice (low threshold) versus fall back to Custom (high threshold) live.

### The `routing_comparison` response object

Compare responses include a `routing_comparison` object with a `custom` result, a `jev` result, and an `agree` flag that is `true` when both routers chose the same model ID:

```json
{
  "routing_comparison": {
    "agree": false,
    "custom": {
      "router": "custom",
      "model_id": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
      "provider": "anthropic",
      "confidence": 0.12,
      "latency_ms": 4,
      "reasoning": ["..."],
      "fallback": false,
      "fallback_reason": null
    },
    "jev": {
      "router": "jev",
      "router_used": "jev",
      "model_id": "openai.gpt-oss-20b-1:0",
      "provider": "openai",
      "confidence": 0.91,
      "jev_confidence": 0.91,
      "latency_ms": 143,
      "reasoning": ["..."],
      "fallback": false,
      "fallback_reason": null,
      "probabilities": {
        "us.anthropic.claude-haiku-4-5-20251001-v1:0": 0.06,
        "openai.gpt-oss-20b-1:0": 0.91,
        "amazon.nova-pro-v1:0": 0.03
      },
      "high_consequence": null,
      "mode": "live"
    }
  }
}
```

When the Jev path falls back, the `jev` result has `fallback: true`, a `fallback_reason` (for example `timeout`, `low_confidence`, `unrecognised`, `unhealthy_choice`, or `not_configured`), and its `model_id` equals the Custom result's, so `agree` is `true` and the UI labels it "Fallback to Custom". In `jev` mode (not compare), the same `router_used` field appears directly on `routing_info`.

The `/health` response gains a `jev` object so the UI can configure itself:

```json
{ "jev": { "configured": false, "mode": "live", "confidence_threshold": 0.3 } }
```

### Optional recorded mode

For demos without a live TypeSafe account, set `JEV_MODE=recorded`. The Lambda then answers from `lambda/jev_recordings.json` instead of calling the API. In recorded mode no key is needed, the query text is not sent to TypeSafe, `/health` reports `"mode": "recorded"`, and every Jev result is labelled "recorded sample, not live" in the UI. A query with no matching recording falls back to Custom.

### Cleaning up the Jev secret

The CloudFormation stack does not own the secret, so deleting the stack leaves it in place. After you tear down the stack (see Cleanup below), delete the secret yourself:

```bash
# Parameter Store
aws ssm delete-parameter --name /genai-demo/jev-api-key

# Secrets Manager
aws secretsmanager delete-secret \
  --secret-id genai-demo/jev-api-key \
  --force-delete-without-recovery
```

## Educational Value

This demo teaches:
- Provider-agnostic API design patterns
- Intelligent routing algorithms
- Circuit breaker and failover patterns
- Health monitoring and observability
- Serverless architecture on AWS

## Cleanup

### Automated Cleanup (Recommended)

```bash
# Run the cleanup script (handles everything automatically)
./cleanup-deployment.sh
```

The cleanup script will:
1. Empty the S3 bucket (required before deletion)
2. Delete the CloudFormation stack
3. Remove all AWS resources (CloudFront, Lambda, API Gateway, IAM roles)
4. Clean up local SAM artifacts
5. Wait for completion and confirm success

See [CLEANUP-GUIDE.md](CLEANUP-GUIDE.md) for detailed documentation.

### Manual Cleanup

```bash
# Empty S3 bucket first
aws s3 rm s3://genai-demo-website-<account-id>/ --recursive

# Delete the stack
aws cloudformation delete-stack --stack-name genai-model-selection-demo

# Wait for deletion
aws cloudformation wait stack-delete-complete --stack-name genai-model-selection-demo
```

> **Jev secret:** the stack does not own the TypeSafe secret. If you created one, delete it separately after the stack is gone — see [Cleaning up the Jev secret](#cleaning-up-the-jev-secret).

## License

Educational demonstration for AWS Technical Training.
