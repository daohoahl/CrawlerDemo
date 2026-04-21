variable "project" {
  description = "Project name prefix"
  type        = string
}

variable "environment" {
  description = "Deployment environment"
  type        = string
}

variable "aws_account_id" {
  description = "AWS Account ID (for globally unique bucket names)"
  type        = string
}

variable "kms_key_arn" {
  description = "KMS Key ARN used to encrypt S3"
  type        = string
}

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
