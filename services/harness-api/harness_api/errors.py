# SPDX-License-Identifier: AGPL-3.0-only
class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        self.status = status
        self.code = code
        self.message = message

    def body(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


def gateway_error(code: str, tier: int) -> ApiError:
    if code == "no_model":
        return ApiError(
            503, code, f"No model is set up for tier {tier} yet. An admin can add one."
        )
    if code == "rate_limited":
        return ApiError(
            429,
            code,
            f"You are sending messages too fast for tier {tier}. Wait a minute.",
        )
    if code == "budget_exceeded":
        return ApiError(
            503,
            code,
            f"Tier {tier} has used its daily budget. "
            "Try again tomorrow or ask an admin.",
        )
    return ApiError(503, "unavailable", "The model did not answer. Try again.")
