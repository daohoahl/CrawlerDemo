# Crawler — Triển khai AWS (Terraform + Ansible + CI/CD)

Luồng tổng quan:

```
Internet ─► ALB (HTTP:80) ─► FastAPI Web (port 8080 on worker ASG)
                                  │
EC2 ASG Worker (Multi-AZ, t3.micro) ─► SQS Standard ─► Lambda Ingester ─► RDS PostgreSQL
         │                              (VT 1080s,      (BatchSize=10,     (db.t3.micro,
         └── Claim-Check gzip ──► S3     DLQ×3)          max ESM=5)         Single-AZ)
```

**Lần đầu (thủ công):** Terraform → có image worker trên ECR → ASG/user_data chạy container → khởi tạo schema DB (Lambda) → **Ansible** đồng bộ cấu hình worker (khuyến nghị) → kiểm tra.

**Các lần sau:** push `main` → GitHub Actions build/push image, cập nhật Lambda, rolling refresh ASG (xem mục CI/CD).

---

## Prerequisites

- AWS CLI (`aws configure` hoặc profile), Terraform ≥ 1.5, Docker (nếu build image local), Python 3.11+.
- Region mặc định trong doc: `ap-southeast-1` — sửa trong `terraform.tfvars` nếu khác.
- **Ansible (tùy chọn nhưng khuyến nghị):** Session Manager plugin (`session-manager-plugin`), key pair EC2 + file `.pem` cho worker, quyền `ec2:DescribeInstances` + `ssm:StartSession`.

---

## 1. Terraform — dựng hạ tầng

**1.1 — State bucket (một lần / account, nếu chưa có):**

```bash
aws s3api create-bucket \
  --bucket crawler-terraform-state-478111025341 \
  --region ap-southeast-1 \
  --create-bucket-configuration LocationConstraint=ap-southeast-1
aws s3api put-bucket-versioning \
  --bucket crawler-terraform-state-478111025341 \
  --versioning-configuration Status=Enabled
```

**1.2 — Biến:** tạo `infrastructure/terraform/environments/demo/terraform.tfvars` (không commit file thật). Tối thiểu:

- `aws_account_id`, `aws_region`, `project`, `environment`
- `alert_email`
- `worker_ec2_key_name` — **tên** key pair đã tạo trong EC2 (cùng region); cần cho SSH/Ansible qua SSM. Sau khi thêm/sửa key, ASG phải có **instance mới** (instance refresh hoặc terminate instance cũ) thì máy mới có public key.
- Mật khẩu DB: `export TF_VAR_db_password='...'` (≥ 8 ký tự) hoặc đặt trong `terraform.tfvars` nếu bạn chọn quản lý cục bộ (vẫn không nên commit).

**1.3 — Apply:**

```bash
terraform -chdir=infrastructure/terraform/environments/demo init
terraform -chdir=infrastructure/terraform/environments/demo apply
```

**1.4 — Lấy output hữu ích:**

```bash
terraform -chdir=infrastructure/terraform/environments/demo output -raw web_dashboard_url
terraform -chdir=infrastructure/terraform/environments/demo output -raw ecr_repository_url
terraform -chdir=infrastructure/terraform/environments/demo output -raw worker_launch_template_key_name
terraform -chdir=infrastructure/terraform/environments/demo output -raw worker_asg_name
```

---

## 2. Image worker trên ECR

ASG khởi chạy instance với **user_data** — script sẽ `docker pull` image `latest` từ ECR. Cần **ít nhất một lần** có image trong repo trước (hoặc instance sẽ retry kéo ảnh).

**Cách A — GitHub Actions:** push lên nhánh `main` (sau khi cấu hình OIDC + secrets trong mục CI/CD bên dưới). Pipeline build `linux/amd64`, push ECR và refresh ASG.

**Cách B — Thủ công (ví dụ):**

```bash
REGION=ap-southeast-1
REPO=$(terraform -chdir=infrastructure/terraform/environments/demo output -raw ecr_repository_url)  # dạng ACCOUNT.dkr.ecr.../crawler-demo-worker
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "${REPO%%/*}"
docker build --platform linux/amd64 -t "$REPO:latest" .
docker push "$REPO:latest"
```

Sau đó (nếu instance đã boot trước khi có image): **instance refresh** hoặc **terminate** instance worker để user_data/systemd kéo lại image — hoặc đợi playbook/CI restart service.

---

## 3. Khởi tạo schema PostgreSQL (Lambda)

Schema được tạo ở cold-start Lambda; có thể gọi sớm để không chờ message SQS:

```bash
terraform -chdir=infrastructure/terraform/environments/demo apply -auto-approve   # nếu vừa đổi Lambda
aws lambda invoke --function-name crawler-demo-ingester \
  --payload '{"action":"init-schema"}' --cli-binary-format raw-in-base64-out /tmp/out.json
cat /tmp/out.json   # kỳ vọng: schema_ready / thành công tương đương
```

---

## 4. Ansible — cấu hình worker (khuyến nghị)

Playbook áp Docker, CloudWatch Agent, container worker + web, biến môi trường — **đồng bộ** với những gì Terraform user_data đã làm, và cho phép chỉnh **không** cần đổi Launch Template.

Chi tiết đầy đủ: [`infrastructure/ansible/README.md`](infrastructure/ansible/README.md).

Tóm tắt:

1. `cd infrastructure/ansible`
2. Sinh biến từ Terraform: `./scripts/render-vars-from-terraform.sh` — gộp output vào `inventory/group_vars/crawler_demo/main.yml` (và chỉnh tay nếu cần).
3. Mật khẩu DB cho container web: `cp inventory/group_vars/crawler_demo/vault.yml.example inventory/group_vars/crawler_demo/vault.yml`, điền giá trị, `ansible-vault encrypt inventory/group_vars/crawler_demo/vault.yml`.
4. Chạy (venv khuyến nghị trên macOS):

```bash
chmod +x run-site-venv.sh
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
./run-site-venv.sh --ask-vault-pass \
  -e ansible_ssh_private_key_file=$HOME/.ssh/your-worker-key.pem
```

`-e ansible_ssh_private_key_file=...` phải đi cùng lệnh `ansible-playbook` (cùng dòng hoặc nối bằng `\`), không chạy riêng `-e` trong shell.

---

## 5. Kiểm tra

- **Dashboard web:** URL từ `terraform output -raw web_dashboard_url`.
- **Worker / ingester:** CloudWatch Logs (log group worker, Lambda), SQS có message không (sau khi crawler chạy).
- **RDS:** đã `available`; bảng schema sau bước Lambda.

---

## 6. CI/CD (GitHub Actions)

Hai workflow trong `.github/workflows/`:

- `terraform-plan.yml` — PR đụng `infrastructure/terraform/**` → `fmt` + `validate` + `plan`.
- `deploy-aws.yml` — push `main` → test → build & push ECR (`:sha` + `:latest`) → cập nhật Lambda → rolling refresh ASG.

**Setup một lần**

1. IAM role `GitHubActionsRole` trust OIDC `token.actions.githubusercontent.com` (sub = repo của bạn), quyền tối thiểu: ECR push, `autoscaling:StartInstanceRefresh` / `Describe*`, `lambda:UpdateFunctionCode` / `PublishVersion`, quyền tương ứng với S3 state nếu dùng remote backend.
2. GitHub → **Settings → Secrets and variables → Actions**:
   - `AWS_ACCOUNT_ID`
   - `TF_VAR_DB_PASSWORD` (cho job plan nếu cần)

Sau đó mỗi lần `git push` lên `main` là pipeline deploy (image + Lambda + ASG).

---

## Troubleshooting (tóm tắt)

| Triệu chứng | Hướng xử lý |
| ----------- | ----------- |
| `terraform init`: bucket không tồn tại | Làm mục **1.1** (state bucket). |
| Worker không có key pair trên EC2 | Đặt `worker_ec2_key_name` trong tfvars → `apply` → instance refresh / instance mới. |
| Ansible: `Permission denied (publickey)` | Key đúng cặp với LT; instance mới sau khi gắn key; `-e ansible_ssh_private_key_file=...`. |
| Ansible: `Could not resolve hostname i-...` | Đã cấu hình trong `inventory/group_vars/crawler_demo/connection.yml` — xem [`infrastructure/ansible/README.md`](infrastructure/ansible/README.md). |
| `dnf` / curl conflict trên AL2023 | Playbook base role **không** cài gói `curl` (dùng `curl-minimal` sẵn AMI). |
| Worker không kéo image mới | CI gọi instance refresh; tay: `aws autoscaling start-instance-refresh --auto-scaling-group-name crawler-demo-worker-asg --region ap-southeast-1` (và preferences phù hợp). |

---

## Outputs hay dùng

```bash
terraform -chdir=infrastructure/terraform/environments/demo output
```

Gồm: `rds_endpoint`, `sqs_queue_url`, `ecr_repository_url`, `worker_asg_name`, `lambda_function_name`, `web_dashboard_url`, v.v.

Tài liệu kiến trúc: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · [`docs/SERVICES_AND_TERRAFORM.md`](docs/SERVICES_AND_TERRAFORM.md) · [`docs/ARCHITECTURE_SOLUTION_TERRAFORM_MAP.md`](docs/ARCHITECTURE_SOLUTION_TERRAFORM_MAP.md).
