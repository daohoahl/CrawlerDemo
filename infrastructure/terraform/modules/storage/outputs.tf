output "rds_endpoint" {
  description = "RDS endpoint host (no port). Use as RDS_HOST for the Lambda."
  value       = aws_db_instance.main.address
}

output "rds_port" {
  description = "RDS port"
  value       = aws_db_instance.main.port
}

output "rds_identifier" {
  description = "RDS instance identifier"
  value       = aws_db_instance.main.identifier
}

output "db_name" {
  description = "Database name"
  value       = aws_db_instance.main.db_name
}

output "db_username" {
  description = "DB master username"
  value       = aws_db_instance.main.username
}

output "s3_raw_bucket" {
  description = "S3 bucket for raw HTML (Claim-Check offload)"
  value       = aws_s3_bucket.raw.bucket
}

output "s3_raw_bucket_arn" {
  description = "ARN of the raw HTML bucket"
  value       = aws_s3_bucket.raw.arn
}

output "s3_exports_bucket" {
  description = "S3 bucket for CSV / JSON exports"
  value       = aws_s3_bucket.exports.bucket
}

output "s3_exports_bucket_arn" {
  description = "ARN of the exports bucket"
  value       = aws_s3_bucket.exports.arn
}
