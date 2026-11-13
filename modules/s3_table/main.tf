locals {
  # "namespace.table" => { namespace, name, format_version, fields }
  tables = merge([
    for ns, tables in var.namespace_to_tables : {
      for name, table in tables : "${ns}.${name}" => merge(table, { namespace = ns, name = name })
    }
  ]...)
}

resource "aws_s3tables_table_bucket" "bucket" {
  name = var.bucket_name
}

resource "aws_s3tables_namespace" "namespace" {

  for_each = var.namespace_to_tables

  namespace        = each.key
  table_bucket_arn = aws_s3tables_table_bucket.bucket.arn
}

resource "aws_s3tables_table" "table" {
  for_each = local.tables

  name             = each.value.name
  namespace        = aws_s3tables_namespace.namespace[each.value.namespace].namespace
  table_bucket_arn = aws_s3tables_table_bucket.bucket.arn
  format           = "ICEBERG"

  metadata {
    iceberg {
      properties = each.value.format_version == null ? null : {
        "format-version" = tostring(each.value.format_version)
      }

      schema {
        dynamic "field" {
          for_each = each.value.fields
          content {
            name     = field.value.name
            type     = field.value.type
            required = field.value.required
          }
        }
      }
    }
  }
}
