# =============================================================================
# MODULE: security
#
# Creates:
#   - KMS Customer Managed Key (encrypts RDS + SQS + S3 + Secrets Manager)
#   - Secrets Manager secret for the DB credentials
#   - Security Groups (EC2 worker, Lambda, RDS)
#   - IAM roles: EC2 instance profile, Lambda execution role
# =============================================================================

locals {
  name_prefix = "${var.project}-${var.environment}"
  tags        = merge(var.common_tags, { Module = "security" })
}

data "aws_caller_identity" "current" {}

# ═════════════════════════════════════════════════════════════════════════════
# KMS
# ═════════════════════════════════════════════════════════════════════════════

data "aws_iam_policy_document" "kms_policy" {
  statement {
    sid    = "RootAccountFullAccess"
    effect = "Allow"
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${var.aws_account_id}:root"]
    }
    actions   = ["kms:*"]
    resources = ["*"]
  }

  statement {
    sid    = "AllowCloudWatchLogs"
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["logs.${var.aws_region}.amazonaws.com"]
    }
    actions   = ["kms:Encrypt", "kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"]
    resources = ["*"]
  }
}

resource "aws_kms_key" "main" {
  description             = "Crawler ${var.environment} - encrypts RDS, SQS, S3, Secrets"
  deletion_window_in_days = 7
  enable_key_rotation     = true
  policy                  = data.aws_iam_policy_document.kms_policy.json
  tags                    = merge(local.tags, { Name = "${local.name_prefix}-kms-key" })
}

resource "aws_kms_alias" "main" {
  name          = "alias/${local.name_prefix}-key"
  target_key_id = aws_kms_key.main.key_id
}

# ═════════════════════════════════════════════════════════════════════════════
# Secrets Manager — DB credentials
# ═════════════════════════════════════════════════════════════════════════════

resource "aws_secretsmanager_secret" "db" {
  name                    = "${local.name_prefix}/db-credentials"
  description             = "RDS PostgreSQL credentials for the crawler"
  kms_key_id              = aws_kms_key.main.arn
  recovery_window_in_days = 0
  tags                    = merge(local.tags, { Name = "${local.name_prefix}-db-secret" })
}

resource "aws_secretsmanager_secret_version" "db" {
  secret_id = aws_secretsmanager_secret.db.id
  secret_string = jsonencode({
    username = "crawler"
    password = var.db_password
    dbname   = "crawlerdb"
    engine   = "postgres"
    port     = 5432
  })
  lifecycle {
    ignore_changes = [secret_string]
  }
}

# ═════════════════════════════════════════════════════════════════════════════
# Security Groups
# ═════════════════════════════════════════════════════════════════════════════

# ── EC2 Worker (ASG): egress-only (crawls over NAT, sends to SQS / S3) ──────
resource "aws_security_group" "worker" {
  name        = "${local.name_prefix}-sg-worker"
  description = "EC2 worker ASG - egress only"
  vpc_id      = var.vpc_id

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.tags, { Name = "${local.name_prefix}-sg-worker" })
}

# ── Lambda Ingester: egress-only ────────────────────────────────────────────
resource "aws_security_group" "lambda" {
  name        = "${local.name_prefix}-sg-lambda"
  description = "Lambda ingester - egress only"
  vpc_id      = var.vpc_id

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.tags, { Name = "${local.name_prefix}-sg-lambda" })
}

# ── RDS: 5432 from Lambda + worker (ingress updated in-place; do not change
# `description` casually — aws_security_group description change forces replace,
# and a second SG with the same `name` fails with InvalidGroup.Duplicate while RDS
# still holds the old SG.)
resource "aws_security_group" "rds" {
  name        = "${local.name_prefix}-sg-rds"
  description = "RDS PostgreSQL - accepts 5432 from Lambda only"
  vpc_id      = var.vpc_id

  ingress {
    description     = "PostgreSQL from Lambda"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.lambda.id]
  }

  ingress {
    description     = "PostgreSQL from Worker"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.worker.id]
  }

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.tags, {
    Name   = "${local.name_prefix}-sg-rds"
    Remark = "Ingress includes Lambda and worker; avoid changing SG description in TF"
  })
}

# ═════════════════════════════════════════════════════════════════════════════
# IAM — Lambda execution role
# ═════════════════════════════════════════════════════════════════════════════

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  name               = "${local.name_prefix}-lambda-exec-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  tags               = local.tags
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "lambda_vpc" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_iam_role_policy" "lambda_custom" {
  name = "${local.name_prefix}-lambda-custom-policy"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "SQSConsume"
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
          "sqs:ChangeMessageVisibility",
        ]
        Resource = "arn:aws:sqs:${var.aws_region}:${var.aws_account_id}:${local.name_prefix}-*"
      },
      {
        Sid      = "S3RawReadClaimCheck"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "arn:aws:s3:::${local.name_prefix}-raw-*/*"
      },
      {
        Sid      = "SecretsManagerRead"
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
        Resource = "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:${local.name_prefix}/*"
      },
      {
        Sid      = "KMSDecrypt"
        Effect   = "Allow"
        Action   = ["kms:Decrypt", "kms:GenerateDataKey"]
        Resource = aws_kms_key.main.arn
      },
    ]
  })
}

# ═════════════════════════════════════════════════════════════════════════════
# IAM — EC2 worker instance profile
# ═════════════════════════════════════════════════════════════════════════════

data "aws_iam_policy_document" "ec2_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "worker" {
  name               = "${local.name_prefix}-worker-role"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
  tags               = local.tags
}

# SSM Session Manager access (no SSH / bastion required for shell access)
resource "aws_iam_role_policy_attachment" "worker_ssm" {
  role       = aws_iam_role.worker.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# Read-only ECR so the worker can pull its Docker image
resource "aws_iam_role_policy_attachment" "worker_ecr_readonly" {
  role       = aws_iam_role.worker.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

# CloudWatch Agent (custom metrics + logs)
resource "aws_iam_role_policy_attachment" "worker_cw_agent" {
  role       = aws_iam_role.worker.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}

resource "aws_iam_role_policy" "worker_custom" {
  name = "${local.name_prefix}-worker-custom-policy"
  role = aws_iam_role.worker.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "SQSSend"
        Effect   = "Allow"
        Action   = ["sqs:SendMessage", "sqs:GetQueueUrl"]
        Resource = "arn:aws:sqs:${var.aws_region}:${var.aws_account_id}:${local.name_prefix}-*"
      },
      {
        Sid    = "S3RawWriteClaimCheck"
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:AbortMultipartUpload",
        ]
        Resource = "arn:aws:s3:::${local.name_prefix}-raw-*/*"
      },
      {
        Sid    = "S3ExportsReadDashboard"
        Effect = "Allow"
        Action = [
          "s3:ListBucket",
        ]
        Resource = "arn:aws:s3:::${local.name_prefix}-exports-*"
      },
      {
        Sid    = "S3ExportsGetObjects"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:GetObjectVersion",
        ]
        Resource = "arn:aws:s3:::${local.name_prefix}-exports-*/*"
      },
      {
        Sid      = "KMSEncrypt"
        Effect   = "Allow"
        Action   = ["kms:Encrypt", "kms:GenerateDataKey", "kms:Decrypt"]
        Resource = aws_kms_key.main.arn
      },
    ]
  })
}

resource "aws_iam_instance_profile" "worker" {
  name = "${local.name_prefix}-worker-profile"
  role = aws_iam_role.worker.name
  tags = local.tags
}
