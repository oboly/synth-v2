"""
Structural tests for db/migrations/20260628_execution_ladder_profiles_v1.sql.

These tests verify the migration file content without requiring a live database.
"""

from __future__ import annotations

from pathlib import Path

import pytest

MIGRATION_PATH = Path("db/migrations/20260628_execution_ladder_profiles_v1.sql")

_REQUIRED_TABLES = [
    "execution_sizing_variable_ref",
    "execution_sizing_rule",
    "execution_ladder_profile",
    "execution_ladder_leg",
]

_REQUIRED_VARIABLE_KEYS = [
    "MANUAL_QUOTE_AMOUNT",
    "FIXED_QUOTE_AMOUNT",
    "FREE_QUOTE_BALANCE",
    "TOTAL_WALLET_QUOTE_VALUE",
    "COIN_POSITION_QUOTE_VALUE",
    "FREE_BASE_QUANTITY",
]


@pytest.fixture(scope="module")
def migration_sql() -> str:
    assert MIGRATION_PATH.exists(), f"migration file not found: {MIGRATION_PATH}"
    return MIGRATION_PATH.read_text(encoding="utf-8")


def test_migration_file_exists() -> None:
    assert MIGRATION_PATH.exists()


def test_migration_has_boundary_comment(migration_sql: str) -> None:
    assert "-- Migration: execution_ladder_profiles_v1" in migration_sql
    assert "-- Boundary:" in migration_sql
    assert "-- Non-goals:" in migration_sql


def test_migration_creates_four_tables(migration_sql: str) -> None:
    for table in _REQUIRED_TABLES:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in migration_sql, (
            f"expected CREATE TABLE IF NOT EXISTS {table}"
        )


def test_migration_uses_trading_account_id_not_account_id(migration_sql: str) -> None:
    assert "trading_account_id" in migration_sql
    # execution layer tables must not introduce bare account_id FK
    lines_with_account_id = [
        line for line in migration_sql.splitlines()
        if "account_id" in line and "trading_account_id" not in line
        and not line.strip().startswith("--")
    ]
    assert lines_with_account_id == [], (
        f"found bare 'account_id' without 'trading_account' prefix: {lines_with_account_id}"
    )


def test_migration_seeds_six_variable_refs(migration_sql: str) -> None:
    for key in _REQUIRED_VARIABLE_KEYS:
        assert f"'{key}'" in migration_sql, (
            f"expected variable_key {key!r} in INSERT seed block"
        )


def test_migration_seeds_include_display_label(migration_sql: str) -> None:
    assert "Manual trade amount" in migration_sql
    assert "Fixed trade amount" in migration_sql
    assert "Free quote balance" in migration_sql
    assert "Total wallet value" in migration_sql
    assert "Coin position value" in migration_sql
    assert "Free asset quantity" in migration_sql


def test_migration_seeds_include_description_text(migration_sql: str) -> None:
    assert "final requested trade amount" in migration_sql
    assert "hard sell-cap constraint" in migration_sql


def test_migration_uses_native_short_anchor_high(migration_sql: str) -> None:
    assert "NATIVE_SHORT_ANCHOR_HIGH" in migration_sql


def test_migration_does_not_use_ppp_price(migration_sql: str) -> None:
    assert "PPP_PRICE" not in migration_sql


def test_migration_does_not_store_number_of_trades(migration_sql: str) -> None:
    assert "number_of_trades" not in migration_sql


def test_migration_idempotent_on_duplicate_key(migration_sql: str) -> None:
    assert "ON DUPLICATE KEY UPDATE" in migration_sql


def test_migration_fk_to_trading_account(migration_sql: str) -> None:
    assert "REFERENCES trading_account (trading_account_id)" in migration_sql


def test_migration_allocation_bps_positive_check(migration_sql: str) -> None:
    assert "CHECK (allocation_bps > 0)" in migration_sql


def test_migration_leg_number_positive_check(migration_sql: str) -> None:
    assert "CHECK (leg_number > 0)" in migration_sql


def test_migration_order_type_limit_check(migration_sql: str) -> None:
    assert "CHECK (order_type = 'LIMIT')" in migration_sql


def test_migration_note_on_cross_row_sum(migration_sql: str) -> None:
    # Cross-row sum enforcement is documented as resolver responsibility
    assert "resolver" in migration_sql.lower()
