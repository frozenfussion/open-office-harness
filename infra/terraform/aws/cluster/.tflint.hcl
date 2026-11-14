# SPDX-License-Identifier: AGPL-3.0-only
plugin "terraform" {
  enabled = true
  preset = "recommended"
}
plugin "aws" {
  enabled = true
  version = "0.50.0"
  source = "github.com/terraform-linters/tflint-ruleset-aws"
}
