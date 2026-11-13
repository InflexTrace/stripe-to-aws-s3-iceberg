provider "aws" {
  region = local.region

  default_tags {
    tags = {
      Environment = var.env
      Region      = local.region

      ManagedBy = "OpenTofu"
    }
  }

  profile = local.aws_profile

}

provider "stripe" {
  api_key = data.aws_ssm_parameter.stripe_api_key.value
}

