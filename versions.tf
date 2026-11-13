language {
  compatible_with {
    opentofu = ">= 1.12.6"
  }
}


terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.62.0"
    }

    stripe = {
      source  = "stripe/stripe"
      version = "0.3.0"
    }

    random = {
      source  = "hashicorp/random"
      version = "3.9.1"
    }
  }
  backend "s3" {
    #This relies on OpenTofu 1.8+ early variable evaluation in backend blocks
    bucket  = "${var.name_prefix}-${local.region}-tofu-state-${var.env}"
    key     = "state.json"
    region  = local.region
    profile = local.aws_profile

    # S3-native state locking (no DynamoDB table required)
    use_lockfile = true
  }
}