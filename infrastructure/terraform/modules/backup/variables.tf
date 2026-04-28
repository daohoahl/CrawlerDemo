variable "project" { type = string }
variable "environment" { type = string }
variable "aws_account_id" { type = string }
variable "kms_key_arn" { type = string }
variable "common_tags" {
  type    = map(string)
  default = {}
}
variable "retention_days" {
  type        = number
  default     = 7
  description = "Delete pg_dump objects older than this many days. Free-tier default: 7."
}
variable "sns_alarm_topic_arn" {
  type        = string
  default     = ""
  description = "Optional SNS topic for 'backup missed' alarm. Empty = no alarm."
}
variable "enable_backup_missed_alarm" {
  type        = bool
  default     = false
  description = "Whether to create the backup missed CloudWatch alarm."
}
variable "ec2_instance_role_name" {
  type        = string
  description = "IAM role name attached to EC2 worker; backup policy is attached here."
}
