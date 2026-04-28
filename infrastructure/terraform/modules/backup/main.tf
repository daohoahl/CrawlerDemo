locals {
  name_prefix = "${var.project}-${var.environment}"
  bucket_name = "${local.name_prefix}-backup-${var.aws_account_id}"
  tags        = merge(var.common_tags, { Module = "backup", Purpose = "db-logical-backup" })
}

# ── S3 bucket for pg_dump artifacts ─────────────────────────────────────────
resource "aws_s3_bucket" "backup" {
  bucket        = local.bucket_name
  force_destroy = false
  tags          = merge(local.tags, { Name = local.bucket_name })
}

resource "aws_s3_bucket_server_side_encryption_configuration" "backup" {
  bucket = aws_s3_bucket.backup.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = var.kms_key_arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "backup" {
  bucket                  = aws_s3_bucket.backup.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Short retention — free-tier friendly. No Glacier (retrieval costs), no versioning.
resource "aws_s3_bucket_lifecycle_configuration" "backup" {
  bucket = aws_s3_bucket.backup.id
  rule {
    id     = "expire-old-backups"
    status = "Enabled"
    filter {}
    expiration {
      days = var.retention_days
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

# ── IAM: allow EC2 worker to PUT / LIST backups and use KMS key ─────────────
data "aws_iam_policy_document" "backup_put" {
  statement {
    sid       = "ListAndPutBackups"
    effect    = "Allow"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [aws_s3_bucket.backup.arn]
  }
  statement {
    sid    = "WriteBackups"
    effect = "Allow"
    actions = [
      "s3:PutObject",
      "s3:GetObject",
      "s3:DeleteObject",
      "s3:AbortMultipartUpload",
      "s3:ListMultipartUploadParts",
    ]
    resources = ["${aws_s3_bucket.backup.arn}/*"]
  }
  statement {
    sid       = "UseKmsKey"
    effect    = "Allow"
    actions   = ["kms:Encrypt", "kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_policy" "backup_put" {
  name        = "${local.name_prefix}-backup-put"
  description = "Allow EC2 worker to upload pg_dump backups to S3"
  policy      = data.aws_iam_policy_document.backup_put.json
}

resource "aws_iam_role_policy_attachment" "backup_put" {
  role       = var.ec2_instance_role_name
  policy_arn = aws_iam_policy.backup_put.arn
}

# ── CloudWatch alarm: no backup object created in last 26h ──────────────────
# Uses S3 request metrics via `NumberOfObjects` daily storage metric (free).
resource "aws_cloudwatch_metric_alarm" "backup_missed" {
  for_each = var.enable_backup_missed_alarm ? { enabled = true } : {}

  alarm_name          = "${local.name_prefix}-backup-missed-24h"
  alarm_description   = "No pg_dump object written to backup bucket in the last 24h. Check pg-backup.timer on EC2."
  namespace           = "AWS/S3"
  metric_name         = "NumberOfObjects"
  statistic           = "Average"
  period              = 86400
  evaluation_periods  = 1
  comparison_operator = "LessThanOrEqualToThreshold"
  threshold           = 0
  treat_missing_data  = "breaching"
  dimensions = {
    BucketName  = aws_s3_bucket.backup.id
    StorageType = "AllStorageTypes"
  }
  alarm_actions = var.sns_alarm_topic_arn != "" ? [var.sns_alarm_topic_arn] : []
  ok_actions    = var.sns_alarm_topic_arn != "" ? [var.sns_alarm_topic_arn] : []
  tags          = local.tags
}
