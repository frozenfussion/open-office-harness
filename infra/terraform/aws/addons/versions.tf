# SPDX-License-Identifier: AGPL-3.0-only
terraform {
  required_version = "= 1.17.2"
  required_providers {
    aws        = { source = "hashicorp/aws", version = "6.73.0" }
    helm       = { source = "hashicorp/helm", version = "3.3.0" }
    kubernetes = { source = "hashicorp/kubernetes", version = "3.5.0" }
  }
  backend "s3" {}
}
provider "aws" {
  region = "ap-southeast-1"
  default_tags { tags = local.tags }
}
