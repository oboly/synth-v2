from __future__ import annotations

import argparse
from pathlib import Path

from src.common.db import get_connection


DEFAULT_MIGRATION_PATH = Path("db/migrations/20260605_website_registration_foundation_v1.sql")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Apply the SYNTH website registration foundation migration with the repository's "
            "canonical MariaDB connection settings. No trading_account or credential changes."
        )
    )
    parser.add_argument("--migration-path", default=str(DEFAULT_MIGRATION_PATH))
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


def main() -> int:
    args = parse_args()
    migration_path = Path(args.migration_path)
    sql_text = migration_path.read_text(encoding="utf-8")
    statements = _split_sql_statements(sql_text)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            for statement in statements:
                cur.execute(statement)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    if args.output == "summary":
        print(f"migration_path={migration_path}")
        print(f"statements_applied={len(statements)}")
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
