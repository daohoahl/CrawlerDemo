output "s3_raw_bucket" {
  description = "S3 bucket for raw HTML (Claim-Check offload)"
  value       = aws_s3_bucket.raw.bucket
}

output "s3_raw_bucket_arn" {
  description = "ARN of the raw HTML bucket"
  value       = aws_s3_bucket.raw.arn
}

output "s3_exports_bucket" {
  description = "S3 bucket for CSV/JSON exports"
  value       = aws_s3_bucket.exports.bucket
}

output "s3_exports_bucket_arn" {
  description = "ARN of the exports bucket"
  value       = aws_s3_bucket.exports.arn
}
