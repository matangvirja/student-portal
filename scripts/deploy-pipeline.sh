#!/usr/bin/env bash
# Usage: ./scripts/deploy-pipeline.sh <connection-arn> <github-owner/repo> [branch]
source "$(dirname "$0")/common.sh"

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <connection-arn> <github-owner/repo> [branch]"
  exit 1
fi
CONNECTION_ARN="$1"
REPO_ID="$2"
BRANCH="${3:-main}"

echo "==> Deploying pipeline stack: $PIPELINE_STACK ($REPO_ID@$BRANCH)"
aws cloudformation deploy \
  --stack-name "$PIPELINE_STACK" \
  --template-file "$ROOT_DIR/infra/02-pipeline.yaml" \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides ProjectName="$PROJECT" ConnectionArn="$CONNECTION_ARN" \
      FullRepositoryId="$REPO_ID" BranchName="$BRANCH" \
  --no-fail-on-empty-changeset

echo
echo "Pipeline: $(stack_output "$PIPELINE_STACK" PipelineUrl)"
echo "It runs once now, and again on every push to $BRANCH."
