#!/usr/bin/env bash
# Sends 20 requests to the ALB and prints which ECS task answered each one.
source "$(dirname "$0")/common.sh"

URL="${1:-$(stack_output "$INFRA_STACK" AppUrl)}"
echo "Hitting $URL/api/server 20 times..."
for i in $(seq 1 20); do
  printf '%2d  ' "$i"
  curl -s "$URL/api/server"
  echo
done
