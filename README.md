# Crawler — AWS Deployment (Terraform + CI/CD)

Hai bước duy nhất để đưa hệ thống lên AWS:

1. **Terraform** — dựng toàn bộ hạ tầng (VPC, SQS, RDS, Lambda, ECR, ASG, CloudWatch).
2. **GitHub Actions** — mỗi lần push `main` là tự build image, update Lambda, rolling refresh ASG.

```
EC2 ASG Worker (Multi-AZ, t3.micro) ─► SQS Standard ─► Lambda Ingester ─► RDS PostgreSQL
         │                              (VT 1080s,      (BatchSize=10,     (db.t3.micro,
         └── Claim-Check gzip ──► S3     DLQ×3)          max ESM=5)         Single-AZ)
```

---

## Prerequisites

- AWS CLI đã `aws configure`, Terraform ≥ 1.5, Docker, Python 3.11.
- Region: `ap-southeast-1`, Account: `478111025341` (sửa trong `terraform.tfvars` nếu khác).

---

## 1. Terraform

```bash
# 1.1 Bootstrap state bucket (chỉ chạy 1 lần / account)
aws s3api create-bucket \
  --bucket crawler-terraform-state-478111025341 \
  --region ap-southeast-1 \
  --create-bucket-configuration LocationConstraint=ap-southeast-1
aws s3api put-bucket-versioning \
  --bucket crawler-terraform-state-478111025341 \
  --versioning-configuration Status=Enabled

# 1.2 Biến bí mật
cp infrastructure/terraform/environments/demo/terraform.tfvars.example \
   infrastructure/terraform/environments/demo/terraform.tfvars
export TF_VAR_db_password="your-strong-password"

# 1.3 Apply
terraform -chdir=infrastructure/terraform/environments/demo init
terraform -chdir=infrastructure/terraform/environments/demo apply
```

Schema DB tự tạo ở cold-start của Lambda (DDL idempotent đã nhúng trong `lambda_function.py`) — **không cần `psql`, không cần SSM tunnel**. Muốn chạy ngay không chờ message đầu tiên:

```bash
# Push code Lambda mới nhất (có DDL tự tạo schema)
terraform -chdir=infrastructure/terraform/environments/demo apply -auto-approve

# Bắn 1 phát để chạy cold-start + apply DDL
aws lambda invoke --function-name crawler-demo-ingester \
  --payload '{"action":"init-schema"}' --cli-binary-format raw-in-base64-out /tmp/out.json
cat /tmp/out.json   # {"schema_ready": true}
```

---

## 2. CI/CD (GitHub Actions)

Hai workflow sẵn trong `.github/workflows/`:

- `terraform-plan.yml` — mọi PR đụng `infrastructure/terraform/**` → `fmt + validate + plan`.
- `deploy-aws.yml` — push `main` → test → build & push ECR (`:sha` + `:latest`) → update Lambda → rolling refresh ASG.

### Setup 1 lần

1. Tạo IAM role `GitHubActionsRole` trust OIDC provider `token.actions.githubusercontent.com` (sub = repo của bạn), gắn quyền: ECR push, `autoscaling:StartInstanceRefresh/Describe*`, `lambda:UpdateFunctionCode/PublishVersion`, `s3:Get/PutObject` trên state bucket.
2. GitHub repo → **Settings → Secrets and variables → Actions**, thêm:
   - `AWS_ACCOUNT_ID` = `478111025341`
   - `TF_VAR_DB_PASSWORD` = mật khẩu DB (dùng cho job plan)

Xong. `git push` lên `main` là pipeline deploy chạy.

---

## Troubleshooting (các lỗi đã gặp)

| Lỗi                                              | Fix                                              |
| ------------------------------------------------ | ------------------------------------------------ |
| `terraform init`: bucket does not exist          | Chạy bước 1.1                                    |
| `CreateSecurityGroup` non-ASCII                  | Không dùng ký tự Unicode trong `description`     |
| `FreeTierRestrictionError` RDS backup            | `db_backup_retention_days = 1` (default rồi)     |
| `Cannot find version 15.8 for postgres`          | Để `engine_version = "15"` (đã fix)              |
| `ReservedConcurrentExecutions ... minimum 10`    | `lambda_reserved_concurrency = null` (đã fix)    |
| Worker không pull image mới                      | CI tự `start-instance-refresh`; manual: `aws autoscaling start-instance-refresh --auto-scaling-group-name crawler-demo-worker-asg` |

---

## Outputs hay dùng

```bash
terraform -chdir=infrastructure/terraform/environments/demo output
# rds_endpoint, sqs_queue_url, sqs_dlq_url,
# ecr_repository_url, worker_asg_name, lambda_function_name,
# cloudwatch_dashboard_url, sns_alert_topic_arn
```

Xem chi tiết kiến trúc: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · Giải thích service + Terraform: [`docs/SERVICES_AND_TERRAFORM.md`](docs/SERVICES_AND_TERRAFORM.md).
