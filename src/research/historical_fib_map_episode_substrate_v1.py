from __future__ import annotations

"""Canonical reusable historical PIT Fib/map episode substrate (#555).

Pure, deterministic, market-only. No DB access, no wall-clock dependence.

Reuses the SAME canonical projection/geometry code path as production:

- src.market_data.canonical_fib_zone_map_v1.build_row
    (canonical map eligibility, direction/map projection, anchor
    timestamps, entry zone, targets, invalidation, map status/quality,
    provenance -- the SAME function the production 4h writer calls)
- src.market_data.fib_navigation_map_v1.build_fib_navigation_map
    (canonical Fib anchor/level geometry engine; called BY build_row, not
    duplicated here)
- src.features.indicators.ema
    (canonical EMA helper used to reconstruct the PIT trend-feature input
    build_row requires -- see _reconstruct_trend_row)
- src.features.indicators.atr
    (canonical ATR helper, used for the ATR-unit distance normalization
    that build_row does not itself compute)

This module does not reimplement Fibonacci math, pivot/swing detection,
trend classification, anchor-timestamp selection, or entry/target/
invalidation field selection. All of that is owned by `build_row` and the
canonical modules it calls. This module adds only:

- reconstruction of the PIT trend-feature input `build_row` requires, from
  raw historical candles, using the canonical `ema()` primitive and the
  exact formula `src/features/etl_candle_feat.py` persists into
  `feat_candle` (price_vs_ema20/50, ema_spread_pct) -- not a second trend
  classifier, `build_row` still owns the actual classification decision
- ATR-unit distance normalization (research-only; build_row's own
  distance_entry_to_target_pct / distance_entry_to_invalidation_pct fields
  are always None -- not computed by production)
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
from src.market_data.canonical_fib_zone_map_v1 import build_row
from src.market_data.fib_navigation_map_v1 import (
    DEFAULT_MIN_CANDLES,
    DIRECTION_BEARISH,
    DIRECTION_BULLISH,
    FibNavCandle,
)

BUILDER_NAME = "historical_fib_map_episode_substrate_v1"
BUILDER_VERSION = "2.0.0"
CONTRACT_VERSION = "1.1.0"

PROJECTION_ENGINE_MODULE = "src.market_data.canonical_fib_zone_map_v1"
PROJECTION_ENGINE_FUNCTION = "build_row"

# Exact formula this module reconstructs from raw historical candles, taken
# verbatim from src/features/etl_candle_feat.py (feat_candle producer):
#   ema_20 = close.ewm(span=20, adjust=False, min_periods=20).mean()
#   ema_50 = close.ewm(span=50, adjust=False, min_periods=50).mean()
#   price_vs_ema20 = (close / ema_20) - 1.0
#   price_vs_ema50 = (close / ema_50) - 1.0
#   ema_spread_pct = (ema_20 / ema_50) - 1.0
TREND_FEATURE_SOURCE_FORMULA = "src.features.etl_candle_feat (price_vs_ema20/50, ema_spread_pct)"
TREND_FEATURE_EMA_FAST_SPAN = 20
TREND_FEATURE_EMA_SLOW_SPAN = 50

DIRECTION_FROM_CURRENT_LEG: Mapping[str, str] = {
    "UP": DIRECTION_BULLISH,
    "DOWN": DIRECTION_BEARISH,
}

# ---------------------------------------------------------------------------
# Lifecycle transition reasons
# ---------------------------------------------------------------------------
# TARGET2_REACHED / INVALIDATION_BREACHED reuse the same semantic meaning as
# the canonical fib_navigation_map_v1 rebuild triggers
# (TRIGGER_ALL_TARGETS_PASSED / TRIGGER_PRICE_BELOW_INVALIDATION). The
# remaining reasons are research-only concepts: production runs forward
# live and never needs to say "the replay window ran out" or "the source
# candle for this bar touched both sides and OHLC cannot order them".
#
# TARGET1_REACHED is NOT a terminal transition reason: T1 records
# target1_ts_utc without ending the scan, so #555 can observe time-to-T1 AND
# time-to-T2 in the same episode. The label is kept as a named constant only
# because target1_ts_utc/time_to_target1_seconds on EpisodeOutcomeLabels
# still needs a stable name for "T1 was reached" in docs/tests; it never
# appears as `lifecycle_transition_reason`.
LIFECYCLE_REASON_TARGET1_REACHED = "TARGET1_REACHED"
LIFECYCLE_REASON_TARGET2_REACHED = "TARGET2_REACHED"
LIFECYCLE_REASON_INVALIDATION_BREACHED = "INVALIDATION_BREACHED"
LIFECYCLE_REASON_FORWARD_WINDOW_EXHAUSTED = "FORWARD_WINDOW_EXHAUSTED"
LIFECYCLE_REASON_SOURCE_DATA_EXHAUSTED = "SOURCE_DATA_EXHAUSTED"

# A single OHLC candle only records the high and low reached during the
# bar, not the order in which they were touched. When a candle's range
# crosses BOTH a target level and the invalidation level, there is no way
# to determine from obs_market_candle whether the target or the
# invalidation happened first. This reason makes that ambiguity an explicit,
# first-class outcome rather than silently picking a side.
LIFECYCLE_REASON_AMBIGUOUS_TARGET_INVALIDATION_SAME_CANDLE = (
    "AMBIGUOUS_TARGET_INVALIDATION_SAME_CANDLE"
)

TERMINAL_LIFECYCLE_REASONS = frozenset(
    {
        LIFECYCLE_REASON_TARGET2_REACHED,
        LIFECYCLE_REASON_INVALIDATION_BREACHED,
        LIFECYCLE_REASON_FORWARD_WINDOW_EXHAUSTED,
        LIFECYCLE_REASON_SOURCE_DATA_EXHAUSTED,
        LIFECYCLE_REASON_AMBIGUOUS_TARGET_INVALIDATION_SAME_CANDLE,
    }
)

# Reasons under which the episode must NOT be counted as a target success or
# an invalidation success by downstream research (#664/#723) unless a later
# frozen protocol explicitly decides how to resolve the ambiguity.
NON_ATTRIBUTABLE_LIFECYCLE_REASONS = frozenset(
    {LIFECYCLE_REASON_AMBIGUOUS_TARGET_INVALIDATION_SAME_CANDLE}
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
    min_window_candles: int = DEFAULT_MIN_CANDLES
    lookback_candles: int = 180
    atr_period: int = 14
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
    projection_engine_module: str
    projection_engine_function: str
    map_version: str
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
    canonical_provenance_payload: Mapping[str, Any]


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
    ambiguous_ts_utc: datetime | None
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
# PIT trend-feature input reconstruction
# ---------------------------------------------------------------------------
# build_row requires a trend_row exactly aligned (by close_ts_utc) to the
# latest candle, carrying price_vs_ema20 / price_vs_ema50 / ema_spread_pct.
# In production these are read from the persisted `feat_candle` table. For
# historical replay this reconstructs the identical formula directly from
# obs_market_candle using the canonical ema() primitive, rather than
# depending on feat_candle's historical retention. This is feature-input
# reconstruction, not a second trend classifier: the actual classification
# decision (UPTREND_STRONG / RANGE / etc.) is made exactly once, inside
# build_row's own call to compute_trend_state.

def _reconstruct_trend_row(window: Sequence[HistoricalCandle]) -> dict[str, Any] | None:
    if len(window) < TREND_FEATURE_EMA_SLOW_SPAN:
        return None

    closes = pd.Series([float(c.close_price) for c in window])
    ema_fast = compute_ema_series(closes, TREND_FEATURE_EMA_FAST_SPAN)
    ema_slow = compute_ema_series(closes, TREND_FEATURE_EMA_SLOW_SPAN)

    last_close = closes.iloc[-1]
    last_fast = ema_fast.iloc[-1]
    last_slow = ema_slow.iloc[-1]
    if last_fast == 0 or last_slow == 0:
        return None

    return {
        "close_ts_utc": window[-1].close_ts_utc,
        "price_vs_ema20": (last_close / last_fast) - 1.0,
        "price_vs_ema50": (last_close / last_slow) - 1.0,
        "ema_spread_pct": (last_fast / last_slow) - 1.0,
    }


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
    last candle in `window` IS the as-of candle). Returns None when the
    canonical `build_row` projection is unavailable at this as-of point
    (RANGE state, insufficient data, missing/misaligned trend input, or a
    canonical MAP_STATE_NO_DATA/STALE result).
    """
    if not window:
        return None

    asof_ts_utc = window[-1].close_ts_utc
    for candle in window:
        if candle.close_ts_utc > asof_ts_utc:
            raise PitViolationError("feature construction received a candle after as-of time")

    if len(window) < cfg.min_window_candles:
        return None

    trend_row = _reconstruct_trend_row(window)
    fib_candles = [c.to_fib_nav_candle() for c in window]

    row = build_row(
        venue=venue,
        symbol=symbol,
        interval_code=cfg.interval_code,
        candles=fib_candles,
        now_utc=asof_ts_utc,
        trend_row=trend_row,
        prior_row=None,
        stale_after=cfg.stale_after,
    )

    if row.get("target_t1") is None:
        return None

    direction = DIRECTION_FROM_CURRENT_LEG.get(str(row.get("current_leg")))
    if direction is None:
        return None

    low_ts = row["anchor_low_ts_utc"]
    high_ts = row["anchor_high_ts_utc"]
    if not isinstance(low_ts, datetime) or not isinstance(high_ts, datetime):
        return None

    anchor_span_candles = sum(
        1 for c in window if min(low_ts, high_ts) <= c.close_ts_utc <= max(low_ts, high_ts)
    )
    anchor_span_elapsed_seconds = abs((high_ts - low_ts).total_seconds())

    reference_price = row["reference_price"]
    target_t1 = row["target_t1"]
    target_t2 = row["target_t2"]
    invalidation = row["invalidation_level"]

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
        anchor_low_price=row["anchor_low_price"],
        anchor_high_price=row["anchor_high_price"],
    )

    provenance = row.get("provenance_payload") or {}

    return EpisodeFeaturePayload(
        episode_id=episode_id,
        symbol=symbol,
        venue=venue,
        source_timeframe=cfg.interval_code,
        builder_name=BUILDER_NAME,
        builder_version=BUILDER_VERSION,
        contract_version=CONTRACT_VERSION,
        projection_engine_module=PROJECTION_ENGINE_MODULE,
        projection_engine_function=PROJECTION_ENGINE_FUNCTION,
        map_version=str(row["map_version"]),
        map_creation_ts_utc=asof_ts_utc,
        source_candle_first_ts_utc=window[0].close_ts_utc,
        source_candle_last_ts_utc=asof_ts_utc,
        source_candle_count=len(window),
        direction=direction,
        anchor_low_price=row["anchor_low_price"],
        anchor_low_ts_utc=low_ts,
        anchor_high_price=row["anchor_high_price"],
        anchor_high_ts_utc=high_ts,
        anchor_span_candles=anchor_span_candles,
        anchor_span_elapsed_seconds=anchor_span_elapsed_seconds,
        swing_amplitude_pct=row["anchor_move_pct"],
        reference_price=reference_price,
        entry_zone_low=row["entry_zone_low"],
        entry_zone_high=row["entry_zone_high"],
        entry_zone_mid=row["entry_zone_mid"],
        target_t1=target_t1,
        target_t2=target_t2,
        target_extension=row["target_extension"],
        invalidation_level=invalidation,
        atr_value=atr_value,
        atr_period=cfg.atr_period,
        target_t1_distance_pct=_distance_pct(target_t1),
        target_t2_distance_pct=_distance_pct(target_t2),
        invalidation_distance_pct=_distance_pct(invalidation),
        target_t1_distance_atr=_distance_atr(target_t1),
        target_t2_distance_atr=_distance_atr(target_t2),
        invalidation_distance_atr=_distance_atr(invalidation),
        map_state=str(row["map_status"]),
        map_confidence=str(row["map_quality"]),
        rebuild_trigger=str(provenance.get("rebuild_trigger")),
        canonical_provenance_payload=provenance,
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

    T1 is not terminal: reaching target_t1 records target1_ts_utc but the
    scan continues so target2_ts_utc / time_to_target2_seconds can still be
    observed later, exactly as #555 requires (time to T1 AND time to T2 in
    the same episode). Only T2, invalidation, same-candle ambiguity, or
    forward/source exhaustion terminate the scan.

    When a single candle's OHLC range crosses both a target level (T1 and/or
    T2) and the invalidation level, obs_market_candle cannot establish which
    happened first. That candle is labeled
    LIFECYCLE_REASON_AMBIGUOUS_TARGET_INVALIDATION_SAME_CANDLE and terminates
    the scan; target2_ts_utc / invalidation_ts_utc are NOT set for it. A
    target1_ts_utc already recorded from an earlier, non-ambiguous candle is
    preserved -- only this candle's attribution is withheld.

    Entry/outcome same-candle ambiguity: a candle's OHLC range likewise
    cannot establish whether the entry zone was touched before or after a
    terminal-outcome level (invalidation and/or target) touched in that same
    bar. first_entry_ts_utc is therefore never attributed from a candle that
    also hits invalidation and/or a target in the same bar; an earlier,
    unambiguous entry candle is preserved, and a later unambiguous candle can
    still set first_entry_ts_utc if entry has not yet been recorded.
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
    ambiguous_ts: datetime | None = None

    scanned = 0
    terminal_ts = feature.map_creation_ts_utc
    reason = LIFECYCLE_REASON_SOURCE_DATA_EXHAUSTED

    bounded = forward_candles[: cfg.forward_max_candles]
    for candle in bounded:
        scanned += 1
        terminal_ts = candle.close_ts_utc

        touches_entry = candle.low_price <= feature.entry_zone_high and candle.high_price >= feature.entry_zone_low

        if bullish:
            invalidation_hit = candle.low_price <= feature.invalidation_level
            target1_hit = candle.high_price >= feature.target_t1
            target2_hit = candle.high_price >= feature.target_t2
        else:
            invalidation_hit = candle.high_price >= feature.invalidation_level
            target1_hit = candle.low_price <= feature.target_t1
            target2_hit = candle.low_price <= feature.target_t2

        target_hit_this_candle = target1_hit or target2_hit

        if first_entry_ts is None and touches_entry and not (invalidation_hit or target_hit_this_candle):
            # A candle that touches the entry zone AND a terminal-outcome
            # level (invalidation and/or target) in the same bar cannot be
            # proven, from OHLC alone, to have reached entry before that
            # outcome. Withhold attribution for this candle only -- an
            # earlier, unambiguous entry candle (if any) is unaffected, and
            # a later unambiguous candle can still set first_entry_ts.
            first_entry_ts = candle.close_ts_utc

        if invalidation_hit and target_hit_this_candle:
            # Cannot infer target-first or invalidation-first from OHLC.
            # Do not attribute this candle to either outcome. A target1_ts
            # already recorded from an earlier, unambiguous candle is
            # preserved -- only this candle's own attribution is withheld.
            ambiguous_ts = candle.close_ts_utc
            reason = LIFECYCLE_REASON_AMBIGUOUS_TARGET_INVALIDATION_SAME_CANDLE
            break
        if invalidation_hit:
            invalidation_ts = candle.close_ts_utc
            reason = LIFECYCLE_REASON_INVALIDATION_BREACHED
            break
        if target2_hit:
            target2_ts = candle.close_ts_utc
            if target1_ts is None:
                target1_ts = candle.close_ts_utc
            reason = LIFECYCLE_REASON_TARGET2_REACHED
            break
        if target1_hit:
            # T1 is not terminal: record it and keep scanning so a later
            # T2/invalidation/ambiguity can still be observed.
            if target1_ts is None:
                target1_ts = candle.close_ts_utc
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
        ambiguous_ts_utc=ambiguous_ts,
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
    emit_from_ts_utc: datetime | None = None,
    emit_to_ts_utc: datetime | None = None,
) -> list[EpisodeRecord]:
    """Build a deterministic list of episodes from a full historical candle series.

    Candles must already be validated (validate_candle_sequence) and sorted
    ascending by close_ts_utc. `episode_stride_candles` bounds episode volume
    by only attempting map creation every N candles; it does not change the
    PIT boundary of any individual episode.

    `candles` may include pre-bound warmup history before the caller's
    requested research window (see the runner's warmup-fetch rule). Leading
    candles are used as feature input (window/EMA/ATR reconstruction) for
    as-of candles inside the requested window exactly as they would be if
    the requested window had started earlier -- this is what makes an
    as-of candle's feature output invariant to the caller's requested
    `from_ts`. `emit_from_ts_utc` / `emit_to_ts_utc`, when given, restrict
    *emission* only: an episode is appended to the result only when
    `feature.map_creation_ts_utc` falls in `[emit_from_ts_utc,
    emit_to_ts_utc)`. Warmup-region as-of candles (before
    `emit_from_ts_utc`) are still scanned to build up window/stride state
    identically to production, but never themselves produce an emitted
    episode.

    `max_episodes` bounds the emitted count and is checked before building
    each candidate episode, so `max_episodes=0` deterministically yields an
    empty list rather than one episode.
    """
    validate_candle_sequence(candles)

    records: list[EpisodeRecord] = []
    for i in range(cfg.min_window_candles - 1, len(candles)):
        if max_episodes is not None and len(records) >= max_episodes:
            break

        if (i - (cfg.min_window_candles - 1)) % episode_stride_candles != 0:
            continue

        window_start = max(0, i - cfg.lookback_candles + 1)
        window = candles[window_start : i + 1]

        feature = build_episode_feature(symbol=symbol, venue=venue, window=window, cfg=cfg)
        if feature is None:
            continue

        if emit_from_ts_utc is not None and feature.map_creation_ts_utc < emit_from_ts_utc:
            continue
        if emit_to_ts_utc is not None and feature.map_creation_ts_utc >= emit_to_ts_utc:
            continue

        forward_candles = candles[i + 1 :]
        labels = build_episode_labels(feature=feature, forward_candles=forward_candles, cfg=cfg)

        records.append(EpisodeRecord(feature=feature, labels=labels))

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
