# SPDX-License-Identifier: AGPL-3.0-only
variable "node_release_version" {
  description = "Pinned EKS AL2023 release from the stage spec."
  type        = string
  default     = "1.36.5-20261107"
}
