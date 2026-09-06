"""Issue #752: canonical strategy-bucket committed-capital capacity contract."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.decision_gate.strategy_bucket_account_config_contract_v1 import (
    StrategyBucketAccountConfigError,
    StrategyBucketAccountConfigV1,
    effective_bucket_ceiling_eur_v1,
)


class StrategyBucketCapacityError(ValueError):
    """Capacity evidence is malformed or cannot resolve a hard ceiling."""


@dataclass(frozen=True)
class StrategyBucketCapacityInputV1:
    account_equity_eur: Decimal
    strategy_owned_exposure_eur: Decimal
    entry_reservations_eur: Decimal
    open_buy_order_remaining_eur: Decimal


@dataclass(frozen=True)
class StrategyBucketCapacityV1:
    hard_ceiling_eur: Decimal
    committed_capital_eur: Decimal
    remaining_capacity_eur: Decimal
    allocation_target_eur: Decimal | None
    new_exposure_allowed: bool
    reducing_exit_allowed: bool = True


def _valid_amount(value: Decimal) -> bool:
    return isinstance(value, Decimal) and value.is_finite() and value >= 0


def compute_strategy_bucket_capacity_v1(
    config: StrategyBucketAccountConfigV1,
    *,
    evidence: StrategyBucketCapacityInputV1,
) -> StrategyBucketCapacityV1:
    """Resolve exact remaining new-entry capacity for one strategy bucket.

    Target allocation is advisory only. Hard capacity consumes current owned
    exposure plus not-yet-filled entry reservations and open BUY remainder.
    Reducing exits remain allowed even when the bucket is at/over capacity.
    """
    for value in (
        evidence.account_equity_eur,
        evidence.strategy_owned_exposure_eur,
        evidence.entry_reservations_eur,
        evidence.open_buy_order_remaining_eur,
    ):
        if not _valid_amount(value):
            raise StrategyBucketCapacityError("INVALID_STRATEGY_BUCKET_CAPACITY_EVIDENCE")

    try:
        ceiling = effective_bucket_ceiling_eur_v1(
            config, account_equity_eur=evidence.account_equity_eur,
        )
    except StrategyBucketAccountConfigError as exc:
        raise StrategyBucketCapacityError(exc.args[0] if exc.args else "STRATEGY_BUCKET_CEILING_UNRESOLVED") from exc
    if ceiling is None:
        raise StrategyBucketCapacityError("STRATEGY_BUCKET_CEILING_UNRESOLVED")

    committed = (
        evidence.strategy_owned_exposure_eur
        + evidence.entry_reservations_eur
        + evidence.open_buy_order_remaining_eur
    )
    remaining = max(Decimal("0"), ceiling - committed)
    target = (
        evidence.account_equity_eur * config.allocation_target_pct
        if config.allocation_target_pct is not None
        else None
    )
    return StrategyBucketCapacityV1(
        hard_ceiling_eur=ceiling,
        committed_capital_eur=committed,
        remaining_capacity_eur=remaining,
        allocation_target_eur=target,
        new_exposure_allowed=remaining > 0 and config.is_enabled and config.allow_new_entries,
    )
