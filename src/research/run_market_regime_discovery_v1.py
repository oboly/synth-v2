from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from src.common.db import get_connection
from src.research.run_market_breath_analysis_v1 import (
    INTERVAL_SECONDS,
    add_breadth_and_scores,
    build_base_observation,
    fetch_assets,
    fmt_ts,
    latest_asof_ts,
    parse_ts,
)


REPORT_NAME = "market_regime_discovery_v1"
VERSION = "1.0"
DEFAULT_OUTPUT_ROOT = "data/research/market_regime_discovery_v1"
DEFAULT_RUN_DIR_PREFIX = "run_"

DISCOVERED_SAMPLES_CSV = "discovered_regime_samples_v1.csv"
DISCOVERED_SAMPLES_JSONL = "discovered_regime_samples_v1.jsonl"
SUMMARY_BY_REGIME_CSV = "summary_by_discovered_regime_v1.csv"
REGIME_FEATURE_CENTERS_CSV = "regime_feature_centers_v1.csv"
REGIME_FORWARD_OUTCOMES_CSV = "regime_forward_outcomes_v1.csv"
REGIME_TRANSITION_MATRIX_CSV = "regime_transition_matrix_v1.csv"
COMPARISON_VS_EXISTING_REGIME_CSV = "comparison_discovered_vs_existing_regime_v1.csv"
COMPARISON_VS_CURVE_SANITY_CSV = "comparison_discovered_vs_curve_sanity_v1.csv"
MANIFEST_JSON = "manifest_v1.json"

DEFAULT_LOOKBACK_WINDOWS = [6, 18, 42, 84]
DEFAULT_INTERVAL = "4h"
DEFAULT_SAMPLE_EVERY_N = 6
DEFAULT_N_REGIMES = 6
FORWARD_HOURS = 24
STABLELIKE_SYMBOLS = {
    "USDT",
    "USDC",
    "DAI",
    "FDUSD",
    "TUSD",
    "EURC",
    "USDE",
    "PYUSD",
    "USDP",
    "BUSD",
}

SAFETY_MARKERS = {
    "db_writes": 0,
    "broker_calls": 0,
    "broker_writes": 0,
    "order_submission": 0,
    "live_orders": 0,
}

SAMPLE_OUTPUT_FIELDS = [
    "sample_ts_utc",
    "discovered_regime_id",
    "discovered_regime_label_auto",
    "cluster_distance",
    "btc_return_24h",
    "btc_return_72h",
    "btc_volatility_7d",
    "alt_breadth_positive_pct",
    "alt_equal_weight_return_24h",
    "alt_dispersion",
    "eth_btc_relative_strength",
    "forward_btc_return_24h",
    "forward_alt_basket_return_24h",
    "forward_top_decile_return_24h",
    "forward_bottom_decile_return_24h",
]

SUMMARY_FIELDS = [
    "discovered_regime_id",
    "discovered_regime_label_auto",
    "sample_count",
    "avg_cluster_distance",
    "avg_btc_return_24h",
    "avg_btc_return_72h",
    "avg_btc_volatility_7d",
    "avg_alt_breadth_positive_pct",
    "avg_alt_equal_weight_return_24h",
    "avg_alt_dispersion",
    "avg_eth_btc_relative_strength",
    "avg_forward_btc_return_24h",
    "avg_forward_alt_basket_return_24h",
    "avg_forward_top_decile_return_24h",
    "avg_forward_bottom_decile_return_24h",
]

COMPARISON_FIELDS = [
    "discovered_regime_id",
    "discovered_regime_label_auto",
    "comparison_label",
    "sample_count",
    "sample_pct",
    "avg_forward_btc_return_24h",
    "avg_forward_alt_basket_return_24h",
]


@dataclass(frozen=True)
class Candle:
    asset_id: int
    close_ts_utc: datetime
    open_price: float
    high_price: float
    low_price: float
    close_price: float


@dataclass(frozen=True)
class OutputPaths:
    discovered_samples_csv: Path
    discovered_samples_jsonl: Path
    summary_by_regime_csv: Path
    regime_feature_centers_csv: Path
    regime_forward_outcomes_csv: Path
    regime_transition_matrix_csv: Path
    comparison_vs_existing_regime_csv: Path
    comparison_vs_curve_sanity_csv: Path
    manifest_json: Path


@dataclass(frozen=True)
class SeriesContext:
    candles: list[Candle]
    ts_to_index: dict[datetime, int]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Discover market regimes from market-only historical candles using unsupervised clustering "
            "(research-only, exploratory, not replay-safe predictive use)."
        )
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", default=DEFAULT_INTERVAL)
    parser.add_argument("--start-ts", default=None)
    parser.add_argument("--end-ts", default=None)
    parser.add_argument(
        "--lookback-windows",
        nargs="+",
        default=[str(value) for value in DEFAULT_LOOKBACK_WINDOWS],
        help="Rolling lookback windows in candles. Accepts spaced values or comma-separated groups.",
    )
    parser.add_argument("--sample-every-n", type=int, default=DEFAULT_SAMPLE_EVERY_N)
    parser.add_argument("--max-samples", type=int, default=None, help="Use 0 for unlimited.")
    parser.add_argument("--n-regimes", type=int, default=DEFAULT_N_REGIMES)
    parser.add_argument("--write-files", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--output-root", default=None)
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args(argv)


def parse_int_list(values: list[Any] | None, *, field_name: str) -> list[int]:
    if not values:
        raise ValueError(f"{field_name} must not be empty")
    parsed: list[int] = []
    for value in values:
        raw = str(value).strip()
        if not raw:
            continue
        for piece in raw.split(","):
            token = piece.strip()
            if not token:
                continue
            number = int(token)
            if number <= 0:
                raise ValueError(f"{field_name} values must be > 0")
            parsed.append(number)
    if not parsed:
        raise ValueError(f"{field_name} must not be empty")
    return sorted(dict.fromkeys(parsed))


def utc_run_id(now_utc: datetime) -> str:
    return now_utc.replace(tzinfo=UTC).strftime("%Y%m%dT%H%M%SZ")


def resolve_output_dir(*, output_root: str | None, run_id: str) -> Path:
    root = Path(output_root) if output_root else Path(DEFAULT_OUTPUT_ROOT)
    return root / f"{DEFAULT_RUN_DIR_PREFIX}{run_id}"


def output_paths(output_dir: Path) -> OutputPaths:
    return OutputPaths(
        discovered_samples_csv=output_dir / DISCOVERED_SAMPLES_CSV,
        discovered_samples_jsonl=output_dir / DISCOVERED_SAMPLES_JSONL,
        summary_by_regime_csv=output_dir / SUMMARY_BY_REGIME_CSV,
        regime_feature_centers_csv=output_dir / REGIME_FEATURE_CENTERS_CSV,
        regime_forward_outcomes_csv=output_dir / REGIME_FORWARD_OUTCOMES_CSV,
        regime_transition_matrix_csv=output_dir / REGIME_TRANSITION_MATRIX_CSV,
        comparison_vs_existing_regime_csv=output_dir / COMPARISON_VS_EXISTING_REGIME_CSV,
        comparison_vs_curve_sanity_csv=output_dir / COMPARISON_VS_CURVE_SANITY_CSV,
        manifest_json=output_dir / MANIFEST_JSON,
    )


def json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return fmt_ts(value)
    return value


def format_number(value: float | None, digits: int = 6) -> str:
    if value is None or math.isnan(value):
        return ""
    return f"{value:.{digits}f}"


def as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except Exception:
        return None


def periods_for_hours(interval_code: str, hours: int) -> int:
    seconds = INTERVAL_SECONDS.get(interval_code)
    if seconds is None:
        raise ValueError(f"Unsupported interval: {interval_code}")
    total_seconds = hours * 3600
    if total_seconds % seconds != 0:
        raise ValueError(f"{hours}h is not aligned to interval {interval_code}")
    return total_seconds // seconds


def pct_return(current: float, previous: float) -> float | None:
    if previous <= 0:
        return None
    return (current / previous - 1.0) * 100.0


def mean_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def stddev_or_none(values: list[float]) -> float | None:
    if len(values) < 2:
        return 0.0 if values else None
    avg = sum(values) / len(values)
    variance = sum((value - avg) ** 2 for value in values) / len(values)
    return math.sqrt(variance)


def slice_returns(candles: list[Candle], end_index: int, periods: int) -> list[float]:
    start_index = max(1, end_index - periods + 1)
    values: list[float] = []
    for idx in range(start_index, end_index + 1):
        prev = candles[idx - 1].close_price
        curr = candles[idx].close_price
        ret = pct_return(curr, prev)
        if ret is not None:
            values.append(ret)
    return values


def exact_return(series: SeriesContext, sample_ts: datetime, periods: int) -> float | None:
    idx = series.ts_to_index.get(sample_ts)
    if idx is None or idx < periods:
        return None
    current = series.candles[idx].close_price
    previous = series.candles[idx - periods].close_price
    return pct_return(current, previous)


def forward_return(series: SeriesContext, sample_ts: datetime, periods: int) -> float | None:
    idx = series.ts_to_index.get(sample_ts)
    if idx is None or idx + periods >= len(series.candles):
        return None
    current = series.candles[idx].close_price
    future = series.candles[idx + periods].close_price
    return pct_return(future, current)


def sma_pct(series: SeriesContext, sample_ts: datetime, periods: int) -> float | None:
    idx = series.ts_to_index.get(sample_ts)
    if idx is None or idx + 1 < periods:
        return None
    closes = [row.close_price for row in series.candles[idx - periods + 1 : idx + 1]]
    baseline = sum(closes) / len(closes)
    if baseline <= 0:
        return None
    return (series.candles[idx].close_price / baseline - 1.0) * 100.0


def volatility_pct(series: SeriesContext, sample_ts: datetime, periods: int) -> float | None:
    idx = series.ts_to_index.get(sample_ts)
    if idx is None or idx < periods:
        return None
    trailing = slice_returns(series.candles, idx, periods)
    return stddev_or_none(trailing)


def fetch_sample_timestamps(
    conn: Any,
    *,
    venue: str,
    interval_code: str,
    start_ts: datetime,
    end_ts: datetime,
    sample_every_n: int,
    max_samples: int | None,
) -> list[datetime]:
    if sample_every_n <= 0:
        raise ValueError("--sample-every-n must be > 0")
    assets = fetch_assets(conn)
    btc_asset = next((asset for asset in assets if asset.symbol == "BTC"), None)
    params: list[Any] = [venue, interval_code, start_ts, end_ts]
    asset_filter = ""
    if btc_asset is not None:
        asset_filter = "AND asset_id = %s"
        params.append(btc_asset.asset_id)
    sql = f"""
        SELECT DISTINCT close_ts_utc
        FROM obs_market_candle
        WHERE venue = %s
          AND interval_code = %s
          AND close_ts_utc >= %s
          AND close_ts_utc <= %s
          {asset_filter}
        ORDER BY close_ts_utc
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = list(cur.fetchall())
    timestamps = [row["close_ts_utc"] for row in rows if row.get("close_ts_utc") is not None]
    sampled = timestamps[::sample_every_n]
    if max_samples is not None:
        sampled = sampled[:max_samples]
    return sampled


def fetch_candles_window(
    conn: Any,
    *,
    asset_ids: list[int],
    venue: str,
    interval_code: str,
    start_ts: datetime,
    end_ts: datetime,
) -> dict[int, SeriesContext]:
    if not asset_ids:
        return {}
    placeholders = ", ".join(["%s"] * len(asset_ids))
    sql = f"""
        SELECT
            asset_id,
            close_ts_utc,
            open_price,
            high_price,
            low_price,
            close_price
        FROM obs_market_candle
        WHERE venue = %s
          AND interval_code = %s
          AND close_ts_utc >= %s
          AND close_ts_utc <= %s
          AND asset_id IN ({placeholders})
        ORDER BY asset_id, close_ts_utc
    """
    params: list[Any] = [venue, interval_code, start_ts, end_ts, *asset_ids]
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = list(cur.fetchall())

    grouped: dict[int, list[Candle]] = defaultdict(list)
    for row in rows:
        if row.get("close_price") is None:
            continue
        grouped[int(row["asset_id"])].append(
            Candle(
                asset_id=int(row["asset_id"]),
                close_ts_utc=row["close_ts_utc"],
                open_price=float(row["open_price"]),
                high_price=float(row["high_price"]),
                low_price=float(row["low_price"]),
                close_price=float(row["close_price"]),
            )
        )

    out: dict[int, SeriesContext] = {}
    for asset_id, candles in grouped.items():
        out[asset_id] = SeriesContext(
            candles=candles,
            ts_to_index={candle.close_ts_utc: idx for idx, candle in enumerate(candles)},
        )
    return out


def cluster_label_auto(center: dict[str, float | None]) -> str:
    btc_24 = center.get("btc_return_24h") or 0.0
    breadth = center.get("alt_breadth_positive_pct") or 0.0
    alt_24 = center.get("alt_equal_weight_return_24h") or 0.0
    vol = center.get("btc_volatility_7d") or 0.0
    dispersion = center.get("alt_dispersion") or 0.0
    eth_rs = center.get("eth_btc_relative_strength") or 0.0

    if btc_24 <= -2.0 and breadth <= 35.0:
        return "DISCOVERED_BEAR_DAMAGE"
    if vol >= 4.0 and dispersion >= 5.0:
        return "DISCOVERED_VOLATILE_ROTATION"
    if breadth >= 65.0 and alt_24 >= 1.0 and eth_rs > 0.0:
        return "DISCOVERED_ALT_EXPANSION"
    if btc_24 >= 1.0 and breadth >= 55.0:
        return "DISCOVERED_BROAD_RISK_ON"
    if abs(btc_24) <= 0.75 and vol <= 2.0 and dispersion <= 2.5:
        return "DISCOVERED_COMPRESSION_BALANCE"
    return "DISCOVERED_TRANSITIONAL_MIXED"


def euclidean_distance(point: list[float], center: list[float]) -> float:
    return math.sqrt(sum((left - right) ** 2 for left, right in zip(point, center)))


def standardize_matrix(rows: list[dict[str, Any]], feature_fields: list[str]) -> tuple[list[list[float]], list[float], list[float]]:
    columns: list[list[float]] = []
    means: list[float] = []
    scales: list[float] = []
    for field in feature_fields:
        values = [float(row[field]) for row in rows]
        avg = sum(values) / len(values)
        std = stddev_or_none(values) or 1.0
        if std == 0.0:
            std = 1.0
        columns.append(values)
        means.append(avg)
        scales.append(std)
    matrix: list[list[float]] = []
    for row in rows:
        matrix.append([(float(row[field]) - means[idx]) / scales[idx] for idx, field in enumerate(feature_fields)])
    return matrix, means, scales


def initialize_centroids(points: list[list[float]], cluster_count: int) -> list[list[float]]:
    ordered = sorted(range(len(points)), key=lambda idx: (sum(points[idx]), points[idx][0], idx))
    if cluster_count == 1:
        return [list(points[ordered[len(ordered) // 2]])]
    centroids: list[list[float]] = []
    for offset in range(cluster_count):
        pos = round(offset * (len(ordered) - 1) / max(cluster_count - 1, 1))
        centroids.append(list(points[ordered[pos]]))
    return centroids


def kmeans(points: list[list[float]], cluster_count: int, *, max_iters: int = 50) -> tuple[list[int], list[list[float]], list[float]]:
    centroids = initialize_centroids(points, cluster_count)
    assignments = [-1] * len(points)

    for _ in range(max_iters):
        changed = False
        for idx, point in enumerate(points):
            nearest = min(range(cluster_count), key=lambda cluster_idx: euclidean_distance(point, centroids[cluster_idx]))
            if assignments[idx] != nearest:
                assignments[idx] = nearest
                changed = True

        grouped: dict[int, list[list[float]]] = defaultdict(list)
        for idx, cluster_idx in enumerate(assignments):
            grouped[cluster_idx].append(points[idx])

        new_centroids: list[list[float]] = []
        for cluster_idx in range(cluster_count):
            group = grouped.get(cluster_idx)
            if not group:
                new_centroids.append(list(centroids[cluster_idx]))
                continue
            cols = zip(*group)
            new_centroids.append([sum(values) / len(group) for values in cols])
        centroids = new_centroids
        if not changed:
            break

    distances = [euclidean_distance(points[idx], centroids[assignments[idx]]) for idx in range(len(points))]
    return assignments, centroids, distances


def center_to_raw(center: list[float], means: list[float], scales: list[float], feature_fields: list[str]) -> dict[str, float]:
    return {
        field: means[idx] + center[idx] * scales[idx]
        for idx, field in enumerate(feature_fields)
    }


def current_curve_sanity_from_btc_row(row: dict[str, Any] | None) -> str:
    if row is None:
        return "UNKNOWN"
    momentum = as_float(row.get("momentum_score")) or 0.0
    ret3 = as_float(row.get("return_3")) or 0.0
    phase = str(row.get("market_breath_phase") or "").upper()
    if phase == "COLLAPSE_RESET" or momentum < -10.0:
        return "CURVE_DOWN_PRESSURE"
    if momentum > 20.0 and ret3 > 0.0:
        return "CURVE_UP_CONFIRMED"
    if abs(momentum) <= 10.0:
        return "CURVE_WEAK"
    return "CURVE_NEUTRAL"


def discovered_summary_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["discovered_regime_id"]), str(row["discovered_regime_label_auto"]))].append(row)

    out: list[dict[str, Any]] = []
    for regime_key in sorted(grouped):
        sample_rows = grouped[regime_key]
        out.append(
            {
                "discovered_regime_id": regime_key[0],
                "discovered_regime_label_auto": regime_key[1],
                "sample_count": len(sample_rows),
                "avg_cluster_distance": format_number(mean_or_none(numeric_values(sample_rows, "cluster_distance"))),
                "avg_btc_return_24h": format_number(mean_or_none(numeric_values(sample_rows, "btc_return_24h"))),
                "avg_btc_return_72h": format_number(mean_or_none(numeric_values(sample_rows, "btc_return_72h"))),
                "avg_btc_volatility_7d": format_number(mean_or_none(numeric_values(sample_rows, "btc_volatility_7d"))),
                "avg_alt_breadth_positive_pct": format_number(mean_or_none(numeric_values(sample_rows, "alt_breadth_positive_pct"))),
                "avg_alt_equal_weight_return_24h": format_number(mean_or_none(numeric_values(sample_rows, "alt_equal_weight_return_24h"))),
                "avg_alt_dispersion": format_number(mean_or_none(numeric_values(sample_rows, "alt_dispersion"))),
                "avg_eth_btc_relative_strength": format_number(mean_or_none(numeric_values(sample_rows, "eth_btc_relative_strength"))),
                "avg_forward_btc_return_24h": format_number(mean_or_none(numeric_values(sample_rows, "forward_btc_return_24h"))),
                "avg_forward_alt_basket_return_24h": format_number(mean_or_none(numeric_values(sample_rows, "forward_alt_basket_return_24h"))),
                "avg_forward_top_decile_return_24h": format_number(mean_or_none(numeric_values(sample_rows, "forward_top_decile_return_24h"))),
                "avg_forward_bottom_decile_return_24h": format_number(mean_or_none(numeric_values(sample_rows, "forward_bottom_decile_return_24h"))),
            }
        )
    return out


def regime_feature_centers_rows(
    raw_centers: dict[int, dict[str, float]],
    labels: dict[int, str],
    counts: dict[int, int],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for regime_id in sorted(raw_centers):
        center = raw_centers[regime_id]
        out.append(
            {
                "discovered_regime_id": str(regime_id),
                "discovered_regime_label_auto": labels[regime_id],
                "sample_count": counts.get(regime_id, 0),
                **{field: format_number(center.get(field)) for field in center},
            }
        )
    return out


def transition_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(rows) < 2:
        return []
    ordered = sorted(rows, key=lambda row: str(row["sample_ts_utc"]))
    counts: dict[tuple[str, str], int] = defaultdict(int)
    from_totals: dict[str, int] = defaultdict(int)
    for idx in range(len(ordered) - 1):
        left = str(ordered[idx]["discovered_regime_id"])
        right = str(ordered[idx + 1]["discovered_regime_id"])
        counts[(left, right)] += 1
        from_totals[left] += 1

    out: list[dict[str, Any]] = []
    for key in sorted(counts):
        left, right = key
        count = counts[key]
        total = from_totals[left]
        out.append(
            {
                "from_discovered_regime_id": left,
                "to_discovered_regime_id": right,
                "transition_count": count,
                "transition_pct": format_number(count / total * 100.0 if total else None),
            }
        )
    return out


def comparison_rows(
    rows: list[dict[str, Any]],
    *,
    comparison_field: str,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    total = len(rows)
    for row in rows:
        label = str(row.get(comparison_field) or "")
        if not label:
            continue
        key = (
            str(row["discovered_regime_id"]),
            str(row["discovered_regime_label_auto"]),
            label,
        )
        grouped[key].append(row)

    out: list[dict[str, Any]] = []
    for key in sorted(grouped):
        sample_rows = grouped[key]
        out.append(
            {
                "discovered_regime_id": key[0],
                "discovered_regime_label_auto": key[1],
                "comparison_label": key[2],
                "sample_count": len(sample_rows),
                "sample_pct": format_number(len(sample_rows) / total * 100.0 if total else None),
                "avg_forward_btc_return_24h": format_number(mean_or_none(numeric_values(sample_rows, "forward_btc_return_24h"))),
                "avg_forward_alt_basket_return_24h": format_number(
                    mean_or_none(numeric_values(sample_rows, "forward_alt_basket_return_24h"))
                ),
            }
        )
    return out


def numeric_values(rows: list[dict[str, Any]], field: str) -> list[float]:
    out: list[float] = []
    for row in rows:
        value = as_float(row.get(field))
        if value is not None:
            out.append(value)
    return out


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=True, default=json_default) + "\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True, default=json_default) + "\n",
        encoding="utf-8",
    )


def build_existing_market_label_rows(
    *,
    sample_ts: datetime,
    assets: list[Any],
    series_by_asset: dict[int, SeriesContext],
    venue: str,
    interval_code: str,
    lookback_candles: int,
) -> tuple[str, str]:
    btc_series = next((series_by_asset.get(asset.asset_id) for asset in assets if asset.symbol == "BTC"), None)
    if btc_series is None:
        return "UNKNOWN:UNKNOWN", "UNKNOWN"

    btc_r6 = exact_return(btc_series, sample_ts, 6)
    btc_r12 = exact_return(btc_series, sample_ts, 12)
    rows: list[dict[str, Any]] = []
    for asset in assets:
        series = series_by_asset.get(asset.asset_id)
        if series is None:
            continue
        idx = series.ts_to_index.get(sample_ts)
        if idx is None:
            continue
        candles = series.candles[max(0, idx - lookback_candles + 1) : idx + 1]
        rows.append(
            build_base_observation(
                asset=asset,
                candles=candles,
                venue=venue,
                interval_code=interval_code,
                lookback_candles=lookback_candles,
                asof_ts=sample_ts,
                btc_r6=btc_r6,
                btc_r12=btc_r12,
            )
        )
    observations = add_breadth_and_scores(rows, lookback_candles)
    btc_row = next((row for row in observations if str(row.get("symbol") or "").upper() == "BTC"), None)
    if btc_row is None:
        return "UNKNOWN:UNKNOWN", "UNKNOWN"
    phase = str(btc_row.get("market_breath_phase") or "UNKNOWN").upper()
    state = str(btc_row.get("market_breath_state") or "UNKNOWN").upper()
    return f"{phase}:{state}", current_curve_sanity_from_btc_row(btc_row)


def build_manifest(
    *,
    args: argparse.Namespace,
    run_id: str,
    output_dir: Path,
    sample_count: int,
    actual_n_regimes: int,
    output_paths_map: OutputPaths,
    start_ts: datetime,
    end_ts: datetime,
    run_started_at: datetime,
    run_finished_at: datetime,
) -> dict[str, Any]:
    duration = (run_finished_at - run_started_at).total_seconds()
    return {
        "report": REPORT_NAME,
        "version": VERSION,
        "run_id": run_id,
        "output_dir": str(output_dir),
        "run_started_at_utc": fmt_ts(run_started_at.replace(tzinfo=None)),
        "run_finished_at_utc": fmt_ts(run_finished_at.replace(tzinfo=None)),
        "run_duration_sec": round(duration, 6),
        "venue": args.venue,
        "interval_code": args.interval,
        "start_ts": fmt_ts(start_ts),
        "end_ts": fmt_ts(end_ts),
        "lookback_windows": [int(value) for value in args.lookback_windows],
        "sample_every_n": int(args.sample_every_n),
        "max_samples": None if args.max_samples is None else int(args.max_samples),
        "requested_n_regimes": int(args.n_regimes),
        "actual_n_regimes": int(actual_n_regimes),
        "sample_count": int(sample_count),
        "wrote_files": bool(args.write_files),
        "exploratory_only": True,
        "predictive_replay_safe": False,
        "paper_advice_used": False,
        "account_tables_used": False,
        "existing_regime_labels_used_as_input": False,
        "aplus_labels_used_as_input": False,
        "output_paths": {
            "discovered_samples_csv": str(output_paths_map.discovered_samples_csv),
            "discovered_samples_jsonl": str(output_paths_map.discovered_samples_jsonl),
            "summary_by_regime_csv": str(output_paths_map.summary_by_regime_csv),
            "regime_feature_centers_csv": str(output_paths_map.regime_feature_centers_csv),
            "regime_forward_outcomes_csv": str(output_paths_map.regime_forward_outcomes_csv),
            "regime_transition_matrix_csv": str(output_paths_map.regime_transition_matrix_csv),
            "comparison_vs_existing_regime_csv": str(output_paths_map.comparison_vs_existing_regime_csv),
            "comparison_vs_curve_sanity_csv": str(output_paths_map.comparison_vs_curve_sanity_csv),
            "manifest_json": str(output_paths_map.manifest_json),
        },
        "notes": [
            "Clusters are discovered from market-only historical data without existing regime labels as input.",
            "Existing regime and curve sanity labels are joined only after clustering for comparison outputs.",
            "V1 may use full selected history for cluster discovery and is not replay-safe predictive logic.",
        ],
        **SAFETY_MARKERS,
    }


def render_table(manifest: dict[str, Any], summary_rows: list[dict[str, Any]]) -> str:
    lines = [
        f"[RUN][ID] {manifest['run_id']}",
        f"[RUN][OUT_DIR] {manifest['output_dir']}",
        f"report={REPORT_NAME} version={VERSION}",
        "scope=research-only market-only exploratory discovery",
        "inputs=obs_market_candle asset no_paper_advice no_aplus no_account no_broker",
        "existing_labels_input=false existing_labels_joined_only_after_clustering=true",
        "db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0",
        f"venue={manifest['venue']} interval={manifest['interval_code']}",
        (
            f"start_ts={manifest['start_ts']} end_ts={manifest['end_ts']} sample_count={manifest['sample_count']} "
            f"requested_n_regimes={manifest['requested_n_regimes']} actual_n_regimes={manifest['actual_n_regimes']}"
        ),
        "",
        "--- summary by discovered regime ---",
    ]
    for row in summary_rows:
        lines.append(
            "  "
            f"id={row['discovered_regime_id']} label={row['discovered_regime_label_auto']} "
            f"count={row['sample_count']} avg_btc_24h={row['avg_btc_return_24h']} "
            f"avg_alt_24h={row['avg_alt_equal_weight_return_24h']} "
            f"avg_fwd_btc_24h={row['avg_forward_btc_return_24h']}"
        )
    lines.append("")
    lines.append(f"wrote_files={manifest['wrote_files']}")
    if manifest["wrote_files"]:
        for key, value in manifest["output_paths"].items():
            lines.append(f"  wrote_file[{key}]={value}")
    lines.append("[DONE] db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    args.lookback_windows = parse_int_list(args.lookback_windows, field_name="--lookback-windows")
    if args.max_samples == 0:
        args.max_samples = None
    if args.interval not in INTERVAL_SECONDS:
        raise ValueError(f"Unsupported interval: {args.interval}")
    if args.sample_every_n <= 0:
        raise ValueError("--sample-every-n must be > 0")
    if args.max_samples is not None and args.max_samples < 0:
        raise ValueError("--max-samples must be >= 0 when provided")
    if args.n_regimes <= 0:
        raise ValueError("--n-regimes must be > 0")

    run_started_at = datetime.now(UTC)
    run_id = utc_run_id(run_started_at)
    output_dir = resolve_output_dir(output_root=args.output_root, run_id=run_id)
    paths = output_paths(output_dir)

    interval_seconds = INTERVAL_SECONDS[args.interval]
    periods_24h = periods_for_hours(args.interval, 24)
    periods_72h = periods_for_hours(args.interval, 72)
    periods_7d = periods_for_hours(args.interval, 168)
    max_window = max(args.lookback_windows + [periods_24h, periods_72h, periods_7d, 120])

    conn = get_connection()
    try:
        latest_ts = latest_asof_ts(conn, args.venue, args.interval)
        default_end = latest_ts - timedelta(hours=FORWARD_HOURS)
        end_ts = parse_ts(args.end_ts) if args.end_ts else default_end
        start_ts = parse_ts(args.start_ts) if args.start_ts else end_ts - timedelta(days=180)
        if start_ts > end_ts:
            raise ValueError("--start-ts must be <= --end-ts")

        sample_timestamps = fetch_sample_timestamps(
            conn,
            venue=args.venue,
            interval_code=args.interval,
            start_ts=start_ts,
            end_ts=end_ts,
            sample_every_n=int(args.sample_every_n),
            max_samples=args.max_samples,
        )
        if not sample_timestamps:
            raise RuntimeError("No sample timestamps found for the requested window")

        assets = fetch_assets(conn)
        asset_ids = [asset.asset_id for asset in assets]
        history_start = start_ts - timedelta(seconds=interval_seconds * (max_window + 2))
        future_end = end_ts + timedelta(hours=FORWARD_HOURS)
        series_by_asset = fetch_candles_window(
            conn,
            asset_ids=asset_ids,
            venue=args.venue,
            interval_code=args.interval,
            start_ts=history_start,
            end_ts=future_end,
        )
        conn.rollback()
    finally:
        conn.close()

    asset_by_symbol = {asset.symbol: asset for asset in assets}
    btc_asset = asset_by_symbol.get("BTC")
    eth_asset = asset_by_symbol.get("ETH")
    if btc_asset is None or eth_asset is None:
        raise RuntimeError("BTC and ETH candles are required for market regime discovery v1")

    btc_series = series_by_asset.get(btc_asset.asset_id)
    eth_series = series_by_asset.get(eth_asset.asset_id)
    if btc_series is None or eth_series is None:
        raise RuntimeError("BTC and ETH candle series are required for market regime discovery v1")

    alt_assets = [
        asset
        for asset in assets
        if asset.symbol not in {"BTC", "ETH"} and asset.symbol not in STABLELIKE_SYMBOLS and asset.asset_id in series_by_asset
    ]

    short_window = args.lookback_windows[0]
    long_window = args.lookback_windows[-1]
    medium_window = args.lookback_windows[min(1, len(args.lookback_windows) - 1)]

    feature_rows: list[dict[str, Any]] = []
    for sample_ts in sample_timestamps:
        btc_return_24h = exact_return(btc_series, sample_ts, periods_24h)
        btc_return_72h = exact_return(btc_series, sample_ts, periods_72h)
        btc_vol_7d = volatility_pct(btc_series, sample_ts, periods_7d)
        btc_sma_short = sma_pct(btc_series, sample_ts, short_window)
        btc_sma_long = sma_pct(btc_series, sample_ts, long_window)
        btc_vol_short = volatility_pct(btc_series, sample_ts, short_window)
        btc_vol_long = volatility_pct(btc_series, sample_ts, long_window)
        eth_return_24h = exact_return(eth_series, sample_ts, periods_24h)
        eth_return_72h = exact_return(eth_series, sample_ts, periods_72h)

        alt_returns_24h: list[float] = []
        alt_returns_72h: list[float] = []
        alt_forward_24h: list[tuple[str, float, float]] = []
        for asset in alt_assets:
            series = series_by_asset[asset.asset_id]
            current_24h = exact_return(series, sample_ts, periods_24h)
            current_72h = exact_return(series, sample_ts, periods_72h)
            future_24h = forward_return(series, sample_ts, periods_24h)
            if current_24h is not None:
                alt_returns_24h.append(current_24h)
            if current_72h is not None:
                alt_returns_72h.append(current_72h)
            if current_24h is not None and future_24h is not None:
                alt_forward_24h.append((asset.symbol, current_24h, future_24h))

        if (
            btc_return_24h is None
            or btc_return_72h is None
            or btc_vol_7d is None
            or btc_sma_short is None
            or btc_sma_long is None
            or btc_vol_short is None
            or btc_vol_long is None
            or eth_return_24h is None
            or eth_return_72h is None
            or len(alt_returns_24h) < 10
            or len(alt_returns_72h) < 10
            or not alt_forward_24h
        ):
            continue

        breadth_24h = sum(1 for value in alt_returns_24h if value > 0.0) / len(alt_returns_24h) * 100.0
        breadth_72h = sum(1 for value in alt_returns_72h if value > 0.0) / len(alt_returns_72h) * 100.0
        alt_eq_24h = mean_or_none(alt_returns_24h)
        alt_eq_72h = mean_or_none(alt_returns_72h)
        alt_dispersion = stddev_or_none(alt_returns_24h)
        eth_btc_rs = ((eth_return_24h - btc_return_24h) + (eth_return_72h - btc_return_72h)) / 2.0
        btc_vol_ratio = btc_vol_short / btc_vol_long if btc_vol_long and btc_vol_long > 0 else None
        breadth_impulse = breadth_24h - breadth_72h
        alt_return_impulse = (alt_eq_24h or 0.0) - (alt_eq_72h or 0.0)

        ranked_alts = sorted(alt_forward_24h, key=lambda row: (row[1], row[0]), reverse=True)
        decile_size = max(1, len(ranked_alts) // 10)
        top_decile = ranked_alts[:decile_size]
        bottom_decile = ranked_alts[-decile_size:]

        feature_row = {
            "sample_ts_utc": fmt_ts(sample_ts),
            "btc_return_24h": btc_return_24h,
            "btc_return_72h": btc_return_72h,
            "btc_volatility_7d": btc_vol_7d,
            "alt_breadth_positive_pct": breadth_24h,
            "alt_equal_weight_return_24h": alt_eq_24h,
            "alt_dispersion": alt_dispersion,
            "eth_btc_relative_strength": eth_btc_rs,
            "forward_btc_return_24h": forward_return(btc_series, sample_ts, periods_24h),
            "forward_alt_basket_return_24h": mean_or_none([row[2] for row in alt_forward_24h]),
            "forward_top_decile_return_24h": mean_or_none([row[2] for row in top_decile]),
            "forward_bottom_decile_return_24h": mean_or_none([row[2] for row in bottom_decile]),
            "feature_btc_price_vs_sma_short_pct": btc_sma_short,
            "feature_btc_price_vs_sma_long_pct": btc_sma_long,
            "feature_btc_volatility_ratio_short_long": btc_vol_ratio,
            "feature_breadth_impulse_pct": breadth_impulse,
            "feature_alt_return_impulse_pct": alt_return_impulse,
        }
        if any(feature_row.get(field) is None for field in [
            "forward_btc_return_24h",
            "forward_alt_basket_return_24h",
            "forward_top_decile_return_24h",
            "forward_bottom_decile_return_24h",
            "feature_btc_volatility_ratio_short_long",
        ]):
            continue
        feature_rows.append(feature_row)

    if not feature_rows:
        raise RuntimeError("No valid regime discovery samples were produced")

    feature_fields = [
        "btc_return_24h",
        "btc_return_72h",
        "btc_volatility_7d",
        "alt_breadth_positive_pct",
        "alt_equal_weight_return_24h",
        "alt_dispersion",
        "eth_btc_relative_strength",
        "feature_btc_price_vs_sma_short_pct",
        "feature_btc_price_vs_sma_long_pct",
        "feature_btc_volatility_ratio_short_long",
        "feature_breadth_impulse_pct",
        "feature_alt_return_impulse_pct",
    ]
    cluster_count = min(int(args.n_regimes), len(feature_rows))
    matrix, means, scales = standardize_matrix(feature_rows, feature_fields)
    assignments, centroids, distances = kmeans(matrix, cluster_count)

    raw_centers_by_old = {
        idx: center_to_raw(centroids[idx], means, scales, feature_fields)
        for idx in range(cluster_count)
    }
    ordered_old_cluster_ids = sorted(
        raw_centers_by_old,
        key=lambda idx: (
            raw_centers_by_old[idx].get("btc_return_24h", 0.0),
            raw_centers_by_old[idx].get("alt_breadth_positive_pct", 0.0),
            raw_centers_by_old[idx].get("alt_equal_weight_return_24h", 0.0),
        ),
        reverse=True,
    )
    regime_id_map = {old_idx: new_idx + 1 for new_idx, old_idx in enumerate(ordered_old_cluster_ids)}
    raw_centers = {regime_id_map[old_idx]: raw_centers_by_old[old_idx] for old_idx in raw_centers_by_old}
    labels_by_regime = {regime_id: cluster_label_auto(raw_centers[regime_id]) for regime_id in raw_centers}

    discovered_rows: list[dict[str, Any]] = []
    counts_by_regime: dict[int, int] = defaultdict(int)
    for idx, row in enumerate(feature_rows):
        regime_id = regime_id_map[assignments[idx]]
        counts_by_regime[regime_id] += 1
        discovered_rows.append(
            {
                "sample_ts_utc": row["sample_ts_utc"],
                "discovered_regime_id": str(regime_id),
                "discovered_regime_label_auto": labels_by_regime[regime_id],
                "cluster_distance": format_number(distances[idx]),
                "btc_return_24h": format_number(row["btc_return_24h"]),
                "btc_return_72h": format_number(row["btc_return_72h"]),
                "btc_volatility_7d": format_number(row["btc_volatility_7d"]),
                "alt_breadth_positive_pct": format_number(row["alt_breadth_positive_pct"]),
                "alt_equal_weight_return_24h": format_number(row["alt_equal_weight_return_24h"]),
                "alt_dispersion": format_number(row["alt_dispersion"]),
                "eth_btc_relative_strength": format_number(row["eth_btc_relative_strength"]),
                "forward_btc_return_24h": format_number(row["forward_btc_return_24h"]),
                "forward_alt_basket_return_24h": format_number(row["forward_alt_basket_return_24h"]),
                "forward_top_decile_return_24h": format_number(row["forward_top_decile_return_24h"]),
                "forward_bottom_decile_return_24h": format_number(row["forward_bottom_decile_return_24h"]),
            }
        )

    comparison_enriched_rows: list[dict[str, Any]] = []
    comparison_lookback = max(120, long_window, periods_72h)
    for row in discovered_rows:
        sample_ts = parse_ts(str(row["sample_ts_utc"]))
        existing_regime_label, curve_sanity_label = build_existing_market_label_rows(
            sample_ts=sample_ts,
            assets=assets,
            series_by_asset=series_by_asset,
            venue=args.venue,
            interval_code=args.interval,
            lookback_candles=comparison_lookback,
        )
        enriched = dict(row)
        enriched["existing_market_regime_label"] = existing_regime_label
        enriched["existing_curve_sanity_label"] = curve_sanity_label
        comparison_enriched_rows.append(enriched)

    summary_rows = discovered_summary_rows(discovered_rows)
    center_rows = regime_feature_centers_rows(raw_centers, labels_by_regime, counts_by_regime)
    forward_rows = [
        {
            key: row[key]
            for key in [
                "discovered_regime_id",
                "discovered_regime_label_auto",
                "sample_count",
                "avg_forward_btc_return_24h",
                "avg_forward_alt_basket_return_24h",
                "avg_forward_top_decile_return_24h",
                "avg_forward_bottom_decile_return_24h",
            ]
        }
        for row in summary_rows
    ]
    transition_matrix_rows = transition_rows(discovered_rows)
    comparison_regime_rows = comparison_rows(
        comparison_enriched_rows,
        comparison_field="existing_market_regime_label",
    )
    comparison_curve_rows = comparison_rows(
        comparison_enriched_rows,
        comparison_field="existing_curve_sanity_label",
    )

    run_finished_at = datetime.now(UTC)
    manifest = build_manifest(
        args=args,
        run_id=run_id,
        output_dir=output_dir,
        sample_count=len(discovered_rows),
        actual_n_regimes=len(raw_centers),
        output_paths_map=paths,
        start_ts=start_ts,
        end_ts=end_ts,
        run_started_at=run_started_at,
        run_finished_at=run_finished_at,
    )

    if args.write_files:
        write_csv(paths.discovered_samples_csv, discovered_rows, SAMPLE_OUTPUT_FIELDS)
        write_jsonl(paths.discovered_samples_jsonl, discovered_rows)
        write_csv(paths.summary_by_regime_csv, summary_rows, SUMMARY_FIELDS)
        if center_rows:
            center_fields = list(center_rows[0].keys())
        else:
            center_fields = ["discovered_regime_id", "discovered_regime_label_auto", "sample_count"]
        write_csv(paths.regime_feature_centers_csv, center_rows, center_fields)
        write_csv(paths.regime_forward_outcomes_csv, forward_rows, list(forward_rows[0].keys()) if forward_rows else SUMMARY_FIELDS)
        write_csv(
            paths.regime_transition_matrix_csv,
            transition_matrix_rows,
            ["from_discovered_regime_id", "to_discovered_regime_id", "transition_count", "transition_pct"],
        )
        write_csv(paths.comparison_vs_existing_regime_csv, comparison_regime_rows, COMPARISON_FIELDS)
        write_csv(paths.comparison_vs_curve_sanity_csv, comparison_curve_rows, COMPARISON_FIELDS)
        write_json(paths.manifest_json, manifest)

    if args.output == "json":
        print(f"[RUN][ID] {manifest['run_id']}")
        print(f"[RUN][OUT_DIR] {manifest['output_dir']}")
        if manifest["wrote_files"]:
            for key, value in manifest["output_paths"].items():
                print(f"wrote_file[{key}]={value}")
        print(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True, default=json_default))
    else:
        print(render_table(manifest, summary_rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
