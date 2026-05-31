from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from src.common.db import get_connection


REPORT_NAME = "canonical_fib_zone_map_writer_preview_v1"
REPORT_VERSION = "0.1"
DEFAULT_OUTPUT_DIR = Path("data/research/canonical_fib_zone_map_writer_preview_v1")
MAP_VERSION = "canonical_fib_zone_map_v1"
DEC_PRICE = Decimal("0.000000000001")
DEC_PCT = Decimal("0.00000001")
BUFFER_PCT = Decimal("0.05")
ENTRY_LOW_RETRACE = Decimal("0.618")
ENTRY_HIGH_RETRACE = Decimal("0.382")
SUPPORT_LOW_RETRACE = Decimal("0.786")
SUPPORT_HIGH_RETRACE = Decimal("0.618")
TARGET_T1_MULTIPLIER = Decimal("1.272")
TARGET_T2_MULTIPLIER = Decimal("1.618")
TARGET_EXTENSION_MULTIPLIER = Decimal("2.618")
INTERVAL_DELTAS = {
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
    "1w": timedelta(days=7),
}
FRESHNESS_MULTIPLIERS = {
    "15m": (Decimal("1.5"), Decimal("4.0")),
    "1h": (Decimal("1.5"), Decimal("4.0")),
    "4h": (Decimal("1.5"), Decimal("4.0")),
    "1d": (Decimal("1.5"), Decimal("4.0")),
    "1w": (Decimal("1.5"), Decimal("4.0")),
}
SWING_PCT_BAND_ORDER = ("<8", "8-25", "25-60", ">=60", "UNKNOWN")


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
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview deterministic market-only canonical fib/zone map rows from public candles."
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--quote", default="EUR")
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--lookback-candles", type=int, default=180)
    parser.add_argument("--swing-window", type=int, default=5)
    parser.add_argument("--limit-assets", type=int, default=80)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--write-files", action="store_true")
    parser.add_argument("--write-db", action="store_true", help="Not supported in v1 preview.")
    parser.add_argument("--output", choices=("summary", "json"), default="summary")
    return parser.parse_args(argv)


def fmt_ts(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    else:
        value = value.astimezone(UTC)
    return value.isoformat().replace("+00:00", "Z")


def d(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    text = str(value).strip()
    if not text:
        return None
    return Decimal(text)


def q_price(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return str(value.quantize(DEC_PRICE, rounding=ROUND_HALF_UP))


def q_pct(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return str(value.quantize(DEC_PCT, rounding=ROUND_HALF_UP))


def now_utc() -> datetime:
    return datetime.now(UTC)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=True) + "\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


def fetch_all_dicts(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    try:
        cursor = conn.cursor(dictionary=True)
    except TypeError:
        cursor = conn.cursor()
    try:
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        if not rows:
            return []
        if isinstance(rows[0], dict):
            return [dict(row) for row in rows]
        columns = [str(desc[0]) for desc in cursor.description or []]
        return [dict(zip(columns, row)) for row in rows]
    finally:
        try:
            cursor.close()
        except Exception:
            pass


def try_query(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    try:
        return fetch_all_dicts(conn, sql, params)
    except Exception:
        return []


def table_columns(conn: Any, table_name: str) -> set[str]:
    rows = try_query(
        conn,
        "SELECT column_name FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = %s",
        (table_name,),
    )
    return {str(row["column_name"]) for row in rows}


def fetch_assets(conn: Any, *, quote: str, limit_assets: int) -> list[AssetRef]:
    columns = table_columns(conn, "asset")
    where: list[str] = []
    params: list[Any] = []
    if "is_enabled" in columns:
        where.append("is_enabled = 1")
    if "quote_asset" in columns:
        where.append("UPPER(quote_asset) = UPPER(%s)")
        params.append(quote.upper())
    elif "quote_currency" in columns:
        where.append("UPPER(quote_currency) = UPPER(%s)")
        params.append(quote.upper())
    sql = "SELECT asset_id, symbol FROM asset"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY symbol ASC LIMIT %s"
    params.append(int(limit_assets))
    rows = try_query(conn, sql, tuple(params))
    return [AssetRef(asset_id=int(row["asset_id"]), symbol=str(row["symbol"]).upper()) for row in rows if row.get("symbol")]


def fetch_recent_candles(
    conn: Any,
    *,
    assets: list[AssetRef],
    venue: str,
    interval: str,
    lookback_candles: int,
) -> dict[str, list[Candle]]:
    if not assets:
        return {}
    placeholders = ",".join(["%s"] * len(assets))
    queries = (
        (
            f"""
            SELECT c.asset_id, a.symbol, c.open_ts_utc, c.close_ts_utc, c.open_price, c.high_price, c.low_price, c.close_price
            FROM obs_market_candle c
            JOIN asset a ON a.asset_id = c.asset_id
            WHERE c.venue = %s
              AND c.interval_code = %s
              AND c.asset_id IN ({placeholders})
            ORDER BY c.asset_id ASC, c.close_ts_utc DESC
            """,
            (venue, interval, *[asset.asset_id for asset in assets]),
        ),
        (
            f"""
            SELECT c.asset_id, a.symbol, c.open_ts_utc, c.close_ts_utc, c.open_price, c.high_price, c.low_price, c.close_price
            FROM obs_market_candle c
            JOIN asset a ON a.id = c.asset_id
            WHERE c.venue = %s
              AND c.interval_code = %s
              AND c.asset_id IN ({placeholders})
            ORDER BY c.asset_id ASC, c.close_ts_utc DESC
            """,
            (venue, interval, *[asset.asset_id for asset in assets]),
        ),
    )
    rows: list[dict[str, Any]] = []
    for sql, params in queries:
        rows = try_query(conn, sql, params)
        if rows:
            break
    grouped: dict[str, list[Candle]] = {asset.symbol: [] for asset in assets}
    counts: dict[str, int] = {}
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
                open_price=d(row["open_price"]) or Decimal("0"),
                high_price=d(row["high_price"]) or Decimal("0"),
                low_price=d(row["low_price"]) or Decimal("0"),
                close_price=d(row["close_price"]) or Decimal("0"),
            )
        )
        counts[symbol] = taken + 1
    return {symbol: list(reversed(items)) for symbol, items in grouped.items()}


def pct_move(base: Decimal, other: Decimal) -> Decimal | None:
    if base <= 0:
        return None
    return ((other / base) - Decimal("1")) * Decimal("100")


def is_pivot_low(candles: list[Candle], index: int, window: int) -> bool:
    low = candles[index].low_price
    start = max(0, index - window)
    end = min(len(candles), index + window + 1)
    return all(low <= candles[i].low_price for i in range(start, end))


def is_pivot_high(candles: list[Candle], index: int, window: int) -> bool:
    high = candles[index].high_price
    start = max(0, index - window)
    end = min(len(candles), index + window + 1)
    return all(high >= candles[i].high_price for i in range(start, end))


def pivot_indices(candles: list[Candle], window: int) -> tuple[list[int], list[int]]:
    if len(candles) < (window * 2 + 1):
        return [], []
    lows: list[int] = []
    highs: list[int] = []
    for index in range(window, len(candles) - window):
        if is_pivot_low(candles, index, window):
            lows.append(index)
        if is_pivot_high(candles, index, window):
            highs.append(index)
    return lows, highs


def classify_freshness(interval: str, latest_ts: datetime | None) -> str:
    if latest_ts is None:
        return "MISSING_CANDLE"
    delta = INTERVAL_DELTAS.get(interval)
    if delta is None:
        return "UNKNOWN"
    age = now_utc() - latest_ts.astimezone(UTC)
    fresh_mult, stale_mult = FRESHNESS_MULTIPLIERS.get(interval, (Decimal("1.5"), Decimal("4.0")))
    delta_seconds = Decimal(str(delta.total_seconds()))
    age_seconds = Decimal(str(age.total_seconds()))
    if age_seconds <= delta_seconds * fresh_mult:
        return "FRESH"
    if age_seconds <= delta_seconds * stale_mult:
        return "DELAYED"
    return "STALE"


def classify_quality(range_pct: Decimal | None, bars_since_anchor_end: int | None) -> str:
    if range_pct is None or bars_since_anchor_end is None:
        return "UNKNOWN"
    if range_pct >= Decimal("25") and bars_since_anchor_end <= 12:
        return "HIGH"
    if range_pct >= Decimal("10") and bars_since_anchor_end <= 30:
        return "MEDIUM"
    return "LOW"


def classify_swing_pct_band(range_pct: Decimal | None) -> str:
    if range_pct is None:
        return "UNKNOWN"
    if range_pct < Decimal("8"):
        return "<8"
    if range_pct < Decimal("25"):
        return "8-25"
    if range_pct < Decimal("60"):
        return "25-60"
    return ">=60"


def choose_up_pair(candles: list[Candle], lows: list[int], highs: list[int]) -> tuple[int, int] | None:
    if not lows or not highs or highs[-1] <= lows[-1]:
        return None
    high_idx = highs[-1]
    prior_lows = [low_idx for low_idx in lows if low_idx < high_idx]
    if not prior_lows:
        return None
    candidates: list[tuple[Decimal, int, int]] = []
    for low_idx in prior_lows[-6:]:
        low_price = candles[low_idx].low_price
        high_price = candles[high_idx].high_price
        if low_price <= 0 or high_price <= low_price:
            continue
        range_pct = pct_move(low_price, high_price) or Decimal("0")
        bars_from_end = Decimal(str(len(candles) - 1 - high_idx))
        leg_span = Decimal(str(high_idx - low_idx))
        score = range_pct - (bars_from_end * Decimal("0.40")) - (leg_span * Decimal("0.05"))
        candidates.append((score, low_idx, high_idx))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[2], item[1]), reverse=True)
    return (candidates[0][1], candidates[0][2])


def choose_down_pair(candles: list[Candle], lows: list[int], highs: list[int]) -> tuple[int, int] | None:
    if not lows or not highs or lows[-1] <= highs[-1]:
        return None
    low_idx = lows[-1]
    prior_highs = [high_idx for high_idx in highs if high_idx < low_idx]
    if not prior_highs:
        return None
    candidates: list[tuple[Decimal, int, int]] = []
    for high_idx in prior_highs[-6:]:
        high_price = candles[high_idx].high_price
        low_price = candles[low_idx].low_price
        if low_price <= 0 or high_price <= low_price:
            continue
        range_pct = pct_move(low_price, high_price) or Decimal("0")
        bars_from_end = Decimal(str(len(candles) - 1 - low_idx))
        leg_span = Decimal(str(low_idx - high_idx))
        score = range_pct - (bars_from_end * Decimal("0.40")) - (leg_span * Decimal("0.05"))
        candidates.append((score, high_idx, low_idx))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[2], item[1]), reverse=True)
    return (candidates[0][1], candidates[0][2])


def up_retrace_from_high(high: Decimal, range_abs: Decimal, retrace: Decimal) -> Decimal:
    return high - (range_abs * retrace)


def down_retrace_from_low(low: Decimal, range_abs: Decimal, retrace: Decimal) -> Decimal:
    return low + (range_abs * retrace)


def extension_from_up(low: Decimal, range_abs: Decimal, multiplier: Decimal) -> Decimal:
    return low + (range_abs * multiplier)


def extension_from_down(high: Decimal, range_abs: Decimal, multiplier: Decimal) -> Decimal:
    return high - (range_abs * multiplier)


def percent_distance(from_price: Decimal | None, to_price: Decimal | None) -> Decimal | None:
    if from_price is None or to_price is None or from_price <= 0:
        return None
    return ((to_price / from_price) - Decimal("1")) * Decimal("100")


def build_incomplete_row(
    *,
    venue: str,
    symbol: str,
    interval: str,
    latest_candle_ts: datetime | None,
    freshness: str,
    provenance: dict[str, Any],
    current_leg: str,
    reason: str,
) -> dict[str, Any]:
    asof_ts = latest_candle_ts or now_utc()
    return {
        "venue": venue,
        "symbol": symbol,
        "interval_code": interval,
        "asof_ts_utc": fmt_ts(asof_ts),
        "map_version": MAP_VERSION,
        "map_status": "INCOMPLETE",
        "map_quality": "UNKNOWN",
        "source_family": "SWING_FIBO_MAP",
        "source_ref": "obs_market_candle",
        "source_created_at_utc": fmt_ts(asof_ts),
        "current_leg": current_leg,
        "leg_method": "PIVOT_SWING_V1",
        "leg_confidence": "UNKNOWN",
        "anchor_low_ts_utc": "",
        "anchor_low_price": None,
        "anchor_high_ts_utc": "",
        "anchor_high_price": None,
        "swing_range_abs": None,
        "swing_range_pct": None,
        "swing_pct": None,
        "swing_pct_band": "UNKNOWN",
        "anchor_method": "PIVOT_SWING_V1",
        "anchor_quality": "UNKNOWN",
        "entry_zone_low": None,
        "entry_zone_high": None,
        "entry_zone_mid": None,
        "entry_zone_method": "UNAVAILABLE",
        "entry_zone_source_field": None,
        "support_reaction_zone_low": None,
        "support_reaction_zone_high": None,
        "support_reaction_method": "UNAVAILABLE",
        "target_t1": None,
        "target_t2": None,
        "target_extension": None,
        "target_method": "UNAVAILABLE",
        "target_source_field": None,
        "invalidation_level": None,
        "invalidation_method": "UNAVAILABLE",
        "invalidation_source_field": None,
        "distance_entry_to_target_pct": None,
        "distance_entry_to_invalidation_pct": None,
        "reward_risk_hint": None,
        "input_latest_candle_ts_utc": fmt_ts(latest_candle_ts),
        "source_freshness_state": freshness,
        "provenance_payload": json.dumps({**provenance, "incomplete_reason": reason}, sort_keys=True, ensure_ascii=True),
    }


def build_complete_row(
    *,
    venue: str,
    interval: str,
    symbol: str,
    candles: list[Candle],
    low_idx: int,
    high_idx: int,
    current_leg: str,
    swing_window: int,
) -> dict[str, Any]:
    latest = candles[-1]
    latest_candle_ts = latest.close_ts_utc
    freshness = classify_freshness(interval, latest_candle_ts)
    low_candle = candles[low_idx]
    high_candle = candles[high_idx]
    anchor_low_price = low_candle.low_price
    anchor_high_price = high_candle.high_price
    range_abs = anchor_high_price - anchor_low_price
    range_pct = pct_move(anchor_low_price, anchor_high_price)
    swing_pct_band = classify_swing_pct_band(range_pct)
    anchor_end_index = high_idx if current_leg == "UP" else low_idx
    bars_since_anchor_end = len(candles) - 1 - anchor_end_index
    map_quality = classify_quality(range_pct, bars_since_anchor_end)
    leg_confidence = map_quality
    buffer_abs = range_abs * BUFFER_PCT

    if current_leg == "UP":
        entry_zone_low = up_retrace_from_high(anchor_high_price, range_abs, ENTRY_LOW_RETRACE)
        entry_zone_high = up_retrace_from_high(anchor_high_price, range_abs, ENTRY_HIGH_RETRACE)
        support_low = up_retrace_from_high(anchor_high_price, range_abs, SUPPORT_LOW_RETRACE)
        support_high = up_retrace_from_high(anchor_high_price, range_abs, SUPPORT_HIGH_RETRACE)
        target_t1 = extension_from_up(anchor_low_price, range_abs, TARGET_T1_MULTIPLIER)
        target_t2 = extension_from_up(anchor_low_price, range_abs, TARGET_T2_MULTIPLIER)
        target_extension = extension_from_up(anchor_low_price, range_abs, TARGET_EXTENSION_MULTIPLIER)
        invalidation = anchor_low_price - buffer_abs
        target_source_field = "anchor_low_price+range*{1.272,1.618,2.618}"
        invalidation_source_field = "anchor_low_price-buffer_5pct_range"
    else:
        entry_zone_low = down_retrace_from_low(anchor_low_price, range_abs, ENTRY_HIGH_RETRACE)
        entry_zone_high = down_retrace_from_low(anchor_low_price, range_abs, ENTRY_LOW_RETRACE)
        support_low = down_retrace_from_low(anchor_low_price, range_abs, SUPPORT_HIGH_RETRACE)
        support_high = down_retrace_from_low(anchor_low_price, range_abs, SUPPORT_LOW_RETRACE)
        target_t1 = extension_from_down(anchor_high_price, range_abs, TARGET_T1_MULTIPLIER)
        target_t2 = extension_from_down(anchor_high_price, range_abs, TARGET_T2_MULTIPLIER)
        target_extension = extension_from_down(anchor_high_price, range_abs, TARGET_EXTENSION_MULTIPLIER)
        invalidation = anchor_high_price + buffer_abs
        target_source_field = "anchor_high_price-range*{1.272,1.618,2.618}"
        invalidation_source_field = "anchor_high_price+buffer_5pct_range"

    if entry_zone_low > entry_zone_high:
        entry_zone_low, entry_zone_high = entry_zone_high, entry_zone_low
    if support_low > support_high:
        support_low, support_high = support_high, support_low
    entry_mid = (entry_zone_low + entry_zone_high) / Decimal("2")
    distance_entry_to_target_pct = abs(percent_distance(entry_mid, target_t1) or Decimal("0"))
    distance_entry_to_invalidation_pct = abs(percent_distance(entry_mid, invalidation) or Decimal("0"))
    reward_risk_hint = None
    if distance_entry_to_invalidation_pct > 0:
        reward_risk_hint = distance_entry_to_target_pct / distance_entry_to_invalidation_pct

    map_status = "ACTIVE" if freshness in {"FRESH", "DELAYED"} else "STALE"
    provenance = {
        "algorithm": "canonical_fib_zone_map_writer_preview_v1",
        "leg_method": "PIVOT_SWING_V1",
        "swing_window": int(swing_window),
        "anchor_indices": {"low_idx": low_idx, "high_idx": high_idx},
        "bars_since_anchor_end": bars_since_anchor_end,
        "swing_pct": q_pct(range_pct),
        "swing_pct_band": swing_pct_band,
        "buffer_pct_of_range": str(BUFFER_PCT),
        "entry_zone_retrace": ["0.382", "0.618"],
        "support_reaction_retrace": ["0.618", "0.786"],
        "target_multipliers": ["1.272", "1.618", "2.618"],
    }
    return {
        "venue": venue,
        "symbol": symbol,
        "interval_code": interval,
        "asof_ts_utc": fmt_ts(latest_candle_ts),
        "map_version": MAP_VERSION,
        "map_status": map_status,
        "map_quality": map_quality,
        "source_family": "SWING_FIBO_MAP",
        "source_ref": "obs_market_candle",
        "source_created_at_utc": fmt_ts(latest_candle_ts),
        "current_leg": current_leg,
        "leg_method": "PIVOT_SWING_V1",
        "leg_confidence": leg_confidence,
        "anchor_low_ts_utc": fmt_ts(low_candle.low_ts_utc if hasattr(low_candle, "low_ts_utc") else low_candle.open_ts_utc),
        "anchor_low_price": q_price(anchor_low_price),
        "anchor_high_ts_utc": fmt_ts(high_candle.high_ts_utc if hasattr(high_candle, "high_ts_utc") else high_candle.close_ts_utc),
        "anchor_high_price": q_price(anchor_high_price),
        "swing_range_abs": q_price(range_abs),
        "swing_range_pct": q_pct(range_pct),
        "swing_pct": q_pct(range_pct),
        "swing_pct_band": swing_pct_band,
        "anchor_method": "PIVOT_SWING_V1",
        "anchor_quality": map_quality,
        "entry_zone_low": q_price(entry_zone_low),
        "entry_zone_high": q_price(entry_zone_high),
        "entry_zone_mid": q_price(entry_mid),
        "entry_zone_method": "FIB_RETRACE_0382_0618",
        "entry_zone_source_field": "anchor_range_retrace",
        "support_reaction_zone_low": q_price(support_low),
        "support_reaction_zone_high": q_price(support_high),
        "support_reaction_method": "FIB_RETRACE_0618_0786",
        "target_t1": q_price(target_t1),
        "target_t2": q_price(target_t2),
        "target_extension": q_price(target_extension),
        "target_method": "FIB_EXTENSION_1272_1618_2618",
        "target_source_field": target_source_field,
        "invalidation_level": q_price(invalidation),
        "invalidation_method": "ANCHOR_RANGE_BUFFER_5PCT",
        "invalidation_source_field": invalidation_source_field,
        "distance_entry_to_target_pct": q_pct(distance_entry_to_target_pct),
        "distance_entry_to_invalidation_pct": q_pct(distance_entry_to_invalidation_pct),
        "reward_risk_hint": q_pct(reward_risk_hint),
        "input_latest_candle_ts_utc": fmt_ts(latest_candle_ts),
        "source_freshness_state": freshness,
        "provenance_payload": json.dumps(provenance, sort_keys=True, ensure_ascii=True),
    }


def build_row_for_symbol(
    *,
    venue: str,
    interval: str,
    symbol: str,
    candles: list[Candle],
    swing_window: int,
) -> dict[str, Any]:
    latest_ts = candles[-1].close_ts_utc if candles else None
    freshness = classify_freshness(interval, latest_ts)
    base_provenance = {
        "algorithm": "canonical_fib_zone_map_writer_preview_v1",
        "symbol": symbol,
        "candle_count": len(candles),
        "swing_window": int(swing_window),
    }
    if len(candles) < (swing_window * 2 + 3):
        return build_incomplete_row(
            venue=venue,
            symbol=symbol,
            interval=interval,
            latest_candle_ts=latest_ts,
            freshness=freshness,
            provenance=base_provenance,
            current_leg="UNKNOWN",
            reason="not_enough_candles_for_pivot_detection",
        )
    lows, highs = pivot_indices(candles, swing_window)
    if not lows and not highs:
        return build_incomplete_row(
            venue=venue,
            symbol=symbol,
            interval=interval,
            latest_candle_ts=latest_ts,
            freshness=freshness,
            provenance={**base_provenance, "pivot_lows": 0, "pivot_highs": 0},
            current_leg="RANGE",
            reason="no_confirmed_pivot_structure",
        )
    latest_low = lows[-1] if lows else None
    latest_high = highs[-1] if highs else None
    if latest_low is None or latest_high is None:
        return build_incomplete_row(
            venue=venue,
            symbol=symbol,
            interval=interval,
            latest_candle_ts=latest_ts,
            freshness=freshness,
            provenance={**base_provenance, "pivot_lows": len(lows), "pivot_highs": len(highs)},
            current_leg="UNKNOWN",
            reason="missing_opposite_pivot_side",
        )
    if latest_high > latest_low:
        pair = choose_up_pair(candles, lows, highs)
        if pair is None:
            return build_incomplete_row(
                venue=venue,
                symbol=symbol,
                interval=interval,
                latest_candle_ts=latest_ts,
                freshness=freshness,
                provenance={**base_provenance, "pivot_lows": len(lows), "pivot_highs": len(highs)},
                current_leg="UP",
                reason="no_meaningful_up_pair",
            )
        return build_complete_row(
            venue=venue,
            interval=interval,
            symbol=symbol,
            candles=candles,
            low_idx=pair[0],
            high_idx=pair[1],
            current_leg="UP",
            swing_window=swing_window,
        )
    if latest_low > latest_high:
        pair = choose_down_pair(candles, lows, highs)
        if pair is None:
            return build_incomplete_row(
                venue=venue,
                symbol=symbol,
                interval=interval,
                latest_candle_ts=latest_ts,
                freshness=freshness,
                provenance={**base_provenance, "pivot_lows": len(lows), "pivot_highs": len(highs)},
                current_leg="DOWN",
                reason="no_meaningful_down_pair",
            )
        return build_complete_row(
            venue=venue,
            interval=interval,
            symbol=symbol,
            candles=candles,
            low_idx=pair[1],
            high_idx=pair[0],
            current_leg="DOWN",
            swing_window=swing_window,
        )
    return build_incomplete_row(
        venue=venue,
        symbol=symbol,
        interval=interval,
        latest_candle_ts=latest_ts,
        freshness=freshness,
        provenance={**base_provenance, "pivot_lows": len(lows), "pivot_highs": len(highs)},
        current_leg="RANGE",
        reason="latest_pivots_do_not_define_direction",
    )


def build_summary(rows: list[dict[str, Any]], output_dir: Path) -> dict[str, Any]:
    complete_rows = sum(1 for row in rows if row["map_status"] != "INCOMPLETE")
    incomplete_rows = len(rows) - complete_rows
    up_leg_rows = sum(1 for row in rows if row["current_leg"] == "UP")
    down_leg_rows = sum(1 for row in rows if row["current_leg"] == "DOWN")
    range_unknown_rows = sum(1 for row in rows if row["current_leg"] in {"RANGE", "UNKNOWN"})
    swing_pct_band_counts = {band: 0 for band in SWING_PCT_BAND_ORDER}
    for row in rows:
        band = str(row.get("swing_pct_band") or "UNKNOWN")
        swing_pct_band_counts[band] = swing_pct_band_counts.get(band, 0) + 1
    return {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "rows": len(rows),
        "complete_rows": complete_rows,
        "incomplete_rows": incomplete_rows,
        "up_leg_rows": up_leg_rows,
        "down_leg_rows": down_leg_rows,
        "range_unknown_rows": range_unknown_rows,
        "swing_pct_band_counts": swing_pct_band_counts,
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


def print_summary(summary: dict[str, Any], output_mode: str) -> None:
    if output_mode == "json":
        print(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=True))
        return
    for key in (
        "report",
        "version",
        "rows",
        "complete_rows",
        "incomplete_rows",
        "up_leg_rows",
        "down_leg_rows",
        "range_unknown_rows",
        "output_dir",
        "db_writes",
        "broker_private_calls",
        "broker_writes",
        "order_submission",
        "decision_gate_changes",
        "execution_planner_changes",
        "executor",
        "account_awareness",
    ):
        print(f"{key}={summary[key]}")
    print(
        "swing_pct_band: "
        + " ".join(
            f"{band}={summary['swing_pct_band_counts'].get(band, 0)}"
            for band in SWING_PCT_BAND_ORDER
        )
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.write_db:
        raise ValueError("--write-db is not supported in v1 preview; this runner is preview-only and read-only.")
    if args.lookback_candles <= 0:
        raise ValueError("--lookback-candles must be greater than zero")
    if args.swing_window <= 0:
        raise ValueError("--swing-window must be greater than zero")
    if args.limit_assets <= 0:
        raise ValueError("--limit-assets must be greater than zero")

    conn = get_connection()
    try:
        assets = fetch_assets(conn, quote=str(args.quote), limit_assets=int(args.limit_assets))
        candles_by_symbol = fetch_recent_candles(
            conn,
            assets=assets,
            venue=str(args.venue),
            interval=str(args.interval),
            lookback_candles=int(args.lookback_candles),
        )
    finally:
        conn.close()

    rows = [
        build_row_for_symbol(
            venue=str(args.venue),
            interval=str(args.interval),
            symbol=asset.symbol,
            candles=candles_by_symbol.get(asset.symbol, []),
            swing_window=int(args.swing_window),
        )
        for asset in assets
    ]

    output_dir = Path(args.output_dir)
    if args.write_files:
        output_dir.mkdir(parents=True, exist_ok=True)
        write_csv(output_dir / "canonical_fib_zone_map_preview_rows_v1.csv", rows)
        write_jsonl(output_dir / "canonical_fib_zone_map_preview_rows_v1.jsonl", rows)
        write_json(output_dir / "summary.json", build_summary(rows, output_dir))

    print_summary(build_summary(rows, output_dir), args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
