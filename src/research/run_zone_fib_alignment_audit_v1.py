from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Any

from src.common.db import get_connection


REPORT_NAME = "zone_fib_alignment_audit_v1"
VERSION = "1.0"
DEFAULT_OUTPUT_ROOT = "data/research/zone_fib_alignment_audit_v1"
DEFAULT_RUN_DIR_PREFIX = "run_"

EVENTS_CSV = "zone_fib_alignment_events_v1.csv"
SUMMARY_BY_ENTRY_ALIGNMENT_CSV = "summary_by_entry_alignment_v1.csv"
SUMMARY_BY_TP_ALIGNMENT_CSV = "summary_by_tp_alignment_v1.csv"
SUMMARY_BY_SYMBOL_CSV = "summary_by_symbol_v1.csv"
SUMMARY_BY_ZONE_TYPE_CSV = "summary_by_zone_type_v1.csv"
MANIFEST_JSON = "manifest_v1.json"

INTERVAL_SECONDS = {
    "1h": 60 * 60,
    "4h": 4 * 60 * 60,
    "1d": 24 * 60 * 60,
}

SAFETY_MARKERS = {
    "db_writes": 0,
    "broker_calls": 0,
    "broker_writes": 0,
    "order_submission": 0,
    "live_orders": 0,
}

EVENT_FIELDS = [
    "symbol",
    "asof_ts_utc",
    "leg_direction",
    "entry_zone_type",
    "entry_zone_low",
    "entry_zone_high",
    "tp_zone_type",
    "tp_zone_low",
    "tp_zone_high",
    "fib_0500_price",
    "fib_0618_price",
    "fib_0786_price",
    "ext_1272_price",
    "ext_1618_price",
    "nearest_entry_fib_level",
    "entry_fib_distance_pct",
    "nearest_tp_fib_level",
    "tp_fib_distance_pct",
    "entry_alignment_label",
    "tp_alignment_label",
    "entry_is_fib_band",
    "tp_is_fib_extension_band",
    "distance_to_tp_pct",
    "forward_return_24h_pct",
    "forward_return_48h_pct",
    "hit_tp_24h",
    "hit_tp_48h",
]

SUMMARY_FIELDS = [
    "label",
    "event_count",
    "avg_entry_fib_distance_pct",
    "avg_tp_fib_distance_pct",
    "avg_distance_to_tp_pct",
    "avg_forward_return_24h_pct",
    "median_forward_return_24h_pct",
    "avg_forward_return_48h_pct",
    "hit_tp_24h_rate_pct",
    "hit_tp_48h_rate_pct",
]


@dataclass(frozen=True)
class OutputPaths:
    events_csv: Path
    summary_by_entry_alignment_csv: Path
    summary_by_tp_alignment_csv: Path
    summary_by_symbol_csv: Path
    summary_by_zone_type_csv: Path
    manifest_json: Path


@dataclass(frozen=True)
class FutureCandle:
    close_ts_utc: datetime
    close_price: Decimal
    high_price: Decimal
    low_price: Decimal


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit whether execution entry and TP zones are fib-aligned or SR-only/fallback "
            "(research-only, read-only DB)."
        )
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--start-ts", required=True)
    parser.add_argument("--end-ts", required=True)
    parser.add_argument("--max-rows", type=int, default=0)
    parser.add_argument("--write-files", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--output-root", default=None)
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args(argv)


def parse_ts(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC).replace(tzinfo=None)
    return parsed.astimezone(UTC).replace(tzinfo=None)


def fmt_ts(value: datetime) -> str:
    return value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


def utc_run_id(now_utc: datetime) -> str:
    return now_utc.replace(tzinfo=UTC).strftime("%Y%m%dT%H%M%SZ")


def resolve_output_dir(*, output_root: str | None, run_id: str) -> Path:
    root = Path(output_root) if output_root else Path(DEFAULT_OUTPUT_ROOT)
    return root / f"{DEFAULT_RUN_DIR_PREFIX}{run_id}"


def output_paths(output_dir: Path) -> OutputPaths:
    return OutputPaths(
        events_csv=output_dir / EVENTS_CSV,
        summary_by_entry_alignment_csv=output_dir / SUMMARY_BY_ENTRY_ALIGNMENT_CSV,
        summary_by_tp_alignment_csv=output_dir / SUMMARY_BY_TP_ALIGNMENT_CSV,
        summary_by_symbol_csv=output_dir / SUMMARY_BY_SYMBOL_CSV,
        summary_by_zone_type_csv=output_dir / SUMMARY_BY_ZONE_TYPE_CSV,
        manifest_json=output_dir / MANIFEST_JSON,
    )


def format_number(value: Decimal | float | None, places: str = "0.000001") -> str:
    if value is None:
        return ""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    try:
        return str(value.quantize(Decimal(places)))
    except Exception:
        return str(value)


def dec(value: Any) -> Decimal | None:
    if value in ("", None):
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def as_float(value: Any) -> float | None:
    if value in ("", None):
        return None
    try:
        return float(value)
    except Exception:
        return None


def table_exists(conn: Any, table_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SHOW TABLES LIKE %s", (table_name,))
        return cur.fetchone() is not None


def fib_table_name(conn: Any) -> str:
    for name in ("fib_observation_v2", "fib_observation"):
        if table_exists(conn, name):
            return name
    raise RuntimeError("No fib observation table found")


def zone_table_name(conn: Any) -> str:
    for name in ("zone_observation_v2", "zone_observation"):
        if table_exists(conn, name):
            return name
    raise RuntimeError("No zone observation table found")


def pct_distance(reference_price: Decimal | None, target_price: Decimal | None) -> Decimal | None:
    if reference_price is None or target_price is None or reference_price <= 0:
        return None
    return abs(target_price - reference_price) / reference_price * Decimal("100")


def pct_return(current_price: Decimal | None, future_price: Decimal | None, leg_direction: str) -> Decimal | None:
    if current_price is None or future_price is None or current_price <= 0:
        return None
    raw = ((future_price / current_price) - Decimal("1")) * Decimal("100")
    if leg_direction == "DOWN":
        raw = -raw
    return raw


def midpoint(low: Decimal | None, high: Decimal | None) -> Decimal | None:
    if low is not None and high is not None:
        return (low + high) / Decimal("2")
    if low is not None:
        return low
    return high


def band_overlap(low_a: Decimal | None, high_a: Decimal | None, low_b: Decimal | None, high_b: Decimal | None) -> bool:
    if None in {low_a, high_a, low_b, high_b}:
        return False
    return max(low_a, low_b) <= min(high_a, high_b)


def nearest_level_name_and_distance(zone_mid: Decimal | None, levels: dict[str, Decimal | None]) -> tuple[str, Decimal | None]:
    if zone_mid is None:
        return "", None
    candidates = [
        (name, pct_distance(level_price, zone_mid))
        for name, level_price in levels.items()
        if level_price is not None
    ]
    if not candidates:
        return "", None
    best_name, best_distance = min(candidates, key=lambda item: (item[1] if item[1] is not None else Decimal("999999"), item[0]))
    return best_name, best_distance


def entry_alignment_label(
    entry_type: str,
    zone_low: Decimal | None,
    zone_high: Decimal | None,
    fib_0500: Decimal | None,
    fib_0618: Decimal | None,
    fib_0786: Decimal | None,
    nearest_distance: Decimal | None,
) -> tuple[str, bool]:
    primary_low = min(fib_0500, fib_0618) if fib_0500 is not None and fib_0618 is not None else None
    primary_high = max(fib_0500, fib_0618) if fib_0500 is not None and fib_0618 is not None else None
    deep_low = min(fib_0618, fib_0786) if fib_0618 is not None and fib_0786 is not None else None
    deep_high = max(fib_0618, fib_0786) if fib_0618 is not None and fib_0786 is not None else None

    if entry_type == "FIB_RETRACEMENT" or band_overlap(zone_low, zone_high, primary_low, primary_high):
        return "FIB_PRIMARY_BAND", True
    if entry_type == "FIB_DEEP" or band_overlap(zone_low, zone_high, deep_low, deep_high):
        return "FIB_DEEP_BAND", True
    if nearest_distance is not None and nearest_distance <= Decimal("1.0"):
        return "FIB_NEAR_LEVEL", False
    return "SR_ONLY_OR_FALLBACK", False


def tp_alignment_label(
    tp_type: str,
    zone_low: Decimal | None,
    zone_high: Decimal | None,
    ext_1272: Decimal | None,
    ext_1618: Decimal | None,
    nearest_distance: Decimal | None,
) -> tuple[str, bool]:
    ext_low = min(ext_1272, ext_1618) if ext_1272 is not None and ext_1618 is not None else None
    ext_high = max(ext_1272, ext_1618) if ext_1272 is not None and ext_1618 is not None else None
    if tp_type == "FIB_EXTENSION" or band_overlap(zone_low, zone_high, ext_low, ext_high):
        return "FIB_EXTENSION_BAND", True
    if nearest_distance is not None and nearest_distance <= Decimal("1.0"):
        return "FIB_NEAR_EXTENSION", False
    return "SR_ONLY_OR_FALLBACK", False


def fetch_base_rows(
    conn: Any,
    *,
    venue: str,
    interval_code: str,
    start_ts: datetime,
    end_ts: datetime,
    max_rows: int,
) -> list[dict[str, Any]]:
    fib_table = fib_table_name(conn)
    zone_table = zone_table_name(conn)
    limit_sql = "" if max_rows <= 0 else f"LIMIT {int(max_rows)}"
    sql = f"""
        SELECT
            a.symbol,
            e.asset_id,
            e.asof_ts_utc,
            e.expected_entry_zone_low,
            e.expected_entry_zone_high,
            e.expected_entry_zone_type,
            e.expected_take_profit_zone_low,
            e.expected_take_profit_zone_high,
            e.expected_take_profit_zone_type,
            e.notes,
            f.leg_direction,
            f.fib_0500_price,
            f.fib_0618_price,
            f.fib_0786_price,
            f.ext_1272_price,
            f.ext_1618_price,
            z_entry.zone_source_type AS entry_zone_source_type,
            z_tp.zone_source_type AS tp_zone_source_type,
            c.close_price AS asof_close_price
        FROM execution_zone_context e
        JOIN asset a
          ON a.asset_id = e.asset_id
        LEFT JOIN {fib_table} f
          ON f.asset_id = e.asset_id
         AND f.venue = e.venue
         AND f.interval_code = e.interval_code
         AND f.asof_ts_utc = e.asof_ts_utc
        LEFT JOIN {zone_table} z_entry
          ON z_entry.asset_id = e.asset_id
         AND z_entry.venue = e.venue
         AND z_entry.interval_code = e.interval_code
         AND z_entry.asof_ts_utc = e.asof_ts_utc
         AND z_entry.zone_type = e.expected_entry_zone_type
         AND (
              (z_entry.zone_low_price = e.expected_entry_zone_low AND z_entry.zone_high_price = e.expected_entry_zone_high)
              OR (z_entry.zone_low_price = e.expected_entry_zone_high AND z_entry.zone_high_price = e.expected_entry_zone_low)
         )
        LEFT JOIN {zone_table} z_tp
          ON z_tp.asset_id = e.asset_id
         AND z_tp.venue = e.venue
         AND z_tp.interval_code = e.interval_code
         AND z_tp.asof_ts_utc = e.asof_ts_utc
         AND z_tp.zone_type = e.expected_take_profit_zone_type
         AND (
              (z_tp.zone_low_price = e.expected_take_profit_zone_low AND z_tp.zone_high_price = e.expected_take_profit_zone_high)
              OR (z_tp.zone_low_price = e.expected_take_profit_zone_high AND z_tp.zone_high_price = e.expected_take_profit_zone_low)
         )
        LEFT JOIN obs_market_candle c
          ON c.asset_id = e.asset_id
         AND c.venue = e.venue
         AND c.interval_code = e.interval_code
         AND c.close_ts_utc = e.asof_ts_utc
        WHERE e.venue = %s
          AND e.interval_code = %s
          AND e.asof_ts_utc >= %s
          AND e.asof_ts_utc <= %s
        ORDER BY e.asof_ts_utc, a.symbol
        {limit_sql}
    """
    with conn.cursor() as cur:
        cur.execute(sql, (venue, interval_code, start_ts, end_ts))
        return list(cur.fetchall())


def fetch_future_candles(
    conn: Any,
    *,
    venue: str,
    interval_code: str,
    asset_id: int,
    sample_ts: datetime,
    max_horizon_hours: int = 48,
) -> list[FutureCandle]:
    sql = """
        SELECT
            close_ts_utc,
            close_price,
            high_price,
            low_price
        FROM obs_market_candle
        WHERE asset_id = %s
          AND venue = %s
          AND interval_code = %s
          AND close_ts_utc > %s
          AND close_ts_utc <= %s
        ORDER BY close_ts_utc ASC
    """
    horizon_end = sample_ts + timedelta(hours=max_horizon_hours)
    with conn.cursor() as cur:
        cur.execute(sql, (asset_id, venue, interval_code, sample_ts, horizon_end))
        rows = list(cur.fetchall())
    out: list[FutureCandle] = []
    for row in rows:
        if row.get("close_price") is None:
            continue
        out.append(
            FutureCandle(
                close_ts_utc=row["close_ts_utc"],
                close_price=Decimal(str(row["close_price"])),
                high_price=Decimal(str(row["high_price"])),
                low_price=Decimal(str(row["low_price"])),
            )
        )
    return out


def price_at_horizon(sample_ts: datetime, future_candles: list[FutureCandle], horizon_hours: int) -> Decimal | None:
    target_ts = sample_ts + timedelta(hours=horizon_hours)
    match = next((row for row in future_candles if row.close_ts_utc >= target_ts), None)
    return None if match is None else match.close_price


def hit_tp(
    *,
    leg_direction: str,
    tp_zone_low: Decimal | None,
    tp_zone_high: Decimal | None,
    future_candles: list[FutureCandle],
    horizon_hours: int,
) -> bool:
    if leg_direction not in {"UP", "DOWN"}:
        return False
    zone_low = min(tp_zone_low, tp_zone_high) if tp_zone_low is not None and tp_zone_high is not None else tp_zone_low or tp_zone_high
    zone_high = max(tp_zone_low, tp_zone_high) if tp_zone_low is not None and tp_zone_high is not None else tp_zone_low or tp_zone_high
    if zone_low is None or zone_high is None:
        return False
    cutoff = future_candles
    for candle in cutoff:
        if candle.close_ts_utc > future_candles[0].close_ts_utc + timedelta(hours=horizon_hours):
            break
        if leg_direction == "UP":
            if candle.high_price >= zone_low:
                return True
        else:
            if candle.low_price <= zone_high:
                return True
    return False


def numeric_values(rows: list[dict[str, str]], field: str) -> list[float]:
    out: list[float] = []
    for row in rows:
        value = as_float(row.get(field))
        if value is not None:
            out.append(value)
    return out


def avg(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def med(values: list[float]) -> float | None:
    if not values:
        return None
    return float(median(values))


def rate_true(rows: list[dict[str, str]], field: str) -> float | None:
    values = [str(row.get(field) or "") for row in rows]
    if not values:
        return None
    true_count = sum(1 for value in values if value == "1")
    return true_count / len(values) * 100.0


def summarize_by(rows: list[dict[str, str]], label_field: str) -> list[dict[str, str]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        label = str(row.get(label_field) or "")
        grouped[label].append(row)

    out: list[dict[str, str]] = []
    for label in sorted(grouped):
        sample = grouped[label]
        out.append(
            {
                "label": label,
                "event_count": str(len(sample)),
                "avg_entry_fib_distance_pct": format_number(avg(numeric_values(sample, "entry_fib_distance_pct"))),
                "avg_tp_fib_distance_pct": format_number(avg(numeric_values(sample, "tp_fib_distance_pct"))),
                "avg_distance_to_tp_pct": format_number(avg(numeric_values(sample, "distance_to_tp_pct"))),
                "avg_forward_return_24h_pct": format_number(avg(numeric_values(sample, "forward_return_24h_pct"))),
                "median_forward_return_24h_pct": format_number(med(numeric_values(sample, "forward_return_24h_pct"))),
                "avg_forward_return_48h_pct": format_number(avg(numeric_values(sample, "forward_return_48h_pct"))),
                "hit_tp_24h_rate_pct": format_number(rate_true(sample, "hit_tp_24h")),
                "hit_tp_48h_rate_pct": format_number(rate_true(sample, "hit_tp_48h")),
            }
        )
    return out


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


def build_manifest(
    *,
    args: argparse.Namespace,
    output_dir: Path,
    sample_count: int,
    run_id: str,
    run_started_at: datetime,
    run_finished_at: datetime,
    paths: OutputPaths,
) -> dict[str, Any]:
    return {
        "report": REPORT_NAME,
        "version": VERSION,
        "run_id": run_id,
        "output_dir": str(output_dir),
        "run_started_at_utc": fmt_ts(run_started_at.replace(tzinfo=None)),
        "run_finished_at_utc": fmt_ts(run_finished_at.replace(tzinfo=None)),
        "run_duration_sec": round((run_finished_at - run_started_at).total_seconds(), 6),
        "venue": args.venue,
        "interval": args.interval,
        "start_ts": args.start_ts,
        "end_ts": args.end_ts,
        "max_rows": int(args.max_rows),
        "sample_count": int(sample_count),
        "wrote_files": bool(args.write_files),
        "notes": [
            "Read-only research audit comparing execution entry/tp zones against fib levels.",
            "No selection, decision, execution, broker, account, or dashboard behavior is changed.",
            "TP hit flags use future candles only for research outcome measurement.",
        ],
        "output_paths": {
            "events_csv": str(paths.events_csv),
            "summary_by_entry_alignment_csv": str(paths.summary_by_entry_alignment_csv),
            "summary_by_tp_alignment_csv": str(paths.summary_by_tp_alignment_csv),
            "summary_by_symbol_csv": str(paths.summary_by_symbol_csv),
            "summary_by_zone_type_csv": str(paths.summary_by_zone_type_csv),
            "manifest_json": str(paths.manifest_json),
        },
        **SAFETY_MARKERS,
    }


def render_table(manifest: dict[str, Any]) -> str:
    lines = [
        f"[RUN][ID] {manifest['run_id']}",
        f"[RUN][OUT_DIR] {manifest['output_dir']}",
        f"report={REPORT_NAME} version={VERSION}",
        "scope=research-only read-only-db",
        "selection_engine=none decision_gate=none execution_planner=none executor=none",
        "db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0",
        f"venue={manifest['venue']} interval={manifest['interval']}",
        f"start_ts={manifest['start_ts']} end_ts={manifest['end_ts']} max_rows={manifest['max_rows']} sample_count={manifest['sample_count']}",
        f"wrote_files={manifest['wrote_files']}",
    ]
    if manifest["wrote_files"]:
        for key, value in manifest["output_paths"].items():
            lines.append(f"  wrote_file[{key}]={value}")
    lines.append("[DONE] db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.interval not in INTERVAL_SECONDS:
        raise ValueError(f"Unsupported interval: {args.interval}")
    if args.max_rows < 0:
        raise ValueError("--max-rows must be >= 0")

    start_ts = parse_ts(args.start_ts)
    end_ts = parse_ts(args.end_ts)
    if start_ts > end_ts:
        raise ValueError("--start-ts must be <= --end-ts")

    run_started_at = datetime.now(UTC)
    run_id = utc_run_id(run_started_at)
    output_dir = resolve_output_dir(output_root=args.output_root, run_id=run_id)
    paths = output_paths(output_dir)

    conn = get_connection()
    try:
        base_rows = fetch_base_rows(
            conn,
            venue=args.venue,
            interval_code=args.interval,
            start_ts=start_ts,
            end_ts=end_ts,
            max_rows=int(args.max_rows),
        )

        event_rows: list[dict[str, str]] = []
        for row in base_rows:
            asof_ts = row["asof_ts_utc"]
            leg_direction = str(row.get("leg_direction") or "").upper()
            entry_low = dec(row.get("expected_entry_zone_low"))
            entry_high = dec(row.get("expected_entry_zone_high"))
            tp_low = dec(row.get("expected_take_profit_zone_low"))
            tp_high = dec(row.get("expected_take_profit_zone_high"))
            fib_0500 = dec(row.get("fib_0500_price"))
            fib_0618 = dec(row.get("fib_0618_price"))
            fib_0786 = dec(row.get("fib_0786_price"))
            ext_1272 = dec(row.get("ext_1272_price"))
            ext_1618 = dec(row.get("ext_1618_price"))
            asof_price = dec(row.get("asof_close_price"))

            entry_mid = midpoint(entry_low, entry_high)
            tp_mid = midpoint(tp_low, tp_high)
            nearest_entry_fib_level, entry_fib_distance = nearest_level_name_and_distance(
                entry_mid,
                {
                    "FIB_0500": fib_0500,
                    "FIB_0618": fib_0618,
                    "FIB_0786": fib_0786,
                },
            )
            nearest_tp_fib_level, tp_fib_distance = nearest_level_name_and_distance(
                tp_mid,
                {
                    "EXT_1272": ext_1272,
                    "EXT_1618": ext_1618,
                    "FIB_0786": fib_0786,
                },
            )
            entry_label, entry_is_band = entry_alignment_label(
                str(row.get("expected_entry_zone_type") or ""),
                entry_low,
                entry_high,
                fib_0500,
                fib_0618,
                fib_0786,
                entry_fib_distance,
            )
            tp_label, tp_is_band = tp_alignment_label(
                str(row.get("expected_take_profit_zone_type") or ""),
                tp_low,
                tp_high,
                ext_1272,
                ext_1618,
                tp_fib_distance,
            )

            future_candles = fetch_future_candles(
                conn,
                venue=args.venue,
                interval_code=args.interval,
                asset_id=int(row["asset_id"]),
                sample_ts=asof_ts,
            )
            price_24h = price_at_horizon(asof_ts, future_candles, 24)
            price_48h = price_at_horizon(asof_ts, future_candles, 48)
            event_rows.append(
                {
                    "symbol": str(row["symbol"]),
                    "asof_ts_utc": fmt_ts(asof_ts),
                    "leg_direction": leg_direction,
                    "entry_zone_type": str(row.get("expected_entry_zone_type") or ""),
                    "entry_zone_low": format_number(entry_low, "0.00000001"),
                    "entry_zone_high": format_number(entry_high, "0.00000001"),
                    "tp_zone_type": str(row.get("expected_take_profit_zone_type") or ""),
                    "tp_zone_low": format_number(tp_low, "0.00000001"),
                    "tp_zone_high": format_number(tp_high, "0.00000001"),
                    "fib_0500_price": format_number(fib_0500, "0.00000001"),
                    "fib_0618_price": format_number(fib_0618, "0.00000001"),
                    "fib_0786_price": format_number(fib_0786, "0.00000001"),
                    "ext_1272_price": format_number(ext_1272, "0.00000001"),
                    "ext_1618_price": format_number(ext_1618, "0.00000001"),
                    "nearest_entry_fib_level": nearest_entry_fib_level,
                    "entry_fib_distance_pct": format_number(entry_fib_distance),
                    "nearest_tp_fib_level": nearest_tp_fib_level,
                    "tp_fib_distance_pct": format_number(tp_fib_distance),
                    "entry_alignment_label": entry_label,
                    "tp_alignment_label": tp_label,
                    "entry_is_fib_band": "1" if entry_is_band else "0",
                    "tp_is_fib_extension_band": "1" if tp_is_band else "0",
                    "distance_to_tp_pct": format_number(pct_distance(asof_price, tp_mid)),
                    "forward_return_24h_pct": format_number(pct_return(asof_price, price_24h, leg_direction)),
                    "forward_return_48h_pct": format_number(pct_return(asof_price, price_48h, leg_direction)),
                    "hit_tp_24h": "1" if hit_tp(leg_direction=leg_direction, tp_zone_low=tp_low, tp_zone_high=tp_high, future_candles=future_candles, horizon_hours=24) else "0",
                    "hit_tp_48h": "1" if hit_tp(leg_direction=leg_direction, tp_zone_low=tp_low, tp_zone_high=tp_high, future_candles=future_candles, horizon_hours=48) else "0",
                }
            )
        conn.rollback()
    finally:
        conn.close()

    summary_by_entry_alignment = summarize_by(event_rows, "entry_alignment_label")
    summary_by_tp_alignment = summarize_by(event_rows, "tp_alignment_label")
    summary_by_symbol = summarize_by(event_rows, "symbol")
    zone_typed_rows = []
    for row in event_rows:
        copied = dict(row)
        copied["zone_type_pair"] = f"{row['entry_zone_type']}|{row['tp_zone_type']}"
        zone_typed_rows.append(copied)
    summary_by_zone_type = summarize_by(zone_typed_rows, "zone_type_pair")

    run_finished_at = datetime.now(UTC)
    manifest = build_manifest(
        args=args,
        output_dir=output_dir,
        sample_count=len(event_rows),
        run_id=run_id,
        run_started_at=run_started_at,
        run_finished_at=run_finished_at,
        paths=paths,
    )

    if args.write_files:
        write_csv(paths.events_csv, event_rows, EVENT_FIELDS)
        write_csv(paths.summary_by_entry_alignment_csv, summary_by_entry_alignment, SUMMARY_FIELDS)
        write_csv(paths.summary_by_tp_alignment_csv, summary_by_tp_alignment, SUMMARY_FIELDS)
        write_csv(paths.summary_by_symbol_csv, summary_by_symbol, SUMMARY_FIELDS)
        write_csv(paths.summary_by_zone_type_csv, summary_by_zone_type, SUMMARY_FIELDS)
        write_json(paths.manifest_json, manifest)

    if args.output == "json":
        print(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True))
    else:
        print(render_table(manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
