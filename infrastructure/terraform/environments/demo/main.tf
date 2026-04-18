# =============================================================================
# ENVIRONMENT: demo — Production-Ready Scope 1
#
# Data flow
#   EC2 ASG Worker (Multi-AZ, t3.micro)  ─┐
#                                         ▼
#                              SQS Standard Queue
#                              (VT=1080s, DLQ×3)
#                                         │
#                                         ▼
#                          Lambda Ingester (Reserved=50)
#                          BatchSize=10, ReportBatchItemFailures
#                          INSERT ... ON CONFLICT DO NOTHING
#                                         │
#                          ┌──────────────┴──────────────┐
#                          ▼                             ▼
#                   RDS PostgreSQL                       S3
#                  (db.t3.micro,                 (raw HTML + exports)
#                   Single-AZ Scope 1)
# =============================================================================

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = local.common_tags
  }
}

# ── Locals ───────────────────────────────────────────────────────────────────

locals {
  name_prefix = "${var.project}-${var.environment}"

  common_tags = {
    Project     = var.project
    Environment = var.environment
    ManagedBy   = "Terraform"
    Scope       = "scope-1"
  }

  # Lambda deployment artefacts (relative to this file)
  lambda_source_file = "${path.module}/../../../aws/lambda_ingester/lambda_function.py"
  lambda_layer_zip   = "${path.module}/../../../aws/postgres_pure_layer.zip"
}

# ═════════════════════════════════════════════════════════════════════════════
# 1. Networking — VPC, subnets (Multi-AZ), IGW, NAT, S3 Endpoint
# ═════════════════════════════════════════════════════════════════════════════

module "networking" {
  source = "../../modules/networking"

  project     = var.project
  environment = var.environment
  aws_region  = var.aws_region

  vpc_cidr = "10.0.0.0/16"

  # Two AZs — required by the ASG spec.
  availability_zones   = [for s in ["a", "b"] : "${var.aws_region}${s}"]
  public_subnet_cidrs  = ["10.0.1.0/24", "10.0.2.0/24"]
  private_subnet_cidrs = ["10.0.11.0/24", "10.0.12.0/24"]
  db_subnet_cidrs      = ["10.0.21.0/24", "10.0.22.0/24"]

  common_tags = local.common_tags
}

# ═════════════════════════════════════════════════════════════════════════════
# 2. Security — KMS, Secrets Manager, Security Groups, IAM roles
# ═════════════════════════════════════════════════════════════════════════════

module "security" {
  source = "../../modules/security"

  project        = var.project
  environment    = var.environment
  aws_region     = var.aws_region
  aws_account_id = var.aws_account_id

  vpc_id   = module.networking.vpc_id
  vpc_cidr = module.networking.vpc_cidr

  db_password = var.db_password

  common_tags = local.common_tags
  depends_on  = [module.networking]
}

# ═════════════════════════════════════════════════════════════════════════════
# 3. Queue — SQS Standard + DLQ
# ═════════════════════════════════════════════════════════════════════════════

module "queue" {
  source = "../../modules/queue"

  project     = var.project
  environment = var.environment
  kms_key_arn = module.security.kms_key_arn

  visibility_timeout_seconds = 1080 # spec: 18 min
  max_receive_count          = 3    # spec: DLQ after 3 fails

  common_tags = local.common_tags
  depends_on  = [module.security]
}

# ═════════════════════════════════════════════════════════════════════════════
# 4. Storage — RDS + S3
# ═════════════════════════════════════════════════════════════════════════════

module "storage" {
  source = "../../modules/storage"

  project        = var.project
  environment    = var.environment
  aws_region     = var.aws_region
  aws_account_id = var.aws_account_id

  vpc_id        = module.networking.vpc_id
  db_subnet_ids = module.networking.db_subnet_ids
  sg_rds_id     = module.security.sg_rds_id

  kms_key_arn = module.security.kms_key_arn

  db_instance_class      = var.db_instance_class
  db_backup_retention_days = var.db_backup_retention_days
  db_multi_az            = false # spec: Single-AZ for Scope 1
  db_deletion_protection = false
  db_password            = var.db_password

  common_tags = local.common_tags
  depends_on  = [module.networking, module.security]
}

# ═════════════════════════════════════════════════════════════════════════════
# 5. Lambda Ingester (Reserved Concurrency = 50, BatchSize = 10)
# ═════════════════════════════════════════════════════════════════════════════

module "lambda" {
  source = "../../modules/lambda"

  project     = var.project
  environment = var.environment
  aws_region  = var.aws_region

  vpc_id             = module.networking.vpc_id
  private_subnet_ids = module.networking.private_subnet_ids
  sg_lambda_id       = module.security.sg_lambda_id
  lambda_role_arn    = module.security.lambda_role_arn
  sqs_main_queue_arn = module.queue.main_queue_arn

  rds_endpoint = module.storage.rds_endpoint
  db_name      = module.storage.db_name
  db_username  = module.storage.db_username
  db_password  = var.db_password

  lambda_memory_mb                   = 256
  lambda_timeout_seconds             = 180
  lambda_reserved_concurrency        = var.lambda_reserved_concurrency
  lambda_event_source_max_concurrency = var.lambda_event_source_max_concurrency
  sqs_batch_size                     = 10 # spec
  log_retention_days                 = 30

  lambda_source_file = local.lambda_source_file
  lambda_layer_zip   = local.lambda_layer_zip

  common_tags = local.common_tags
  depends_on  = [module.storage, module.queue, module.security]
}

# ═════════════════════════════════════════════════════════════════════════════
# 6. Worker — EC2 ASG (Multi-AZ, t3.micro, 1/1/2)
# ═════════════════════════════════════════════════════════════════════════════

module "worker" {
  source = "../../modules/worker"

  project     = var.project
  environment = var.environment
  aws_region  = var.aws_region

  private_subnet_ids        = module.networking.private_subnet_ids
  sg_worker_id              = module.security.sg_worker_id
  iam_instance_profile_name = module.security.worker_instance_profile_name

  instance_type    = var.ec2_instance_type
  desired_capacity = 1 # spec
  min_size         = 1 # spec
  max_size         = 2 # spec

  sqs_queue_url               = module.queue.main_queue_url
  s3_raw_bucket               = module.storage.s3_raw_bucket
  interval_seconds            = var.crawler_interval_seconds
  max_items_per_source        = 100
  claim_check_threshold_bytes = 204800 # 200 KB

  log_retention_days = 30
  common_tags        = local.common_tags

  depends_on = [module.networking, module.security, module.queue, module.storage]
}

# ═════════════════════════════════════════════════════════════════════════════
# 7. Observability — SNS + alarms + dashboard
# ═════════════════════════════════════════════════════════════════════════════

module "observability" {
  source = "../../modules/observability"

  project     = var.project
  environment = var.environment
  aws_region  = var.aws_region

  lambda_function_name = module.lambda.lambda_function_name
  rds_identifier       = module.storage.rds_identifier
  dlq_name             = module.queue.dlq_name
  worker_asg_name      = module.worker.asg_name
  worker_asg_max_size  = 2

  alert_email        = var.alert_email
  log_retention_days = 30

  common_tags = local.common_tags
  depends_on  = [module.lambda, module.storage, module.queue, module.worker]
}
