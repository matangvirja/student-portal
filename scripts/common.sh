#!/usr/bin/env bash
# Shared settings for the deploy scripts. Override with env vars, e.g.
#   PROJECT=my-portal AWS_REGION=us-east-1 ./scripts/deploy-infra.sh
set -euo pipefail

PROJECT="${PROJECT:-student-portal}"
export AWS_REGION="${AWS_REGION:-ap-south-1}"
export AWS_DEFAULT_REGION="$AWS_REGION"

ECR_STACK="${PROJECT}-ecr"
INFRA_STACK="${PROJECT}-infra"
PIPELINE_STACK="${PROJECT}-pipeline"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

stack_output() {  # stack_output <stack> <OutputKey>
  aws cloudformation describe-stacks --stack-name "$1" \
    --query "Stacks[0].Outputs[?OutputKey=='$2'].OutputValue" --output text
}

stack_exists() {
  aws cloudformation describe-stacks --stack-name "$1" >/dev/null 2>&1
}
