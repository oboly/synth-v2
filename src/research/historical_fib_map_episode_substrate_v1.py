from __future__ import annotations

"""Canonical reusable historical PIT Fib/map episode substrate (#555).

Pure, deterministic, market-only. No DB access, no wall-clock dependence.

Reuses the SAME canonical geometry/classification code paths as production:

- src.market_data.fib_navigation_map_v1.build_fib_navigation_map
    (canonical Fib anchor/level geometry engine)
- src.structure.trend_state_v1.compute_trend_state
    (canonical trend/direction classification)
- src.features.indicators.ema / atr
    (canonical EMA/ATR helpers used to build the trend-state input features)

This module does not reimplement Fibonacci math, pivot/swing detection, or
trend classification. It adds only:

- a PIT-safe feature/label split for historical replay
- forward-scan lifecycle-label computation (does not exist as a production
  concept; production runs forward live, it does not label its own history)
- a deterministic episode identity/contract

Scope boundary (issue #555):
- This module owns the historical episode dataset only.
- It does not perform #664 Fib Reach calibration.
- It does not perform #723 promotion qualification.
- It does not touch #657 promotion mechanics.

Safety markers:
research_only=1 market_only=1 account_awareness=0 decision_permission=0
execution_intent=0 broker_calls=0 broker_writes=0 orders=0 db_writes=0
production_profile_writes=0 runtime_activation=0
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Mapping, Sequence

import pandas as pd

from src.features.indicators import atr as compute_atr_series
from src.features.indicators import ema as compute_ema_series
from src.market_data.fib_navigation_map_v1 import (
    DEFAULT_ATR_PERIOD,
    DEFAULT_MIN_CANDLES,
    DEFAULT_PIVOT_SPAN,
    DIRECTION_BEARISH,
    DIRECTION_BULLISH,
    MAP_STATE_NO_DATA,
    MAP_STATE_STALE,
    FibNavCandle,
    FibNavigationMap,
    build_fib_navigation_map,
)
from src.structure.trend_state_v1 import (
    ENGINE_NAME as TREND_ENGINE_NAME,
    ENGINE_VERSION as TREND_ENGINE_VERSION,
    compute_trend_state,
)

BUILDER_NAME = "historical_fib_map_episode_substrate_v1"
BUILDER_VERSION = "1.0.0"
CONTRACT_VERSION = "1.0.0"

GEOMETRY_ENGINE_MODULE = "src.market_data.fib_navigation_map_v1"
GEOMETRY_ENGINE_FUNCTION = "build_fib_navigation_map"

TREND_STATE_TO_DIRECTION: Mapping[str, str] = {
    "UPTREND_STRONG": DIRECTION_BULLISH,
    "UPTREND_WEAK": DIRECTION_BULLISH,
    "DOWNTREND_STRONG": DIRECTION_BEARISH,
    "DOWNTREND_WEAK": DIRECTION_BEARISH,
}

# ---------------------------------------------------------------------------
# Lifecycle transition reasons
# ---------------------------------------------------------------------------
# TARGET1_REACHED / TARGET2_REACHED / INVALIDATION_BREACHED reuse the same
# semantic meaning as the canonical fib_navigation_map_v1 rebuild triggers
# (TRIGGER_ALL_TARGETS_PASSED / TRIGGER_PRICE_BELOW_INVALIDATION). The
# remaining two reasons are research-only concepts: production runs forward
# live and never needs to say "the replay window ran out".
LIFECYCLE_REASON_TARGET1_REACHED = "TARGET1_REACHED"
LIFECYCLE_REASON_TARGET2_REACHED = "TARGET2_REACHED"
LIFECYCLE_REASON_INVALIDATION_BREACHED = "INVALIDATION_BREACHED"
LIFECYCLE_REASON_FORWARD_WINDOW_EXHAUSTED = "FORWARD_WINDOW_EXHAUSTED"
LIFECYCLE_REASON_SOURCE_DATA_EXHAUSTED = "SOURCE_DATA_EXHAUSTED"

TERMINAL_LIFECYCLE_REASONS = frozenset(
    {
        LIFECYCLE_REASON_TARGET1_REACHED,
        LIFECYCLE_REASON_TARGET2_REACHED,
        LIFECYCLE_REASON_INVALIDATION_BREACHED,
        LIFECYCLE_REASON_FORWARD_WINDOW_EXHAUSTED,
        LIFECYCLE_REASON_SOURCE_DATA_EXHAUSTED,
    }
)


class EpisodeSubstrateError(ValueError):
    pass


class PitViolationError(EpisodeSubstrateError):
    """Raised when a future candle would leak into feature/geometry construction."""


# ---------------------------------------------------------------------------
# Per-timeframe configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EpisodeConfig:
    interval_code: str
    interval_seconds: int
    pivot_span: int = DEFAULT_PIVOT_SPAN
    min_candles: int = DEFAULT_MIN_CANDLES
    lookback_candles: int = 180
    atr_period: int = DEFAULT_ATR_PERIOD
    ema_fast_span: int = 20
    ema_slow_span: int = 50
    stale_after_multiple_candles: int = 6
    forward_max_candles: int = 500

    @property
    def stale_after(self) -> timedelta:
        return timedelta(seconds=self.interval_seconds * self.stale_after_multiple_candles)


TIMEFRAME_CONFIGS: Mapping[str, EpisodeConfig] = {
    "1h": EpisodeConfig(interval_code="1h", interval_seconds=3600),
    "4h": EpisodeConfig(interval_code="4h", interval_seconds=4 * 3600),
}


def resolve_config(timeframe: str) -> EpisodeConfig:
    try:
        return TIMEFRAME_CONFIGS[timeframe]
    except KeyError as exc:
        raise EpisodeSubstrateError(
            f"unsupported timeframe {timeframe!r}; supported={sorted(TIMEFRAME_CONFIGS)}"
        ) from exc


# ---------------------------------------------------------------------------
# Candle input contract
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HistoricalCandle:
    symbol: str
    venue: str
    interval_code: str
    open_ts_utc: datetime
    close_ts_utc: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: Decimal = Decimal("0")

    def to_fib_nav_candle(self) -> FibNavCandle:
        return FibNavCandle(
            close_ts_utc=self.close_ts_utc,
            open_price=self.open_price,
            high_price=self.high_price,
            low_price=self.low_price,
            close_price=self.close_price,
            volume=self.volume,
        )


def validate_candle_sequence(candles: Sequence[HistoricalCandle]) -> None:
    """Reject duplicate or non-monotonic candle sequences.

    Required safeguard for #555: historical replay must fail closed on
    malformed source data rather than silently tolerate it.
    """
    seen_ts: set[datetime] = set()
    prev_ts: datetime | None = None
    for candle in candles:
        ts = candle.close_ts_utc
        if ts in seen_ts:
            raise EpisodeSubstrateError(f"duplicate candle close_ts_utc={ts.isoformat()}")
        seen_ts.add(ts)
        if prev_ts is not None and ts <= prev_ts:
            raise EpisodeSubstrateError(
                f"non-monotonic candle sequence: {ts.isoformat()} <= {prev_ts.isoformat()}"
            )
        prev_ts = ts


# ---------------------------------------------------------------------------
# Feature payload (PIT-only) and outcome labels (forward-only)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EpisodeFeaturePayload:
    episode_id: str
    symbol: str
    venue: str
    source_timeframe: str
    builder_name: str
    builder_version: str
    contract_version: str
    geometry_engine_module: str
    geometry_engine_function: str
    trend_engine_name: str
    trend_engine_version: str
    map_creation_ts_utc: datetime
    source_candle_first_ts_utc: datetime
    source_candle_last_ts_utc: datetime
    source_candle_count: int
    direction: str
    anchor_low_price: Decimal
    anchor_low_ts_utc: datetime
    anchor_high_price: Decimal
    anchor_high_ts_utc: datetime
    anchor_span_candles: int
    anchor_span_elapsed_seconds: float
    swing_amplitude_pct: Decimal
    reference_price: Decimal
    entry_zone_low: Decimal
    entry_zone_high: Decimal
    entry_zone_mid: Decimal
    target_t1: Decimal
    target_t2: Decimal
    target_extension: Decimal
    invalidation_level: Decimal
    atr_value: Decimal
    atr_period: int
    target_t1_distance_pct: Decimal
    target_t2_distance_pct: Decimal
    invalidation_distance_pct: Decimal
    target_t1_distance_atr: Decimal | None
    target_t2_distance_atr: Decimal | None
    invalidation_distance_atr: Decimal | None
    map_state: str
    map_confidence: str
    rebuild_trigger: str


@dataclass(frozen=True)
class EpisodeOutcomeLabels:
    episode_id: str
    first_entry_ts_utc: datetime | None
    time_to_first_entry_seconds: float | None
    target1_ts_utc: datetime | None
    time_to_target1_seconds: float | None
    target2_ts_utc: datetime | None
    time_to_target2_seconds: float | None
    invalidation_ts_utc: datetime | None
    time_to_invalidation_seconds: float | None
    terminal_ts_utc: datetime
    map_lifetime_seconds: float
    lifecycle_transition_reason: str
    num_source_candles_until_terminal: int
    forward_candles_scanned: int


@dataclass(frozen=True)
class EpisodeRecord:
    feature: EpisodeFeaturePayload
    labels: EpisodeOutcomeLabels


# ---------------------------------------------------------------------------
# Deterministic identity
# ---------------------------------------------------------------------------

def compute_episode_id(
    *,
    symbol: str,
    venue: str,
    interval_code: str,
    contract_version: str,
    map_creation_ts_utc: datetime,
    direction: str,
    anchor_low_price: Decimal,
    anchor_high_price: Decimal,
) -> str:
    payload = "|".join(
        [
            symbol,
            venue,
            interval_code,
            contract_version,
            map_creation_ts_utc.astimezone(timezone.utc).isoformat(),
            direction,
            format(anchor_low_price, "f"),
            format(anchor_high_price, "f"),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Direction classification (reuses canonical trend_state_v1)
# ---------------------------------------------------------------------------

def classify_direction(window: Sequence[HistoricalCandle], cfg: EpisodeConfig) -> tuple[str | None, str, Decimal]:
    """Return (direction_or_None, trend_state, trend_score) for the PIT window.

    direction is None when the trend state has no directional Fib map
    (e.g. RANGE), mirroring the canonical producer's eligibility rule.
    """
    closes = pd.Series([float(c.close_price) for c in window])
    ema_fast = compute_ema_series(closes, cfg.ema_fast_span)
    ema_slow = compute_ema_series(closes, cfg.ema_slow_span)

    last_close = closes.iloc[-1]
    last_fast = ema_fast.iloc[-1]
    last_slow = ema_slow.iloc[-1]

    price_vs_ema20 = (last_close - last_fast) / last_fast if last_fast else 0.0
    price_vs_ema50 = (last_close - last_slow) / last_slow if last_slow else 0.0
    ema_spread_pct = (last_fast - last_slow) / last_slow if last_slow else 0.0

    trend_row = {
        "price_vs_ema20": price_vs_ema20,
        "price_vs_ema50": price_vs_ema50,
        "ema_spread_pct": ema_spread_pct,
    }
    trend_state, trend_score = compute_trend_state(trend_row)
    direction = TREND_STATE_TO_DIRECTION.get(trend_state)
    return direction, trend_state, trend_score


# ---------------------------------------------------------------------------
# Level lookup (bookkeeping only — not Fib math; reads the canonical
# geometry engine's already-computed level tuples)
# ---------------------------------------------------------------------------

def _find_level(map_: FibNavigationMap, label: str) -> Decimal:
    for level in (*map_.retracement_levels, *map_.extension_levels):
        if level.label == label:
            return level.price
    raise EpisodeSubstrateError(f"canonical map is missing required level {label!r}")


def _find_anchor_ts(window: Sequence[HistoricalCandle], *, low: Decimal, high: Decimal) -> tuple[datetime, datetime]:
    low_ts: datetime | None = None
    high_ts: datetime | None = None
    for candle in window:
        if low_ts is None and candle.low_price == low:
            low_ts = candle.close_ts_utc
        if high_ts is None and candle.high_price == high:
            high_ts = candle.close_ts_utc
    if low_ts is None or high_ts is None:
        raise EpisodeSubstrateError("anchor price not found among PIT window candles")
    return low_ts, high_ts


# ---------------------------------------------------------------------------
# Feature construction (PIT-only)
# ---------------------------------------------------------------------------

def build_episode_feature(
    *,
    symbol: str,
    venue: str,
    window: Sequence[HistoricalCandle],
    cfg: EpisodeConfig,
) -> EpisodeFeaturePayload | None:
    """Build a PIT-safe episode feature payload from a candle window ending at as-of.

    `window` must contain only candles observable at map-creation time (the
    last candle in `window` IS the as-of candle). Returns None when no
    admissible directional Fib map exists at this as-of point (RANGE state,
    insufficient data, or a canonical MAP_STATE_NO_DATA/STALE result).
    """
    if not window:
        return None

    asof_ts_utc = window[-1].close_ts_utc
    for candle in window:
        if candle.close_ts_utc > asof_ts_utc:
            raise PitViolationError("feature construction received a candle after as-of time")

    if len(window) < cfg.min_candles:
        return None

    direction, trend_state, _trend_score = classify_direction(window, cfg)
    if direction is None:
        return None

    fib_candles = [c.to_fib_nav_candle() for c in window]
    reference_price = window[-1].close_price

    map_ = build_fib_navigation_map(
        candles=fib_candles,
        current_price=reference_price,
        now_utc=asof_ts_utc,
        prior=None,
        direction=direction,
        pivot_span=cfg.pivot_span,
        min_candles=cfg.min_candles,
        stale_after=cfg.stale_after,
    )

    if map_.map_state in {MAP_STATE_NO_DATA, MAP_STATE_STALE} or not map_.extension_levels:
        return None
    if map_.direction != direction:
        raise EpisodeSubstrateError(
            f"{symbol}: canonical map direction {map_.direction} contradicts classified direction {direction}"
        )

    r382 = _find_level(map_, "r_0382")
    r500 = _find_level(map_, "r_0500")
    r618 = _find_level(map_, "r_0618")
    invalidation = _find_level(map_, "r_1000")
    t1 = _find_level(map_, "ext_1272")
    t2 = _find_level(map_, "ext_1618")
    extension = _find_level(map_, "ext_2618")

    low_ts, high_ts = _find_anchor_ts(window, low=map_.anchor_low, high=map_.anchor_high)
    anchor_span_candles = sum(
        1 for c in window if min(low_ts, high_ts) <= c.close_ts_utc <= max(low_ts, high_ts)
    )
    anchor_span_elapsed_seconds = abs((high_ts - low_ts).total_seconds())
    swing_amplitude_pct = ((map_.anchor_high - map_.anchor_low) / map_.anchor_low) * Decimal("100")

    df = pd.DataFrame(
        {
            "high": [float(c.high_price) for c in window],
            "low": [float(c.low_price) for c in window],
            "close": [float(c.close_price) for c in window],
        }
    )
    atr_series = compute_atr_series(df, cfg.atr_period)
    atr_raw = atr_series.iloc[-1]
    atr_value = Decimal(str(atr_raw)) if pd.notna(atr_raw) and atr_raw > 0 else Decimal("0")

    def _distance_pct(level: Decimal) -> Decimal:
        return (abs(level - reference_price) / reference_price) * Decimal("100")

    def _distance_atr(level: Decimal) -> Decimal | None:
        if atr_value <= 0:
            return None
        return abs(level - reference_price) / atr_value

    episode_id = compute_episode_id(
        symbol=symbol,
        venue=venue,
        interval_code=cfg.interval_code,
        contract_version=CONTRACT_VERSION,
        map_creation_ts_utc=asof_ts_utc,
        direction=direction,
        anchor_low_price=map_.anchor_low,
        anchor_high_price=map_.anchor_high,
    )

    return EpisodeFeaturePayload(
        episode_id=episode_id,
        symbol=symbol,
        venue=venue,
        source_timeframe=cfg.interval_code,
        builder_name=BUILDER_NAME,
        builder_version=BUILDER_VERSION,
        contract_version=CONTRACT_VERSION,
        geometry_engine_module=GEOMETRY_ENGINE_MODULE,
        geometry_engine_function=GEOMETRY_ENGINE_FUNCTION,
        trend_engine_name=TREND_ENGINE_NAME,
        trend_engine_version=TREND_ENGINE_VERSION,
        map_creation_ts_utc=asof_ts_utc,
        source_candle_first_ts_utc=window[0].close_ts_utc,
        source_candle_last_ts_utc=asof_ts_utc,
        source_candle_count=len(window),
        direction=direction,
        anchor_low_price=map_.anchor_low,
        anchor_low_ts_utc=low_ts,
        anchor_high_price=map_.anchor_high,
        anchor_high_ts_utc=high_ts,
        anchor_span_candles=anchor_span_candles,
        anchor_span_elapsed_seconds=anchor_span_elapsed_seconds,
        swing_amplitude_pct=swing_amplitude_pct,
        reference_price=reference_price,
        entry_zone_low=min(r382, r618),
        entry_zone_high=max(r382, r618),
        entry_zone_mid=r500,
        target_t1=t1,
        target_t2=t2,
        target_extension=extension,
        invalidation_level=invalidation,
        atr_value=atr_value,
        atr_period=cfg.atr_period,
        target_t1_distance_pct=_distance_pct(t1),
        target_t2_distance_pct=_distance_pct(t2),
        invalidation_distance_pct=_distance_pct(invalidation),
        target_t1_distance_atr=_distance_atr(t1),
        target_t2_distance_atr=_distance_atr(t2),
        invalidation_distance_atr=_distance_atr(invalidation),
        map_state=map_.map_state,
        map_confidence=map_.confidence,
        rebuild_trigger=map_.rebuild_trigger,
    )


# ---------------------------------------------------------------------------
# Label construction (forward-only)
# ---------------------------------------------------------------------------

def build_episode_labels(
    *,
    feature: EpisodeFeaturePayload,
    forward_candles: Sequence[HistoricalCandle],
    cfg: EpisodeConfig,
) -> EpisodeOutcomeLabels:
    """Compute forward-only lifecycle labels for a previously built feature.

    `forward_candles` must contain only candles strictly after
    `feature.map_creation_ts_utc`. This is the structural PIT tripwire: any
    candle at/before as-of raises PitViolationError.
    """
    for candle in forward_candles:
        if candle.close_ts_utc <= feature.map_creation_ts_utc:
            raise PitViolationError(
                "label construction received a candle at/before map_creation_ts_utc"
            )

    bullish = feature.direction == DIRECTION_BULLISH

    first_entry_ts: datetime | None = None
    target1_ts: datetime | None = None
    target2_ts: datetime | None = None
    invalidation_ts: datetime | None = None

    scanned = 0
    terminal_ts = feature.map_creation_ts_utc
    reason = LIFECYCLE_REASON_SOURCE_DATA_EXHAUSTED

    bounded = forward_candles[: cfg.forward_max_candles]
    for candle in bounded:
        scanned += 1
        terminal_ts = candle.close_ts_utc

        if first_entry_ts is None:
            touches_entry = candle.low_price <= feature.entry_zone_high and candle.high_price >= feature.entry_zone_low
            if touches_entry:
                first_entry_ts = candle.close_ts_utc

        if bullish:
            invalidation_hit = candle.low_price <= feature.invalidation_level
            target1_hit = candle.high_price >= feature.target_t1
            target2_hit = candle.high_price >= feature.target_t2
        else:
            invalidation_hit = candle.high_price >= feature.invalidation_level
            target1_hit = candle.low_price <= feature.target_t1
            target2_hit = candle.low_price <= feature.target_t2

        if target1_ts is None and target1_hit:
            target1_ts = candle.close_ts_utc
        if target2_ts is None and target2_hit:
            target2_ts = candle.close_ts_utc
        if invalidation_ts is None and invalidation_hit:
            invalidation_ts = candle.close_ts_utc

        if invalidation_ts is not None:
            reason = LIFECYCLE_REASON_INVALIDATION_BREACHED
            break
        if target2_ts is not None:
            reason = LIFECYCLE_REASON_TARGET2_REACHED
            break
        if target1_ts is not None:
            reason = LIFECYCLE_REASON_TARGET1_REACHED
            break
    else:
        if len(forward_candles) > cfg.forward_max_candles:
            reason = LIFECYCLE_REASON_FORWARD_WINDOW_EXHAUSTED
        else:
            reason = LIFECYCLE_REASON_SOURCE_DATA_EXHAUSTED

    def _seconds(ts: datetime | None) -> float | None:
        if ts is None:
            return None
        return (ts - feature.map_creation_ts_utc).total_seconds()

    return EpisodeOutcomeLabels(
        episode_id=feature.episode_id,
        first_entry_ts_utc=first_entry_ts,
        time_to_first_entry_seconds=_seconds(first_entry_ts),
        target1_ts_utc=target1_ts,
        time_to_target1_seconds=_seconds(target1_ts),
        target2_ts_utc=target2_ts,
        time_to_target2_seconds=_seconds(target2_ts),
        invalidation_ts_utc=invalidation_ts,
        time_to_invalidation_seconds=_seconds(invalidation_ts),
        terminal_ts_utc=terminal_ts,
        map_lifetime_seconds=(terminal_ts - feature.map_creation_ts_utc).total_seconds(),
        lifecycle_transition_reason=reason,
        num_source_candles_until_terminal=scanned,
        forward_candles_scanned=scanned,
    )


# ---------------------------------------------------------------------------
# Orchestration over a full candle series for one symbol/timeframe
# ---------------------------------------------------------------------------

def build_episodes(
    *,
    symbol: str,
    venue: str,
    candles: Sequence[HistoricalCandle],
    cfg: EpisodeConfig,
    episode_stride_candles: int = 1,
    max_episodes: int | None = None,
) -> list[EpisodeRecord]:
    """Build a deterministic list of episodes from a full historical candle series.

    Candles must already be validated (validate_candle_sequence) and sorted
    ascending by close_ts_utc. `episode_stride_candles` bounds episode volume
    by only attempting map creation every N candles; it does not change the
    PIT boundary of any individual episode.
    """
    validate_candle_sequence(candles)

    records: list[EpisodeRecord] = []
    for i in range(cfg.min_candles - 1, len(candles)):
        if (i - (cfg.min_candles - 1)) % episode_stride_candles != 0:
            continue

        window_start = max(0, i - cfg.lookback_candles + 1)
        window = candles[window_start : i + 1]

        feature = build_episode_feature(symbol=symbol, venue=venue, window=window, cfg=cfg)
        if feature is None:
            continue

        forward_candles = candles[i + 1 :]
        labels = build_episode_labels(feature=feature, forward_candles=forward_candles, cfg=cfg)

        records.append(EpisodeRecord(feature=feature, labels=labels))
        if max_episodes is not None and len(records) >= max_episodes:
            break

    return records


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def episode_record_to_dict(record: EpisodeRecord) -> dict[str, Any]:
    return {
        "feature": record.feature.__dict__,
        "labels": record.labels.__dict__,
    }


def episodes_to_json(records: Sequence[EpisodeRecord]) -> str:
    payload = [episode_record_to_dict(r) for r in records]
    return json.dumps(payload, indent=2, sort_keys=True, default=_json_default) + "\n"
