output "sns_topic_arn" {
  description = "SNS topic receiving alerts"
  value       = aws_sns_topic.alerts.arn
}

output "dashboard_url" {
  description = "Direct URL to the CloudWatch dashboard"
  value       = "https://${var.aws_region}.console.aws.amazon.com/cloudwatch/home?region=${var.aws_region}#dashboards:name=${aws_cloudwatch_dashboard.main.dashboard_name}"
}
