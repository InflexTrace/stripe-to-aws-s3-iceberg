variable "layer_name" {
  type = string
}

variable "source_dir_path" {
  type        = string
  description = "Directory with the built layer contents (e.g. containing python/ for Python layers)."
}

variable "target_zip_file_path" {
  type = string
}

variable "compatible_runtimes" {
  type = list(string)
}

variable "compatible_architectures" {
  type = list(string)

  validation {
    condition     = alltrue([for a in var.compatible_architectures : contains(["arm64", "x86_64"], a)])
    error_message = "compatible_architectures may only contain \"arm64\" and/or \"x86_64\"."
  }
}
