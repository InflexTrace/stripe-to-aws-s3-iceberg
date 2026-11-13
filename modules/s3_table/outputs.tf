output "table_bucket_arn" {
  value = aws_s3tables_table_bucket.bucket.arn
}

# name => namespace
output "namespaces" {
  value = { for k, ns in aws_s3tables_namespace.namespace : k => ns.namespace }
}

# namespace => table name => table ARN
output "table_arns" {
  value = {
    for ns, tables in var.namespace_to_tables : ns => {
      for name, _ in tables : name => aws_s3tables_table.table["${ns}.${name}"].arn
    }
  }
}
