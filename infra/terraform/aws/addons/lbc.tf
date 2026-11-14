# SPDX-License-Identifier: AGPL-3.0-only
data "aws_iam_policy_document" "pod" {
  statement {
    actions = ["sts:AssumeRole", "sts:TagSession"]
    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }
  }
}
resource "aws_iam_role" "lbc" {
  name               = "ooh-aws-load-balancer-controller"
  assume_role_policy = data.aws_iam_policy_document.pod.json
}
resource "aws_iam_policy" "lbc" {
  name   = "ooh-aws-load-balancer-controller"
  policy = file("${path.module}/policies/aws-load-balancer-controller-v3.6.3.json")
}
resource "aws_iam_role_policy_attachment" "lbc" {
  role       = aws_iam_role.lbc.name
  policy_arn = aws_iam_policy.lbc.arn
}
resource "aws_eks_pod_identity_association" "lbc" {
  cluster_name    = data.terraform_remote_state.cluster.outputs.cluster_name
  namespace       = "kube-system"
  service_account = "aws-load-balancer-controller"
  role_arn        = aws_iam_role.lbc.arn
}
resource "helm_release" "lbc" {
  name       = "aws-load-balancer-controller"
  namespace  = "kube-system"
  repository = "https://aws.github.io/eks-charts"
  chart      = "aws-load-balancer-controller"
  version    = "3.6.3"
  timeout    = 600
  values = [yamlencode({
    createIngressClassResource = false
    clusterName                = data.terraform_remote_state.cluster.outputs.cluster_name
    region                     = "ap-southeast-1"
    vpcId                      = data.terraform_remote_state.cluster.outputs.vpc_id
    defaultTags                = local.tags
    replicaCount               = 1
    serviceAccount             = { name = "aws-load-balancer-controller" }
    resources                  = { requests = { cpu = "10m", memory = "64Mi" }, limits = { cpu = "200m", memory = "256Mi" } }
  })]
  depends_on = [aws_eks_pod_identity_association.lbc, aws_iam_role_policy_attachment.lbc]
}
