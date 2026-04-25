from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


ALLOWED_LEVEL_VALUES = {"high", "moderate", "low"}
ALLOWED_PRESSURE_VALUES = {"up", "down", "neutral"}
ALLOWED_SHIFT_VALUES = {"strengthening", "stable", "weakening"}
ALLOWED_CLASS_VALUES = {"LEADER", "ANCHOR", "MID", "WEAK", "DRIFT"}


@dataclass(slots=True, frozen=True)
class BreathlineRunCreate:
    prediction_ts_utc: datetime
    source_name: str
    prompt_version: str
    run_label: str
    raw_text: str


@dataclass(slots=True, frozen=True)
class BreathlineTokenRow:
    token: str
    momentum: str
    stability: str
    alignment: str
    volatility: str
    pressure: str
    shift: str


@dataclass(slots=True, frozen=True)
class BreathlineTokenSnapshotCreate:
    aplus_run_id: int
    asset_id: int
    prediction_ts_utc: datetime
    momentum: str
    stability: str
    alignment: str
    volatility: str
    pressure: str
    shift: str
    aplus_initial_class: str | None
    aplus_final_class: str | None
    aplus_correction_flag: int
    aplus_correction_reason: str | None
    source_name: str
    prompt_version: str
    run_label: str


@dataclass(slots=True, frozen=True)
class BreathlineConsistencyRow:
    prediction_ts_utc: datetime
    asset_id: int
    run_count: int
    momentum_consistency: float
    stability_consistency: float
    alignment_consistency: float
    volatility_consistency: float
    pressure_consistency: float
    shift_consistency: float
    token_consistency_score: float
    aplus_initial_class: str | None
    aplus_final_class: str | None
    aplus_correction_flag: int
    aplus_correction_reason: str | None
