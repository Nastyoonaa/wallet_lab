import os
from pathlib import Path

import psycopg

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


def migrate(database_url: str) -> None:
    with psycopg.connect(database_url) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(724085491)")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY)"
        )
        applied = {
            version for (version,) in conn.execute("SELECT version FROM schema_migrations")
        }
        for path in sorted(MIGRATIONS.glob("*.sql")):
            if path.name not in applied:
                conn.execute(path.read_text(encoding="utf-8"))
                conn.execute("INSERT INTO schema_migrations VALUES (%s)", (path.name,))


if __name__ == "__main__":
    migrate(os.environ["DATABASE_URL"])
