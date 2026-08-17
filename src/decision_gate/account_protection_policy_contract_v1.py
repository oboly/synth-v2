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
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Final, Iterable

from src.decision_gate.account_protection_runtime_v1 import AccountProtectionPolicyV1


POLICY_CONFIG_CONTRACT_VERSION: Final[str] = "1"
SUPPORTED_POLICY_CONFIG_VERSIONS: Final[frozenset[str]] = frozenset({POLICY_CONFIG_CONTRACT_VERSION})


class AccountProtectionPolicyConfigError(ValueError):
    """Configuration is missing, ambiguous, malformed, or unsupported.

    Callers evaluating a live permission decision must treat this as
    fail-closed (BLOCKED), not as permission to proceed without protection.
    """


@dataclass(frozen=True)
class AccountProtectionPolicyConfigRowV1:
    """One durable, account-scoped, effective-window protection policy row.

    ``config_version`` is this row's own schema/contract version (fails
    closed if unsupported). ``configuration_version`` is the arbitrary
    version label threaded into #318 lock-fact identity
    (``ProtectionLockFactV1.configuration_version``); the two are
    deliberately distinct concepts.
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


def resolve_account_protection_policy_v1(
    rows: Iterable[AccountProtectionPolicyConfigRowV1],
    *,
    trading_account_id: int,
    at: datetime,
) -> AccountProtectionPolicyV1:
    """Return the single effective, supported-version policy for this account.

    Fail-closed (raises :class:`AccountProtectionPolicyConfigError`) when: no
    row is effective at ``at`` (configuration unresolved), more than one row
    is simultaneously effective (ambiguous), a row's window is malformed, or
    the resolved row's ``config_version`` is unsupported. Never invents a
    default/no-op policy in any of these cases.
    """
    if trading_account_id <= 0 or not _is_aware(at):
        raise AccountProtectionPolicyConfigError("INVALID_PROTECTION_CONFIGURATION_LOOKUP")

    account_rows = tuple(row for row in rows if row.trading_account_id == trading_account_id)
    for row in account_rows:
        _validate_window(row)

    matches = tuple(row for row in account_rows if _active_at(row, at=at))
    if not matches:
        raise AccountProtectionPolicyConfigError("PROTECTION_CONFIGURATION_UNRESOLVED")
    if len(matches) != 1:
        raise AccountProtectionPolicyConfigError("AMBIGUOUS_PROTECTION_CONFIGURATION")

    row = matches[0]
    if row.config_version not in SUPPORTED_POLICY_CONFIG_VERSIONS:
        raise AccountProtectionPolicyConfigError("UNSUPPORTED_PROTECTION_CONFIGURATION_VERSION")
    if not _is_nonempty_string(row.configuration_version):
        raise AccountProtectionPolicyConfigError("INVALID_PROTECTION_CONFIGURATION_VERSION_LABEL")
    if row.max_metric_age_seconds < 0:
        raise AccountProtectionPolicyConfigError("INVALID_PROTECTION_METRIC_AGE_BOUND")

    return AccountProtectionPolicyV1(
        configuration_version=row.configuration_version,
        max_account_drawdown=row.max_account_drawdown,
        max_daily_realized_loss=row.max_daily_realized_loss,
        max_repeated_stoploss_streak=row.max_repeated_stoploss_streak,
        max_metric_age_seconds=row.max_metric_age_seconds,
    )
