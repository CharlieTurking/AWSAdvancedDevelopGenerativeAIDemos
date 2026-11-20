#!/usr/bin/env bash
#
# Deploy the context-pruning Streamlit demo to AWS App Runner.
#
# Creates (all tagged/named with APP_NAME so teardown.sh can find them):
#   - 1 ECR repository              (holds the container image)
#   - 1 IAM role  (instance role)  (lets the container call Bedrock)
#   - 1 IAM policy (Bedrock invoke) (attached to the instance role)
#   - 1 IAM role  (access role)    (lets App Runner pull from ECR)
#   - 1 App Runner service         (the public HTTPS endpoint)
#
# Requirements: awscli v2, docker, and credentials with permission to create
# the above. Run teardown.sh to remove everything.
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$(dirname "$HERE")"
source "$HERE/config.sh"

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
ECR_URI="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO}"

echo "==> Account ${ACCOUNT_ID}, region ${AWS_REGION}"
echo "==> App name: ${APP_NAME}"

############################################
# 1. ECR repository
############################################
echo "==> Ensuring ECR repository '${ECR_REPO}'"
aws ecr describe-repositories --repository-names "$ECR_REPO" --region "$AWS_REGION" >/dev/null 2>&1 \
  || aws ecr create-repository \
       --repository-name "$ECR_REPO" \
       --region "$AWS_REGION" \
       --tags Key=app,Value="$APP_NAME" >/dev/null

############################################
# 2. Build + push image
############################################
echo "==> Logging in to ECR"
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

echo "==> Building image"
docker build -t "${ECR_REPO}:${IMAGE_TAG}" "$SRC_DIR"
docker tag "${ECR_REPO}:${IMAGE_TAG}" "${ECR_URI}:${IMAGE_TAG}"

echo "==> Pushing image to ${ECR_URI}:${IMAGE_TAG}"
docker push "${ECR_URI}:${IMAGE_TAG}"

############################################
# 3. IAM: instance role (container -> Bedrock)
############################################
echo "==> Ensuring instance role '${INSTANCE_ROLE}'"
INSTANCE_TRUST='{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "tasks.apprunner.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}'
aws iam get-role --role-name "$INSTANCE_ROLE" >/dev/null 2>&1 \
  || aws iam create-role \
       --role-name "$INSTANCE_ROLE" \
       --assume-role-policy-document "$INSTANCE_TRUST" \
       --tags Key=app,Value="$APP_NAME" >/dev/null

BEDROCK_POLICY_DOC='{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
    "Resource": [
      "arn:aws:bedrock:*::foundation-model/*",
      "arn:aws:bedrock:*:'"$ACCOUNT_ID"':inference-profile/*"
    ]
  }]
}'
echo "==> Attaching inline Bedrock policy to instance role"
aws iam put-role-policy \
  --role-name "$INSTANCE_ROLE" \
  --policy-name "$BEDROCK_POLICY" \
  --policy-document "$BEDROCK_POLICY_DOC" >/dev/null
INSTANCE_ROLE_ARN="$(aws iam get-role --role-name "$INSTANCE_ROLE" --query 'Role.Arn' --output text)"

############################################
# 4. IAM: access role (App Runner -> ECR pull)
############################################
echo "==> Ensuring ECR access role '${ACCESS_ROLE}'"
ACCESS_TRUST='{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "build.apprunner.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}'
aws iam get-role --role-name "$ACCESS_ROLE" >/dev/null 2>&1 \
  || aws iam create-role \
       --role-name "$ACCESS_ROLE" \
       --assume-role-policy-document "$ACCESS_TRUST" \
       --tags Key=app,Value="$APP_NAME" >/dev/null
aws iam attach-role-policy \
  --role-name "$ACCESS_ROLE" \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSAppRunnerServicePolicyForECRAccess >/dev/null
ACCESS_ROLE_ARN="$(aws iam get-role --role-name "$ACCESS_ROLE" --query 'Role.Arn' --output text)"

# IAM is eventually consistent; give the new roles a moment before App Runner uses them.
echo "==> Waiting for IAM roles to propagate"
sleep 10

############################################
# 5. App Runner service
############################################
SOURCE_CONFIG=$(cat <<JSON
{
  "ImageRepository": {
    "ImageIdentifier": "${ECR_URI}:${IMAGE_TAG}",
    "ImageRepositoryType": "ECR",
    "ImageConfiguration": {
      "Port": "8080",
      "RuntimeEnvironmentVariables": {
        "AWS_REGION": "${AWS_REGION}",
        "BEDROCK_MODEL_ID": "${BEDROCK_MODEL_ID}"
      }
    }
  },
  "AuthenticationConfiguration": { "AccessRoleArn": "${ACCESS_ROLE_ARN}" },
  "AutoDeploymentsEnabled": false
}
JSON
)
INSTANCE_CONFIG=$(cat <<JSON
{ "InstanceRoleArn": "${INSTANCE_ROLE_ARN}" }
JSON
)

EXISTING_ARN="$(aws apprunner list-services --region "$AWS_REGION" \
  --query "ServiceSummaryList[?ServiceName=='${SERVICE_NAME}'].ServiceArn | [0]" \
  --output text 2>/dev/null || echo "None")"

if [ "$EXISTING_ARN" != "None" ] && [ -n "$EXISTING_ARN" ]; then
  echo "==> Service exists; starting a new deployment"
  aws apprunner start-deployment --service-arn "$EXISTING_ARN" --region "$AWS_REGION" >/dev/null
  SERVICE_ARN="$EXISTING_ARN"
else
  echo "==> Creating App Runner service '${SERVICE_NAME}'"
  SERVICE_ARN="$(aws apprunner create-service \
    --service-name "$SERVICE_NAME" \
    --region "$AWS_REGION" \
    --source-configuration "$SOURCE_CONFIG" \
    --instance-configuration "$INSTANCE_CONFIG" \
    --tags Key=app,Value="$APP_NAME" \
    --query 'Service.ServiceArn' --output text)"
fi

echo "==> Waiting for service to reach RUNNING (first deploy ~3-5 min)"
while true; do
  STATUS="$(aws apprunner describe-service --service-arn "$SERVICE_ARN" --region "$AWS_REGION" \
    --query 'Service.Status' --output text)"
  echo "    status: ${STATUS}"
  case "$STATUS" in
    RUNNING) break ;;
    CREATE_FAILED|DELETE_FAILED) echo "!! Service entered ${STATUS}"; exit 1 ;;
  esac
  sleep 15
done

URL="$(aws apprunner describe-service --service-arn "$SERVICE_ARN" --region "$AWS_REGION" \
  --query 'Service.ServiceUrl' --output text)"
echo ""
echo "==> Deployed. Open: https://${URL}"
echo "==> Tear it all down with: deploy/teardown.sh"
