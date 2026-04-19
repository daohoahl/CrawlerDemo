#!/usr/bin/env bash
# Giống user_data Terraform: gom docker logs vào /var/log/crawler.log cho CloudWatch Agent.
set -euo pipefail
while true; do docker logs -f crawler-worker >> /var/log/crawler.log 2>&1 || true; sleep 5; done &
while true; do docker logs -f crawler-web >> /var/log/crawler.log 2>&1 || true; sleep 5; done &
wait
