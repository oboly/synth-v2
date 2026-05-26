from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from src.common.db import get_connection


REPORT_NAME = "position_rotation_preview_v1"
REPORT_VERSION = "0.1"


@dataclass(frozen=True)
class RotationRow:
    trading_account_id: int
    account_code: str
    account_mode: str
    live_trading_enabled: int
    position_symbol: str
    venue: str
    position_snapshot_ts_utc: datetime | None
    position_source_name: str | None
    position_source_age_days: Decimal | None
    position_source_state: str
    quantity_base: Decimal | None
    available_quantity_base: Decimal | None
    reserved_quantity_base: Decimal | None
    average_entry_price_eur: Decimal | None
    position_mark_price_eur: Decimal | None
    position_value_eur: Decimal | None
    paper_asof_ts_utc: datetime | None
    selection_state: str | None
    priority_rank: int | None
    selection_score: Decimal | None
    setup_filter_state: str | None
    setup_filter_reason: str | None
    advice_state: str | None
    advice_action: str | None
    leg_direction: str | None
    entry_zone_low: Decimal | None
    entry_zone_high: Decimal | None
    tp_zone_low: Decimal | None
    tp_zone_high: Decimal | None
    invalidation_price: Decimal | None
    aplus_bucket: str | None
    target_state: str
    risk_state: str
    review_references: list[str]
    rotation_destination_candidates: list[str]
    better_candidates: list[str]
    rotation_state: str
    position_management_state: str
    add_permission_state: str
    add_block_reason: str | None
    hold_context_label: str | None
    entry_alignment_label: str | None
    entry_fib_distance_pct: Decimal | None
    tp_alignment_label: str | None
    tp_fib_distance_pct: Decimal | None
    tp_is_fib_extension_band: int
    entry_is_fib_band: int
    position_lifecycle_action: str
    position_lifecycle_reason: str
    position_lifecycle_source_modules: list[str]
    position_lifecycle_missing_inputs: list[str]
    position_lifecycle_price_vs_entry_pct: Decimal | None
    position_lifecycle_target_distance_pct: Decimal | None
    position_lifecycle_invalidation_distance_pct: Decimal | None
    rotation_pressure_score: int
    reason_codes: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only account-aware position rotation preview v1."
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--trading-account-id", type=int, default=None)
    parser.add_argument("--stale-days", type=Decimal, default=Decimal("1.0"))
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args()


def dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def dec_text(value: Decimal | None, places: str = "0.000000") -> str:
    if value is None:
        return ""
    try:
        return str(value.quantize(Decimal(places)))
    except Exception:
        return str(value)


def dt_text(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.isoformat(sep=" ")


def midpoint_or_edge(low: Decimal | None, high: Decimal | None) -> Decimal | None:
    if low is not None and high is not None:
        return (low + high) / Decimal("2")
    if low is not None:
        return low
    return high


def table_exists(conn: Any, table_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SHOW TABLES LIKE %s", (table_name,))
        return cur.fetchone() is not None


def fib_table_name(conn: Any) -> str:
    for name in ("fib_observation_v2", "fib_observation"):
        if table_exists(conn, name):
            return name
    raise RuntimeError("No fib observation table found")


def pct_distance(reference_price: Decimal | None, target_price: Decimal | None) -> Decimal | None:
    if reference_price is None or target_price is None or reference_price <= 0:
        return None
    return abs(target_price - reference_price) / reference_price * Decimal("100")


def band_overlap(
    low_a: Decimal | None,
    high_a: Decimal | None,
    low_b: Decimal | None,
    high_b: Decimal | None,
) -> bool:
    if None in {low_a, high_a, low_b, high_b}:
        return False
    return max(low_a, low_b) <= min(high_a, high_b)


def nearest_level_distance(
    zone_mid: Decimal | None,
    levels: list[Decimal | None],
) -> Decimal | None:
    if zone_mid is None:
        return None
    distances = [
        pct_distance(level_price, zone_mid)
        for level_price in levels
        if level_price is not None
    ]
    distances = [distance for distance in distances if distance is not None]
    if not distances:
        return None
    return min(distances)


def classify_entry_alignment(
    *,
    entry_type: str | None,
    zone_low: Decimal | None,
    zone_high: Decimal | None,
    fib_0500: Decimal | None,
    fib_0618: Decimal | None,
    fib_0786: Decimal | None,
) -> tuple[str, Decimal | None, int]:
    entry_type_up = str(entry_type or "").upper()
    zone_mid = midpoint_or_edge(zone_low, zone_high)
    nearest_distance = nearest_level_distance(zone_mid, [fib_0500, fib_0618, fib_0786])

    primary_low = min(fib_0500, fib_0618) if fib_0500 is not None and fib_0618 is not None else None
    primary_high = max(fib_0500, fib_0618) if fib_0500 is not None and fib_0618 is not None else None
    deep_low = min(fib_0618, fib_0786) if fib_0618 is not None and fib_0786 is not None else None
    deep_high = max(fib_0618, fib_0786) if fib_0618 is not None and fib_0786 is not None else None

    if (
        entry_type_up == "FIB_RETRACEMENT"
        or band_overlap(zone_low, zone_high, primary_low, primary_high)
    ):
        return "ENTRY_FIB_PRIMARY_0500_0618", nearest_distance, 1
    if entry_type_up == "FIB_DEEP" or band_overlap(zone_low, zone_high, deep_low, deep_high):
        return "ENTRY_FIB_DEEP_0618_0786", nearest_distance, 1
    if entry_type_up or zone_low is not None or zone_high is not None:
        return "ENTRY_SR_ONLY", nearest_distance, 0
    return "ENTRY_UNKNOWN", nearest_distance, 0


def classify_tp_alignment(
    *,
    tp_type: str | None,
    zone_low: Decimal | None,
    zone_high: Decimal | None,
    ext_1272: Decimal | None,
    ext_1618: Decimal | None,
    near_threshold_pct: Decimal = Decimal("1.0"),
) -> tuple[str, Decimal | None, int]:
    tp_type_up = str(tp_type or "").upper()
    zone_mid = midpoint_or_edge(zone_low, zone_high)
    nearest_distance = nearest_level_distance(zone_mid, [ext_1272, ext_1618])
    ext_low = min(ext_1272, ext_1618) if ext_1272 is not None and ext_1618 is not None else None
    ext_high = max(ext_1272, ext_1618) if ext_1272 is not None and ext_1618 is not None else None

    if tp_type_up == "FIB_EXTENSION" or band_overlap(zone_low, zone_high, ext_low, ext_high):
        return "TP_FIB_EXTENSION_1272_1618", nearest_distance, 1
    if nearest_distance is not None and nearest_distance <= near_threshold_pct:
        return "TP_NEAR_FIB_EXTENSION", nearest_distance, 0
    if tp_type_up or zone_low is not None or zone_high is not None:
        return "TP_SR_ONLY", nearest_distance, 0
    return "TP_UNKNOWN", nearest_distance, 0


def target_state_for_advice(
    advice_row: dict[str, Any] | None,
    current_price: Decimal | None,
) -> str:
    if not advice_row or current_price is None or current_price <= 0:
        return "TARGET_UNKNOWN"

    leg_direction = str(advice_row.get("leg_direction") or "").upper()
    target = midpoint_or_edge(dec(advice_row.get("tp_zone_low")), dec(advice_row.get("tp_zone_high")))
    if target is None or leg_direction not in {"UP", "DOWN"}:
        return "TARGET_UNKNOWN"

    if leg_direction == "UP" and current_price >= target:
        return "TARGET_REACHED"
    if leg_direction == "DOWN" and current_price <= target:
        return "TARGET_REACHED"
    return "TARGET_PENDING"


def pct_return_from_entry(
    average_entry_price_eur: Decimal | None,
    current_price: Decimal | None,
) -> Decimal | None:
    if (
        average_entry_price_eur is None
        or current_price is None
        or average_entry_price_eur <= 0
        or current_price <= 0
    ):
        return None
    return ((current_price / average_entry_price_eur) - Decimal("1")) * Decimal("100")


def pct_distance_to_zone(
    zone_low: Decimal | None,
    zone_high: Decimal | None,
    current_price: Decimal | None,
) -> Decimal | None:
    if current_price is None or current_price <= 0:
        return None
    if zone_low is None and zone_high is None:
        return None
    if zone_low is not None and zone_high is not None:
        low = min(zone_low, zone_high)
        high = max(zone_low, zone_high)
        if low <= current_price <= high:
            return Decimal("0")
        reference = low if current_price < low else high
        return abs((current_price / reference) - Decimal("1")) * Decimal("100")
    reference = zone_low if zone_low is not None else zone_high
    if reference is None or reference <= 0:
        return None
    return abs((current_price / reference) - Decimal("1")) * Decimal("100")


def classify_position_lifecycle(
    *,
    position_row: dict[str, Any],
    advice_row: dict[str, Any] | None,
    position_source_state: str,
    current_price: Decimal | None,
    target_state: str,
    risk_state: str,
) -> tuple[str, str, list[str], list[str], Decimal | None, Decimal | None, Decimal | None]:
    source_modules: list[str] = ["account_position_snapshot"]
    missing_inputs: list[str] = []

    quantity = dec(position_row.get("quantity_base"))
    average_entry = dec(position_row.get("average_entry_price_eur"))
    if quantity is None or quantity <= 0:
        missing_inputs.append("MISSING_POSITION")
        return "MISSING_POSITION", "position quantity is missing", source_modules, missing_inputs, None, None, None

    if position_source_state == "STALE":
        return "STALE_POSITION_SOURCE", "position snapshot is stale", source_modules, missing_inputs, None, None, None

    if current_price is None or current_price <= 0:
        missing_inputs.append("MISSING_PRICE")
        return "MISSING_PRICE", "current price is missing", source_modules, missing_inputs, None, None, None

    source_modules.append("market_price_snapshot")

    if advice_row is None:
        missing_inputs.append("MISSING_PAPER_ADVICE")
        return "NO_POSITION_LIFECYCLE_EDGE", "paper advice context is missing", source_modules, missing_inputs, None, None, None

    source_modules.extend(["paper_advice_observation", "execution_zone_context"])

    leg_direction = str(advice_row.get("leg_direction") or "").upper()
    advice_state = str(advice_row.get("advice_state") or "").upper()
    advice_action = str(advice_row.get("advice_action") or "").upper()
    selection_state = str(advice_row.get("selection_state") or "").upper()
    setup_reason = str(advice_row.get("setup_filter_reason") or "").upper()

    entry_zone_low = dec(advice_row.get("entry_zone_low"))
    entry_zone_high = dec(advice_row.get("entry_zone_high"))
    tp_zone_low = dec(advice_row.get("tp_zone_low"))
    tp_zone_high = dec(advice_row.get("tp_zone_high"))
    invalidation_price = dec(advice_row.get("invalidation_price"))

    if average_entry is None or average_entry <= 0:
        missing_inputs.append("MISSING_ENTRY_PRICE")
    if tp_zone_low is None and tp_zone_high is None:
        missing_inputs.append("MISSING_TARGET_ZONE")
    if invalidation_price is None or invalidation_price <= 0:
        missing_inputs.append("MISSING_INVALIDATION")

    price_vs_entry_pct = pct_return_from_entry(average_entry, current_price)
    target_distance_pct = pct_distance_to_zone(tp_zone_low, tp_zone_high, current_price)
    reload_distance_pct = pct_distance_to_zone(entry_zone_low, entry_zone_high, current_price)
    invalidation_distance_pct = pct_distance(reference_price=invalidation_price, target_price=current_price)

    in_profit = price_vs_entry_pct is not None and price_vs_entry_pct > 0
    near_target = target_distance_pct is not None and target_distance_pct <= Decimal("2.0")
    near_reload_zone = reload_distance_pct is not None and reload_distance_pct <= Decimal("2.0")
    target_touch_context = target_state == "TARGET_REACHED" or near_target
    blocked_context = (
        advice_state in {"AVOID", "NO_NEW_BUY", "BLOCK_24H"}
        or advice_action in {"DO_NOT_ADD", "AVOID_NO_NEW_BUY", "BLOCK_NEW_24H_ENTRY"}
        or selection_state == "AVOID"
        or setup_reason == "MARKET_DAMAGE_RISK"
    )
    poor_risk = risk_state in {"RECLAIM_CONFIRMED", "RISK_NEAR"} or leg_direction == "DOWN"

    if blocked_context and poor_risk:
        return (
            "REDUCE_REVIEW",
            "position context is defensive and paper advice risk is poor",
            source_modules,
            missing_inputs,
            price_vs_entry_pct,
            target_distance_pct,
            invalidation_distance_pct,
        )

    if target_touch_context and (in_profit or average_entry is None or average_entry <= 0):
        return (
            "TRIM_REVIEW",
            "price is near or inside target context; review spike-harvest trim manually",
            source_modules,
            missing_inputs,
            price_vs_entry_pct,
            target_distance_pct,
            invalidation_distance_pct,
        )

    if leg_direction == "UP" and target_state == "TARGET_PENDING" and near_reload_zone and not blocked_context:
        return (
            "RELOAD_REVIEW",
            "price is back near the mapped reload or reaction zone",
            source_modules,
            missing_inputs,
            price_vs_entry_pct,
            target_distance_pct,
            invalidation_distance_pct,
        )

    if missing_inputs and target_state == "TARGET_UNKNOWN" and risk_state == "RISK_UNKNOWN":
        return (
            "NO_POSITION_LIFECYCLE_EDGE",
            "position exists but current lifecycle context is incomplete",
            source_modules,
            missing_inputs,
            price_vs_entry_pct,
            target_distance_pct,
            invalidation_distance_pct,
        )

    return (
        "HOLD",
        "position exists but no trim, reload, or reduce edge is visible",
        source_modules,
        missing_inputs,
        price_vs_entry_pct,
        target_distance_pct,
        invalidation_distance_pct,
    )


def risk_state_for_advice(
    advice_row: dict[str, Any] | None,
    current_price: Decimal | None,
    *,
    near_threshold_pct: Decimal = Decimal("2.0"),
) -> str:
    if not advice_row or current_price is None or current_price <= 0:
        return "RISK_UNKNOWN"

    leg_direction = str(advice_row.get("leg_direction") or "").upper()
    invalidation_price = dec(advice_row.get("invalidation_price"))
    if invalidation_price is None or invalidation_price <= 0 or leg_direction not in {"UP", "DOWN"}:
        return "RISK_UNKNOWN"

    if leg_direction == "DOWN" and current_price >= invalidation_price:
        return "RECLAIM_CONFIRMED"

    if leg_direction == "UP":
        distance_pct = ((current_price / invalidation_price) - Decimal("1")) * Decimal("100")
    else:
        distance_pct = ((invalidation_price / current_price) - Decimal("1")) * Decimal("100")

    if distance_pct <= near_threshold_pct:
        return "RISK_NEAR"
    return "RISK_OK"


def fetch_latest_position_rows(
    conn: Any,
    *,
    venue: str,
    trading_account_id: int | None,
    limit: int,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"venue": venue, "limit": int(limit)}
    account_filter = ""
    if trading_account_id is not None:
        account_filter = "AND p.trading_account_id = %(trading_account_id)s"
        params["trading_account_id"] = int(trading_account_id)

    sql = f"""
    WITH latest_position AS (
        SELECT trading_account_id, MAX(snapshot_ts_utc) AS snapshot_ts_utc
        FROM account_position_snapshot
        WHERE venue = %(venue)s
        GROUP BY trading_account_id
    )
    SELECT
        p.snapshot_ts_utc,
        p.trading_account_id,
        ta.account_code,
        ta.account_mode,
        ta.live_trading_enabled,
        p.asset_id,
        p.symbol,
        p.venue,
        p.quantity_base,
        p.available_quantity_base,
        p.reserved_quantity_base,
        p.average_entry_price_eur,
        p.mark_price_eur,
        (p.quantity_base * p.mark_price_eur) AS position_value_eur,
        p.source_name
    FROM account_position_snapshot p
    JOIN latest_position lp
      ON lp.trading_account_id = p.trading_account_id
     AND lp.snapshot_ts_utc = p.snapshot_ts_utc
    JOIN trading_account ta
      ON ta.trading_account_id = p.trading_account_id
    WHERE p.venue = %(venue)s
      AND p.quantity_base > 0
      {account_filter}
    ORDER BY position_value_eur DESC, p.symbol ASC
    LIMIT %(limit)s
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def fetch_latest_paper_advice_rows(
    conn: Any,
    *,
    venue: str,
    interval: str,
) -> dict[str, dict[str, Any]]:
    sql = """
    WITH latest_advice AS (
        SELECT MAX(asof_ts_utc) AS asof_ts_utc
        FROM paper_advice_observation
        WHERE venue = %(venue)s
          AND interval_code = %(interval)s
    )
    SELECT
        p.*
    FROM paper_advice_observation p
    JOIN latest_advice la
      ON la.asof_ts_utc = p.asof_ts_utc
    WHERE p.venue = %(venue)s
      AND p.interval_code = %(interval)s
    """
    with conn.cursor() as cur:
        cur.execute(sql, {"venue": venue, "interval": interval})
        rows = list(cur.fetchall())
    return {str(row["symbol"]).upper(): row for row in rows}


def fetch_latest_zone_fib_context_for_symbol(
    conn: Any,
    *,
    symbol: str,
    venue: str,
    interval: str,
    asof_ts_utc: datetime | None,
) -> dict[str, Any] | None:
    fib_table = fib_table_name(conn)
    reference_ts = asof_ts_utc or datetime.now(UTC).replace(tzinfo=None)

    zone_sql = """
    SELECT
        e.asset_id,
        e.asof_ts_utc,
        e.expected_entry_zone_type AS entry_zone_type,
        e.expected_entry_zone_low AS entry_zone_low,
        e.expected_entry_zone_high AS entry_zone_high,
        e.expected_take_profit_zone_type AS tp_zone_type,
        e.expected_take_profit_zone_low AS tp_zone_low,
        e.expected_take_profit_zone_high AS tp_zone_high
    FROM execution_zone_context e
    JOIN asset a
      ON a.asset_id = e.asset_id
    WHERE a.symbol = %(symbol)s
      AND e.venue = %(venue)s
      AND e.interval_code = %(interval)s
      AND e.asof_ts_utc <= %(reference_ts)s
    ORDER BY e.asof_ts_utc DESC
    LIMIT 1
    """
    with conn.cursor() as cur:
        cur.execute(
            zone_sql,
            {
                "symbol": symbol,
                "venue": venue,
                "interval": interval,
                "reference_ts": reference_ts,
            },
        )
        zone_row = cur.fetchone()

    if not zone_row:
        return None

    fib_sql = f"""
    SELECT
        asof_ts_utc,
        fib_0500_price,
        fib_0618_price,
        fib_0786_price,
        ext_1272_price,
        ext_1618_price
    FROM {fib_table}
    WHERE asset_id = %(asset_id)s
      AND venue = %(venue)s
      AND interval_code = %(interval)s
      AND asof_ts_utc <= %(reference_ts)s
    ORDER BY asof_ts_utc DESC
    LIMIT 1
    """
    with conn.cursor() as cur:
        cur.execute(
            fib_sql,
            {
                "asset_id": zone_row["asset_id"],
                "venue": venue,
                "interval": interval,
                "reference_ts": reference_ts,
            },
        )
        fib_row = cur.fetchone()

    entry_label = "ENTRY_UNKNOWN"
    entry_distance = None
    entry_is_fib_band = 0
    tp_label = "TP_UNKNOWN"
    tp_distance = None
    tp_is_fib_extension_band = 0

    if fib_row:
        entry_label, entry_distance, entry_is_fib_band = classify_entry_alignment(
            entry_type=zone_row.get("entry_zone_type"),
            zone_low=dec(zone_row.get("entry_zone_low")),
            zone_high=dec(zone_row.get("entry_zone_high")),
            fib_0500=dec(fib_row.get("fib_0500_price")),
            fib_0618=dec(fib_row.get("fib_0618_price")),
            fib_0786=dec(fib_row.get("fib_0786_price")),
        )
        tp_label, tp_distance, tp_is_fib_extension_band = classify_tp_alignment(
            tp_type=zone_row.get("tp_zone_type"),
            zone_low=dec(zone_row.get("tp_zone_low")),
            zone_high=dec(zone_row.get("tp_zone_high")),
            ext_1272=dec(fib_row.get("ext_1272_price")),
            ext_1618=dec(fib_row.get("ext_1618_price")),
        )

    return {
        "entry_alignment_label": entry_label,
        "entry_fib_distance_pct": entry_distance,
        "tp_alignment_label": tp_label,
        "tp_fib_distance_pct": tp_distance,
        "tp_is_fib_extension_band": tp_is_fib_extension_band,
        "entry_is_fib_band": entry_is_fib_band,
    }


def fetch_zone_fib_context_by_symbol(
    conn: Any,
    *,
    position_rows: list[dict[str, Any]],
    advice_by_symbol: dict[str, dict[str, Any]],
    venue: str,
    interval: str,
) -> dict[str, dict[str, Any]]:
    context_by_symbol: dict[str, dict[str, Any]] = {}
    for position in position_rows:
        symbol = str(position["symbol"]).upper()
        advice = advice_by_symbol.get(symbol)
        context = fetch_latest_zone_fib_context_for_symbol(
            conn,
            symbol=symbol,
            venue=venue,
            interval=interval,
            asof_ts_utc=None if not advice else advice.get("asof_ts_utc"),
        )
        if context is not None:
            context_by_symbol[symbol] = context
    return context_by_symbol


def classify_position_source(
    *,
    snapshot_ts: datetime | None,
    stale_days: Decimal,
) -> tuple[str, Decimal | None, list[str]]:
    reasons: list[str] = []

    if snapshot_ts is None:
        return "MISSING", None, ["POSITION_SOURCE_MISSING"]

    now = datetime.now(UTC).replace(tzinfo=None)
    age_seconds = Decimal(str((now - snapshot_ts).total_seconds()))
    age_days = age_seconds / Decimal("86400")

    if age_days > stale_days:
        reasons.append("POSITION_SOURCE_STALE")
        return "STALE", age_days, reasons

    reasons.append("POSITION_SOURCE_FRESH")
    return "FRESH", age_days, reasons


def classify_rotation(
    *,
    position_row: dict[str, Any],
    advice_row: dict[str, Any] | None,
    position_source_state: str,
    target_state: str,
    risk_state: str,
) -> tuple[str, int, list[str]]:
    reasons: list[str] = []
    score = 0

    if position_source_state == "STALE":
        reasons.append("POSITION_SOURCE_STALE")
        score += 2
    elif position_source_state == "MISSING":
        reasons.append("POSITION_SOURCE_MISSING")
        return "NO_POSITION_CONTEXT", score, reasons
    else:
        reasons.append("POSITION_SOURCE_FRESH")

    if not advice_row:
        reasons.append("PAPER_ADVICE_MISSING")
        return "REVIEW_ONLY", score + 1, reasons

    selection_state = str(advice_row.get("selection_state") or "").upper()
    setup_state = str(advice_row.get("setup_filter_state") or "").upper()
    setup_reason = str(advice_row.get("setup_filter_reason") or "").upper()
    advice_action = str(advice_row.get("advice_action") or "").upper()
    leg_direction = str(advice_row.get("leg_direction") or "").upper()
    aplus_bucket = str(advice_row.get("aplus_bucket") or "").upper()

    if selection_state:
        reasons.append(f"SELECTION_{selection_state}")
    if setup_state:
        reasons.append(f"SETUP_{setup_state}")
    if setup_reason:
        reasons.append(setup_reason)
    if advice_action:
        reasons.append(f"ADVICE_{advice_action}")
    if leg_direction:
        reasons.append(f"LEG_{leg_direction}")
    if aplus_bucket:
        reasons.append(aplus_bucket)
    reasons.append(target_state)
    reasons.append(risk_state)

    if setup_reason == "MARKET_DAMAGE_RISK":
        score += 4
    elif setup_reason == "MARKET_DAMAGE_CAUTION":
        score += 2

    if advice_action == "WATCH_ONLY":
        score += 2
    elif advice_action == "WAIT":
        score += 1

    if leg_direction == "DOWN":
        score += 2

    if aplus_bucket == "APLUS_AVOID":
        score += 2
    elif aplus_bucket == "APLUS_UNKNOWN":
        score += 1

    if selection_state == "AVOID":
        score += 2
    elif selection_state == "NEUTRAL":
        score += 1
    elif selection_state == "WATCHLIST":
        score -= 1

    if target_state == "TARGET_REACHED":
        score += 3
    elif target_state == "TARGET_UNKNOWN":
        score += 1

    if risk_state == "RECLAIM_CONFIRMED":
        reasons.append("DOWN_MAP_INVALIDATED_BY_RECLAIM")
        reasons.append("MAP_RECOMPUTE_NEEDED")
        score += 2
    elif risk_state == "RISK_NEAR":
        score += 3
    elif risk_state == "RISK_UNKNOWN":
        score += 1

    if risk_state == "RECLAIM_CONFIRMED":
        return "RECLAIM_CONFIRMED_REVIEW", score, reasons

    if position_source_state == "STALE":
        # Stale private-read position data must never escalate to an exit label.
        # It may raise review pressure, but fresh account state is required before
        # any exit/trim-specific downstream workflow.
        if score >= 4:
            return "REDUCE_REVIEW_CANDIDATE_STALE_SOURCE", score, reasons
        return "HOLD_REVIEW_STALE_SOURCE", score, reasons

    if target_state == "TARGET_REACHED":
        if score >= 6:
            return "REDUCE_REVIEW_TARGET_REACHED", score, reasons
        if score >= 4:
            return "TARGET_REACHED_REVIEW", score, reasons
        return "PARTIAL_TP_REVIEW", score, reasons

    if score >= 7:
        return "EXIT_CANDIDATE", score, reasons
    if score >= 4:
        return "REDUCE_CANDIDATE", score, reasons
    if score >= 2:
        return "HOLD_REVIEW", score, reasons

    return "HOLD", score, reasons



def market_candidate_quality_score(advice_row: dict[str, Any] | None) -> Decimal:
    if not advice_row:
        return Decimal("-999")

    score = Decimal("0")
    selection_state = str(advice_row.get("selection_state") or "").upper()
    setup_state = str(advice_row.get("setup_filter_state") or "").upper()
    setup_reason = str(advice_row.get("setup_filter_reason") or "").upper()
    advice_action = str(advice_row.get("advice_action") or "").upper()
    leg_direction = str(advice_row.get("leg_direction") or "").upper()
    aplus_bucket = str(advice_row.get("aplus_bucket") or "").upper()

    selection_score = dec(advice_row.get("selection_score")) or Decimal("0")
    score += selection_score * Decimal("10")

    if selection_state == "WATCHLIST":
        score += Decimal("4")
    elif selection_state == "NEUTRAL":
        score += Decimal("1")
    elif selection_state == "AVOID":
        score -= Decimal("4")

    if setup_state == "PASS":
        score += Decimal("5")
    elif setup_state == "FAIL":
        score -= Decimal("2")

    if setup_reason == "MARKET_DAMAGE_RISK":
        score -= Decimal("5")
    elif setup_reason == "MARKET_DAMAGE_CAUTION":
        score -= Decimal("2")
    elif setup_reason == "SELECTION_STATE_NOT_ELIGIBLE":
        score -= Decimal("2")

    if advice_action in {"BUY_READY", "ACCUMULATE", "BUY"}:
        score += Decimal("5")
    elif advice_action == "WATCH_ONLY":
        score -= Decimal("1")
    elif advice_action == "WAIT":
        score += Decimal("0")

    if leg_direction == "UP":
        score += Decimal("2")
    elif leg_direction == "DOWN":
        score -= Decimal("2")

    if aplus_bucket == "APLUS_AVOID":
        score -= Decimal("4")
    elif aplus_bucket == "APLUS_UNKNOWN":
        score -= Decimal("1")
    elif aplus_bucket.startswith("APLUS_"):
        score += Decimal("1")

    return score


def rank_market_candidates(
    advice_by_symbol: dict[str, dict[str, Any]],
    current_price_by_symbol: dict[str, Decimal] | None = None,
) -> list[tuple[str, Decimal]]:
    ranked: list[tuple[str, Decimal]] = []
    prices = current_price_by_symbol or {}

    for symbol, advice in advice_by_symbol.items():
        selection_state = str(advice.get("selection_state") or "").upper()
        if selection_state == "AVOID":
            continue

        candidate_score = market_candidate_quality_score(advice)
        ranked.append((symbol, candidate_score))

    ranked.sort(key=lambda item: (item[1], item[0]), reverse=True)
    return ranked


def candidate_exclusion_reasons(
    advice_row: dict[str, Any] | None,
    *,
    current_price: Decimal | None,
) -> list[str]:
    if not advice_row:
        return ["ADVICE_MISSING"]

    reasons: list[str] = []
    target_state = target_state_for_advice(advice_row, current_price)
    risk_state = risk_state_for_advice(advice_row, current_price)
    setup_state = str(advice_row.get("setup_filter_state") or "").upper()
    setup_reason = str(advice_row.get("setup_filter_reason") or "").upper()
    advice_action = str(advice_row.get("advice_action") or "").upper()
    aplus_bucket = str(advice_row.get("aplus_bucket") or "").upper()

    if target_state == "TARGET_REACHED":
        reasons.append("TARGET_REACHED")
    if risk_state in {"RISK_NEAR", "RECLAIM_CONFIRMED"}:
        reasons.append(risk_state)
    if aplus_bucket == "APLUS_AVOID":
        reasons.append("APLUS_AVOID")
    if advice_action in {"DO_NOT_ADD", "AVOID_NO_NEW_BUY"}:
        reasons.append(advice_action)
    if setup_reason == "MARKET_DAMAGE_RISK":
        reasons.append("MARKET_DAMAGE_RISK")
    if setup_state != "PASS":
        reasons.append("SETUP_NOT_PASS")

    return reasons


def choose_better_candidates(
    *,
    current_symbol: str,
    current_advice: dict[str, Any] | None,
    ranked_candidates: list[tuple[str, Decimal]],
    advice_by_symbol: dict[str, dict[str, Any]],
    current_price_by_symbol: dict[str, Decimal] | None = None,
    max_items: int = 3,
) -> tuple[list[str], list[str]]:
    current_quality = market_candidate_quality_score(current_advice)
    prices = current_price_by_symbol or {}

    review_references: list[str] = []
    destinations: list[str] = []
    for symbol, candidate_score in ranked_candidates:
        if symbol == current_symbol:
            continue
        if candidate_score <= current_quality:
            continue
        label = f"{symbol}:{candidate_score.quantize(Decimal('0.01'))}"
        review_references.append(label)

        advice = advice_by_symbol.get(symbol)
        exclusions = candidate_exclusion_reasons(
            advice,
            current_price=prices.get(symbol),
        )
        if not exclusions:
            destinations.append(label)

        if len(review_references) >= max_items and len(destinations) >= max_items:
            break

    return review_references[:max_items], destinations[:max_items]


def derive_position_management_fields(
    *,
    advice_row: dict[str, Any] | None,
    rotation_state: str,
    target_state: str,
    risk_state: str,
) -> tuple[str, str, str | None, str | None]:
    if rotation_state == "HOLD":
        position_management_state = "HOLD_EXISTING"
    else:
        position_management_state = rotation_state

    if not advice_row:
        add_permission_state = "DO_NOT_ADD"
        add_block_reason = "PAPER_ADVICE_MISSING"
    else:
        selection_state = str(advice_row.get("selection_state") or "").upper()
        setup_state = str(advice_row.get("setup_filter_state") or "").upper()
        advice_action = str(advice_row.get("advice_action") or "").upper()
        aplus_bucket = str(advice_row.get("aplus_bucket") or "").upper()

        if risk_state == "RECLAIM_CONFIRMED":
            add_permission_state = "ADD_REVIEW_AFTER_RECOMPUTE"
            add_block_reason = "RECLAIM_CONFIRMED"
        elif aplus_bucket == "APLUS_AVOID":
            add_permission_state = "DO_NOT_ADD"
            add_block_reason = "APLUS_AVOID"
        elif setup_state == "FAIL":
            add_permission_state = "DO_NOT_ADD"
            add_block_reason = "SETUP_FAIL"
        elif selection_state == "AVOID":
            add_permission_state = "DO_NOT_ADD"
            add_block_reason = "SELECTION_AVOID"
        elif advice_action in {"DO_NOT_ADD", "AVOID_NO_NEW_BUY", "WATCH_ONLY", "WAIT"}:
            add_permission_state = "DO_NOT_ADD"
            add_block_reason = advice_action or "ADVICE_BLOCKED"
        elif advice_action in {"BUY_READY", "ACCUMULATE", "BUY"} and setup_state == "PASS" and selection_state != "AVOID":
            add_permission_state = "ADD_REVIEW"
            add_block_reason = None
        else:
            add_permission_state = "DO_NOT_ADD"
            add_block_reason = "ADVICE_NOT_ADD_READY"

    hold_context_label: str | None = None
    if target_state == "TARGET_REACHED":
        hold_context_label = "TARGET_REACHED_REVIEW"
    elif target_state == "TARGET_PENDING":
        hold_context_label = "HOLD_WITH_REACTION_TARGET_PENDING"

    return position_management_state, add_permission_state, add_block_reason, hold_context_label



def build_rows(
    position_rows: list[dict[str, Any]],
    advice_by_symbol: dict[str, dict[str, Any]],
    *,
    stale_days: Decimal,
    current_price_by_symbol: dict[str, Decimal] | None = None,
    zone_fib_context_by_symbol: dict[str, dict[str, Any]] | None = None,
) -> list[RotationRow]:
    out: list[RotationRow] = []
    prices = current_price_by_symbol or {}
    zone_fib_context = zone_fib_context_by_symbol or {}
    ranked_candidates = rank_market_candidates(advice_by_symbol, prices)

    for position in position_rows:
        symbol = str(position["symbol"]).upper()
        advice = advice_by_symbol.get(symbol)
        current_price = prices.get(symbol) or dec(position.get("mark_price_eur"))
        target_state = target_state_for_advice(advice, current_price)
        risk_state = risk_state_for_advice(advice, current_price)
        source_state, source_age_days, source_reasons = classify_position_source(
            snapshot_ts=position.get("snapshot_ts_utc"),
            stale_days=stale_days,
        )
        rotation_state, pressure_score, rotation_reasons = classify_rotation(
            position_row=position,
            advice_row=advice,
            position_source_state=source_state,
            target_state=target_state,
            risk_state=risk_state,
        )
        reason_codes = list(dict.fromkeys(source_reasons + rotation_reasons))
        review_references, rotation_destination_candidates = choose_better_candidates(
            current_symbol=symbol,
            current_advice=advice,
            ranked_candidates=ranked_candidates,
            advice_by_symbol=advice_by_symbol,
            current_price_by_symbol=prices,
        )
        (
            position_management_state,
            add_permission_state,
            add_block_reason,
            hold_context_label,
        ) = derive_position_management_fields(
            advice_row=advice,
            rotation_state=rotation_state,
            target_state=target_state,
            risk_state=risk_state,
        )
        (
            position_lifecycle_action,
            position_lifecycle_reason,
            position_lifecycle_source_modules,
            position_lifecycle_missing_inputs,
            position_lifecycle_price_vs_entry_pct,
            position_lifecycle_target_distance_pct,
            position_lifecycle_invalidation_distance_pct,
        ) = classify_position_lifecycle(
            position_row=position,
            advice_row=advice,
            position_source_state=source_state,
            current_price=current_price,
            target_state=target_state,
            risk_state=risk_state,
        )
        if review_references:
            reason_codes.append("REVIEW_REFERENCES_AVAILABLE")
        else:
            reason_codes.append("NO_REVIEW_REFERENCES_FOUND")
        if rotation_destination_candidates:
            reason_codes.append("ROTATION_DESTINATION_CANDIDATES_AVAILABLE")
        else:
            reason_codes.append("NO_ROTATION_DESTINATION_CANDIDATES_FOUND")
        alignment_context = zone_fib_context.get(symbol, {})

        out.append(
            RotationRow(
                trading_account_id=int(position["trading_account_id"]),
                account_code=str(position.get("account_code") or ""),
                account_mode=str(position.get("account_mode") or ""),
                live_trading_enabled=int(position.get("live_trading_enabled") or 0),
                position_symbol=symbol,
                venue=str(position["venue"]),
                position_snapshot_ts_utc=position.get("snapshot_ts_utc"),
                position_source_name=position.get("source_name"),
                position_source_age_days=source_age_days,
                position_source_state=source_state,
                quantity_base=dec(position.get("quantity_base")),
                available_quantity_base=dec(position.get("available_quantity_base")),
                reserved_quantity_base=dec(position.get("reserved_quantity_base")),
                average_entry_price_eur=dec(position.get("average_entry_price_eur")),
                position_mark_price_eur=dec(position.get("mark_price_eur")),
                position_value_eur=dec(position.get("position_value_eur")),
                paper_asof_ts_utc=None if not advice else advice.get("asof_ts_utc"),
                selection_state=None if not advice else advice.get("selection_state"),
                priority_rank=None
                if not advice or advice.get("priority_rank") is None
                else int(advice.get("priority_rank")),
                selection_score=None if not advice else dec(advice.get("selection_score")),
                setup_filter_state=None if not advice else advice.get("setup_filter_state"),
                setup_filter_reason=None if not advice else advice.get("setup_filter_reason"),
                advice_state=None if not advice else advice.get("advice_state"),
                advice_action=None if not advice else advice.get("advice_action"),
                leg_direction=None if not advice else advice.get("leg_direction"),
                entry_zone_low=None if not advice else dec(advice.get("entry_zone_low")),
                entry_zone_high=None if not advice else dec(advice.get("entry_zone_high")),
                tp_zone_low=None if not advice else dec(advice.get("tp_zone_low")),
                tp_zone_high=None if not advice else dec(advice.get("tp_zone_high")),
                invalidation_price=None if not advice else dec(advice.get("invalidation_price")),
                aplus_bucket=None if not advice else advice.get("aplus_bucket"),
                target_state=target_state,
                risk_state=risk_state,
                review_references=review_references,
                rotation_destination_candidates=rotation_destination_candidates,
                better_candidates=review_references,
                rotation_state=rotation_state,
                position_management_state=position_management_state,
                add_permission_state=add_permission_state,
                add_block_reason=add_block_reason,
                hold_context_label=hold_context_label,
                entry_alignment_label=alignment_context.get("entry_alignment_label"),
                entry_fib_distance_pct=alignment_context.get("entry_fib_distance_pct"),
                tp_alignment_label=alignment_context.get("tp_alignment_label"),
                tp_fib_distance_pct=alignment_context.get("tp_fib_distance_pct"),
                tp_is_fib_extension_band=int(alignment_context.get("tp_is_fib_extension_band") or 0),
                entry_is_fib_band=int(alignment_context.get("entry_is_fib_band") or 0),
                position_lifecycle_action=position_lifecycle_action,
                position_lifecycle_reason=position_lifecycle_reason,
                position_lifecycle_source_modules=position_lifecycle_source_modules,
                position_lifecycle_missing_inputs=position_lifecycle_missing_inputs,
                position_lifecycle_price_vs_entry_pct=position_lifecycle_price_vs_entry_pct,
                position_lifecycle_target_distance_pct=position_lifecycle_target_distance_pct,
                position_lifecycle_invalidation_distance_pct=position_lifecycle_invalidation_distance_pct,
                rotation_pressure_score=pressure_score,
                reason_codes=reason_codes,
            )
        )

    return out


def serialize_row(row: RotationRow) -> dict[str, Any]:
    data = asdict(row)
    for key, value in list(data.items()):
        if isinstance(value, Decimal):
            data[key] = str(value)
        elif isinstance(value, datetime):
            data[key] = value.isoformat(sep=" ")
    return data


def print_table(rows: list[RotationRow]) -> None:
    headers = [
        "symbol",
        "value_eur",
        "qty",
        "entry_px",
        "src",
        "age_d",
        "selection",
        "setup_reason",
        "leg",
        "action",
        "target_state",
        "risk_state",
        "position_mgmt",
        "add_permission",
        "hold_context",
        "lifecycle",
        "entry_align",
        "tp_align",
        "tp_zone",
        "rotation",
        "score",
        "review_refs",
        "destinations",
    ]

    table: list[list[str]] = []
    for row in rows:
        tp_zone = ""
        if row.tp_zone_low is not None or row.tp_zone_high is not None:
            tp_zone = f"{dec_text(row.tp_zone_low, '0.000000')}..{dec_text(row.tp_zone_high, '0.000000')}"
        table.append(
            [
                row.position_symbol,
                dec_text(row.position_value_eur, "0.01"),
                dec_text(row.quantity_base, "0.000000"),
                dec_text(row.average_entry_price_eur, "0.000000"),
                row.position_source_state,
                dec_text(row.position_source_age_days, "0.01"),
                row.selection_state or "",
                row.setup_filter_reason or "",
                row.leg_direction or "",
                row.advice_action or "",
                row.target_state,
                row.risk_state,
                row.position_management_state,
                row.add_permission_state,
                row.hold_context_label or "",
                row.position_lifecycle_action,
                row.entry_alignment_label or "",
                row.tp_alignment_label or "",
                tp_zone,
                row.rotation_state,
                str(row.rotation_pressure_score),
                ",".join(row.review_references[:3]),
                ",".join(row.rotation_destination_candidates[:3]),
            ]
        )

    widths = [
        max(len(headers[i]), *(len(row[i]) for row in table)) if table else len(headers[i])
        for i in range(len(headers))
    ]

    def fmt(row: list[str]) -> str:
        return " | ".join(row[i].ljust(widths[i]) for i in range(len(row)))

    print(fmt(headers))
    print("-+-".join("-" * w for w in widths))
    for row in table:
        print(fmt(row))


def emit_report_header(*, rows: list[RotationRow], args: argparse.Namespace) -> None:
    state_counts: dict[str, int] = {}
    for row in rows:
        state_counts[row.rotation_state] = state_counts.get(row.rotation_state, 0) + 1

    print(f"report={REPORT_NAME} version={REPORT_VERSION}", file=sys.stderr)
    print("scope=read-only account-aware rotation preview", file=sys.stderr)
    print(
        "broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0 db_writes=0",
        file=sys.stderr,
    )
    print("decision_gate=none execution_planner=none executor=none", file=sys.stderr)
    print(f"venue={args.venue} interval={args.interval}", file=sys.stderr)
    print(f"rows={len(rows)} stale_days={args.stale_days}", file=sys.stderr)
    print(f"state_counts={json.dumps(state_counts, sort_keys=True)}", file=sys.stderr)
    print(file=sys.stderr)


def main() -> int:
    args = parse_args()

    conn = get_connection()
    try:
        position_rows = fetch_latest_position_rows(
            conn,
            venue=args.venue,
            trading_account_id=args.trading_account_id,
            limit=args.limit,
        )
        advice_by_symbol = fetch_latest_paper_advice_rows(
            conn,
            venue=args.venue,
            interval=args.interval,
        )
        zone_fib_context_by_symbol = fetch_zone_fib_context_by_symbol(
            conn,
            position_rows=position_rows,
            advice_by_symbol=advice_by_symbol,
            venue=args.venue,
            interval=args.interval,
        )
    finally:
        conn.close()

    rows = build_rows(
        position_rows,
        advice_by_symbol,
        stale_days=args.stale_days,
        zone_fib_context_by_symbol=zone_fib_context_by_symbol,
    )

    if args.output == "json":
        print(json.dumps([serialize_row(row) for row in rows], indent=2, sort_keys=True))
    else:
        emit_report_header(rows=rows, args=args)
        print_table(rows)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
