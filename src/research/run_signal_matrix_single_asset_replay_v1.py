from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any

from src.common.db import get_connection


REPORT_NAME = "signal_matrix_single_asset_replay_v1"
REPORT_VERSION = "1.0"
DEFAULT_VENUE = "bitvavo"
DEFAULT_SYMBOL = "XLM"
DEFAULT_QUOTE = "EUR"
DEFAULT_START_DATE = "2026-01-01"
DEFAULT_TIMEFRAMES = ("15m", "1h", "4h", "1d")
DEFAULT_OUTPUT_DIR = Path("data/research/signal_matrix_single_asset_replay_v1")
BTC_SYMBOL = "BTC"
ROLLING_RETURN_LOOKBACK = 8
ROLLING_LEVEL_LOOKBACK = 20
RANGE_LOOKBACK = 12
VOLUME_EXPANSION_MULTIPLIER = 1.5
RANGE_EXPANSION_MULTIPLIER = 1.5
MAX_TIMEFRAME_STALENESS_MULTIPLIER = 1.5
TIMEFRAME_DELTAS = {
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
}


@dataclass(frozen=True)
class Candle:
    close_ts_utc: datetime
    open_price: float | None
    high_price: float
    low_price: float
    close_price: float
    volume_value: float | None


@dataclass(frozen=True)
class SignalRow:
    symbol: str
    timeframe: str
    candle_ts_utc: str
    candle_return_pct: float | None
    rolling_return_pct: float | None
    volume_expansion: str
    range_expansion: str
    local_high_break: str
    local_low_break: str
    distance_to_rolling_high_pct: float | None
    distance_to_rolling_low_pct: float | None
    relative_strength_vs_btc_pct: float | None
    source_table: str
    source_candle_ts_utc: str
    freshness_status: str
    replay_safe_status: str
    missing_fields: str


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only single-asset primitive signal replay for multiple timeframes. "
            "Exports transparent signal rows, summary counts, and timeframe conflict inventory."
        )
    )
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL)
    parser.add_argument("--quote", default=DEFAULT_QUOTE)
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--timeframes", default=",".join(DEFAULT_TIMEFRAMES))
    parser.add_argument("--write-files", action="store_true")
    parser.add_argument("--output", choices=("summary", "json"), default="summary")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser.parse_args(argv)


def parse_timeframes(raw: str) -> list[str]:
    items = [item.strip() for item in str(raw).split(",") if item.strip()]
    if not items:
        raise ValueError("At least one timeframe is required")
    unknown = [item for item in items if item not in TIMEFRAME_DELTAS]
    if unknown:
        raise ValueError(f"Unsupported timeframes: {', '.join(unknown)}")
    return items


def parse_start_date(raw: str) -> datetime:
    return datetime.fromisoformat(str(raw).strip()).replace(tzinfo=UTC)


def fmt_ts(value: datetime | None) -> str:
    if value is None:
        return "unavailable"
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def to_naive_utc(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None)


def as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def average_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 6)


def median_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return round(float(median(values)), 6)


def bool_text(value: bool | None) -> str:
    if value is None:
        return "unavailable"
    return "yes" if value else "no"


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


def fetch_asset_ids(conn: Any, symbols: list[str]) -> dict[str, int]:
    if not symbols:
        return {}
    placeholders = ", ".join(["%s"] * len(symbols))
    sql = f"SELECT symbol, asset_id FROM asset WHERE symbol IN ({placeholders})"
    with conn.cursor() as cur:
        cur.execute(sql, symbols)
        rows = cur.fetchall()
    return {str(row["symbol"]).upper(): int(row["asset_id"]) for row in rows}


def detect_volume_column(columns: set[str]) -> str | None:
    for candidate in ("volume_quote_eur", "quote_volume", "volume", "base_volume"):
        if candidate in columns:
            return candidate
    return None


def fetch_candles(
    conn: Any,
    *,
    asset_id: int,
    venue: str,
    timeframe: str,
    start_ts: datetime,
    volume_column: str | None,
) -> list[Candle]:
    selected_cols = ["close_ts_utc", "open_price", "high_price", "low_price", "close_price"]
    if volume_column:
        selected_cols.append(volume_column)
    sql = f"""
        SELECT {", ".join(selected_cols)}
        FROM obs_market_candle
        WHERE venue = %s
          AND interval_code = %s
          AND asset_id = %s
          AND close_ts_utc >= %s
        ORDER BY close_ts_utc
    """
    with conn.cursor() as cur:
        cur.execute(sql, [venue, timeframe, asset_id, to_naive_utc(start_ts)])
        rows = cur.fetchall()
    output: list[Candle] = []
    for row in rows:
        ts = row["close_ts_utc"]
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        else:
            ts = ts.astimezone(UTC)
        high_price = as_float(row.get("high_price"))
        low_price = as_float(row.get("low_price"))
        close_price = as_float(row.get("close_price"))
        if high_price is None or low_price is None or close_price is None:
            continue
        output.append(
            Candle(
                close_ts_utc=ts,
                open_price=as_float(row.get("open_price")),
                high_price=high_price,
                low_price=low_price,
                close_price=close_price,
                volume_value=as_float(row.get(volume_column)) if volume_column else None,
            )
        )
    return output


def pct_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return round((current / previous - 1.0) * 100.0, 6)


def latest_candle_before_or_at(candles: list[Candle], ts: datetime) -> Candle | None:
    candidate: Candle | None = None
    for candle in candles:
        if candle.close_ts_utc <= ts:
            candidate = candle
        else:
            break
    return candidate


def rolling_median(values: list[float]) -> float | None:
    if not values:
        return None
    return float(median(values))


def derive_signal_rows(
    *,
    symbol: str,
    timeframe: str,
    candles: list[Candle],
    btc_candles: list[Candle],
) -> list[SignalRow]:
    rows: list[SignalRow] = []
    for idx, candle in enumerate(candles):
        prev = candles[idx - 1] if idx > 0 else None
        candle_return_pct = pct_change(candle.close_price, None if prev is None else prev.close_price)
        rolling_anchor = candles[idx - ROLLING_RETURN_LOOKBACK] if idx >= ROLLING_RETURN_LOOKBACK else None
        rolling_return_pct = pct_change(candle.close_price, None if rolling_anchor is None else rolling_anchor.close_price)

        prior_range_values = [
            ((c.high_price / c.low_price) - 1.0) * 100.0
            for c in candles[max(0, idx - RANGE_LOOKBACK):idx]
            if c.low_price > 0
        ]
        current_range_pct = ((candle.high_price / candle.low_price) - 1.0) * 100.0 if candle.low_price > 0 else None
        median_range_pct = rolling_median(prior_range_values)
        range_expansion = (
            current_range_pct is not None
            and median_range_pct is not None
            and current_range_pct >= median_range_pct * RANGE_EXPANSION_MULTIPLIER
        )

        prior_highs = [c.high_price for c in candles[max(0, idx - ROLLING_LEVEL_LOOKBACK):idx]]
        prior_lows = [c.low_price for c in candles[max(0, idx - ROLLING_LEVEL_LOOKBACK):idx]]
        rolling_high = max(prior_highs) if prior_highs else None
        rolling_low = min(prior_lows) if prior_lows else None
        local_high_break = rolling_high is not None and candle.close_price > rolling_high
        local_low_break = rolling_low is not None and candle.close_price < rolling_low

        distance_to_rolling_high_pct = None
        if rolling_high is not None and candle.close_price > 0:
            distance_to_rolling_high_pct = round((rolling_high / candle.close_price - 1.0) * 100.0, 6)
        distance_to_rolling_low_pct = None
        if rolling_low is not None and rolling_low > 0:
            distance_to_rolling_low_pct = round((candle.close_price / rolling_low - 1.0) * 100.0, 6)

        prior_volume_values = [
            c.volume_value for c in candles[max(0, idx - RANGE_LOOKBACK):idx] if c.volume_value is not None
        ]
        median_volume = rolling_median([value for value in prior_volume_values if value is not None])
        volume_expansion = (
            candle.volume_value is not None
            and median_volume is not None
            and candle.volume_value >= median_volume * VOLUME_EXPANSION_MULTIPLIER
        )

        btc_reference = latest_candle_before_or_at(btc_candles, candle.close_ts_utc)
        relative_strength_vs_btc_pct = None
        if btc_reference is not None:
            btc_index = next((i for i, c in enumerate(btc_candles) if c.close_ts_utc == btc_reference.close_ts_utc), None)
            if btc_index is not None and btc_index >= ROLLING_RETURN_LOOKBACK:
                btc_anchor = btc_candles[btc_index - ROLLING_RETURN_LOOKBACK]
                btc_rolling_return_pct = pct_change(btc_reference.close_price, btc_anchor.close_price)
                if rolling_return_pct is not None and btc_rolling_return_pct is not None:
                    relative_strength_vs_btc_pct = round(rolling_return_pct - btc_rolling_return_pct, 6)

        missing_fields: list[str] = []
        if candle.volume_value is None:
            missing_fields.append("MISSING_VOLUME")
        if relative_strength_vs_btc_pct is None:
            missing_fields.append("MISSING_RELATIVE_STRENGTH_BTC")

        rows.append(
            SignalRow(
                symbol=symbol,
                timeframe=timeframe,
                candle_ts_utc=fmt_ts(candle.close_ts_utc),
                candle_return_pct=candle_return_pct,
                rolling_return_pct=rolling_return_pct,
                volume_expansion=bool_text(volume_expansion if median_volume is not None else None),
                range_expansion=bool_text(range_expansion if median_range_pct is not None else None),
                local_high_break=bool_text(local_high_break if rolling_high is not None else None),
                local_low_break=bool_text(local_low_break if rolling_low is not None else None),
                distance_to_rolling_high_pct=distance_to_rolling_high_pct,
                distance_to_rolling_low_pct=distance_to_rolling_low_pct,
                relative_strength_vs_btc_pct=relative_strength_vs_btc_pct,
                source_table="obs_market_candle",
                source_candle_ts_utc=fmt_ts(candle.close_ts_utc),
                freshness_status="historical_replay",
                replay_safe_status="REPLAY_SAFE_READY",
                missing_fields=",".join(missing_fields) if missing_fields else "none",
            )
        )
    return rows


def build_summary_rows(signal_rows: list[SignalRow]) -> list[dict[str, Any]]:
    grouped: dict[str, list[SignalRow]] = {}
    for row in signal_rows:
        grouped.setdefault(row.timeframe, []).append(row)

    output: list[dict[str, Any]] = []
    for timeframe, rows in sorted(grouped.items(), key=lambda item: list(TIMEFRAME_DELTAS).index(item[0])):
        def count_value(field: str, expected: str) -> int:
            return sum(1 for row in rows if str(getattr(row, field)) == expected)

        output.append(
            {
                "timeframe": timeframe,
                "rows": len(rows),
                "first_ts_utc": rows[0].candle_ts_utc if rows else "unavailable",
                "last_ts_utc": rows[-1].candle_ts_utc if rows else "unavailable",
                "candle_return_available_count": sum(1 for row in rows if row.candle_return_pct is not None),
                "rolling_return_available_count": sum(1 for row in rows if row.rolling_return_pct is not None),
                "volume_expansion_yes_count": count_value("volume_expansion", "yes"),
                "volume_available_count": sum(1 for row in rows if row.volume_expansion != "unavailable"),
                "range_expansion_yes_count": count_value("range_expansion", "yes"),
                "local_high_break_yes_count": count_value("local_high_break", "yes"),
                "local_low_break_yes_count": count_value("local_low_break", "yes"),
                "relative_strength_vs_btc_available_count": sum(1 for row in rows if row.relative_strength_vs_btc_pct is not None),
            }
        )
    return output


def direction_state(row: SignalRow) -> str:
    if row.rolling_return_pct is not None:
        if row.rolling_return_pct > 0 or row.local_high_break == "yes":
            return "bullish"
        if row.rolling_return_pct < 0 or row.local_low_break == "yes":
            return "bearish"
        return "neutral"
    return "unavailable"


def build_conflict_inventory(signal_rows: list[SignalRow], *, base_timeframe: str) -> list[dict[str, Any]]:
    rows_by_tf: dict[str, list[SignalRow]] = {}
    for row in signal_rows:
        rows_by_tf.setdefault(row.timeframe, []).append(row)
    anchors = rows_by_tf.get(base_timeframe, [])
    if not anchors:
        return []

    indices = {tf: 0 for tf in rows_by_tf}
    output: list[dict[str, Any]] = []
    for anchor in anchors:
        anchor_ts = datetime.fromisoformat(anchor.candle_ts_utc.replace("Z", "+00:00"))
        direction_map: dict[str, str] = {}
        participating: list[str] = []

        for timeframe, tf_rows in rows_by_tf.items():
            while indices[timeframe] + 1 < len(tf_rows):
                next_ts = datetime.fromisoformat(tf_rows[indices[timeframe] + 1].candle_ts_utc.replace("Z", "+00:00"))
                if next_ts <= anchor_ts:
                    indices[timeframe] += 1
                else:
                    break
            row = tf_rows[indices[timeframe]]
            row_ts = datetime.fromisoformat(row.candle_ts_utc.replace("Z", "+00:00"))
            if anchor_ts - row_ts > TIMEFRAME_DELTAS[timeframe] * MAX_TIMEFRAME_STALENESS_MULTIPLIER:
                continue
            participating.append(timeframe)
            direction_map[timeframe] = direction_state(row)

        bullish = [tf for tf, state in direction_map.items() if state == "bullish"]
        bearish = [tf for tf, state in direction_map.items() if state == "bearish"]
        conflict_types: list[str] = []
        if bullish and bearish:
            conflict_types.append("DIRECTION_CONFLICT")
        if not conflict_types:
            continue
        output.append(
            {
                "symbol": anchor.symbol,
                "anchor_timeframe": base_timeframe,
                "anchor_ts_utc": anchor.candle_ts_utc,
                "participating_timeframes": ",".join(participating),
                "bullish_timeframes": ",".join(bullish) if bullish else "none",
                "bearish_timeframes": ",".join(bearish) if bearish else "none",
                "conflict_types": ",".join(conflict_types),
                "notes": "Elke timeframe mag zijn eigen waarheid hebben; conflict is shown, not resolved.",
            }
        )
    return output


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=True))
            handle.write("\n")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def print_summary(
    *,
    symbol: str,
    venue: str,
    quote: str,
    start_date: str,
    timeframes: list[str],
    signal_rows: list[SignalRow],
    summary_rows: list[dict[str, Any]],
    conflict_rows: list[dict[str, Any]],
    output_dir: Path,
    db_error: str | None,
) -> None:
    print(f"report={REPORT_NAME} version={REPORT_VERSION}")
    print("scope=research-only market-only account-agnostic primitive-signal replay")
    print("broker_private_calls=0 broker_writes=0 order_submission=0 db_writes=0 executor=none account_awareness=0")
    print(f"symbol={symbol} venue={venue} quote={quote} start_date={start_date}")
    print(f"timeframes={','.join(timeframes)}")
    if db_error:
        print(f"db_error={db_error}")
    print(f"signal_rows={len(signal_rows)}")
    print(f"conflict_rows={len(conflict_rows)}")
    print(f"output_dir={output_dir}")
    print()
    print("--- summary by timeframe ---")
    for row in summary_rows:
        print(
            " ".join(
                [
                    f"timeframe={row['timeframe']}",
                    f"rows={row['rows']}",
                    f"volume_expansion_yes={row['volume_expansion_yes_count']}",
                    f"range_expansion_yes={row['range_expansion_yes_count']}",
                    f"local_high_break_yes={row['local_high_break_yes_count']}",
                    f"local_low_break_yes={row['local_low_break_yes_count']}",
                    f"rs_btc_available={row['relative_strength_vs_btc_available_count']}",
                ]
            )
        )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    symbol = str(args.symbol).upper()
    venue = str(args.venue)
    quote = str(args.quote).upper()
    start_dt = parse_start_date(str(args.start_date))
    timeframes = parse_timeframes(str(args.timeframes))
    output_dir = Path(args.output_dir)

    db_error: str | None = None
    signal_rows: list[SignalRow] = []
    summary_rows: list[dict[str, Any]] = []
    conflict_rows: list[dict[str, Any]] = []

    try:
        conn = get_connection()
    except Exception as exc:
        db_error = f"{type(exc).__name__}: {exc}"
    else:
        try:
            columns = table_columns(conn, "obs_market_candle")
            volume_column = detect_volume_column(columns)
            asset_ids = fetch_asset_ids(conn, [symbol, BTC_SYMBOL])
            if symbol not in asset_ids:
                raise ValueError(f"Asset symbol not found: {symbol}")
            if BTC_SYMBOL not in asset_ids:
                raise ValueError("BTC asset_id is required for relative strength vs BTC")

            all_rows: list[SignalRow] = []
            for timeframe in timeframes:
                asset_candles = fetch_candles(
                    conn,
                    asset_id=asset_ids[symbol],
                    venue=venue,
                    timeframe=timeframe,
                    start_ts=start_dt,
                    volume_column=volume_column,
                )
                btc_candles = fetch_candles(
                    conn,
                    asset_id=asset_ids[BTC_SYMBOL],
                    venue=venue,
                    timeframe=timeframe,
                    start_ts=start_dt,
                    volume_column=volume_column,
                )
                all_rows.extend(
                    derive_signal_rows(
                        symbol=symbol,
                        timeframe=timeframe,
                        candles=asset_candles,
                        btc_candles=btc_candles,
                    )
                )
            signal_rows = all_rows
            summary_rows = build_summary_rows(signal_rows)
            base_timeframe = min(timeframes, key=lambda item: TIMEFRAME_DELTAS[item])
            conflict_rows = build_conflict_inventory(signal_rows, base_timeframe=base_timeframe)
        except Exception as exc:
            db_error = f"{type(exc).__name__}: {exc}"
        finally:
            conn.close()

    period_label = f"{symbol}_{start_dt.year}YTD"
    events_csv = output_dir / f"{period_label}_signal_events.csv"
    events_jsonl = output_dir / f"{period_label}_signal_events.jsonl"
    summary_csv = output_dir / f"{period_label}_signal_summary.csv"
    conflict_csv = output_dir / f"{period_label}_conflict_inventory.csv"

    if args.write_files:
        write_csv(events_csv, [asdict(row) for row in signal_rows])
        write_jsonl(events_jsonl, [asdict(row) for row in signal_rows])
        write_csv(summary_csv, summary_rows)
        write_csv(conflict_csv, conflict_rows)

    if args.output == "json":
        print(
            json.dumps(
                {
                    "report": REPORT_NAME,
                    "version": REPORT_VERSION,
                    "symbol": symbol,
                    "venue": venue,
                    "quote": quote,
                    "start_date": str(args.start_date),
                    "timeframes": timeframes,
                    "safety": {
                        "broker_private_calls": 0,
                        "broker_writes": 0,
                        "order_submission": 0,
                        "db_writes": 0,
                        "executor": "none",
                        "account_awareness": 0,
                    },
                    "db_error": db_error,
                    "signal_rows": [asdict(row) for row in signal_rows],
                    "summary_rows": summary_rows,
                    "conflict_rows": conflict_rows,
                    "output_files": {
                        "signal_events_csv": str(events_csv),
                        "signal_events_jsonl": str(events_jsonl),
                        "signal_summary_csv": str(summary_csv),
                        "conflict_inventory_csv": str(conflict_csv),
                    },
                },
                indent=2,
                sort_keys=True,
                ensure_ascii=True,
            )
        )
    else:
        print_summary(
            symbol=symbol,
            venue=venue,
            quote=quote,
            start_date=str(args.start_date),
            timeframes=timeframes,
            signal_rows=signal_rows,
            summary_rows=summary_rows,
            conflict_rows=conflict_rows,
            output_dir=output_dir,
            db_error=db_error,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
