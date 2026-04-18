output "main_queue_arn" {
  description = "ARN of the main SQS Standard data queue"
  value       = aws_sqs_queue.main.arn
}

output "main_queue_url" {
  description = "URL of the main SQS Standard data queue (used by the worker)"
  value       = aws_sqs_queue.main.url
}

output "main_queue_name" {
  description = "Name of the main SQS queue (for CloudWatch alarms)"
  value       = aws_sqs_queue.main.name
}

output "dlq_arn" {
  description = "ARN of the Dead Letter Queue"
  value       = aws_sqs_queue.dlq.arn
}

output "dlq_url" {
  description = "URL of the Dead Letter Queue"
  value       = aws_sqs_queue.dlq.url
}

output "dlq_name" {
  description = "Name of the DLQ (for CloudWatch alarms)"
  value       = aws_sqs_queue.dlq.name
}
