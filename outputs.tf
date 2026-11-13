locals {
  s3tables_common_args = [
    "--table-bucket-arn ${module.subscription_data.table_bucket_arn}",
    "--region ${local.region}",
    "--profile ${local.aws_profile}",
  ]
  # Renders each command as a multi-line shell command with `\` continuations
  s3tables_line_sep = " \\\n    "
}


output "stripe_partner_aws_event_bridge_event_source" {
  value = {
    arn    = stripe_v2_core_event_destination.aws_eventbridge_webhook.amazon_eventbridge[0].aws_event_source_arn,
    status = stripe_v2_core_event_destination.aws_eventbridge_webhook.amazon_eventbridge[0].aws_event_source_status
  }
}

# Handy AWS CLI commands for inspecting the S3 table bucket
output "s3tables_commands" {
  value = {
    list_namespaces = join(local.s3tables_line_sep, concat(
      ["aws s3tables list-namespaces"],
      local.s3tables_common_args,
    ))
    "list_tables_${local.stripe_raw_namespace}" = join(local.s3tables_line_sep, concat(
      ["aws s3tables list-tables", "--namespace ${module.subscription_data.namespaces[local.stripe_raw_namespace]}"],
      local.s3tables_common_args,
    ))
    delete_table_example = join(local.s3tables_line_sep, concat(
      ["aws s3tables delete-table", "--namespace ${module.subscription_data.namespaces[local.stripe_raw_namespace]}", "--name subscription"],
      local.s3tables_common_args,
    ))
  }
}

output "stripe_price_lookup_key" {
  value = stripe_price.monthly.lookup_key
}
