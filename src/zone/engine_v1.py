from __future__ import annotations

from decimal import Decimal

from src.zone.models import (
    CandleRow,
    ExecutionZoneContextInput,
    FibObservationInput,
    SwingPoint,
    ZoneEngineResult,
    ZoneObservationInput,
)
from src.zone.repository import ZoneRepository


def _quant_price(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0000000001"))


def _quant_score(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.00000001"))


def _pct_change(start_price: Decimal, end_price: Decimal) -> Decimal:
    if start_price == 0:
        return Decimal("0")
    return _quant_score((end_price - start_price) / start_price)


def _mid(low_price: Decimal, high_price: Decimal) -> Decimal:
    return _quant_price((low_price + high_price) / Decimal("2"))


def _width_pct(low_price: Decimal, high_price: Decimal) -> Decimal:
    mid = _mid(low_price, high_price)
    if mid == 0:
        return Decimal("0")
    return _quant_score((high_price - low_price) / mid)


def _price_from_leg(start_price: Decimal, end_price: Decimal, ratio: str) -> Decimal:
    r = Decimal(ratio)
    move = end_price - start_price
    return _quant_price(end_price - (move * r))


def _extension_from_leg(start_price: Decimal, end_price: Decimal, ratio: str) -> Decimal:
    r = Decimal(ratio)
    move = end_price - start_price
    return _quant_price(end_price + (move * (r - Decimal("1.0"))))


def _detect_swings(candles: list[CandleRow], swing_window: int) -> list[SwingPoint]:
    if len(candles) < (swing_window * 2 + 1):
        return []

    out: list[SwingPoint] = []
    for i in range(swing_window, len(candles) - swing_window):
        center = candles[i]
        prevs = candles[i - swing_window : i]
        nexts = candles[i + 1 : i + 1 + swing_window]

        is_swing_high = all(center.high_price > c.high_price for c in prevs + nexts)
        is_swing_low = all(center.low_price < c.low_price for c in prevs + nexts)

        if is_swing_high:
            out.append(
                SwingPoint(
                    point_type="SWING_HIGH",
                    ts_utc=center.open_ts_utc,
                    price=center.high_price,
                    index=i,
                )
            )
        if is_swing_low:
            out.append(
                SwingPoint(
                    point_type="SWING_LOW",
                    ts_utc=center.open_ts_utc,
                    price=center.low_price,
                    index=i,
                )
            )

    out.sort(key=lambda x: (x.index, x.point_type))
    return out


def _latest_alternating_leg(swings: list[SwingPoint]) -> tuple[SwingPoint, SwingPoint] | None:
    if len(swings) < 2:
        return None

    for i in range(len(swings) - 1, 0, -1):
        right = swings[i]
        left = swings[i - 1]
        if left.point_type != right.point_type and left.index < right.index:
            return left, right

    return None


def _cluster_recent_sr_zone(
    swings: list[SwingPoint],
    *,
    zone_type: str,
    tolerance_bps: Decimal,
    max_points: int = 5,
) -> tuple[Decimal, Decimal, int] | None:
    filtered = [s for s in swings if s.point_type == zone_type]
    if not filtered:
        return None

    filtered = filtered[-max_points:]
    anchor = filtered[-1].price
    tol = anchor * (tolerance_bps / Decimal("10000"))

    cluster = [s for s in filtered if abs(s.price - anchor) <= tol]
    if not cluster:
        return None

    low_price = min(s.price for s in cluster)
    high_price = max(s.price for s in cluster)
    return (_quant_price(low_price), _quant_price(high_price), len(cluster))


def _build_zone_strength(
    *,
    touch_count: int,
    confluence_components: int,
    interval_weight: Decimal,
) -> Decimal:
    base = Decimal(str(touch_count)) * Decimal("0.10")
    confluence = Decimal(str(confluence_components)) * Decimal("0.20")
    return _quant_score(min(Decimal("1.0"), base + confluence + interval_weight))


def _interval_weight(interval_code: str) -> Decimal:
    if interval_code == "1d":
        return Decimal("0.40")
    if interval_code == "4h":
        return Decimal("0.25")
    if interval_code == "1h":
        return Decimal("0.15")
    return Decimal("0.10")


def _build_fib_observation(
    *,
    candles: list[CandleRow],
    symbol: str,
    venue: str,
    interval_code: str,
    asof_ts_utc,
    left: SwingPoint,
    right: SwingPoint,
) -> FibObservationInput:
    leg_direction = "UP" if left.point_type == "SWING_LOW" and right.point_type == "SWING_HIGH" else "DOWN"

    anchor_start_price = left.price
    anchor_end_price = right.price

    fib_0236 = _price_from_leg(anchor_start_price, anchor_end_price, "0.236")
    fib_0382 = _price_from_leg(anchor_start_price, anchor_end_price, "0.382")
    fib_0500 = _price_from_leg(anchor_start_price, anchor_end_price, "0.500")
    fib_0618 = _price_from_leg(anchor_start_price, anchor_end_price, "0.618")
    fib_0786 = _price_from_leg(anchor_start_price, anchor_end_price, "0.786")
    ext_1272 = _extension_from_leg(anchor_start_price, anchor_end_price, "1.272")
    ext_1618 = _extension_from_leg(anchor_start_price, anchor_end_price, "1.618")

    return FibObservationInput(
        asset_id=candles[-1].asset_id,
        symbol=symbol,
        venue=venue,
        interval_code=interval_code,
        asof_ts_utc=asof_ts_utc,
        anchor_start_ts_utc=left.ts_utc,
        anchor_end_ts_utc=right.ts_utc,
        anchor_start_price=_quant_price(anchor_start_price),
        anchor_end_price=_quant_price(anchor_end_price),
        leg_direction=leg_direction,
        anchor_span_bars=(right.index - left.index),
        anchor_move_pct=_pct_change(anchor_start_price, anchor_end_price),
        fib_0236_price=fib_0236,
        fib_0382_price=fib_0382,
        fib_0500_price=fib_0500,
        fib_0618_price=fib_0618,
        fib_0786_price=fib_0786,
        ext_1272_price=ext_1272,
        ext_1618_price=ext_1618,
        active_retracement_price=fib_0618,
        active_extension_price=ext_1272,
        fib_confluence_score=Decimal("0.00000000"),
        structure_quality_score=Decimal("0.75000000"),
        source_type="SWING_ANCHOR",
        notes=f"latest_leg {left.point_type}->{right.point_type}",
    )


def _build_zones(
    *,
    candles: list[CandleRow],
    fib: FibObservationInput,
    swings: list[SwingPoint],
    sr_tolerance_bps: Decimal,
) -> list[ZoneObservationInput]:
    zones: list[ZoneObservationInput] = []
    interval_weight = _interval_weight(fib.interval_code)
    last_index = len(candles) - 1

    fib_primary_low = min(fib.fib_0500_price, fib.fib_0618_price)
    fib_primary_high = max(fib.fib_0500_price, fib.fib_0618_price)
    fib_deep_low = min(fib.fib_0618_price, fib.fib_0786_price)
    fib_deep_high = max(fib.fib_0618_price, fib.fib_0786_price)

    invalidation_price = (
        fib.anchor_start_price if fib.leg_direction == "UP"
        else fib.anchor_start_price
    )

    zones.append(
        ZoneObservationInput(
            asset_id=fib.asset_id,
            symbol=fib.symbol,
            venue=fib.venue,
            interval_code=fib.interval_code,
            asof_ts_utc=fib.asof_ts_utc,
            zone_type="FIB_RETRACEMENT",
            zone_source_type="FIB",
            zone_low_price=fib_primary_low,
            zone_high_price=fib_primary_high,
            zone_mid_price=_mid(fib_primary_low, fib_primary_high),
            zone_width_pct=_width_pct(fib_primary_low, fib_primary_high),
            expected_reaction="BOUNCE" if fib.leg_direction == "UP" else "REJECTION",
            invalidation_price=invalidation_price,
            zone_strength_score=_build_zone_strength(
                touch_count=1,
                confluence_components=1,
                interval_weight=interval_weight,
            ),
            confluence_score=_quant_score(Decimal("0.20000000") + interval_weight),
            touch_count=1,
            break_count=0,
            zone_age_bars=max(0, last_index - (fib.anchor_span_bars)),
            source_ref_type="FIB_OBSERVATION",
            source_ref_id=None,
            parent_zone_observation_id=None,
            notes="primary fib retracement zone (0.500-0.618)",
        )
    )

    zones.append(
        ZoneObservationInput(
            asset_id=fib.asset_id,
            symbol=fib.symbol,
            venue=fib.venue,
            interval_code=fib.interval_code,
            asof_ts_utc=fib.asof_ts_utc,
            zone_type="FIB_DEEP",
            zone_source_type="FIB",
            zone_low_price=fib_deep_low,
            zone_high_price=fib_deep_high,
            zone_mid_price=_mid(fib_deep_low, fib_deep_high),
            zone_width_pct=_width_pct(fib_deep_low, fib_deep_high),
            expected_reaction="LAST_DEFENSE",
            invalidation_price=invalidation_price,
            zone_strength_score=_build_zone_strength(
                touch_count=1,
                confluence_components=1,
                interval_weight=interval_weight - Decimal("0.05"),
            ),
            confluence_score=_quant_score(Decimal("0.15000000") + interval_weight),
            touch_count=1,
            break_count=0,
            zone_age_bars=max(0, last_index - (fib.anchor_span_bars)),
            source_ref_type="FIB_OBSERVATION",
            source_ref_id=None,
            parent_zone_observation_id=None,
            notes="deep fib zone (0.618-0.786)",
        )
    )

    support_cluster = _cluster_recent_sr_zone(swings, zone_type="SWING_LOW", tolerance_bps=sr_tolerance_bps)
    if support_cluster is not None:
        low_price, high_price, touch_count = support_cluster
        zones.append(
            ZoneObservationInput(
                asset_id=fib.asset_id,
                symbol=fib.symbol,
                venue=fib.venue,
                interval_code=fib.interval_code,
                asof_ts_utc=fib.asof_ts_utc,
                zone_type="SR_SUPPORT",
                zone_source_type="SWING_CLUSTER",
                zone_low_price=low_price,
                zone_high_price=high_price,
                zone_mid_price=_mid(low_price, high_price),
                zone_width_pct=_width_pct(low_price, high_price),
                expected_reaction="BOUNCE",
                invalidation_price=low_price,
                zone_strength_score=_build_zone_strength(
                    touch_count=touch_count,
                    confluence_components=1,
                    interval_weight=interval_weight,
                ),
                confluence_score=_quant_score(interval_weight),
                touch_count=touch_count,
                break_count=0,
                zone_age_bars=max(0, last_index - max(s.index for s in swings if s.point_type == "SWING_LOW")),
                source_ref_type="SWING_CLUSTER",
                source_ref_id=None,
                parent_zone_observation_id=None,
                notes="simple recent swing-low support cluster",
            )
        )

    resistance_cluster = _cluster_recent_sr_zone(swings, zone_type="SWING_HIGH", tolerance_bps=sr_tolerance_bps)
    if resistance_cluster is not None:
        low_price, high_price, touch_count = resistance_cluster
        zones.append(
            ZoneObservationInput(
                asset_id=fib.asset_id,
                symbol=fib.symbol,
                venue=fib.venue,
                interval_code=fib.interval_code,
                asof_ts_utc=fib.asof_ts_utc,
                zone_type="SR_RESISTANCE",
                zone_source_type="SWING_CLUSTER",
                zone_low_price=low_price,
                zone_high_price=high_price,
                zone_mid_price=_mid(low_price, high_price),
                zone_width_pct=_width_pct(low_price, high_price),
                expected_reaction="REJECTION",
                invalidation_price=high_price,
                zone_strength_score=_build_zone_strength(
                    touch_count=touch_count,
                    confluence_components=1,
                    interval_weight=interval_weight,
                ),
                confluence_score=_quant_score(interval_weight),
                touch_count=touch_count,
                break_count=0,
                zone_age_bars=max(0, last_index - max(s.index for s in swings if s.point_type == "SWING_HIGH")),
                source_ref_type="SWING_CLUSTER",
                source_ref_id=None,
                parent_zone_observation_id=None,
                notes="simple recent swing-high resistance cluster",
            )
        )

    return zones


def _overlap(low_a: Decimal, high_a: Decimal, low_b: Decimal, high_b: Decimal) -> bool:
    return max(low_a, low_b) <= min(high_a, high_b)


def _select_execution_context(
    *,
    repo: ZoneRepository,
    fib: FibObservationInput,
    zones: list[ZoneObservationInput],
    sleeve_code: str,
) -> ExecutionZoneContextInput:
    entry_zone = None
    tp_zone = None

    fib_zone_candidates = [z for z in zones if z.zone_type in {"FIB_RETRACEMENT", "FIB_DEEP"}]
    sr_zone_candidates = [z for z in zones if z.zone_type in {"SR_SUPPORT", "SR_RESISTANCE"}]

    best_entry_score = Decimal("-999")
    for fib_zone in fib_zone_candidates:
        confluence_bonus = Decimal("0")
        for sr_zone in sr_zone_candidates:
            if _overlap(
                fib_zone.zone_low_price,
                fib_zone.zone_high_price,
                sr_zone.zone_low_price,
                sr_zone.zone_high_price,
            ):
                confluence_bonus += Decimal("0.25")

        score = fib_zone.zone_strength_score + fib_zone.confluence_score + confluence_bonus
        if score > best_entry_score:
            best_entry_score = score
            entry_zone = fib_zone

    if fib.leg_direction == "UP":
        sr_res = [z for z in zones if z.zone_type == "SR_RESISTANCE"]
        if sr_res:
            tp_zone = max(sr_res, key=lambda z: z.zone_strength_score + z.confluence_score)
        else:
            tp_zone = ZoneObservationInput(
                asset_id=fib.asset_id,
                symbol=fib.symbol,
                venue=fib.venue,
                interval_code=fib.interval_code,
                asof_ts_utc=fib.asof_ts_utc,
                zone_type="FIB_EXTENSION",
                zone_source_type="FIB",
                zone_low_price=fib.ext_1272_price,
                zone_high_price=fib.ext_1618_price,
                zone_mid_price=_mid(fib.ext_1272_price, fib.ext_1618_price),
                zone_width_pct=_width_pct(fib.ext_1272_price, fib.ext_1618_price),
                expected_reaction="TAKE_PROFIT",
                invalidation_price=None,
                zone_strength_score=Decimal("0.55000000"),
                confluence_score=Decimal("0.20000000"),
                touch_count=0,
                break_count=0,
                zone_age_bars=0,
                source_ref_type="FIB_OBSERVATION",
                source_ref_id=None,
                parent_zone_observation_id=None,
                notes="fallback fib extension TP zone",
            )
    else:
        sr_sup = [z for z in zones if z.zone_type == "SR_SUPPORT"]
        if sr_sup:
            tp_zone = max(sr_sup, key=lambda z: z.zone_strength_score + z.confluence_score)
        else:
            tp_zone = ZoneObservationInput(
                asset_id=fib.asset_id,
                symbol=fib.symbol,
                venue=fib.venue,
                interval_code=fib.interval_code,
                asof_ts_utc=fib.asof_ts_utc,
                zone_type="FIB_EXTENSION",
                zone_source_type="FIB",
                zone_low_price=min(fib.ext_1272_price, fib.ext_1618_price),
                zone_high_price=max(fib.ext_1272_price, fib.ext_1618_price),
                zone_mid_price=_mid(min(fib.ext_1272_price, fib.ext_1618_price), max(fib.ext_1272_price, fib.ext_1618_price)),
                zone_width_pct=_width_pct(min(fib.ext_1272_price, fib.ext_1618_price), max(fib.ext_1272_price, fib.ext_1618_price)),
                expected_reaction="TAKE_PROFIT",
                invalidation_price=None,
                zone_strength_score=Decimal("0.55000000"),
                confluence_score=Decimal("0.20000000"),
                touch_count=0,
                break_count=0,
                zone_age_bars=0,
                source_ref_type="FIB_OBSERVATION",
                source_ref_id=None,
                parent_zone_observation_id=None,
                notes="fallback fib extension TP zone",
            )

    zone_confidence_score = _quant_score(
        (entry_zone.zone_strength_score if entry_zone else Decimal("0"))
        + (entry_zone.confluence_score if entry_zone else Decimal("0"))
    )
    zone_alignment_score = _quant_score(
        Decimal("0.50")
        + (_interval_weight(fib.interval_code) / Decimal("2"))
    )

    source_ref_json = repo.make_source_ref_json(
        fib_anchor_start_ts_utc=str(fib.anchor_start_ts_utc),
        fib_anchor_end_ts_utc=str(fib.anchor_end_ts_utc),
        zones=zones,
    )

    return ExecutionZoneContextInput(
        asset_id=fib.asset_id,
        symbol=fib.symbol,
        venue=fib.venue,
        sleeve_code=sleeve_code,
        interval_code=fib.interval_code,
        asof_ts_utc=fib.asof_ts_utc,
        dominant_tf=fib.interval_code,
        expected_entry_zone_low=entry_zone.zone_low_price if entry_zone else None,
        expected_entry_zone_high=entry_zone.zone_high_price if entry_zone else None,
        expected_entry_zone_type=entry_zone.zone_type if entry_zone else None,
        expected_take_profit_zone_low=tp_zone.zone_low_price if tp_zone else None,
        expected_take_profit_zone_high=tp_zone.zone_high_price if tp_zone else None,
        expected_take_profit_zone_type=tp_zone.zone_type if tp_zone else None,
        invalidation_price=entry_zone.invalidation_price if entry_zone else fib.anchor_start_price,
        zone_confidence_score=zone_confidence_score,
        zone_alignment_score=zone_alignment_score,
        source_timeframes=fib.interval_code,
        source_types="fib,sr",
        source_ref_json=source_ref_json,
        notes=f"leg_direction={fib.leg_direction}",
    )


def build_zone_engine_result(
    *,
    repo: ZoneRepository,
    candles: list[CandleRow],
    swing_window: int,
    sr_tolerance_bps: Decimal,
    sleeve_code: str,
) -> ZoneEngineResult | None:
    if len(candles) < max(10, swing_window * 2 + 3):
        return None

    swings = _detect_swings(candles, swing_window=swing_window)
    latest_leg = _latest_alternating_leg(swings)
    if latest_leg is None:
        return None

    left, right = latest_leg
    fib = _build_fib_observation(
        candles=candles,
        symbol=candles[-1].symbol,
        venue=candles[-1].venue,
        interval_code=candles[-1].interval_code,
        asof_ts_utc=candles[-1].close_ts_utc,
        left=left,
        right=right,
    )
    zones = _build_zones(
        candles=candles,
        fib=fib,
        swings=swings,
        sr_tolerance_bps=sr_tolerance_bps,
    )
    execution_context = _select_execution_context(
        repo=repo,
        fib=fib,
        zones=zones,
        sleeve_code=sleeve_code,
    )

    return ZoneEngineResult(
        asset_id=fib.asset_id,
        symbol=fib.symbol,
        venue=fib.venue,
        interval_code=fib.interval_code,
        asof_ts_utc=fib.asof_ts_utc,
        leg_direction=fib.leg_direction,
        fib_observation=fib,
        zones=zones,
        execution_context=execution_context,
    )
