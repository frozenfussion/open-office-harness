# SPDX-License-Identifier: AGPL-3.0-only
resource "aws_eks_cluster" "main" {
  name                          = "ooh-aws"
  version                       = "1.36"
  role_arn                      = aws_iam_role.cluster.arn
  bootstrap_self_managed_addons = false
  access_config {
    authentication_mode                         = "API"
    bootstrap_cluster_creator_admin_permissions = true
  }
  vpc_config {
    subnet_ids              = [for subnet in aws_subnet.private : subnet.id]
    endpoint_private_access = true
    endpoint_public_access  = true
    public_access_cidrs     = ["143.198.221.2/32"]
  }
  depends_on = [aws_iam_role_policy_attachment.cluster]
}
