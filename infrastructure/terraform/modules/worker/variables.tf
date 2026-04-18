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

variable "private_subnet_ids" {
  description = "Private subnet IDs - must contain >= 2 (Multi-AZ ASG)"
  type        = list(string)
  validation {
    condition     = length(var.private_subnet_ids) >= 2
    error_message = "Worker ASG requires at least 2 subnets across different AZs."
  }
}

variable "sg_worker_id" {
  description = "Security Group ID for the worker EC2 instances"
  type        = string
}

variable "iam_instance_profile_name" {
  description = "IAM Instance Profile name (from security module)"
  type        = string
}

# ── Instance sizing ──────────────────────────────────────────────────────────
variable "instance_type" {
  description = "EC2 instance type. Spec: t3.micro (Free Tier)."
  type        = string
  default     = "t3.micro"
}

# ── ASG capacity (spec: desired=1, min=1, max=2) ────────────────────────────
variable "desired_capacity" {
  type        = number
  default     = 1
  description = "Desired number of worker instances (spec=1)"
}

variable "min_size" {
  type        = number
  default     = 1
  description = "Minimum number of worker instances (spec=1)"
}

variable "max_size" {
  type        = number
  default     = 2
  description = "Maximum number of worker instances (spec=2)"
}

# ── Container runtime env (wired into user_data.sh.tpl) ─────────────────────
variable "sqs_queue_url" {
  description = "SQS Standard queue URL passed to the worker container"
  type        = string
}

variable "s3_raw_bucket" {
  description = "S3 bucket name for the Claim Check payloads"
  type        = string
}

variable "interval_seconds" {
  description = "APScheduler interval between crawl cycles"
  type        = number
  default     = 1800
}

variable "max_items_per_source" {
  description = "Maximum articles fetched per source per cycle"
  type        = number
  default     = 100
}

variable "claim_check_threshold_bytes" {
  description = "Message body size that triggers S3 Claim Check (bytes)"
  type        = number
  default     = 204800 # 200 KB
}

# ── Observability ────────────────────────────────────────────────────────────
variable "log_retention_days" {
  description = "CloudWatch Logs retention for the worker log group"
  type        = number
  default     = 30
}

variable "common_tags" {
  description = "Common tags"
  type        = map(string)
  default     = {}
}
