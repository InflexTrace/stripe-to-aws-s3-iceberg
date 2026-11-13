data "aws_ssm_parameter" "stripe_api_key" {
  name            = "/${var.env}/${var.name_prefix}/stripe/api_secret_key"
  with_decryption = true
}

data "aws_caller_identity" "current" {}