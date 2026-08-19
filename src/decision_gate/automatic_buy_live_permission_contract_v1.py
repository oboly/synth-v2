"""Pure append-only decision-gate LIVE permission contract for automatic BUY.

This grants decision_gate permission only. It never grants executor LIVE
authority, kill-switch state, credentials, broker access, or order authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final, Iterable

PERMISSION_CONTRACT_VERSION: Final[str] = "1"
REVOCATION_CONTRACT_VERSION: Final[str] = "1"
SUPPORTED_PERMISSION_VERSIONS: Final[frozenset[str]] = frozenset({PERMISSION_CONTRACT_VERSION})
SUPPORTED_REVOCATION_VERSIONS: Final[frozenset[str]] = frozenset({REVOCATION_CONTRACT_VERSION})


class AutomaticBuyLivePermissionContractError(ValueError):
    pass


@dataclass(frozen=True)
class AutomaticBuyLiveDecisionGatePermissionV1:
    permission_id: int
    trading_account_id: int
    live_execution_permitted: bool
    effective_from_ts_utc: datetime
    effective_until_ts_utc: datetime | None
    permission_version: str
    source_provenance: str


@dataclass(frozen=True)
class AutomaticBuyLiveDecisionGatePermissionRevocationV1:
    revocation_id: int
    permission_id: int
    trading_account_id: int
    revocation_version: str
    effective_ts_utc: datetime
    actor: str
    reason: str


def _aware(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _active(row: AutomaticBuyLiveDecisionGatePermissionV1, at: datetime) -> bool:
    return row.effective_from_ts_utc <= at and (row.effective_until_ts_utc is None or at < row.effective_until_ts_utc)


def _validate_permission(row: AutomaticBuyLiveDecisionGatePermissionV1) -> None:
    if (
        row.permission_id <= 0
        or row.trading_account_id <= 0
        or type(row.live_execution_permitted) is not bool
        or row.permission_version not in SUPPORTED_PERMISSION_VERSIONS
        or not isinstance(row.source_provenance, str)
        or not row.source_provenance.strip()
        or not _aware(row.effective_from_ts_utc)
        or (row.effective_until_ts_utc is not None and not _aware(row.effective_until_ts_utc))
        or (row.effective_until_ts_utc is not None and row.effective_until_ts_utc <= row.effective_from_ts_utc)
    ):
        raise AutomaticBuyLivePermissionContractError("INVALID_OR_UNSUPPORTED_AUTOMATIC_BUY_LIVE_PERMISSION")


def _validate_revocation(
    row: AutomaticBuyLiveDecisionGatePermissionRevocationV1,
    permissions_by_id: dict[int, AutomaticBuyLiveDecisionGatePermissionV1],
) -> None:
    permission = permissions_by_id.get(row.permission_id)
    if permission is None:
        raise AutomaticBuyLivePermissionContractError("INVALID_AUTOMATIC_BUY_LIVE_PERMISSION_REVOCATION")
    if permission.trading_account_id != row.trading_account_id:
        raise AutomaticBuyLivePermissionContractError("AUTOMATIC_BUY_LIVE_PERMISSION_REVOCATION_ACCOUNT_MISMATCH")
    if (
        row.revocation_id <= 0
        or row.revocation_version not in SUPPORTED_REVOCATION_VERSIONS
        or not _aware(row.effective_ts_utc)
        or row.effective_ts_utc <= permission.effective_from_ts_utc
        or not isinstance(row.actor, str)
        or not row.actor.strip()
        or not isinstance(row.reason, str)
        or not row.reason.strip()
    ):
        raise AutomaticBuyLivePermissionContractError("INVALID_AUTOMATIC_BUY_LIVE_PERMISSION_REVOCATION")


def resolve_automatic_buy_live_decision_gate_permission_v1(
    permissions: Iterable[AutomaticBuyLiveDecisionGatePermissionV1],
    revocations: Iterable[AutomaticBuyLiveDecisionGatePermissionRevocationV1] = (),
    *,
    trading_account_id: int,
    at: datetime,
) -> AutomaticBuyLiveDecisionGatePermissionV1 | None:
    if trading_account_id <= 0 or not _aware(at):
        raise AutomaticBuyLivePermissionContractError("INVALID_LIVE_PERMISSION_LOOKUP")
    all_permissions = tuple(permissions)
    permissions_by_id = {row.permission_id: row for row in all_permissions}
    account_permissions = tuple(row for row in all_permissions if row.trading_account_id == trading_account_id)
    for row in account_permissions:
        _validate_permission(row)
    account_revocations = tuple(row for row in revocations if row.trading_account_id == trading_account_id)
    for row in account_revocations:
        _validate_revocation(row, permissions_by_id)
    matches = tuple(
        row for row in account_permissions
        if _active(row, at)
        and not any(r.permission_id == row.permission_id and r.effective_ts_utc <= at for r in account_revocations)
    )
    if not matches:
        return None
    if len(matches) != 1:
        raise AutomaticBuyLivePermissionContractError("CONFLICTING_AUTOMATIC_BUY_LIVE_PERMISSION")
    return matches[0]
