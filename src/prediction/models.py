from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass(slots=True)
class PredictionRun:
    created_ts: datetime
    source: str
    strategy_name: str
    timeframe_code: str
    horizon_days: int
    notes: str | None = None


@dataclass(slots=True)
class PredictionItem:
    asset_code: str
    created_ts: datetime
    anchor_tf: str
    horizon_end_ts: datetime
    regime_call: str | None = None
    direction_call: str | None = None
    magnitude_call: str | None = None
    timing_call: str | None = None
    target_price: Decimal | None = None
    target_currency: str = "EUR"
    invalidation_price: Decimal | None = None
    entry_zone_low: Decimal | None = None
    entry_zone_high: Decimal | None = None
    conviction_total: Decimal | None = None
    status: str = "open"
    notes: str | None = None


@dataclass(slots=True)
class PredictionFactor:
    factor_type: str
    factor_name: str
    factor_value_text: str | None = None
    factor_value_num: Decimal | None = None
    factor_score: Decimal | None = None
    factor_weight: Decimal | None = None
    evidence_json: dict[str, Any] | None = None
    notes: str | None = None


@dataclass(slots=True)
class PredictionDraft:
    run: PredictionRun
    item: PredictionItem
    factors: list[PredictionFactor] = field(default_factory=list)
