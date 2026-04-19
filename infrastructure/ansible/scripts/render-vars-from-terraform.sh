#!/usr/bin/env bash
# In ra YAML snippet để dán vào inventory/group_vars/crawler_demo/main.yml (không chứa mật khẩu DB).
# Chạy sau khi terraform apply, từ repo root hoặc từ thư mục này:
#   ./render-vars-from-terraform.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TF_DIR="$(cd "$SCRIPT_DIR/../../terraform/environments/demo" && pwd)"

if ! command -v terraform >/dev/null 2>&1; then
  echo "Cần cài Terraform và đã chạy terraform init trong $TF_DIR" >&2
  exit 1
fi

cd "$TF_DIR"

echo "# --- Gộp vào infrastructure/ansible/inventory/group_vars/crawler_demo/main.yml ---"
echo "# Region (sửa nếu tf workspace khác):"
echo "crawler_aws_region: ${AWS_REGION:-ap-southeast-1}"
echo ""

echo "crawler_ecr_repo_url: $(terraform output -raw ecr_repository_url)"
echo "crawler_cwa_log_group_name: $(terraform output -raw worker_cloudwatch_log_group_name)"
echo "crawler_sqs_queue_url: $(terraform output -raw sqs_queue_url)"
echo "crawler_s3_raw_bucket: $(terraform output -raw s3_raw_bucket)"
echo "crawler_s3_exports_bucket: $(terraform output -raw s3_exports_bucket)"
echo "crawler_web_db_host: $(terraform output -raw rds_endpoint)"
echo "crawler_web_db_port: $(terraform output -raw rds_port)"
echo "crawler_web_db_name: $(terraform output -raw db_name)"
echo "crawler_web_db_user: $(terraform output -raw db_username)"
echo ""
echo "# crawler_web_db_password: dùng ansible-vault hoặc: terraform output không in password (TF_VAR_db_password)"
echo "# Sao chép vault.yml.example -> vault.yml rồi: ansible-vault encrypt inventory/group_vars/crawler_demo/vault.yml"
