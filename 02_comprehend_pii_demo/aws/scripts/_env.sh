#!/usr/bin/env bash
# Shared setup for deploy.sh and teardown.sh (sourced, not run).
# Leaves you in aws/ with node (via .nvmrc), the shared venv, and the CDK env vars ready.

AWS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$AWS_DIR"

fail() { echo "ERROR: $*" >&2; exit 1; }

# Shared venv at the repo root (see START-VENV.md): cdk.json runs ../../.venv/bin/python3
[ -x "../../.venv/bin/python3" ] || fail "Shared venv not found at ~/AdvDevGenAI/.venv. See START-VENV.md."
export PATH="$(cd ../../.venv/bin && pwd):$PATH"
python3 -c "import aws_cdk" 2>/dev/null || fail "aws-cdk-lib is not installed in the shared venv. Run: pip install -r requirements.txt (repo root)."

# Node for the CDK CLI, from .nvmrc
export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
# shellcheck disable=SC1091
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" && nvm use >/dev/null 2>&1
command -v cdk >/dev/null || fail "The CDK CLI was not found. Install it with: npm install -g aws-cdk"

# Which account and region will be used
IDENTITY="$(aws sts get-caller-identity --query Arn --output text 2>/dev/null)" \
    || fail "No valid AWS credentials. Configure the AWS CLI or export AWS_PROFILE / keys, then retry."
export CDK_DEFAULT_ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
export CDK_DEFAULT_REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-$(aws configure get region 2>/dev/null || true)}}"
export CDK_DEFAULT_REGION="${CDK_DEFAULT_REGION:-us-east-1}"
echo "Account: $CDK_DEFAULT_ACCOUNT   Region: $CDK_DEFAULT_REGION"
echo "Identity: $IDENTITY"
