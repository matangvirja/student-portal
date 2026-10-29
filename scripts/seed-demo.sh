#!/usr/bin/env bash
# Fills the AWS deployment with a demo semester (faculty, students, courses, submissions, grades)
# by running `flask seed-demo` as a one-off ECS Fargate task inside the VPC.
# Safe to run twice: the second run does nothing.
source "$(dirname "$0")/common.sh"

CLUSTER="$(stack_output "$INFRA_STACK" ClusterName)"
FAMILY="$(stack_output "$INFRA_STACK" TaskDefinitionFamily)"
SUBNETS="$(stack_output "$INFRA_STACK" TaskSubnets)"
SG="$(stack_output "$INFRA_STACK" AppSecurityGroupId)"

echo "==> Starting one-off task in $CLUSTER"
TASK_ARN="$(aws ecs run-task \
  --cluster "$CLUSTER" \
  --task-definition "$FAMILY" \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNETS],securityGroups=[$SG],assignPublicIp=ENABLED}" \
  --overrides '{"containerOverrides":[{"name":"web","command":["flask","seed-demo"]}]}' \
  --query 'tasks[0].taskArn' --output text)"
echo "    $TASK_ARN"

echo "==> Waiting for it to finish (about 1 minute)"
aws ecs wait tasks-stopped --cluster "$CLUSTER" --tasks "$TASK_ARN"
EXIT_CODE="$(aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$TASK_ARN" \
  --query 'tasks[0].containers[0].exitCode' --output text)"

echo "==> Output:"
aws logs tail "/ecs/$PROJECT" --since 10m --format short \
  --log-stream-names "web/web/${TASK_ARN##*/}" 2>/dev/null | grep -v '"event"' || true

[[ "$EXIT_CODE" == "0" ]] && echo "Done. Sign in at $(stack_output "$INFRA_STACK" AppUrl)" \
  || { echo "Seed task exited with code $EXIT_CODE"; exit 1; }
