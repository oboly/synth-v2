from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class AssetProfileSnapshot:
    asset_id: int
    symbol: str
    venue: str
    interval_code: str
    asof_ts_utc: datetime
    lookback_days: int
    profile_version: str
    liquidity_score: Decimal | None
    liquidity_class: str | None
    beta_to_market: Decimal | None
    beta_profile: str | None
    realized_volatility: Decimal | None
    sector_group_code: str | None
    sector_confidence: Decimal | None
    candles_observed: int
    coverage_ratio: Decimal | None
    benchmark_symbols: str | None
    notes: str | None
