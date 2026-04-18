output "asg_name" {
  description = "Auto Scaling Group name"
  value       = aws_autoscaling_group.worker.name
}

output "asg_arn" {
  description = "Auto Scaling Group ARN"
  value       = aws_autoscaling_group.worker.arn
}

output "launch_template_id" {
  description = "Launch Template ID"
  value       = aws_launch_template.worker.id
}

output "ecr_repository_url" {
  description = "ECR repository URL (push worker images here)"
  value       = aws_ecr_repository.worker.repository_url
}

output "ecr_repository_name" {
  description = "ECR repository name"
  value       = aws_ecr_repository.worker.name
}

output "log_group_name" {
  description = "CloudWatch Log Group for worker logs"
  value       = aws_cloudwatch_log_group.worker.name
}

output "scale_out_alarm_arn" {
  description = "CloudWatch alarm: CPU > 70 % for 3 min → +1 instance"
  value       = aws_cloudwatch_metric_alarm.cpu_high.arn
}

output "scale_in_alarm_arn" {
  description = "CloudWatch alarm: CPU < 40 % for 3 min → -1 instance"
  value       = aws_cloudwatch_metric_alarm.cpu_low.arn
}
