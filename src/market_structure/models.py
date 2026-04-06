from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional


@dataclass(slots=True)
class ZoneObservation:
    asset_id: int
    interval_code: str
    zone_type: str
    zone_low: Decimal
    zone_high: Decimal
    zone_strength: Decimal
    zone_source: str
    touch_count: int
    last_touch_ts_utc: Optional[datetime]
    is_active: bool


@dataclass(slots=True)
class FibObservation:
    asset_id: int
    interval_code: str
    anchor_start_ts_utc: datetime
    anchor_end_ts_utc: datetime
    swing_direction: str
    fib_level: Decimal
    fib_price: Decimal
    is_retracement: bool
    is_extension: bool
    confluence_score: Decimal
    is_active: bool


@dataclass(slots=True)
class WaveCountSet:
    asset_id: int
    interval_code: str
    count_state: str
    bias: str
    confidence_score: Decimal
    invalidation_price: Optional[Decimal]
    is_primary_count: bool
    is_alternate_count: bool


@dataclass(slots=True)
class WaveCountObservation:
    asset_id: int
    interval_code: str
    wave_label: str
    start_ts_utc: datetime
    end_ts_utc: datetime
    start_price: Decimal
    end_price: Decimal
    confidence_score: Decimal
    invalidation_price: Optional[Decimal]
    parent_wave_id: Optional[int]


@dataclass(slots=True)
class StrategySignalContext:
    asset_id: int
    interval_code: str
    context_ts_utc: datetime
    zone_state: str
    fib_state: str
    wave_label: Optional[str]
    wave_confidence: Optional[Decimal]
    zone_confluence_score: Decimal
    fib_confluence_score: Decimal
    context_score: Decimal
    volume_ratio: Optional[Decimal] = None
    volume_zscore: Optional[Decimal] = None
    volume_state: Optional[str] = None
    volume_alignment_score: Optional[Decimal] = None
    distance_to_support: Optional[Decimal] = None
    distance_to_resistance: Optional[Decimal] = None
    distance_to_support_bps: Optional[Decimal] = None
    distance_to_resistance_bps: Optional[Decimal] = None
    fib_level: Optional[Decimal] = None
    fib_price: Optional[Decimal] = None
    fib_distance_bps: Optional[Decimal] = None


@dataclass(slots=True)
class ExecutionPlan:
    asset_id: int
    sleeve_code: str
    desired_action: str
    plan_ts_utc: datetime
    execution_mode: str
    target_fraction: Decimal
    reference_price_eur: Optional[Decimal]
    passive_price_eur: Optional[Decimal]
    urgent_limit_price_eur: Optional[Decimal]
    max_reprices: int
    max_wait_seconds: int
    max_chase_bps: Decimal
    min_spread_bps_for_capture: Decimal
    escalation_to_urgent_limit: bool
    abort_if_signal_invalidates: bool
    plan_state: str
    notes: Optional[str]
