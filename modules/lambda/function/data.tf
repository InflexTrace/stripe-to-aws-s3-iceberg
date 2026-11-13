data "aws_iam_policy_document" "assume_role" {
  statement {
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }

    actions = ["sts:AssumeRole"]
  }
}

data "archive_file" "lambda_package" {
  type        = "zip"
  output_path = var.target_zip_file_path

  # Handler file at the zip root, plus every file of each additional dir under <zip dir>/ (minus binary __pycache__ files)
  dynamic "source" {
    for_each = merge(
      { (basename(var.source_file_path)) = var.source_file_path },
      [for zip_dir, local_dir in var.additional_dirs : { for f in fileset(local_dir, "**") : "${zip_dir}/${f}" => "${local_dir}/${f}" if !strcontains(f, "__pycache__") }]...
    )

    content {
      filename = source.key
      content  = file(source.value)
    }
  }
}

data "aws_iam_policy_document" "additional" {
  count = length(var.additional_iam_policy_statements) > 0 ? 1 : 0

  dynamic "statement" {
    for_each = var.additional_iam_policy_statements

    content {
      sid       = statement.value.sid
      effect    = statement.value.effect
      actions   = statement.value.actions
      resources = statement.value.resources
    }
  }
}

data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "scheduler_assume_role" {
  count = var.schedule_expression != null ? 1 : 0

  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

data "aws_iam_policy_document" "scheduler_invoke_lambda" {
  count = var.schedule_expression != null ? 1 : 0

  statement {
    sid       = "InvokeLambda"
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.this.arn]
  }
}
