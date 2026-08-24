"""Canonical provisioning path for ``account_protection_policy_config_v1``.

This decision-gate-owned writer is the sole repository path for appending an
account-protection policy configuration.  It resolves an operator-supplied
``(account_code, venue)`` identity to the internal account id; callers never
supply that numeric id.  Existing policy resolution remains entirely owned by
``account_protection_policy_contract_v1`` and is used here unchanged to prove
candidate validity and idempotency.

Rows are immutable.  This module never updates or deletes a configuration or
revocation fact.  A same-value rerun returns the existing row; a conflicting
or overlapping rerun fails closed.  It has no broker, executor, planner, or
order dependency.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final

from src.decision_gate.account_protection_policy_contract_v1 import (
    POLICY_CONFIG_CONTRACT_VERSION,
    AccountProtectionPolicyConfigError,
    AccountProtectionPolicyConfigRevocationV1,
    AccountProtectionPolicyConfigRowV1,
    resolve_account_protection_policy_v1,
)
from src.decision_gate.account_protection_policy_repository_v1 import (
    AccountProtectionPolicyRepositoryError,
    load_account_protection_policy_config_revocations_v1,
    load_account_protection_policy_config_rows_v1,
)

_CONFIG_VERSION_MAX_LENGTH: Final[int] = 16
_CONFIGURATION_VERSION_MAX_LENGTH: Final[int] = 128
_SOURCE_PROVENANCE_MAX_LENGTH: Final[int] = 128
_PRE_VALIDATION_CONFIG_ID: Final[int] = 1


class AccountProtectionPolicyProvisioningError(RuntimeError):
    """Fail-closed provisioning error. ``args[0]`` is the reason code."""


class AccountProtectionPolicyConflictError(AccountProtectionPolicyProvisioningError):
    """A policy row conflicts with the requested immutable configuration."""


@dataclass(frozen=True)
class AccountProtectionPolicyProvisioningRequestV1:
    account_code: str
    venue: str
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
class AccountProtectionPolicyProvisioningResultV1:
    trading_account_id: int
    account_protection_policy_config_id: int
    idempotent: bool


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _aware(value: object) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _valid_positive_decimal(value: object) -> bool:
    return isinstance(value, Decimal) and value.is_finite() and value > 0


def _validate_request(request: AccountProtectionPolicyProvisioningRequestV1) -> None:
    if not _nonempty(request.account_code) or not _nonempty(request.venue):
        raise AccountProtectionPolicyProvisioningError("INVALID_ACCOUNT_IDENTITY")
    if not _nonempty(request.config_version) or len(request.config_version) > _CONFIG_VERSION_MAX_LENGTH:
        raise AccountProtectionPolicyProvisioningError("INVALID_PROTECTION_CONFIG_VERSION")
    if (
        not _nonempty(request.configuration_version)
        or len(request.configuration_version) > _CONFIGURATION_VERSION_MAX_LENGTH
    ):
        raise AccountProtectionPolicyProvisioningError("INVALID_PROTECTION_CONFIGURATION_VERSION_LABEL")
    if not _nonempty(request.source_provenance) or len(request.source_provenance) > _SOURCE_PROVENANCE_MAX_LENGTH:
        raise AccountProtectionPolicyProvisioningError("INVALID_SOURCE_PROVENANCE")
    if not _aware(request.effective_from_ts_utc):
        raise AccountProtectionPolicyProvisioningError("INVALID_EFFECTIVE_FROM_TIMESTAMP")
    if request.effective_until_ts_utc is not None and not _aware(request.effective_until_ts_utc):
        raise AccountProtectionPolicyProvisioningError("INVALID_EFFECTIVE_UNTIL_TIMESTAMP")
    if (
        request.effective_until_ts_utc is not None
        and request.effective_until_ts_utc <= request.effective_from_ts_utc
    ):
        raise AccountProtectionPolicyProvisioningError("INVALID_PROTECTION_CONFIGURATION_WINDOW")
    if request.max_account_drawdown is not None and not _valid_positive_decimal(request.max_account_drawdown):
        raise AccountProtectionPolicyProvisioningError("INVALID_MAX_ACCOUNT_DRAWDOWN")
    if request.max_daily_realized_loss is not None and not _valid_positive_decimal(request.max_daily_realized_loss):
        raise AccountProtectionPolicyProvisioningError("INVALID_MAX_DAILY_REALIZED_LOSS")
    if request.max_repeated_stoploss_streak is not None and (
        not isinstance(request.max_repeated_stoploss_streak, int)
        or isinstance(request.max_repeated_stoploss_streak, bool)
        or request.max_repeated_stoploss_streak <= 0
    ):
        raise AccountProtectionPolicyProvisioningError("INVALID_MAX_REPEATED_STOPLOSS_STREAK")
    if (
        not isinstance(request.max_metric_age_seconds, int)
        or isinstance(request.max_metric_age_seconds, bool)
        or request.max_metric_age_seconds < 0
    ):
        raise AccountProtectionPolicyProvisioningError("INVALID_MAX_METRIC_AGE_SECONDS")


def _resolve_trading_account_id(conn: Any, *, account_code: str, venue: str) -> int:
    """Resolve exactly one canonical account identity; never use ``LIMIT 1``."""
    sql = "SELECT trading_account_id FROM trading_account WHERE account_code = %s AND venue = %s"
    with conn.cursor() as cur:
        cur.execute(sql, (account_code, venue))
        rows = cur.fetchall()
    if len(rows) == 0:
        raise AccountProtectionPolicyProvisioningError("UNKNOWN_TRADING_ACCOUNT")
    if len(rows) != 1:
        raise AccountProtectionPolicyProvisioningError("AMBIGUOUS_TRADING_ACCOUNT_IDENTITY")
    return int(rows[0]["trading_account_id"])


def _candidate_row(
    *, trading_account_id: int, request: AccountProtectionPolicyProvisioningRequestV1,
) -> AccountProtectionPolicyConfigRowV1:
    return AccountProtectionPolicyConfigRowV1(
        account_protection_policy_config_id=_PRE_VALIDATION_CONFIG_ID,
        trading_account_id=trading_account_id,
        config_version=request.config_version,
        configuration_version=request.configuration_version,
        max_account_drawdown=request.max_account_drawdown,
        max_daily_realized_loss=request.max_daily_realized_loss,
        max_repeated_stoploss_streak=request.max_repeated_stoploss_streak,
        max_metric_age_seconds=request.max_metric_age_seconds,
        effective_from_ts_utc=request.effective_from_ts_utc,
        effective_until_ts_utc=request.effective_until_ts_utc,
        source_provenance=request.source_provenance,
    )


def _active_at(row: AccountProtectionPolicyConfigRowV1, *, at: datetime) -> bool:
    return row.effective_from_ts_utc <= at and (
        row.effective_until_ts_utc is None or at < row.effective_until_ts_utc
    )


def _revoked_at(
    config_id: int, *, revocations: tuple[AccountProtectionPolicyConfigRevocationV1, ...], at: datetime,
) -> bool:
    return any(
        row.account_protection_policy_config_id == config_id and row.effective_ts_utc <= at
        for row in revocations
    )


def _find_effective_raw_row(
    rows: tuple[AccountProtectionPolicyConfigRowV1, ...],
    revocations: tuple[AccountProtectionPolicyConfigRevocationV1, ...],
    *,
    trading_account_id: int,
    at: datetime,
) -> AccountProtectionPolicyConfigRowV1:
    matches = [
        row for row in rows
        if row.trading_account_id == trading_account_id
        and _active_at(row, at=at)
        and not _revoked_at(row.account_protection_policy_config_id, revocations=revocations, at=at)
    ]
    if len(matches) != 1:
        raise AccountProtectionPolicyProvisioningError("PROTECTION_CONFIGURATION_STATE_INVALID")
    return matches[0]


def _same_values(
    existing: AccountProtectionPolicyConfigRowV1, request: AccountProtectionPolicyProvisioningRequestV1,
) -> bool:
    return (
        existing.config_version == request.config_version
        and existing.configuration_version == request.configuration_version
        and existing.max_account_drawdown == request.max_account_drawdown
        and existing.max_daily_realized_loss == request.max_daily_realized_loss
        and existing.max_repeated_stoploss_streak == request.max_repeated_stoploss_streak
        and existing.max_metric_age_seconds == request.max_metric_age_seconds
        and existing.effective_from_ts_utc == request.effective_from_ts_utc
        and existing.effective_until_ts_utc == request.effective_until_ts_utc
        and existing.source_provenance == request.source_provenance
    )


def _effective_end(
    row: AccountProtectionPolicyConfigRowV1,
    *,
    revocations: tuple[AccountProtectionPolicyConfigRevocationV1, ...],
) -> datetime | None:
    ends = [row.effective_until_ts_utc] if row.effective_until_ts_utc is not None else []
    ends.extend(
        revocation.effective_ts_utc
        for revocation in revocations
        if revocation.account_protection_policy_config_id == row.account_protection_policy_config_id
    )
    return min(ends) if ends else None


def _would_overlap_existing_row(
    rows: tuple[AccountProtectionPolicyConfigRowV1, ...],
    revocations: tuple[AccountProtectionPolicyConfigRevocationV1, ...],
    *,
    trading_account_id: int,
    candidate_start: datetime,
    candidate_end: datetime | None,
) -> bool:
    """Check all future/past windows so a write cannot create later ambiguity."""
    for row in rows:
        if row.trading_account_id != trading_account_id:
            continue
        row_end = _effective_end(row, revocations=revocations)
        start = max(candidate_start, row.effective_from_ts_utc)
        end_candidates = [end for end in (candidate_end, row_end) if end is not None]
        if not end_candidates or start < min(end_candidates):
            return True
    return False


def provision_account_protection_policy_v1(
    conn: Any, *, request: AccountProtectionPolicyProvisioningRequestV1,
) -> AccountProtectionPolicyProvisioningResultV1:
    """Append one typed policy row, or return its exact idempotent predecessor.

    The caller owns transaction commit/rollback.  No missing-row default is
    created by any reader: only this explicit request may create a row.
    """
    _validate_request(request)
    request = replace(
        request,
        effective_from_ts_utc=request.effective_from_ts_utc.astimezone(UTC),
        effective_until_ts_utc=(
            request.effective_until_ts_utc.astimezone(UTC)
            if request.effective_until_ts_utc is not None else None
        ),
    )
    trading_account_id = _resolve_trading_account_id(conn, account_code=request.account_code, venue=request.venue)
    candidate = _candidate_row(trading_account_id=trading_account_id, request=request)
    try:
        resolve_account_protection_policy_v1(
            (candidate,), (), trading_account_id=trading_account_id, at=request.effective_from_ts_utc,
        )
    except AccountProtectionPolicyConfigError as exc:
        raise AccountProtectionPolicyProvisioningError(
            exc.args[0] if exc.args else "INVALID_PROTECTION_CONFIGURATION"
        ) from exc

    try:
        existing_rows = load_account_protection_policy_config_rows_v1(conn, trading_account_id=trading_account_id)
        existing_revocations = load_account_protection_policy_config_revocations_v1(
            conn, trading_account_id=trading_account_id,
        )
    except AccountProtectionPolicyRepositoryError as exc:
        raise AccountProtectionPolicyProvisioningError("PERSISTED_PROTECTION_CONFIGURATION_EVIDENCE_INVALID") from exc

    try:
        resolve_account_protection_policy_v1(
            existing_rows, existing_revocations, trading_account_id=trading_account_id,
            at=request.effective_from_ts_utc,
        )
    except AccountProtectionPolicyConfigError as exc:
        reason = exc.args[0] if exc.args else "PROTECTION_CONFIGURATION_STATE_INVALID"
        if reason != "PROTECTION_CONFIGURATION_UNRESOLVED":
            raise AccountProtectionPolicyProvisioningError(reason) from exc
    else:
        raw = _find_effective_raw_row(
            existing_rows, existing_revocations, trading_account_id=trading_account_id,
            at=request.effective_from_ts_utc,
        )
        if _same_values(raw, request):
            return AccountProtectionPolicyProvisioningResultV1(
                trading_account_id=trading_account_id,
                account_protection_policy_config_id=raw.account_protection_policy_config_id,
                idempotent=True,
            )
        raise AccountProtectionPolicyConflictError("CONFLICTING_PROTECTION_CONFIGURATION")

    if _would_overlap_existing_row(
        existing_rows, existing_revocations, trading_account_id=trading_account_id,
        candidate_start=request.effective_from_ts_utc, candidate_end=request.effective_until_ts_utc,
    ):
        raise AccountProtectionPolicyConflictError("OVERLAPPING_PROTECTION_CONFIGURATION")

    insert_sql = """
    INSERT INTO account_protection_policy_config_v1 (
        trading_account_id, config_version, configuration_version,
        max_account_drawdown, max_daily_realized_loss, max_repeated_stoploss_streak,
        max_metric_age_seconds, effective_from_ts_utc, effective_until_ts_utc,
        source_provenance
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    params = (
        trading_account_id, request.config_version, request.configuration_version,
        request.max_account_drawdown, request.max_daily_realized_loss,
        request.max_repeated_stoploss_streak, request.max_metric_age_seconds,
        request.effective_from_ts_utc, request.effective_until_ts_utc,
        request.source_provenance,
    )
    with conn.cursor() as cur:
        cur.execute(insert_sql, params)
        new_id = int(cur.lastrowid)
    return AccountProtectionPolicyProvisioningResultV1(
        trading_account_id=trading_account_id,
        account_protection_policy_config_id=new_id,
        idempotent=False,
    )
