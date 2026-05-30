from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from src.common.db import get_connection
from src.research.run_aplus_prime17_opportunity_report_v1 import (
    fetch_asset_ids,
    fetch_optional_context,
    parse_focus_table1,
    parse_focus_table2,
)
from src.research.run_aplus_vs_synth_comparison_report_v1 import (
    ComparisonRow,
    build_rows,
    fetch_additional_context,
    tokens_in_both,
)


REPORT_NAME = "aplus_vs_synth_comparison_outcome_validation_v1"
REPORT_VERSION = "1.0"
DEFAULT_VENUE = "bitvavo"
DEFAULT_QUOTE = "EUR"
DEFAULT_INTERVAL = "1d"
DEFAULT_CANDLE_INTERVAL = "15m"
LOCAL_TZ = ZoneInfo("Europe/Amsterdam")
HORIZON_HOURS: tuple[tuple[str, int], ...] = (
    ("15m", 0),
    ("1h", 1),
    ("4h", 4),
    ("24h", 24),
    ("72h", 72),
    ("168h", 168),
)
HORIZON_DELTAS = {
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "24h": timedelta(hours=24),
    "72h": timedelta(hours=72),
    "168h": timedelta(hours=168),
}
MAX_HORIZON = max(HORIZON_DELTAS.values())


@dataclass(frozen=True)
class Candle:
    close_ts_utc: datetime
    close_price: float
    high_price: float
    low_price: float


@dataclass(frozen=True)
class OutcomeRow:
    token: str
    snapshot_ts_utc: str
    comparison_bucket: str
    synth_bucket: str
    aplus_bucket: str
    reference_price: float | None
    reference_price_source: str
    base_candle_ts_utc: str | None
    avg_mfe: float | None
    avg_mae: float | None
    return_15m: float | None
    return_1h: float | None
    return_4h: float | None
    return_24h: float | None
    return_72h: float | None
    return_168h: float | None
    complete_15m: bool
    complete_1h: bool
    complete_4h: bool
    complete_24h: bool
    complete_72h: bool
    complete_168h: bool


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only forward outcome validation for A+ vs Synth comparison buckets "
            "using Prime-17 raw snapshots plus public market candles."
        )
    )
    parser.add_argument("--table1-raw", required=True)
    parser.add_argument("--table2-raw", required=True)
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--quote", default=DEFAULT_QUOTE)
    parser.add_argument("--interval", default=DEFAULT_INTERVAL)
    parser.add_argument("--candle-interval", default=DEFAULT_CANDLE_INTERVAL)
    parser.add_argument("--reload-selected-events", default="data/research/reload_reaction_scalp_parameter_sweep_v1/reload_reaction_scalp_selected_events_v1.jsonl")
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args(argv)


def parse_snapshot_ts_from_path(path: Path) -> datetime:
    match = re.search(r"(\d{4}-\d{2}-\d{2})_(\d{2})(\d{2})", path.name)
    if not match:
        raise ValueError(f"Could not infer snapshot timestamp from filename: {path}")
    local_dt = datetime.strptime(
        f"{match.group(1)} {match.group(2)}:{match.group(3)}",
        "%Y-%m-%d %H:%M",
    ).replace(tzinfo=LOCAL_TZ)
    return local_dt.astimezone(UTC)


def fmt_ts(value: datetime | None) -> str | None:
    if value is None:
        return None
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


def winrate_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(1 for value in values if value > 0) / len(values) * 100.0, 6)


def return_pct(reference_price: float | None, future_price: float | None) -> float | None:
    if reference_price is None or future_price is None or reference_price <= 0:
        return None
    return round((future_price / reference_price - 1.0) * 100.0, 6)


def fetch_candles(
    conn: Any,
    *,
    asset_ids: dict[str, int],
    venue: str,
    interval_code: str,
    start_ts: datetime,
    end_ts: datetime,
) -> dict[str, list[Candle]]:
    if not asset_ids:
        return {}
    placeholders = ", ".join(["%s"] * len(asset_ids))
    sql = f"""
        SELECT asset_id, close_ts_utc, close_price, high_price, low_price
        FROM obs_market_candle
        WHERE venue = %s
          AND interval_code = %s
          AND close_ts_utc >= %s
          AND close_ts_utc <= %s
          AND asset_id IN ({placeholders})
        ORDER BY asset_id, close_ts_utc
    """
    params: list[Any] = [venue, interval_code, to_naive_utc(start_ts), to_naive_utc(end_ts), *asset_ids.values()]
    reverse_asset = {asset_id: symbol for symbol, asset_id in asset_ids.items()}
    grouped: dict[str, list[Candle]] = {symbol: [] for symbol in asset_ids}
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    for row in rows:
        symbol = reverse_asset.get(int(row["asset_id"]))
        if symbol is None:
            continue
        close_ts = row["close_ts_utc"]
        if close_ts.tzinfo is None:
            close_ts = close_ts.replace(tzinfo=UTC)
        else:
            close_ts = close_ts.astimezone(UTC)
        close_price = as_float(row["close_price"])
        high_price = as_float(row["high_price"])
        low_price = as_float(row["low_price"])
        if close_price is None or high_price is None or low_price is None:
            continue
        grouped[symbol].append(
            Candle(
                close_ts_utc=close_ts,
                close_price=close_price,
                high_price=high_price,
                low_price=low_price,
            )
        )
    return grouped


def latest_candle_before_or_at(candles: list[Candle], ts: datetime) -> Candle | None:
    candidate: Candle | None = None
    for candle in candles:
        if candle.close_ts_utc <= ts:
            candidate = candle
            continue
        break
    return candidate


def first_candle_at_or_after(candles: list[Candle], ts: datetime) -> Candle | None:
    for candle in candles:
        if candle.close_ts_utc >= ts:
            return candle
    return None


def candles_in_window(candles: list[Candle], start_ts: datetime, end_ts: datetime) -> list[Candle]:
    return [candle for candle in candles if start_ts < candle.close_ts_utc <= end_ts]


def build_outcome_rows(
    comparison_rows: list[ComparisonRow],
    *,
    snapshot_ts_utc: datetime,
    candles_by_symbol: dict[str, list[Candle]],
) -> list[OutcomeRow]:
    output: list[OutcomeRow] = []
    for row in comparison_rows:
        candles = candles_by_symbol.get(row.token, [])
        base_candle = latest_candle_before_or_at(candles, snapshot_ts_utc)
        reference_price = None if base_candle is None else base_candle.close_price
        window_candles = candles_in_window(candles, snapshot_ts_utc, snapshot_ts_utc + MAX_HORIZON)
        mfe = None
        mae = None
        if reference_price is not None and reference_price > 0 and window_candles:
            mfe = round((max(c.high_price for c in window_candles) / reference_price - 1.0) * 100.0, 6)
            mae = round((min(c.low_price for c in window_candles) / reference_price - 1.0) * 100.0, 6)

        horizon_returns: dict[str, float | None] = {}
        horizon_complete: dict[str, bool] = {}
        for label, delta in HORIZON_DELTAS.items():
            future_candle = first_candle_at_or_after(candles, snapshot_ts_utc + delta)
            future_price = None if future_candle is None else future_candle.close_price
            horizon_returns[label] = return_pct(reference_price, future_price)
            horizon_complete[label] = future_candle is not None

        output.append(
            OutcomeRow(
                token=row.token,
                snapshot_ts_utc=fmt_ts(snapshot_ts_utc) or "",
                comparison_bucket=row.comparison_bucket,
                synth_bucket=row.synth_bucket,
                aplus_bucket=row.aplus_bucket,
                reference_price=reference_price,
                reference_price_source="latest_candle_before_or_at_snapshot" if reference_price is not None else "missing",
                base_candle_ts_utc=fmt_ts(None if base_candle is None else base_candle.close_ts_utc),
                avg_mfe=mfe,
                avg_mae=mae,
                return_15m=horizon_returns["15m"],
                return_1h=horizon_returns["1h"],
                return_4h=horizon_returns["4h"],
                return_24h=horizon_returns["24h"],
                return_72h=horizon_returns["72h"],
                return_168h=horizon_returns["168h"],
                complete_15m=horizon_complete["15m"],
                complete_1h=horizon_complete["1h"],
                complete_4h=horizon_complete["4h"],
                complete_24h=horizon_complete["24h"],
                complete_72h=horizon_complete["72h"],
                complete_168h=horizon_complete["168h"],
            )
        )
    return output


def build_bucket_summary(rows: list[OutcomeRow]) -> list[dict[str, Any]]:
    grouped: dict[str, list[OutcomeRow]] = defaultdict(list)
    for row in rows:
        grouped[row.comparison_bucket].append(row)

    summary_rows: list[dict[str, Any]] = []
    for bucket in sorted(grouped):
        bucket_rows = grouped[bucket]
        summary: dict[str, Any] = {"comparison_bucket": bucket, "count": len(bucket_rows)}
        for label, _hours in HORIZON_HOURS:
            values = [
                float(getattr(row, f"return_{label}"))
                for row in bucket_rows
                if getattr(row, f"return_{label}") is not None
            ]
            summary[f"complete_{label}"] = sum(1 for row in bucket_rows if bool(getattr(row, f"complete_{label}")))
            summary[f"avg_return_{label}"] = average_or_none(values)
            summary[f"median_return_{label}"] = median_or_none(values)
            summary[f"winrate_{label}"] = winrate_or_none(values)
        mfes = [float(row.avg_mfe) for row in bucket_rows if row.avg_mfe is not None]
        maes = [float(row.avg_mae) for row in bucket_rows if row.avg_mae is not None]
        summary["avg_mfe"] = average_or_none(mfes)
        summary["avg_mae"] = average_or_none(maes)
        summary_rows.append(summary)
    return summary_rows


def print_table(
    *,
    snapshot_ts_utc: datetime,
    comparison_rows: list[ComparisonRow],
    bucket_summary: list[dict[str, Any]],
    meta: dict[str, Any],
) -> None:
    print(f"report={REPORT_NAME} version={REPORT_VERSION}")
    print("scope=research-only read-only aplus-vs-synth comparison outcome validation")
    print("broker_calls=0 broker_writes=0 order_submission=0 executor=none live_trading=false")
    print(f"snapshot_ts_utc={fmt_ts(snapshot_ts_utc)}")
    print(f"token_rows={len(comparison_rows)}")
    print(f"venue={meta['venue']} quote={meta['quote']} interval={meta['interval']} candle_interval={meta['candle_interval']}")
    if meta.get("db_error"):
        print(f"db_error={meta['db_error']}")
    print()
    cols = [
        "comparison_bucket",
        "count",
        "avg_return_15m",
        "avg_return_1h",
        "avg_return_4h",
        "avg_return_24h",
        "avg_return_72h",
        "avg_return_168h",
        "winrate_15m",
        "winrate_1h",
        "winrate_4h",
        "winrate_24h",
        "winrate_72h",
        "winrate_168h",
        "avg_mfe",
        "avg_mae",
    ]
    print("\t".join(cols))
    for row in bucket_summary:
        print("\t".join(str(row.get(col)) for col in cols))


def print_json(
    *,
    snapshot_ts_utc: datetime,
    comparison_rows: list[ComparisonRow],
    outcome_rows: list[OutcomeRow],
    bucket_summary: list[dict[str, Any]],
    meta: dict[str, Any],
) -> None:
    payload = {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "snapshot_ts_utc": fmt_ts(snapshot_ts_utc),
        "row_count": len(comparison_rows),
        "safety": {
            "db_writes": 0,
            "broker_calls": 0,
            "broker_writes": 0,
            "order_submission": 0,
            "selection_engine_changes": 0,
            "decision_gate_changes": 0,
            "execution_planner_changes": 0,
            "executor_changes": 0,
        },
        "meta": meta,
        "bucket_summary": bucket_summary,
        "comparison_rows": [asdict(row) for row in comparison_rows],
        "outcome_rows": [asdict(row) for row in outcome_rows],
    }
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    table1_path = Path(args.table1_raw)
    table2_path = Path(args.table2_raw)
    table1 = parse_focus_table1(table1_path.read_text(encoding="utf-8"))
    table2 = parse_focus_table2(table2_path.read_text(encoding="utf-8"))
    tokens = tokens_in_both(table1, table2)
    snapshot_ts_utc = min(parse_snapshot_ts_from_path(table1_path), parse_snapshot_ts_from_path(table2_path))

    selection_map, zone_map, volume_map, base_meta = fetch_optional_context(
        tokens=tokens,
        venue=args.venue,
        interval=args.interval,
    )
    setup_map, paper_advice_map, reload_selected_map, extra_meta = fetch_additional_context(
        tokens=tokens,
        venue=args.venue,
        interval=args.interval,
        reload_selected_events=Path(args.reload_selected_events),
    )
    comparison_rows = build_rows(
        tokens=tokens,
        table1=table1,
        table2=table2,
        selection_map=selection_map,
        setup_map=setup_map,
        zone_map=zone_map,
        volume_map=volume_map,
        paper_advice_map=paper_advice_map,
        reload_selected_map=reload_selected_map,
    )

    db_error: str | None = None
    candles_by_symbol: dict[str, list[Candle]] = {}
    try:
        conn = get_connection()
    except Exception as exc:
        db_error = f"{type(exc).__name__}: {exc}"
    else:
        try:
            asset_ids = fetch_asset_ids(conn, tokens)
            candles_by_symbol = fetch_candles(
                conn,
                asset_ids=asset_ids,
                venue=args.venue,
                interval_code=args.candle_interval,
                start_ts=snapshot_ts_utc - timedelta(days=1),
                end_ts=snapshot_ts_utc + MAX_HORIZON + timedelta(hours=1),
            )
        except Exception as exc:
            db_error = f"{type(exc).__name__}: {exc}"
            candles_by_symbol = {}
        finally:
            conn.close()

    outcome_rows = build_outcome_rows(
        comparison_rows,
        snapshot_ts_utc=snapshot_ts_utc,
        candles_by_symbol=candles_by_symbol,
    )
    bucket_summary = build_bucket_summary(outcome_rows)
    meta = {
        "tokens_used": tokens,
        "venue": args.venue,
        "quote": args.quote,
        "interval": args.interval,
        "candle_interval": args.candle_interval,
        "reload_selected_events": str(args.reload_selected_events),
        "missing_candles_handled_gracefully": True,
        **base_meta,
        **extra_meta,
    }
    if db_error is not None:
        meta["db_error"] = db_error

    if args.output == "json":
        print_json(
            snapshot_ts_utc=snapshot_ts_utc,
            comparison_rows=comparison_rows,
            outcome_rows=outcome_rows,
            bucket_summary=bucket_summary,
            meta=meta,
        )
    else:
        print_table(
            snapshot_ts_utc=snapshot_ts_utc,
            comparison_rows=comparison_rows,
            bucket_summary=bucket_summary,
            meta=meta,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
