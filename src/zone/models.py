from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class CandleRow:
    asset_id: int
    symbol: str
    venue: str
    interval_code: str
    open_ts_utc: datetime
    close_ts_utc: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal


@dataclass(frozen=True)
class SwingPoint:
    point_type: str  # SWING_HIGH | SWING_LOW
    ts_utc: datetime
    price: Decimal
    index: int


@dataclass(frozen=True)
class FibObservationInput:
    asset_id: int
    symbol: str
    venue: str
    interval_code: str
    asof_ts_utc: datetime
    anchor_start_ts_utc: datetime
    anchor_end_ts_utc: datetime
    anchor_start_price: Decimal
    anchor_end_price: Decimal
    leg_direction: str
    anchor_span_bars: int
    anchor_move_pct: Decimal
    fib_0236_price: Decimal
    fib_0382_price: Decimal
    fib_0500_price: Decimal
    fib_0618_price: Decimal
    fib_0786_price: Decimal
    ext_1272_price: Decimal
    ext_1618_price: Decimal
    active_retracement_price: Decimal
    active_extension_price: Decimal
    fib_confluence_score: Decimal
    structure_quality_score: Decimal
    source_type: str
    notes: str | None


@dataclass(frozen=True)
class ZoneObservationInput:
    asset_id: int
    symbol: str
    venue: str
    interval_code: str
    asof_ts_utc: datetime
    zone_type: str
    zone_source_type: str
    zone_low_price: Decimal
    zone_high_price: Decimal
    zone_mid_price: Decimal
    zone_width_pct: Decimal
    expected_reaction: str | None
    invalidation_price: Decimal | None
    zone_strength_score: Decimal
    confluence_score: Decimal
    touch_count: int
    break_count: int
    zone_age_bars: int
    source_ref_type: str | None
    source_ref_id: int | None
    parent_zone_observation_id: int | None
    notes: str | None


@dataclass(frozen=True)
class ExecutionZoneContextInput:
    asset_id: int
    symbol: str
    venue: str
    sleeve_code: str
    interval_code: str
    asof_ts_utc: datetime
    dominant_tf: str
    expected_entry_zone_low: Decimal | None
    expected_entry_zone_high: Decimal | None
    expected_entry_zone_type: str | None
    expected_take_profit_zone_low: Decimal | None
    expected_take_profit_zone_high: Decimal | None
    expected_take_profit_zone_type: str | None
    invalidation_price: Decimal | None
    zone_confidence_score: Decimal
    zone_alignment_score: Decimal
    source_timeframes: str
    source_types: str
    source_ref_json: str
    notes: str | None


@dataclass(frozen=True)
class ZoneEngineResult:
    asset_id: int
    symbol: str
    venue: str
    interval_code: str
    asof_ts_utc: datetime
    leg_direction: str
    fib_observation: FibObservationInput
    zones: list[ZoneObservationInput]
    execution_context: ExecutionZoneContextInput
