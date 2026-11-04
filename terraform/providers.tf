terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
  }
  backend "s3" {
    bucket = "acme-tfstate-eu-west-1"
    key    = "payments-ledger/terraform.tfstate"
    region = "eu-west-1"
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project     = "payments-ledger"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}
