from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any

from src.common.db import get_connection


REPORT_NAME = "fibo_target_map_v1"
REPORT_VERSION = "1.0"

DEFAULT_VENUE = "bitvavo"
DEFAULT_INTERVAL = "1d"
DEFAULT_QUOTE = "EUR"
DEFAULT_LOOKBACK_CANDLES = 180
DEFAULT_SWING_WINDOW = 5
DEFAULT_MAX_SYMBOLS = 0
DEFAULT_OUTPUT_DIR = Path("data/research/fibo_target_map_v1")

ROWS_CSV = "fibo_target_map_rows_v1.csv"
ROWS_JSONL = "fibo_target_map_rows_v1.jsonl"
SUMMARY_BY_TARGET_STATUS_CSV = "summary_by_target_status_v1.csv"
SUMMARY_BY_ANCHOR_QUALITY_CSV = "summary_by_anchor_quality_v1.csv"
MANIFEST_JSON = "manifest_v1.json"

FIB_LEVELS = {
    "fib_1272_price": 1.272,
    "fib_1618_price": 1.618,
    "fib_2618_price": 2.618,
    "fib_3618_price": 3.618,
    "fib_4236_price": 4.236,
}
FIB_TARGET_LABELS = {
    "fib_1272_price": "FIB_1272_TP",
    "fib_1618_price": "FIB_1618_MAIN_TP",
    "fib_2618_price": "FIB_2618_STRETCH_TP",
    "fib_3618_price": "FIB_3618_BULL_TARGET",
    "fib_4236_price": "FIB_4236_MOONBAG_TP",
}
TARGET_STATUS_ORDER = [
    "MISSING_MARKET_DATA",
    "BELOW_LOCAL_REACTION",
    "APPROACHING_1272",
    "BETWEEN_1272_1618",
    "BETWEEN_1618_2618",
    "BETWEEN_2618_3618",
    "BETWEEN_3618_4236",
    "TARGETS_EXCEEDED",
    "INSUFFICIENT_SWING",
    "NOT_IMPLEMENTED",
]
ANCHOR_QUALITY_ORDER = [
    "MISSING_MARKET_DATA",
    "HIGH_QUALITY",
    "MEDIUM_QUALITY",
    "LOW_QUALITY",
    "INSUFFICIENT_SWING",
    "NOT_IMPLEMENTED",
]
SAFETY_MARKERS = {
    "db_writes": 0,
    "broker_calls": 0,
    "broker_writes": 0,
    "order_submission": 0,
    "account_tables_used": False,
    "executor": "none",
    "research_only": True,
}
VALIDATION_BASELINE_NOTE = (
    "Every future strategy/backtest must compare strategy profit against HOLD / "
    "buy-and-hold baseline and report excess return plus drawdown improvement."
)


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
    open_price: float
    high_price: float
    low_price: float
    close_price: float


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build anchored fib target ladders from recent market swings "
            "(research-only, market-only, account-agnostic, no execution)."
        )
    )
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--interval", default=DEFAULT_INTERVAL)
    parser.add_argument("--quote", default=DEFAULT_QUOTE)
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--lookback-candles", type=int, default=DEFAULT_LOOKBACK_CANDLES)
    parser.add_argument("--swing-window", type=int, default=DEFAULT_SWING_WINDOW)
    parser.add_argument("--max-symbols", type=int, default=DEFAULT_MAX_SYMBOLS)
    parser.add_argument("--write-files", action="store_true")
    parser.add_argument("--output", choices=("summary", "json"), default="summary")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser.parse_args(argv)


def fmt_ts(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=True) + "\n")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def read_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def table_columns(conn: Any, table_name: str) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = %s",
            (table_name,),
        )
        return {str(row["column_name"]) for row in cur.fetchall()}


def parse_symbols_arg(value: str | None) -> list[str] | None:
    if not value:
        return None
    items = [piece.strip().upper() for piece in str(value).split(",") if piece.strip()]
    return sorted(dict.fromkeys(items))


def fetch_assets(
    conn: Any,
    *,
    symbols: list[str] | None,
    quote: str,
    max_symbols: int,
) -> list[AssetRef]:
    columns = table_columns(conn, "asset")
    where: list[str] = []
    params: list[Any] = []
    if "is_enabled" in columns:
        where.append("is_enabled = 1")
    if symbols:
        where.append("UPPER(symbol) IN (" + ",".join(["%s"] * len(symbols)) + ")")
        params.extend([symbol.upper() for symbol in symbols])
    else:
        if "quote_asset" in columns:
            where.append("UPPER(quote_asset) = UPPER(%s)")
            params.append(quote.upper())
        elif "quote_currency" in columns:
            where.append("UPPER(quote_currency) = UPPER(%s)")
            params.append(quote.upper())
    sql = "SELECT asset_id, symbol FROM asset"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY symbol ASC"
    if max_symbols > 0:
        sql += " LIMIT %s"
        params.append(int(max_symbols))
    with conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        rows = list(cur.fetchall())
    return [AssetRef(asset_id=int(row["asset_id"]), symbol=str(row["symbol"]).upper()) for row in rows]


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
    sql = f"""
        SELECT c.asset_id, a.symbol, c.open_ts_utc, c.close_ts_utc, c.open_price, c.high_price, c.low_price, c.close_price
        FROM obs_market_candle c
        JOIN asset a
          ON a.asset_id = c.asset_id
        WHERE c.venue = %s
          AND c.interval_code = %s
          AND c.asset_id IN ({placeholders})
        ORDER BY c.asset_id ASC, c.close_ts_utc DESC
    """
    params: list[Any] = [venue, interval, *[asset.asset_id for asset in assets]]
    grouped: dict[str, list[Candle]] = {asset.symbol: [] for asset in assets}
    with conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        rows = list(cur.fetchall())
    counts: dict[str, int] = {}
    for row in rows:
        symbol = str(row["symbol"]).upper()
        taken = counts.get(symbol, 0)
        if taken >= int(lookback_candles):
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
        grouped.setdefault(symbol, []).append(
            Candle(
                asset_id=int(row["asset_id"]),
                symbol=symbol,
                open_ts_utc=open_ts,
                close_ts_utc=close_ts,
                open_price=float(row["open_price"]),
                high_price=float(row["high_price"]),
                low_price=float(row["low_price"]),
                close_price=float(row["close_price"]),
            )
        )
        counts[symbol] = taken + 1
    return {symbol: list(reversed(rows_for_symbol)) for symbol, rows_for_symbol in grouped.items()}


def average_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 6)


def median_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return round(float(median(values)), 6)


def pct_move(low_price: float, high_price: float) -> float:
    if low_price <= 0:
        return 0.0
    return ((high_price / low_price) - 1.0) * 100.0


def upward_distance_pct(current_price: float | None, target_price: float | None) -> float | None:
    if current_price is None or target_price is None or current_price <= 0:
        return None
    return round(((target_price / current_price) - 1.0) * 100.0, 6)


def downward_distance_pct(current_price: float | None, support_price: float | None) -> float | None:
    if current_price is None or support_price is None or current_price <= 0:
        return None
    return round(((current_price / support_price) - 1.0) * 100.0, 6)


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


def infer_latest_leg(lows: list[int], highs: list[int]) -> str:
    latest_low = None if not lows else lows[-1]
    latest_high = None if not highs else highs[-1]
    if latest_low is None and latest_high is None:
        return "UNKNOWN"
    if latest_high is None:
        return "DOWN"
    if latest_low is None:
        return "UP"
    return "UP" if latest_high > latest_low else "DOWN"


def choose_up_swing(candles: list[Candle], lows: list[int], highs: list[int]) -> tuple[int, int] | None:
    candidates: list[tuple[float, int, int]] = []
    for high_idx in highs:
        prior_lows = [low_idx for low_idx in lows if low_idx < high_idx]
        if not prior_lows:
            continue
        for low_idx in prior_lows[-6:]:
            low_price = candles[low_idx].low_price
            high_price = candles[high_idx].high_price
            if low_price <= 0 or high_price <= low_price:
                continue
            range_pct = pct_move(low_price, high_price)
            bars_from_high = len(candles) - 1 - high_idx
            candles_in_leg = high_idx - low_idx
            score = range_pct - (bars_from_high * 0.40) - (candles_in_leg * 0.05)
            candidates.append((score, low_idx, high_idx))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[2], item[1]), reverse=True)
    _score, low_idx, high_idx = candidates[0]
    return low_idx, high_idx


def extension_price(swing_low: float, swing_high: float, fib_multiplier: float) -> float:
    swing_range = swing_high - swing_low
    return round(swing_low + swing_range * fib_multiplier, 8)


def classify_anchor_quality(*, range_pct: float, bars_since_anchor_end: int) -> str:
    if range_pct >= 60.0 and bars_since_anchor_end <= 35:
        return "HIGH_QUALITY"
    if range_pct >= 25.0 and bars_since_anchor_end <= 75:
        return "MEDIUM_QUALITY"
    return "LOW_QUALITY"


def reentry_zone_label(distance_pct: float | None) -> str:
    if distance_pct is None:
        return "UNKNOWN_RELOAD"
    if distance_pct <= 3.0:
        return "EASY_RELOAD"
    if distance_pct <= 8.0:
        return "NORMAL_RELOAD"
    if distance_pct <= 15.0:
        return "DEEP_RELOAD"
    return "HARD_RELOAD"


def tp_reentry_risk_label(
    *,
    distance_to_next_extension_pct: float | None,
    distance_to_next_fibo_support_pct: float | None,
) -> str:
    if distance_to_next_extension_pct is None or distance_to_next_fibo_support_pct is None:
        return "UNKNOWN_TP_REENTRY"
    if distance_to_next_fibo_support_pct <= 0:
        return "UNKNOWN_TP_REENTRY"
    ratio = distance_to_next_extension_pct / distance_to_next_fibo_support_pct
    if ratio >= 2.0:
        return "FAVORABLE_TP_VS_REENTRY"
    if ratio >= 1.0:
        return "BALANCED_TP_VS_REENTRY"
    return "POOR_TP_VS_REENTRY"


def classify_target_ladder(
    *,
    current_price: float,
    swing_low_price: float,
    local_reaction_price: float,
    fib_1272_price: float,
    fib_1618_price: float,
    fib_2618_price: float,
    fib_3618_price: float,
    fib_4236_price: float,
) -> dict[str, Any]:
    main_extension_target_level = "FIB_1618_MAIN_TP"
    stretch_target_level = "FIB_2618_STRETCH_TP"
    bull_target_level = "FIB_3618_BULL_TARGET"
    moonbag_target_level = "FIB_4236_MOONBAG_TP"
    if current_price < local_reaction_price:
        target_status = "BELOW_LOCAL_REACTION"
        current_target_band = "BELOW_LOCAL_REACTION"
        next_extension_target_level = "FIB_1272_TP"
        next_extension_target_price = fib_1272_price
        next_fibo_support_level = "SWING_LOW_SUPPORT"
        next_fibo_support_price = swing_low_price
        secondary_fibo_support_level = None
        secondary_fibo_support_price = None
    elif current_price < fib_1272_price:
        target_status = "APPROACHING_1272"
        current_target_band = "BETWEEN_LOCAL_AND_1272"
        next_extension_target_level = "FIB_1272_TP"
        next_extension_target_price = fib_1272_price
        next_fibo_support_level = "LOCAL_REACTION_SUPPORT"
        next_fibo_support_price = local_reaction_price
        secondary_fibo_support_level = "SWING_LOW_SUPPORT"
        secondary_fibo_support_price = None
    elif current_price < fib_1618_price:
        target_status = "BETWEEN_1272_1618"
        current_target_band = "BETWEEN_1272_AND_1618"
        next_extension_target_level = "FIB_1618_MAIN_TP"
        next_extension_target_price = fib_1618_price
        next_fibo_support_level = "FIB_1272_SUPPORT"
        next_fibo_support_price = fib_1272_price
        secondary_fibo_support_level = "LOCAL_REACTION_SUPPORT"
        secondary_fibo_support_price = local_reaction_price
    elif current_price < fib_2618_price:
        target_status = "BETWEEN_1618_2618"
        current_target_band = "BETWEEN_1618_AND_2618"
        next_extension_target_level = "FIB_2618_STRETCH_TP"
        next_extension_target_price = fib_2618_price
        next_fibo_support_level = "FIB_1618_SUPPORT"
        next_fibo_support_price = fib_1618_price
        secondary_fibo_support_level = "FIB_1272_SUPPORT"
        secondary_fibo_support_price = fib_1272_price
    elif current_price < fib_3618_price:
        target_status = "BETWEEN_2618_3618"
        current_target_band = "BETWEEN_2618_AND_3618"
        next_extension_target_level = "FIB_3618_BULL_TARGET"
        next_extension_target_price = fib_3618_price
        next_fibo_support_level = "FIB_2618_SUPPORT"
        next_fibo_support_price = fib_2618_price
        secondary_fibo_support_level = "FIB_1618_SUPPORT"
        secondary_fibo_support_price = fib_1618_price
    elif current_price < fib_4236_price:
        target_status = "BETWEEN_3618_4236"
        current_target_band = "BETWEEN_3618_AND_4236"
        next_extension_target_level = "FIB_4236_MOONBAG_TP"
        next_extension_target_price = fib_4236_price
        next_fibo_support_level = "FIB_3618_SUPPORT"
        next_fibo_support_price = fib_3618_price
        secondary_fibo_support_level = "FIB_2618_SUPPORT"
        secondary_fibo_support_price = fib_2618_price
    else:
        target_status = "TARGETS_EXCEEDED"
        current_target_band = "ABOVE_4236"
        next_extension_target_level = None
        next_extension_target_price = None
        next_fibo_support_level = "FIB_4236_SUPPORT"
        next_fibo_support_price = fib_4236_price
        secondary_fibo_support_level = "FIB_3618_SUPPORT"
        secondary_fibo_support_price = fib_3618_price

    distance_to_local_reaction_pct = upward_distance_pct(current_price, local_reaction_price) if current_price < local_reaction_price else 0.0
    distance_to_next_extension_pct = upward_distance_pct(current_price, next_extension_target_price)
    distance_to_next_fibo_support_pct = downward_distance_pct(current_price, next_fibo_support_price)
    distance_to_secondary_fibo_support_pct = downward_distance_pct(current_price, secondary_fibo_support_price)
    reload_label = reentry_zone_label(distance_to_next_fibo_support_pct)
    return {
        "target_status": target_status,
        "current_target_band": current_target_band,
        "local_reaction_price": round(local_reaction_price, 8),
        "distance_to_local_reaction_pct": distance_to_local_reaction_pct,
        "next_extension_target_level": next_extension_target_level,
        "next_extension_target_price": None if next_extension_target_price is None else round(next_extension_target_price, 8),
        "distance_to_next_extension_pct": distance_to_next_extension_pct,
        "main_extension_target_level": main_extension_target_level,
        "main_extension_target_price": round(fib_1618_price, 8),
        "stretch_target_level": stretch_target_level,
        "stretch_target_price": round(fib_2618_price, 8),
        "bull_target_level": bull_target_level,
        "bull_target_price": round(fib_3618_price, 8),
        "moonbag_target_level": moonbag_target_level,
        "moonbag_target_price": round(fib_4236_price, 8),
        "next_fibo_support_level": next_fibo_support_level,
        "next_fibo_support_price": None if next_fibo_support_price is None else round(next_fibo_support_price, 8),
        "distance_to_next_fibo_support_pct": distance_to_next_fibo_support_pct,
        "secondary_fibo_support_level": secondary_fibo_support_level,
        "secondary_fibo_support_price": None if secondary_fibo_support_price is None else round(secondary_fibo_support_price, 8),
        "distance_to_secondary_fibo_support_pct": distance_to_secondary_fibo_support_pct,
        "reentry_zone_label": reload_label,
        "reentry_distance_pct": distance_to_next_fibo_support_pct,
        "tp_reentry_risk_label": tp_reentry_risk_label(
            distance_to_next_extension_pct=distance_to_next_extension_pct,
            distance_to_next_fibo_support_pct=distance_to_next_fibo_support_pct,
        ),
        "next_target_level": next_extension_target_level,
        "next_target_price": None if next_extension_target_price is None else round(next_extension_target_price, 8),
        "distance_to_next_target_pct": distance_to_next_extension_pct,
    }


def insufficient_row(symbol: str, venue: str, interval: str, current_price: float | None, reason: str, status: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "venue": venue,
        "interval": interval,
        "anchor_start_ts": "",
        "anchor_end_ts": "",
        "swing_low_price": None,
        "swing_high_price": None,
        "leg_direction": "UP" if status == "INSUFFICIENT_SWING" else "DOWN",
        "range_pct": None,
        "local_reaction_price": None,
        "distance_to_local_reaction_pct": None,
        "fib_1272_price": None,
        "fib_1618_price": None,
        "fib_2618_price": None,
        "fib_3618_price": None,
        "fib_4236_price": None,
        "current_price": current_price,
        "current_target_band": status,
        "next_extension_target_level": None,
        "next_extension_target_price": None,
        "distance_to_next_extension_pct": None,
        "main_extension_target_level": "FIB_1618_MAIN_TP",
        "main_extension_target_price": None,
        "stretch_target_level": "FIB_2618_STRETCH_TP",
        "stretch_target_price": None,
        "bull_target_level": "FIB_3618_BULL_TARGET",
        "bull_target_price": None,
        "moonbag_target_level": "FIB_4236_MOONBAG_TP",
        "moonbag_target_price": None,
        "next_fibo_support_level": None,
        "next_fibo_support_price": None,
        "distance_to_next_fibo_support_pct": None,
        "secondary_fibo_support_level": None,
        "secondary_fibo_support_price": None,
        "distance_to_secondary_fibo_support_pct": None,
        "reentry_zone_label": "UNKNOWN_RELOAD",
        "reentry_distance_pct": None,
        "tp_reentry_risk_label": "UNKNOWN_TP_REENTRY",
        "next_target_level": None,
        "next_target_price": None,
        "distance_to_next_target_pct": None,
        "target_status": status,
        "anchor_quality": status,
        "bars_since_anchor_end": None,
        "swing_window": None,
        "anchor_reason": reason,
    }


def missing_market_data_row(symbol: str, venue: str, interval: str, reason: str) -> dict[str, Any]:
    return insufficient_row(
        symbol,
        venue,
        interval,
        None,
        reason,
        "MISSING_MARKET_DATA",
    )


def build_row_for_symbol(symbol: str, candles: list[Candle], *, venue: str, interval: str, swing_window: int) -> dict[str, Any]:
    current_price = None if not candles else candles[-1].close_price
    if len(candles) < (swing_window * 2 + 3):
        return insufficient_row(symbol, venue, interval, current_price, "not_enough_candles_for_pivot_detection", "INSUFFICIENT_SWING")
    lows, highs = pivot_indices(candles, swing_window)
    if not lows or not highs:
        return insufficient_row(symbol, venue, interval, current_price, "no_confirmed_pivot_pairs", "INSUFFICIENT_SWING")
    latest_leg = infer_latest_leg(lows, highs)
    if latest_leg == "DOWN":
        return insufficient_row(symbol, venue, interval, current_price, "down_leg_mapping_not_implemented_in_v1", "NOT_IMPLEMENTED")
    pair = choose_up_swing(candles, lows, highs)
    if pair is None:
        return insufficient_row(symbol, venue, interval, current_price, "no_meaningful_up_swing_pair_found", "INSUFFICIENT_SWING")
    low_idx, high_idx = pair
    swing_low = candles[low_idx]
    swing_high = candles[high_idx]
    if swing_high.high_price <= swing_low.low_price:
        return insufficient_row(symbol, venue, interval, current_price, "non_positive_swing_range", "INSUFFICIENT_SWING")
    range_pct = round(pct_move(swing_low.low_price, swing_high.high_price), 6)
    bars_since_anchor_end = len(candles) - 1 - high_idx
    fib_prices = {
        label: extension_price(swing_low.low_price, swing_high.high_price, level)
        for label, level in FIB_LEVELS.items()
    }
    ladder = classify_target_ladder(
        current_price=current_price if current_price is not None else swing_high.high_price,
        swing_low_price=swing_low.low_price,
        local_reaction_price=swing_high.high_price,
        fib_1272_price=fib_prices["fib_1272_price"],
        fib_1618_price=fib_prices["fib_1618_price"],
        fib_2618_price=fib_prices["fib_2618_price"],
        fib_3618_price=fib_prices["fib_3618_price"],
        fib_4236_price=fib_prices["fib_4236_price"],
    )
    row = {
        "symbol": symbol,
        "venue": venue,
        "interval": interval,
        "anchor_start_ts": fmt_ts(swing_low.open_ts_utc),
        "anchor_end_ts": fmt_ts(swing_high.close_ts_utc),
        "swing_low_price": round(swing_low.low_price, 8),
        "swing_high_price": round(swing_high.high_price, 8),
        "leg_direction": "UP",
        "range_pct": range_pct,
        "local_reaction_price": round(swing_high.high_price, 8),
        "fib_1272_price": fib_prices["fib_1272_price"],
        "fib_1618_price": fib_prices["fib_1618_price"],
        "fib_2618_price": fib_prices["fib_2618_price"],
        "fib_3618_price": fib_prices["fib_3618_price"],
        "fib_4236_price": fib_prices["fib_4236_price"],
        "current_price": round(current_price, 8) if current_price is not None else None,
        "anchor_quality": classify_anchor_quality(range_pct=range_pct, bars_since_anchor_end=bars_since_anchor_end),
        "bars_since_anchor_end": bars_since_anchor_end,
        "swing_window": int(swing_window),
        "anchor_reason": "anchored_up_swing_from_confirmed_pivot_low_to_later_pivot_high",
    }
    row.update(ladder)
    return row


def build_rows(
    *,
    assets: list[AssetRef],
    requested_symbols: list[str] | None,
    candles_by_symbol: dict[str, list[Candle]],
    venue: str,
    interval: str,
    swing_window: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    asset_symbols = {asset.symbol for asset in assets}
    symbols_to_process = (
        list(requested_symbols)
        if requested_symbols is not None
        else sorted(candles_by_symbol.keys())
    )
    for symbol in sorted(symbols_to_process):
        if requested_symbols is not None and symbol not in asset_symbols:
            rows.append(
                missing_market_data_row(
                    symbol,
                    venue,
                    interval,
                    "symbol_not_found_in_asset_universe",
                )
            )
            continue
        candles = candles_by_symbol.get(symbol, [])
        if not candles:
            rows.append(
                missing_market_data_row(
                    symbol,
                    venue,
                    interval,
                    "no_market_candles_found_for_symbol",
                )
            )
            continue
        rows.append(
            build_row_for_symbol(
                symbol,
                candles,
                venue=venue,
                interval=interval,
                swing_window=swing_window,
            )
        )
    return rows


def is_partial_scope(*, requested_symbols: list[str] | None, max_symbols: int) -> bool:
    return requested_symbols is not None or max_symbols > 0


def merge_rows_by_symbol(existing_rows: list[dict[str, Any]], new_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for row in existing_rows:
        symbol = str(row.get("symbol") or "").upper()
        if symbol:
            merged[symbol] = row
    for row in new_rows:
        symbol = str(row.get("symbol") or "").upper()
        if symbol:
            merged[symbol] = row
    return [merged[symbol] for symbol in sorted(merged.keys())]


def summary_rows(rows: list[dict[str, Any]], field: str, ordered_values: list[str]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for value in ordered_values:
        matching = [row for row in rows if str(row.get(field) or "") == value]
        if not matching:
            continue
        range_values = [float(row["range_pct"]) for row in matching if row.get("range_pct") is not None]
        distance_values = [float(row["distance_to_next_extension_pct"]) for row in matching if row.get("distance_to_next_extension_pct") is not None]
        output.append(
            {
                field: value,
                "count": len(matching),
                "avg_range_pct": average_or_none(range_values),
                "median_range_pct": median_or_none(range_values),
                "avg_distance_to_next_extension_pct": average_or_none(distance_values),
                "median_distance_to_next_extension_pct": median_or_none(distance_values),
            }
        )
    return output


def build_manifest(*, args: argparse.Namespace, rows: list[dict[str, Any]], paths: dict[str, Path]) -> dict[str, Any]:
    return {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "parameters": {
            "venue": args.venue,
            "interval": args.interval,
            "quote": args.quote,
            "symbols": parse_symbols_arg(args.symbols),
            "lookback_candles": int(args.lookback_candles),
            "swing_window": int(args.swing_window),
            "max_symbols": int(args.max_symbols),
        },
        "row_count": len(rows),
        "symbols_processed": sorted({str(row.get("symbol") or "") for row in rows if row.get("symbol")}),
        "files": {key: str(value) for key, value in paths.items()},
        "validation_baseline_rule": VALIDATION_BASELINE_NOTE,
        **SAFETY_MARKERS,
    }


def print_summary(*, rows: list[dict[str, Any]], target_status_summary: list[dict[str, Any]], anchor_quality_summary: list[dict[str, Any]], manifest: dict[str, Any], output_mode: str) -> None:
    summary = {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "row_count": len(rows),
        "target_status_counts": {row["target_status"]: row["count"] for row in target_status_summary},
        "anchor_quality_counts": {row["anchor_quality"]: row["count"] for row in anchor_quality_summary},
        "symbols_processed": manifest["symbols_processed"],
        "validation_baseline_rule": manifest["validation_baseline_rule"],
        "safety": SAFETY_MARKERS,
        "files": {key: str(value) for key, value in manifest["files"].items()},
    }
    if output_mode == "json":
        print(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=True))
        return
    print(f"report={REPORT_NAME} version={REPORT_VERSION}")
    print(
        f"rows={len(rows)} venue={manifest['parameters']['venue']} interval={manifest['parameters']['interval']} "
        f"lookback_candles={manifest['parameters']['lookback_candles']} swing_window={manifest['parameters']['swing_window']}"
    )
    if target_status_summary:
        print("target_status " + " ; ".join(f"{row['target_status']}:{row['count']}" for row in target_status_summary))
    if anchor_quality_summary:
        print("anchor_quality " + " ; ".join(f"{row['anchor_quality']}:{row['count']}" for row in anchor_quality_summary))
    print(f"validation_baseline_rule={manifest['validation_baseline_rule']}")
    print(
        "safety "
        "db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 account_tables_used=false executor=none research_only=true"
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.lookback_candles <= 0:
        raise ValueError("--lookback-candles must be greater than zero")
    if args.swing_window <= 0:
        raise ValueError("--swing-window must be greater than zero")
    if args.interval not in {"1d", "1w"}:
        raise ValueError("V1 currently supports 1d or 1w anchor intervals only")
    symbols = parse_symbols_arg(args.symbols)

    conn = get_connection()
    try:
        assets = fetch_assets(
            conn,
            symbols=symbols,
            quote=args.quote,
            max_symbols=int(args.max_symbols),
        )
        candles_by_symbol = fetch_recent_candles(
            conn,
            assets=assets,
            venue=args.venue,
            interval=args.interval,
            lookback_candles=int(args.lookback_candles),
        )
    finally:
        conn.close()

    rows = build_rows(
        assets=assets,
        requested_symbols=symbols,
        candles_by_symbol=candles_by_symbol,
        venue=args.venue,
        interval=args.interval,
        swing_window=int(args.swing_window),
    )
    target_status_summary = summary_rows(rows, "target_status", TARGET_STATUS_ORDER)
    anchor_quality_summary = summary_rows(rows, "anchor_quality", ANCHOR_QUALITY_ORDER)

    output_dir = Path(args.output_dir)
    paths = {
        "rows_csv": output_dir / ROWS_CSV,
        "rows_jsonl": output_dir / ROWS_JSONL,
        "summary_by_target_status_csv": output_dir / SUMMARY_BY_TARGET_STATUS_CSV,
        "summary_by_anchor_quality_csv": output_dir / SUMMARY_BY_ANCHOR_QUALITY_CSV,
        "manifest_json": output_dir / MANIFEST_JSON,
    }
    rows_to_write = rows
    if args.write_files and is_partial_scope(requested_symbols=symbols, max_symbols=int(args.max_symbols)):
        rows_to_write = merge_rows_by_symbol(read_csv_rows(paths["rows_csv"]), rows)
    manifest = build_manifest(args=args, rows=rows_to_write, paths=paths)

    if args.write_files:
        write_csv(paths["rows_csv"], rows_to_write)
        write_jsonl(paths["rows_jsonl"], rows_to_write)
        write_csv(paths["summary_by_target_status_csv"], summary_rows(rows_to_write, "target_status", TARGET_STATUS_ORDER))
        write_csv(paths["summary_by_anchor_quality_csv"], summary_rows(rows_to_write, "anchor_quality", ANCHOR_QUALITY_ORDER))
        write_json(paths["manifest_json"], manifest)

    print_summary(
        rows=rows,
        target_status_summary=target_status_summary,
        anchor_quality_summary=anchor_quality_summary,
        manifest=manifest,
        output_mode=args.output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
