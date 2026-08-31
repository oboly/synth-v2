"""Register canonical asset identity without inventing an automated venue market.

Dry-run by default. ``--apply`` mutates only the ``asset`` table and requires
explicit operator/reason provenance. This is intended for instruments that are
tradable manually/RFQ/broker-assisted but are not eligible for Synth's automated
venue execution path.

broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
venue_market_writes=0
"""
from __future__ import annotations

import argparse
import sys
from typing import Any

from src.common.db import get_db_connection
from src.execution_capability.execution_capability_v1 import (
    EXECUTION_MODE_MANUAL,
    EXECUTION_MODE_MANUAL_RFQ,
    normalize_execution_mode,
)
from src.market.run_bitvavo_market_sync_v1 import (
    _build_asset_insert_payload,
    fetch_asset_columns,
)

RUNNER_NAME = "manual_trade_asset_registration_v1"
RUNNER_VERSION = "0.1"
ALLOWED_REGISTRATION_MODES = {EXECUTION_MODE_MANUAL_RFQ, EXECUTION_MODE_MANUAL}


def _require_execution_mode_column(asset_columns: list[dict[str, Any]]) -> None:
    if "execution_mode" not in {str(row["COLUMN_NAME"]) for row in asset_columns}:
        raise RuntimeError("ASSET_EXECUTION_MODE_SCHEMA_MISSING")


def fetch_asset(conn: Any, *, symbol: str) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT asset_id, symbol, asset_class, is_enabled, is_tradeable, execution_mode "
            "FROM asset WHERE symbol = %s LIMIT 1",
            (symbol,),
        )
        row = cur.fetchone()
    return None if row is None else dict(row)


def register_manual_trade_asset(
    conn: Any,
    *,
    symbol: str,
    asset_class: str,
    execution_mode: str,
) -> str:
    symbol = symbol.strip().upper()
    asset_class = asset_class.strip().upper()
    mode = normalize_execution_mode(execution_mode)
    if not symbol:
        raise RuntimeError("SYMBOL_EMPTY")
    if not asset_class:
        raise RuntimeError("ASSET_CLASS_EMPTY")
    if mode not in ALLOWED_REGISTRATION_MODES:
        raise RuntimeError("MANUAL_REGISTRATION_MODE_REQUIRED")

    asset_columns = fetch_asset_columns(conn)
    _require_execution_mode_column(asset_columns)
    existing = fetch_asset(conn, symbol=symbol)
    if existing is not None:
        if str(existing["execution_mode"]) == mode:
            return "EXISTING_MATCH"
        raise RuntimeError(
            f"EXISTING_ASSET_EXECUTION_MODE_CONFLICT:{existing['execution_mode']}:{mode}"
        )

    columns, values = _build_asset_insert_payload(asset_columns, symbol=symbol)
    value_by_column = dict(zip(columns, values))
    value_by_column["asset_class"] = asset_class
    value_by_column["is_enabled"] = 1
    # Economically tradable remains distinct from automated-execution capability.
    value_by_column["is_tradeable"] = 1
    value_by_column["execution_mode"] = mode

    ordered_columns = [str(row["COLUMN_NAME"]) for row in asset_columns if str(row["COLUMN_NAME"]) in value_by_column]
    ordered_values = [value_by_column[name] for name in ordered_columns]
    placeholders = ",".join(["%s"] * len(ordered_columns))
    with conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO asset ({','.join(ordered_columns)}) VALUES ({placeholders})",
            ordered_values,
        )
    return "INSERTED"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Register a manual-trade asset identity without venue-market creation.")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--asset-class", required=True)
    parser.add_argument("--execution-mode", choices=sorted(ALLOWED_REGISTRATION_MODES), required=True)
    parser.add_argument("--apply", action="store_true", default=False)
    parser.add_argument("--operator")
    parser.add_argument("--reason")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    symbol = args.symbol.strip().upper()
    mode = normalize_execution_mode(args.execution_mode)
    print(f"runner={RUNNER_NAME} version={RUNNER_VERSION}")
    print(f"symbol={symbol} asset_class={args.asset_class.strip().upper()} execution_mode={mode}")
    print("manual_trade=true")
    print("venue_market_writes=0")
    print("broker_writes=0")
    print("order_submission=0")

    if not args.apply:
        print("[DRY_RUN] --apply not set; no DB writes performed")
        return 0
    if not str(args.operator or "").strip() or not str(args.reason or "").strip():
        print("[error] --apply requires non-empty --operator and --reason", file=sys.stderr)
        return 1

    conn = get_db_connection()
    try:
        action = register_manual_trade_asset(
            conn,
            symbol=symbol,
            asset_class=args.asset_class,
            execution_mode=mode,
        )
        conn.commit()
        row = fetch_asset(conn, symbol=symbol)
        print(f"db_action={action}")
        print(f"asset_id={row['asset_id'] if row else 'MISSING'}")
        print(f"operator={args.operator}")
        print(f"reason={args.reason}")
        return 0
    except Exception as exc:
        conn.rollback()
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
