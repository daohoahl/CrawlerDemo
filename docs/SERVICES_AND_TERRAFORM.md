# Nguyên lý dịch vụ AWS và hướng dùng Terraform trong project Crawler

Tài liệu này dành cho người **chưa thạo Terraform**: giải thích **dịch vụ làm gì**, **cơ chế vận hành** trong kiến trúc Scope 1, và **Terraform dùng như thế nào** trong repo này.

---

## Mục lục

1. [Terraform là gì — từ vựng tối thiểu](#1-terraform-là-gì--từ-vựng-tối-thiểu)
2. [Cấu trúc thư mục Terraform trong repo](#2-cấu-trúc-thư-mục-terraform-trong-repo)
3. [Thứ tự module và lý do phụ thuộc](#3-thứ-tự-module-và-lý-do-phụ-thuộc)
4. [Từng dịch vụ AWS: nguyên lý, cơ chế, Terraform](#4-từng-dịch-vụ-aws-nguyên-lý-cơ-chế-terraform)
5. [Làm việc với Terraform từ zero](#5-làm-việc-với-terraform-từ-zero)
6. [Các lệnh thường dùng](#6-các-lệnh-thường-dùng)
7. [Câu hỏi thường gặp](#7-câu-hỏi-thường-gặp)

---

## 1. Terraform là gì — từ vựng tối thiểu

### 1.1 Infrastructure as Code (IaC)

Thay vì bấm từng bước trên AWS Console để tạo VPC, RDS, Lambda…, bạn **mô tả hạ tầng bằng file cấu hình**. Terraform đọc các file đó, so sánh với **state** (trạng thái đã tạo trên cloud) và tạo/sửa/xóa tài nguyên cho khớp.

### 1.2 Khái niệm cần nhớ

| Khái niệm | Ý nghĩa ngắn gọn |
|-----------|------------------|
| **Provider** | Plugin nói chuyện với API (ở đây `hashicorp/aws`). Khai báo trong `required_providers` và dùng `provider "aws" { ... }`. |
| **Resource** | Một tài nguyên cụ thể, ví dụ `aws_sqs_queue.main`. Có **loại** + **tên local** (trong file). |
| **Module** | Gói tái sử dụng: một thư mục chứa nhiều resource được tham số hóa. Trong repo: `modules/networking`, `modules/queue`, … |
| **Variable** | Giá trị đầu vào (region, mật khẩu DB, account id…). Định nghĩa trong `variables.tf`, gán qua `terraform.tfvars` hoặc `TF_VAR_*`. |
| **Output** | Giá trị xuất ra sau khi apply (URL queue, endpoint RDS, tên ASG…). Dùng để copy sang bước deploy Docker / `psql`. |
| **State** | File Terraform ghi lại ID tài nguyên đã tạo (để lần sau biết sửa đúng cái nào). Thường lưu remote (S3 backend + lockfile) trong production. |
| **Plan** | Xem trước Terraform sẽ **tạo / sửa / xóa** gì — **luôn đọc kỹ** trước khi apply. |
| **Apply** | Áp dụng thay đổi lên AWS. |

### 1.3 Vì sao có `main.tf`, `variables.tf`, `outputs.tf`?

Quy ước phổ biến (không bắt buộc tên file):

- `main.tf` — provider, locals, gọi `module "..."`.
- `variables.tf` — biến đầu vào của environment.
- `outputs.tf` — kết quả in ra.
- `backend.tf` — backend state (remote S3 / local).

Terraform **gộp mọi file `.tf` trong cùng thư mục** thành một cấu hình.

---

## 2. Cấu trúc thư mục Terraform trong repo

```
infrastructure/terraform/
├── modules/                    # Khối xây dựng tái sử dụng
│   ├── networking/           # VPC, subnet, NAT, endpoint S3
│   ├── security/             # KMS, IAM, Security Group, Secrets Manager
│   ├── queue/                # SQS Standard + DLQ
│   ├── storage/              # RDS PostgreSQL + S3
│   ├── worker/               # ECR, Launch Template, ASG, scaling
│   ├── lambda/               # Lambda + event source mapping SQS
│   └── observability/        # CloudWatch, SNS, dashboard
│
└── environments/demo/        # Môi trường “gắn” module lại với nhau
    ├── main.tf               # Toàn bộ wiring + provider
    ├── variables.tf          # Biến cho demo
    ├── outputs.tf            # Output sau deploy
    ├── backend.tf            # Cấu hình state backend
    └── terraform.tfvars.example   # Mẫu — copy thành terraform.tfvars
```

**Ý tưởng:** `modules/*` = “bộ phận máy”; `environments/demo` = “lắp rap một xe cụ thể” với giá trị biến của bạn.

---

## 3. Thứ tự module và lý do phụ thuộc

Trong `environments/demo/main.tf` thứ tự gần đúng như sau (và có `depends_on` khi cần):

1. **networking** — nền: VPC, subnet, route, NAT, S3 endpoint. Không có VPC thì không gắn RDS/Lambda/EC2 đúng chỗ được.
2. **security** — KMS, Secrets, IAM role, Security Group. Queue và RDS thường cần KMS ARN và SG.
3. **queue** — SQS + DLQ (mã hóa bằng KMS).
4. **storage** — RDS trong DB subnet + SG RDS; S3 buckets.
5. **lambda** — cần queue ARN, subnet private, SG Lambda, endpoint/secret DB.
6. **worker** — cần queue URL, bucket raw, networking + IAM instance profile.
7. **observability** — alarm/dashboard cần tên Lambda, RDS, DLQ, ASG đã tồn tại.

Thứ tự này phản ánh **phụ thuộc thực tế**: mạng → bảo mật → hàng đợi/lưu trữ → ứng dụng → giám sát.

---

## 4. Từng dịch vụ AWS: nguyên lý, cơ chế, Terraform

### 4.1 Amazon VPC & networking

**Nguyên lý:** Cô lập mạng ảo của bạn: IP range riêng, subnet, bảng route, Internet Gateway, NAT.

**Cơ chế trong project:**

- **Public subnet:** có route `0.0.0.0/0` → Internet Gateway (ví dụ NAT đặt ở đây).
- **Private subnet:** default route internet qua **NAT Gateway** (instance/Lambda ra ngoài được nhưng không có IP public).
- **DB subnet:** chỉ dùng cho RDS; thường **không** NAT trực tiếp vào DB — RDS chỉ nhận kết nối nội bộ.
- **VPC Endpoint (S3 gateway):** lưu lượng tới S3 **không đi qua NAT** (tiết kiệm chi phí, hiệu năng tốt hơn).

**Terraform:** `modules/networking/main.tf` (`aws_vpc`, `aws_subnet`, `aws_route_table`, `aws_nat_gateway`, `aws_vpc_endpoint` s3, …).

---

### 4.2 Security Groups (SG)

**Nguyên lý:** Firewall **stateful** ở cấp ENI: cho phép cổng/protocole theo nguồn (CIDR hoặc SG khác).

**Cơ chế trong project (mô hình típ):**

- **Worker SG:** egress cần thiết (HTTPS tới web, SQS, S3, ECR…).
- **Lambda SG:** egress tới RDS `5432`, S3, SQS, Secrets…
- **RDS SG:** **chỉ** ingress `5432` **từ SG Lambda** (giảm bề mặt tấn công).

**Terraform:** `modules/security/main.tf` (các `aws_security_group`).

---

### 4.3 AWS KMS & Secrets Manager

**Nguyên lý:**

- **KMS:** quản lý khóa mã hóa; SQS/S3/RDS có thể dùng CMK.
- **Secrets Manager:** lưu secret (ở đây có thể dùng cho chuỗi kết nối DB); rotate được (tùy cấu hình).

**Cơ chế:** Lambda/EC2 được IAM cho phép `kms:Decrypt` / `secretsmanager:GetSecretValue` tới resource cụ thể.

**Terraform:** `modules/security/` — `aws_kms_key`, quan hệ tới queue/S3/RDS tùy module.

---

### 4.4 IAM Roles & Instance Profile

**Nguyên lý:** Không gắn access key vào code. **Lambda execution role** và **EC2 instance profile** nhận temporary credentials qua STS.

**Cơ chế:**

- Lambda role: quyền gọi SQS, S3, VPC (ENI), Secrets, CloudWatch Logs…
- EC2 role: quyền gửi SQS, ghi S3, pull ECR, (tuỳ cấu hình) SSM, CloudWatch agent…

**Terraform:** `aws_iam_role`, `aws_iam_role_policy_attachment`, `aws_iam_instance_profile` trong `modules/security/` và tham chiếu từ `modules/worker/`, `modules/lambda/`.

---

### 4.5 Amazon SQS (Standard + DLQ)

**Nguyên lý:** Hàng đợi message — producer và consumer **độc lập** thời gian và scaling.

**Cơ chế quan trọng:**

- **Visibility timeout:** sau khi consumer nhận message, message **ẩn** với consumer khác trong khoảng thời gian này. Nếu không xóa/trả lời đúng hạn, message **hiện lại** (at-least-once delivery).  
  → Phải set `VT` **đủ lớn** so với thời gian xử lý Lambda (project: **1080s**).
- **Redrive policy (DLQ):** sau `maxReceiveCount` lần nhận mà xử lý thất bại, message chuyển sang **DLQ** để không làm tắc queue chính.

**Terraform:** `modules/queue/main.tf` — `aws_sqs_queue` (main + dlq), `redrive_policy`, `aws_sqs_queue_policy` (TLS-only).

---

### 4.6 AWS Lambda

**Nguyên lý:** Chạy code theo sự kiện, không quản lý server. Scale theo số sự kiện (ở đây: batch từ SQS).

**Cơ chế trong project:**

- **Event source mapping:** Lambda kéo message từ SQS, gói tối đa **batch_size = 10**.
- **Report batch item failures:** chỉ message lỗi được trả lại queue; message thành công bị xóa.
- **SQS event-source max concurrency = 5:** giới hạn số batch xử lý song song ở event source mapping.
- **Reserved concurrency:** để `null` mặc định trong demo để tương thích account quota thấp; chỉ bật khi account cho phép.
- **VPC:** Lambda cần ENI trong private subnet để nói chuyện RDS private.

**Terraform:** `modules/lambda/main.tf` — `aws_lambda_function`, `aws_lambda_event_source_mapping`, …  
Mã nguồn: `infrastructure/aws/lambda_ingester/lambda_function.py`.  
Layer zip PostgreSQL (driver): README ghi `infrastructure/aws/postgres_pure_layer.zip` — cần có file này trước khi apply (hoặc điều chỉnh pipeline build layer).

---

### 4.7 Amazon RDS (PostgreSQL)

**Nguyên lý:** Database managed — backup, patching, monitoring một phần do AWS đảm nhiệm.

**Cơ chế trong project (Scope 1):**

- Instance class **`db.t3.micro`**, **Single-AZ** (đơn giản, rẻ; SPOF chấp nhận được cho lab/sơ khai).
- **Kết nối private** — không public endpoint (khuyến nghị).
- **Idempotency tầng DB:** `INSERT ... ON CONFLICT (canonical_url) DO NOTHING` + **UNIQUE INDEX** trên `canonical_url`.

**Terraform:** `modules/storage/main.tf` — `aws_db_instance`, subnet group, …  
Schema: `infrastructure/aws/lambda_ingester/schema.sql` (apply **sau** khi RDS lên, có đường mạng tới DB).

---

### 4.8 Amazon S3

**Nguyên lý:** Object storage — phù hợp file lớn, static, lifecycle.

**Cơ chế trong project:**

- **Raw bucket:** Claim Check — gzip payload lớn, gửi pointer trên SQS.
- **Exports bucket:** dự kiến CSV/JSON export (lifecycle/IA tuỳ module).

**Terraform:** `modules/storage/main.tf` — `aws_s3_bucket`, encryption, public access block, lifecycle.

---

### 4.9 EC2 + Auto Scaling Group + Launch Template + ECR

**Nguyên lý:**

- **EC2:** máy ảo bạn kiểm soát (ở đây chạy Docker worker).
- **Launch Template:** mẫu AMI, instance type, user-data, SG, IAM profile.
- **ASG:** giữ số instance trong khoảng **min–max**, spread **nhiều AZ** để HA phía compute.
- **ECR:** registry chứa image Docker — ASG bootstrap `docker pull` từ ECR.

**Cơ chế scaling trong spec:** CloudWatch alarm CPU **> 70%** / **< 40%** trong **3 phút** → scale out/in.

**Terraform:** `modules/worker/main.tf` — `aws_launch_template`, `aws_autoscaling_group`, `aws_ecr_repository`, policies/alarm liên quan.

---

### 4.10 CloudWatch & SNS (Observability)

**Nguyên lý:** Metric + log + alarm + thông báo (email SNS).

**Cơ chế:** Alarm khi DLQ có message, Lambda lỗi nhiều, RDS CPU cao, ASG đạt max…

**Terraform:** `modules/observability/main.tf`.

---

## 5. Làm việc với Terraform từ zero

### Bước 1 — Chuẩn bị

- Cài [Terraform](https://developer.hashicorp.com/terraform/install) ≥ 1.5 và AWS CLI đã `aws configure`.
- Có quyền IAM đủ tạo VPC, RDS, Lambda, … (thường là account lab hoặc role có policy rộng trong môi trường dev).

### Bước 2 — Biến và secret

Trong thư mục environment:

```bash
cp infrastructure/terraform/environments/demo/terraform.tfvars.example \
   infrastructure/terraform/environments/demo/terraform.tfvars
# Sửa file terraform.tfvars: aws_account_id, alert_email, region, ...
```

Mật khẩu DB không nên commit; có thể:

```bash
export TF_VAR_db_password="your-secure-password"
```

`TF_VAR_<tên biến>` sẽ map vào `variable "db_password"` trong Terraform.

Với account Free Tier, nên giữ:

```hcl
db_backup_retention_days = 1
lambda_reserved_concurrency = null
lambda_event_source_max_concurrency = 5
```

### Bước 3 — `init`

Từ thư mục gốc repo:

```bash
# Bootstrap backend bucket 1 lần trước khi init (theo backend.tf của demo)
aws s3api create-bucket \
  --bucket crawler-terraform-state-478111025341 \
  --region ap-southeast-1 \
  --create-bucket-configuration LocationConstraint=ap-southeast-1
aws s3api put-bucket-versioning \
  --bucket crawler-terraform-state-478111025341 \
  --versioning-configuration Status=Enabled

terraform -chdir=infrastructure/terraform/environments/demo init
```

- Tải provider `aws`, `archive`.
- Nếu `backend.tf` trỏ S3: bucket state phải tồn tại trước khi init (hoặc đổi sang backend local khi học).

### Bước 4 — `plan`

```bash
terraform -chdir=infrastructure/terraform/environments/demo plan
```

Đọc kỹ: sẽ tạo bao nhiêu resource, có gì **destroy** không.

### Bước 5 — `apply`

```bash
terraform -chdir=infrastructure/terraform/environments/demo apply
```

Nhập `yes` khi chắc chắn.

### Bước 6 — Sau Terraform: không nằm trong Terraform nhưng bắt buộc để chạy

1. Build & push image worker lên ECR (output `ecr_repository_url`).
2. `apply` schema SQL lên RDS (`schema.sql`).
3. `start-instance-refresh` ASG để instance mới pull image.

Chi tiết lệnh: `README.md` mục Deploy.

---

## 6. Các lệnh thường dùng

| Mục đích | Lệnh (ví dụ) |
|---------|----------------|
| Xem output | `terraform -chdir=... output` hoặc `terraform output -raw ecr_repository_url` |
| Định dạng code | `terraform fmt -recursive infrastructure/terraform` |
| Kiểm tra cú pháp | `terraform -chdir=... validate` |
| Xóa hạ tầng (cẩn thận) | `terraform -chdir=... destroy` |
| Workspace (nhiều môi trường) | Nâng cao; demo hiện dùng một folder `environments/demo`. |

---

## 7. Câu hỏi thường gặp

**Tại sao sửa code Lambda rồi DB không đổi?**  
Terraform quản **hạ tầng** và **artifact deploy** (zip/build trong module). Logic Python đổi — cần pipeline build zip / `terraform apply` lại phần Lambda nếu module tạo lại package.

**State file là gì và sao phải cẩn thận?**  
Chứa mapping “tên trong code” ↔ “ID trên AWS”. Mất state hoặc để nhầm state có thể tạo **duplicate resource** hoặc Terraform “không tìm thấy” resource cũ.

**Tôi chỉ muốn đổi instance type worker?**  
Đổi biến (ví dụ `ec2_instance_type` trong `variables.tf` / `.tfvars`) → `plan` → `apply`. Kiểm tra ASG/Launch Template version mới và instance refresh nếu cần.

**Lambda bị lỗi kết nối RDS?**  
Kiểm tra: Lambda trong đúng subnet private? SG Lambda → SG RDS mở 5432? RDS endpoint đúng? Secret/password đúng?

**Chi phí tăng không ngờ?**  
NAT Gateway thường tốn phí đáng kể trong lab nhỏ — bình thường trong kiến trúc có NAT; endpoint S3 giúp giảm một phần lưu lượng NAT.

---

## Tài liệu liên quan trong repo

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — kiến trúc và luồng dữ liệu.
- [`README.md`](../README.md) — deploy nhanh và cheat sheet spec.

---

*Tài liệu này mô tả đúng tinh thần Scope 1; khi bạn nâng cấp HA DB, CI/CD đầy đủ hoặc tách account, một số chi tiết Terraform và vận hành sẽ được bổ sung thêm.*
