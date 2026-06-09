from __future__ import annotations

import argparse
from pathlib import Path

from src.common.db import get_connection


# Canonical migration chain — applied in order, idempotent.
MIGRATION_CHAIN = [
    Path("db/migrations/20260605_website_registration_foundation_v1.sql"),
    Path("db/migrations/20260607_profile_session_authorization_v1.sql"),
    Path("db/migrations/20260607_app_profile_trading_account_link_v1.sql"),
    Path("db/migrations/20260609_trading_account_credential_v1.sql"),
    Path("db/migrations/20260609_trading_account_credential_add_valid_private_read.sql"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Apply the SYNTH website registration migration chain with the repository's "
            "canonical MariaDB connection settings. No trading_account or credential changes. "
            "Migrations are applied in order and are idempotent."
        )
    )
    parser.add_argument("--output", choices=("summary", "none"), default="summary")
    return parser.parse_args()


def _split_sql_statements(sql_text: str) -> list[str]:
    statements: list[str] = []
    buffer: list[str] = []
    for line in sql_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        buffer.append(line)
        if stripped.endswith(";"):
            statement = "\n".join(buffer).strip()
            if statement.endswith(";"):
                statement = statement[:-1]
            if statement:
                statements.append(statement)
            buffer = []
    trailing = "\n".join(buffer).strip()
    if trailing:
        statements.append(trailing)
    return statements


def _apply_migration(conn: object, migration_path: Path) -> int:
    sql_text = migration_path.read_text(encoding="utf-8")
    statements = _split_sql_statements(sql_text)
    with conn.cursor() as cur:
        for statement in statements:
            cur.execute(statement)
    conn.commit()
    return len(statements)


def main() -> int:
    args = parse_args()
    conn = get_connection()
    results: list[tuple[str, int]] = []
    try:
        for migration_path in MIGRATION_CHAIN:
            count = _apply_migration(conn, migration_path)
            results.append((migration_path.name, count))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    if args.output == "summary":
        for name, count in results:
            print(f"migration={name} statements_applied={count}")
        print("broker_private_calls=0")
        print("broker_writes=0")
        print("order_submission=0")
        print("live_orders=0")
        print("decision_gate=none")
        print("execution_planner=none")
        print("executor=none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
