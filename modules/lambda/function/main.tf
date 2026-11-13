resource "aws_iam_role" "lambda_role" {
  name               = "${var.function_name}-role"
  assume_role_policy = data.aws_iam_policy_document.assume_role.json
}

resource "aws_iam_role_policy_attachment" "basic_execution" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# count, not for_each: ARNs of policies created in the same apply are unknown at plan time
resource "aws_iam_role_policy_attachment" "managed" {
  count = length(var.managed_policy_arns)

  role       = aws_iam_role.lambda_role.name
  policy_arn = var.managed_policy_arns[count.index]
}

resource "aws_iam_role_policy" "additional" {
  count = length(data.aws_iam_policy_document.additional)

  name   = "${var.function_name}-additional"
  role   = aws_iam_role.lambda_role.id
  policy = data.aws_iam_policy_document.additional[0].json
}

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.function_name}"
  retention_in_days = var.log_retention_days
}


resource "aws_lambda_function" "this" {
  function_name    = var.function_name
  filename         = data.archive_file.lambda_package.output_path
  source_code_hash = data.archive_file.lambda_package.output_base64sha256
  role             = aws_iam_role.lambda_role.arn
  runtime          = var.runtime
  handler          = var.handler
  timeout          = var.timeout_seconds
  architectures    = [var.architecture]
  layers           = var.layers

  memory_size = var.memory_size_mb

  environment {
    variables = var.env_vars
  }

  # Ensure the log group exists (with retention) before Lambda can auto-create one without it
  depends_on = [aws_cloudwatch_log_group.lambda]
}

########### Optional schedule ###########################

resource "aws_iam_role" "scheduler_role" {
  count = length(data.aws_iam_policy_document.scheduler_assume_role)

  name               = "${var.function_name}-schedule-role"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume_role[0].json
}

resource "aws_iam_role_policy" "scheduler_invoke_lambda" {
  count = length(aws_iam_role.scheduler_role)

  name   = "invoke-lambda"
  role   = aws_iam_role.scheduler_role[0].id
  policy = data.aws_iam_policy_document.scheduler_invoke_lambda[0].json
}

resource "aws_scheduler_schedule" "this" {
  count = length(aws_iam_role.scheduler_role)

  name = "${var.function_name}-schedule"

  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression          = var.schedule_expression
  schedule_expression_timezone = "UTC"

  target {
    arn      = aws_lambda_function.this.arn
    role_arn = aws_iam_role.scheduler_role[0].arn

    input = jsonencode({})

    # Defaults are 185 retries over 24h. Retries only cover failed Invoke calls (throttling, service errors);
    # function errors are retried by Lambda's own async retry policy
    retry_policy {
      maximum_retry_attempts       = 3
      maximum_event_age_in_seconds = 3600
    }
  }
}
