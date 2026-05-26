from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class StrategyInstanceConfig:
    strategy_instance_id: str
    strategy_family: str
    symbol: str
    venue: str
    quote: str
    enabled: bool
    mode: str
    capital_bucket: str
    primary_tf: str
    entry_tf: str
    context_tf: str
    max_candidate_age_seconds: int
    min_confidence_score: float
    max_risk_severity_score: float
    execution_profile: str


@dataclass(frozen=True)
class StrategyCandidate:
    strategy_candidate_id: str
    strategy_instance_id: str
    strategy_family: str
    symbol: str
    venue: str
    quote: str
    horizon_bucket: str
    primary_timeframe: str
    entry_timeframe: str
    candidate_state: str
    entry_state: str
    direction_pressure: float
    exposure_delta_pressure: float
    entry_quality_score: float
    risk_severity_score: float
    confidence_score: float
    freshness_state: str
    created_at_utc: str
    source_context: dict[str, Any]
    safety_markers: dict[str, Any]


@dataclass(frozen=True)
class DecisionPreview:
    strategy_candidate_id: str
    trading_account_id: int | None
    decision_state: str
    permission_state: str
    block_reasons: tuple[str, ...]
    account_awareness: str
    live_trading_enabled: bool
    broker_write_permission: bool
    notes: str


@dataclass(frozen=True)
class ExecutionPlanPreview:
    decision_preview_id: str
    execution_plan_state: str
    execution_profile: str
    side: str
    symbol: str
    quote: str
    max_notional_preview: float | None
    limit_price_preview: float | None
    ladder_steps_preview: tuple[dict[str, Any], ...]
    timeout_seconds: int
    cancel_conditions: tuple[str, ...]
    mode: str
    executor_enabled: bool = False
    no_order_submission: bool = True


@dataclass(frozen=True)
class ShadowEvent:
    strategy_instance_id: str
    candidate_state: str
    decision_state: str
    execution_plan_state: str
    observed_price: float
    event_ts_utc: str
    no_order_submitted: bool = True


NEAR_INTRADAY_RETEST_RECLAIM_V1 = StrategyInstanceConfig(
    strategy_instance_id="near_intraday_retest_reclaim_v1",
    strategy_family="INTRADAY_RETEST_RECLAIM_V1",
    symbol="NEAR",
    venue="bitvavo",
    quote="EUR",
    enabled=True,
    mode="shadow",
    capital_bucket="INTRADAY_TEST",
    primary_tf="1h",
    entry_tf="15m",
    context_tf="4h",
    max_candidate_age_seconds=900,
    min_confidence_score=0.55,
    max_risk_severity_score=0.45,
    execution_profile="PASSIVE_LIMIT_RETEST",
)


def to_dict(value: Any) -> dict[str, Any]:
    return asdict(value)
