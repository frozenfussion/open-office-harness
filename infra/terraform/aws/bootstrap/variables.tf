# SPDX-License-Identifier: AGPL-3.0-only
variable "budget_email" {
  description = "Private budget notification recipient, passed from the environment."
  type        = string
  sensitive   = true
  validation {
    condition     = can(regex("^[^@ ]+@[^@ ]+\\.[^@ ]+$", var.budget_email))
    error_message = "Enter a valid budget email address."
  }
}
