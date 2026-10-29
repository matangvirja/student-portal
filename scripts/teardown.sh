#!/usr/bin/env bash
# Deletes EVERYTHING (including uploaded files and the database). Run after your demo to stop charges.
source "$(dirname "$0")/common.sh"

read -r -p "This deletes all $PROJECT resources in $AWS_REGION, including data. Type 'delete' to continue: " ans
[[ "$ans" == "delete" ]] || { echo "Cancelled."; exit 1; }

empty_bucket() {
  local b="$1"
  if [[ -n "$b" && "$b" != "None" ]]; then
    echo "    Emptying s3://$b"
    aws s3 rm "s3://$b" --recursive >/dev/null || true
  fi
}

if stack_exists "$PIPELINE_STACK"; then
  echo "==> Deleting $PIPELINE_STACK"
  empty_bucket "$(stack_output "$PIPELINE_STACK" ArtifactBucketName)"
  aws cloudformation delete-stack --stack-name "$PIPELINE_STACK"
  aws cloudformation wait stack-delete-complete --stack-name "$PIPELINE_STACK"
fi

if stack_exists "$INFRA_STACK"; then
  echo "==> Deleting $INFRA_STACK (takes ~10 minutes, RDS is slow to delete)"
  empty_bucket "$(stack_output "$INFRA_STACK" UploadsBucketName)"
  aws cloudformation delete-stack --stack-name "$INFRA_STACK"
  aws cloudformation wait stack-delete-complete --stack-name "$INFRA_STACK"
fi

if stack_exists "$ECR_STACK"; then
  echo "==> Deleting $ECR_STACK"
  aws cloudformation delete-stack --stack-name "$ECR_STACK"
  aws cloudformation wait stack-delete-complete --stack-name "$ECR_STACK"
fi

echo "All stacks deleted. (The GitHub connection is free; delete it in the console if you like.)"
