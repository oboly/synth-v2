"""Pure automatic SELL exit-candidate evaluation.

This is an account-aware *input evaluator* owned by ``decision_gate``.  It
does not grant permission, resolve a base quantity, construct a ladder, write
state, or import execution/broker code.  A later decision-gate integration
must validate its fraction against current account state before an execution
planner can receive any concrete intent.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Final


POLICY_NAME: Final[str] = "automatic_exit_candidate_v1"
POLICY_VERSION: Final[str] = "1"

STATE_NO_ACTION: Final[str] = "NO_ACTION"
STATE_NON_ACTIONABLE: Final[str] = "NON_ACTIONABLE"
STATE_CANDIDATE: Final[str] = "CANDIDATE"

ACTION_REDUCE: Final[str] = "REDUCE"
ACTION_EXIT: Final[str] = "EXIT"

REASON_NO_HELD_POSITION: Final[str] = "NO_HELD_POSITION"
REASON_NO_EXIT_CONDITION: Final[str] = "NO_EXIT_CONDITION"
REASON_TARGET_REACHED: Final[str] = "TARGET_REACHED"
REASON_INVALIDATION_BREACHED: Final[str] = "INVALIDATION_BREACHED"
REASON_POSITION_STALE: Final[str] = "POSITION_CONTEXT_STALE"
REASON_EXIT_CONTEXT_STALE: Final[str] = "EXIT_CONTEXT_STALE"
REASON_CONTEXT_MISMATCH: Final[str] = "POSITION_EXIT_CONTEXT_MISMATCH"
REASON_INVALID_CONTEXT: Final[str] = "INVALID_EXIT_CONTEXT"
REASON_INVALID_POLICY_CONFIG: Final[str] = "INVALID_POLICY_CONFIG"


@dataclass(frozen=True)
class AutomaticExitPositionContextV1:
    """Account-held position fact supplied by the decision-gate input loader."""

    trading_account_id: int
    position_reference: str
    venue: str
    asset_id: int
    market: str
    held_quantity_base: Decimal
    observed_ts_utc: datetime


@dataclass(frozen=True)
class AutomaticExitMarketContextV1:
    """Validated market-only exit-profile observation; no account facts."""

    venue: str
    asset_id: int
    market: str
    current_price: Decimal
    active_target_price: Decimal | None
    invalidation_price: Decimal | None
    exit_profile_id: str
    exit_profile_version: str
    evidence_id: str
    observed_ts_utc: datetime


@dataclass(frozen=True)
class AutomaticExitPolicyConfigV1:
    harvest_reduction_fraction: Decimal = Decimal("0.25")
    invalidation_exit_fraction: Decimal = Decimal("1")
    max_position_age_seconds: int = 15 * 60
    max_market_context_age_seconds: int = 15 * 60


@dataclass(frozen=True)
class AutomaticExitCandidateV1:
    trading_account_id: int
    position_reference: str
    venue: str
    asset_id: int
    market: str
    candidate_action: str  # REDUCE | EXIT
    reduction_fraction_candidate: Decimal
    urgency_candidate: str
    reason_code: str
    evidence_id: str
    exit_profile_id: str
    exit_profile_version: str
    target_price: Decimal | None
    invalidation_price: Decimal | None
    observed_ts_utc: datetime
    policy_name: str = POLICY_NAME
    policy_version: str = POLICY_VERSION


@dataclass(frozen=True)
class AutomaticExitEvaluationV1:
    state: str  # NO_ACTION | NON_ACTIONABLE | CANDIDATE
    reason_code: str
    candidate: AutomaticExitCandidateV1 | None


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _is_stale(observed_ts_utc: datetime, evaluation_ts_utc: datetime, max_age_seconds: int) -> bool:
    age = _aware(evaluation_ts_utc) - _aware(observed_ts_utc)
    return age < timedelta(0) or age > timedelta(seconds=max_age_seconds)


def _valid_fraction(value: Decimal) -> bool:
    return Decimal("0") < value <= Decimal("1")


def evaluate_automatic_exit_candidate_v1(
    *,
    position: AutomaticExitPositionContextV1,
    market_context: AutomaticExitMarketContextV1,
    evaluation_ts_utc: datetime,
    config: AutomaticExitPolicyConfigV1 = AutomaticExitPolicyConfigV1(),
) -> AutomaticExitEvaluationV1:
    """Return a non-authoritative candidate or fail closed.

    ``evaluation_ts_utc`` is explicit so equal inputs always produce equal
    output.  This function intentionally has no account-balance, reservation,
    planner, executor, or broker dependency.
    """
    if position.held_quantity_base == 0:
        return AutomaticExitEvaluationV1(STATE_NO_ACTION, REASON_NO_HELD_POSITION, None)

    if position.held_quantity_base < 0 or position.trading_account_id <= 0 or not position.position_reference.strip():
        return AutomaticExitEvaluationV1(STATE_NON_ACTIONABLE, REASON_INVALID_CONTEXT, None)

    if not _valid_fraction(config.harvest_reduction_fraction) or not _valid_fraction(config.invalidation_exit_fraction):
        return AutomaticExitEvaluationV1(STATE_NON_ACTIONABLE, REASON_INVALID_POLICY_CONFIG, None)

    if config.max_position_age_seconds < 0 or config.max_market_context_age_seconds < 0:
        return AutomaticExitEvaluationV1(STATE_NON_ACTIONABLE, REASON_INVALID_POLICY_CONFIG, None)

    if _is_stale(position.observed_ts_utc, evaluation_ts_utc, config.max_position_age_seconds):
        return AutomaticExitEvaluationV1(STATE_NON_ACTIONABLE, REASON_POSITION_STALE, None)

    if _is_stale(market_context.observed_ts_utc, evaluation_ts_utc, config.max_market_context_age_seconds):
        return AutomaticExitEvaluationV1(STATE_NON_ACTIONABLE, REASON_EXIT_CONTEXT_STALE, None)

    if (position.venue, position.asset_id, position.market) != (market_context.venue, market_context.asset_id, market_context.market):
        return AutomaticExitEvaluationV1(STATE_NON_ACTIONABLE, REASON_CONTEXT_MISMATCH, None)

    if (
        market_context.current_price <= 0
        or not market_context.exit_profile_id.strip()
        or not market_context.exit_profile_version.strip()
        or not market_context.evidence_id.strip()
        or (market_context.active_target_price is not None and market_context.active_target_price <= 0)
        or (market_context.invalidation_price is not None and market_context.invalidation_price <= 0)
    ):
        return AutomaticExitEvaluationV1(STATE_NON_ACTIONABLE, REASON_INVALID_CONTEXT, None)

    if (
        market_context.invalidation_price is not None
        and market_context.current_price <= market_context.invalidation_price
    ):
        action, fraction, urgency, reason = (
            ACTION_EXIT,
            config.invalidation_exit_fraction,
            "HIGH",
            REASON_INVALIDATION_BREACHED,
        )
    elif (
        market_context.active_target_price is not None
        and market_context.current_price >= market_context.active_target_price
    ):
        action, fraction, urgency, reason = (
            ACTION_REDUCE,
            config.harvest_reduction_fraction,
            "NORMAL",
            REASON_TARGET_REACHED,
        )
    else:
        return AutomaticExitEvaluationV1(STATE_NO_ACTION, REASON_NO_EXIT_CONDITION, None)

    return AutomaticExitEvaluationV1(
        state=STATE_CANDIDATE,
        reason_code=reason,
        candidate=AutomaticExitCandidateV1(
            trading_account_id=position.trading_account_id,
            position_reference=position.position_reference,
            venue=position.venue,
            asset_id=position.asset_id,
            market=position.market,
            candidate_action=action,
            reduction_fraction_candidate=fraction,
            urgency_candidate=urgency,
            reason_code=reason,
            evidence_id=market_context.evidence_id,
            exit_profile_id=market_context.exit_profile_id,
            exit_profile_version=market_context.exit_profile_version,
            target_price=market_context.active_target_price,
            invalidation_price=market_context.invalidation_price,
            observed_ts_utc=_aware(evaluation_ts_utc),
        ),
    )
