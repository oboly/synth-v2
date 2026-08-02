from __future__ import annotations

import re
from pathlib import Path

import pytest

MIGRATIONS_DIR = Path("db/migrations")
MARIADB_MAX_IDENTIFIER_LENGTH = 64

# Explicit schema identifiers this migration format can introduce. Table/view
# names are included because CREATE TABLE/VIEW also assigns a new identifier;
# ALTER TABLE target names are pre-existing identifiers and are intentionally
# not matched here.
IDENTIFIER_PATTERNS = [
    re.compile(r"\bCONSTRAINT\s+(\w+)", re.IGNORECASE),
    re.compile(r"\bUNIQUE\s+KEY\s+(\w+)", re.IGNORECASE),
    re.compile(r"\bADD\s+INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)", re.IGNORECASE),
    re.compile(r"(?<!UNIQUE\s)\bKEY\s+(\w+)\s*\(", re.IGNORECASE),
    re.compile(r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)", re.IGNORECASE),
    re.compile(r"\bCREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+(\w+)", re.IGNORECASE),
]


def _migration_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def _explicit_identifiers(sql_text: str) -> list[str]:
    names: list[str] = []
    for pattern in IDENTIFIER_PATTERNS:
        names.extend(pattern.findall(sql_text))
    return names


@pytest.mark.parametrize("migration_path", _migration_files(), ids=lambda p: p.name)
def test_migration_identifiers_fit_mariadb_limit(migration_path: Path) -> None:
    sql_text = migration_path.read_text(encoding="utf-8")
    overlong = [
        name
        for name in _explicit_identifiers(sql_text)
        if len(name) > MARIADB_MAX_IDENTIFIER_LENGTH
    ]
    assert not overlong, (
        f"{migration_path}: identifier(s) exceed MariaDB's "
        f"{MARIADB_MAX_IDENTIFIER_LENGTH}-char limit: {overlong}"
    )
