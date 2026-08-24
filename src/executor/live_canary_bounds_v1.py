"""Typed, versioned first-LIVE canary safety bounds for the shared executor.

This module defines the smallest explicit, fail-closed canary contract
required before the shared executor may ever construct a LIVE broker-write
path: exactly one account, exactly one market, BUY only, a hard cap on
orders per runtime cycle, and a tiny notional ceiling.

This module grants no authority and activates nothing. It is a pure,
side-neutral safety-bound contract plus deny-by-default validators. Actual
LIVE authority remains owned by ``execution_live_authority_v1`` and
``execution_kill_switch_v1``; actual sizing authority remains owned by
``decision_gate``/``strategy_bucket_account_config_contract_v1``. This
module never grants sizing permission -- it only enforces an additional,
independent, tighter executor-level circuit breaker on top of whatever
sizing authority already approved a plan.

Safety:
  broker_private_calls=0
  broker_writes=0
  order_submission=0
  live_orders=0
  decision_gate=none
  execution_planner=none
  executor=circuit_breaker_only
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Final, Iterable


CANARY_BOUNDS_CONTRACT_VERSION: Final[str] = "v1"

# Fixed for the v1 first-LIVE canary contract. Not env-configurable: a
# canary run is BUY-only by design, and the kill switch / withdrawal
# prohibition are non-negotiable structural invariants, not operator knobs.
CANARY_ALLOWED_SIDE: Final[str] = "BUY"
CANARY_KILL_SWITCH_REQUIRED: Final[bool] = True
CANARY_WITHDRAWAL_PERMISSION: Final[bool] = False

# Hard engineering sanity ceiling for the first-LIVE canary. This is a
# structural upper bound on the executor-level circuit breaker, independent
# of and in addition to whatever decision_gate/strategy_bucket_account_config
# sizing ceiling applies. It never widens; only an explicit new reviewed
# contract version may raise it.
CANARY_MAX_NOTIONAL_EUR_CEILING: Final[Decimal] = Decimal("25")
CANARY_MAX_ORDERS_PER_CYCLE_CEILING: Final[int] = 1

ENV_TRADING_ACCOUNT_ID: Final[str] = "SYNTH_SHARED_EXECUTOR_LIVE_CANARY_TRADING_ACCOUNT_ID"
ENV_VENUE: Final[str] = "SYNTH_SHARED_EXECUTOR_LIVE_CANARY_VENUE"
ENV_MARKET: Final[str] = "SYNTH_SHARED_EXECUTOR_LIVE_CANARY_MARKET"
ENV_MAX_NOTIONAL_EUR: Final[str] = "SYNTH_SHARED_EXECUTOR_LIVE_CANARY_MAX_NOTIONAL_EUR"
ENV_MAX_ORDERS_PER_CYCLE: Final[str] = "SYNTH_SHARED_EXECUTOR_LIVE_CANARY_MAX_ORDERS_PER_CYCLE"


class LiveCanaryBoundsError(ValueError):
    """The canary contract is missing, malformed, or structurally unsafe."""


class LiveCanaryScopeDeniedError(PermissionError):
    """An exact handoff or plan falls outside the frozen canary scope."""


@dataclass(frozen=True)
class LiveCanaryBoundsV1:
    """Frozen first-LIVE canary contract. Exactly one account/market/side."""

    version: str
    allowed_trading_account_id: int
    allowed_venue: str
    allowed_market: str
    allowed_side: str
    max_orders_per_cycle: int
    max_notional_eur: Decimal
    kill_switch_required: bool
    withdrawal_permission: bool

    def __post_init__(self) -> None:
        if self.version != CANARY_BOUNDS_CONTRACT_VERSION:
            raise LiveCanaryBoundsError("UNSUPPORTED_CANARY_BOUNDS_VERSION")
        if (
            not isinstance(self.allowed_trading_account_id, int)
            or isinstance(self.allowed_trading_account_id, bool)
            or self.allowed_trading_account_id <= 0
        ):
            raise LiveCanaryBoundsError("CANARY_ACCOUNT_MUST_BE_POSITIVE_INT")
        if not isinstance(self.allowed_venue, str) or not self.allowed_venue.strip():
            raise LiveCanaryBoundsError("CANARY_VENUE_REQUIRED")
        if not isinstance(self.allowed_market, str) or not self.allowed_market.strip():
            raise LiveCanaryBoundsError("CANARY_MARKET_REQUIRED")
        if self.allowed_side != CANARY_ALLOWED_SIDE:
            raise LiveCanaryBoundsError("CANARY_SIDE_MUST_BE_BUY")
        if (
            not isinstance(self.max_orders_per_cycle, int)
            or isinstance(self.max_orders_per_cycle, bool)
            or self.max_orders_per_cycle <= 0
            or self.max_orders_per_cycle > CANARY_MAX_ORDERS_PER_CYCLE_CEILING
        ):
            raise LiveCanaryBoundsError("CANARY_MAX_ORDERS_PER_CYCLE_OUT_OF_BOUNDS")
        if (
            not isinstance(self.max_notional_eur, Decimal)
            or not self.max_notional_eur.is_finite()
            or self.max_notional_eur <= 0
            or self.max_notional_eur > CANARY_MAX_NOTIONAL_EUR_CEILING
        ):
            raise LiveCanaryBoundsError("CANARY_MAX_NOTIONAL_EUR_OUT_OF_BOUNDS")
        if self.kill_switch_required is not CANARY_KILL_SWITCH_REQUIRED:
            raise LiveCanaryBoundsError("CANARY_KILL_SWITCH_MUST_BE_REQUIRED")
        if self.withdrawal_permission is not CANARY_WITHDRAWAL_PERMISSION:
            raise LiveCanaryBoundsError("CANARY_WITHDRAWAL_PERMISSION_MUST_BE_FALSE")


def _env_required_text(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise LiveCanaryBoundsError(f"CANARY_ENV_MISSING:{name}")
    return value.strip()


def _env_required_positive_int(name: str) -> int:
    raw = _env_required_text(name)
    try:
        value = int(raw)
    except ValueError as exc:
        raise LiveCanaryBoundsError(f"CANARY_ENV_INVALID_INT:{name}") from exc
    if value <= 0:
        raise LiveCanaryBoundsError(f"CANARY_ENV_INVALID_INT:{name}")
    return value


def _env_required_decimal(name: str) -> Decimal:
    raw = _env_required_text(name)
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise LiveCanaryBoundsError(f"CANARY_ENV_INVALID_DECIMAL:{name}") from exc
    if not value.is_finite() or value <= 0:
        raise LiveCanaryBoundsError(f"CANARY_ENV_INVALID_DECIMAL:{name}")
    return value


def load_live_canary_bounds_from_env_v1() -> LiveCanaryBoundsV1:
    """Resolve the canary contract from explicit environment configuration.

    Fails closed on any missing/invalid value. No field defaults to a
    production account, market, or notional amount -- every scoped value
    must be explicitly supplied by the caller's environment.
    """
    return LiveCanaryBoundsV1(
        version=CANARY_BOUNDS_CONTRACT_VERSION,
        allowed_trading_account_id=_env_required_positive_int(ENV_TRADING_ACCOUNT_ID),
        allowed_venue=_env_required_text(ENV_VENUE),
        allowed_market=_env_required_text(ENV_MARKET),
        allowed_side=CANARY_ALLOWED_SIDE,
        max_orders_per_cycle=int(
            os.getenv(ENV_MAX_ORDERS_PER_CYCLE, str(CANARY_MAX_ORDERS_PER_CYCLE_CEILING))
        ),
        max_notional_eur=_env_required_decimal(ENV_MAX_NOTIONAL_EUR),
        kill_switch_required=CANARY_KILL_SWITCH_REQUIRED,
        withdrawal_permission=CANARY_WITHDRAWAL_PERMISSION,
    )


def assert_handoff_within_canary_scope_v1(bounds: LiveCanaryBoundsV1, handoff: Any) -> None:
    """Reject any handoff outside the frozen one-account/one-market/BUY scope."""
    if (
        handoff.trading_account_id != bounds.allowed_trading_account_id
        or handoff.venue != bounds.allowed_venue
        or handoff.market != bounds.allowed_market
        or handoff.side != bounds.allowed_side
    ):
        raise LiveCanaryScopeDeniedError("CANARY_SCOPE_MISMATCH")


def notional_eur_for_legs_v1(legs: Iterable[Any]) -> Decimal:
    total = Decimal("0")
    for leg in legs:
        total += Decimal(leg.price) * Decimal(leg.quantity)
    return total


def assert_plan_notional_within_canary_bound_v1(
    bounds: LiveCanaryBoundsV1, legs: Iterable[Any]
) -> None:
    total = notional_eur_for_legs_v1(legs)
    if total <= 0 or total > bounds.max_notional_eur:
        raise LiveCanaryScopeDeniedError("CANARY_MAX_NOTIONAL_EUR_EXCEEDED")


def clamp_batch_limit_to_canary_v1(bounds: LiveCanaryBoundsV1, requested_limit: int) -> int:
    """Deterministically truncate a requested batch size to the canary bound."""
    if not isinstance(requested_limit, int) or isinstance(requested_limit, bool) or requested_limit <= 0:
        raise LiveCanaryBoundsError("REQUESTED_LIMIT_MUST_BE_POSITIVE_INT")
    return min(requested_limit, bounds.max_orders_per_cycle)
