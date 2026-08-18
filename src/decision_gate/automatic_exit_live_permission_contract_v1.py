"""Issue #392 Phase 6 blocker B: pure decision-gate LIVE permission contract.

This is account-scoped, decision-gate-owned permission evidence only. It
distinguishes whether a LIVE-mode account/candidate may be considered for
``automatic_exit_gate_v1`` APPROVAL. It grants no executor operational LIVE
authority (``src/executor/execution_live_authority_v1.py``), no kill-switch
state, no credential, and no broker permission of any kind -- a decision_gate
APPROVED LIVE result under this contract still requires the wholly separate,
downstream executor-authority gate before any order may ever be placed.

Mirrors ``src/exit_policy/automatic_exit_runtime_contract_v1.py``'s
``AutomaticExitPlanningPermissionV1`` / ``resolve_automatic_exit_planning_enabled``
pattern exactly (default-denied, fail-closed on overlap/malformed evidence),
but lives in ``decision_gate`` because it is decision-gate permission, not
exit-policy planning enablement -- ``exit_policy`` does not own permission.

No database, broker, credential, executor, kill-switch, or execution_planner
import is permitted here. Database rows are loaded by a later runtime
repository (``automatic_exit_live_permission_repository_v1.py``).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final, Iterable


PERMISSION_CONTRACT_VERSION: Final[str] = "1"


class AutomaticExitLivePermissionContractError(ValueError):
    """Fail-closed contract violation. ``args[0]`` is the reason code."""


@dataclass(frozen=True)
class AutomaticExitLiveDecisionGatePermissionV1:
    """Append-only, account-scoped decision-gate LIVE permission fact.

    ``live_execution_permitted`` grants decision-gate LIVE permission only --
    never order authority, executor authority, or broker access.
    """

    permission_id: int
    trading_account_id: int
    live_execution_permitted: bool
    effective_from_ts_utc: datetime
    effective_until_ts_utc: datetime | None
    permission_version: str
    source_provenance: str


def _aware(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _active_at(*, effective_from: datetime, effective_until: datetime | None, at: datetime) -> bool:
    return effective_from <= at and (effective_until is None or at < effective_until)


def _validate_window_membership(row: AutomaticExitLiveDecisionGatePermissionV1) -> None:
    """Validate only facts required to determine whether history is current."""
    if (
        not _aware(row.effective_from_ts_utc)
        or (row.effective_until_ts_utc is not None and not _aware(row.effective_until_ts_utc))
        or (row.effective_until_ts_utc is not None and row.effective_until_ts_utc <= row.effective_from_ts_utc)
    ):
        raise AutomaticExitLivePermissionContractError("INVALID_OR_UNSUPPORTED_AUTOMATIC_EXIT_LIVE_PERMISSION")


def _validate_permission(row: AutomaticExitLiveDecisionGatePermissionV1) -> None:
    if (
        row.permission_id <= 0
        or row.trading_account_id <= 0
        or row.permission_version != PERMISSION_CONTRACT_VERSION
        or not row.source_provenance.strip()
        or type(row.live_execution_permitted) is not bool
        or not _aware(row.effective_from_ts_utc)
        or (row.effective_until_ts_utc is not None and not _aware(row.effective_until_ts_utc))
        or (row.effective_until_ts_utc is not None and row.effective_until_ts_utc <= row.effective_from_ts_utc)
    ):
        raise AutomaticExitLivePermissionContractError("INVALID_OR_UNSUPPORTED_AUTOMATIC_EXIT_LIVE_PERMISSION")


def resolve_automatic_exit_live_decision_gate_permission_v1(
    permissions: Iterable[AutomaticExitLiveDecisionGatePermissionV1],
    *,
    trading_account_id: int,
    at: datetime,
) -> bool:
    """Default-denied account-scoped LIVE decision-gate permission resolver.

    No row for the account means denied. More than one simultaneously
    effective row is ambiguous and fails closed (raises) rather than
    arbitrarily picking one. A row belonging to a different account is
    silently excluded from consideration for this lookup -- it can never
    grant permission to the wrong account -- matching
    ``resolve_automatic_exit_planning_enabled``'s existing precedent.
    """
    if trading_account_id <= 0 or not _aware(at):
        raise AutomaticExitLivePermissionContractError("INVALID_LIVE_PERMISSION_LOOKUP")
    account_rows = [row for row in permissions if row.trading_account_id == trading_account_id]
    for row in account_rows:
        _validate_window_membership(row)
    matches = [
        row for row in account_rows
        if _active_at(effective_from=row.effective_from_ts_utc, effective_until=row.effective_until_ts_utc, at=at)
    ]
    if not matches:
        return False
    if len(matches) != 1:
        raise AutomaticExitLivePermissionContractError("CONFLICTING_AUTOMATIC_EXIT_LIVE_PERMISSION")
    _validate_permission(matches[0])
    return matches[0].live_execution_permitted
