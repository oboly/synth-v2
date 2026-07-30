from __future__ import annotations

"""Production projection for the canonical market-only 4h Fibonacci map."""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

from src.market_data.fib_navigation_map_v1 import (
    DIRECTION_BEARISH,
    DIRECTION_BULLISH,
    MAP_STATE_NO_DATA,
    MAP_STATE_STALE,
    FibNavCandle,
    FibNavigationMap,
    PriorMapMeta,
    build_fib_navigation_map,
)
from src.structure.trend_state_v1 import (
    ENGINE_NAME as TREND_ENGINE_NAME,
    ENGINE_VERSION as TREND_ENGINE_VERSION,
    compute_trend_state,
)


MAP_VERSION = "canonical_fib_zone_map_v1"
PRODUCER_NAME = "canonical_fib_zone_map_writer_v1"
PRODUCER_VERSION = "1.1"
SOURCE_FAMILY = "FIB_NAVIGATION_MAP"
LEG_METHOD = f"{TREND_ENGINE_NAME}_v{TREND_ENGINE_VERSION}"
DEFAULT_INTERVAL = "4h"
DEFAULT_LOOKBACK_CANDLES = 180
DEFAULT_STALE_AFTER = timedelta(hours=8)
AVAILABLE_STATES = frozenset({"FRESH", "FALLBACK", "EMERGENCY_REBUILT"})
SAFETY_MARKERS: dict[str, int | str | bool] = {
    "broker_private_calls": 0,
    "broker_writes": 0,
    "order_submission": 0,
    "live_orders": 0,
    "account_awareness": 0,
    "decision_gate": "none",
    "execution_planner": "none",
    "executor": "none",
    "research_inputs": 0,
    "paper_advice_fallback": 0,
}


class CanonicalFibMapError(ValueError):
    pass


@dataclass(frozen=True)
class PublicationBuild:
    venue: str
    quote_currency: str
    interval_code: str
    asof_ts_utc: datetime
    rows: tuple[dict[str, Any], ...]
    content_digest: str
    available_count: int


@dataclass(frozen=True)
class PublicationResult:
    status: str
    publication_id: str
    content_digest: str
    row_count: int
    available_count: int


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _db_ts(value: datetime) -> datetime:
    return _utc(value).replace(tzinfo=None)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _utc(value).isoformat().replace("+00:00", "Z")


def _decimal(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise CanonicalFibMapError(f"invalid decimal value: {value!r}") from exc
    if not result.is_finite():
        raise CanonicalFibMapError(f"non-finite decimal value: {value!r}")
    return result


def _price_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.normalize(), "f")


def _level(map_: FibNavigationMap, label: str) -> Decimal | None:
    for level in (*map_.retracement_levels, *map_.extension_levels):
        if level.label == label:
            return level.price
    return None


def _anchor_times(
    candles: Sequence[FibNavCandle],
    *,
    anchor_low: Decimal,
    anchor_high: Decimal,
    direction: str,
) -> tuple[datetime | None, datetime | None]:
    low_indices = [index for index, candle in enumerate(candles) if candle.low_price == anchor_low]
    high_indices = [index for index, candle in enumerate(candles) if candle.high_price == anchor_high]
    ordered_pairs = [
        (low, high)
        for low in low_indices
        for high in high_indices
        if (
            direction == DIRECTION_BULLISH
            and low <= high
        ) or (
            direction == DIRECTION_BEARISH
            and high <= low
        )
    ]
    if ordered_pairs:
        low_index, high_index = max(
            ordered_pairs,
            key=(
                (lambda pair: (pair[1], pair[0]))
                if direction == DIRECTION_BULLISH
                else (lambda pair: (pair[0], pair[1]))
            ),
        )
        return candles[low_index].close_ts_utc, candles[high_index].close_ts_utc
    return (
        candles[low_indices[-1]].close_ts_utc if low_indices else None,
        candles[high_indices[-1]].close_ts_utc if high_indices else None,
    )


def _prior_from_row(row: Mapping[str, Any] | None) -> PriorMapMeta | None:
    if not row:
        return None
    try:
        low = _decimal(row.get("anchor_low_price"))
        high = _decimal(row.get("anchor_high_price"))
        top = _decimal(row.get("target_extension"))
    except CanonicalFibMapError:
        return None
    candle_ts = row.get("input_latest_candle_ts_utc")
    direction = {
        "UP": DIRECTION_BULLISH,
        "DOWN": DIRECTION_BEARISH,
    }.get(str(row.get("current_leg") or "").upper())
    if (
        not isinstance(candle_ts, datetime)
        or direction is None
        or low <= 0
        or high <= low
    ):
        return None
    return PriorMapMeta(
        map_state=str(row.get("map_status") or ""),
        anchor_low=low,
        anchor_high=high,
        direction=direction,
        top_extension_price=top,
        candle_ts_utc=_utc(candle_ts),
    )


def _unavailable_row(
    *,
    venue: str,
    symbol: str,
    interval_code: str,
    latest_ts: datetime | None,
    reference_price: Decimal | None,
    map_status: str,
    reason: str,
    candle_count: int,
    current_leg: str = "UNKNOWN",
    trend_state: str = "UNKNOWN",
    trend_score: Decimal | None = None,
    direction: str | None = None,
) -> dict[str, Any]:
    freshness = "STALE" if map_status == MAP_STATE_STALE else "UNAVAILABLE"
    return {
        "venue": venue,
        "symbol": symbol,
        "interval_code": interval_code,
        "asof_ts_utc": latest_ts,
        "map_version": MAP_VERSION,
        "map_status": map_status,
        "map_quality": "UNAVAILABLE",
        "source_family": SOURCE_FAMILY,
        "source_ref": "obs_market_candle",
        "source_created_at_utc": latest_ts,
        "reference_price": reference_price,
        "current_leg": current_leg,
        "leg_method": LEG_METHOD,
        "leg_confidence": "UNAVAILABLE",
        "anchor_low_ts_utc": None,
        "anchor_low_price": None,
        "anchor_high_ts_utc": None,
        "anchor_high_price": None,
        "swing_range_abs": None,
        "anchor_move_pct": None,
        "anchor_method": "FIB_NAVIGATION_MAP_V1",
        "anchor_quality": "UNAVAILABLE",
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
        "input_latest_candle_ts_utc": latest_ts,
        "source_freshness_state": freshness,
        "provenance_payload": {
            "algorithm": "src.market_data.fib_navigation_map_v1.build_fib_navigation_map",
            "producer": PRODUCER_NAME,
            "producer_version": PRODUCER_VERSION,
            "reason": reason,
            "candle_count": candle_count,
            "trend_state": trend_state,
            "trend_score": _price_text(trend_score),
            "trend_engine": TREND_ENGINE_NAME,
            "trend_engine_version": TREND_ENGINE_VERSION,
            "map_direction": direction,
            "future_aware_inputs": False,
            "research_inputs": False,
        },
    }


def build_row(
    *,
    venue: str,
    symbol: str,
    interval_code: str,
    candles: Sequence[FibNavCandle],
    now_utc: datetime,
    trend_row: Mapping[str, Any] | None = None,
    prior_row: Mapping[str, Any] | None = None,
    stale_after: timedelta = DEFAULT_STALE_AFTER,
) -> dict[str, Any]:
    ordered = sorted(candles, key=lambda candle: candle.close_ts_utc)
    latest = ordered[-1] if ordered else None
    reference_price = latest.close_price if latest else None
    trend_ts = trend_row.get("close_ts_utc") if trend_row else None
    if latest is None:
        return _unavailable_row(
            venue=venue,
            symbol=symbol,
            interval_code=interval_code,
            latest_ts=None,
            reference_price=None,
            map_status=MAP_STATE_NO_DATA,
            reason="MISSING_CANDLES",
            candle_count=0,
        )
    if not isinstance(trend_ts, datetime) or _utc(trend_ts) != _utc(latest.close_ts_utc):
        return _unavailable_row(
            venue=venue,
            symbol=symbol,
            interval_code=interval_code,
            latest_ts=latest.close_ts_utc,
            reference_price=reference_price,
            map_status=MAP_STATE_NO_DATA,
            reason="MISSING_OR_MISALIGNED_TREND_FEATURE",
            candle_count=len(ordered),
        )
    trend_state, trend_score = compute_trend_state(trend_row)
    direction_and_leg = {
        "UPTREND_STRONG": (DIRECTION_BULLISH, "UP"),
        "UPTREND_WEAK": (DIRECTION_BULLISH, "UP"),
        "DOWNTREND_STRONG": (DIRECTION_BEARISH, "DOWN"),
        "DOWNTREND_WEAK": (DIRECTION_BEARISH, "DOWN"),
    }.get(trend_state)
    if direction_and_leg is None:
        return _unavailable_row(
            venue=venue,
            symbol=symbol,
            interval_code=interval_code,
            latest_ts=latest.close_ts_utc,
            reference_price=reference_price,
            map_status=MAP_STATE_NO_DATA,
            reason="RANGE_STRUCTURE_HAS_NO_DIRECTIONAL_FIB_MAP",
            candle_count=len(ordered),
            current_leg="RANGE" if trend_state == "RANGE" else "UNKNOWN",
            trend_state=trend_state,
            trend_score=trend_score,
        )
    direction, current_leg = direction_and_leg
    prior = _prior_from_row(prior_row)
    if prior is not None and prior.direction != direction:
        prior = None
    map_ = build_fib_navigation_map(
        candles=list(ordered),
        current_price=reference_price,
        now_utc=_utc(now_utc),
        prior=prior,
        direction=direction,
        stale_after=stale_after,
    )
    if map_.map_state in {MAP_STATE_NO_DATA, MAP_STATE_STALE} or not map_.extension_levels:
        return _unavailable_row(
            venue=venue,
            symbol=symbol,
            interval_code=interval_code,
            latest_ts=latest.close_ts_utc if latest else None,
            reference_price=reference_price,
            map_status=map_.map_state,
            reason=map_.rebuild_trigger,
            candle_count=len(ordered),
            current_leg=current_leg,
            trend_state=trend_state,
            trend_score=trend_score,
            direction=map_.direction,
        )
    if map_.direction != direction:
        raise CanonicalFibMapError(
            f"{symbol}: map direction {map_.direction} contradicts {current_leg} structure"
        )

    low_ts, high_ts = _anchor_times(
        ordered,
        anchor_low=map_.anchor_low,
        anchor_high=map_.anchor_high,
        direction=map_.direction,
    )
    r382 = _level(map_, "r_0382")
    r500 = _level(map_, "r_0500")
    r618 = _level(map_, "r_0618")
    r786 = _level(map_, "r_0786")
    invalidation = _level(map_, "r_1000")
    t1 = _level(map_, "ext_1272")
    t2 = _level(map_, "ext_1618")
    extension = _level(map_, "ext_2618")
    required = (r382, r500, r618, r786, invalidation, t1, t2, extension)
    if any(value is None or value <= 0 for value in required):
        raise CanonicalFibMapError(f"{symbol}: canonical builder returned malformed levels")

    move_pct = ((map_.anchor_high - map_.anchor_low) / map_.anchor_low) * Decimal("100")
    return {
        "venue": venue,
        "symbol": symbol,
        "interval_code": interval_code,
        "asof_ts_utc": latest.close_ts_utc if latest else None,
        "map_version": MAP_VERSION,
        "map_status": map_.map_state,
        "map_quality": map_.confidence,
        "source_family": SOURCE_FAMILY,
        "source_ref": "obs_market_candle",
        "source_created_at_utc": latest.close_ts_utc if latest else None,
        "reference_price": reference_price,
        "current_leg": current_leg,
        "leg_method": LEG_METHOD,
        "leg_confidence": map_.confidence,
        "anchor_low_ts_utc": low_ts,
        "anchor_low_price": map_.anchor_low,
        "anchor_high_ts_utc": high_ts,
        "anchor_high_price": map_.anchor_high,
        "swing_range_abs": map_.leg_size,
        "anchor_move_pct": move_pct,
        "anchor_method": "FIB_NAVIGATION_MAP_V1",
        "anchor_quality": map_.confidence,
        "entry_zone_low": min(r382, r618),
        "entry_zone_high": max(r382, r618),
        "entry_zone_mid": r500,
        "entry_zone_method": "FIB_RETRACE_0382_0618",
        "entry_zone_source_field": "FibNavigationMap.retracement_levels",
        "support_reaction_zone_low": min(r618, r786),
        "support_reaction_zone_high": max(r618, r786),
        "support_reaction_method": "FIB_RETRACE_0618_0786",
        "target_t1": t1,
        "target_t2": t2,
        "target_extension": extension,
        "target_method": "FIB_EXTENSION_1272_1618_2618",
        "target_source_field": "FibNavigationMap.extension_levels",
        "invalidation_level": invalidation,
        "invalidation_method": "FIB_RETRACE_1000",
        "invalidation_source_field": "FibNavigationMap.retracement_levels.r_1000",
        "distance_entry_to_target_pct": None,
        "distance_entry_to_invalidation_pct": None,
        "reward_risk_hint": None,
        "input_latest_candle_ts_utc": latest.close_ts_utc if latest else None,
        "source_freshness_state": "FRESH",
        "provenance_payload": {
            "algorithm": "src.market_data.fib_navigation_map_v1.build_fib_navigation_map",
            "producer": PRODUCER_NAME,
            "producer_version": PRODUCER_VERSION,
            "rebuild_trigger": map_.rebuild_trigger,
            "anchor_candle_count": map_.anchor_candle_count,
            "canonical_builder": "FibNavigationMap",
            "map_direction": map_.direction,
            "current_leg": current_leg,
            "trend_state": trend_state,
            "trend_score": _price_text(trend_score),
            "trend_engine": TREND_ENGINE_NAME,
            "trend_engine_version": TREND_ENGINE_VERSION,
            "future_aware_inputs": False,
            "research_inputs": False,
        },
    }


def _semantic_row(row: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in sorted(row.items()):
        if isinstance(value, datetime):
            result[key] = _iso(value)
        elif isinstance(value, Decimal):
            result[key] = _price_text(value)
        else:
            result[key] = value
    return result


def validate_rows(rows: Sequence[Mapping[str, Any]]) -> None:
    symbols = [str(row.get("symbol") or "") for row in rows]
    if not rows or symbols != sorted(symbols) or len(symbols) != len(set(symbols)):
        raise CanonicalFibMapError("rows must contain unique symbols in deterministic order")
    for row in rows:
        if row.get("map_status") in AVAILABLE_STATES:
            for field in (
                "reference_price",
                "anchor_low_price",
                "anchor_high_price",
                "entry_zone_low",
                "entry_zone_high",
                "target_t1",
                "target_t2",
                "target_extension",
                "invalidation_level",
            ):
                value = row.get(field)
                if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
                    raise CanonicalFibMapError(f"{row.get('symbol')}: malformed {field}")
            leg = str(row.get("current_leg") or "").upper()
            provenance = row.get("provenance_payload")
            direction = provenance.get("map_direction") if isinstance(provenance, dict) else None
            expected_direction = {
                "UP": DIRECTION_BULLISH,
                "DOWN": DIRECTION_BEARISH,
            }.get(leg)
            if expected_direction is None or direction != expected_direction:
                raise CanonicalFibMapError(
                    f"{row.get('symbol')}: current_leg and map_direction disagree"
                )
            entry_low = row["entry_zone_low"]
            entry_high = row["entry_zone_high"]
            support_low = row["support_reaction_zone_low"]
            support_high = row["support_reaction_zone_high"]
            target_t1 = row["target_t1"]
            target_t2 = row["target_t2"]
            target_extension = row["target_extension"]
            invalidation = row["invalidation_level"]
            anchor_low = row["anchor_low_price"]
            anchor_high = row["anchor_high_price"]
            if not (
                entry_low <= entry_high
                and support_low <= support_high
                and anchor_low < anchor_high
            ):
                raise CanonicalFibMapError(f"{row.get('symbol')}: malformed directional zones")
            if leg == "UP" and not (
                invalidation == anchor_low
                and anchor_high < target_t1 < target_t2 < target_extension
            ):
                raise CanonicalFibMapError(f"{row.get('symbol')}: inconsistent bullish geometry")
            if leg == "DOWN" and not (
                invalidation == anchor_high
                and target_extension < target_t2 < target_t1 < anchor_low
            ):
                raise CanonicalFibMapError(f"{row.get('symbol')}: inconsistent bearish geometry")
        provenance = row.get("provenance_payload")
        if not isinstance(provenance, dict) or provenance.get("canonical_builder") not in {
            None,
            "FibNavigationMap",
        }:
            raise CanonicalFibMapError(f"{row.get('symbol')}: malformed provenance")


def build_publication(
    *,
    venue: str,
    quote_currency: str,
    interval_code: str,
    symbols: Sequence[str],
    candles_by_symbol: Mapping[str, Sequence[FibNavCandle]],
    trend_rows_by_symbol: Mapping[str, Mapping[str, Any]],
    now_utc: datetime,
    prior_rows_by_symbol: Mapping[str, Mapping[str, Any]] | None = None,
) -> PublicationBuild:
    normalized = sorted({str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()})
    rows = tuple(
        build_row(
            venue=venue,
            symbol=symbol,
            interval_code=interval_code,
            candles=candles_by_symbol.get(symbol, ()),
            now_utc=now_utc,
            trend_row=trend_rows_by_symbol.get(symbol),
            prior_row=(prior_rows_by_symbol or {}).get(symbol),
        )
        for symbol in normalized
    )
    validate_rows(rows)
    asof_candidates = [
        _utc(value)
        for row in rows
        if isinstance((value := row.get("input_latest_candle_ts_utc")), datetime)
    ]
    if not asof_candidates:
        raise CanonicalFibMapError("publication has no source candle timestamp")
    payload = {
        "schema": "canonical_fib_zone_map_publication_v1",
        "venue": venue,
        "quote_currency": quote_currency,
        "interval_code": interval_code,
        "rows": [_semantic_row(row) for row in rows],
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
    return PublicationBuild(
        venue=venue,
        quote_currency=quote_currency,
        interval_code=interval_code,
        asof_ts_utc=max(asof_candidates),
        rows=rows,
        content_digest=digest,
        available_count=sum(row["map_status"] in AVAILABLE_STATES for row in rows),
    )


def fetch_tracked_symbols(conn: Any, *, venue: str, quote_currency: str) -> list[str]:
    sql = """
        SELECT DISTINCT a.symbol
        FROM venue_market vm
        JOIN asset a ON a.asset_id = vm.base_asset_id
        WHERE vm.venue = %s
          AND vm.quote_currency = %s
          AND a.is_enabled = 1
          AND COALESCE(a.is_tradeable, 0) = 1
          AND (COALESCE(a.is_portfolio, 0) = 1 OR COALESCE(a.is_core_sensor, 0) = 1)
        ORDER BY a.symbol
    """
    with conn.cursor() as cur:
        cur.execute(sql, (venue, quote_currency))
        return [str(row["symbol"]).upper() for row in cur.fetchall()]


def fetch_recent_candles(
    conn: Any,
    *,
    venue: str,
    interval_code: str,
    symbols: Sequence[str],
    lookback_candles: int = DEFAULT_LOOKBACK_CANDLES,
) -> dict[str, list[FibNavCandle]]:
    if not symbols:
        return {}
    placeholders = ",".join(["%s"] * len(symbols))
    sql = f"""
        SELECT symbol, close_ts_utc, open_price, high_price, low_price, close_price, volume
        FROM (
            SELECT a.symbol, c.close_ts_utc, c.open_price, c.high_price, c.low_price,
                   c.close_price, c.volume_base AS volume,
                   ROW_NUMBER() OVER (PARTITION BY a.symbol ORDER BY c.close_ts_utc DESC) AS row_num
            FROM obs_market_candle c
            JOIN asset a ON a.asset_id = c.asset_id
            WHERE c.venue = %s
              AND c.interval_code = %s
              AND a.symbol IN ({placeholders})
        ) ranked
        WHERE row_num <= %s
        ORDER BY symbol, close_ts_utc
    """
    with conn.cursor() as cur:
        cur.execute(sql, (venue, interval_code, *symbols, lookback_candles))
        rows = list(cur.fetchall())
    grouped = {symbol: [] for symbol in symbols}
    for row in rows:
        symbol = str(row["symbol"]).upper()
        grouped[symbol].append(
            FibNavCandle(
                close_ts_utc=_utc(row["close_ts_utc"]),
                open_price=_decimal(row["open_price"]),
                high_price=_decimal(row["high_price"]),
                low_price=_decimal(row["low_price"]),
                close_price=_decimal(row["close_price"]),
                volume=_decimal(row.get("volume") or 0),
            )
        )
    return grouped


def fetch_latest_trend_rows(
    conn: Any,
    *,
    venue: str,
    interval_code: str,
    symbols: Sequence[str],
) -> dict[str, dict[str, Any]]:
    if not symbols:
        return {}
    placeholders = ",".join(["%s"] * len(symbols))
    sql = f"""
        SELECT symbol, close_ts_utc, price_vs_ema20, price_vs_ema50, ema_spread_pct
        FROM (
            SELECT a.symbol, fc.close_ts_utc, fc.price_vs_ema20, fc.price_vs_ema50,
                   fc.ema_spread_pct,
                   ROW_NUMBER() OVER (
                       PARTITION BY a.symbol ORDER BY fc.close_ts_utc DESC
                   ) AS row_num
            FROM feat_candle fc
            JOIN asset a ON a.asset_id = fc.asset_id
            WHERE fc.venue = %s
              AND fc.interval_code = %s
              AND a.symbol IN ({placeholders})
        ) ranked
        WHERE row_num = 1
        ORDER BY symbol
    """
    with conn.cursor() as cur:
        cur.execute(sql, (venue, interval_code, *symbols))
        rows = list(cur.fetchall())
    return {
        str(row["symbol"]).upper(): {
            **dict(row),
            "close_ts_utc": _utc(row["close_ts_utc"]),
        }
        for row in rows
    }


def fetch_latest_production_rows(
    conn: Any,
    *,
    venue: str,
    quote_currency: str,
    interval_code: str,
) -> dict[str, dict[str, Any]]:
    sql = """
        SELECT *
        FROM canonical_fib_zone_map_latest_v1
        WHERE venue = %s AND quote_currency = %s AND interval_code = %s
        ORDER BY symbol
    """
    with conn.cursor() as cur:
        cur.execute(sql, (venue, quote_currency, interval_code))
        return {str(row["symbol"]).upper(): dict(row) for row in cur.fetchall()}


def publish(conn: Any, build: PublicationBuild, *, authorization: Any) -> PublicationResult:
    from src.operations.writer_capability_authorization_v1 import (
        require_writer_mutation_authorization,
    )

    require_writer_mutation_authorization(authorization, "native_short_4h_chain")
    publication_id = f"fibnav-{build.content_digest[:32]}"
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT publication_id, content_digest, row_count, available_count
            FROM canonical_fib_zone_map_publication_v1
            WHERE venue=%s AND quote_currency=%s AND interval_code=%s AND asof_ts_utc=%s
            FOR UPDATE
            """,
            (
                build.venue,
                build.quote_currency,
                build.interval_code,
                _db_ts(build.asof_ts_utc),
            ),
        )
        existing = cur.fetchone()
        if existing:
            if str(existing["content_digest"]) != build.content_digest:
                raise CanonicalFibMapError("publication identity collision with different content")
            return PublicationResult(
                status="UNCHANGED",
                publication_id=str(existing["publication_id"]),
                content_digest=build.content_digest,
                row_count=int(existing["row_count"]),
                available_count=int(existing["available_count"]),
            )
        cur.execute(
            """
            INSERT INTO canonical_fib_zone_map_publication_v1
              (publication_id, venue, quote_currency, interval_code, asof_ts_utc,
               map_version, content_digest, row_count, available_count, producer_name, producer_version)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                publication_id,
                build.venue,
                build.quote_currency,
                build.interval_code,
                _db_ts(build.asof_ts_utc),
                MAP_VERSION,
                build.content_digest,
                len(build.rows),
                build.available_count,
                PRODUCER_NAME,
                PRODUCER_VERSION,
            ),
        )
        for row in build.rows:
            cur.execute(
                """
                INSERT INTO canonical_fib_zone_map_v1 (
                  publication_id, venue, symbol, interval_code, asof_ts_utc, map_version,
                  map_status, map_quality, source_family, source_ref, source_created_at_utc,
                  reference_price, current_leg, leg_method, leg_confidence,
                  anchor_low_ts_utc, anchor_low_price, anchor_high_ts_utc, anchor_high_price,
                  swing_range_abs, anchor_move_pct, anchor_method, anchor_quality,
                  entry_zone_low, entry_zone_high, entry_zone_mid, entry_zone_method,
                  entry_zone_source_field, support_reaction_zone_low,
                  support_reaction_zone_high, support_reaction_method, target_t1, target_t2,
                  target_extension, target_method, target_source_field, invalidation_level,
                  invalidation_method, invalidation_source_field, input_latest_candle_ts_utc,
                  source_freshness_state, provenance_payload
                ) VALUES (
                  %(publication_id)s,%(venue)s,%(symbol)s,%(interval_code)s,%(asof_ts_utc)s,
                  %(map_version)s,%(map_status)s,%(map_quality)s,%(source_family)s,%(source_ref)s,
                  %(source_created_at_utc)s,%(reference_price)s,%(current_leg)s,%(leg_method)s,
                  %(leg_confidence)s,%(anchor_low_ts_utc)s,%(anchor_low_price)s,
                  %(anchor_high_ts_utc)s,%(anchor_high_price)s,%(swing_range_abs)s,
                  %(anchor_move_pct)s,%(anchor_method)s,%(anchor_quality)s,%(entry_zone_low)s,
                  %(entry_zone_high)s,%(entry_zone_mid)s,%(entry_zone_method)s,
                  %(entry_zone_source_field)s,%(support_reaction_zone_low)s,
                  %(support_reaction_zone_high)s,%(support_reaction_method)s,%(target_t1)s,
                  %(target_t2)s,%(target_extension)s,%(target_method)s,%(target_source_field)s,
                  %(invalidation_level)s,%(invalidation_method)s,%(invalidation_source_field)s,
                  %(input_latest_candle_ts_utc)s,%(source_freshness_state)s,%(provenance_payload)s
                )
                """,
                {
                    **row,
                    "publication_id": publication_id,
                    "asof_ts_utc": _db_ts(row["asof_ts_utc"] or build.asof_ts_utc),
                    "source_created_at_utc": (
                        _db_ts(row["source_created_at_utc"])
                        if row["source_created_at_utc"]
                        else None
                    ),
                    "anchor_low_ts_utc": (
                        _db_ts(row["anchor_low_ts_utc"]) if row["anchor_low_ts_utc"] else None
                    ),
                    "anchor_high_ts_utc": (
                        _db_ts(row["anchor_high_ts_utc"]) if row["anchor_high_ts_utc"] else None
                    ),
                    "input_latest_candle_ts_utc": (
                        _db_ts(row["input_latest_candle_ts_utc"])
                        if row["input_latest_candle_ts_utc"]
                        else None
                    ),
                    "provenance_payload": json.dumps(
                        row["provenance_payload"],
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                },
            )
    return PublicationResult(
        status="PUBLISHED",
        publication_id=publication_id,
        content_digest=build.content_digest,
        row_count=len(build.rows),
        available_count=build.available_count,
    )
