"""Shared sqlite fixtures for Issue #474 automatic BUY account-allocation
evidence tests.

Not a test module itself (no test_ functions). Mirrors the production
MariaDB schema closely enough for the contract/repository/composition tests:
%s placeholders, DictCursor-style rows, lastrowid. Modeled directly on
``tests/automatic_exit_runtime_fixtures_v1.py``'s sqlite fake-connection
pattern, extended with the strategy-bucket account config and automatic-BUY
account permission tables this evidence projection also reads.
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

CREATE TABLE asset (
    asset_id INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL,
    is_enabled INTEGER NOT NULL DEFAULT 1,
    is_tradeable INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE venue_market (
    venue_market_id INTEGER PRIMARY KEY AUTOINCREMENT,
    venue TEXT NOT NULL,
    market TEXT NOT NULL,
    base_asset_id INTEGER NOT NULL,
    quote_currency TEXT NOT NULL,
    is_tradeable INTEGER NOT NULL DEFAULT 1,
    UNIQUE(venue, market)
);

CREATE TABLE account_asset (
    account_asset_id INTEGER PRIMARY KEY AUTOINCREMENT,
    trading_account_id INTEGER NOT NULL,
    venue_market_id INTEGER NOT NULL,
    UNIQUE(trading_account_id, venue_market_id)
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

CREATE TABLE strategy_bucket_account_config_v1 (
    strategy_bucket_account_config_id INTEGER PRIMARY KEY AUTOINCREMENT,
    trading_account_id INTEGER NOT NULL,
    strategy_bucket_id TEXT NOT NULL,
    config_version TEXT NOT NULL,
    is_enabled INTEGER NOT NULL,
    risk_profile TEXT NOT NULL,
    max_position_amount_eur TEXT,
    max_bucket_amount_eur TEXT,
    max_asset_exposure_pct TEXT,
    max_open_positions INTEGER,
    allow_new_entries INTEGER NOT NULL,
    allow_reduce_reviews INTEGER NOT NULL,
    effective_from_ts_utc TEXT NOT NULL,
    effective_until_ts_utc TEXT,
    source_provenance TEXT NOT NULL,
    allocation_target_pct TEXT,
    allocation_max_pct TEXT
);

CREATE TABLE strategy_bucket_account_config_revocation_v1 (
    strategy_bucket_account_config_revocation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_bucket_account_config_id INTEGER NOT NULL,
    trading_account_id INTEGER NOT NULL,
    revocation_version TEXT NOT NULL,
    effective_ts_utc TEXT NOT NULL,
    actor TEXT NOT NULL,
    reason TEXT NOT NULL
);

CREATE TABLE automatic_buy_account_permission_v1 (
    automatic_buy_account_permission_id INTEGER PRIMARY KEY AUTOINCREMENT,
    trading_account_id INTEGER NOT NULL,
    execution_enabled INTEGER NOT NULL,
    effective_from_ts_utc TEXT NOT NULL,
    effective_until_ts_utc TEXT,
    permission_version TEXT NOT NULL,
    source_provenance TEXT NOT NULL
);

CREATE TABLE automatic_buy_account_permission_revocation_v1 (
    automatic_buy_account_permission_revocation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    automatic_buy_account_permission_id INTEGER NOT NULL,
    trading_account_id INTEGER NOT NULL,
    revocation_version TEXT NOT NULL,
    effective_ts_utc TEXT NOT NULL,
    actor TEXT NOT NULL,
    reason TEXT NOT NULL
);

CREATE TABLE account_protection_lock_fact_v1 (
    account_protection_lock_fact_id INTEGER PRIMARY KEY AUTOINCREMENT,
    lifecycle_id TEXT NOT NULL,
    event_id TEXT NOT NULL UNIQUE,
    protection_code TEXT NOT NULL,
    protection_version TEXT NOT NULL,
    trading_account_id INTEGER NOT NULL,
    scope_type TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    observed_from_ts_utc TEXT NOT NULL,
    observed_to_ts_utc TEXT NOT NULL,
    triggered_ts_utc TEXT NOT NULL,
    expires_ts_utc TEXT,
    reason_code TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL,
    configuration_version TEXT NOT NULL,
    lock_state TEXT NOT NULL
);

CREATE TABLE account_protection_policy_config_v1 (
    account_protection_policy_config_id INTEGER PRIMARY KEY AUTOINCREMENT,
    trading_account_id INTEGER NOT NULL,
    config_version TEXT NOT NULL,
    configuration_version TEXT NOT NULL,
    max_account_drawdown TEXT,
    max_daily_realized_loss TEXT,
    max_repeated_stoploss_streak INTEGER,
    max_metric_age_seconds INTEGER NOT NULL,
    effective_from_ts_utc TEXT NOT NULL,
    effective_until_ts_utc TEXT,
    source_provenance TEXT NOT NULL
);

CREATE TABLE account_protection_policy_config_revocation_v1 (
    account_protection_policy_config_revocation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_protection_policy_config_id INTEGER NOT NULL,
    trading_account_id INTEGER NOT NULL,
    revocation_version TEXT NOT NULL,
    effective_ts_utc TEXT NOT NULL,
    actor TEXT NOT NULL,
    reason TEXT NOT NULL
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

CREATE TABLE automatic_buy_runtime_input_v1 (
    automatic_buy_runtime_input_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_snapshot_key TEXT NOT NULL UNIQUE,
    input_contract_version TEXT NOT NULL DEFAULT '1',
    input_state TEXT NOT NULL DEFAULT 'READY',
    evaluation_ts_utc TEXT NOT NULL,
    trading_account_id INTEGER NOT NULL,
    venue TEXT NOT NULL,
    asset_id INTEGER NOT NULL,
    market TEXT NOT NULL,
    strategy_bucket_id TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    setup_id TEXT NOT NULL,
    setup_ready INTEGER NOT NULL,
    current_price TEXT NOT NULL,
    entry_zone_low TEXT,
    entry_zone_high TEXT,
    re_entry_zone_low TEXT,
    re_entry_zone_high TEXT,
    setup_evidence_id TEXT NOT NULL,
    setup_observed_ts_utc TEXT NOT NULL,
    account_observed_ts_utc TEXT NOT NULL,
    account_enabled INTEGER NOT NULL,
    account_mode TEXT NOT NULL,
    automatic_buy_execution_enabled INTEGER NOT NULL,
    live_trading_enabled INTEGER NOT NULL DEFAULT 0,
    free_quote_balance_eur TEXT NOT NULL,
    free_quote_balance_observed_ts_utc TEXT NOT NULL,
    blocking_conflict INTEGER NOT NULL,
    proposed_position_amount_eur TEXT NOT NULL,
    current_bucket_amount_eur TEXT NOT NULL,
    current_open_positions INTEGER NOT NULL,
    current_asset_exposure_pct TEXT NOT NULL,
    max_automatic_buy_notional_eur TEXT,
    source_provenance TEXT NOT NULL
);
"""


class _Cursor:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._cursor = conn.cursor()
        self.lastrowid = 0

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> "_Cursor":
        # SQLite has no row-level locking clause; strip MariaDB's FOR UPDATE
        # (sqlite otherwise raises a syntax error) while leaving production
        # SQL unchanged -- callers that need to prove a query requests the
        # lock should assert on the SQL text before it reaches this fake.
        normalized = sql.replace("FOR UPDATE", "").replace("%s", "?")
        values = tuple(_adapt(value) for value in params)
        self._cursor.execute(normalized, values)
        self.lastrowid = self._cursor.lastrowid
        return self

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


TS = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


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
    position_count: int = 0, balance_count: int = 1, order_count: int = 0,
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


def insert_venue_market(
    conn: FakeConnection, *, venue: str = "bitvavo", market: str = "BTC-EUR",
    asset_id: int = 101, symbol: str = "BTC", quote_currency: str = "EUR", is_tradeable: bool = True,
) -> int:
    with conn.cursor() as cur:
        cur.execute("INSERT OR IGNORE INTO asset (asset_id, symbol) VALUES (%s,%s)", (asset_id, symbol))
        cur.execute(
            "INSERT INTO venue_market (venue, market, base_asset_id, quote_currency, is_tradeable) VALUES (%s,%s,%s,%s,%s)",
            (venue, market, asset_id, quote_currency, is_tradeable),
        )
        return cur.lastrowid


def bind_account_market(conn: FakeConnection, *, account_id: int = 7, venue_market_id: int) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO account_asset (trading_account_id, venue_market_id) VALUES (%s,%s)",
            (account_id, venue_market_id),
        )
        return cur.lastrowid


def insert_balance(
    conn: FakeConnection, *, account_id: int = 7, venue: str = "bitvavo", snapshot_ts_utc: datetime = TS,
    source_name: str = "account_wallet_refresh_v1", currency_code: str = "EUR", available_amount: Decimal = Decimal("1000"),
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


def insert_bucket_config(
    conn: FakeConnection, *, account_id: int = 7, strategy_bucket_id: str = "SHORT_TERM_ROTATION",
    config_version: str = "1", is_enabled: bool = True, risk_profile: str = "standard",
    max_position_amount_eur: Decimal | None = Decimal("250"), max_bucket_amount_eur: Decimal | None = Decimal("1000"),
    max_asset_exposure_pct: Decimal | None = Decimal("50"), max_open_positions: int | None = 5,
    allow_new_entries: bool = True, allow_reduce_reviews: bool = True,
    effective_from_ts_utc: datetime = TS, effective_until_ts_utc: datetime | None = None,
    source_provenance: str = "manual_review",
    allocation_target_pct: Decimal | None = None, allocation_max_pct: Decimal | None = None,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO strategy_bucket_account_config_v1 (trading_account_id, strategy_bucket_id, config_version, is_enabled, risk_profile, max_position_amount_eur, max_bucket_amount_eur, max_asset_exposure_pct, max_open_positions, allow_new_entries, allow_reduce_reviews, effective_from_ts_utc, effective_until_ts_utc, source_provenance, allocation_target_pct, allocation_max_pct) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                account_id, strategy_bucket_id, config_version, is_enabled, risk_profile,
                max_position_amount_eur, max_bucket_amount_eur, max_asset_exposure_pct, max_open_positions,
                allow_new_entries, allow_reduce_reviews, effective_from_ts_utc, effective_until_ts_utc, source_provenance,
                allocation_target_pct, allocation_max_pct,
            ),
        )
        return cur.lastrowid


def insert_buy_permission(
    conn: FakeConnection, *, account_id: int = 7, execution_enabled: bool = True,
    effective_from_ts_utc: datetime = TS, effective_until_ts_utc: datetime | None = None,
    permission_version: str = "1", source_provenance: str = "manual_review",
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO automatic_buy_account_permission_v1 (trading_account_id, execution_enabled, effective_from_ts_utc, effective_until_ts_utc, permission_version, source_provenance) VALUES (%s,%s,%s,%s,%s,%s)",
            (account_id, execution_enabled, effective_from_ts_utc, effective_until_ts_utc, permission_version, source_provenance),
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


def insert_protection_policy_config(
    conn: FakeConnection, *, account_id: int = 7, config_version: str = "1", configuration_version: str = "policy-1",
    max_account_drawdown: Decimal | None = None, max_daily_realized_loss: Decimal | None = None,
    max_repeated_stoploss_streak: int | None = None, max_metric_age_seconds: int = 900,
    effective_from_ts_utc: datetime = TS, effective_until_ts_utc: datetime | None = None,
    source_provenance: str = "manual_review",
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO account_protection_policy_config_v1 (trading_account_id, config_version, configuration_version, "
            "max_account_drawdown, max_daily_realized_loss, max_repeated_stoploss_streak, max_metric_age_seconds, "
            "effective_from_ts_utc, effective_until_ts_utc, source_provenance) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                account_id, config_version, configuration_version, max_account_drawdown, max_daily_realized_loss,
                max_repeated_stoploss_streak, max_metric_age_seconds, effective_from_ts_utc, effective_until_ts_utc,
                source_provenance,
            ),
        )
        return cur.lastrowid


def seed_happy_path(
    conn: FakeConnection, *, account_id: int = 7, venue: str = "bitvavo", position_count: int = 0,
) -> dict[str, Any]:
    """A fully fresh, internally consistent PAPER evidence set.

    ``position_count`` must match the number of ``insert_position`` calls the
    caller makes afterward: the COMPLETE bundle header's declared count is
    cross-checked against the actual row count on every read.
    """
    insert_trading_account(conn, account_id=account_id, venue=venue)
    bundle_ids = insert_complete_bundle(conn, account_id=account_id, venue=venue, position_count=position_count)
    venue_market_id = insert_venue_market(conn, venue=venue)
    bind_account_market(conn, account_id=account_id, venue_market_id=venue_market_id)
    insert_balance(conn, account_id=account_id, venue=venue)
    insert_bucket_config(conn, account_id=account_id)
    insert_buy_permission(conn, account_id=account_id)
    insert_venue_constraint(conn, venue=venue)
    insert_protection_policy_config(conn, account_id=account_id)
    return {"account_id": account_id, "venue": venue, "venue_market_id": venue_market_id, **bundle_ids}
