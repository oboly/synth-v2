"""Issue #392 Phase 6 blocker B: pure decision-gate LIVE permission contract.

This is account-scoped, decision-gate-owned permission evidence only. It
distinguishes whether a LIVE-mode account/candidate may be considered for
``automatic_exit_gate_v1`` APPROVAL. It grants no executor operational LIVE
authority (``src/executor/execution_live_authority_v1.py``), no kill-switch
state, no credential, and no broker permission of any kind -- a decision_gate
APPROVED LIVE result under this contract still requires the wholly separate,
downstream executor-authority gate before any order may ever be placed.

Permission rows are permanently immutable (enforced in the DB by
``automatic_exit_live_decision_gate_permission_v1``'s UPDATE/DELETE-rejecting
triggers). Superseding or ending an open-ended row is expressed exclusively
through an immutable ``AutomaticExitLiveDecisionGatePermissionRevocationV1``
fact, never by mutating the permission row itself. A permission row is
revoked at time ``T`` if any of its revocation facts has
``effective_ts_utc <= T`` -- multiple revocation facts per permission row are
permitted by design so that an earlier scheduled (future-dated) revocation
can never block a later immediate one from also being recorded and taking
effect. This mirrors
``src/decision_gate/account_protection_policy_contract_v1.py`` exactly.

No database, broker, credential, executor, kill-switch, or execution_planner
import is permitted here. Database rows are loaded by a later runtime
repository (``automatic_exit_live_permission_repository_v1.py``).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final, Iterable


PERMISSION_CONTRACT_VERSION: Final[str] = "1"
SUPPORTED_PERMISSION_VERSIONS: Final[frozenset[str]] = frozenset({PERMISSION_CONTRACT_VERSION})

REVOCATION_CONTRACT_VERSION: Final[str] = "1"
SUPPORTED_REVOCATION_VERSIONS: Final[frozenset[str]] = frozenset({REVOCATION_CONTRACT_VERSION})


class AutomaticExitLivePermissionContractError(ValueError):
    """Fail-closed contract violation. ``args[0]`` is the reason code."""


@dataclass(frozen=True)
class AutomaticExitLiveDecisionGatePermissionV1:
    """Append-only, permanently immutable, account-scoped decision-gate LIVE
    permission fact.

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


@dataclass(frozen=True)
class AutomaticExitLiveDecisionGatePermissionRevocationV1:
    """One immutable revocation/supersession fact for one permission row.

    ``trading_account_id`` is denormalized from the referenced permission row
    so the resolver can detect a corrupt/conflicting cross-account reference
    without a join. ``revocation_version`` is this fact's own contract
    version (fails closed if unsupported).
    """

    revocation_id: int
    permission_id: int
    trading_account_id: int
    revocation_version: str
    effective_ts_utc: datetime
    actor: str
    reason: str


def _aware(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _is_nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


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
        or row.permission_version not in SUPPORTED_PERMISSION_VERSIONS
        or not row.source_provenance.strip()
        or type(row.live_execution_permitted) is not bool
        or not _aware(row.effective_from_ts_utc)
        or (row.effective_until_ts_utc is not None and not _aware(row.effective_until_ts_utc))
        or (row.effective_until_ts_utc is not None and row.effective_until_ts_utc <= row.effective_from_ts_utc)
    ):
        raise AutomaticExitLivePermissionContractError("INVALID_OR_UNSUPPORTED_AUTOMATIC_EXIT_LIVE_PERMISSION")


def _validate_revocation(
    revocation: AutomaticExitLiveDecisionGatePermissionRevocationV1,
    *,
    permissions_by_id: dict[int, AutomaticExitLiveDecisionGatePermissionV1],
) -> None:
    """Validate one revocation already scoped to the account being resolved.

    Caller guarantees ``revocation.trading_account_id == trading_account_id``
    for every fact passed here; a dangling permission reference is malformed,
    while a resolvable reference whose own permission row belongs to a
    different account is a corrupt cross-account reference.
    """
    referenced = permissions_by_id.get(revocation.permission_id)
    if referenced is None:
        raise AutomaticExitLivePermissionContractError("INVALID_AUTOMATIC_EXIT_LIVE_PERMISSION_REVOCATION")
    if referenced.trading_account_id != revocation.trading_account_id:
        raise AutomaticExitLivePermissionContractError("AUTOMATIC_EXIT_LIVE_PERMISSION_REVOCATION_ACCOUNT_MISMATCH")
    if not _aware(revocation.effective_ts_utc) or revocation.effective_ts_utc <= referenced.effective_from_ts_utc:
        raise AutomaticExitLivePermissionContractError("INVALID_AUTOMATIC_EXIT_LIVE_PERMISSION_REVOCATION")
    if not _is_nonempty_string(revocation.actor) or not _is_nonempty_string(revocation.reason):
        raise AutomaticExitLivePermissionContractError("INVALID_AUTOMATIC_EXIT_LIVE_PERMISSION_REVOCATION")
    if revocation.revocation_version not in SUPPORTED_REVOCATION_VERSIONS:
        raise AutomaticExitLivePermissionContractError("UNSUPPORTED_AUTOMATIC_EXIT_LIVE_PERMISSION_REVOCATION_VERSION")


def _revoked_at(
    permission_id: int,
    *,
    revocations: Iterable[AutomaticExitLiveDecisionGatePermissionRevocationV1],
    at: datetime,
) -> bool:
    return any(
        revocation.permission_id == permission_id and revocation.effective_ts_utc <= at
        for revocation in revocations
    )


def resolve_automatic_exit_live_decision_gate_permission_v1(
    permissions: Iterable[AutomaticExitLiveDecisionGatePermissionV1],
    revocations: Iterable[AutomaticExitLiveDecisionGatePermissionRevocationV1] = (),
    *,
    trading_account_id: int,
    at: datetime,
) -> AutomaticExitLiveDecisionGatePermissionV1 | None:
    """Return the single effective, non-revoked, supported-version permission row, or ``None``.

    ``None`` means no active permission for this account at ``at`` --
    default-denied, not an error. Fail-closed (raises
    :class:`AutomaticExitLivePermissionContractError`) when: more than one
    non-revoked row is simultaneously effective (ambiguous), a row's window
    is malformed, any revocation referencing this account's permission is
    malformed/cross-account/unsupported-version, or the resolved row's
    ``permission_version``/``source_provenance`` is unsupported/missing.
    Never invents a default permission in any of these cases. A row
    belonging to a different account is excluded from consideration for this
    lookup and can never grant or affect permission for the wrong account.
    Deterministic regardless of the input iteration order of either
    ``permissions`` or ``revocations``.
    """
    if trading_account_id <= 0 or not _aware(at):
        raise AutomaticExitLivePermissionContractError("INVALID_LIVE_PERMISSION_LOOKUP")

    all_permissions = tuple(permissions)
    permissions_by_id = {row.permission_id: row for row in all_permissions}
    account_rows = tuple(row for row in all_permissions if row.trading_account_id == trading_account_id)
    for row in account_rows:
        _validate_window_membership(row)

    relevant_revocations = tuple(
        revocation for revocation in revocations if revocation.trading_account_id == trading_account_id
    )
    for revocation in relevant_revocations:
        _validate_revocation(revocation, permissions_by_id=permissions_by_id)

    matches = tuple(
        row
        for row in account_rows
        if _active_at(effective_from=row.effective_from_ts_utc, effective_until=row.effective_until_ts_utc, at=at)
        and not _revoked_at(row.permission_id, revocations=relevant_revocations, at=at)
    )
    if not matches:
        return None
    if len(matches) != 1:
        raise AutomaticExitLivePermissionContractError("CONFLICTING_AUTOMATIC_EXIT_LIVE_PERMISSION")
    resolved = matches[0]
    _validate_permission(resolved)
    return resolved
