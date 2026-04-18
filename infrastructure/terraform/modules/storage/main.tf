# =============================================================================
# MODULE: storage
#
# Creates:
#   - RDS PostgreSQL 15 (db.t3.micro, Single-AZ for Scope 1)
#   - S3 bucket for raw HTML offload (Claim Check Pattern)
#   - S3 bucket for CSV/JSON exports
#
# Spec alignment (Scope 1):
#   - db.t3.micro (Free Tier eligible)
#   - Single-AZ (`db_multi_az = false`) — cost-optimised for the demo.
#     Switching to Multi-AZ is a one-variable change for Scope 2+.
#   - UNIQUE INDEX on `canonical_url` is created by `schema.sql`, applied
#     once post-deploy (see README).
# =============================================================================

locals {
  name_prefix = "${var.project}-${var.environment}"
  tags        = merge(var.common_tags, { Module = "storage" })
}

# ═════════════════════════════════════════════════════════════════════════════
# RDS PostgreSQL
# ═════════════════════════════════════════════════════════════════════════════

resource "aws_db_subnet_group" "main" {
  name        = "${local.name_prefix}-db-subnet-group"
  description = "Subnets for RDS (isolated DB tier)"
  subnet_ids  = var.db_subnet_ids

  tags = merge(local.tags, { Name = "${local.name_prefix}-db-subnet-group" })
}

resource "aws_db_parameter_group" "main" {
  name        = "${local.name_prefix}-pg15-params"
  family      = "postgres15"
  description = "Custom parameter group for ${local.name_prefix}"

  parameter {
    name  = "log_connections"
    value = "1"
  }
  parameter {
    name  = "log_disconnections"
    value = "1"
  }
  parameter {
    name  = "log_min_duration_statement"
    value = "1000" # log statements > 1 s
  }

  tags = merge(local.tags, { Name = "${local.name_prefix}-pg15-params" })
}

resource "aws_db_instance" "main" {
  identifier           = "${local.name_prefix}-db"
  engine               = "postgres"
  engine_version       = "15"
  instance_class       = var.db_instance_class
  parameter_group_name = aws_db_parameter_group.main.name

  storage_type          = "gp3"
  allocated_storage     = var.db_allocated_storage
  max_allocated_storage = var.db_max_allocated_storage
  storage_encrypted     = true
  kms_key_id            = var.kms_key_arn

  db_name  = var.db_name
  username = var.db_username
  password = var.db_password

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [var.sg_rds_id]
  publicly_accessible    = false
  port                   = 5432

  # Scope 1: Single-AZ. Flip to true for Scope 2+.
  multi_az                = var.db_multi_az
  backup_retention_period = var.db_backup_retention_days
  backup_window           = "18:00-19:00"
  maintenance_window      = "sun:19:00-sun:20:00"

  deletion_protection        = var.db_deletion_protection
  skip_final_snapshot        = true
  apply_immediately           = false
  auto_minor_version_upgrade = true

  performance_insights_enabled    = true
  performance_insights_kms_key_id = var.kms_key_arn
  monitoring_interval             = 60
  monitoring_role_arn             = aws_iam_role.rds_monitoring.arn
  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]

  tags = merge(local.tags, { Name = "${local.name_prefix}-db" })
}

# Enhanced Monitoring role for RDS
data "aws_iam_policy_document" "rds_monitoring_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["monitoring.rds.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "rds_monitoring" {
  name               = "${local.name_prefix}-rds-monitoring-role"
  assume_role_policy = data.aws_iam_policy_document.rds_monitoring_assume.json
  tags               = local.tags
}

resource "aws_iam_role_policy_attachment" "rds_monitoring" {
  role       = aws_iam_role.rds_monitoring.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
}

# ═════════════════════════════════════════════════════════════════════════════
# S3 — Raw HTML bucket (Claim Check offload)
# ═════════════════════════════════════════════════════════════════════════════

resource "aws_s3_bucket" "raw" {
  bucket        = "${local.name_prefix}-raw-${var.aws_account_id}"
  force_destroy = true

  tags = merge(local.tags, {
    Name    = "${local.name_prefix}-raw"
    Purpose = "claim-check-raw-html"
  })
}

resource "aws_s3_bucket_server_side_encryption_configuration" "raw" {
  bucket = aws_s3_bucket.raw.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = var.kms_key_arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "raw" {
  bucket                  = aws_s3_bucket.raw.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Auto-expire raw objects after 30 days (already ingested into RDS)
resource "aws_s3_bucket_lifecycle_configuration" "raw" {
  bucket = aws_s3_bucket.raw.id
  rule {
    id     = "expire-raw-payloads"
    status = "Enabled"
    filter {}
    expiration {
      days = var.raw_expiration_days
    }
  }
}

# ═════════════════════════════════════════════════════════════════════════════
# S3 — Exports bucket (CSV / JSON deliveries)
# ═════════════════════════════════════════════════════════════════════════════

resource "aws_s3_bucket" "exports" {
  bucket        = "${local.name_prefix}-exports-${var.aws_account_id}"
  force_destroy = false

  tags = merge(local.tags, {
    Name    = "${local.name_prefix}-exports"
    Purpose = "csv-json-exports"
  })
}

resource "aws_s3_bucket_server_side_encryption_configuration" "exports" {
  bucket = aws_s3_bucket.exports.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = var.kms_key_arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "exports" {
  bucket                  = aws_s3_bucket.exports.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "exports" {
  bucket = aws_s3_bucket.exports.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "exports" {
  bucket = aws_s3_bucket.exports.id
  rule {
    id     = "transition-old-exports"
    status = "Enabled"
    filter {}
    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }
    noncurrent_version_expiration {
      noncurrent_days = 90
    }
  }
}
