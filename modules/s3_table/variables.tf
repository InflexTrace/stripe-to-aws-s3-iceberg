variable "bucket_name" {
  type = string
}

# namespace => table name => Iceberg table definition. A namespace with no tables is `{}`.
variable "namespace_to_tables" {
  type = map(map(object({
    # Iceberg format version; 3 is required for v3 types such as `variant`. null keeps the S3 Tables default (2).
    format_version = optional(number)

    # Column order is preserved. `type` is an Iceberg primitive type name, e.g. string, long, timestamptz, variant.
    fields = list(object({
      name     = string
      type     = string
      required = optional(bool, false)
    }))
  })))
}
