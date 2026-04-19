# =============================================================================
# MODULE: lambda
#
# Creates:
#   - Lambda Layer (pg8000 pure-Python PostgreSQL driver)
#   - Lambda Function (SQS → RDS ingester)
#   - CloudWatch Log Group with retention policy
#   - SQS Event Source Mapping (BatchSize=10, ReportBatchItemFailures)
#
# Spec alignment (Scope 1):
#   - batch_size = 10
#   - function_response_types = ["ReportBatchItemFailures"]
# =============================================================================

locals {
  name_prefix   = "${var.project}-${var.environment}"
  function_name = "${local.name_prefix}-ingester"
  tags          = merge(var.common_tags, { Module = "lambda" })
}

# ── Package the function ─────────────────────────────────────────────────────

data "archive_file" "function_zip" {
  type        = "zip"
  source_file = var.lambda_source_file
  output_path = "${path.module}/build/lambda_function.zip"
}

# ── Lambda Layer: pg8000 ─────────────────────────────────────────────────────

resource "aws_lambda_layer_version" "pg8000" {
  layer_name          = "${local.name_prefix}-pg8000-layer"
  description         = "Pure-Python pg8000 PostgreSQL driver"
  filename            = var.lambda_layer_zip
  source_code_hash    = filebase64sha256(var.lambda_layer_zip)
  compatible_runtimes = ["python3.11", "python3.12"]
}

# ── Log Group ────────────────────────────────────────────────────────────────

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${local.function_name}"
  retention_in_days = var.log_retention_days
  tags              = merge(local.tags, { Name = "/aws/lambda/${local.function_name}" })
}

# ── Lambda Function ──────────────────────────────────────────────────────────

resource "aws_lambda_function" "ingester" {
  function_name    = local.function_name
  description      = "SQS → RDS ingester (BatchSize=10, ON CONFLICT DO NOTHING)"
  role             = var.lambda_role_arn
  runtime          = "python3.12"
  handler          = "lambda_function.lambda_handler"
  filename         = data.archive_file.function_zip.output_path
  source_code_hash = data.archive_file.function_zip.output_base64sha256

  layers      = [aws_lambda_layer_version.pg8000.arn]
  timeout     = var.lambda_timeout_seconds
  memory_size = var.lambda_memory_mb

  # Optional hard cap. Set to null to avoid account-level reserved concurrency limits.
  reserved_concurrent_executions = var.lambda_reserved_concurrency

  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [var.sg_lambda_id]
  }

  environment {
    variables = {
      RDS_HOST          = var.rds_endpoint
      DB_NAME           = var.db_name
      DB_USER           = var.db_username
      DB_PASSWORD       = var.db_password
      LOG_LEVEL         = "INFO"
      S3_EXPORTS_BUCKET = var.s3_exports_bucket
      S3_EXPORTS_PREFIX = var.s3_exports_prefix
    }
  }

  tracing_config {
    mode = "PassThrough"
  }

  depends_on = [
    aws_cloudwatch_log_group.lambda,
    aws_lambda_layer_version.pg8000,
  ]

  tags = merge(local.tags, { Name = local.function_name })
}

# ── SQS Event Source Mapping ────────────────────────────────────────────────
#
# ReportBatchItemFailures: only failed records return to SQS; the successful
# records in the same batch are deleted automatically.  This is what makes the
# ingester safe to retry without risking duplicate inserts (ON CONFLICT also
# provides a DB-level safety net).

resource "aws_lambda_event_source_mapping" "sqs" {
  event_source_arn                   = var.sqs_main_queue_arn
  function_name                      = aws_lambda_function.ingester.arn
  batch_size                         = var.sqs_batch_size # spec = 10
  maximum_batching_window_in_seconds = 30
  enabled                            = true

  function_response_types = ["ReportBatchItemFailures"]

  scaling_config {
    maximum_concurrency = var.lambda_event_source_max_concurrency
  }
}
