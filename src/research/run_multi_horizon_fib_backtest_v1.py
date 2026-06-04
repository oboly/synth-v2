from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.common.db import get_db_connection
from src.research.multi_horizon_fib_backtest_v1 import run_multi_horizon_backtest
from src.research.multi_horizon_fib_contract_v1 import (
    DEFAULT_FEE_BPS_PER_SIDE,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_OVERLAP_CANDLES,
    DEFAULT_PIVOT_SPAN,
    FIB_TRADING_HORIZONS,
    INTERVAL_TO_DELTA,
    Candle,
    ContextRow,
    SAFETY_MARKERS,
    get_horizon_definition,
)


DEFAULT_VENUE = "bitvavo"
DEFAULT_QUOTE = "EUR"
DEFAULT_WORKERS = 1
DEFAULT_CONTEXT_PATHS = (
    Path("data/research/historical_breath_regime_context_builder_v1/historical_breath_regime_context_rows_v1.csv"),
    Path("data/research/historical_market_breath_source_recompute_v1/historical_market_breath_source_recomputed_rows_v1.csv"),
)


@dataclass(frozen=True)
class AssetRef:
    asset_id: int
    symbol: str


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Research-only incremental multi-horizon fib backtest foundation "
            "(market-only, account-agnostic, read-only candle inputs, no execution)."
        )
    )
    parser.add_argument("--mode", choices=("bootstrap", "incremental", "rebuild"), default="bootstrap")
    parser.add_argument("--horizons", default="SHORT,MEDIUM,LONG")
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--quote", default=DEFAULT_QUOTE)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--fee-bps-per-side", default=str(DEFAULT_FEE_BPS_PER_SIDE))
    parser.add_argument("--overlap-candles", type=int, default=DEFAULT_OVERLAP_CANDLES)
    parser.add_argument("--pivot-span", type=int, default=DEFAULT_PIVOT_SPAN)
    parser.add_argument("--write-files", action="store_true")
    parser.add_argument("--output", choices=("summary", "json"), default="summary")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args(argv)


def parse_symbols_arg(value: str | None) -> list[str] | None:
    if not value:
        return None
    return sorted({piece.strip().upper() for piece in str(value).split(",") if piece.strip()})


def parse_horizons_arg(value: str) -> list[str]:
    items = [piece.strip().upper() for piece in str(value).split(",") if piece.strip()]
    if not items:
        raise ValueError("At least one horizon is required.")
    invalid = [item for item in items if item not in FIB_TRADING_HORIZONS]
    if invalid:
        raise ValueError(f"Unsupported horizons: {', '.join(invalid)}")
    return items


def _table_columns(conn: Any, table_name: str) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = %s",
            (table_name,),
        )
        return {str(row["column_name"]) for row in cur.fetchall()}


def fetch_assets(conn: Any, *, symbols: list[str] | None, quote: str) -> list[AssetRef]:
    columns = _table_columns(conn, "asset")
    where: list[str] = []
    params: list[Any] = []
    if "is_enabled" in columns:
        where.append("is_enabled = 1")
    if symbols:
        where.append("UPPER(symbol) IN (" + ",".join(["%s"] * len(symbols)) + ")")
        params.extend(symbols)
    elif "quote_asset" in columns:
        where.append("UPPER(quote_asset) = UPPER(%s)")
        params.append(quote)
    sql = "SELECT asset_id, symbol FROM asset"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY symbol ASC"
    with conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        rows = cur.fetchall() or []
    return [AssetRef(asset_id=int(row["asset_id"]), symbol=str(row["symbol"]).upper()) for row in rows]


def fetch_candles(
    conn: Any,
    *,
    assets: list[AssetRef],
    venue: str,
    quote: str,
    interval_codes: list[str],
) -> dict[str, dict[str, list[Candle]]]:
    if not assets or not interval_codes:
        return {}
    placeholders_assets = ",".join(["%s"] * len(assets))
    placeholders_intervals = ",".join(["%s"] * len(interval_codes))
    sql = f"""
        SELECT c.asset_id, a.symbol, c.venue, c.interval_code, c.open_ts_utc, c.close_ts_utc,
               c.open_price, c.high_price, c.low_price, c.close_price
        FROM obs_market_candle c
        JOIN asset a ON a.asset_id = c.asset_id
        WHERE c.venue = %s
          AND c.interval_code IN ({placeholders_intervals})
          AND c.asset_id IN ({placeholders_assets})
        ORDER BY a.symbol ASC, c.interval_code ASC, c.close_ts_utc ASC
    """
    params: list[Any] = [venue, *interval_codes, *[asset.asset_id for asset in assets]]
    grouped: dict[str, dict[str, list[Candle]]] = {
        asset.symbol: {interval: [] for interval in interval_codes} for asset in assets
    }
    with conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        for row in cur.fetchall() or []:
            symbol = str(row["symbol"]).upper()
            open_ts = row["open_ts_utc"].replace(tzinfo=UTC) if row["open_ts_utc"].tzinfo is None else row["open_ts_utc"].astimezone(UTC)
            close_ts = row["close_ts_utc"].replace(tzinfo=UTC) if row["close_ts_utc"].tzinfo is None else row["close_ts_utc"].astimezone(UTC)
            grouped.setdefault(symbol, {}).setdefault(str(row["interval_code"]), []).append(
                Candle(
                    symbol=symbol,
                    venue=str(row["venue"]),
                    quote=quote,
                    interval_code=str(row["interval_code"]),
                    open_ts_utc=open_ts,
                    close_ts_utc=close_ts,
                    open_price=Decimal(str(row["open_price"])),
                    high_price=Decimal(str(row["high_price"])),
                    low_price=Decimal(str(row["low_price"])),
                    close_price=Decimal(str(row["close_price"])),
                )
            )
    return grouped


def _parse_context_ts(text: str | None) -> datetime | None:
    if not text:
        return None
    return datetime.fromisoformat(str(text).replace("Z", "+00:00")).astimezone(UTC)


def load_context_rows(symbols: list[str]) -> dict[str, list[ContextRow]]:
    grouped: dict[str, list[ContextRow]] = {symbol: [] for symbol in symbols}
    for path in DEFAULT_CONTEXT_PATHS:
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                symbol = str(row.get("symbol") or "").upper()
                if symbol not in grouped:
                    continue
                ts = _parse_context_ts(
                    row.get("sample_ts_utc")
                    or row.get("close_ts_utc")
                    or row.get("asof_ts_utc")
                    or row.get("ts_utc")
                )
                if ts is None:
                    continue
                grouped[symbol].append(
                    ContextRow(
                        symbol=symbol,
                        sample_ts_utc=ts,
                        market_regime=str(row.get("market_regime") or "UNKNOWN").upper(),
                        symbol_regime=str(row.get("symbol_regime") or "UNKNOWN").upper(),
                        breath_phase=str(row.get("breath_phase") or "UNKNOWN").upper(),
                        breath_alignment=str(row.get("breath_alignment") or "UNKNOWN").upper(),
                    )
                )
    for symbol in grouped:
        grouped[symbol] = sorted(grouped[symbol], key=lambda item: item.sample_ts_utc)
    return grouped


def build_symbol_inputs(
    *,
    assets: list[AssetRef],
    candles_by_symbol: dict[str, dict[str, list[Candle]]],
    context_rows_by_symbol: dict[str, list[ContextRow]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for asset in assets:
        rows.append(
            {
                "symbol": asset.symbol,
                "candles_by_interval": candles_by_symbol.get(asset.symbol, {}),
                "context_rows": context_rows_by_symbol.get(asset.symbol, []),
            }
        )
    return rows


def build_summary_lines(result: dict[str, Any]) -> list[str]:
    manifest = result["manifest"]
    row_counts = manifest["row_counts"]
    return [
        f"mode={manifest['mode']} workers={manifest['workers']} fee_bps_per_side={manifest['fee_bps_per_side']}",
        f"symbols={','.join(manifest['symbols']) or 'none'} horizons={','.join(manifest['horizons'])}",
        f"swing_events={row_counts['swing_events']} active_swings={row_counts['active_swing_rows']} fib_outcomes={row_counts['fib_level_outcomes']}",
        f"profile_stats={row_counts['profile_stats']} context_profile_stats={row_counts['context_profile_stats']}",
        "broker_writes=0 order_submission=0 executor=none db_writes=0",
    ]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    horizons = parse_horizons_arg(args.horizons)
    symbols = parse_symbols_arg(args.symbols)
    needed_intervals = sorted(
        {
            interval
            for horizon_name in horizons
            for interval in (
                get_horizon_definition(horizon_name).primary_interval,
                *get_horizon_definition(horizon_name).supporting_intervals,
            )
        }
    )
    conn = get_db_connection()
    try:
        assets = fetch_assets(conn, symbols=symbols, quote=args.quote)
        if symbols:
            existing = {asset.symbol for asset in assets}
            for missing in sorted(set(symbols) - existing):
                assets.append(AssetRef(asset_id=-1, symbol=missing))
            assets = sorted(assets, key=lambda item: item.symbol)
        candles_by_symbol = fetch_candles(
            conn,
            assets=[asset for asset in assets if asset.asset_id > 0],
            venue=args.venue,
            quote=args.quote,
            interval_codes=needed_intervals,
        )
    finally:
        conn.close()
    context_rows_by_symbol = load_context_rows([asset.symbol for asset in assets])
    symbol_inputs = build_symbol_inputs(
        assets=assets,
        candles_by_symbol=candles_by_symbol,
        context_rows_by_symbol=context_rows_by_symbol,
    )
    result = run_multi_horizon_backtest(
        mode=args.mode,
        output_dir=Path(args.output_dir),
        symbol_inputs=symbol_inputs,
        horizons=horizons,
        venue=args.venue,
        quote=args.quote,
        workers=max(int(args.workers), 1),
        fee_bps_per_side=Decimal(str(args.fee_bps_per_side)),
        overlap_candles=max(int(args.overlap_candles), 0),
        pivot_span=max(int(args.pivot_span), 1),
        write_files=bool(args.write_files),
    )
    if args.output == "json":
        print(json.dumps(result["manifest"], indent=2, sort_keys=True))
    else:
        for line in build_summary_lines(result):
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
