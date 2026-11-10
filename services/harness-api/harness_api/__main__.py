# SPDX-License-Identifier: AGPL-3.0-only
import json
import sys


def main() -> None:
    if sys.argv[1:] == ["migrate"]:
        from .migrate import main as migrate

        try:
            migrate()
        except Exception:
            print(json.dumps({"level": "error", "event": "migration_failed"}))
            raise SystemExit(1) from None
        print(json.dumps({"level": "info", "event": "migrations_complete"}))
    elif not sys.argv[1:]:
        import uvicorn

        uvicorn.run(
            "harness_api.app:factory",
            factory=True,
            host="0.0.0.0",
            port=8080,
            access_log=False,
            log_config=None,
        )
    else:
        raise SystemExit("Use: python -m harness_api [migrate]")


if __name__ == "__main__":
    main()
