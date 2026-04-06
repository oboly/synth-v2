from __future__ import annotations

from datetime import datetime, UTC
from decimal import Decimal

from src.common.db import db_cursor
from src.market_structure.models import StrategySignalContext


DECIMAL_ZERO = Decimal("0")
BPS = Decimal("10000")
NEAR_ZONE_BPS = Decimal("150")


def _bps(current: Decimal, ref: Decimal) -> Decimal:
    if current == DECIMAL_ZERO:
        return Decimal("999999")
    return abs(current - ref) / current * BPS


def _fetch_latest_closes(intervals: list[str]) -> list[dict]:
    placeholders = ", ".join(["%s"] * len(intervals))
    sql = f"""
    SELECT
        x.asset_id,
        x.interval_code,
        x.close_price
    FROM (
        SELECT
            c.asset_id,
            c.interval_code,
            c.close_price,
            ROW_NUMBER() OVER (
                PARTITION BY c.asset_id, c.interval_code
                ORDER BY c.close_ts_utc DESC
            ) AS rn
        FROM obs_market_candle c
        WHERE c.interval_code IN ({placeholders})
    ) x
    WHERE x.rn = 1
    """
    with db_cursor(commit=False) as (_conn, cur):
        cur.execute(sql, intervals)
        return cur.fetchall()


def _fetch_zones() -> list[dict]:
    sql = """
    SELECT
        asset_id,
        interval_code,
        zone_type,
        zone_low,
        zone_high,
        zone_strength
    FROM zone_observation
    WHERE is_active = 1
    """
    with db_cursor(commit=False) as (_conn, cur):
        cur.execute(sql)
        return cur.fetchall()


def _fetch_latest_volume_map() -> dict[tuple[int, str], dict]:
    sql = """
    SELECT
        asset_id,
        '1d' AS interval_code,
        vc_volume_ratio_7d AS volume_ratio,
        vc_volume_zscore_7d AS volume_zscore
    FROM v_latest_volume_confirmation
    """

    with db_cursor(commit=False) as (_conn, cur):
        cur.execute(sql)
        rows = cur.fetchall()

    out: dict[tuple[int, str], dict] = {}
    for row in rows:
        out[(int(row["asset_id"]), str(row["interval_code"]))] = {
            "volume_ratio": Decimal(str(row["volume_ratio"])) if row["volume_ratio"] is not None else None,
            "volume_zscore": Decimal(str(row["volume_zscore"])) if row["volume_zscore"] is not None else None,
        }
    return out


def _fetch_nearest_fib_map(interval_code: str) -> dict[tuple[int, str], dict]:
    sql = """
    SELECT
        t.asset_id,
        t.interval_code,
        t.fib_level,
        t.fib_price,
        t.distance_bps,
        t.confluence_score
    FROM (
        SELECT
            f.asset_id,
            f.interval_code,
            f.fib_level,
            f.fib_price,
            f.confluence_score,
            ABS((c.close_price - f.fib_price) / c.close_price) * 10000 AS distance_bps,
            ROW_NUMBER() OVER (
                PARTITION BY f.asset_id, f.interval_code
                ORDER BY ABS(c.close_price - f.fib_price)
            ) AS rn
        FROM fib_observation f
        JOIN (
            SELECT
                x.asset_id,
                x.interval_code,
                x.close_price
            FROM (
                SELECT
                    c.asset_id,
                    c.interval_code,
                    c.close_price,
                    ROW_NUMBER() OVER (
                        PARTITION BY c.asset_id, c.interval_code
                        ORDER BY c.close_ts_utc DESC
                    ) AS rn
                FROM obs_market_candle c
                WHERE c.interval_code = %s
            ) x
            WHERE x.rn = 1
        ) c
            ON c.asset_id = f.asset_id
           AND c.interval_code = f.interval_code
        WHERE f.is_active = 1
          AND f.interval_code = %s
    ) t
    WHERE t.rn = 1
    """

    with db_cursor(commit=False) as (_conn, cur):
        cur.execute(sql, (interval_code, interval_code))
        rows = cur.fetchall()

    out: dict[tuple[int, str], dict] = {}
    for r in rows:
        out[(int(r["asset_id"]), str(r["interval_code"]))] = {
            "fib_level": Decimal(str(r["fib_level"])),
            "fib_price": Decimal(str(r["fib_price"])),
            "fib_distance_bps": Decimal(str(r["distance_bps"])),
            "fib_confluence_score_raw": Decimal(str(r["confluence_score"])),
        }
    return out


def _classify_volume_state(volume_ratio: Decimal | None, volume_zscore: Decimal | None) -> str | None:
    if volume_ratio is None or volume_zscore is None:
        return None
    if volume_ratio > Decimal("1.5") and volume_zscore > Decimal("1.0"):
        return "HIGH_EXPANSION"
    if volume_ratio < Decimal("0.7") and volume_zscore < Decimal("-0.5"):
        return "LOW_ACTIVITY"
    return "NORMAL"


def _compute_volume_alignment(volume_ratio: Decimal | None, volume_zscore: Decimal | None) -> Decimal | None:
    if volume_ratio is None or volume_zscore is None:
        return None

    score = Decimal("0")

    if volume_ratio > Decimal("1.2"):
        score += Decimal("0.5")
    if volume_zscore > Decimal("1.0"):
        score += Decimal("0.5")
    if volume_ratio < Decimal("0.8"):
        score -= Decimal("0.5")

    return score


def _in_zone(price: Decimal, zone_low: Decimal, zone_high: Decimal) -> bool:
    return zone_low <= price <= zone_high


def _best_zone_strength(zones: list[dict]) -> Decimal:
    if not zones:
        return DECIMAL_ZERO
    return max(Decimal(str(z["zone_strength"])) for z in zones)


def _nearest_support_metrics(price: Decimal, support_zones: list[dict]) -> tuple[Decimal | None, Decimal | None]:
    if not support_zones:
        return None, None

    best = min(support_zones, key=lambda z: abs(price - Decimal(str(z["zone_high"]))))
    ref = Decimal(str(best["zone_high"]))

    distance = max(DECIMAL_ZERO, price - ref)
    distance_bps = Decimal("0") if _in_zone(price, Decimal(str(best["zone_low"])), Decimal(str(best["zone_high"]))) else _bps(price, ref)
    return distance, distance_bps


def _nearest_resistance_metrics(price: Decimal, resistance_zones: list[dict]) -> tuple[Decimal | None, Decimal | None]:
    if not resistance_zones:
        return None, None

    best = min(resistance_zones, key=lambda z: abs(price - Decimal(str(z["zone_low"]))))
    ref = Decimal(str(best["zone_low"]))

    distance = max(DECIMAL_ZERO, ref - price)
    distance_bps = Decimal("0") if _in_zone(price, Decimal(str(best["zone_low"])), Decimal(str(best["zone_high"]))) else _bps(price, ref)
    return distance, distance_bps


def _compute_zone_context(
    current_close: Decimal,
    support_zones: list[dict],
    resistance_zones: list[dict],
) -> tuple[str, Decimal, Decimal | None, Decimal | None, Decimal | None, Decimal | None]:
    distance_to_support, distance_to_support_bps = _nearest_support_metrics(current_close, support_zones)
    distance_to_resistance, distance_to_resistance_bps = _nearest_resistance_metrics(current_close, resistance_zones)

    at_support = [
        z for z in support_zones
        if _in_zone(current_close, Decimal(str(z["zone_low"])), Decimal(str(z["zone_high"])))
    ]
    at_resistance = [
        z for z in resistance_zones
        if _in_zone(current_close, Decimal(str(z["zone_low"])), Decimal(str(z["zone_high"])))
    ]

    if at_support:
        return (
            "AT_SUPPORT",
            _best_zone_strength(at_support),
            distance_to_support,
            distance_to_resistance,
            distance_to_support_bps,
            distance_to_resistance_bps,
        )

    if at_resistance:
        return (
            "AT_RESISTANCE",
            _best_zone_strength(at_resistance),
            distance_to_support,
            distance_to_resistance,
            distance_to_support_bps,
            distance_to_resistance_bps,
        )

    if distance_to_support_bps is not None and distance_to_support_bps <= NEAR_ZONE_BPS:
        return (
            "NEAR_SUPPORT",
            Decimal("0.5"),
            distance_to_support,
            distance_to_resistance,
            distance_to_support_bps,
            distance_to_resistance_bps,
        )

    if distance_to_resistance_bps is not None and distance_to_resistance_bps <= NEAR_ZONE_BPS:
        return (
            "NEAR_RESISTANCE",
            Decimal("0.5"),
            distance_to_support,
            distance_to_resistance,
            distance_to_support_bps,
            distance_to_resistance_bps,
        )

    return (
        "NONE",
        DECIMAL_ZERO,
        distance_to_support,
        distance_to_resistance,
        distance_to_support_bps,
        distance_to_resistance_bps,
    )


def _fib_state(distance_bps: Decimal | None) -> str:
    if distance_bps is None:
        return "NO_FIB"
    if distance_bps <= Decimal("5"):
        return "AT_FIB"
    if distance_bps <= Decimal("50"):
        return "NEAR_FIB"
    return "FAR_FROM_FIB"


def _fib_confluence(zone_state: str, fib_confluence_raw: Decimal | None, fib_distance_bps: Decimal | None) -> Decimal:
    if fib_confluence_raw is None or fib_distance_bps is None:
        return DECIMAL_ZERO

    if fib_distance_bps > Decimal("100"):
        return DECIMAL_ZERO

    distance_factor = max(DECIMAL_ZERO, Decimal("1") - (fib_distance_bps / Decimal("100")))
    zone_bonus = Decimal("1.0") if zone_state in ("AT_SUPPORT", "AT_RESISTANCE", "NEAR_SUPPORT", "NEAR_RESISTANCE") else Decimal("0.5")
    return fib_confluence_raw * distance_factor * zone_bonus


def _normalize_component(value: Decimal | None, floor: Decimal, ceil: Decimal) -> Decimal:
    if value is None:
        return DECIMAL_ZERO
    if value <= floor:
        return DECIMAL_ZERO
    if value >= ceil:
        return Decimal("1")
    return (value - floor) / (ceil - floor)


def _composite_context_score(
    zone_confluence_score: Decimal,
    fib_confluence_score: Decimal,
    volume_alignment_score: Decimal | None,
) -> Decimal:
    zone_component = _normalize_component(zone_confluence_score, Decimal("0"), Decimal("1"))
    fib_component = _normalize_component(fib_confluence_score, Decimal("0"), Decimal("1"))
    volume_component = _normalize_component(volume_alignment_score, Decimal("-0.5"), Decimal("1.0"))

    score = (
        zone_component * Decimal("0.40")
        + fib_component * Decimal("0.40")
        + volume_component * Decimal("0.20")
    )

    return score.quantize(Decimal("0.00000001"))


def build_strategy_context_from_volume_and_zones() -> list[StrategySignalContext]:
    closes = _fetch_latest_closes(["4h", "1d"])
    zones = _fetch_zones()

    fib_maps = {
        "1d": _fetch_nearest_fib_map("1d"),
        "4h": _fetch_nearest_fib_map("4h"),
    }
    volume_map = _fetch_latest_volume_map()

    zone_map: dict[tuple[int, str], dict[str, list[dict]]] = {}
    for z in zones:
        key = (int(z["asset_id"]), str(z["interval_code"]))
        zone_map.setdefault(key, {"support": [], "resistance": []})
        zone_map[key][str(z["zone_type"])].append(z)

    now = datetime.now(UTC).replace(tzinfo=None)
    out: list[StrategySignalContext] = []

    for c in closes:
        asset_id = int(c["asset_id"])
        interval_code = str(c["interval_code"])
        current_close = Decimal(str(c["close_price"]))

        bucket = zone_map.get((asset_id, interval_code), {"support": [], "resistance": []})

        (
            zone_state,
            zone_confluence_score,
            distance_to_support,
            distance_to_resistance,
            distance_to_support_bps,
            distance_to_resistance_bps,
        ) = _compute_zone_context(
            current_close=current_close,
            support_zones=bucket["support"],
            resistance_zones=bucket["resistance"],
        )

        fib_data = fib_maps.get(interval_code, {}).get((asset_id, interval_code))
        fib_level = fib_data["fib_level"] if fib_data else None
        fib_price = fib_data["fib_price"] if fib_data else None
        fib_distance_bps = fib_data["fib_distance_bps"] if fib_data else None
        fib_state = _fib_state(fib_distance_bps)
        fib_confluence_score = _fib_confluence(
            zone_state=zone_state,
            fib_confluence_raw=fib_data["fib_confluence_score_raw"] if fib_data else None,
            fib_distance_bps=fib_distance_bps,
        )

        vol = volume_map.get((asset_id, "1d"))
        volume_ratio = vol["volume_ratio"] if vol else None
        volume_zscore = vol["volume_zscore"] if vol else None
        volume_state = _classify_volume_state(volume_ratio, volume_zscore)
        volume_alignment_score = _compute_volume_alignment(volume_ratio, volume_zscore)

        context_score = _composite_context_score(
            zone_confluence_score=zone_confluence_score,
            fib_confluence_score=fib_confluence_score,
            volume_alignment_score=volume_alignment_score,
        )

        out.append(
            StrategySignalContext(
                asset_id=asset_id,
                interval_code=interval_code,
                context_ts_utc=now,
                zone_state=zone_state,
                fib_state=fib_state,
                wave_label=None,
                wave_confidence=None,
                zone_confluence_score=zone_confluence_score,
                fib_confluence_score=fib_confluence_score,
                context_score=context_score,
                volume_ratio=volume_ratio,
                volume_zscore=volume_zscore,
                volume_state=volume_state,
                volume_alignment_score=volume_alignment_score,
                distance_to_support=distance_to_support,
                distance_to_resistance=distance_to_resistance,
                distance_to_support_bps=distance_to_support_bps,
                distance_to_resistance_bps=distance_to_resistance_bps,
                fib_level=fib_level,
                fib_price=fib_price,
                fib_distance_bps=fib_distance_bps,
            )
        )

    return out
