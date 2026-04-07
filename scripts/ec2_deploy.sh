#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/crawlerdemo}"
IMAGE="${IMAGE:?IMAGE is required}"

mkdir -p "$APP_DIR"
cd "$APP_DIR"

# First-time setup: expect docker-compose.ec2.yml to exist in repo.
if [ ! -f docker-compose.ec2.yml ]; then
  echo "docker-compose.ec2.yml not found in $APP_DIR"
  exit 1
fi

export IMAGE

docker compose -f docker-compose.ec2.yml pull
docker compose -f docker-compose.ec2.yml up -d
docker image prune -f

echo "Deployed $IMAGE to $APP_DIR"

