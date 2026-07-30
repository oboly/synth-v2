from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

# ---------------------------------------------------------------------------
# Map lifecycle states
# ---------------------------------------------------------------------------

MAP_STATE_FRESH = "FRESH"
MAP_STATE_STALE = "STALE"
MAP_STATE_EXHAUSTED = "EXHAUSTED"
MAP_STATE_FALLBACK = "FALLBACK"
MAP_STATE_EMERGENCY_REBUILT = "EMERGENCY_REBUILT"
MAP_STATE_NO_DATA = "NO_DATA"
MAP_STATE_LOW_CONFIDENCE = "LOW_CONFIDENCE"
MAP_COMPLETED_FROZEN = "MAP_COMPLETED_FROZEN"
ACTIVE_RECOMPUTED_MAP = "ACTIVE_RECOMPUTED_MAP"

# ---------------------------------------------------------------------------
# Rebuild triggers
# ---------------------------------------------------------------------------

TRIGGER_NONE = "NONE"
TRIGGER_MAP_MISSING = "MAP_MISSING"
TRIGGER_MAP_STALE = "MAP_STALE"
TRIGGER_MAP_EXHAUSTED = "MAP_EXHAUSTED"
TRIGGER_ALL_TARGETS_PASSED = "ALL_TARGETS_PASSED"
TRIGGER_PRICE_ABOVE_TOP_TARGET = "PRICE_ABOVE_TOP_TARGET"
TRIGGER_PRICE_BELOW_INVALIDATION = "PRICE_BELOW_INVALIDATION"
TRIGGER_NEW_HIGH_WITH_VOLUME = "NEW_HIGH_WITH_VOLUME_EXPANSION"
TRIGGER_NEW_LOW_WITH_VOLUME = "NEW_LOW_WITH_VOLUME_EXPANSION"
TRIGGER_IMPULSE_MOVE = "IMPULSE_MOVE_GT_ATR_MULTIPLE"
RECOMPUTE_NEEDED = "RECOMPUTE_NEEDED"
NEW_MAP_AVAILABLE = "NEW_MAP_AVAILABLE"
RECOMPUTE_STATUS_NONE = "NONE"

DIRECTION_BULLISH = "BULLISH"
DIRECTION_BEARISH = "BEARISH"

# ---------------------------------------------------------------------------
# Level tables
# ---------------------------------------------------------------------------

RETRACE_LEVELS: tuple[tuple[str, Decimal], ...] = (
    ("r_0236", Decimal("0.236")),
    ("r_0382", Decimal("0.382")),
    ("r_0500", Decimal("0.500")),
    ("r_0618", Decimal("0.618")),
    ("r_0786", Decimal("0.786")),
    ("r_1000", Decimal("1.000")),
)

EXTENSION_LEVELS: tuple[tuple[str, Decimal], ...] = (
    ("ext_1272", Decimal("1.272")),
    ("ext_1414", Decimal("1.414")),
    ("ext_1618", Decimal("1.618")),
    ("ext_2000", Decimal("2.000")),
    ("ext_2272", Decimal("2.272")),
    ("ext_2414", Decimal("2.414")),
    ("ext_2618", Decimal("2.618")),
    ("ext_3000", Decimal("3.000")),
    ("ext_4236", Decimal("4.236")),
)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_PIVOT_SPAN: int = 3
DEFAULT_MIN_CANDLES: int = 10
DEFAULT_STALE_HOURS: int = 4
DEFAULT_ATR_PERIOD: int = 14
DEFAULT_IMPULSE_ATR_MULTIPLE: Decimal = Decimal("1.5")
DEFAULT_VOLUME_EXPANSION_RATIO: Decimal = Decimal("1.5")
PRICE_QUANT: Decimal = Decimal("0.0000000001")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FibNavCandle:
    close_ts_utc: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: Decimal = Decimal("0")


@dataclass(frozen=True)
class FibNavLevel:
    label: str
    fib_level: Decimal
    price: Decimal
    is_retracement: bool


@dataclass(frozen=True)
class PriorMapMeta:
    """Minimal snapshot of the prior map needed for lifecycle decisions."""
    map_state: str
    anchor_low: Decimal
    anchor_high: Decimal
    direction: str
    top_extension_price: Decimal  # price of highest extension level (ext_4236)
    candle_ts_utc: datetime       # timestamp of the prior map's last candle


@dataclass(frozen=True)
class FibNavigationMap:
    anchor_low: Decimal
    anchor_high: Decimal
    direction: str
    leg_size: Decimal
    current_price: Decimal
    retracement_levels: tuple[FibNavLevel, ...]
    extension_levels: tuple[FibNavLevel, ...]
    map_state: str
    rebuild_trigger: str
    confidence: str             # HIGH / MEDIUM / LOW
    anchor_candle_count: int
    computed_at_utc: datetime
    historical_reference_state: str | None = None
    historical_reference_anchor_low: Decimal | None = None
    historical_reference_anchor_high: Decimal | None = None
    historical_reference_top_extension_price: Decimal | None = None
    active_map_state: str | None = None
    recompute_status: str = RECOMPUTE_STATUS_NONE


# ---------------------------------------------------------------------------
# Level calculation
# ---------------------------------------------------------------------------

def _quant(value: Decimal) -> Decimal:
    return value.quantize(PRICE_QUANT)


def _build_levels(
    anchor_low: Decimal,
    anchor_high: Decimal,
    direction: str,
) -> tuple[tuple[FibNavLevel, ...], tuple[FibNavLevel, ...]]:
    leg = anchor_high - anchor_low
    retrace_rows: list[FibNavLevel] = []
    ext_rows: list[FibNavLevel] = []

    for label, level in RETRACE_LEVELS:
        if direction == DIRECTION_BULLISH:
            price = _quant(anchor_high - leg * level)
        else:
            price = _quant(anchor_low + leg * level)
        retrace_rows.append(FibNavLevel(label=label, fib_level=level, price=price, is_retracement=True))

    for label, level in EXTENSION_LEVELS:
        if direction == DIRECTION_BULLISH:
            price = _quant(anchor_low + leg * level)
        else:
            price = _quant(anchor_high - leg * level)
        ext_rows.append(FibNavLevel(label=label, fib_level=level, price=price, is_retracement=False))

    return tuple(retrace_rows), tuple(ext_rows)


# ---------------------------------------------------------------------------
# ATR / volatility helpers
# ---------------------------------------------------------------------------

def _compute_atr(candles: list[FibNavCandle], period: int) -> Decimal:
    if len(candles) < 2:
        return Decimal("0")
    trs: list[Decimal] = []
    for i in range(1, len(candles)):
        prev_close = candles[i - 1].close_price
        tr = max(
            candles[i].high_price - candles[i].low_price,
            abs(candles[i].high_price - prev_close),
            abs(candles[i].low_price - prev_close),
        )
        trs.append(tr)
    window = trs[-period:] if len(trs) >= period else trs
    return sum(window, Decimal("0")) / Decimal(str(len(window)))


def _volume_expanded(candles: list[FibNavCandle], ratio: Decimal, lookback: int = 20) -> bool:
    if len(candles) < 2:
        return False
    recent = candles[-1]
    if recent.volume <= 0:
        return False
    prior = candles[max(0, len(candles) - 1 - lookback) : len(candles) - 1]
    vols = [c.volume for c in prior if c.volume > 0]
    if not vols:
        return False
    avg = sum(vols, Decimal("0")) / Decimal(str(len(vols)))
    return recent.volume >= avg * ratio


# ---------------------------------------------------------------------------
# Pivot detection
# ---------------------------------------------------------------------------

def _find_pivot_lows(candles: list[FibNavCandle], span: int) -> list[int]:
    result: list[int] = []
    for i in range(span, len(candles) - span):
        low = candles[i].low_price
        window = candles[i - span : i + span + 1]
        if all(low <= c.low_price for c in window):
            result.append(i)
    return result


def _find_pivot_highs(candles: list[FibNavCandle], span: int) -> list[int]:
    result: list[int] = []
    for i in range(span, len(candles) - span):
        high = candles[i].high_price
        window = candles[i - span : i + span + 1]
        if all(high >= c.high_price for c in window):
            result.append(i)
    return result


def _best_bullish_swing(
    candles: list[FibNavCandle], span: int
) -> tuple[Decimal, Decimal] | None:
    lows = _find_pivot_lows(candles, span)
    highs = _find_pivot_highs(candles, span)
    best_low: Decimal | None = None
    best_high: Decimal | None = None
    best_size = Decimal("0")
    for high_idx in highs:
        prior_lows = [li for li in lows if li < high_idx]
        if not prior_lows:
            continue
        low_idx = prior_lows[-1]
        s_low = candles[low_idx].low_price
        s_high = candles[high_idx].high_price
        if s_low <= 0 or s_high <= s_low:
            continue
        size = s_high - s_low
        if size > best_size:
            best_size = size
            best_low = s_low
            best_high = s_high
    if best_low is None or best_high is None:
        return None
    return best_low, best_high


def _best_bearish_swing(
    candles: list[FibNavCandle], span: int
) -> tuple[Decimal, Decimal] | None:
    lows = _find_pivot_lows(candles, span)
    highs = _find_pivot_highs(candles, span)
    best_low: Decimal | None = None
    best_high: Decimal | None = None
    best_size = Decimal("0")
    for low_idx in lows:
        prior_highs = [hi for hi in highs if hi < low_idx]
        if not prior_highs:
            continue
        high_idx = prior_highs[-1]
        s_high = candles[high_idx].high_price
        s_low = candles[low_idx].low_price
        if s_low <= 0 or s_high <= s_low:
            continue
        size = s_high - s_low
        if size > best_size:
            best_size = size
            best_low = s_low
            best_high = s_high
    if best_low is None or best_high is None:
        return None
    return best_low, best_high


def _range_fallback(candles: list[FibNavCandle]) -> tuple[Decimal, Decimal] | None:
    if not candles:
        return None
    low = min(c.low_price for c in candles)
    high = max(c.high_price for c in candles)
    if high <= low or low <= 0:
        return None
    return low, high


def _is_completed_or_exhausted_state(state: str | None) -> bool:
    return str(state or "").upper() in {
        MAP_STATE_EXHAUSTED,
        MAP_COMPLETED_FROZEN,
        "MAP_COMPLETED",
    }


def _latest_active_bullish_swing(
    candles: list[FibNavCandle], span: int
) -> tuple[Decimal, Decimal] | None:
    if len(candles) < span + 2:
        return None
    recent_start = max(0, len(candles) - (span + 1))
    high_idx = max(
        range(recent_start, len(candles)),
        key=lambda idx: (candles[idx].high_price, idx),
    )
    if high_idx <= 0:
        return None
    pivot_lows = [idx for idx in _find_pivot_lows(candles, span) if idx < high_idx]
    if pivot_lows:
        low_idx = pivot_lows[-1]
    else:
        low_idx = min(range(0, high_idx), key=lambda idx: (candles[idx].low_price, idx))
    low_price = candles[low_idx].low_price
    high_price = candles[high_idx].high_price
    if low_price <= 0 or high_price <= low_price:
        return None
    return low_price, high_price


def _latest_active_bearish_swing(
    candles: list[FibNavCandle], span: int
) -> tuple[Decimal, Decimal] | None:
    if len(candles) < span + 2:
        return None
    recent_start = max(0, len(candles) - (span + 1))
    low_idx = min(
        range(recent_start, len(candles)),
        key=lambda idx: (candles[idx].low_price, idx),
    )
    if low_idx <= 0:
        return None
    pivot_highs = [idx for idx in _find_pivot_highs(candles, span) if idx < low_idx]
    if pivot_highs:
        high_idx = pivot_highs[-1]
    else:
        high_idx = max(range(0, low_idx), key=lambda idx: (candles[idx].high_price, idx))
    low_price = candles[low_idx].low_price
    high_price = candles[high_idx].high_price
    if low_price <= 0 or high_price <= low_price:
        return None
    return low_price, high_price


def _reference_fields(
    prior: PriorMapMeta | None,
    *,
    recompute_available: bool,
) -> dict[str, Decimal | str | None]:
    if prior is None or not _is_completed_or_exhausted_state(prior.map_state):
        return {
            "historical_reference_state": None,
            "historical_reference_anchor_low": None,
            "historical_reference_anchor_high": None,
            "historical_reference_top_extension_price": None,
            "active_map_state": None,
            "recompute_status": RECOMPUTE_STATUS_NONE,
        }
    return {
        "historical_reference_state": MAP_COMPLETED_FROZEN,
        "historical_reference_anchor_low": prior.anchor_low,
        "historical_reference_anchor_high": prior.anchor_high,
        "historical_reference_top_extension_price": prior.top_extension_price,
        "active_map_state": ACTIVE_RECOMPUTED_MAP if recompute_available else None,
        "recompute_status": NEW_MAP_AVAILABLE if recompute_available else RECOMPUTE_NEEDED,
    }


# ---------------------------------------------------------------------------
# Rebuild trigger detection
# ---------------------------------------------------------------------------

def _detect_trigger(
    *,
    candles: list[FibNavCandle],
    current_price: Decimal,
    prior: PriorMapMeta | None,
    atr: Decimal,
    impulse_atr_multiple: Decimal,
    volume_expansion_ratio: Decimal,
    now_utc: datetime,
    stale_after: timedelta,
) -> str | None:
    if prior is None:
        return TRIGGER_MAP_MISSING

    if _is_completed_or_exhausted_state(prior.map_state):
        return TRIGGER_MAP_EXHAUSTED

    if now_utc - prior.candle_ts_utc > stale_after:
        return TRIGGER_MAP_STALE

    if prior.map_state == MAP_STATE_STALE:
        return TRIGGER_MAP_STALE

    # All extension targets passed in the map's directional travel.
    if (
        prior.direction == DIRECTION_BULLISH
        and current_price >= prior.top_extension_price
    ) or (
        prior.direction == DIRECTION_BEARISH
        and current_price <= prior.top_extension_price
    ):
        return TRIGGER_ALL_TARGETS_PASSED

    # Price below invalidation level
    if prior.direction == DIRECTION_BULLISH and current_price < prior.anchor_low:
        return TRIGGER_PRICE_BELOW_INVALIDATION
    if prior.direction == DIRECTION_BEARISH and current_price > prior.anchor_high:
        return TRIGGER_PRICE_BELOW_INVALIDATION

    # Impulse move detection
    if atr > 0 and len(candles) >= 2:
        recent_move = abs(candles[-1].close_price - candles[-2].close_price)
        if recent_move >= atr * impulse_atr_multiple:
            if _volume_expanded(candles, ratio=volume_expansion_ratio):
                prior_highs = [c.high_price for c in candles[:-1]]
                prior_lows = [c.low_price for c in candles[:-1]]
                if prior_highs and candles[-1].high_price > max(prior_highs):
                    return TRIGGER_NEW_HIGH_WITH_VOLUME
                if prior_lows and candles[-1].low_price < min(prior_lows):
                    return TRIGGER_NEW_LOW_WITH_VOLUME
            return TRIGGER_IMPULSE_MOVE

    return None


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_fib_navigation_map_from_anchor(
    *,
    anchor_low: Decimal,
    anchor_high: Decimal,
    current_price: Decimal,
    direction: str = DIRECTION_BULLISH,
    prior_map_state: str = MAP_STATE_EXHAUSTED,
    computed_at_utc: datetime,
) -> FibNavigationMap:
    """
    Build a FibNavigationMap directly from a known anchor without candle detection.

    Used when the anchor is already known (e.g., from native context) and candle
    detection is not needed or available. Sets map_state=EMERGENCY_REBUILT when
    prior_map_state is EXHAUSTED.
    """
    if anchor_high <= anchor_low or anchor_low <= 0:
        raise ValueError(
            f"Invalid anchor for fib nav map: low={anchor_low}, high={anchor_high}"
        )
    retrace, ext = _build_levels(anchor_low, anchor_high, direction)
    exhausted_reference = _is_completed_or_exhausted_state(prior_map_state)
    trigger = TRIGGER_MAP_EXHAUSTED if exhausted_reference else TRIGGER_MAP_MISSING
    map_state = MAP_STATE_EMERGENCY_REBUILT if exhausted_reference else MAP_STATE_FRESH
    # Anchor-only fallback reuses the historical anchor. It must not claim
    # that a fresh active recomputed map was derived from new candles.
    active_map_state = None
    recompute_status = RECOMPUTE_NEEDED if exhausted_reference else RECOMPUTE_STATUS_NONE
    historical_reference_state = MAP_COMPLETED_FROZEN if exhausted_reference else None
    return FibNavigationMap(
        anchor_low=anchor_low,
        anchor_high=anchor_high,
        direction=direction,
        leg_size=anchor_high - anchor_low,
        current_price=current_price,
        retracement_levels=retrace,
        extension_levels=ext,
        map_state=map_state,
        rebuild_trigger=trigger,
        confidence="HIGH",
        anchor_candle_count=0,
        computed_at_utc=computed_at_utc,
        historical_reference_state=historical_reference_state,
        historical_reference_anchor_low=anchor_low if historical_reference_state else None,
        historical_reference_anchor_high=anchor_high if historical_reference_state else None,
        historical_reference_top_extension_price=ext[-1].price if historical_reference_state else None,
        active_map_state=active_map_state,
        recompute_status=recompute_status,
    )


def build_fib_navigation_map(
    *,
    candles: list[FibNavCandle],
    current_price: Decimal,
    now_utc: datetime,
    prior: PriorMapMeta | None = None,
    direction: str = DIRECTION_BULLISH,
    pivot_span: int = DEFAULT_PIVOT_SPAN,
    min_candles: int = DEFAULT_MIN_CANDLES,
    stale_after: timedelta = timedelta(hours=DEFAULT_STALE_HOURS),
    impulse_atr_multiple: Decimal = DEFAULT_IMPULSE_ATR_MULTIPLE,
    volume_expansion_ratio: Decimal = DEFAULT_VOLUME_EXPANSION_RATIO,
) -> FibNavigationMap:

    def _empty(state: str, trigger: str) -> FibNavigationMap:
        reference = _reference_fields(prior, recompute_available=False)
        return FibNavigationMap(
            anchor_low=Decimal("0"),
            anchor_high=Decimal("0"),
            direction=direction,
            leg_size=Decimal("0"),
            current_price=current_price,
            retracement_levels=(),
            extension_levels=(),
            map_state=state,
            rebuild_trigger=trigger,
            confidence="LOW",
            anchor_candle_count=len(candles),
            computed_at_utc=now_utc,
            historical_reference_state=reference["historical_reference_state"],
            historical_reference_anchor_low=reference["historical_reference_anchor_low"],
            historical_reference_anchor_high=reference["historical_reference_anchor_high"],
            historical_reference_top_extension_price=reference["historical_reference_top_extension_price"],
            active_map_state=reference["active_map_state"],
            recompute_status=str(reference["recompute_status"]),
        )

    if len(candles) < min_candles:
        return _empty(MAP_STATE_NO_DATA, TRIGGER_MAP_MISSING)

    if now_utc - candles[-1].close_ts_utc > stale_after:
        return _empty(MAP_STATE_STALE, TRIGGER_MAP_STALE)

    atr = _compute_atr(candles, DEFAULT_ATR_PERIOD)

    trigger = _detect_trigger(
        candles=candles,
        current_price=current_price,
        prior=prior,
        atr=atr,
        impulse_atr_multiple=impulse_atr_multiple,
        volume_expansion_ratio=volume_expansion_ratio,
        now_utc=now_utc,
        stale_after=stale_after,
    )

    # No rebuild needed — return prior anchor with FRESH state
    if trigger is None and prior is not None:
        retrace, ext = _build_levels(prior.anchor_low, prior.anchor_high, prior.direction)
        return FibNavigationMap(
            anchor_low=prior.anchor_low,
            anchor_high=prior.anchor_high,
            direction=prior.direction,
            leg_size=prior.anchor_high - prior.anchor_low,
            current_price=current_price,
            retracement_levels=retrace,
            extension_levels=ext,
            map_state=MAP_STATE_FRESH,
            rebuild_trigger=TRIGGER_NONE,
            confidence="HIGH",
            anchor_candle_count=len(candles),
            computed_at_utc=now_utc,
        )

    # Rebuild: detect swing from fresh candles
    fallback_used = False
    if direction == DIRECTION_BULLISH:
        pair = _latest_active_bullish_swing(candles, pivot_span)
        if pair is None:
            pair = _best_bullish_swing(candles, pivot_span)
    else:
        pair = _latest_active_bearish_swing(candles, pivot_span)
        if pair is None:
            pair = _best_bearish_swing(candles, pivot_span)

    if pair is None:
        fb = _range_fallback(candles)
        if fb is None:
            return _empty(MAP_STATE_NO_DATA, trigger or TRIGGER_MAP_MISSING)
        anchor_low, anchor_high = fb
        fallback_used = True
    else:
        anchor_low, anchor_high = pair

    if anchor_high <= anchor_low or anchor_low <= 0:
        return _empty(MAP_STATE_NO_DATA, trigger or TRIGGER_MAP_MISSING)

    retrace, ext = _build_levels(anchor_low, anchor_high, direction)

    # Classify state
    exhausted_triggers = {TRIGGER_MAP_EXHAUSTED, TRIGGER_ALL_TARGETS_PASSED}
    if trigger in exhausted_triggers:
        map_state = MAP_STATE_EMERGENCY_REBUILT
    elif fallback_used:
        map_state = MAP_STATE_FALLBACK
    elif trigger == MAP_STATE_NO_DATA:
        map_state = MAP_STATE_NO_DATA
    else:
        map_state = MAP_STATE_EMERGENCY_REBUILT

    # Confidence
    if fallback_used:
        confidence = "LOW"
    elif len(candles) >= min_candles * 3:
        confidence = "HIGH"
    else:
        confidence = "MEDIUM"

    reference = _reference_fields(
        prior,
        recompute_available=trigger in exhausted_triggers or _is_completed_or_exhausted_state(prior.map_state if prior else None),
    )

    return FibNavigationMap(
        anchor_low=anchor_low,
        anchor_high=anchor_high,
        direction=direction,
        leg_size=anchor_high - anchor_low,
        current_price=current_price,
        retracement_levels=retrace,
        extension_levels=ext,
        map_state=map_state,
        rebuild_trigger=trigger or TRIGGER_MAP_MISSING,
        confidence=confidence,
        anchor_candle_count=len(candles),
        computed_at_utc=now_utc,
        historical_reference_state=reference["historical_reference_state"],
        historical_reference_anchor_low=reference["historical_reference_anchor_low"],
        historical_reference_anchor_high=reference["historical_reference_anchor_high"],
        historical_reference_top_extension_price=reference["historical_reference_top_extension_price"],
        active_map_state=reference["active_map_state"],
        recompute_status=str(reference["recompute_status"]),
    )
