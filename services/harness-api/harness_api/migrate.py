# SPDX-License-Identifier: AGPL-3.0-only
import hashlib
import os
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"


def migrate(connection: str) -> None:
    name = conninfo_to_dict(connection).get("dbname")
    if name not in {"harness", "harness_test"}:
        raise ValueError("Migration connection must name a Harness database")
    app_role = "harness_app" if name == "harness" else "harness_test_app"
    with psycopg.connect(connection) as db:
        db.execute("SELECT pg_advisory_xact_lock(660020)")
        db.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(name text PRIMARY KEY, sha256 text NOT NULL, "
            "applied_at timestamptz NOT NULL DEFAULT now())"
        )
        for file in sorted(MIGRATIONS.glob("*.sql")):
            content = file.read_text()
            digest = hashlib.sha256(content.encode()).hexdigest()
            previous = db.execute(
                "SELECT sha256 FROM schema_migrations WHERE name=%s", (file.name,)
            ).fetchone()
            if previous:
                if previous[0] != digest:
                    raise ValueError("An applied migration was changed")
                continue
            db.execute(content)
            db.execute(
                "INSERT INTO schema_migrations(name,sha256) VALUES (%s,%s)",
                (file.name, digest),
            )
        db.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
        db.execute(
            sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(
                sql.Identifier(app_role)
            )
        )
        db.execute(
            sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}").format(
                sql.Identifier(app_role)
            )
        )
        db.execute(
            sql.SQL("GRANT SELECT, INSERT ON messages TO {}").format(
                sql.Identifier(app_role)
            )
        )
        db.execute(
            sql.SQL("GRANT SELECT, INSERT, UPDATE ON conversations TO {}").format(
                sql.Identifier(app_role)
            )
        )
        db.execute(
            "CREATE OR REPLACE FUNCTION refuse_migration_change() RETURNS trigger "
            "LANGUAGE plpgsql AS $$ BEGIN "
            "RAISE EXCEPTION 'Migration records are append-only'; END; $$"
        )
        db.execute(
            "CREATE OR REPLACE TRIGGER schema_migrations_immutable "
            "BEFORE UPDATE OR DELETE OR TRUNCATE ON schema_migrations "
            "FOR EACH STATEMENT EXECUTE FUNCTION refuse_migration_change()"
        )


def main() -> None:
    migrate(os.environ["HA_DB_MIGRATE_CONNECTION"])
