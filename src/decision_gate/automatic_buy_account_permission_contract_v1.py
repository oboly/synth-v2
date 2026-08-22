"""Issue #474: pure decision-gate general automatic-BUY execution permission
contract.

This is account-scoped, decision-gate-owned permission evidence only. It is
the canonical owner of ``automatic_buy_execution_enabled`` -- a general
account-level opt-in for automatic BUY execution that applies to both PAPER
and LIVE account modes. It is wholly separate from
``automatic_buy_live_permission_contract_v1``, which resolves the additional
LIVE-only decision-gate permission required on top of this general opt-in. It
grants no executor operational authority, kill-switch state, credential,
broker permission, or order authority.

Permission rows are permanently immutable. Superseding or ending a row is
expressed exclusively through immutable revocation facts. Resolution is
fail-closed and mirrors the canonical automatic-exit account permission and
automatic-BUY LIVE permission models.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final, Iterable

PERMISSION_CONTRACT_VERSION: Final[str] = "1"
SUPPORTED_PERMISSION_VERSIONS: Final[frozenset[str]] = frozenset({PERMISSION_CONTRACT_VERSION})
REVOCATION_CONTRACT_VERSION: Final[str] = "1"
SUPPORTED_REVOCATION_VERSIONS: Final[frozenset[str]] = frozenset({REVOCATION_CONTRACT_VERSION})


class AutomaticBuyAccountPermissionContractError(ValueError):
    """Fail-closed contract violation. ``args[0]`` is the reason code."""


@dataclass(frozen=True)
class AutomaticBuyAccountPermissionV1:
    permission_id: int
    trading_account_id: int
    execution_enabled: bool
    effective_from_ts_utc: datetime
    effective_until_ts_utc: datetime | None
    permission_version: str
    source_provenance: str


@dataclass(frozen=True)
class AutomaticBuyAccountPermissionRevocationV1:
    revocation_id: int
    permission_id: int
    trading_account_id: int
    revocation_version: str
    effective_ts_utc: datetime
    actor: str
    reason: str


def _aware(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _active_at(*, effective_from: datetime, effective_until: datetime | None, at: datetime) -> bool:
    return effective_from <= at and (effective_until is None or at < effective_until)


def _validate_window_membership(row: AutomaticBuyAccountPermissionV1) -> None:
    if (
        not _aware(row.effective_from_ts_utc)
        or (row.effective_until_ts_utc is not None and not _aware(row.effective_until_ts_utc))
        or (row.effective_until_ts_utc is not None and row.effective_until_ts_utc <= row.effective_from_ts_utc)
    ):
        raise AutomaticBuyAccountPermissionContractError("INVALID_OR_UNSUPPORTED_AUTOMATIC_BUY_ACCOUNT_PERMISSION")


def _validate_permission(row: AutomaticBuyAccountPermissionV1) -> None:
    if (
        row.permission_id <= 0
        or row.trading_account_id <= 0
        or row.permission_version not in SUPPORTED_PERMISSION_VERSIONS
        or not _nonempty(row.source_provenance)
        or type(row.execution_enabled) is not bool
        or not _aware(row.effective_from_ts_utc)
        or (row.effective_until_ts_utc is not None and not _aware(row.effective_until_ts_utc))
        or (row.effective_until_ts_utc is not None and row.effective_until_ts_utc <= row.effective_from_ts_utc)
    ):
        raise AutomaticBuyAccountPermissionContractError("INVALID_OR_UNSUPPORTED_AUTOMATIC_BUY_ACCOUNT_PERMISSION")


def _validate_revocation(
    revocation: AutomaticBuyAccountPermissionRevocationV1,
    *,
    permissions_by_id: dict[int, AutomaticBuyAccountPermissionV1],
) -> None:
    referenced = permissions_by_id.get(revocation.permission_id)
    if referenced is None:
        raise AutomaticBuyAccountPermissionContractError("INVALID_AUTOMATIC_BUY_ACCOUNT_PERMISSION_REVOCATION")
    if referenced.trading_account_id != revocation.trading_account_id:
        raise AutomaticBuyAccountPermissionContractError(
            "AUTOMATIC_BUY_ACCOUNT_PERMISSION_REVOCATION_ACCOUNT_MISMATCH"
        )
    if (
        revocation.revocation_id <= 0
        or not _aware(revocation.effective_ts_utc)
        or revocation.effective_ts_utc <= referenced.effective_from_ts_utc
        or not _nonempty(revocation.actor)
        or not _nonempty(revocation.reason)
    ):
        raise AutomaticBuyAccountPermissionContractError("INVALID_AUTOMATIC_BUY_ACCOUNT_PERMISSION_REVOCATION")
    if revocation.revocation_version not in SUPPORTED_REVOCATION_VERSIONS:
        raise AutomaticBuyAccountPermissionContractError(
            "UNSUPPORTED_AUTOMATIC_BUY_ACCOUNT_PERMISSION_REVOCATION_VERSION"
        )


def _revoked_at(
    permission_id: int,
    *,
    revocations: Iterable[AutomaticBuyAccountPermissionRevocationV1],
    at: datetime,
) -> bool:
    return any(
        row.permission_id == permission_id and row.effective_ts_utc <= at
        for row in revocations
    )


def resolve_automatic_buy_account_permission_v1(
    permissions: Iterable[AutomaticBuyAccountPermissionV1],
    revocations: Iterable[AutomaticBuyAccountPermissionRevocationV1] = (),
    *,
    trading_account_id: int,
    at: datetime,
) -> AutomaticBuyAccountPermissionV1 | None:
    """Resolve one effective general automatic-BUY execution permission.

    Returns ``None`` when no non-revoked row is currently effective (default
    denied -- absence of a row is not evidence of permission). Raises
    :class:`AutomaticBuyAccountPermissionContractError` when more than one
    non-revoked row is simultaneously effective (ambiguous, fail closed) or
    any row/revocation is malformed.
    """
    if trading_account_id <= 0 or not _aware(at):
        raise AutomaticBuyAccountPermissionContractError("INVALID_ACCOUNT_PERMISSION_LOOKUP")

    all_permissions = tuple(permissions)
    permissions_by_id = {row.permission_id: row for row in all_permissions}
    account_rows = tuple(row for row in all_permissions if row.trading_account_id == trading_account_id)
    for row in account_rows:
        _validate_window_membership(row)

    relevant_revocations = tuple(
        row for row in revocations if row.trading_account_id == trading_account_id
    )
    for row in relevant_revocations:
        _validate_revocation(row, permissions_by_id=permissions_by_id)

    matches = tuple(
        row for row in account_rows
        if _active_at(
            effective_from=row.effective_from_ts_utc,
            effective_until=row.effective_until_ts_utc,
            at=at,
        )
        and not _revoked_at(row.permission_id, revocations=relevant_revocations, at=at)
    )
    if not matches:
        return None
    if len(matches) != 1:
        raise AutomaticBuyAccountPermissionContractError("CONFLICTING_AUTOMATIC_BUY_ACCOUNT_PERMISSION")
    resolved = matches[0]
    _validate_permission(resolved)
    return resolved
