#!/usr/bin/env bash
#
# Remove every AWS resource created by deploy.sh for the prompt-compression demo.
# Safe to run repeatedly; each step is best-effort and skips what is already gone.
#
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/config.sh"

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
echo "==> Tearing down '${APP_NAME}' in ${AWS_REGION} (account ${ACCOUNT_ID})"

############################################
# 1. App Runner service
############################################
SERVICE_ARN="$(aws apprunner list-services --region "$AWS_REGION" \
  --query "ServiceSummaryList[?ServiceName=='${SERVICE_NAME}'].ServiceArn | [0]" \
  --output text 2>/dev/null || echo "None")"

if [ "$SERVICE_ARN" != "None" ] && [ -n "$SERVICE_ARN" ]; then
  echo "==> Deleting App Runner service"
  aws apprunner delete-service --service-arn "$SERVICE_ARN" --region "$AWS_REGION" >/dev/null || true
  echo "    waiting for deletion..."
  while true; do
    STATUS="$(aws apprunner describe-service --service-arn "$SERVICE_ARN" --region "$AWS_REGION" \
      --query 'Service.Status' --output text 2>/dev/null || echo "GONE")"
    echo "    status: ${STATUS}"
    [ "$STATUS" = "GONE" ] && break
    sleep 15
  done
else
  echo "==> No App Runner service found; skipping"
fi

############################################
# 2. IAM instance role (+ inline policy)
############################################
if aws iam get-role --role-name "$INSTANCE_ROLE" >/dev/null 2>&1; then
  echo "==> Deleting instance role '${INSTANCE_ROLE}'"
  aws iam delete-role-policy --role-name "$INSTANCE_ROLE" --policy-name "$BEDROCK_POLICY" >/dev/null 2>&1 || true
  aws iam delete-role --role-name "$INSTANCE_ROLE" >/dev/null 2>&1 || true
else
  echo "==> No instance role found; skipping"
fi

############################################
# 3. IAM access role (+ managed policy)
############################################
if aws iam get-role --role-name "$ACCESS_ROLE" >/dev/null 2>&1; then
  echo "==> Deleting ECR access role '${ACCESS_ROLE}'"
  aws iam detach-role-policy \
    --role-name "$ACCESS_ROLE" \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSAppRunnerServicePolicyForECRAccess >/dev/null 2>&1 || true
  aws iam delete-role --role-name "$ACCESS_ROLE" >/dev/null 2>&1 || true
else
  echo "==> No access role found; skipping"
fi

############################################
# 4. ECR repository (force removes images)
############################################
if aws ecr describe-repositories --repository-names "$ECR_REPO" --region "$AWS_REGION" >/dev/null 2>&1; then
  echo "==> Deleting ECR repository '${ECR_REPO}' (and its images)"
  aws ecr delete-repository --repository-name "$ECR_REPO" --region "$AWS_REGION" --force >/dev/null || true
else
  echo "==> No ECR repository found; skipping"
fi

echo ""
echo "==> Teardown complete. Nothing from this demo should remain."
