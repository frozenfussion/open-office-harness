# SPDX-License-Identifier: AGPL-3.0-only
import uvicorn

uvicorn.run(
    "slides_worker.app:factory",
    factory=True,
    host="0.0.0.0",
    port=8080,
    access_log=False,
    log_config=None,
)
