#!/bin/bash
# =============================================================================
# user_data.sh  — bootstraps an EC2 worker instance at first boot.
#
# Installs: Docker, CloudWatch Agent, AWS CLI v2.
# Pulls the latest worker image from ECR and runs it as a systemd service
# so that the container restarts automatically on crash / instance reboot.
# =============================================================================
set -euo pipefail
exec > >(tee /var/log/user-data.log) 2>&1

echo "[user-data] $(date -Is) starting bootstrap"

# ── 1. Base packages ────────────────────────────────────────────────────────
dnf -y update
dnf -y install docker amazon-cloudwatch-agent

systemctl enable --now docker
usermod -aG docker ec2-user

# ── 2. CloudWatch Agent (ship /var/log/*.log + Docker JSON logs) ────────────
cat > /opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json <<EOF_CWA
{
  "agent": { "metrics_collection_interval": 60 },
  "logs": {
    "logs_collected": {
      "files": {
        "collect_list": [
          {
            "file_path": "/var/log/user-data.log",
            "log_group_name": "${log_group_name}",
            "log_stream_name": "{instance_id}/user-data"
          },
          {
            "file_path": "/var/log/crawler.log",
            "log_group_name": "${log_group_name}",
            "log_stream_name": "{instance_id}/crawler"
          }
        ]
      }
    }
  }
}
EOF_CWA

/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
  -a fetch-config -m ec2 -c file:/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json -s

# ── 3. Authenticate to ECR and pull the worker image ────────────────────────
REGION="${aws_region}"
REPO_URL="${ecr_repo_url}"
IMAGE_TAG="latest"

aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "$REPO_URL"

# Retry loop — first boot can race the image push during initial deploy
for i in 1 2 3 4 5; do
  if docker pull "$REPO_URL:$IMAGE_TAG"; then
    break
  fi
  echo "[user-data] image not ready yet, retrying in 30 s ($i/5)"
  sleep 30
done

# ── 4. systemd unit: keep the worker container running ──────────────────────
cat > /etc/systemd/system/crawler-worker.service <<'EOF_SYSTEMD'
[Unit]
Description=Crawler Worker (Docker)
After=docker.service network-online.target
Requires=docker.service

[Service]
Restart=always
RestartSec=10
TimeoutStartSec=0

# Container lifecycle
ExecStartPre=-/usr/bin/docker rm -f crawler-worker
ExecStart=/usr/bin/docker run --rm --name crawler-worker \
  --log-driver=json-file \
  --log-opt max-size=10m --log-opt max-file=3 \
  -e CRAWLER_SCHEDULE_MODE=idle \
  -e CRAWLER_INTERVAL_SECONDS=__INTERVAL_SECONDS__ \
  -e CRAWLER_MAX_ITEMS_PER_SOURCE=__MAX_ITEMS__ \
  -e CRAWLER_AWS_REGION=__REGION__ \
  -e CRAWLER_SQS_QUEUE_URL=__SQS_URL__ \
  -e CRAWLER_S3_RAW_BUCKET=__S3_BUCKET__ \
  -e CRAWLER_CLAIM_CHECK_THRESHOLD_BYTES=__CLAIM_CHECK_BYTES__ \
  -e CRAWLER_LOG_LEVEL=INFO \
  __IMAGE__

ExecStop=/usr/bin/docker stop crawler-worker

[Install]
WantedBy=multi-user.target
EOF_SYSTEMD

# Substitute template variables (avoids Terraform $${} dance inside the heredoc)
sed -i \
  -e "s#__INTERVAL_SECONDS__#${interval_seconds}#g" \
  -e "s#__MAX_ITEMS__#${max_items_per_source}#g" \
  -e "s#__REGION__#${aws_region}#g" \
  -e "s#__SQS_URL__#${sqs_queue_url}#g" \
  -e "s#__S3_BUCKET__#${s3_raw_bucket}#g" \
  -e "s#__CLAIM_CHECK_BYTES__#${claim_check_threshold_bytes}#g" \
  -e "s#__IMAGE__#$REPO_URL:$IMAGE_TAG#g" \
  /etc/systemd/system/crawler-worker.service

systemctl daemon-reload
systemctl enable --now crawler-worker.service

# ── 5. systemd unit: FastAPI dashboard on port __WEB_PORT__ ──────────────────
cat > /etc/systemd/system/crawler-web.service <<'EOF_WEB'
[Unit]
Description=Crawler Web Dashboard (Docker)
After=docker.service network-online.target
Requires=docker.service

[Service]
Restart=always
RestartSec=10
TimeoutStartSec=0

ExecStartPre=-/usr/bin/docker rm -f crawler-web
ExecStart=/usr/bin/docker run --rm --name crawler-web \
  --log-driver=json-file \
  --log-opt max-size=10m --log-opt max-file=3 \
  -p __WEB_PORT__:__WEB_PORT__ \
  -e WEB_DB_HOST=__WEB_DB_HOST__ \
  -e WEB_DB_PORT=__WEB_DB_PORT__ \
  -e WEB_DB_NAME=__WEB_DB_NAME__ \
  -e WEB_DB_USER=__WEB_DB_USER__ \
  -e WEB_DB_PASSWORD=__WEB_DB_PASSWORD__ \
  -e WEB_S3_EXPORTS_BUCKET=__S3_EXPORTS_BUCKET__ \
  -e AWS_DEFAULT_REGION=__REGION__ \
  -e CRAWLER_AWS_REGION=__REGION__ \
  -e CRAWLER_SQS_QUEUE_URL=__WEB_SQS_URL__ \
  -e CRAWLER_S3_RAW_BUCKET=__WEB_S3_RAW__ \
  -e CRAWLER_CLAIM_CHECK_THRESHOLD_BYTES=__WEB_CLAIM_CHECK__ \
  -e CRAWLER_MAX_ITEMS_PER_SOURCE=__WEB_MAX_ITEMS__ \
  __IMAGE__ \
  uvicorn crawlerdemo.webapp:app --host 0.0.0.0 --port __WEB_PORT__ --app-dir src

ExecStop=/usr/bin/docker stop crawler-web

[Install]
WantedBy=multi-user.target
EOF_WEB

sed -i \
  -e "s#__WEB_PORT__#${web_port}#g" \
  -e "s#__WEB_DB_HOST__#${web_db_host}#g" \
  -e "s#__WEB_DB_PORT__#${web_db_port}#g" \
  -e "s#__WEB_DB_NAME__#${web_db_name}#g" \
  -e "s#__WEB_DB_USER__#${web_db_user}#g" \
  -e "s#__WEB_DB_PASSWORD__#${web_db_password}#g" \
  -e "s#__S3_EXPORTS_BUCKET__#${s3_exports_bucket}#g" \
  -e "s#__REGION__#${aws_region}#g" \
  -e "s#__WEB_SQS_URL__#${sqs_queue_url}#g" \
  -e "s#__WEB_S3_RAW__#${s3_raw_bucket}#g" \
  -e "s#__WEB_CLAIM_CHECK__#${claim_check_threshold_bytes}#g" \
  -e "s#__WEB_MAX_ITEMS__#${max_items_per_source}#g" \
  -e "s#__IMAGE__#$REPO_URL:$IMAGE_TAG#g" \
  /etc/systemd/system/crawler-web.service

systemctl daemon-reload
systemctl enable --now crawler-web.service

# Stream container stdout/stderr into /var/log/crawler.log so CloudWatch
# Agent ships it without needing the Docker log driver plugin.
nohup bash -c 'while true; do docker logs -f crawler-worker >> /var/log/crawler.log 2>&1 || true; sleep 5; done' &
nohup bash -c 'while true; do docker logs -f crawler-web >> /var/log/crawler.log 2>&1 || true; sleep 5; done' &

echo "[user-data] $(date -Is) bootstrap complete"
