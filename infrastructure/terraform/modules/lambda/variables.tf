variable "project" {
  description = "Project name prefix"
  type        = string
}

variable "environment" {
  description = "Deployment environment"
  type        = string
}

variable "aws_region" {
  description = "AWS Region"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID"
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet IDs where Lambda ENIs are attached"
  type        = list(string)
}

variable "sg_lambda_id" {
  description = "Security Group ID for the Lambda ENI"
  type        = string
}

variable "lambda_role_arn" {
  description = "ARN of the Lambda execution role"
  type        = string
}

variable "sqs_main_queue_arn" {
  description = "ARN of the main SQS queue (event source)"
  type        = string
}

variable "rds_endpoint" {
  description = "RDS endpoint host"
  type        = string
}

variable "db_name" {
  description = "DB name"
  type        = string
}

variable "db_username" {
  description = "DB username"
  type        = string
}

variable "db_password" {
  description = "DB password (sensitive)"
  type        = string
  sensitive   = true
}

variable "s3_exports_bucket" {
  description = "S3 bucket for JSONL auto-exports after ingest (ingester PutObject)"
  type        = string
}

variable "s3_exports_prefix" {
  description = "Key prefix for auto-export objects (e.g. auto/)"
  type        = string
  default     = "auto/"
}

# ── Lambda sizing ────────────────────────────────────────────────────────────
variable "lambda_memory_mb" {
  description = "Lambda memory allocation"
  type        = number
  default     = 256
}

variable "lambda_timeout_seconds" {
  description = "Lambda timeout. Keep ≤ VisibilityTimeout / 6."
  type        = number
  default     = 180
}

variable "lambda_reserved_concurrency" {
  description = "Reserved concurrency for Lambda. Set null to use account unreserved pool."
  type        = number
  default     = null
  nullable    = true
}

variable "lambda_event_source_max_concurrency" {
  description = "Max concurrent batches polled from SQS event source mapping."
  type        = number
  default     = 5
}

# ── Spec: BatchSize = 10 ─────────────────────────────────────────────────────
variable "sqs_batch_size" {
  description = "Number of SQS records Lambda pulls per invocation (spec = 10)"
  type        = number
  default     = 10
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention"
  type        = number
  default     = 30
}

# ── Asset paths ──────────────────────────────────────────────────────────────
variable "lambda_source_file" {
  description = "Path to the Lambda source .py file"
  type        = string
}

variable "lambda_layer_zip" {
  description = "Path to the pg8000 layer zip"
  type        = string
}

variable "common_tags" {
  description = "Common tags"
  type        = map(string)
  default     = {}
}
