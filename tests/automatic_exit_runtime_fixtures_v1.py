"""Shared sqlite fixtures for Phase 4B automatic-exit runtime tests.

Not a test module itself (no test_ functions). Mirrors the production MariaDB
schema closely enough for the repository/orchestrator/audit-writer/cycle
tests: %s placeholders, DictCursor-style rows, lastrowid.
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any


SCHEMA = """
PRAGMA foreign_keys = OFF;

CREATE TABLE trading_account (
    trading_account_id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_code TEXT NOT NULL UNIQUE,
    venue TEXT NOT NULL,
    account_mode TEXT NOT NULL DEFAULT 'paper',
    enabled INTEGER NOT NULL DEFAULT 1,
    live_trading_enabled INTEGER NOT NULL DEFAULT 0,
    created_ts_utc TEXT NOT NULL
);

CREATE TABLE account_open_order_snapshot_run_v1 (
    account_open_order_snapshot_run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    trading_account_id INTEGER NOT NULL,
    venue TEXT NOT NULL,
    source_name TEXT NOT NULL,
    snapshot_ts_utc TEXT NOT NULL,
    snapshot_state TEXT NOT NULL,
    open_order_count INTEGER NOT NULL,
    UNIQUE(trading_account_id, venue, source_name, snapshot_ts_utc)
);

CREATE TABLE account_state_snapshot_run_v1 (
    account_state_snapshot_run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    trading_account_id INTEGER NOT NULL,
    venue TEXT NOT NULL,
    source_name TEXT NOT NULL,
    snapshot_ts_utc TEXT NOT NULL,
    run_state TEXT NOT NULL,
    position_source_name TEXT NOT NULL,
    position_snapshot_count INTEGER NOT NULL,
    balance_source_name TEXT NOT NULL,
    balance_snapshot_count INTEGER NOT NULL,
    account_open_order_snapshot_run_id INTEGER NOT NULL,
    UNIQUE(trading_account_id, venue, source_name, snapshot_ts_utc)
);

CREATE TABLE account_position_snapshot (
    account_position_snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    trading_account_id INTEGER NOT NULL,
    venue TEXT NOT NULL,
    source_name TEXT NOT NULL,
    snapshot_ts_utc TEXT NOT NULL,
    asset_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    quantity_base TEXT NOT NULL,
    available_quantity_base TEXT NOT NULL
);

CREATE TABLE trading_account_balance_snapshot (
    trading_account_balance_snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    trading_account_id INTEGER NOT NULL,
    venue TEXT NOT NULL,
    source_name TEXT NOT NULL,
    snapshot_ts_utc TEXT NOT NULL,
    currency_code TEXT NOT NULL,
    available_amount TEXT NOT NULL
);

CREATE TABLE account_open_order_snapshot (
    account_open_order_snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    trading_account_id INTEGER NOT NULL,
    venue TEXT NOT NULL,
    snapshot_ts_utc TEXT NOT NULL,
    market TEXT NOT NULL
);

CREATE TABLE market_price_snapshot (
    market_price_snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    venue TEXT NOT NULL,
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,
    price TEXT NOT NULL,
    observed_ts_utc TEXT NOT NULL
);

CREATE TABLE automatic_exit_profile_v1 (
    automatic_exit_profile_row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id TEXT NOT NULL,
    profile_version TEXT NOT NULL,
    venue TEXT NOT NULL,
    asset_id INTEGER NOT NULL,
    market TEXT NOT NULL,
    active_target_price TEXT,
    invalidation_price TEXT,
    evidence_id TEXT NOT NULL,
    evidence_provenance TEXT NOT NULL,
    observed_ts_utc TEXT NOT NULL,
    effective_from_ts_utc TEXT NOT NULL,
    effective_until_ts_utc TEXT
);

CREATE TABLE automatic_exit_account_permission_v1 (
    automatic_exit_account_permission_id INTEGER PRIMARY KEY AUTOINCREMENT,
    trading_account_id INTEGER NOT NULL,
    planning_enabled INTEGER NOT NULL,
    effective_from_ts_utc TEXT NOT NULL,
    effective_until_ts_utc TEXT,
    permission_version TEXT NOT NULL,
    source_provenance TEXT NOT NULL
);

CREATE TABLE venue_execution_constraint (
    venue_execution_constraint_id INTEGER PRIMARY KEY AUTOINCREMENT,
    venue TEXT NOT NULL,
    market TEXT NOT NULL,
    tick_size TEXT NOT NULL,
    qty_step_size TEXT NOT NULL,
    min_base_quantity TEXT NOT NULL,
    min_quote_notional TEXT NOT NULL,
    supported_order_types TEXT NOT NULL,
    supported_time_in_force TEXT NOT NULL,
    source_provenance TEXT NOT NULL,
    metadata_synced_ts_utc TEXT NOT NULL,
    UNIQUE(venue, market)
);

CREATE TABLE automatic_exit_evaluation_audit_v1 (
    automatic_exit_evaluation_audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    idempotency_key TEXT NOT NULL UNIQUE,
    runtime_version TEXT NOT NULL,
    trading_account_id INTEGER NOT NULL,
    position_reference TEXT NOT NULL,
    venue TEXT NOT NULL,
    asset_id INTEGER NOT NULL,
    market TEXT NOT NULL,
    source_evidence_json TEXT NOT NULL,
    candidate_state TEXT NOT NULL,
    candidate_action TEXT,
    candidate_reason_code TEXT NOT NULL,
    candidate_evidence_id TEXT,
    exit_profile_id TEXT,
    exit_profile_version TEXT,
    gate_state TEXT,
    gate_reason_code TEXT,
    approved_fraction_candidate TEXT,
    approved_quantity_ceiling_base TEXT,
    planner_state TEXT NOT NULL,
    planner_reason_code TEXT,
    immutable_plan_json TEXT,
    evaluation_ts_utc TEXT NOT NULL,
    planning_ts_utc TEXT
);
"""


class _Cursor:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._cursor = conn.cursor()
        self.lastrowid = 0

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> "_Cursor":
        normalized = sql.replace("%s", "?")
        values = tuple(_adapt(value) for value in params)
        self._cursor.execute(normalized, values)
        self.lastrowid = self._cursor.lastrowid
        return self

    def executemany(self, sql: str, seq_of_params: list[tuple[Any, ...]]) -> None:
        normalized = sql.replace("%s", "?")
        self._cursor.executemany(normalized, [tuple(_adapt(v) for v in params) for params in seq_of_params])

    def fetchone(self) -> dict[str, Any] | None:
        row = self._cursor.fetchone()
        return None if row is None else _parse_row(dict(row))

    def fetchall(self) -> list[dict[str, Any]]:
        return [_parse_row(dict(row)) for row in self._cursor.fetchall()]

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, *args: Any) -> None:
        return None


def _adapt(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(UTC).replace(tzinfo=None).isoformat(sep=" ") if value.tzinfo else value.isoformat(sep=" ")
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bool):
        return int(value)
    return value


def _parse_row(row: dict[str, Any]) -> dict[str, Any]:
    """Mimic pymysql: DATETIME columns come back as naive datetime objects."""
    for key, value in row.items():
        if isinstance(value, str):
            try:
                row[key] = datetime.fromisoformat(value)
            except ValueError:
                pass
    return row


class FakeConnection:
    def __init__(self) -> None:
        self.raw = sqlite3.connect(":memory:")
        self.raw.row_factory = sqlite3.Row
        self.raw.executescript(SCHEMA)
        self.committed = False
        self.rolled_back = False

    def cursor(self) -> _Cursor:
        return _Cursor(self.raw)

    def commit(self) -> None:
        self.raw.commit()
        self.committed = True

    def rollback(self) -> None:
        self.raw.rollback()
        self.rolled_back = True

    def close(self) -> None:
        self.raw.close()


TS = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


def insert_trading_account(
    conn: FakeConnection, *, account_id: int = 7, account_code: str | None = None,
    venue: str = "bitvavo", account_mode: str = "paper", enabled: bool = True, live_trading_enabled: bool = False,
) -> int:
    if account_code is None:
        account_code = f"bitvavo_synth_read_{account_id}"
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO trading_account (trading_account_id, account_code, venue, account_mode, enabled, live_trading_enabled, created_ts_utc) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (account_id, account_code, venue, account_mode, enabled, live_trading_enabled, TS),
        )
    return account_id


def insert_complete_bundle(
    conn: FakeConnection, *, account_id: int = 7, venue: str = "bitvavo", snapshot_ts_utc: datetime = TS,
    position_source_name: str = "bitvavo_private_balance_position_snapshot_v1",
    balance_source_name: str = "account_wallet_refresh_v1",
    position_count: int = 1, balance_count: int = 1, order_count: int = 0,
) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO account_open_order_snapshot_run_v1 (trading_account_id, venue, source_name, snapshot_ts_utc, snapshot_state, open_order_count) VALUES (%s,%s,%s,%s,%s,%s)",
            (account_id, venue, "account_wallet_refresh_v1", snapshot_ts_utc, "COMPLETE", order_count),
        )
        order_run_id = cur.lastrowid
        cur.execute(
            "INSERT INTO account_state_snapshot_run_v1 (trading_account_id, venue, source_name, snapshot_ts_utc, run_state, position_source_name, position_snapshot_count, balance_source_name, balance_snapshot_count, account_open_order_snapshot_run_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (account_id, venue, "account_wallet_refresh_v1", snapshot_ts_utc, "COMPLETE", position_source_name, position_count, balance_source_name, balance_count, order_run_id),
        )
        state_run_id = cur.lastrowid
    return {"account_state_snapshot_run_id": state_run_id, "account_open_order_snapshot_run_id": order_run_id}


def insert_position(
    conn: FakeConnection, *, account_id: int = 7, venue: str = "bitvavo", snapshot_ts_utc: datetime = TS,
    source_name: str = "bitvavo_private_balance_position_snapshot_v1", asset_id: int = 101, symbol: str = "BTC",
    quantity_base: Decimal = Decimal("1.5"), available_quantity_base: Decimal = Decimal("1.5"),
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO account_position_snapshot (trading_account_id, venue, source_name, snapshot_ts_utc, asset_id, symbol, quantity_base, available_quantity_base) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (account_id, venue, source_name, snapshot_ts_utc, asset_id, symbol, quantity_base, available_quantity_base),
        )
        return cur.lastrowid


def insert_balance(
    conn: FakeConnection, *, account_id: int = 7, venue: str = "bitvavo", snapshot_ts_utc: datetime = TS,
    source_name: str = "account_wallet_refresh_v1", currency_code: str = "BTC", available_amount: Decimal = Decimal("1.5"),
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO trading_account_balance_snapshot (trading_account_id, venue, source_name, snapshot_ts_utc, currency_code, available_amount) VALUES (%s,%s,%s,%s,%s,%s)",
            (account_id, venue, source_name, snapshot_ts_utc, currency_code, available_amount),
        )
        return cur.lastrowid


def insert_open_order(
    conn: FakeConnection, *, account_id: int = 7, venue: str = "bitvavo", snapshot_ts_utc: datetime = TS, market: str = "ETH-EUR",
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO account_open_order_snapshot (trading_account_id, venue, snapshot_ts_utc, market) VALUES (%s,%s,%s,%s)",
            (account_id, venue, snapshot_ts_utc, market),
        )
        return cur.lastrowid


def insert_market_price(
    conn: FakeConnection, *, venue: str = "bitvavo", symbol: str = "BTC", market: str = "BTC-EUR",
    price: Decimal = Decimal("50000"), observed_ts_utc: datetime = TS,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO market_price_snapshot (venue, symbol, market, price, observed_ts_utc) VALUES (%s,%s,%s,%s,%s)",
            (venue, symbol, market, price, observed_ts_utc),
        )
        return cur.lastrowid


def insert_exit_profile(
    conn: FakeConnection, *, profile_id: str = "profile-1", profile_version: str = "1", venue: str = "bitvavo",
    asset_id: int = 101, market: str = "BTC-EUR", active_target_price: Decimal | None = Decimal("60000"),
    invalidation_price: Decimal | None = Decimal("40000"), evidence_id: str = "evidence-1",
    evidence_provenance: str = "fib_zone_map_v1", observed_ts_utc: datetime = TS,
    effective_from_ts_utc: datetime = TS, effective_until_ts_utc: datetime | None = None,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO automatic_exit_profile_v1 (profile_id, profile_version, venue, asset_id, market, active_target_price, invalidation_price, evidence_id, evidence_provenance, observed_ts_utc, effective_from_ts_utc, effective_until_ts_utc) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (profile_id, profile_version, venue, asset_id, market, active_target_price, invalidation_price, evidence_id, evidence_provenance, observed_ts_utc, effective_from_ts_utc, effective_until_ts_utc),
        )
        return cur.lastrowid


def insert_permission(
    conn: FakeConnection, *, account_id: int = 7, planning_enabled: bool = True, effective_from_ts_utc: datetime = TS,
    effective_until_ts_utc: datetime | None = None, permission_version: str = "1", source_provenance: str = "manual_review",
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO automatic_exit_account_permission_v1 (trading_account_id, planning_enabled, effective_from_ts_utc, effective_until_ts_utc, permission_version, source_provenance) VALUES (%s,%s,%s,%s,%s,%s)",
            (account_id, planning_enabled, effective_from_ts_utc, effective_until_ts_utc, permission_version, source_provenance),
        )
        return cur.lastrowid


def insert_venue_constraint(
    conn: FakeConnection, *, venue: str = "bitvavo", market: str = "BTC-EUR", tick_size: Decimal = Decimal("0.01"),
    qty_step_size: Decimal = Decimal("0.0001"), min_base_quantity: Decimal = Decimal("0.0001"),
    min_quote_notional: Decimal = Decimal("5"), supported_order_types: str = "limit,market",
    supported_time_in_force: str = "gtc,ioc", source_provenance: str = "BITVAVO_PUBLIC_MARKETS_API_V2",
    metadata_synced_ts_utc: datetime = TS,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO venue_execution_constraint (venue, market, tick_size, qty_step_size, min_base_quantity, min_quote_notional, supported_order_types, supported_time_in_force, source_provenance, metadata_synced_ts_utc) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (venue, market, tick_size, qty_step_size, min_base_quantity, min_quote_notional, supported_order_types, supported_time_in_force, source_provenance, metadata_synced_ts_utc),
        )
        return cur.lastrowid


def seed_happy_path(conn: FakeConnection, *, account_id: int = 7, venue: str = "bitvavo") -> dict[str, Any]:
    """A fully fresh, internally consistent evidence set for one BTC position."""
    insert_trading_account(conn, account_id=account_id, venue=venue)
    bundle_ids = insert_complete_bundle(conn, account_id=account_id, venue=venue)
    position_id = insert_position(conn, account_id=account_id, venue=venue)
    insert_balance(conn, account_id=account_id, venue=venue)
    insert_market_price(conn, venue=venue)
    insert_exit_profile(conn, venue=venue)
    insert_permission(conn, account_id=account_id)
    insert_venue_constraint(conn, venue=venue)
    return {"account_id": account_id, "venue": venue, "position_id": position_id, **bundle_ids}
