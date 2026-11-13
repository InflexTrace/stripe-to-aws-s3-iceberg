resource "aws_lambda_layer_version" "this" {
  layer_name               = var.layer_name
  filename                 = data.archive_file.layer_package.output_path
  source_code_hash         = data.archive_file.layer_package.output_base64sha256
  compatible_runtimes      = var.compatible_runtimes
  compatible_architectures = var.compatible_architectures
}
