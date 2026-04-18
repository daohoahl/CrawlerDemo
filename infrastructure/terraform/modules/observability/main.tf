# =============================================================================
# MODULE: observability
#
# Creates:
#   - SNS Topic (alert destination; sends email)
#   - CloudWatch Alarms: DLQ messages, Lambda errors, RDS CPU, ASG capacity
#   - CloudWatch Dashboard stitching SQS + Lambda + RDS + ASG into one view
# =============================================================================

locals {
  name_prefix = "${var.project}-${var.environment}"
  tags        = merge(var.common_tags, { Module = "observability" })
}

# ── SNS alert topic ──────────────────────────────────────────────────────────

resource "aws_sns_topic" "alerts" {
  name = "${local.name_prefix}-alerts"
  tags = merge(local.tags, { Name = "${local.name_prefix}-alerts" })
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# ── Alarm: DLQ has messages ─────────────────────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "dlq_has_messages" {
  alarm_name          = "${local.name_prefix}-dlq-has-messages"
  alarm_description   = "Messages landed in the DLQ (poison pill or Lambda bug)"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  statistic           = "Maximum"
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  period              = 60
  evaluation_periods  = 1
  treat_missing_data  = "notBreaching"

  dimensions = { QueueName = var.dlq_name }

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]

  tags = local.tags
}

# ── Alarm: Lambda errors ────────────────────────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name          = "${local.name_prefix}-lambda-errors"
  alarm_description   = "Lambda ingester threw errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  statistic           = "Sum"
  comparison_operator = "GreaterThanThreshold"
  threshold           = 5
  period              = 300
  evaluation_periods  = 1
  treat_missing_data  = "notBreaching"

  dimensions = { FunctionName = var.lambda_function_name }

  alarm_actions = [aws_sns_topic.alerts.arn]
  tags          = local.tags
}

# ── Alarm: RDS CPU > 80 % for 5 min ─────────────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "rds_cpu" {
  alarm_name          = "${local.name_prefix}-rds-cpu-high"
  alarm_description   = "RDS CPU > 80 % for 5 min"
  namespace           = "AWS/RDS"
  metric_name         = "CPUUtilization"
  statistic           = "Average"
  comparison_operator = "GreaterThanThreshold"
  threshold           = 80
  period              = 60
  evaluation_periods  = 5

  dimensions = { DBInstanceIdentifier = var.rds_identifier }

  alarm_actions = [aws_sns_topic.alerts.arn]
  tags          = local.tags
}

# ── Alarm: ASG reached max capacity ─────────────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "asg_at_max" {
  count = var.worker_asg_name == "" ? 0 : 1

  alarm_name          = "${local.name_prefix}-worker-asg-at-max"
  alarm_description   = "Worker ASG is running at max_size - consider raising the cap"
  namespace           = "AWS/AutoScaling"
  metric_name         = "GroupInServiceInstances"
  statistic           = "Maximum"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = var.worker_asg_max_size
  period              = 300
  evaluation_periods  = 2

  dimensions = { AutoScalingGroupName = var.worker_asg_name }

  alarm_actions = [aws_sns_topic.alerts.arn]
  tags          = local.tags
}

# ── Dashboard ───────────────────────────────────────────────────────────────

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "${local.name_prefix}-overview"

  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric", x = 0, y = 0, width = 12, height = 6
        properties = {
          title  = "SQS — Messages"
          region = var.aws_region
          metrics = [
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", "${local.name_prefix}-data-queue", { label = "Main" }],
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", var.dlq_name, { label = "DLQ", color = "#d13212" }],
          ]
          period = 60
          stat   = "Maximum"
          view   = "timeSeries"
        }
      },
      {
        type = "metric", x = 12, y = 0, width = 12, height = 6
        properties = {
          title  = "Lambda — Invocations / Errors / Throttles"
          region = var.aws_region
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", var.lambda_function_name],
            [".", "Errors", ".", ".", { color = "#d13212" }],
            [".", "Throttles", ".", ".", { color = "#ff9900" }],
          ]
          period = 60
          stat   = "Sum"
          view   = "timeSeries"
        }
      },
      {
        type = "metric", x = 0, y = 6, width = 12, height = 6
        properties = {
          title  = "RDS — CPU & Connections"
          region = var.aws_region
          metrics = [
            ["AWS/RDS", "CPUUtilization", "DBInstanceIdentifier", var.rds_identifier],
            [".", "DatabaseConnections", ".", "."],
          ]
          period = 60
          stat   = "Average"
          view   = "timeSeries"
        }
      },
      {
        type = "metric", x = 12, y = 6, width = 12, height = 6
        properties = {
          title  = "Worker ASG — CPU & Capacity"
          region = var.aws_region
          metrics = var.worker_asg_name == "" ? [] : [
            ["AWS/EC2", "CPUUtilization", "AutoScalingGroupName", var.worker_asg_name, { label = "CPU %" }],
            ["AWS/AutoScaling", "GroupInServiceInstances", "AutoScalingGroupName", var.worker_asg_name, { label = "Running", yAxis = "right" }],
          ]
          period = 60
          stat   = "Average"
          view   = "timeSeries"
        }
      },
    ]
  })
}
