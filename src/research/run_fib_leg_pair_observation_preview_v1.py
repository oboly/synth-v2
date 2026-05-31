from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.common.db import get_connection


REPORT_NAME = "fib_leg_pair_observation_preview_v1"
REPORT_VERSION = "0.1"

DEFAULT_VENUE = "bitvavo"
DEFAULT_QUOTE = "EUR"
DEFAULT_INTERVAL = "4h"
DEFAULT_LOOKBACK_CANDLES = 240
DEFAULT_SWING_WINDOW = 5
DEFAULT_LIMIT_ASSETS = 80
DEFAULT_OUTPUT_DIR = Path("data/research/fib_leg_pair_observation_preview_v1")

ROWS_CSV = "fib_leg_pair_observation_preview_rows_v1.csv"
ROWS_JSONL = "fib_leg_pair_observation_preview_rows_v1.jsonl"
SUMMARY_JSON = "summary.json"
SOURCE_TABLE = "obs_market_candle"
DETECTOR_NAME = "pivot_leg_pair_detector"
DETECTOR_VERSION = "1"

ROW_FIELDS = [
    "venue",
    "symbol",
    "interval_code",
    "asof_ts_utc",
    "source_table",
    "detector_name",
    "detector_version",
    "lookback_candles",
    "swing_window",
    "input_first_ts_utc",
    "input_last_ts_utc",
    "leg1_start_ts_utc",
    "leg1_start_price",
    "leg1_finish_ts_utc",
    "leg1_finish_price",
    "leg2_start_ts_utc",
    "leg2_start_price",
    "leg2_finish_ts_utc",
    "leg2_finish_price",
    "pivot_count",
    "leg_pair_index",
    "generated_at_utc",
    "derived_leg1_move_abs",
    "derived_leg2_move_abs",
    "derived_realized_multiplier",
    "derived_leg1_direction",
    "derived_leg2_direction",
    "derived_same_direction",
    "derived_opposite_direction",
    "derived_leg1_duration_candles",
    "derived_leg2_duration_candles",
]

SUMMARY_FIELD_ORDER = [
    "report",
    "version",
    "rows",
    "symbols",
    "complete_rows",
    "incomplete_rows",
    "output_dir",
    "db_writes",
    "broker_private_calls",
    "broker_writes",
    "order_submission",
    "decision_gate_changes",
    "execution_planner_changes",
    "executor",
    "account_awareness",
]


@dataclass(frozen=True)
class AssetRef:
    asset_id: int
    symbol: str


@dataclass(frozen=True)
class Candle:
    asset_id: int
    symbol: str
    open_ts_utc: datetime
    close_ts_utc: datetime
    high_price: float
    low_price: float


@dataclass(frozen=True)
class Pivot:
    candle_index: int
    pivot_kind: str
    ts_utc: datetime
    price: float


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build measurement-first fib leg-pair observations from public market candles "
            "(research-only, no fib targets, no account logic, no execution)."
        )
    )
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--quote", default=DEFAULT_QUOTE)
    parser.add_argument("--interval", default=DEFAULT_INTERVAL)
    parser.add_argument("--lookback-candles", type=int, default=DEFAULT_LOOKBACK_CANDLES)
    parser.add_argument("--swing-window", type=int, default=DEFAULT_SWING_WINDOW)
    parser.add_argument("--limit-assets", type=int, default=DEFAULT_LIMIT_ASSETS)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--write-files", action="store_true")
    parser.add_argument("--output", choices=("summary", "json"), default="summary")
    return parser.parse_args(argv)


def fmt_ts(value: datetime | None) -> str:
    if value is None:
        return ""
    normalized = value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized.isoformat().replace("+00:00", "Z")


def fmt_price(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.10f}"


def fmt_number(value: float | None, digits: int = 6) -> str:
    if value is None:
        return ""
    return f"{value:.{digits}f}"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=False, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True, sort_keys=False) + "\n")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ROW_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def table_columns(conn: Any, table_name: str) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = DATABASE()
              AND table_name = %s
            """,
            (table_name,),
        )
        return {str(row["column_name"]) for row in cur.fetchall()}


def fetch_assets(
    conn: Any,
    *,
    quote: str,
    limit_assets: int,
) -> list[AssetRef]:
    columns = table_columns(conn, "asset")
    where: list[str] = []
    params: list[Any] = []

    if "is_enabled" in columns:
        where.append("is_enabled = 1")
    if "quote_asset" in columns:
        where.append("UPPER(quote_asset) = UPPER(%s)")
        params.append(quote)
    elif "quote_currency" in columns:
        where.append("UPPER(quote_currency) = UPPER(%s)")
        params.append(quote)

    sql = "SELECT asset_id, symbol FROM asset"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY symbol ASC"
    if limit_assets > 0:
        sql += " LIMIT %s"
        params.append(int(limit_assets))

    with conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()

    return [
        AssetRef(asset_id=int(row["asset_id"]), symbol=str(row["symbol"]).upper())
        for row in rows
    ]


def fetch_recent_candles(
    conn: Any,
    *,
    assets: list[AssetRef],
    venue: str,
    interval_code: str,
    lookback_candles: int,
) -> dict[str, list[Candle]]:
    if not assets:
        return {}

    asset_ids = [asset.asset_id for asset in assets]
    placeholders = ",".join(["%s"] * len(asset_ids))
    sql = f"""
        SELECT
            c.asset_id,
            a.symbol,
            c.open_ts_utc,
            c.close_ts_utc,
            c.high_price,
            c.low_price
        FROM obs_market_candle c
        JOIN asset a
          ON a.asset_id = c.asset_id
        WHERE c.venue = %s
          AND c.interval_code = %s
          AND c.asset_id IN ({placeholders})
        ORDER BY c.asset_id ASC, c.close_ts_utc DESC
    """
    params: list[Any] = [venue, interval_code, *asset_ids]

    grouped: dict[str, list[Candle]] = {asset.symbol: [] for asset in assets}
    counts: dict[str, int] = {}

    with conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()

    for row in rows:
        symbol = str(row["symbol"]).upper()
        taken = counts.get(symbol, 0)
        if taken >= lookback_candles:
            continue

        open_ts = row["open_ts_utc"]
        close_ts = row["close_ts_utc"]
        if open_ts.tzinfo is None:
            open_ts = open_ts.replace(tzinfo=UTC)
        else:
            open_ts = open_ts.astimezone(UTC)
        if close_ts.tzinfo is None:
            close_ts = close_ts.replace(tzinfo=UTC)
        else:
            close_ts = close_ts.astimezone(UTC)

        grouped[symbol].append(
            Candle(
                asset_id=int(row["asset_id"]),
                symbol=symbol,
                open_ts_utc=open_ts,
                close_ts_utc=close_ts,
                high_price=float(row["high_price"]),
                low_price=float(row["low_price"]),
            )
        )
        counts[symbol] = taken + 1

    return {
        symbol: list(reversed(candles))
        for symbol, candles in grouped.items()
        if candles
    }


def detect_pivots(candles: list[Candle], swing_window: int) -> list[Pivot]:
    if len(candles) < (swing_window * 2) + 1:
        return []

    candidates: list[Pivot] = []
    for index in range(swing_window, len(candles) - swing_window):
        left = index - swing_window
        right = index + swing_window + 1
        window = candles[left:right]
        current = candles[index]

        window_highs = [candle.high_price for candle in window]
        window_lows = [candle.low_price for candle in window]
        current_high = current.high_price
        current_low = current.low_price

        is_pivot_high = (
            current_high == max(window_highs) and window_highs.count(current_high) == 1
        )
        is_pivot_low = current_low == min(window_lows) and window_lows.count(current_low) == 1

        if is_pivot_high and is_pivot_low:
            continue
        if is_pivot_high:
            candidates.append(
                Pivot(
                    candle_index=index,
                    pivot_kind="HIGH",
                    ts_utc=current.close_ts_utc,
                    price=current_high,
                )
            )
        elif is_pivot_low:
            candidates.append(
                Pivot(
                    candle_index=index,
                    pivot_kind="LOW",
                    ts_utc=current.close_ts_utc,
                    price=current_low,
                )
            )
        else:
            continue

    if not candidates:
        return []

    compressed: list[Pivot] = []
    for pivot in candidates:
        if not compressed:
            compressed.append(pivot)
            continue

        previous = compressed[-1]
        if pivot.pivot_kind != previous.pivot_kind:
            compressed.append(pivot)
            continue

        if pivot.pivot_kind == "HIGH":
            if pivot.price >= previous.price:
                compressed[-1] = pivot
        else:
            if pivot.price <= previous.price:
                compressed[-1] = pivot

    return compressed


def direction_for(start_price: float, finish_price: float) -> str:
    if finish_price > start_price:
        return "UP"
    if finish_price < start_price:
        return "DOWN"
    return "FLAT"


def build_row(
    *,
    venue: str,
    symbol: str,
    interval_code: str,
    lookback_candles: int,
    swing_window: int,
    candles: list[Candle],
    pivots: list[Pivot],
    leg_pair_index: int,
    generated_at_utc: datetime,
) -> dict[str, Any]:
    pivot_a = pivots[leg_pair_index]
    pivot_b = pivots[leg_pair_index + 1]
    pivot_c = pivots[leg_pair_index + 2]

    leg1_move_abs = abs(pivot_b.price - pivot_a.price)
    leg2_move_abs = abs(pivot_c.price - pivot_b.price)
    realized_multiplier = None
    if leg1_move_abs > 0:
        realized_multiplier = leg2_move_abs / leg1_move_abs

    leg1_direction = direction_for(pivot_a.price, pivot_b.price)
    leg2_direction = direction_for(pivot_b.price, pivot_c.price)

    return {
        "venue": venue,
        "symbol": symbol,
        "interval_code": interval_code,
        "asof_ts_utc": fmt_ts(candles[-1].close_ts_utc),
        "source_table": SOURCE_TABLE,
        "detector_name": DETECTOR_NAME,
        "detector_version": DETECTOR_VERSION,
        "lookback_candles": str(lookback_candles),
        "swing_window": str(swing_window),
        "input_first_ts_utc": fmt_ts(candles[0].close_ts_utc),
        "input_last_ts_utc": fmt_ts(candles[-1].close_ts_utc),
        "leg1_start_ts_utc": fmt_ts(pivot_a.ts_utc),
        "leg1_start_price": fmt_price(pivot_a.price),
        "leg1_finish_ts_utc": fmt_ts(pivot_b.ts_utc),
        "leg1_finish_price": fmt_price(pivot_b.price),
        "leg2_start_ts_utc": fmt_ts(pivot_b.ts_utc),
        "leg2_start_price": fmt_price(pivot_b.price),
        "leg2_finish_ts_utc": fmt_ts(pivot_c.ts_utc),
        "leg2_finish_price": fmt_price(pivot_c.price),
        "pivot_count": str(len(pivots)),
        "leg_pair_index": str(leg_pair_index),
        "generated_at_utc": fmt_ts(generated_at_utc),
        "derived_leg1_move_abs": fmt_number(leg1_move_abs, digits=10),
        "derived_leg2_move_abs": fmt_number(leg2_move_abs, digits=10),
        "derived_realized_multiplier": fmt_number(realized_multiplier),
        "derived_leg1_direction": leg1_direction,
        "derived_leg2_direction": leg2_direction,
        "derived_same_direction": "1" if leg1_direction == leg2_direction else "0",
        "derived_opposite_direction": (
            "1"
            if {leg1_direction, leg2_direction} == {"UP", "DOWN"}
            else "0"
        ),
        "derived_leg1_duration_candles": str(pivot_b.candle_index - pivot_a.candle_index),
        "derived_leg2_duration_candles": str(pivot_c.candle_index - pivot_b.candle_index),
    }


def is_complete_row(row: dict[str, Any]) -> bool:
    required = [
        "venue",
        "symbol",
        "interval_code",
        "asof_ts_utc",
        "source_table",
        "detector_name",
        "detector_version",
        "lookback_candles",
        "swing_window",
        "input_first_ts_utc",
        "input_last_ts_utc",
        "leg1_start_ts_utc",
        "leg1_start_price",
        "leg1_finish_ts_utc",
        "leg1_finish_price",
        "leg2_start_ts_utc",
        "leg2_start_price",
        "leg2_finish_ts_utc",
        "leg2_finish_price",
    ]
    if any(not row.get(field) for field in required):
        return False
    if row.get("derived_realized_multiplier") == "":
        return False
    return True


def build_summary(*, rows: list[dict[str, Any]], output_dir: Path) -> dict[str, Any]:
    complete_rows = sum(1 for row in rows if is_complete_row(row))
    return {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "rows": len(rows),
        "symbols": len({row["symbol"] for row in rows}),
        "complete_rows": complete_rows,
        "incomplete_rows": len(rows) - complete_rows,
        "output_dir": str(output_dir),
        "db_writes": 0,
        "broker_private_calls": 0,
        "broker_writes": 0,
        "order_submission": 0,
        "decision_gate_changes": 0,
        "execution_planner_changes": 0,
        "executor": "none",
        "account_awareness": 0,
    }


def print_summary(summary: dict[str, Any]) -> None:
    for field in SUMMARY_FIELD_ORDER:
        print(f"{field}={summary[field]}")


def build_rows(args: argparse.Namespace) -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        assets = fetch_assets(conn, quote=args.quote, limit_assets=args.limit_assets)
        candles_by_symbol = fetch_recent_candles(
            conn,
            assets=assets,
            venue=args.venue,
            interval_code=args.interval,
            lookback_candles=args.lookback_candles,
        )
    finally:
        conn.close()

    generated_at_utc = datetime.now(UTC)
    rows: list[dict[str, Any]] = []

    for symbol in sorted(candles_by_symbol):
        candles = candles_by_symbol[symbol]
        if len(candles) < 3:
            continue
        pivots = detect_pivots(candles, args.swing_window)
        if len(pivots) < 3:
            continue
        for leg_pair_index in range(len(pivots) - 2):
            rows.append(
                build_row(
                    venue=args.venue,
                    symbol=symbol,
                    interval_code=args.interval,
                    lookback_candles=args.lookback_candles,
                    swing_window=args.swing_window,
                    candles=candles,
                    pivots=pivots,
                    leg_pair_index=leg_pair_index,
                    generated_at_utc=generated_at_utc,
                )
            )

    return rows


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.lookback_candles <= 0:
        raise ValueError("--lookback-candles must be > 0")
    if args.swing_window <= 0:
        raise ValueError("--swing-window must be > 0")
    if args.limit_assets < 0:
        raise ValueError("--limit-assets must be >= 0")

    output_dir = Path(args.output_dir)
    rows = build_rows(args)
    summary = build_summary(rows=rows, output_dir=output_dir)

    if args.write_files:
        output_dir.mkdir(parents=True, exist_ok=True)
        write_csv(output_dir / ROWS_CSV, rows)
        write_jsonl(output_dir / ROWS_JSONL, rows)
        write_json(output_dir / SUMMARY_JSON, summary)

    if args.output == "json":
        print(json.dumps(summary, indent=2, sort_keys=False))
    else:
        print_summary(summary)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
