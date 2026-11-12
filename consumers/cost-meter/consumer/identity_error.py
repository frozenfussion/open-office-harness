# SPDX-License-Identifier: AGPL-3.0-only
class IdentityError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        self.status, self.code, self.message = status, code, message
        super().__init__(code)
