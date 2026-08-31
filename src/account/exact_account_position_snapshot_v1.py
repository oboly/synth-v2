"""Execution-capability-aware position derivation for exact account snapshots.

Unlike the legacy position writer, this exact-account helper treats canonical
instrument identity separately from automated venue execution. A positive
holding with an ``asset`` row can therefore be represented even when no
``venue_market`` exists (for example an RFQ/manual-trade instrument).

No broker client, decision gate, planner or executor is imported here.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pymysql

from src.execution_capability.execution_capability_v1 import capability_for_mode
from src.operations.run_broker_account_position_snapshot_writer_v1 import (
    SOURCE_NAME,
    WRITER_NAME,
    WRITER_VERSION,
    PositionRow,
    TradingAccount,
    detect_candle_columns,
    fetch_balances,
    fetch_prices,
    format_decimal,
    write_position_rows,
)


@dataclass(frozen=True)
class AssetIdentityV1:
    asset_id: int
    symbol: str
    execution_mode: str


def fetch_asset_identities(conn: Any, *, symbols: list[str]) -> dict[str, AssetIdentityV1]:
    if not symbols:
        return {}
    placeholders = ",".join(["%s"] * len(symbols))
    sql = f"""
    SELECT asset_id, symbol, execution_mode
    FROM asset
    WHERE symbol IN ({placeholders})
    """
    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, symbols)
        rows = cur.fetchall()
    result: dict[str, AssetIdentityV1] = {}
    for row in rows:
        capability_for_mode(row["execution_mode"])
        symbol = str(row["symbol"])
        result[symbol] = AssetIdentityV1(
            asset_id=int(row["asset_id"]),
            symbol=symbol,
            execution_mode=str(row["execution_mode"]),
        )
    return result


def build_exact_position_rows(
    *,
    balances: dict[str, Any],
    assets: dict[str, AssetIdentityV1],
    prices: dict[str, Any],
    account: TradingAccount,
    balance_snapshot_ts_utc: Any,
) -> tuple[list[PositionRow], list[str]]:
    rows: list[PositionRow] = []
    missing_identity: list[str] = []
    for symbol, balance in sorted(balances.items()):
        asset = assets.get(symbol)
        if asset is None:
            missing_identity.append(symbol)
            continue
        capability = capability_for_mode(asset.execution_mode)
        price = prices.get(symbol)
        raw = {
            "source": SOURCE_NAME,
            "writer": WRITER_NAME,
            "writer_version": WRITER_VERSION,
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
            "execution_mode": capability.execution_mode,
            "manual_trade": capability.manual_trade,
            "automated_execution_eligible": capability.automated_execution_eligible,
            "execution_disposition": capability.execution_disposition,
            "broker_submission": False,
            "live_trading_enabled": bool(account.live_trading_enabled),
            "position_mutation": False,
        }
        rows.append(
            PositionRow(
                asset_id=asset.asset_id,
                symbol=symbol,
                quantity_base=balance.total_amount,
                available_quantity_base=balance.available_amount,
                reserved_quantity_base=balance.reserved_amount,
                mark_price_eur=None if price is None else price.price_eur,
                raw_json=json.dumps(raw, sort_keys=True, separators=(",", ":")),
            )
        )
    return rows, missing_identity


def write_exact_positions_from_balance_snapshot(
    conn: Any,
    *,
    account: TradingAccount,
    balance_source_name: str,
    balance_snapshot_ts_utc: Any,
    interval_code: str = "1h",
    commit: bool = True,
):
    balances = fetch_balances(
        conn,
        account=account,
        source_name=balance_source_name,
        snapshot_ts_utc=balance_snapshot_ts_utc,
    )
    symbols = sorted(balances.keys())
    if not symbols:
        return write_position_rows(
            conn,
            account=account,
            snapshot_ts_utc=balance_snapshot_ts_utc,
            rows=[],
            commit=commit,
        ), []

    assets = fetch_asset_identities(conn, symbols=symbols)
    # Price evidence is optional for snapshot completeness. Manual/non-market
    # instruments can still be held canonically with mark_price_eur=NULL.
    try:
        ts_col, price_col = detect_candle_columns(conn)
        prices = fetch_prices(
            conn,
            venue=account.venue,
            interval_code=interval_code,
            symbols=symbols,
            ts_col=ts_col,
            price_col=price_col,
        )
    except RuntimeError:
        prices = {}

    rows, missing_identity = build_exact_position_rows(
        balances=balances,
        assets=assets,
        prices=prices,
        account=account,
        balance_snapshot_ts_utc=balance_snapshot_ts_utc,
    )
    if missing_identity:
        raise RuntimeError(
            "POSITION_SNAPSHOT_INCOMPLETE: missing asset identity for "
            + ",".join(missing_identity)
        )
    return write_position_rows(
        conn,
        account=account,
        snapshot_ts_utc=balance_snapshot_ts_utc,
        rows=rows,
        commit=commit,
    ), []
