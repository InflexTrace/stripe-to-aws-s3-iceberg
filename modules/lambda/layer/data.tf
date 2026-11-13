data "archive_file" "layer_package" {
  type        = "zip"
  source_dir  = var.source_dir_path
  output_path = var.target_zip_file_path
}
