"""Issue #752: decision_gate-owned capital-sleeve capacity computation.

Extends #279's ``strategy_bucket_account_config_contract_v1`` (which owns
absolute EUR ceilings and per-asset exposure percentages) with the
percentage-of-account-equity allocation semantics #279 never had:
``allocation_target_pct`` (advisory only) and ``allocation_max_pct`` (a hard
ceiling), resolved via

    effective_bucket_ceiling_eur = MIN(
        account_equity_eur * allocation_max_pct,
        max_bucket_amount_eur,      # if configured
    )

Pure functions only: no DB access, no broker, no market ranking, no
execution-ladder pricing. Callers supply already-resolved
``StrategyBucketAccountConfigV1`` rows (see #279) and an already-observed
account-equity fact; this module never fetches either itself.

Aggregate fail-closed policy (#752 design freeze): if the sum of every
*enabled* bucket's hard ceiling (as a fraction of account equity, ignoring
any bucket whose ceiling is bounded only by an absolute EUR cap with no
percentage component) would authorize more than 100% of account equity,
validation fails closed. This module never renormalizes percentages and
never redistributes unused sleeve capacity across strategies -- an
operator must fix the configuration.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Iterable

from src.decision_gate.strategy_bucket_account_config_contract_v1 import (
    StrategyBucketAccountConfigV1,
)

CAPACITY_CONTRACT_VERSION: Final[str] = "1"

# Fraction of account equity that all enabled buckets' allocation_max_pct
# ceilings may sum to before aggregate policy fails closed. Fixed at 1
# (100%) per the #752 design freeze: hard sleeve maxima must never be
# silently authorized above account policy, and this module never
# normalizes percentages or borrows unused capacity across strategies to
# make an over-committed configuration fit.
MAX_AGGREGATE_ALLOCATION_MAX_PCT: Final[Decimal] = Decimal("1")


class StrategyBucketCapacityError(ValueError):
    """Fail-closed capacity computation/validation error. ``args[0]`` is the reason code."""


@dataclass(frozen=True)
class StrategyBucketCapacityV1:
    """Resolved capacity facts for one exact (account, bucket) at one instant.

    ``effective_bucket_ceiling_eur`` is the hard ceiling this bucket may
    never exceed. ``remaining_capacity_eur`` subtracts already-owned
    exposure and active reservations supplied by the caller; it is never
    computed here from a ledger or reservation table directly -- callers
    own gathering those canonical facts (existing account/reservation
    evidence, e.g. ``automatic_buy_account_allocation_evidence_contract_v1``)
    and pass already-summed totals.
    """

    trading_account_id: int
    strategy_bucket_id: str
    account_equity_eur: Decimal
    allocation_target_pct: Decimal | None
    allocation_max_pct: Decimal | None
    percent_ceiling_eur: Decimal | None
    absolute_ceiling_eur: Decimal | None
    effective_bucket_ceiling_eur: Decimal | None
    owned_exposure_eur: Decimal
    active_reservations_eur: Decimal
    remaining_capacity_eur: Decimal | None
    # Issue #756 Codex block: carried through so
    # ``validate_new_entry_within_capacity_v1`` can enforce it -- this field
    # was previously persisted/validated (#279/#752 config contract) but
    # never reached the actual per-position ceiling check.
    max_position_pct_of_bucket: Decimal | None = None


def _is_finite_nonnegative(value: Decimal) -> bool:
    return isinstance(value, Decimal) and value.is_finite() and value >= 0


def compute_strategy_bucket_capacity_v1(
    config: StrategyBucketAccountConfigV1,
    *,
    account_equity_eur: Decimal,
    owned_exposure_eur: Decimal,
    active_reservations_eur: Decimal = Decimal("0"),
) -> StrategyBucketCapacityV1:
    """Resolve one bucket's effective hard ceiling and remaining capacity.

    ``allocation_target_pct`` is read for provenance only -- it is never
    compared against anything and never used to force or size a BUY; it is
    advisory context a caller may display, nothing more.

    Fails closed (:class:`StrategyBucketCapacityError`) on: negative/invalid
    equity, negative owned exposure/reservations, or a malformed config
    (should never occur for a config already returned by
    ``resolve_strategy_bucket_account_config_v1``, which validates these
    fields itself; re-checked here defensively since this module has its
    own trust boundary).
    """
    if not _is_finite_nonnegative(account_equity_eur):
        raise StrategyBucketCapacityError("INVALID_ACCOUNT_EQUITY")
    if not _is_finite_nonnegative(owned_exposure_eur):
        raise StrategyBucketCapacityError("INVALID_OWNED_EXPOSURE")
    if not _is_finite_nonnegative(active_reservations_eur):
        raise StrategyBucketCapacityError("INVALID_ACTIVE_RESERVATIONS")
    if config.allocation_max_pct is not None and not (
        isinstance(config.allocation_max_pct, Decimal)
        and config.allocation_max_pct.is_finite()
        and 0 <= config.allocation_max_pct <= 1
    ):
        raise StrategyBucketCapacityError("INVALID_ALLOCATION_MAX_PCT")
    if config.max_bucket_amount_eur is not None and not (
        isinstance(config.max_bucket_amount_eur, Decimal)
        and config.max_bucket_amount_eur.is_finite()
        and config.max_bucket_amount_eur > 0
    ):
        raise StrategyBucketCapacityError("INVALID_MAX_BUCKET_AMOUNT_EUR")
    if config.max_position_pct_of_bucket is not None and not (
        isinstance(config.max_position_pct_of_bucket, Decimal)
        and config.max_position_pct_of_bucket.is_finite()
        and 0 < config.max_position_pct_of_bucket <= 1
    ):
        raise StrategyBucketCapacityError("INVALID_MAX_POSITION_PCT_OF_BUCKET")

    percent_ceiling_eur = (
        account_equity_eur * config.allocation_max_pct if config.allocation_max_pct is not None else None
    )
    absolute_ceiling_eur = config.max_bucket_amount_eur

    if percent_ceiling_eur is None and absolute_ceiling_eur is None:
        # Neither a percentage nor an absolute bucket ceiling is configured.
        # #752 does not invent a default ceiling here; the caller (gate)
        # must fail closed for NEW exposure when no ceiling can be resolved.
        effective_bucket_ceiling_eur = None
    elif percent_ceiling_eur is None:
        effective_bucket_ceiling_eur = absolute_ceiling_eur
    elif absolute_ceiling_eur is None:
        effective_bucket_ceiling_eur = percent_ceiling_eur
    else:
        effective_bucket_ceiling_eur = min(percent_ceiling_eur, absolute_ceiling_eur)

    remaining_capacity_eur = (
        effective_bucket_ceiling_eur - owned_exposure_eur - active_reservations_eur
        if effective_bucket_ceiling_eur is not None
        else None
    )

    return StrategyBucketCapacityV1(
        trading_account_id=config.trading_account_id,
        strategy_bucket_id=config.strategy_bucket_id,
        account_equity_eur=account_equity_eur,
        allocation_target_pct=config.allocation_target_pct,
        allocation_max_pct=config.allocation_max_pct,
        percent_ceiling_eur=percent_ceiling_eur,
        absolute_ceiling_eur=absolute_ceiling_eur,
        effective_bucket_ceiling_eur=effective_bucket_ceiling_eur,
        owned_exposure_eur=owned_exposure_eur,
        active_reservations_eur=active_reservations_eur,
        remaining_capacity_eur=remaining_capacity_eur,
        max_position_pct_of_bucket=config.max_position_pct_of_bucket,
    )


def validate_new_entry_within_capacity_v1(
    capacity: StrategyBucketCapacityV1, *, proposed_position_amount_eur: Decimal,
) -> None:
    """Fail closed if a NEW entry would exceed this bucket's remaining capacity.

    Never applies to a reducing/protective exit -- callers must route
    reductions through ``strategy_owned_inventory_ledger_v1``'s
    ``validate_sell_authority_v1`` instead, which never consults this
    ceiling at all (crossing ``allocation_max_pct`` blocks NEW exposure
    only, per the #752 design freeze). If neither a percentage nor an
    absolute bucket ceiling is configured (``remaining_capacity_eur is
    None``), this mirrors #279's existing "no ceiling configured means no
    block" behavior and does not fail closed -- an operator who wants a
    ceiling enforced must configure one.

    Issue #756 Codex block: also fails closed if
    ``capacity.max_position_pct_of_bucket`` is configured, enforcing
    ``proposed_position_amount_eur <= max_position_pct_of_bucket *
    effective_bucket_ceiling_eur`` as a single-position ceiling distinct
    from (and checked in addition to) the bucket-wide remaining-capacity
    ceiling above. If a per-position percentage is configured but no bucket
    ceiling exists to take the percentage of (``effective_bucket_ceiling_eur
    is None``), this fails closed rather than silently skipping the
    configured cap -- an operator who configures a per-position percentage
    ceiling has an explicit intent that must never be silently dropped.
    """
    if not _is_finite_nonnegative(proposed_position_amount_eur) or proposed_position_amount_eur <= 0:
        raise StrategyBucketCapacityError("INVALID_PROPOSED_POSITION_AMOUNT")
    if capacity.max_position_pct_of_bucket is not None:
        if capacity.effective_bucket_ceiling_eur is None:
            raise StrategyBucketCapacityError("STRATEGY_BUCKET_CAPACITY_EXCEEDED_FOR_NEW_ENTRY")
        position_ceiling_eur = capacity.effective_bucket_ceiling_eur * capacity.max_position_pct_of_bucket
        if proposed_position_amount_eur > position_ceiling_eur:
            raise StrategyBucketCapacityError("STRATEGY_BUCKET_CAPACITY_EXCEEDED_FOR_NEW_ENTRY")
    if capacity.remaining_capacity_eur is None:
        return
    if proposed_position_amount_eur > capacity.remaining_capacity_eur:
        raise StrategyBucketCapacityError("STRATEGY_BUCKET_CAPACITY_EXCEEDED_FOR_NEW_ENTRY")


def validate_aggregate_sleeve_allocation_policy_v1(
    configs: Iterable[StrategyBucketAccountConfigV1],
) -> None:
    """Fail closed if enabled sleeves' percentage maxima sum above policy.

    Only buckets that are both ``is_enabled`` and carry a configured
    ``allocation_max_pct`` participate in the sum (an absolute-only bucket
    with no percentage component makes no percentage-of-equity commitment
    to check here; its absolute ceiling is enforced independently by #279's
    existing ``max_bucket_amount_eur``/``max_position_amount_eur`` checks).
    This function never renormalizes the percentages and never authorizes
    borrowing unused capacity across buckets -- exceeding the aggregate
    ceiling is always a configuration error the operator must fix, not a
    runtime condition this module works around.
    """
    total = Decimal("0")
    for config in configs:
        if config.is_enabled and config.allocation_max_pct is not None:
            total += config.allocation_max_pct
    if total > MAX_AGGREGATE_ALLOCATION_MAX_PCT:
        raise StrategyBucketCapacityError("AGGREGATE_SLEEVE_ALLOCATION_MAX_PCT_EXCEEDS_ACCOUNT_POLICY")
