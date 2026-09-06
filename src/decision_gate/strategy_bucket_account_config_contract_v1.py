"""Issue #279: durable, versioned, account-scoped strategy-bucket
activation and risk/allocation configuration.

Pure, versioned resolver only; no database access here. A separate
repository (``strategy_bucket_account_config_repository_v1``) loads raw
rows and this module picks the single effective, supported-version row
deterministically or fails closed. Mirrors the shape of
``account_protection_policy_contract_v1``'s resolver: effective-window
versioned rows, exact (trading_account_id, strategy_bucket_id) scope, no
row means unresolved (fail closed), overlapping active rows are ambiguous
(fail closed).

``strategy_bucket_id`` is the canonical strategy-bucket identity (e.g.
``SHORT_TERM_ROTATION``). Bucket definition/validation is #232's upstream
responsibility; this module only resolves an account's own activation/risk
configuration for a bucket it already refers to by id -- it never marks a
bucket validated, paper-ready, or live-ready.

Config rows are permanently immutable (enforced in the DB by
``strategy_bucket_account_config_v1``'s UPDATE/DELETE-rejecting triggers).
Superseding or ending an open-ended row is expressed exclusively through an
immutable ``StrategyBucketAccountConfigRevocationV1`` fact, never by
mutating the config row itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Final, Iterable


CONFIG_CONTRACT_VERSION: Final[str] = "1"
SUPPORTED_CONFIG_VERSIONS: Final[frozenset[str]] = frozenset({CONFIG_CONTRACT_VERSION})

REVOCATION_CONTRACT_VERSION: Final[str] = "1"
SUPPORTED_REVOCATION_VERSIONS: Final[frozenset[str]] = frozenset({REVOCATION_CONTRACT_VERSION})


class StrategyBucketAccountConfigError(ValueError):
    """Configuration is missing, ambiguous, malformed, or unsupported.

    Callers evaluating strategy-bucket participation must treat this as
    fail-closed (BLOCKED), not as permission to proceed with a default.
    """


@dataclass(frozen=True)
class StrategyBucketAccountConfigRowV1:
    """One durable, immutable, account-scoped strategy-bucket config row."""

    strategy_bucket_account_config_id: int
    trading_account_id: int
    strategy_bucket_id: str
    config_version: str
    is_enabled: bool
    risk_profile: str
    max_position_amount_eur: Decimal | None
    max_bucket_amount_eur: Decimal | None
    max_asset_exposure_pct: Decimal | None
    max_open_positions: int | None
    allow_new_entries: bool
    allow_reduce_reviews: bool
    effective_from_ts_utc: datetime
    effective_until_ts_utc: datetime | None
    source_provenance: str
    allocation_target_pct: Decimal | None = None
    allocation_max_pct: Decimal | None = None


@dataclass(frozen=True)
class StrategyBucketAccountConfigRevocationV1:
    """One immutable revocation/supersession fact for one config row.

    ``trading_account_id`` is denormalized from the referenced config row so
    the resolver can detect a corrupt/conflicting cross-account reference
    without a join.
    """

    strategy_bucket_account_config_revocation_id: int
    strategy_bucket_account_config_id: int
    trading_account_id: int
    revocation_version: str
    effective_ts_utc: datetime
    actor: str
    reason: str


@dataclass(frozen=True)
class StrategyBucketAccountConfigV1:
    """Resolved, effective strategy-bucket account configuration."""

    trading_account_id: int
    strategy_bucket_id: str
    is_enabled: bool
    risk_profile: str
    max_position_amount_eur: Decimal | None
    max_bucket_amount_eur: Decimal | None
    max_asset_exposure_pct: Decimal | None
    max_open_positions: int | None
    allow_new_entries: bool
    allow_reduce_reviews: bool
    allocation_target_pct: Decimal | None = None
    allocation_max_pct: Decimal | None = None


def _is_aware(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _is_nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_positive_decimal(value: Decimal | None) -> bool:
    return value is None or (isinstance(value, Decimal) and value.is_finite() and value > 0)


def _is_fraction(value: Decimal | None, *, allow_zero: bool) -> bool:
    if value is None:
        return True
    if not isinstance(value, Decimal) or not value.is_finite():
        return False
    lower_ok = value >= 0 if allow_zero else value > 0
    return lower_ok and value <= 1


def effective_bucket_ceiling_eur_v1(
    config: "StrategyBucketAccountConfigV1", *, account_equity_eur: Decimal,
) -> Decimal | None:
    """Return the hard bucket capital ceiling, if configured.

    Percentage ceilings are fractions of current account equity (0..1). When
    both percentage and absolute EUR ceilings exist, the stricter bound wins.
    Advisory target percentages never participate in authorization.
    """
    if not isinstance(account_equity_eur, Decimal) or not account_equity_eur.is_finite() or account_equity_eur < 0:
        raise StrategyBucketAccountConfigError("INVALID_ACCOUNT_EQUITY_FOR_STRATEGY_BUCKET_CEILING")
    ceilings: list[Decimal] = []
    if config.allocation_max_pct is not None:
        ceilings.append(account_equity_eur * config.allocation_max_pct)
    if config.max_bucket_amount_eur is not None:
        ceilings.append(config.max_bucket_amount_eur)
    return min(ceilings) if ceilings else None


def _validate_window(row: StrategyBucketAccountConfigRowV1) -> None:
    if (
        not _is_aware(row.effective_from_ts_utc)
        or (row.effective_until_ts_utc is not None and not _is_aware(row.effective_until_ts_utc))
        or (row.effective_until_ts_utc is not None and row.effective_until_ts_utc <= row.effective_from_ts_utc)
    ):
        raise StrategyBucketAccountConfigError("INVALID_STRATEGY_BUCKET_CONFIGURATION_WINDOW")


def _active_at(row: StrategyBucketAccountConfigRowV1, *, at: datetime) -> bool:
    return row.effective_from_ts_utc <= at and (row.effective_until_ts_utc is None or at < row.effective_until_ts_utc)


def _validate_revocation(
    revocation: StrategyBucketAccountConfigRevocationV1,
    *,
    configs_by_id: dict[int, StrategyBucketAccountConfigRowV1],
) -> None:
    """Validate one revocation already scoped to the account being resolved.

    Caller guarantees ``revocation.trading_account_id == trading_account_id``
    for every fact passed here; a dangling config reference is malformed,
    while a resolvable reference whose own config row belongs to a different
    account is a corrupt cross-account reference.
    """
    referenced = configs_by_id.get(revocation.strategy_bucket_account_config_id)
    if referenced is None:
        raise StrategyBucketAccountConfigError("INVALID_STRATEGY_BUCKET_CONFIGURATION_REVOCATION")
    if referenced.trading_account_id != revocation.trading_account_id:
        raise StrategyBucketAccountConfigError("STRATEGY_BUCKET_CONFIGURATION_REVOCATION_ACCOUNT_MISMATCH")
    if not _is_aware(revocation.effective_ts_utc) or revocation.effective_ts_utc <= referenced.effective_from_ts_utc:
        raise StrategyBucketAccountConfigError("INVALID_STRATEGY_BUCKET_CONFIGURATION_REVOCATION")
    if not _is_nonempty_string(revocation.actor) or not _is_nonempty_string(revocation.reason):
        raise StrategyBucketAccountConfigError("INVALID_STRATEGY_BUCKET_CONFIGURATION_REVOCATION")
    if revocation.revocation_version not in SUPPORTED_REVOCATION_VERSIONS:
        raise StrategyBucketAccountConfigError("UNSUPPORTED_STRATEGY_BUCKET_CONFIGURATION_REVOCATION_VERSION")


def _revoked_at(
    config_id: int, *, revocations: Iterable[StrategyBucketAccountConfigRevocationV1], at: datetime,
) -> bool:
    return any(
        revocation.strategy_bucket_account_config_id == config_id and revocation.effective_ts_utc <= at
        for revocation in revocations
    )


def resolve_strategy_bucket_account_config_v1(
    rows: Iterable[StrategyBucketAccountConfigRowV1],
    revocations: Iterable[StrategyBucketAccountConfigRevocationV1] = (),
    *,
    trading_account_id: int,
    strategy_bucket_id: str,
    at: datetime,
) -> StrategyBucketAccountConfigV1:
    """Return the single effective, non-revoked, supported-version config.

    Fail-closed (raises :class:`StrategyBucketAccountConfigError`) when: no
    non-revoked row is effective at ``at`` for this exact
    (``trading_account_id``, ``strategy_bucket_id``) pair (configuration
    unresolved), more than one non-revoked row is simultaneously effective
    (ambiguous), a row's window is malformed, any revocation referencing
    this account's configuration is malformed/cross-account/unsupported
    version, or the resolved row's ``config_version``/``risk_profile``/
    ``source_provenance`` is unsupported/missing. Never invents a
    default/enabled configuration in any of these cases. Deterministic
    regardless of the input iteration order of either ``rows`` or
    ``revocations``.
    """
    if (
        trading_account_id <= 0
        or not _is_nonempty_string(strategy_bucket_id)
        or not _is_aware(at)
    ):
        raise StrategyBucketAccountConfigError("INVALID_STRATEGY_BUCKET_CONFIGURATION_LOOKUP")

    all_rows = tuple(rows)
    configs_by_id = {row.strategy_bucket_account_config_id: row for row in all_rows}
    account_rows = tuple(
        row
        for row in all_rows
        if row.trading_account_id == trading_account_id and row.strategy_bucket_id == strategy_bucket_id
    )
    for row in account_rows:
        _validate_window(row)

    relevant_revocations = tuple(
        revocation for revocation in revocations if revocation.trading_account_id == trading_account_id
    )
    for revocation in relevant_revocations:
        _validate_revocation(revocation, configs_by_id=configs_by_id)

    matches = tuple(
        row
        for row in account_rows
        if _active_at(row, at=at) and not _revoked_at(
            row.strategy_bucket_account_config_id, revocations=relevant_revocations, at=at,
        )
    )
    if not matches:
        raise StrategyBucketAccountConfigError("STRATEGY_BUCKET_CONFIGURATION_UNRESOLVED")
    if len(matches) != 1:
        raise StrategyBucketAccountConfigError("AMBIGUOUS_STRATEGY_BUCKET_CONFIGURATION")

    row = matches[0]
    if row.config_version not in SUPPORTED_CONFIG_VERSIONS:
        raise StrategyBucketAccountConfigError("UNSUPPORTED_STRATEGY_BUCKET_CONFIGURATION_VERSION")
    if not _is_nonempty_string(row.risk_profile):
        raise StrategyBucketAccountConfigError("INVALID_STRATEGY_BUCKET_RISK_PROFILE")
    if not _is_nonempty_string(row.source_provenance):
        raise StrategyBucketAccountConfigError("INVALID_STRATEGY_BUCKET_CONFIGURATION_SOURCE_PROVENANCE")
    if not _is_positive_decimal(row.max_position_amount_eur):
        raise StrategyBucketAccountConfigError("INVALID_STRATEGY_BUCKET_MAX_POSITION_AMOUNT")
    if not _is_positive_decimal(row.max_bucket_amount_eur):
        raise StrategyBucketAccountConfigError("INVALID_STRATEGY_BUCKET_MAX_BUCKET_AMOUNT")
    if row.max_asset_exposure_pct is not None and (
        not isinstance(row.max_asset_exposure_pct, Decimal)
        or not row.max_asset_exposure_pct.is_finite()
        or row.max_asset_exposure_pct <= 0
        or row.max_asset_exposure_pct > 100
    ):
        raise StrategyBucketAccountConfigError("INVALID_STRATEGY_BUCKET_MAX_ASSET_EXPOSURE_PCT")
    if row.max_open_positions is not None and (
        isinstance(row.max_open_positions, bool) or not isinstance(row.max_open_positions, int) or row.max_open_positions <= 0
    ):
        raise StrategyBucketAccountConfigError("INVALID_STRATEGY_BUCKET_MAX_OPEN_POSITIONS")
    if not _is_fraction(row.allocation_target_pct, allow_zero=True):
        raise StrategyBucketAccountConfigError("INVALID_STRATEGY_BUCKET_ALLOCATION_TARGET_PCT")
    if not _is_fraction(row.allocation_max_pct, allow_zero=False):
        raise StrategyBucketAccountConfigError("INVALID_STRATEGY_BUCKET_ALLOCATION_MAX_PCT")
    if (
        row.allocation_target_pct is not None
        and row.allocation_max_pct is not None
        and row.allocation_target_pct > row.allocation_max_pct
    ):
        raise StrategyBucketAccountConfigError("STRATEGY_BUCKET_ALLOCATION_TARGET_EXCEEDS_MAX")

    # Validate the complete active account configuration set, not just the
    # requested bucket. Hard sleeve maxima above 100% are ambiguous account
    # authority and therefore fail closed rather than being normalized.
    active_account_rows = tuple(
        candidate
        for candidate in all_rows
        if candidate.trading_account_id == trading_account_id
        and candidate.is_enabled
        and _active_at(candidate, at=at)
        and not _revoked_at(
            candidate.strategy_bucket_account_config_id,
            revocations=relevant_revocations,
            at=at,
        )
    )
    for candidate in active_account_rows:
        if not _is_fraction(candidate.allocation_target_pct, allow_zero=True):
            raise StrategyBucketAccountConfigError("INVALID_STRATEGY_BUCKET_ALLOCATION_TARGET_PCT")
        if not _is_fraction(candidate.allocation_max_pct, allow_zero=False):
            raise StrategyBucketAccountConfigError("INVALID_STRATEGY_BUCKET_ALLOCATION_MAX_PCT")
        if (
            candidate.allocation_target_pct is not None
            and candidate.allocation_max_pct is not None
            and candidate.allocation_target_pct > candidate.allocation_max_pct
        ):
            raise StrategyBucketAccountConfigError("STRATEGY_BUCKET_ALLOCATION_TARGET_EXCEEDS_MAX")
    configured_max_total = sum(
        (candidate.allocation_max_pct for candidate in active_account_rows if candidate.allocation_max_pct is not None),
        Decimal("0"),
    )
    if configured_max_total > Decimal("1"):
        raise StrategyBucketAccountConfigError("STRATEGY_BUCKET_ALLOCATION_OVERCOMMITTED")

    return StrategyBucketAccountConfigV1(
        trading_account_id=row.trading_account_id,
        strategy_bucket_id=row.strategy_bucket_id,
        is_enabled=row.is_enabled,
        risk_profile=row.risk_profile,
        max_position_amount_eur=row.max_position_amount_eur,
        max_bucket_amount_eur=row.max_bucket_amount_eur,
        max_asset_exposure_pct=row.max_asset_exposure_pct,
        max_open_positions=row.max_open_positions,
        allow_new_entries=row.allow_new_entries,
        allow_reduce_reviews=row.allow_reduce_reviews,
        allocation_target_pct=row.allocation_target_pct,
        allocation_max_pct=row.allocation_max_pct,
    )
