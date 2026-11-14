# SPDX-License-Identifier: AGPL-3.0-only
resource "aws_launch_template" "main" {
  name                   = "ooh-aws-main"
  vpc_security_group_ids = [aws_eks_cluster.main.vpc_config[0].cluster_security_group_id]
  block_device_mappings {
    device_name = "/dev/xvda"
    ebs {
      volume_size           = 50
      volume_type           = "gp3"
      encrypted             = true
      kms_key_id            = "alias/aws/ebs"
      delete_on_termination = true
    }
  }
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }
  dynamic "tag_specifications" {
    for_each = toset(["instance", "volume", "network-interface"])
    content {
      resource_type = tag_specifications.value
      tags          = local.tags
    }
  }
}
resource "aws_eks_node_group" "main" {
  cluster_name    = aws_eks_cluster.main.name
  node_group_name = "main"
  node_role_arn   = aws_iam_role.node.arn
  subnet_ids      = [aws_subnet.private["a"].id]
  instance_types  = ["t3.xlarge"]
  ami_type        = "AL2023_x86_64_STANDARD"
  release_version = var.node_release_version
  version         = "1.36"
  capacity_type   = "ON_DEMAND"
  scaling_config {
    desired_size = 1
    min_size     = 1
    max_size     = 1
  }
  launch_template {
    id      = aws_launch_template.main.id
    version = aws_launch_template.main.latest_version
  }
  depends_on = [aws_eks_addon.before, aws_iam_role_policy_attachment.node, aws_route.nat, aws_route_table_association.private]
}
