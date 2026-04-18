# =============================================================================
# Demo environment outputs
# Use: terraform -chdir=environments/demo output
# =============================================================================

output "rds_endpoint" {
  description = "RDS endpoint (plug into the Lambda RDS_HOST)"
  value       = module.storage.rds_endpoint
  sensitive   = true
}

output "s3_raw_bucket" {
  description = "S3 bucket used by the Claim-Check pattern (raw HTML offload)"
  value       = module.storage.s3_raw_bucket
}

output "s3_exports_bucket" {
  description = "S3 bucket for CSV / JSON exports"
  value       = module.storage.s3_exports_bucket
}

output "sqs_queue_url" {
  description = "Main SQS Standard queue URL (worker → this)"
  value       = module.queue.main_queue_url
}

output "sqs_dlq_url" {
  description = "Dead Letter Queue URL (inspect / redrive failures here)"
  value       = module.queue.dlq_url
}

output "lambda_function_name" {
  description = "Lambda ingester function name"
  value       = module.lambda.lambda_function_name
}

output "ecr_repository_url" {
  description = "ECR repository to push the worker image to"
  value       = module.worker.ecr_repository_url
}

output "worker_asg_name" {
  description = "Worker Auto Scaling Group name"
  value       = module.worker.asg_name
}

output "nat_gateway_ip" {
  description = "NAT Gateway public IP - whitelist this on crawl targets if needed"
  value       = module.networking.nat_gateway_ip
}

output "cloudwatch_dashboard_url" {
  description = "CloudWatch dashboard URL"
  value       = module.observability.dashboard_url
}

output "sns_alert_topic_arn" {
  description = "SNS alert topic (confirm the email subscription after apply)"
  value       = module.observability.sns_topic_arn
}

output "kms_key_arn" {
  description = "KMS CMK ARN"
  value       = module.security.kms_key_arn
}

output "db_secret_arn" {
  description = "Secrets Manager secret ARN with DB credentials"
  value       = module.security.db_secret_arn
}

output "web_dashboard_url" {
  description = "Public URL of FastAPI dashboard through ALB"
  value       = "http://${aws_lb.web.dns_name}"
}
