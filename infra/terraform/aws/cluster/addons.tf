# SPDX-License-Identifier: AGPL-3.0-only
resource "aws_eks_addon" "before" {
  for_each      = { vpc-cni = "v1.22.4-eksbuild.14", kube-proxy = "v1.36.0-eksbuild.65", eks-pod-identity-agent = "v1.4.1-eksbuild.3" }
  cluster_name  = aws_eks_cluster.main.name
  addon_name    = each.key
  addon_version = each.value
}
resource "aws_eks_addon" "coredns" {
  cluster_name  = aws_eks_cluster.main.name
  addon_name    = "coredns"
  addon_version = "v1.14.7-eksbuild.35"
  depends_on    = [aws_eks_node_group.main]
}
resource "aws_eks_addon" "ebs" {
  cluster_name  = aws_eks_cluster.main.name
  addon_name    = "aws-ebs-csi-driver"
  addon_version = "v1.68.0-eksbuild.1"
  configuration_values = jsonencode({ controller = {
    additionalArgs  = ["--k8s-tag-cluster-id=ooh-aws"]
    extraVolumeTags = merge(local.tags, { ooh-stage = "4b" })
  } })
  depends_on = [aws_eks_node_group.main, aws_eks_pod_identity_association.ebs, aws_iam_role_policy_attachment.ebs]
}
