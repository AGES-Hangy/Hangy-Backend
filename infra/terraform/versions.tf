terraform {
  required_version = ">= 1.11.0, < 2.0.0"

  # The workflow creates this bucket before initializing the application stack.
  backend "s3" {
    encrypt      = true
    use_lockfile = true
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.7"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = "Hangy"
      ManagedBy = "Terraform"
      Stack     = var.name
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
