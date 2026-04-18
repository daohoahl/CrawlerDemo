variable "project" {
  description = "Project name prefix"
  type        = string
}

variable "environment" {
  description = "Deployment environment (e.g. demo, prod)"
  type        = string
}

variable "kms_key_arn" {
  description = "KMS key ARN used for SQS encryption"
  type        = string
}

# ── Spec: VisibilityTimeout = 1080 s (18 min) ──
variable "visibility_timeout_seconds" {
  description = "SQS visibility timeout. Rule: >= 6 x Lambda timeout."
  type        = number
  default     = 1080
}

variable "receive_wait_time_seconds" {
  description = "Long polling wait time (0-20 s). 20 = max efficiency."
  type        = number
  default     = 20
}

variable "message_retention_seconds" {
  description = "How long messages stay in the main queue"
  type        = number
  default     = 345600 # 4 days
}

# ── Spec: DLQ maxReceiveCount = 3 ──
variable "max_receive_count" {
  description = "Number of receives before a message is parked in DLQ"
  type        = number
  default     = 3
}

variable "dlq_message_retention_seconds" {
  description = "How long failed messages stay in the DLQ for inspection"
  type        = number
  default     = 1209600 # 14 days (SQS max)
}

variable "common_tags" {
  description = "Common tags applied to all resources"
  type        = map(string)
  default     = {}
}
