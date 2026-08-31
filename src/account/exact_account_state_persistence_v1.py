"""Exact-account account-state persistence for explicitly selected accounts.

This module is the persistence counterpart to ``run_exact_account_state_refresh_v1``.
It performs local DB work only. It never constructs a broker client and never
creates execution intent.

The legacy/profile position writer keeps its ``live_trading_enabled == 0`` guard.
This module resolves one exact account by ``trading_account_id + venue`` and may
therefore persist evidence for an enabled LIVE account selected explicitly by the
operator-facing exact-account refresh runner.

Safety:
  broker_private_calls=0
  broker_writes=0
  order_submission=0
  live_orders=0
  decision_gate=none
  execution_planner=none
  executor=none
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from src.account.account_snapshot_models_v1 import WalletBalanceRow, WalletOpenOrderRow
from src.account.account_state_snapshot_alignment_v1 import (
    ACCOUNT_OPEN_ORDER_SNAPSHOT_RUN_SOURCE,
    ACCOUNT_STATE_SNAPSHOT_RUN_SOURCE,
    AccountStateSnapshotRunV1,
    verify_persisted_component_counts,
    write_complete_account_state_snapshot_run,
    write_complete_open_order_snapshot_run,
)
from src.account.run_account_wallet_refresh_v1 import (
    RUNNER_NAME,
    utc_now_naive,
    write_balance_snapshot,
    write_open_order_snapshot,
)
from src.operations.run_broker_account_position_snapshot_writer_v1 import (
    SOURCE_NAME as POSITION_SNAPSHOT_SOURCE_NAME,
    BalanceRow,
    PositionRow,
    PriceRow,
    TradingAccount,
    detect_candle_columns,
    fetch_asset_ids,
    fetch_balances,
    fetch_prices,
    format_decimal,
    write_position_rows,
)


def fetch_exact_persistence_account(
    conn: Any,
    *,
    trading_account_id: int,
    account_code: str,
    venue: str,
) -> TradingAccount:
    """Resolve one enabled account by exact id + venue without a LIVE-mode ban."""
    sql = """
    SELECT
        trading_account_id,
        account_code,
        venue,
        account_mode,
        enabled,
        live_trading_enabled
    FROM trading_account
    WHERE trading_account_id = %s
      AND venue = %s
    LIMIT 1
    """
    with conn.cursor() as cur:
        cur.execute(sql, (trading_account_id, venue))
        row = cur.fetchone()

    if not row:
        raise RuntimeError("EXACT_ACCOUNT_PERSISTENCE_ACCOUNT_NOT_FOUND")
    if int(row["trading_account_id"]) != trading_account_id:
        raise RuntimeError("EXACT_ACCOUNT_PERSISTENCE_IDENTITY_MISMATCH")
    if str(row["account_code"]) != account_code:
        raise RuntimeError("EXACT_ACCOUNT_PERSISTENCE_ACCOUNT_CODE_MISMATCH")
    if str(row["venue"]) != venue:
        raise RuntimeError("EXACT_ACCOUNT_PERSISTENCE_VENUE_MISMATCH")
    if int(row["enabled"]) != 1:
        raise RuntimeError("EXACT_ACCOUNT_PERSISTENCE_ACCOUNT_DISABLED")

    return TradingAccount(
        trading_account_id=int(row["trading_account_id"]),
        account_code=str(row["account_code"]),
        venue=str(row["venue"]),
        account_mode=str(row["account_mode"]),
        enabled=int(row["enabled"]),
        live_trading_enabled=int(row["live_trading_enabled"]),
    )


def _build_exact_position_rows(
    *,
    balances: dict[str, BalanceRow],
    asset_ids: dict[str, int],
    prices: dict[str, PriceRow],
    account: TradingAccount,
    balance_snapshot_ts_utc: Any,
) -> tuple[list[PositionRow], list[str]]:
    rows: list[PositionRow] = []
    skipped_symbols: list[str] = []

    for symbol, balance in sorted(balances.items()):
        asset_id = asset_ids.get(symbol)
        if asset_id is None:
            skipped_symbols.append(symbol)
            continue

        price = prices.get(symbol)
        raw = {
            "source": POSITION_SNAPSHOT_SOURCE_NAME,
            "writer": "exact_account_state_persistence_v1",
            "writer_version": "0.1",
            "account_code": account.account_code,
            "account_mode": account.account_mode,
            "venue": account.venue,
            "balance_snapshot_ts_utc": str(balance_snapshot_ts_utc),
            "currency_code": symbol,
            "available_amount": format_decimal(balance.available_amount),
            "reserved_amount": format_decimal(balance.reserved_amount),
            "total_amount": format_decimal(balance.total_amount),
            "mark_price_eur": None if price is None else format_decimal(price.price_eur),
            "price_ts_utc": None if price is None else str(price.price_ts_utc),
            "broker_submission": False,
            "live_trading_enabled": bool(account.live_trading_enabled),
            "position_mutation": False,
        }
        rows.append(
            PositionRow(
                asset_id=asset_id,
                symbol=symbol,
                quantity_base=balance.total_amount,
                available_quantity_base=balance.available_amount,
                reserved_quantity_base=balance.reserved_amount,
                mark_price_eur=None if price is None else price.price_eur,
                raw_json=json.dumps(raw, sort_keys=True, separators=(",", ":")),
            )
        )
    return rows, skipped_symbols


def _write_exact_positions_from_balance_snapshot(
    conn: Any,
    *,
    account: TradingAccount,
    balance_source_name: str,
    balance_snapshot_ts_utc: Any,
) -> tuple[list[Any], list[str]]:
    balances = fetch_balances(
        conn,
        account=account,
        source_name=balance_source_name,
        snapshot_ts_utc=balance_snapshot_ts_utc,
    )
    symbols = sorted(balances)
    if not symbols:
        return write_position_rows(
            conn,
            account=account,
            snapshot_ts_utc=balance_snapshot_ts_utc,
            rows=[],
            commit=False,
        ), []

    ts_col, price_col = detect_candle_columns(conn)
    asset_ids = fetch_asset_ids(conn, symbols=symbols)
    prices = fetch_prices(
        conn,
        venue=account.venue,
        interval_code="1h",
        symbols=symbols,
        ts_col=ts_col,
        price_col=price_col,
    )
    rows, skipped_symbols = _build_exact_position_rows(
        balances=balances,
        asset_ids=asset_ids,
        prices=prices,
        account=account,
        balance_snapshot_ts_utc=balance_snapshot_ts_utc,
    )
    if skipped_symbols:
        raise RuntimeError(
            "POSITION_SNAPSHOT_INCOMPLETE: missing asset identity for "
            + ",".join(skipped_symbols)
        )
    return write_position_rows(
        conn,
        account=account,
        snapshot_ts_utc=balance_snapshot_ts_utc,
        rows=rows,
        commit=False,
    ), skipped_symbols


def write_exact_aligned_account_state_snapshot(
    conn: Any,
    *,
    trading_account_id: int,
    account_code: str,
    venue: str,
    balances: list[WalletBalanceRow],
    orders: list[WalletOpenOrderRow],
    refresh_started_ts_utc: datetime,
    snapshot_ts_utc: datetime,
) -> AccountStateSnapshotRunV1:
    """Persist one exact-account COMPLETE bundle in the caller transaction."""
    account = fetch_exact_persistence_account(
        conn,
        trading_account_id=trading_account_id,
        account_code=account_code,
        venue=venue,
    )

    balance_writes = write_balance_snapshot(
        conn,
        trading_account_id=trading_account_id,
        venue=venue,
        balances=balances,
        snapshot_ts_utc=snapshot_ts_utc,
        source_name=ACCOUNT_OPEN_ORDER_SNAPSHOT_RUN_SOURCE,
    )
    position_results, skipped_symbols = _write_exact_positions_from_balance_snapshot(
        conn,
        account=account,
        balance_source_name=RUNNER_NAME,
        balance_snapshot_ts_utc=snapshot_ts_utc,
    )
    if skipped_symbols:
        raise RuntimeError("POSITION_SNAPSHOT_INCOMPLETE")

    order_writes = write_open_order_snapshot(
        conn,
        trading_account_id=trading_account_id,
        venue=venue,
        orders=orders,
        snapshot_ts_utc=snapshot_ts_utc,
    )
    if order_writes != len(orders):
        raise RuntimeError("OPEN_ORDER_SNAPSHOT_COUNT_MISMATCH")

    verify_persisted_component_counts(
        conn,
        trading_account_id=trading_account_id,
        venue=venue,
        snapshot_ts_utc=snapshot_ts_utc,
        position_source_name=POSITION_SNAPSHOT_SOURCE_NAME,
        expected_position_count=len(position_results),
        balance_source_name=RUNNER_NAME,
        expected_balance_count=balance_writes,
        expected_open_order_count=order_writes,
    )

    open_order_run_id = write_complete_open_order_snapshot_run(
        conn,
        trading_account_id=trading_account_id,
        venue=venue,
        source_name=RUNNER_NAME,
        snapshot_ts_utc=snapshot_ts_utc,
        open_order_count=order_writes,
    )
    return write_complete_account_state_snapshot_run(
        conn,
        trading_account_id=trading_account_id,
        venue=venue,
        source_name=ACCOUNT_STATE_SNAPSHOT_RUN_SOURCE,
        refresh_started_ts_utc=refresh_started_ts_utc,
        snapshot_ts_utc=snapshot_ts_utc,
        completed_ts_utc=utc_now_naive(),
        position_source_name=POSITION_SNAPSHOT_SOURCE_NAME,
        position_snapshot_count=len(position_results),
        balance_source_name=RUNNER_NAME,
        balance_snapshot_count=balance_writes,
        account_open_order_snapshot_run_id=open_order_run_id,
        expected_open_order_count=order_writes,
    )
