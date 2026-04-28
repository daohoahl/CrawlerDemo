output "bucket_name" {
  value       = aws_s3_bucket.backup.id
  description = "S3 bucket name to use as pg_dump target."
}

output "bucket_arn" {
  value = aws_s3_bucket.backup.arn
}
