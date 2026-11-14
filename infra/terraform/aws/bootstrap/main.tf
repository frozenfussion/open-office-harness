# SPDX-License-Identifier: AGPL-3.0-only
locals {
  tags = { project = "open-office-harness", stage = "4b", managed-by = "terraform" }
}

data "aws_caller_identity" "current" {}
resource "aws_s3_bucket" "state" {
  force_destroy = true
  bucket        = "ooh-tfstate-${data.aws_caller_identity.current.account_id}-apse1"
}
resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}
resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_budgets_budget" "copy" {
  name         = "ooh-aws-copy"
  budget_type  = "COST"
  limit_amount = "40"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"
  dynamic "notification" {
    for_each = { actual50 = ["ACTUAL", "50"], actual80 = ["ACTUAL", "80"], actual100 = ["ACTUAL", "100"], forecast100 = ["FORECASTED", "100"] }
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = tonumber(notification.value[1])
      threshold_type             = "PERCENTAGE"
      notification_type          = notification.value[0]
      subscriber_email_addresses = [var.budget_email]
    }
  }
}
