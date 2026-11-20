#!/usr/bin/env bash
# Shared configuration for deploy/teardown of the prompt-compression demo.
# Source this from the other scripts. Override any value via environment.

# A short, unique-ish name used to tag every AWS resource this demo creates.
export APP_NAME="${APP_NAME:-genai-prompt-compression-demo}"

export AWS_REGION="${AWS_REGION:-us-east-1}"

# Bedrock model the running container will call.
export BEDROCK_MODEL_ID="${BEDROCK_MODEL_ID:-us.anthropic.claude-haiku-4-5-20251001-v1:0}"

# Derived names (kept in sync between deploy and teardown).
export ECR_REPO="${APP_NAME}"
export INSTANCE_ROLE="${APP_NAME}-instance-role"
export ACCESS_ROLE="${APP_NAME}-ecr-access-role"
export BEDROCK_POLICY="${APP_NAME}-bedrock-policy"
export SERVICE_NAME="${APP_NAME}"

# Image tag.
export IMAGE_TAG="${IMAGE_TAG:-latest}"
