# SPDX-License-Identifier: AGPL-3.0-only
resource "kubernetes_storage_class_v1" "gp3" {
  metadata { name = "ooh-gp3" }
  storage_provisioner    = "ebs.csi.aws.com"
  parameters             = { type = "gp3", encrypted = "true", tagSpecification_1 = "ooh-stage=4b" }
  volume_binding_mode    = "WaitForFirstConsumer"
  reclaim_policy         = "Delete"
  allow_volume_expansion = true
}
