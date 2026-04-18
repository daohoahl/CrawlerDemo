# =============================================================================
# MODULE: queue
# Creates: SQS Standard Dead Letter Queue + SQS Standard Main Queue
#
# Why SQS Standard (not FIFO)?
#   - Spec target: Worker → SQS Standard → Lambda
#   - Higher throughput (nearly unlimited vs FIFO's 300/s per group).
#   - Dedup / ordering needs are handled downstream by the idempotent
#     INSERT ... ON CONFLICT DO NOTHING in the Lambda ingester.
#
# Visibility Timeout = 1080 s (18 min)
#   Rule of thumb: VT ≥ 6 × Lambda timeout.  With a 180 s Lambda budget we
#   land at 1080 s, leaving comfortable headroom so SQS never re-delivers
#   while a slow Lambda is still processing.
#
# DLQ
#   maxReceiveCount = 3 — after three failed receives a message is moved
#   out of the hot path and parked in the DLQ for inspection / replay.
# =============================================================================

locals {
  name_prefix = "${var.project}-${var.environment}"
  tags        = merge(var.common_tags, { Module = "queue" })
}

# ── Dead Letter Queue (Standard) ──────────────────────────────────────────────

resource "aws_sqs_queue" "dlq" {
  name                       = "${local.name_prefix}-data-dlq"
  message_retention_seconds  = var.dlq_message_retention_seconds
  visibility_timeout_seconds = var.visibility_timeout_seconds
  kms_master_key_id          = var.kms_key_arn

  tags = merge(local.tags, {
    Name = "${local.name_prefix}-data-dlq"
    Role = "dlq"
  })
}

# ── Main Data Queue (Standard) ────────────────────────────────────────────────

resource "aws_sqs_queue" "main" {
  name                              = "${local.name_prefix}-data-queue"
  visibility_timeout_seconds        = var.visibility_timeout_seconds
  message_retention_seconds         = var.message_retention_seconds
  receive_wait_time_seconds         = var.receive_wait_time_seconds
  kms_master_key_id                 = var.kms_key_arn

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = var.max_receive_count
  })

  tags = merge(local.tags, {
    Name = "${local.name_prefix}-data-queue"
    Role = "main"
  })
}

# ── Queue Policies: enforce TLS in transit ────────────────────────────────────

resource "aws_sqs_queue_policy" "main" {
  queue_url = aws_sqs_queue.main.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyNonSecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "sqs:*"
      Resource  = aws_sqs_queue.main.arn
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}

resource "aws_sqs_queue_policy" "dlq" {
  queue_url = aws_sqs_queue.dlq.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyNonSecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "sqs:*"
      Resource  = aws_sqs_queue.dlq.arn
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}
