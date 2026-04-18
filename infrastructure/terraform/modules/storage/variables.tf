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

variable "aws_account_id" {
  description = "AWS Account ID (used to build globally-unique S3 bucket names)"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID"
  type        = string
}

variable "db_subnet_ids" {
  description = "Subnet IDs for the RDS subnet group (DB tier)"
  type        = list(string)
}

variable "sg_rds_id" {
  description = "Security Group ID for the RDS instance"
  type        = string
}

variable "kms_key_arn" {
  description = "KMS Key ARN used to encrypt RDS + S3"
  type        = string
}

# ── RDS ──────────────────────────────────────────────────────────────────────
variable "db_instance_class" {
  description = "RDS instance class. Scope 1 target: db.t3.micro (Free Tier)."
  type        = string
  default     = "db.t3.micro"
}

variable "db_allocated_storage" {
  description = "Initial storage (GB)"
  type        = number
  default     = 20
}

variable "db_max_allocated_storage" {
  description = "Upper bound for storage autoscaling (GB)"
  type        = number
  default     = 100
}

variable "db_multi_az" {
  description = "Enable Multi-AZ for RDS. Scope 1 = false."
  type        = bool
  default     = false
}

variable "db_backup_retention_days" {
  description = "Automated backup retention days (Free Tier commonly allows up to 1)"
  type        = number
  default     = 1
}

variable "db_deletion_protection" {
  description = "Enable deletion protection on the DB instance"
  type        = bool
  default     = false
}

variable "db_name" {
  description = "Database name"
  type        = string
  default     = "crawlerdb"
}

variable "db_username" {
  description = "Master DB username"
  type        = string
  default     = "crawler"
}

variable "db_password" {
  description = "Master DB password"
  type        = string
  sensitive   = true
}

# ── S3 ───────────────────────────────────────────────────────────────────────
variable "raw_expiration_days" {
  description = "Lifecycle: expire raw HTML payloads after N days"
  type        = number
  default     = 30
}

variable "common_tags" {
  description = "Common tags"
  type        = map(string)
  default     = {}
}
