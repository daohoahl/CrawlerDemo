output "lambda_function_name" {
  description = "Lambda ingester function name"
  value       = aws_lambda_function.ingester.function_name
}

output "lambda_function_arn" {
  description = "Lambda ingester function ARN"
  value       = aws_lambda_function.ingester.arn
}

output "lambda_layer_arn" {
  description = "pg8000 Lambda Layer ARN"
  value       = aws_lambda_layer_version.pg8000.arn
}

output "log_group_name" {
  description = "CloudWatch Logs group for the ingester"
  value       = aws_cloudwatch_log_group.lambda.name
}
