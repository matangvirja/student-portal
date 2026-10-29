#!/usr/bin/env bash
# Prints the faculty access code needed to create a teacher account on the AWS deployment.
source "$(dirname "$0")/common.sh"

ARN="$(stack_output "$INFRA_STACK" TeacherInviteSecretArn)"
aws secretsmanager get-secret-value --secret-id "$ARN" --query SecretString --output text
