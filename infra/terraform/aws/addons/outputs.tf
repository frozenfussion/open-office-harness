# SPDX-License-Identifier: AGPL-3.0-only
output "storage_class" { value = kubernetes_storage_class_v1.gp3.metadata[0].name }
