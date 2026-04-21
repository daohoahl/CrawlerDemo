#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
TF_DIR="$ROOT_DIR/terraform/environments/demo"
ANSIBLE_DIR="$ROOT_DIR/ansible"

ENV_TEMPLATE="$TF_DIR/env.tpl"
INI_TEMPLATE="$ANSIBLE_DIR/inventory/inventory.ini.tpl"
ENV_OUT="$TF_DIR/.runtime.env"
INI_OUT="$ANSIBLE_DIR/inventory/inventory.ini"

if ! command -v terraform >/dev/null 2>&1; then
  echo "Terraform not found. Install Terraform first." >&2
  exit 1
fi

if [[ ! -f "$ENV_TEMPLATE" || ! -f "$INI_TEMPLATE" ]]; then
  echo "Template files not found." >&2
  exit 1
fi

cd "$TF_DIR"

AWS_REGION="${AWS_REGION:-ap-southeast-1}"
AWS_ACCOUNT_ID="$(terraform output -raw kms_key_arn | awk -F: '{print $5}')"
ENVIRONMENT="${ENVIRONMENT:-demo}"
PROJECT="${PROJECT:-crawler}"

CRAWLER_ECR_REPO_URL="$(terraform output -raw ecr_repository_url)"
CRAWLER_WEB_URL="$(terraform output -raw web_dashboard_url)"
CRAWLER_SQS_QUEUE_URL="$(terraform output -raw sqs_queue_url)"
CRAWLER_S3_RAW_BUCKET="$(terraform output -raw s3_raw_bucket)"
CRAWLER_S3_EXPORTS_BUCKET="$(terraform output -raw s3_exports_bucket)"
CRAWLER_DB_HOST="$(terraform output -raw rds_endpoint)"
CRAWLER_DB_PORT="$(terraform output -raw rds_port)"
CRAWLER_DB_NAME="$(terraform output -raw db_name)"
CRAWLER_DB_USER="$(terraform output -raw db_username)"
CRAWLER_WORKER_ASG_NAME="$(terraform output -raw worker_asg_name)"
CRAWLER_CWA_LOG_GROUP_NAME="$(terraform output -raw worker_cloudwatch_log_group_name)"

ANSIBLE_GROUP="${ANSIBLE_GROUP:-crawler_demo}"
ANSIBLE_USER="${ANSIBLE_USER:-ec2-user}"
ANSIBLE_SSH_PRIVATE_KEY_FILE="${ANSIBLE_SSH_PRIVATE_KEY_FILE:-$HOME/.ssh/crawler-worker.pem}"
ANSIBLE_BASTION_USER="${ANSIBLE_BASTION_USER:-ec2-user}"
ANSIBLE_BASTION_HOST="${ANSIBLE_BASTION_HOST:-}"
ANSIBLE_WORKER_HOST="${ANSIBLE_WORKER_HOST:-10.0.12.10}"

render_template() {
  local in_file="$1"
  local out_file="$2"
  python3 - "$in_file" "$out_file" <<'PY'
import os
import sys
from pathlib import Path

in_file = Path(sys.argv[1])
out_file = Path(sys.argv[2])

text = in_file.read_text()
for key, value in os.environ.items():
    if key.startswith("TPL_"):
        text = text.replace(f"__{key[4:]}__", value)
out_file.write_text(text)
PY
}

export TPL_AWS_REGION="$AWS_REGION"
export TPL_AWS_ACCOUNT_ID="$AWS_ACCOUNT_ID"
export TPL_ENVIRONMENT="$ENVIRONMENT"
export TPL_PROJECT="$PROJECT"
export TPL_CRAWLER_ECR_REPO_URL="$CRAWLER_ECR_REPO_URL"
export TPL_CRAWLER_WEB_URL="$CRAWLER_WEB_URL"
export TPL_CRAWLER_SQS_QUEUE_URL="$CRAWLER_SQS_QUEUE_URL"
export TPL_CRAWLER_S3_RAW_BUCKET="$CRAWLER_S3_RAW_BUCKET"
export TPL_CRAWLER_S3_EXPORTS_BUCKET="$CRAWLER_S3_EXPORTS_BUCKET"
export TPL_CRAWLER_DB_HOST="$CRAWLER_DB_HOST"
export TPL_CRAWLER_DB_PORT="$CRAWLER_DB_PORT"
export TPL_CRAWLER_DB_NAME="$CRAWLER_DB_NAME"
export TPL_CRAWLER_DB_USER="$CRAWLER_DB_USER"
export TPL_CRAWLER_WORKER_ASG_NAME="$CRAWLER_WORKER_ASG_NAME"
export TPL_CRAWLER_CWA_LOG_GROUP_NAME="$CRAWLER_CWA_LOG_GROUP_NAME"
export TPL_ANSIBLE_GROUP="$ANSIBLE_GROUP"
export TPL_ANSIBLE_USER="$ANSIBLE_USER"
export TPL_ANSIBLE_SSH_PRIVATE_KEY_FILE="$ANSIBLE_SSH_PRIVATE_KEY_FILE"
export TPL_ANSIBLE_BASTION_USER="$ANSIBLE_BASTION_USER"
export TPL_ANSIBLE_BASTION_HOST="$ANSIBLE_BASTION_HOST"
export TPL_ANSIBLE_WORKER_HOST="$ANSIBLE_WORKER_HOST"

render_template "$ENV_TEMPLATE" "$ENV_OUT"
render_template "$INI_TEMPLATE" "$INI_OUT"

if [[ -z "$ANSIBLE_BASTION_HOST" ]]; then
  python3 - "$INI_OUT" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
lines = [ln for ln in p.read_text().splitlines() if "ansible_ssh_common_args" not in ln]
p.write_text("\n".join(lines) + "\n")
PY
fi

echo "Generated:"
echo "  - $ENV_OUT"
echo "  - $INI_OUT"
