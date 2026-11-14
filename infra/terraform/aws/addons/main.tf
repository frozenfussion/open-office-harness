# SPDX-License-Identifier: AGPL-3.0-only
locals {
  tags = { project = "open-office-harness", stage = "4b", managed-by = "terraform" }
}

data "terraform_remote_state" "cluster" {
  backend = "s3"
  config  = { bucket = var.state_bucket, key = "cluster/terraform.tfstate", region = "ap-southeast-1", use_lockfile = true }
}
provider "helm" {
  kubernetes = {
    host                   = data.terraform_remote_state.cluster.outputs.endpoint
    cluster_ca_certificate = base64decode(data.terraform_remote_state.cluster.outputs.certificate_authority_data)
    exec                   = { api_version = "client.authentication.k8s.io/v1beta1", command = "aws", args = ["eks", "get-token", "--cluster-name", data.terraform_remote_state.cluster.outputs.cluster_name, "--region", "ap-southeast-1"] }
  }
}
provider "kubernetes" {
  host                   = data.terraform_remote_state.cluster.outputs.endpoint
  cluster_ca_certificate = base64decode(data.terraform_remote_state.cluster.outputs.certificate_authority_data)
  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args        = ["eks", "get-token", "--cluster-name", data.terraform_remote_state.cluster.outputs.cluster_name, "--region", "ap-southeast-1"]
  }
}
