# Terraform — AWS Crawler Infrastructure

Production-Ready **Scope 1** deployment:

```
Internet ──► ALB (HTTP) ──► FastAPI dashboard on worker ASG (port 8080)
                                  │
EC2 ASG Worker (Multi-AZ, t3.micro) ──► SQS Standard ──► Lambda Ingester ──► RDS PostgreSQL
                                         (VT=1080s,      (max ESM=5,        (db.t3.micro,
                                          DLQ×3)          BatchSize=10)      Single-AZ)
                                                                                │
                                                                                ▼
                                                                         S3 (raw + exports)
```

## Layout

```
infrastructure/terraform/
├── environments/
│   └── demo/                     # Wires up all modules + chooses sizes
├── modules/
│   ├── networking/               # VPC, Multi-AZ subnets, NAT, S3 Endpoint
│   ├── security/                 # KMS, Secrets Manager, SGs, IAM
│   ├── queue/                    # SQS Standard main + DLQ (maxReceiveCount=3, VT=1080s)
│   ├── storage/                  # RDS PostgreSQL, S3 raw + S3 exports
│   ├── worker/                   # EC2 ASG (Multi-AZ, t3.micro, 1/1/2), CPU scaling 70/40
│   ├── lambda/                   # Lambda ingester + SQS event source mapping
│   └── observability/            # SNS alerts + CloudWatch alarms + dashboard
└── README.md
```

## Deploy

```bash
# 0. AWS auth (example)
aws sts get-caller-identity

# 1. Configure variables
cp environments/demo/terraform.tfvars.example environments/demo/terraform.tfvars
# Defaults already set in example:
# - aws_account_id=478111025341
# - alert_email=duyhung81002x@gmail.com
# - db_backup_retention_days=1 (Free Tier-safe)
# Keep DB password default requested for this project:
export TF_VAR_db_password="12345678"

# 2. Bootstrap Terraform remote state backend (run once per account/region)
aws s3api create-bucket \
  --bucket crawler-terraform-state-478111025341 \
  --region ap-southeast-1 \
  --create-bucket-configuration LocationConstraint=ap-southeast-1
aws s3api put-bucket-versioning \
  --bucket crawler-terraform-state-478111025341 \
  --versioning-configuration Status=Enabled

# 3. Initialise + apply
terraform -chdir=environments/demo init
terraform -chdir=environments/demo plan
terraform -chdir=environments/demo apply

# 4. Build + push the worker image to ECR
# Note: if this is your first deployment and app instances started before
# pushing the image, do this step then run step 6 (instance refresh).
ECR=$(terraform -chdir=environments/demo output -raw ecr_repository_url)
aws ecr get-login-password --region ap-southeast-1 | docker login --username AWS --password-stdin "$ECR"
docker build --platform linux/amd64 -t "$ECR:latest" ../..
docker push "$ECR:latest"

# 5. Init DB schema via Lambda (cloud-native, no local psql/SSM tunnel)
aws lambda invoke --function-name crawler-demo-ingester \
  --payload '{"action":"init-schema"}' --cli-binary-format raw-in-base64-out /tmp/out.json
cat /tmp/out.json

# 6. Refresh ASG instances so they pull the latest worker image
aws autoscaling start-instance-refresh \
  --auto-scaling-group-name "$(terraform -chdir=environments/demo output -raw worker_asg_name)"

# 7. Get public web URL
terraform -chdir=environments/demo output -raw web_dashboard_url
```

## Backend note

- Remote state backend for `environments/demo` is S3 (`backend.tf`).
- State locking uses `use_lockfile = true` in S3 backend (no DynamoDB lock table required).

## Key spec parameters baked in

| Area                 | Parameter                     | Value    |
| -------------------- | ----------------------------- | -------- |
| EC2 ASG              | `instance_type`               | t3.micro |
| EC2 ASG              | `desired / min / max`         | 1 / 1 / 2|
| EC2 ASG              | AZs                           | ≥ 2      |
| EC2 ASG scale-out    | CPU > 70% for 3 × 60s         | +1       |
| EC2 ASG scale-in     | CPU < 40% for 3 × 60s         | −1       |
| SQS main queue       | `VisibilityTimeout`           | 1080 s   |
| SQS redrive policy   | `maxReceiveCount`             | 3        |
| Lambda               | `batch_size`                  | 10       |
| Lambda               | `maximum_concurrency` (SQS ESM) | 5      |
| Lambda               | `ReportBatchItemFailures`     | enabled  |
| RDS                  | class / AZ                    | db.t3.micro / Single-AZ |
| RDS                  | `backup_retention_period`     | 1 day (Free Tier-safe) |
| RDS                  | `UNIQUE INDEX(canonical_url)` | enforced by schema.sql |
