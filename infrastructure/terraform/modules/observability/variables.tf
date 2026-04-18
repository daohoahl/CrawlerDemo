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

variable "alert_email" {
  description = "Email to receive SNS alarm notifications"
  type        = string
}

variable "lambda_function_name" {
  description = "Lambda ingester function name (from lambda module)"
  type        = string
}

variable "rds_identifier" {
  description = "RDS instance identifier (from storage module)"
  type        = string
}

variable "dlq_name" {
  description = "DLQ queue name (from queue module)"
  type        = string
}

variable "worker_asg_name" {
  description = "Worker ASG name (from worker module). Leave empty to skip ASG alarms."
  type        = string
  default     = ""
}

variable "worker_asg_max_size" {
  description = "ASG max_size used by the 'at-max-capacity' alarm"
  type        = number
  default     = 2
}

variable "log_retention_days" {
  description = "Log retention for any log group created here"
  type        = number
  default     = 30
}

variable "common_tags" {
  description = "Common tags"
  type        = map(string)
  default     = {}
}
