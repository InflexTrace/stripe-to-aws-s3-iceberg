output "lambda_arn" {
  value = aws_lambda_function.this.arn
}

output "lambda_name" {
  value = aws_lambda_function.this.function_name
}
output "schedule_arn" {
  value = one(aws_scheduler_schedule.this[*].arn)
}
