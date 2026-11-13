variable "env" {
  type = string

  validation {
    condition     = contains(["dev", "prod"], var.env)
    error_message = "env must be either \"dev\" or \"prod\"."
  }
}


variable "region" {
  type        = string
  default     = "us-east-2"
  description = "AWS region to deploy into (also where the state bucket lives)."
}

variable "name_prefix" {
  type        = string
  default     = "stripe-iceberg"
  description = "Prefix of resource names, the AWS CLI profile (<name_prefix>-<env>), the state bucket and the SSM path of the Stripe API key."
}
