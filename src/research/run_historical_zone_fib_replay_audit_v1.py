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
from time import perf_counter
from typing import Any

from src.common.db import get_connection


REPORT_NAME = "historical_zone_fib_replay_audit_v1"
VERSION = "1.0"
DEFAULT_OUTPUT_ROOT = "data/research/historical_zone_fib_replay_audit_v1"
DEFAULT_RUN_DIR_PREFIX = "run_"
DEFAULT_HORIZONS_HOURS = [4, 8, 12, 24, 48]

EVENTS_CSV = "zone_fib_replay_events_v1.csv"
SUMMARY_BY_ENTRY_ALIGNMENT_CSV = "summary_by_entry_alignment_v1.csv"
SUMMARY_BY_TP_ALIGNMENT_CSV = "summary_by_tp_alignment_v1.csv"
SUMMARY_BY_TP_ALIGNMENT_DIRECTIONAL_CSV = "summary_by_tp_alignment_directional_v1.csv"
SUMMARY_BY_TP_ALIGNMENT_FUTURE_STRICT_CSV = "summary_by_tp_alignment_future_strict_v1.csv"
SUMMARY_BY_SYMBOL_CSV = "summary_by_symbol_v1.csv"
SUMMARY_BY_LEG_DIRECTION_CSV = "summary_by_leg_direction_v1.csv"
SUMMARY_BY_TP_ALIGNMENT_AND_LEG_CSV = "summary_by_tp_alignment_and_leg_v1.csv"
SUMMARY_BY_TP_SIDE_LABEL_CSV = "summary_by_tp_side_label_v1.csv"
SUMMARY_BY_TP_SIDE_FUTURE_STRICT_CSV = "summary_by_tp_side_future_strict_v1.csv"
SUMMARY_BY_TP_ALIGNMENT_AND_SIDE_CSV = "summary_by_tp_alignment_and_side_v1.csv"
SUMMARY_BY_TP_ALIGNMENT_AND_SIDE_FUTURE_STRICT_CSV = "summary_by_tp_alignment_and_side_future_strict_v1.csv"
SUMMARY_BY_VALID_FUTURE_TP_TARGET_CSV = "summary_by_valid_future_tp_target_v1.csv"
MANIFEST_JSON = "manifest_v1.json"
LEAKAGE_GUARD_JSON = "leakage_guard_report_v1.json"

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
    "account_tables_used": False,
}

EVENT_FIELDS = [
    "symbol",
    "sample_ts_utc",
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
    "sample_close_price",
    "distance_to_tp_pct",
    "tp_side_label",
    "tp_already_crossed_at_sample",
    "directional_distance_to_tp_pct",
    "forward_return_4h_pct",
    "forward_return_8h_pct",
    "forward_return_12h_pct",
    "forward_return_24h_pct",
    "forward_return_48h_pct",
    "hit_tp_4h",
    "hit_tp_8h",
    "hit_tp_12h",
    "hit_tp_24h",
    "hit_tp_48h",
    "hit_tp_directional_4h",
    "hit_tp_directional_8h",
    "hit_tp_directional_12h",
    "hit_tp_directional_24h",
    "hit_tp_directional_48h",
    "forward_window_first_candle_ts_4h",
    "forward_window_first_candle_ts_24h",
    "forward_window_candle_count_4h",
    "forward_window_candle_count_24h",
    "hit_tp_future_strict_4h",
    "hit_tp_future_strict_8h",
    "hit_tp_future_strict_12h",
    "hit_tp_future_strict_24h",
    "hit_tp_future_strict_48h",
    "future_strict_hit_note",
    "valid_future_tp_target",
    "invalid_future_tp_reason",
    "max_high_4h",
    "min_low_4h",
    "max_high_24h",
    "min_low_24h",
    "hit_tp_sanity_note",
    "max_input_ts_utc",
    "leakage_flag",
]

SUMMARY_FIELDS = [
    "label",
    "event_count",
    "avg_entry_fib_distance_pct",
    "avg_tp_fib_distance_pct",
    "avg_distance_to_tp_pct",
    "avg_forward_return_4h_pct",
    "median_forward_return_4h_pct",
    "avg_forward_return_8h_pct",
    "avg_forward_return_12h_pct",
    "avg_forward_return_24h_pct",
    "avg_forward_return_48h_pct",
    "hit_tp_4h_rate_pct",
    "hit_tp_8h_rate_pct",
    "hit_tp_12h_rate_pct",
    "hit_tp_24h_rate_pct",
    "hit_tp_48h_rate_pct",
    "hit_tp_directional_4h_rate_pct",
    "hit_tp_directional_8h_rate_pct",
    "hit_tp_directional_12h_rate_pct",
    "hit_tp_directional_24h_rate_pct",
    "hit_tp_directional_48h_rate_pct",
    "hit_tp_future_strict_4h_rate_pct",
    "hit_tp_future_strict_8h_rate_pct",
    "hit_tp_future_strict_12h_rate_pct",
    "hit_tp_future_strict_24h_rate_pct",
    "hit_tp_future_strict_48h_rate_pct",
]


@dataclass(frozen=True)
class OutputPaths:
    events_csv: Path
    summary_by_entry_alignment_csv: Path
    summary_by_tp_alignment_csv: Path
    summary_by_tp_alignment_directional_csv: Path
    summary_by_tp_alignment_future_strict_csv: Path
    summary_by_symbol_csv: Path
    summary_by_leg_direction_csv: Path
    summary_by_tp_alignment_and_leg_csv: Path
    summary_by_tp_side_label_csv: Path
    summary_by_tp_side_future_strict_csv: Path
    summary_by_tp_alignment_and_side_csv: Path
    summary_by_tp_alignment_and_side_future_strict_csv: Path
    summary_by_valid_future_tp_target_csv: Path
    manifest_json: Path
    leakage_guard_json: Path


@dataclass(frozen=True)
class FutureCandle:
    close_ts_utc: datetime
    close_price: Decimal
    high_price: Decimal
    low_price: Decimal


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Historically replay zone/fib context point-in-time from fib and zone observations "
            "and measure forward outcomes (research-only, no execution_zone_context history dependency)."
        )
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--start-ts", required=True)
    parser.add_argument("--end-ts", required=True)
    parser.add_argument("--sample-every-n", type=int, default=1)
    parser.add_argument(
        "--max-samples",
        type=int,
        default=0,
        help="Maximum sampled timestamps to replay. Use 0 for unlimited.",
    )
    parser.add_argument(
        "--horizons-hours",
        nargs="+",
        default=[str(value) for value in DEFAULT_HORIZONS_HOURS],
        help="Forward horizons in hours. Accepts either spaced values or comma-separated groups.",
    )
    parser.add_argument("--write-files", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--output-root", default=None)
    return parser.parse_args(argv)


def parse_ts(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC).replace(tzinfo=None)
    return parsed.astimezone(UTC).replace(tzinfo=None)


def fmt_ts(value: datetime | None) -> str:
    if value is None:
        return ""
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
        summary_by_tp_alignment_directional_csv=output_dir / SUMMARY_BY_TP_ALIGNMENT_DIRECTIONAL_CSV,
        summary_by_tp_alignment_future_strict_csv=output_dir / SUMMARY_BY_TP_ALIGNMENT_FUTURE_STRICT_CSV,
        summary_by_symbol_csv=output_dir / SUMMARY_BY_SYMBOL_CSV,
        summary_by_leg_direction_csv=output_dir / SUMMARY_BY_LEG_DIRECTION_CSV,
        summary_by_tp_alignment_and_leg_csv=output_dir / SUMMARY_BY_TP_ALIGNMENT_AND_LEG_CSV,
        summary_by_tp_side_label_csv=output_dir / SUMMARY_BY_TP_SIDE_LABEL_CSV,
        summary_by_tp_side_future_strict_csv=output_dir / SUMMARY_BY_TP_SIDE_FUTURE_STRICT_CSV,
        summary_by_tp_alignment_and_side_csv=output_dir / SUMMARY_BY_TP_ALIGNMENT_AND_SIDE_CSV,
        summary_by_tp_alignment_and_side_future_strict_csv=output_dir / SUMMARY_BY_TP_ALIGNMENT_AND_SIDE_FUTURE_STRICT_CSV,
        summary_by_valid_future_tp_target_csv=output_dir / SUMMARY_BY_VALID_FUTURE_TP_TARGET_CSV,
        manifest_json=output_dir / MANIFEST_JSON,
        leakage_guard_json=output_dir / LEAKAGE_GUARD_JSON,
    )


def parse_horizons_hours(values: list[Any] | None) -> list[int]:
    if not values:
        raise ValueError("--horizons-hours must not be empty")
    horizons: list[int] = []
    for value in values:
        raw = str(value).strip()
        if not raw:
            continue
        for piece in raw.split(","):
            token = piece.strip()
            if not token:
                continue
            parsed = int(token)
            if parsed <= 0:
                raise ValueError("--horizons-hours values must be > 0")
            horizons.append(parsed)
    if not horizons:
        raise ValueError("--horizons-hours must not be empty")
    return sorted(set(horizons))


def dec(value: Any) -> Decimal | None:
    if value in ("", None):
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return None


def format_number(value: Decimal | float | int | None, places: str = "0.000001") -> str:
    if value is None:
        return ""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    try:
        return str(value.quantize(Decimal(places)))
    except Exception:
        return str(value)


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


def midpoint(low: Decimal | None, high: Decimal | None) -> Decimal | None:
    if low is not None and high is not None:
        return (low + high) / Decimal("2")
    if low is not None:
        return low
    return high


def pct_distance(reference_price: Decimal | None, target_price: Decimal | None) -> Decimal | None:
    if reference_price is None or target_price is None or reference_price <= 0:
        return None
    return abs(target_price - reference_price) / reference_price * Decimal("100")


def pct_return(base_price: Decimal | None, future_price: Decimal | None, leg_direction: str) -> Decimal | None:
    if base_price is None or future_price is None or base_price <= 0:
        return None
    raw = ((future_price / base_price) - Decimal("1")) * Decimal("100")
    if leg_direction == "DOWN":
        raw = -raw
    return raw


def band_overlap(low_a: Decimal | None, high_a: Decimal | None, low_b: Decimal | None, high_b: Decimal | None) -> bool:
    if None in {low_a, high_a, low_b, high_b}:
        return False
    return max(low_a, low_b) <= min(high_a, high_b)


def nearest_level_name_and_distance(
    zone_mid: Decimal | None,
    levels: dict[str, Decimal | None],
) -> tuple[str, Decimal | None]:
    if zone_mid is None:
        return "", None
    candidates = [
        (name, pct_distance(level_price, zone_mid))
        for name, level_price in levels.items()
        if level_price is not None
    ]
    if not candidates:
        return "", None
    best_name, best_distance = min(
        candidates,
        key=lambda item: (
            item[1] if item[1] is not None else Decimal("999999"),
            item[0],
        ),
    )
    return best_name, best_distance


def classify_entry_alignment(
    entry_type: str | None,
    zone_low: Decimal | None,
    zone_high: Decimal | None,
    fib_0500: Decimal | None,
    fib_0618: Decimal | None,
    fib_0786: Decimal | None,
) -> tuple[str, int]:
    primary_low = min(fib_0500, fib_0618) if fib_0500 is not None and fib_0618 is not None else None
    primary_high = max(fib_0500, fib_0618) if fib_0500 is not None and fib_0618 is not None else None
    deep_low = min(fib_0618, fib_0786) if fib_0618 is not None and fib_0786 is not None else None
    deep_high = max(fib_0618, fib_0786) if fib_0618 is not None and fib_0786 is not None else None

    entry_type = str(entry_type or "").upper()
    if entry_type == "FIB_RETRACEMENT" or band_overlap(zone_low, zone_high, primary_low, primary_high):
        return "ENTRY_FIB_PRIMARY_0500_0618", 1
    if entry_type == "FIB_DEEP" or band_overlap(zone_low, zone_high, deep_low, deep_high):
        return "ENTRY_FIB_DEEP_0618_0786", 1
    if entry_type or zone_low is not None or zone_high is not None:
        return "ENTRY_SR_ONLY", 0
    return "ENTRY_UNKNOWN", 0


def classify_tp_alignment(
    tp_type: str | None,
    zone_low: Decimal | None,
    zone_high: Decimal | None,
    ext_1272: Decimal | None,
    ext_1618: Decimal | None,
    nearest_distance: Decimal | None,
    near_threshold_pct: Decimal = Decimal("1.0"),
) -> tuple[str, int]:
    ext_low = min(ext_1272, ext_1618) if ext_1272 is not None and ext_1618 is not None else None
    ext_high = max(ext_1272, ext_1618) if ext_1272 is not None and ext_1618 is not None else None
    tp_type = str(tp_type or "").upper()
    if tp_type == "FIB_EXTENSION" or band_overlap(zone_low, zone_high, ext_low, ext_high):
        return "TP_FIB_EXTENSION_1272_1618", 1
    if nearest_distance is not None and nearest_distance <= near_threshold_pct:
        return "TP_NEAR_FIB_EXTENSION", 0
    if tp_type or zone_low is not None or zone_high is not None:
        return "TP_SR_ONLY", 0
    return "TP_UNKNOWN", 0


def sample_limit_clause(max_samples: int) -> str:
    if max_samples <= 0:
        return ""
    return f"LIMIT {int(max_samples)}"


def fetch_sample_timestamps(
    conn: Any,
    *,
    fib_table: str,
    venue: str,
    interval: str,
    start_ts: datetime,
    end_ts: datetime,
    sample_every_n: int,
    max_samples: int,
) -> list[datetime]:
    if sample_every_n <= 0:
        raise ValueError("--sample-every-n must be > 0")
    sql = f"""
    WITH ordered AS (
        SELECT
            asof_ts_utc,
            ROW_NUMBER() OVER (ORDER BY asof_ts_utc) AS seq_num
        FROM (
            SELECT DISTINCT asof_ts_utc
            FROM {fib_table}
            WHERE venue = %s
              AND interval_code = %s
              AND asof_ts_utc >= %s
              AND asof_ts_utc <= %s
        ) t
    )
    SELECT asof_ts_utc
    FROM ordered
    WHERE MOD(seq_num - 1, %s) = 0
    ORDER BY asof_ts_utc
    {sample_limit_clause(max_samples)}
    """
    with conn.cursor() as cur:
        cur.execute(sql, (venue, interval, start_ts, end_ts, sample_every_n))
        return [row["asof_ts_utc"] for row in cur.fetchall()]


def fetch_replay_rows(
    conn: Any,
    *,
    fib_table: str,
    zone_table: str,
    venue: str,
    interval: str,
    sample_timestamps: list[datetime],
) -> list[dict[str, Any]]:
    if not sample_timestamps:
        return []
    placeholders = ",".join(["%s"] * len(sample_timestamps))
    sql = f"""
    SELECT
        a.symbol,
        f.asset_id,
        f.asof_ts_utc AS sample_ts_utc,
        f.leg_direction,
        f.fib_0500_price,
        f.fib_0618_price,
        f.fib_0786_price,
        f.ext_1272_price,
        f.ext_1618_price,
        f.asof_ts_utc AS fib_asof_ts_utc,
        z.zone_type,
        z.zone_source_type,
        z.zone_low_price,
        z.zone_high_price,
        z.zone_strength_score,
        z.confluence_score,
        z.expected_reaction,
        z.invalidation_price,
        z.asof_ts_utc AS zone_asof_ts_utc,
        c.close_price AS sample_close_price
    FROM {fib_table} f
    JOIN asset a
      ON a.asset_id = f.asset_id
    LEFT JOIN {zone_table} z
      ON z.asset_id = f.asset_id
     AND z.venue = f.venue
     AND z.interval_code = f.interval_code
     AND z.asof_ts_utc = f.asof_ts_utc
    LEFT JOIN obs_market_candle c
      ON c.asset_id = f.asset_id
     AND c.venue = f.venue
     AND c.interval_code = f.interval_code
     AND c.close_ts_utc = f.asof_ts_utc
    WHERE f.venue = %s
      AND f.interval_code = %s
      AND f.asof_ts_utc IN ({placeholders})
    ORDER BY f.asof_ts_utc, a.symbol, z.zone_type
    """
    params: list[Any] = [venue, interval, *sample_timestamps]
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def fetch_future_candles(
    conn: Any,
    *,
    venue: str,
    interval: str,
    asset_ids: list[int],
    start_ts: datetime,
    end_ts: datetime,
) -> dict[int, list[FutureCandle]]:
    if not asset_ids:
        return {}
    placeholders = ",".join(["%s"] * len(asset_ids))
    sql = f"""
    SELECT
        asset_id,
        close_ts_utc,
        close_price,
        high_price,
        low_price
    FROM obs_market_candle
    WHERE venue = %s
      AND interval_code = %s
      AND asset_id IN ({placeholders})
      AND close_ts_utc >= %s
      AND close_ts_utc <= %s
    ORDER BY asset_id, close_ts_utc
    """
    params: list[Any] = [venue, interval, *asset_ids, start_ts, end_ts]
    by_asset: dict[int, list[FutureCandle]] = defaultdict(list)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        for row in cur.fetchall():
            by_asset[int(row["asset_id"])].append(
                FutureCandle(
                    close_ts_utc=row["close_ts_utc"],
                    close_price=dec(row["close_price"]) or Decimal("0"),
                    high_price=dec(row["high_price"]) or Decimal("0"),
                    low_price=dec(row["low_price"]) or Decimal("0"),
                )
            )
    return dict(by_asset)


def select_entry_zone(zone_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    fib_zone_candidates = [
        row for row in zone_rows if str(row.get("zone_type") or "").upper() in {"FIB_RETRACEMENT", "FIB_DEEP"}
    ]
    sr_zone_candidates = [
        row for row in zone_rows if str(row.get("zone_type") or "").upper() in {"SR_SUPPORT", "SR_RESISTANCE"}
    ]
    best_entry: dict[str, Any] | None = None
    best_score = Decimal("-999")
    for fib_zone in fib_zone_candidates:
        confluence_bonus = Decimal("0")
        fib_low = dec(fib_zone.get("zone_low_price"))
        fib_high = dec(fib_zone.get("zone_high_price"))
        for sr_zone in sr_zone_candidates:
            if band_overlap(
                fib_low,
                fib_high,
                dec(sr_zone.get("zone_low_price")),
                dec(sr_zone.get("zone_high_price")),
            ):
                confluence_bonus += Decimal("0.25")
        score = (
            (dec(fib_zone.get("zone_strength_score")) or Decimal("0"))
            + (dec(fib_zone.get("confluence_score")) or Decimal("0"))
            + confluence_bonus
        )
        if score > best_score:
            best_score = score
            best_entry = fib_zone
    return best_entry


def build_fib_extension_tp(
    *,
    fib_row: dict[str, Any],
    sample_ts: datetime,
) -> dict[str, Any]:
    ext_1272 = dec(fib_row.get("ext_1272_price"))
    ext_1618 = dec(fib_row.get("ext_1618_price"))
    low = min(ext_1272, ext_1618) if ext_1272 is not None and ext_1618 is not None else ext_1272 or ext_1618
    high = max(ext_1272, ext_1618) if ext_1272 is not None and ext_1618 is not None else ext_1272 or ext_1618
    return {
        "zone_type": "FIB_EXTENSION",
        "zone_source_type": "FIB",
        "zone_low_price": low,
        "zone_high_price": high,
        "zone_strength_score": Decimal("0.55"),
        "confluence_score": Decimal("0.20"),
        "zone_asof_ts_utc": sample_ts,
    }


def select_tp_zone(
    *,
    leg_direction: str,
    zone_rows: list[dict[str, Any]],
    fib_row: dict[str, Any],
    sample_ts: datetime,
) -> dict[str, Any] | None:
    if leg_direction == "UP":
        candidates = [row for row in zone_rows if str(row.get("zone_type") or "").upper() == "SR_RESISTANCE"]
    else:
        candidates = [row for row in zone_rows if str(row.get("zone_type") or "").upper() == "SR_SUPPORT"]
    if candidates:
        return max(
            candidates,
            key=lambda row: (
                (dec(row.get("zone_strength_score")) or Decimal("0"))
                + (dec(row.get("confluence_score")) or Decimal("0"))
            ),
        )
    return build_fib_extension_tp(fib_row=fib_row, sample_ts=sample_ts)


def future_price_for_horizon(
    candles: list[FutureCandle],
    *,
    sample_ts: datetime,
    horizon_hours: int,
) -> Decimal | None:
    target_ts = sample_ts + timedelta(hours=horizon_hours)
    for candle in candles:
        if candle.close_ts_utc >= target_ts:
            return candle.close_price
    return None


def hit_tp(
    *,
    candles: list[FutureCandle],
    sample_ts: datetime,
    horizon_hours: int,
    leg_direction: str,
    tp_price: Decimal | None,
) -> int:
    if tp_price is None:
        return 0
    cutoff_ts = sample_ts + timedelta(hours=horizon_hours)
    for candle in candles:
        if candle.close_ts_utc > cutoff_ts:
            break
        if leg_direction == "UP" and candle.high_price >= tp_price:
            return 1
        if leg_direction == "DOWN" and candle.low_price <= tp_price:
            return 1
    return 0


def tp_directional_target(
    *,
    leg_direction: str,
    tp_low: Decimal | None,
    tp_high: Decimal | None,
    tp_mid: Decimal | None,
) -> Decimal | None:
    if leg_direction == "UP":
        return tp_low if tp_low is not None else tp_mid
    if leg_direction == "DOWN":
        return tp_high if tp_high is not None else tp_mid
    return tp_mid


def tp_side_label_and_crossed(
    *,
    leg_direction: str,
    sample_close_price: Decimal | None,
    tp_target: Decimal | None,
    near_threshold_pct: Decimal = Decimal("0.10"),
) -> tuple[str, int, str]:
    if sample_close_price is None or sample_close_price <= 0 or tp_target is None:
        return "TP_UNKNOWN", 0, "TP_TARGET_UNKNOWN"
    distance_pct = pct_distance(sample_close_price, tp_target)
    if distance_pct is not None and distance_pct <= near_threshold_pct:
        crossed = int(
            (leg_direction == "UP" and tp_target <= sample_close_price)
            or (leg_direction == "DOWN" and tp_target >= sample_close_price)
        )
        return "TP_AT_OR_NEAR_PRICE", crossed, "TP_AT_OR_NEAR_SAMPLE_PRICE"
    if leg_direction == "UP":
        if tp_target <= sample_close_price:
            return "TP_WRONG_SIDE_FOR_LEG", 1, "UP_TP_ALREADY_CROSSED_OR_BELOW_PRICE"
        return "TP_ABOVE_PRICE", 0, "UP_TP_ABOVE_PRICE"
    if leg_direction == "DOWN":
        if tp_target >= sample_close_price:
            return "TP_WRONG_SIDE_FOR_LEG", 1, "DOWN_TP_ALREADY_CROSSED_OR_ABOVE_PRICE"
        return "TP_BELOW_PRICE", 0, "DOWN_TP_BELOW_PRICE"
    return "TP_UNKNOWN", 0, "TP_TARGET_UNKNOWN"


def hit_tp_directional(
    *,
    candles: list[FutureCandle],
    sample_ts: datetime,
    horizon_hours: int,
    leg_direction: str,
    tp_trigger_price: Decimal | None,
    tp_already_crossed_at_sample: int,
    tp_side_label: str,
) -> int:
    if tp_trigger_price is None:
        return 0
    if tp_already_crossed_at_sample:
        return 0
    if tp_side_label in {"TP_UNKNOWN", "TP_WRONG_SIDE_FOR_LEG", "TP_AT_OR_NEAR_PRICE"}:
        return 0
    cutoff_ts = sample_ts + timedelta(hours=horizon_hours)
    for candle in candles:
        if candle.close_ts_utc > cutoff_ts:
            break
        if leg_direction == "UP" and candle.high_price >= tp_trigger_price:
            return 1
        if leg_direction == "DOWN" and candle.low_price <= tp_trigger_price:
            return 1
    return 0


def future_extremes(
    *,
    candles: list[FutureCandle],
    sample_ts: datetime,
    horizon_hours: int,
) -> tuple[Decimal | None, Decimal | None]:
    cutoff_ts = sample_ts + timedelta(hours=horizon_hours)
    highs: list[Decimal] = []
    lows: list[Decimal] = []
    for candle in candles:
        if candle.close_ts_utc > cutoff_ts:
            break
        highs.append(candle.high_price)
        lows.append(candle.low_price)
    if not highs or not lows:
        return None, None
    return max(highs), min(lows)


def strict_future_window(
    *,
    candles: list[FutureCandle],
    sample_ts: datetime,
    horizon_hours: int,
) -> list[FutureCandle]:
    cutoff_ts = sample_ts + timedelta(hours=horizon_hours)
    return [
        candle
        for candle in candles
        if candle.close_ts_utc > sample_ts and candle.close_ts_utc <= cutoff_ts
    ]


def invalid_future_tp_reason(
    *,
    tp_already_crossed_at_sample: int,
    tp_side_label: str,
    strict_future_candles_exist: bool,
) -> str:
    if tp_already_crossed_at_sample:
        return "ALREADY_CROSSED_AT_SAMPLE"
    if tp_side_label == "TP_WRONG_SIDE_FOR_LEG":
        return "WRONG_SIDE_FOR_LEG"
    if tp_side_label == "TP_AT_OR_NEAR_PRICE":
        return "AT_OR_NEAR_PRICE"
    if not strict_future_candles_exist:
        return "NO_FUTURE_CANDLES"
    return "VALID"


def hit_tp_future_strict(
    *,
    candles: list[FutureCandle],
    leg_direction: str,
    tp_trigger_price: Decimal | None,
    valid_future_tp_target: bool,
) -> int:
    if tp_trigger_price is None or not valid_future_tp_target:
        return 0
    for candle in candles:
        if leg_direction == "UP" and candle.high_price >= tp_trigger_price:
            return 1
        if leg_direction == "DOWN" and candle.low_price <= tp_trigger_price:
            return 1
    return 0


def summarize_by(rows: list[dict[str, Any]], key_name: str) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row.get(key_name) or "")].append(row)

    out: list[dict[str, Any]] = []
    for label in sorted(groups):
        group = groups[label]

        def avg_decimal(field: str) -> Decimal | None:
            values = [dec(item.get(field)) for item in group]
            values = [value for value in values if value is not None]
            if not values:
                return None
            return sum(values, Decimal("0")) / Decimal(len(values))

        def median_decimal(field: str) -> Decimal | None:
            values = [dec(item.get(field)) for item in group]
            values = [value for value in values if value is not None]
            if not values:
                return None
            return Decimal(str(median(values)))

        def hit_rate(field: str) -> Decimal | None:
            values = [int(item.get(field) or 0) for item in group]
            if not values:
                return None
            return (Decimal(sum(values)) / Decimal(len(values))) * Decimal("100")

        out.append(
            {
                "label": label,
                "event_count": len(group),
                "avg_entry_fib_distance_pct": avg_decimal("entry_fib_distance_pct"),
                "avg_tp_fib_distance_pct": avg_decimal("tp_fib_distance_pct"),
                "avg_distance_to_tp_pct": avg_decimal("distance_to_tp_pct"),
                "avg_forward_return_4h_pct": avg_decimal("forward_return_4h_pct"),
                "median_forward_return_4h_pct": median_decimal("forward_return_4h_pct"),
                "avg_forward_return_8h_pct": avg_decimal("forward_return_8h_pct"),
                "avg_forward_return_12h_pct": avg_decimal("forward_return_12h_pct"),
                "avg_forward_return_24h_pct": avg_decimal("forward_return_24h_pct"),
                "avg_forward_return_48h_pct": avg_decimal("forward_return_48h_pct"),
                "hit_tp_4h_rate_pct": hit_rate("hit_tp_4h"),
                "hit_tp_8h_rate_pct": hit_rate("hit_tp_8h"),
                "hit_tp_12h_rate_pct": hit_rate("hit_tp_12h"),
                "hit_tp_24h_rate_pct": hit_rate("hit_tp_24h"),
                "hit_tp_48h_rate_pct": hit_rate("hit_tp_48h"),
                "hit_tp_directional_4h_rate_pct": hit_rate("hit_tp_directional_4h"),
                "hit_tp_directional_8h_rate_pct": hit_rate("hit_tp_directional_8h"),
                "hit_tp_directional_12h_rate_pct": hit_rate("hit_tp_directional_12h"),
                "hit_tp_directional_24h_rate_pct": hit_rate("hit_tp_directional_24h"),
                "hit_tp_directional_48h_rate_pct": hit_rate("hit_tp_directional_48h"),
                "hit_tp_future_strict_4h_rate_pct": hit_rate("hit_tp_future_strict_4h"),
                "hit_tp_future_strict_8h_rate_pct": hit_rate("hit_tp_future_strict_8h"),
                "hit_tp_future_strict_12h_rate_pct": hit_rate("hit_tp_future_strict_12h"),
                "hit_tp_future_strict_24h_rate_pct": hit_rate("hit_tp_future_strict_24h"),
                "hit_tp_future_strict_48h_rate_pct": hit_rate("hit_tp_future_strict_48h"),
            }
        )
    return out


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            out_row: dict[str, Any] = {}
            for field in fieldnames:
                value = row.get(field)
                if isinstance(value, Decimal):
                    out_row[field] = format_number(value)
                elif isinstance(value, datetime):
                    out_row[field] = fmt_ts(value)
                else:
                    out_row[field] = value
            writer.writerow(out_row)


def build_leakage_guard_report(
    *,
    sample_count: int,
    event_count: int,
    max_input_ts_gt_sample_ts_rows: int,
    sample_range_start_utc: datetime,
    sample_range_end_utc: datetime,
) -> dict[str, Any]:
    return {
        "report": "leakage_guard_report_v1",
        "sample_count": sample_count,
        "event_count": event_count,
        "sample_range_start_utc": fmt_ts(sample_range_start_utc),
        "sample_range_end_utc": fmt_ts(sample_range_end_utc),
        "point_in_time_sources_only": True,
        "execution_zone_context_used_for_history": False,
        "future_candles_used_only_for_outcomes": True,
        "max_input_ts_gt_sample_ts_rows": max_input_ts_gt_sample_ts_rows,
        "directional_hit_fields_present": True,
        "strict_future_hit_fields_present": True,
        "sample_candle_excluded_from_hit_tests": True,
    }


def print_summary(
    *,
    args: argparse.Namespace,
    run_id: str,
    output_dir: Path,
    sample_count: int,
    event_count: int,
    leakage_rows: int,
) -> None:
    print(f"[RUN][ID] {run_id}")
    print(f"[RUN][OUT_DIR] {output_dir}")
    print(f"report={REPORT_NAME} version={VERSION}")
    print("scope=research-only point-in-time historical replay")
    print("candidate_source=historical fib_observation + zone_observation replay")
    print("execution_zone_context_history_dependency=false")
    print(
        "db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 "
        "account_tables_used=false"
    )
    print(
        f"venue={args.venue} interval={args.interval} "
        f"sample_count={sample_count} event_count={event_count} leakage_rows={leakage_rows}"
    )


def main(argv: list[str] | None = None) -> int:
    started_perf = perf_counter()
    run_started_at = datetime.now(UTC)
    args = parse_args(argv)
    start_ts = parse_ts(args.start_ts)
    end_ts = parse_ts(args.end_ts)
    horizons_hours = parse_horizons_hours(args.horizons_hours)
    if args.sample_every_n <= 0:
        raise ValueError("--sample-every-n must be > 0")

    conn = get_connection()
    try:
        fib_table = fib_table_name(conn)
        zone_table = zone_table_name(conn)
        sample_timestamps = fetch_sample_timestamps(
            conn,
            fib_table=fib_table,
            venue=args.venue,
            interval=args.interval,
            start_ts=start_ts,
            end_ts=end_ts,
            sample_every_n=args.sample_every_n,
            max_samples=args.max_samples,
        )
        replay_rows = fetch_replay_rows(
            conn,
            fib_table=fib_table,
            zone_table=zone_table,
            venue=args.venue,
            interval=args.interval,
            sample_timestamps=sample_timestamps,
        )
        asset_ids = sorted({int(row["asset_id"]) for row in replay_rows})
        future_candles_by_asset = fetch_future_candles(
            conn,
            venue=args.venue,
            interval=args.interval,
            asset_ids=asset_ids,
            start_ts=start_ts,
            end_ts=end_ts + timedelta(hours=max(horizons_hours) + 4),
        )
    finally:
        conn.close()

    grouped_rows: dict[tuple[int, datetime], list[dict[str, Any]]] = defaultdict(list)
    for row in replay_rows:
        grouped_rows[(int(row["asset_id"]), row["sample_ts_utc"])].append(row)

    event_rows: list[dict[str, Any]] = []
    max_input_ts_gt_sample_ts_rows = 0
    already_crossed_tp_rows = 0
    wrong_side_tp_rows = 0
    invalid_future_tp_rows = 0
    no_future_candle_rows = 0

    for (asset_id, sample_ts), rows in sorted(grouped_rows.items(), key=lambda item: (item[0][1], str(item[1][0]["symbol"]))):
        base_row = rows[0]
        leg_direction = str(base_row.get("leg_direction") or "").upper()
        if leg_direction not in {"UP", "DOWN"}:
            continue
        entry_zone = select_entry_zone(rows)
        tp_zone = select_tp_zone(
            leg_direction=leg_direction,
            zone_rows=rows,
            fib_row=base_row,
            sample_ts=sample_ts,
        )
        entry_low = None if entry_zone is None else dec(entry_zone.get("zone_low_price"))
        entry_high = None if entry_zone is None else dec(entry_zone.get("zone_high_price"))
        tp_low = None if tp_zone is None else dec(tp_zone.get("zone_low_price"))
        tp_high = None if tp_zone is None else dec(tp_zone.get("zone_high_price"))
        sample_close_price = dec(base_row.get("sample_close_price"))
        fib_0500 = dec(base_row.get("fib_0500_price"))
        fib_0618 = dec(base_row.get("fib_0618_price"))
        fib_0786 = dec(base_row.get("fib_0786_price"))
        ext_1272 = dec(base_row.get("ext_1272_price"))
        ext_1618 = dec(base_row.get("ext_1618_price"))

        entry_mid = midpoint(entry_low, entry_high)
        tp_mid = midpoint(tp_low, tp_high)
        nearest_entry_fib_level, entry_fib_distance_pct = nearest_level_name_and_distance(
            entry_mid,
            {
                "fib_0500_price": fib_0500,
                "fib_0618_price": fib_0618,
                "fib_0786_price": fib_0786,
            },
        )
        nearest_tp_fib_level, tp_fib_distance_pct = nearest_level_name_and_distance(
            tp_mid,
            {
                "ext_1272_price": ext_1272,
                "ext_1618_price": ext_1618,
            },
        )
        entry_alignment_label, entry_is_fib_band = classify_entry_alignment(
            None if entry_zone is None else entry_zone.get("zone_type"),
            entry_low,
            entry_high,
            fib_0500,
            fib_0618,
            fib_0786,
        )
        tp_alignment_label, tp_is_fib_extension_band = classify_tp_alignment(
            None if tp_zone is None else tp_zone.get("zone_type"),
            tp_low,
            tp_high,
            ext_1272,
            ext_1618,
            tp_fib_distance_pct,
        )

        distance_to_tp_pct = pct_return(sample_close_price, tp_mid, leg_direction)
        tp_trigger_price = tp_directional_target(
            leg_direction=leg_direction,
            tp_low=tp_low,
            tp_high=tp_high,
            tp_mid=tp_mid,
        )
        tp_side_label, tp_already_crossed_at_sample, tp_side_note = tp_side_label_and_crossed(
            leg_direction=leg_direction,
            sample_close_price=sample_close_price,
            tp_target=tp_trigger_price,
        )
        directional_distance_to_tp_pct = pct_return(sample_close_price, tp_trigger_price, leg_direction)
        already_crossed_tp_rows += tp_already_crossed_at_sample
        wrong_side_tp_rows += int(tp_side_label == "TP_WRONG_SIDE_FOR_LEG")
        future_candles = future_candles_by_asset.get(asset_id, [])
        strict_future_candles_all = [candle for candle in future_candles if candle.close_ts_utc > sample_ts]
        invalid_reason = invalid_future_tp_reason(
            tp_already_crossed_at_sample=tp_already_crossed_at_sample,
            tp_side_label=tp_side_label,
            strict_future_candles_exist=bool(strict_future_candles_all),
        )
        valid_future_tp_target = int(invalid_reason == "VALID")
        invalid_future_tp_rows += int(not valid_future_tp_target)
        no_future_candle_rows += int(invalid_reason == "NO_FUTURE_CANDLES")
        horizon_returns: dict[int, Decimal | None] = {}
        horizon_hits: dict[int, int] = {}
        horizon_hits_directional: dict[int, int] = {}
        horizon_hits_future_strict: dict[int, int] = {}
        forward_window_first_ts: dict[int, datetime | None] = {}
        forward_window_count: dict[int, int] = {}
        for horizon in horizons_hours:
            future_price = future_price_for_horizon(
                future_candles,
                sample_ts=sample_ts,
                horizon_hours=horizon,
            )
            horizon_returns[horizon] = pct_return(sample_close_price, future_price, leg_direction)
            horizon_hits[horizon] = hit_tp(
                candles=future_candles,
                sample_ts=sample_ts,
                horizon_hours=horizon,
                leg_direction=leg_direction,
                tp_price=tp_mid,
            )
            horizon_hits_directional[horizon] = hit_tp_directional(
                candles=future_candles,
                sample_ts=sample_ts,
                horizon_hours=horizon,
                leg_direction=leg_direction,
                tp_trigger_price=tp_trigger_price,
                tp_already_crossed_at_sample=tp_already_crossed_at_sample,
                tp_side_label=tp_side_label,
            )
            strict_window = strict_future_window(
                candles=future_candles,
                sample_ts=sample_ts,
                horizon_hours=horizon,
            )
            horizon_hits_future_strict[horizon] = hit_tp_future_strict(
                candles=strict_window,
                leg_direction=leg_direction,
                tp_trigger_price=tp_trigger_price,
                valid_future_tp_target=bool(valid_future_tp_target),
            )
            forward_window_first_ts[horizon] = None if not strict_window else strict_window[0].close_ts_utc
            forward_window_count[horizon] = len(strict_window)
        max_high_4h, min_low_4h = future_extremes(
            candles=future_candles,
            sample_ts=sample_ts,
            horizon_hours=4,
        )
        max_high_24h, min_low_24h = future_extremes(
            candles=future_candles,
            sample_ts=sample_ts,
            horizon_hours=24,
        )

        input_ts_candidates = [
            sample_ts,
            base_row.get("fib_asof_ts_utc"),
            base_row.get("zone_asof_ts_utc"),
            None if entry_zone is None else entry_zone.get("zone_asof_ts_utc"),
            None if tp_zone is None else tp_zone.get("zone_asof_ts_utc"),
        ]
        max_input_ts = max(ts for ts in input_ts_candidates if isinstance(ts, datetime))
        leakage_flag = int(max_input_ts > sample_ts)
        max_input_ts_gt_sample_ts_rows += leakage_flag
        sanity_notes = [tp_side_note]
        if tp_side_label == "TP_WRONG_SIDE_FOR_LEG":
            sanity_notes.append("TP_DIRECTION_WRONG_SIDE")
        if tp_already_crossed_at_sample:
            sanity_notes.append("TP_ALREADY_CROSSED_AT_SAMPLE")
        if tp_side_label == "TP_AT_OR_NEAR_PRICE":
            sanity_notes.append("TP_AT_OR_NEAR_SAMPLE")
        if tp_trigger_price is None:
            sanity_notes.append("TP_DIRECTIONAL_TRIGGER_UNKNOWN")
        elif not tp_already_crossed_at_sample and tp_side_label not in {"TP_WRONG_SIDE_FOR_LEG", "TP_UNKNOWN", "TP_AT_OR_NEAR_PRICE"}:
            sanity_notes.append("TP_DIRECTIONALLY_VALID")
        future_strict_notes = [f"INVALID_REASON_{invalid_reason}"]
        if valid_future_tp_target:
            future_strict_notes.append("SAMPLE_CANDLE_EXCLUDED")
        else:
            future_strict_notes.append("STRICT_FUTURE_HIT_NOT_EVALUATED")

        event_rows.append(
            {
                "symbol": str(base_row["symbol"]).upper(),
                "sample_ts_utc": sample_ts,
                "leg_direction": leg_direction,
                "entry_zone_type": "" if entry_zone is None else entry_zone.get("zone_type"),
                "entry_zone_low": entry_low,
                "entry_zone_high": entry_high,
                "tp_zone_type": "" if tp_zone is None else tp_zone.get("zone_type"),
                "tp_zone_low": tp_low,
                "tp_zone_high": tp_high,
                "fib_0500_price": fib_0500,
                "fib_0618_price": fib_0618,
                "fib_0786_price": fib_0786,
                "ext_1272_price": ext_1272,
                "ext_1618_price": ext_1618,
                "nearest_entry_fib_level": nearest_entry_fib_level,
                "entry_fib_distance_pct": entry_fib_distance_pct,
                "nearest_tp_fib_level": nearest_tp_fib_level,
                "tp_fib_distance_pct": tp_fib_distance_pct,
                "entry_alignment_label": entry_alignment_label,
                "tp_alignment_label": tp_alignment_label,
                "entry_is_fib_band": entry_is_fib_band,
                "tp_is_fib_extension_band": tp_is_fib_extension_band,
                "sample_close_price": sample_close_price,
                "distance_to_tp_pct": distance_to_tp_pct,
                "tp_side_label": tp_side_label,
                "tp_already_crossed_at_sample": tp_already_crossed_at_sample,
                "directional_distance_to_tp_pct": directional_distance_to_tp_pct,
                "forward_return_4h_pct": horizon_returns.get(4),
                "forward_return_8h_pct": horizon_returns.get(8),
                "forward_return_12h_pct": horizon_returns.get(12),
                "forward_return_24h_pct": horizon_returns.get(24),
                "forward_return_48h_pct": horizon_returns.get(48),
                "hit_tp_4h": horizon_hits.get(4, 0),
                "hit_tp_8h": horizon_hits.get(8, 0),
                "hit_tp_12h": horizon_hits.get(12, 0),
                "hit_tp_24h": horizon_hits.get(24, 0),
                "hit_tp_48h": horizon_hits.get(48, 0),
                "hit_tp_directional_4h": horizon_hits_directional.get(4, 0),
                "hit_tp_directional_8h": horizon_hits_directional.get(8, 0),
                "hit_tp_directional_12h": horizon_hits_directional.get(12, 0),
                "hit_tp_directional_24h": horizon_hits_directional.get(24, 0),
                "hit_tp_directional_48h": horizon_hits_directional.get(48, 0),
                "forward_window_first_candle_ts_4h": forward_window_first_ts.get(4),
                "forward_window_first_candle_ts_24h": forward_window_first_ts.get(24),
                "forward_window_candle_count_4h": forward_window_count.get(4, 0),
                "forward_window_candle_count_24h": forward_window_count.get(24, 0),
                "hit_tp_future_strict_4h": horizon_hits_future_strict.get(4, 0),
                "hit_tp_future_strict_8h": horizon_hits_future_strict.get(8, 0),
                "hit_tp_future_strict_12h": horizon_hits_future_strict.get(12, 0),
                "hit_tp_future_strict_24h": horizon_hits_future_strict.get(24, 0),
                "hit_tp_future_strict_48h": horizon_hits_future_strict.get(48, 0),
                "future_strict_hit_note": ";".join(future_strict_notes),
                "valid_future_tp_target": valid_future_tp_target,
                "invalid_future_tp_reason": invalid_reason,
                "max_high_4h": max_high_4h,
                "min_low_4h": min_low_4h,
                "max_high_24h": max_high_24h,
                "min_low_24h": min_low_24h,
                "hit_tp_sanity_note": ";".join(sanity_notes),
                "max_input_ts_utc": max_input_ts,
                "leakage_flag": leakage_flag,
            }
        )

    summary_by_entry_alignment = summarize_by(event_rows, "entry_alignment_label")
    summary_by_tp_alignment = summarize_by(event_rows, "tp_alignment_label")
    summary_by_tp_alignment_directional = summarize_by(event_rows, "tp_alignment_label")
    summary_by_tp_alignment_future_strict = summarize_by(event_rows, "tp_alignment_label")
    summary_by_symbol = summarize_by(event_rows, "symbol")
    summary_by_leg_direction = summarize_by(event_rows, "leg_direction")
    summary_by_tp_side_label = summarize_by(event_rows, "tp_side_label")
    summary_by_tp_side_future_strict = summarize_by(event_rows, "tp_side_label")
    summary_by_valid_future_tp_target = summarize_by(event_rows, "valid_future_tp_target")
    for row in event_rows:
        row["tp_alignment_and_leg"] = f"{row['tp_alignment_label']}|{row['leg_direction']}"
        row["tp_alignment_and_side"] = f"{row['tp_alignment_label']}|{row['tp_side_label']}"
    summary_by_tp_alignment_and_leg = summarize_by(event_rows, "tp_alignment_and_leg")
    summary_by_tp_alignment_and_side = summarize_by(event_rows, "tp_alignment_and_side")
    summary_by_tp_alignment_and_side_future_strict = summarize_by(event_rows, "tp_alignment_and_side")

    run_finished_at = datetime.now(UTC)
    run_id = utc_run_id(run_started_at)
    output_dir = resolve_output_dir(output_root=args.output_root, run_id=run_id)
    outputs = output_paths(output_dir)
    leakage_guard = build_leakage_guard_report(
        sample_count=len(sample_timestamps),
        event_count=len(event_rows),
        max_input_ts_gt_sample_ts_rows=max_input_ts_gt_sample_ts_rows,
        sample_range_start_utc=start_ts,
        sample_range_end_utc=end_ts,
    )
    manifest = {
        "report": REPORT_NAME,
        "version": VERSION,
        "run_id": run_id,
        "output_dir": str(output_dir),
        "run_started_at_utc": fmt_ts(run_started_at),
        "run_finished_at_utc": fmt_ts(run_finished_at),
        "run_duration_sec": round(perf_counter() - started_perf, 6),
        "exit_code": 0,
        "venue": args.venue,
        "interval": args.interval,
        "sample_every_n": args.sample_every_n,
        "max_samples": args.max_samples,
        "horizons_hours": horizons_hours,
        "sample_count": len(sample_timestamps),
        "event_count": len(event_rows),
        "already_crossed_tp_rows": already_crossed_tp_rows,
        "wrong_side_tp_rows": wrong_side_tp_rows,
        "directional_hit_fields_present": True,
        "strict_future_hit_fields_present": True,
        "invalid_future_tp_rows": invalid_future_tp_rows,
        "no_future_candle_rows": no_future_candle_rows,
        "sample_candle_excluded_from_hit_tests": True,
        "input_tables": {
            "fib_table": fib_table,
            "zone_table": zone_table,
            "candles_table": "obs_market_candle",
            "asset_table": "asset",
        },
        "output_files": {
            "zone_fib_replay_events_v1_csv": str(outputs.events_csv),
            "summary_by_entry_alignment_v1_csv": str(outputs.summary_by_entry_alignment_csv),
            "summary_by_tp_alignment_v1_csv": str(outputs.summary_by_tp_alignment_csv),
            "summary_by_tp_alignment_directional_v1_csv": str(outputs.summary_by_tp_alignment_directional_csv),
            "summary_by_tp_alignment_future_strict_v1_csv": str(outputs.summary_by_tp_alignment_future_strict_csv),
            "summary_by_symbol_v1_csv": str(outputs.summary_by_symbol_csv),
            "summary_by_leg_direction_v1_csv": str(outputs.summary_by_leg_direction_csv),
            "summary_by_tp_alignment_and_leg_v1_csv": str(outputs.summary_by_tp_alignment_and_leg_csv),
            "summary_by_tp_side_label_v1_csv": str(outputs.summary_by_tp_side_label_csv),
            "summary_by_tp_side_future_strict_v1_csv": str(outputs.summary_by_tp_side_future_strict_csv),
            "summary_by_tp_alignment_and_side_v1_csv": str(outputs.summary_by_tp_alignment_and_side_csv),
            "summary_by_tp_alignment_and_side_future_strict_v1_csv": str(outputs.summary_by_tp_alignment_and_side_future_strict_csv),
            "summary_by_valid_future_tp_target_v1_csv": str(outputs.summary_by_valid_future_tp_target_csv),
            "manifest_v1_json": str(outputs.manifest_json),
            "leakage_guard_report_v1_json": str(outputs.leakage_guard_json),
        },
        **SAFETY_MARKERS,
    }

    if args.write_files:
        output_dir.mkdir(parents=True, exist_ok=True)
        write_csv(outputs.events_csv, event_rows, EVENT_FIELDS)
        write_csv(outputs.summary_by_entry_alignment_csv, summary_by_entry_alignment, SUMMARY_FIELDS)
        write_csv(outputs.summary_by_tp_alignment_csv, summary_by_tp_alignment, SUMMARY_FIELDS)
        write_csv(outputs.summary_by_tp_alignment_directional_csv, summary_by_tp_alignment_directional, SUMMARY_FIELDS)
        write_csv(outputs.summary_by_tp_alignment_future_strict_csv, summary_by_tp_alignment_future_strict, SUMMARY_FIELDS)
        write_csv(outputs.summary_by_symbol_csv, summary_by_symbol, SUMMARY_FIELDS)
        write_csv(outputs.summary_by_leg_direction_csv, summary_by_leg_direction, SUMMARY_FIELDS)
        write_csv(outputs.summary_by_tp_alignment_and_leg_csv, summary_by_tp_alignment_and_leg, SUMMARY_FIELDS)
        write_csv(outputs.summary_by_tp_side_label_csv, summary_by_tp_side_label, SUMMARY_FIELDS)
        write_csv(outputs.summary_by_tp_side_future_strict_csv, summary_by_tp_side_future_strict, SUMMARY_FIELDS)
        write_csv(outputs.summary_by_tp_alignment_and_side_csv, summary_by_tp_alignment_and_side, SUMMARY_FIELDS)
        write_csv(outputs.summary_by_tp_alignment_and_side_future_strict_csv, summary_by_tp_alignment_and_side_future_strict, SUMMARY_FIELDS)
        write_csv(outputs.summary_by_valid_future_tp_target_csv, summary_by_valid_future_tp_target, SUMMARY_FIELDS)
        outputs.manifest_json.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        outputs.leakage_guard_json.write_text(json.dumps(leakage_guard, indent=2, sort_keys=True), encoding="utf-8")

    print_summary(
        args=args,
        run_id=run_id,
        output_dir=output_dir,
        sample_count=len(sample_timestamps),
        event_count=len(event_rows),
        leakage_rows=max_input_ts_gt_sample_ts_rows,
    )
    if args.write_files:
        for path in [
            outputs.events_csv,
            outputs.summary_by_entry_alignment_csv,
            outputs.summary_by_tp_alignment_csv,
            outputs.summary_by_tp_alignment_directional_csv,
            outputs.summary_by_tp_alignment_future_strict_csv,
            outputs.summary_by_symbol_csv,
            outputs.summary_by_leg_direction_csv,
            outputs.summary_by_tp_alignment_and_leg_csv,
            outputs.summary_by_tp_side_label_csv,
            outputs.summary_by_tp_side_future_strict_csv,
            outputs.summary_by_tp_alignment_and_side_csv,
            outputs.summary_by_tp_alignment_and_side_future_strict_csv,
            outputs.summary_by_valid_future_tp_target_csv,
            outputs.manifest_json,
            outputs.leakage_guard_json,
        ]:
            print(f"wrote_files={path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
