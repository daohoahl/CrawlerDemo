variable "aws_region" {
  description = "AWS Region"
  type        = string
  default     = "ap-southeast-1"
}

variable "aws_account_id" {
  description = "AWS Account ID (12 digits)"
  type        = string
}

variable "environment" {
  description = "Deployment environment tag"
  type        = string
  default     = "demo"
}

variable "project" {
  description = "Project name (used as prefix for all resources)"
  type        = string
  default     = "crawler"
}

# ── Database ────────────────────────────────────────────────────────────────
variable "db_password" {
  description = "Master DB password (pass via TF_VAR_db_password in CI)"
  type        = string
  sensitive   = true
  validation {
    condition     = length(var.db_password) >= 8
    error_message = "db_password must be at least 8 characters long."
  }
}

variable "db_instance_class" {
  description = "RDS instance class. Scope 1: db.t3.micro."
  type        = string
  default     = "db.t3.micro"
  validation {
    condition     = contains(["db.t3.micro", "db.t4g.micro"], var.db_instance_class)
    error_message = "For Scope 1 cost control, use db.t3.micro or db.t4g.micro."
  }
}

variable "db_backup_retention_days" {
  description = "RDS automated backup retention days (set 1 for Free Tier compatibility)"
  type        = number
  default     = 1
  validation {
    condition     = var.db_backup_retention_days >= 0 && var.db_backup_retention_days <= 35
    error_message = "db_backup_retention_days must be between 0 and 35."
  }
}

# ── Worker ──────────────────────────────────────────────────────────────────
variable "ec2_instance_type" {
  description = "EC2 worker instance type. Spec: t3.micro."
  type        = string
  default     = "t3.micro"
  validation {
    condition     = contains(["t3.micro", "t4g.micro"], var.ec2_instance_type)
    error_message = "For Scope 1 cost control, use t3.micro or t4g.micro."
  }
}

variable "worker_ec2_key_name" {
  description = "Optional EC2 Key Pair name in AWS for worker instances. Required for Ansible over SSH through Session Manager (see infrastructure/ansible). Leave null to omit SSH key on instances."
  type        = string
  default     = null
  nullable    = true
}

variable "crawler_interval_seconds" {
  description = "APScheduler interval between crawl cycles (inside the worker container)"
  type        = number
  default     = 1800
}

variable "web_port" {
  description = "Port exposed by the FastAPI dashboard container on worker instances"
  type        = number
  default     = 8080
}

variable "lambda_reserved_concurrency" {
  description = "Reserved concurrency for Lambda ingester (null = no reserved cap)"
  type        = number
  default     = null
  nullable    = true
}

variable "lambda_event_source_max_concurrency" {
  description = "Max concurrent SQS batches for Lambda event source mapping"
  type        = number
  default     = 5
}

# ── Alerting ────────────────────────────────────────────────────────────────
variable "alert_email" {
  description = "Email for SNS alarm notifications"
  type        = string
}
