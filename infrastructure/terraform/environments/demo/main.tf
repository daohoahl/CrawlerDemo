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
    local = {
      source  = "hashicorp/local"
      version = "~> 2.5"
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

# Preserve state when refactoring module names/paths.
moved {
  from = module.networking
  to   = module.vpc
}

moved {
  from = module.worker
  to   = module.ec2
}

moved {
  from = module.storage.aws_db_subnet_group.main
  to   = module.rds.aws_db_subnet_group.main
}

moved {
  from = module.storage.aws_db_parameter_group.main
  to   = module.rds.aws_db_parameter_group.main
}

moved {
  from = module.storage.aws_db_instance.main
  to   = module.rds.aws_db_instance.main
}

moved {
  from = module.storage.aws_iam_role.rds_monitoring
  to   = module.rds.aws_iam_role.rds_monitoring
}

moved {
  from = module.storage.aws_iam_role_policy_attachment.rds_monitoring
  to   = module.rds.aws_iam_role_policy_attachment.rds_monitoring
}

moved {
  from = module.storage.aws_s3_bucket.raw
  to   = module.s3.aws_s3_bucket.raw
}

moved {
  from = module.storage.aws_s3_bucket_server_side_encryption_configuration.raw
  to   = module.s3.aws_s3_bucket_server_side_encryption_configuration.raw
}

moved {
  from = module.storage.aws_s3_bucket_public_access_block.raw
  to   = module.s3.aws_s3_bucket_public_access_block.raw
}

moved {
  from = module.storage.aws_s3_bucket_lifecycle_configuration.raw
  to   = module.s3.aws_s3_bucket_lifecycle_configuration.raw
}

moved {
  from = module.storage.aws_s3_bucket.exports
  to   = module.s3.aws_s3_bucket.exports
}

moved {
  from = module.storage.aws_s3_bucket_server_side_encryption_configuration.exports
  to   = module.s3.aws_s3_bucket_server_side_encryption_configuration.exports
}

moved {
  from = module.storage.aws_s3_bucket_public_access_block.exports
  to   = module.s3.aws_s3_bucket_public_access_block.exports
}

moved {
  from = module.storage.aws_s3_bucket_versioning.exports
  to   = module.s3.aws_s3_bucket_versioning.exports
}

moved {
  from = module.storage.aws_s3_bucket_lifecycle_configuration.exports
  to   = module.s3.aws_s3_bucket_lifecycle_configuration.exports
}

# ═════════════════════════════════════════════════════════════════════════════
# 1. VPC — subnets (Multi-AZ), IGW, NAT, S3 Endpoint
# ═════════════════════════════════════════════════════════════════════════════

module "vpc" {
  source = "../../modules/vpc"

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

  vpc_id   = module.vpc.vpc_id
  vpc_cidr = module.vpc.vpc_cidr

  db_password = var.db_password

  common_tags = local.common_tags
  depends_on  = [module.vpc]
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
# 4. Data Services — RDS + S3
# ═════════════════════════════════════════════════════════════════════════════

module "rds" {
  source = "../../modules/rds"

  project     = var.project
  environment = var.environment

  db_subnet_ids = module.vpc.db_subnet_ids
  sg_rds_id     = module.security.sg_rds_id

  kms_key_arn = module.security.kms_key_arn

  db_instance_class        = var.db_instance_class
  db_backup_retention_days = var.db_backup_retention_days
  db_multi_az              = false # spec: Single-AZ for Scope 1
  db_deletion_protection   = false
  db_password              = var.db_password

  common_tags = local.common_tags
  depends_on  = [module.vpc, module.security]
}

module "s3" {
  source = "../../modules/s3"

  project        = var.project
  environment    = var.environment
  aws_account_id = var.aws_account_id

  kms_key_arn = module.security.kms_key_arn

  common_tags = local.common_tags
  depends_on  = [module.security]
}

# ═════════════════════════════════════════════════════════════════════════════
# 5. Lambda Ingester (Reserved Concurrency = 50, BatchSize = 10)
# ═════════════════════════════════════════════════════════════════════════════

module "lambda" {
  source = "../../modules/lambda"

  project     = var.project
  environment = var.environment
  aws_region  = var.aws_region

  vpc_id             = module.vpc.vpc_id
  private_subnet_ids = module.vpc.private_subnet_ids
  sg_lambda_id       = module.security.sg_lambda_id
  lambda_role_arn    = module.security.lambda_role_arn
  sqs_main_queue_arn = module.queue.main_queue_arn

  rds_endpoint = module.rds.rds_endpoint
  db_name      = module.rds.db_name
  db_username  = module.rds.db_username
  db_password  = var.db_password

  lambda_memory_mb                    = 256
  lambda_timeout_seconds              = 180
  lambda_reserved_concurrency         = var.lambda_reserved_concurrency
  lambda_event_source_max_concurrency = var.lambda_event_source_max_concurrency
  sqs_batch_size                      = 10 # spec
  log_retention_days                  = 30

  lambda_source_file = local.lambda_source_file
  lambda_layer_zip   = local.lambda_layer_zip

  s3_exports_bucket = module.s3.s3_exports_bucket
  s3_exports_prefix = "auto/"

  common_tags = local.common_tags
  depends_on  = [module.rds, module.s3, module.queue, module.security]
}

# ═════════════════════════════════════════════════════════════════════════════
# 6. Worker — EC2 ASG (Multi-AZ, t3.micro, 1/1/2)
# ═════════════════════════════════════════════════════════════════════════════

module "ec2" {
  source = "../../modules/ec2"

  project     = var.project
  environment = var.environment
  aws_region  = var.aws_region

  private_subnet_ids        = module.vpc.private_subnet_ids
  sg_worker_id              = module.security.sg_worker_id
  iam_instance_profile_name = module.security.worker_instance_profile_name
  ec2_key_name              = var.worker_ec2_key_name

  instance_type    = var.ec2_instance_type
  desired_capacity = 1 # spec
  min_size         = 1 # spec
  max_size         = 2 # spec

  sqs_queue_url               = module.queue.main_queue_url
  s3_raw_bucket               = module.s3.s3_raw_bucket
  s3_exports_bucket           = module.s3.s3_exports_bucket
  interval_seconds            = var.crawler_interval_seconds
  max_items_per_source        = 100
  claim_check_threshold_bytes = 204800 # 200 KB
  web_db_host                 = module.rds.rds_endpoint
  web_db_port                 = module.rds.rds_port
  web_db_name                 = module.rds.db_name
  web_db_user                 = module.rds.db_username
  web_db_password             = var.db_password
  web_port                    = var.web_port

  log_retention_days = 30
  common_tags        = local.common_tags

  depends_on = [module.vpc, module.security, module.queue, module.rds, module.s3]
}

# ═════════════════════════════════════════════════════════════════════════════
# 7. Public Web ALB -> worker ASG (FastAPI dashboard)
# ═════════════════════════════════════════════════════════════════════════════

resource "aws_security_group" "web_alb" {
  name        = "${local.name_prefix}-sg-web-alb"
  description = "Public ALB for crawler web dashboard"
  vpc_id      = module.vpc.vpc_id

  ingress {
    description = "Allow HTTP from internet"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, { Name = "${local.name_prefix}-sg-web-alb" })
}

resource "aws_security_group_rule" "worker_web_from_alb" {
  type                     = "ingress"
  description              = "Allow web traffic from ALB to worker web container"
  from_port                = var.web_port
  to_port                  = var.web_port
  protocol                 = "tcp"
  security_group_id        = module.security.sg_worker_id
  source_security_group_id = aws_security_group.web_alb.id
}

resource "aws_lb" "web" {
  name               = "${local.name_prefix}-web-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.web_alb.id]
  subnets            = module.vpc.public_subnet_ids

  tags = merge(local.common_tags, { Name = "${local.name_prefix}-web-alb" })
}

resource "aws_lb_target_group" "web" {
  name        = "${local.name_prefix}-web-tg"
  port        = var.web_port
  protocol    = "HTTP"
  target_type = "instance"
  vpc_id      = module.vpc.vpc_id

  health_check {
    enabled             = true
    path                = "/health"
    protocol            = "HTTP"
    matcher             = "200"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 2
  }

  tags = merge(local.common_tags, { Name = "${local.name_prefix}-web-tg" })
}

resource "aws_lb_listener" "web_http" {
  load_balancer_arn = aws_lb.web.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.web.arn
  }
}

resource "aws_autoscaling_attachment" "web_tg" {
  autoscaling_group_name = module.ec2.asg_name
  lb_target_group_arn    = aws_lb_target_group.web.arn
}

# ═════════════════════════════════════════════════════════════════════════════
# 8. Observability — SNS + alarms + dashboard
# ═════════════════════════════════════════════════════════════════════════════

module "observability" {
  source = "../../modules/observability"

  project     = var.project
  environment = var.environment
  aws_region  = var.aws_region

  lambda_function_name = module.lambda.lambda_function_name
  rds_identifier       = module.rds.rds_identifier
  dlq_name             = module.queue.dlq_name
  worker_asg_name      = module.ec2.asg_name
  worker_asg_max_size  = 2

  alert_email        = var.alert_email
  log_retention_days = 30

  common_tags = local.common_tags
  depends_on  = [module.lambda, module.rds, module.s3, module.queue, module.ec2]
}

# ═════════════════════════════════════════════════════════════════════════════
# 9. Local runtime files (auto-generated after apply)
# ═════════════════════════════════════════════════════════════════════════════

resource "local_file" "runtime_env" {
  count = var.generate_runtime_files ? 1 : 0

  filename = "${path.module}/.runtime.env"
  content = templatefile("${path.module}/env.tpl", {
    aws_region                   = var.aws_region
    aws_account_id               = var.aws_account_id
    environment                  = var.environment
    project                      = var.project
    crawler_ecr_repo_url         = module.ec2.ecr_repository_url
    crawler_web_url              = "http://${aws_lb.web.dns_name}"
    crawler_sqs_queue_url        = module.queue.main_queue_url
    crawler_s3_raw_bucket        = module.s3.s3_raw_bucket
    crawler_s3_exports_bucket    = module.s3.s3_exports_bucket
    crawler_db_host              = module.rds.rds_endpoint
    crawler_db_port              = module.rds.rds_port
    crawler_db_name              = module.rds.db_name
    crawler_db_user              = module.rds.db_username
    crawler_worker_asg_name      = module.ec2.asg_name
    ansible_group                = "crawler_demo"
    ansible_user                 = var.ansible_user
    ansible_ssh_private_key_file = var.ansible_ssh_private_key_file
    ansible_bastion_user         = var.ansible_bastion_user
    ansible_bastion_host         = var.ansible_bastion_host
    ansible_worker_host          = var.ansible_worker_host
  })
}

resource "local_file" "ansible_inventory_ini" {
  count = var.generate_runtime_files ? 1 : 0

  filename = "${path.module}/../../../ansible/inventory/inventory.ini"
  content = templatefile("${path.module}/../../../ansible/inventory/inventory.ini.tpl", {
    ansible_worker_host          = var.ansible_worker_host
    ansible_user                 = var.ansible_user
    ansible_ssh_private_key_file = var.ansible_ssh_private_key_file
    ansible_bastion_user         = var.ansible_bastion_user
    ansible_bastion_host         = var.ansible_bastion_host
    aws_region                   = var.aws_region
    crawler_ecr_repo_url         = module.ec2.ecr_repository_url
    crawler_cwa_log_group_name   = module.ec2.log_group_name
    crawler_sqs_queue_url        = module.queue.main_queue_url
    crawler_s3_raw_bucket        = module.s3.s3_raw_bucket
    crawler_s3_exports_bucket    = module.s3.s3_exports_bucket
    crawler_db_host              = module.rds.rds_endpoint
    crawler_db_port              = module.rds.rds_port
    crawler_db_name              = module.rds.db_name
    crawler_db_user              = module.rds.db_username
  })
}
