from __future__ import annotations

"""
Synth v2 - Trade Setup Filter V1 models.

LAYER:
market-only setup/context filter

BOUNDARY:
These models may describe market setup eligibility only.
They must not include account, balance, position, order, or execution-plan state.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class TradeSetupCandidate:
    asset_id: int
    symbol: str
    venue: str
    asof_ts_utc: datetime
    context_ts_utc: datetime | None
    selection_state: str
    selection_bias: str | None
    selection_score: Decimal | None
    priority_rank: int | None
    allowed_sleeves: str | None
    btc_prior_24h: Decimal | None
    summary_text: str | None


@dataclass(frozen=True)
class TradeSetupDecision:
    asset_id: int
    symbol: str
    venue: str
    asof_ts_utc: datetime
    context_ts_utc: datetime | None
    selection_state: str
    selection_bias: str | None
    selection_score: Decimal | None
    priority_rank: int | None
    allowed_sleeves: str | None
    btc_prior_24h: Decimal | None
    setup_filter_state: str
    setup_filter_reason: str
    target_horizon: str
    notes: str
