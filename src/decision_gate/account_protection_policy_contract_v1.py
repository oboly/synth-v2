"""Issue #392 Phase 6 blocker C: durable account-protection configuration.

Pure, versioned resolver for the account-scoped account-protection policy
(thresholds for #318's max-drawdown / daily-realized-loss / repeated-stoploss
protections). No database access here; a separate repository loads raw rows
and this module picks the single effective, supported-version row
deterministically or fails closed. Mirrors the shape of
``src/exit_policy/automatic_exit_runtime_contract_v1.py``'s permission
resolver: effective-window versioned rows, exact account scope, no row means
unresolved (fail closed), overlapping active rows are ambiguous (fail
closed).

Config rows are permanently immutable (enforced in the DB by
``account_protection_policy_config_v1``'s UPDATE/DELETE-rejecting triggers).
Superseding or ending an open-ended row is expressed exclusively through an
immutable ``AccountProtectionPolicyConfigRevocationV1`` fact, never by
mutating the config row itself. A config row is revoked at time ``T`` if any
of its revocation facts has ``effective_ts_utc <= T`` -- multiple revocation
facts per config row are permitted by design so that an earlier scheduled
(future-dated) revocation can never block a later immediate one from also
being recorded and taking effect.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Final, Iterable

from src.decision_gate.account_protection_runtime_v1 import AccountProtectionPolicyV1


POLICY_CONFIG_CONTRACT_VERSION: Final[str] = "1"
SUPPORTED_POLICY_CONFIG_VERSIONS: Final[frozenset[str]] = frozenset({POLICY_CONFIG_CONTRACT_VERSION})

POLICY_REVOCATION_CONTRACT_VERSION: Final[str] = "1"
SUPPORTED_POLICY_REVOCATION_VERSIONS: Final[frozenset[str]] = frozenset({POLICY_REVOCATION_CONTRACT_VERSION})


class AccountProtectionPolicyConfigError(ValueError):
    """Configuration is missing, ambiguous, malformed, or unsupported.

    Callers evaluating a live permission decision must treat this as
    fail-closed (BLOCKED), not as permission to proceed without protection.
    """


@dataclass(frozen=True)
class AccountProtectionPolicyConfigRowV1:
    """One durable, immutable, account-scoped protection policy row.

    ``config_version`` is this row's own schema/contract version (fails
    closed if unsupported). ``configuration_version`` is the arbitrary
    version label threaded into #318 lock-fact identity
    (``ProtectionLockFactV1.configuration_version``); the two are
    deliberately distinct concepts. ``source_provenance`` records who/what
    provisioned this row (operational audit trail only; never used as
    threshold semantics).
    """

    account_protection_policy_config_id: int
    trading_account_id: int
    config_version: str
    configuration_version: str
    max_account_drawdown: Decimal | None
    max_daily_realized_loss: Decimal | None
    max_repeated_stoploss_streak: int | None
    max_metric_age_seconds: int
    effective_from_ts_utc: datetime
    effective_until_ts_utc: datetime | None
    source_provenance: str


@dataclass(frozen=True)
class AccountProtectionPolicyConfigRevocationV1:
    """One immutable revocation/supersession fact for one config row.

    ``trading_account_id`` is denormalized from the referenced config row so
    the resolver can detect a corrupt/conflicting cross-account reference
    without a join. ``revocation_version`` is this fact's own contract
    version (fails closed if unsupported).
    """

    account_protection_policy_config_revocation_id: int
    account_protection_policy_config_id: int
    trading_account_id: int
    revocation_version: str
    effective_ts_utc: datetime
    actor: str
    reason: str


def _is_aware(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _is_nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_window(row: AccountProtectionPolicyConfigRowV1) -> None:
    if (
        not _is_aware(row.effective_from_ts_utc)
        or (row.effective_until_ts_utc is not None and not _is_aware(row.effective_until_ts_utc))
        or (row.effective_until_ts_utc is not None and row.effective_until_ts_utc <= row.effective_from_ts_utc)
    ):
        raise AccountProtectionPolicyConfigError("INVALID_PROTECTION_CONFIGURATION_WINDOW")


def _active_at(row: AccountProtectionPolicyConfigRowV1, *, at: datetime) -> bool:
    return row.effective_from_ts_utc <= at and (row.effective_until_ts_utc is None or at < row.effective_until_ts_utc)


def _validate_revocation(
    revocation: AccountProtectionPolicyConfigRevocationV1,
    *,
    configs_by_id: dict[int, AccountProtectionPolicyConfigRowV1],
) -> None:
    """Validate one revocation already scoped to the account being resolved.

    Caller guarantees ``revocation.trading_account_id == trading_account_id``
    for every fact passed here; a dangling config reference is malformed,
    while a resolvable reference whose own config row belongs to a different
    account is a corrupt cross-account reference.
    """
    referenced = configs_by_id.get(revocation.account_protection_policy_config_id)
    if referenced is None:
        raise AccountProtectionPolicyConfigError("INVALID_PROTECTION_CONFIGURATION_REVOCATION")
    if referenced.trading_account_id != revocation.trading_account_id:
        raise AccountProtectionPolicyConfigError("PROTECTION_CONFIGURATION_REVOCATION_ACCOUNT_MISMATCH")
    if not _is_aware(revocation.effective_ts_utc) or revocation.effective_ts_utc <= referenced.effective_from_ts_utc:
        raise AccountProtectionPolicyConfigError("INVALID_PROTECTION_CONFIGURATION_REVOCATION")
    if not _is_nonempty_string(revocation.actor) or not _is_nonempty_string(revocation.reason):
        raise AccountProtectionPolicyConfigError("INVALID_PROTECTION_CONFIGURATION_REVOCATION")
    if revocation.revocation_version not in SUPPORTED_POLICY_REVOCATION_VERSIONS:
        raise AccountProtectionPolicyConfigError("UNSUPPORTED_PROTECTION_CONFIGURATION_REVOCATION_VERSION")


def _revoked_at(
    config_id: int, *, revocations: Iterable[AccountProtectionPolicyConfigRevocationV1], at: datetime,
) -> bool:
    return any(
        revocation.account_protection_policy_config_id == config_id and revocation.effective_ts_utc <= at
        for revocation in revocations
    )


def resolve_account_protection_policy_v1(
    rows: Iterable[AccountProtectionPolicyConfigRowV1],
    revocations: Iterable[AccountProtectionPolicyConfigRevocationV1] = (),
    *,
    trading_account_id: int,
    at: datetime,
) -> AccountProtectionPolicyV1:
    """Return the single effective, non-revoked, supported-version policy.

    Fail-closed (raises :class:`AccountProtectionPolicyConfigError`) when: no
    non-revoked row is effective at ``at`` (configuration unresolved), more
    than one non-revoked row is simultaneously effective (ambiguous), a
    row's window is malformed, any revocation referencing this account's
    configuration is malformed/cross-account/unsupported-version, or the
    resolved row's ``config_version``/``source_provenance`` is
    unsupported/missing. Never invents a default/no-op policy in any of
    these cases. Deterministic regardless of the input iteration order of
    either ``rows`` or ``revocations``.
    """
    if trading_account_id <= 0 or not _is_aware(at):
        raise AccountProtectionPolicyConfigError("INVALID_PROTECTION_CONFIGURATION_LOOKUP")

    all_rows = tuple(rows)
    configs_by_id = {row.account_protection_policy_config_id: row for row in all_rows}
    account_rows = tuple(row for row in all_rows if row.trading_account_id == trading_account_id)
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
            row.account_protection_policy_config_id, revocations=relevant_revocations, at=at,
        )
    )
    if not matches:
        raise AccountProtectionPolicyConfigError("PROTECTION_CONFIGURATION_UNRESOLVED")
    if len(matches) != 1:
        raise AccountProtectionPolicyConfigError("AMBIGUOUS_PROTECTION_CONFIGURATION")

    row = matches[0]
    if row.config_version not in SUPPORTED_POLICY_CONFIG_VERSIONS:
        raise AccountProtectionPolicyConfigError("UNSUPPORTED_PROTECTION_CONFIGURATION_VERSION")
    if not _is_nonempty_string(row.configuration_version):
        raise AccountProtectionPolicyConfigError("INVALID_PROTECTION_CONFIGURATION_VERSION_LABEL")
    if not _is_nonempty_string(row.source_provenance):
        raise AccountProtectionPolicyConfigError("INVALID_PROTECTION_CONFIGURATION_SOURCE_PROVENANCE")
    if row.max_metric_age_seconds < 0:
        raise AccountProtectionPolicyConfigError("INVALID_PROTECTION_METRIC_AGE_BOUND")

    return AccountProtectionPolicyV1(
        configuration_version=row.configuration_version,
        max_account_drawdown=row.max_account_drawdown,
        max_daily_realized_loss=row.max_daily_realized_loss,
        max_repeated_stoploss_streak=row.max_repeated_stoploss_streak,
        max_metric_age_seconds=row.max_metric_age_seconds,
    )
