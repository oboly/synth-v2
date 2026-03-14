from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from synth.common.enums import ConfidenceLabel, DirectionLabel, MagnitudeLabel, PhaseLabel


@dataclass(slots=True)
class APlusRun:
    created_ts: datetime
    source_name: str
    model_variant: str
    prompt_label: str | None = None
    source_session_ref: str | None = None
    notes: str | None = None


@dataclass(slots=True)
class APlusSignal:
    asset_code: str
    created_ts: datetime
    phase_label: PhaseLabel | None = None
    direction_label: DirectionLabel | None = None
    magnitude_label: MagnitudeLabel | None = None
    confidence_label: ConfidenceLabel | None = None
    confidence_score: Decimal | None = None
    horizon_label: str | None = None
    horizon_end_ts: datetime | None = None
    target_price: Decimal | None = None
    target_currency: str = "EUR"
    raw_excerpt: str | None = None
    notes: str | None = None


@dataclass(slots=True)
class APlusFactor:
    factor_name: str
    factor_value_text: str | None = None
    factor_value_num: Decimal | None = None
    factor_unit: str | None = None
    notes: str | None = None


@dataclass(slots=True)
class ParsedAPlusAssetBlock:
    signal: APlusSignal
    factors: list[APlusFactor] = field(default_factory=list)
    raw_block: str | None = None


@dataclass(slots=True)
class ParsedAPlusDocument:
    run: APlusRun
    raw_text: str
    assets: list[ParsedAPlusAssetBlock]
    metadata: dict[str, Any] = field(default_factory=dict)
