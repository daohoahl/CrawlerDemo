output "kms_key_arn" {
  value       = aws_kms_key.main.arn
  description = "KMS CMK ARN"
}

output "kms_key_id" {
  value       = aws_kms_key.main.key_id
  description = "KMS CMK ID"
}

output "db_secret_arn" {
  value       = aws_secretsmanager_secret.db.arn
  description = "Secrets Manager ARN holding DB credentials"
}

output "sg_worker_id" {
  value       = aws_security_group.worker.id
  description = "Security Group ID for EC2 ASG workers"
}

output "sg_lambda_id" {
  value       = aws_security_group.lambda.id
  description = "Security Group ID for the Lambda ingester"
}

output "sg_rds_id" {
  value       = aws_security_group.rds.id
  description = "Security Group ID for RDS"
}

output "lambda_role_arn" {
  value       = aws_iam_role.lambda.arn
  description = "ARN of the Lambda execution role"
}

output "worker_instance_profile_name" {
  value       = aws_iam_instance_profile.worker.name
  description = "EC2 instance profile name (for the Launch Template)"
}

output "worker_instance_profile_arn" {
  value       = aws_iam_instance_profile.worker.arn
  description = "EC2 instance profile ARN"
}

output "worker_role_arn" {
  value       = aws_iam_role.worker.arn
  description = "ARN of the EC2 worker IAM role"
}
