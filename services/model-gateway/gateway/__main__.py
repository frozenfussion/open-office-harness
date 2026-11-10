# SPDX-License-Identifier: AGPL-3.0-only
import asyncio
import json
import logging
import os
import sys

import psycopg
import uvicorn

from gateway.app import create_app
from gateway.database import migrate


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        if record.name == "gateway":
            return record.getMessage()
        return json.dumps({"level": record.levelname, "message": "server event"})


def main() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    if sys.argv[1:] == ["migrate"]:
        try:
            asyncio.run(migrate(os.environ["GW_DB_MIGRATE_CONNECTION"]))
        except psycopg.Error, KeyError, OSError:
            print(
                '{"message":"migration failed; check database readiness and owner settings"}'
            )
            raise SystemExit(1) from None
        print('{"message":"migrations completed"}')
    elif not sys.argv[1:]:
        uvicorn.run(
            create_app(), host="0.0.0.0", port=8080, access_log=False, log_config=None
        )
    else:
        raise SystemExit("usage: python -m gateway [migrate]")


if __name__ == "__main__":
    main()
