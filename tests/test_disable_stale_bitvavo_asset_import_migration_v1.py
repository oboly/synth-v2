from __future__ import annotations

import re
from pathlib import Path


MIGRATION = Path(
    "db/migrations/20260724_disable_stale_bitvavo_asset_import_v1.sql"
)
EXPECTED_SYMBOLS = frozenset(
    {"CARDS", "COS", "D", "IP", "MBOX", "NFP", "QTUM", "XION"}
)


def _sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_migration_targets_exact_stale_import_symbol_set() -> None:
    symbols = frozenset(re.findall(r"'([A-Z]+)'", _sql()))
    assert symbols == EXPECTED_SYMBOLS


def test_migration_changes_only_asset_enabled_flag() -> None:
    sql = _sql()
    update = re.search(
        r"UPDATE\s+asset\s+SET\s+(.*?)\s+WHERE",
        sql,
        flags=re.IGNORECASE | re.DOTALL,
    )
    assert update is not None
    assert update.group(1).strip().lower() == "is_enabled = 0"
    assert "DELETE " not in sql.upper()
    assert "TRUNCATE " not in sql.upper()


def test_migration_is_guarded_and_idempotent() -> None:
    sql = _sql()
    assert "target_count <> 8" in sql
    assert "remaining_enabled_count <> 0" in sql
    assert "AND is_enabled <> 0" in sql
    assert "ROLLBACK" in sql
    assert "RESIGNAL" in sql


def test_migration_has_no_alias_or_candle_writer_exception() -> None:
    lowered = _sql().lower()
    for forbidden in (
        "set symbol",
        "insert into asset",
        "update venue_market",
        "obs_market_candle",
        "run_candles_etl",
        "marketunavailableerror",
    ):
        assert forbidden not in lowered
