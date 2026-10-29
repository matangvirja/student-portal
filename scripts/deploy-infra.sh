#!/usr/bin/env bash
# Creates the ECR repo, pushes a first image, then creates the whole app infrastructure.
# Takes ~15 minutes the first time (RDS is the slow part).
source "$(dirname "$0")/common.sh"

echo "==> [1/4] Checking AWS identity (region: $AWS_REGION)"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
echo "    Account: $ACCOUNT_ID"

echo "==> [2/4] Deploying ECR stack: $ECR_STACK"
aws cloudformation deploy \
  --stack-name "$ECR_STACK" \
  --template-file "$ROOT_DIR/infra/00-ecr.yaml" \
  --parameter-overrides ProjectName="$PROJECT" \
  --no-fail-on-empty-changeset
REPO_URI="$(stack_output "$ECR_STACK" RepositoryUri)"
echo "    Repository: $REPO_URI"

echo "==> [3/4] Building and pushing the bootstrap image"
aws ecr get-login-password | docker login --username AWS --password-stdin "${REPO_URI%%/*}"
# --platform matters on Apple Silicon Macs: Fargate tasks here run on x86_64.
docker build --platform linux/amd64 --target runtime -t "$REPO_URI:bootstrap" "$ROOT_DIR"
docker push "$REPO_URI:bootstrap"

echo "==> [4/4] Deploying infrastructure stack: $INFRA_STACK (VPC, ALB, ECS, RDS, S3...)"
aws cloudformation deploy \
  --stack-name "$INFRA_STACK" \
  --template-file "$ROOT_DIR/infra/01-infra.yaml" \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides ProjectName="$PROJECT" ImageTag=bootstrap \
  --no-fail-on-empty-changeset

echo
echo "Done. Your app:      $(stack_output "$INFRA_STACK" AppUrl)"
echo "CloudWatch dashboard: $(stack_output "$INFRA_STACK" DashboardUrl)"
echo "(Give the tasks a minute to pass health checks if you get a 503.)"
