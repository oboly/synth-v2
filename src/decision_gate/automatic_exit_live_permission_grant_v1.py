"""Issue #588: canonical append-only grant path for
``automatic_exit_live_decision_gate_permission_v1``.

This is the sole service/validation seam for granting decision-gate LIVE
automatic-exit permission. It owns every eligibility, idempotency, and
conflict decision; the ops CLI
(``run_grant_automatic_exit_live_permission_v1.py``) and the repository
(``automatic_exit_live_permission_repository_v1.py``) hold no such logic of
their own -- the CLI only parses arguments and prints results, and the
repository's write function performs a bare, unconditional ``INSERT``.

Grants decision-gate LIVE permission only. Never touches credentials,
account bindings, the kill switch, executor LIVE authority, or broker/order
state, and never calls a broker API.

Fail-closed by design: any ambiguous or conflicting persisted state blocks
the grant rather than guessing. Permission rows are permanently immutable;
this module never issues ``UPDATE`` or ``DELETE`` against the permission or
revocation tables, and revocation remains a wholly separate canonical path
(not implemented here). ``check_automatic_exit_live_permission_grant_v1``
performs the identical validation as ``apply_...`` but never writes.

broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from src.decision_gate.automatic_exit_live_permission_contract_v1 import (
    SUPPORTED_PERMISSION_VERSIONS,
    AutomaticExitLiveDecisionGatePermissionV1,
    AutomaticExitLivePermissionContractError,
    resolve_automatic_exit_live_decision_gate_permission_v1,
)
from src.decision_gate.automatic_exit_live_permission_repository_v1 import (
    AutomaticExitLivePermissionRepositoryError,
    insert_automatic_exit_live_decision_gate_permission_v1,
    load_automatic_exit_live_permission_history_v1,
    load_automatic_exit_live_permission_revocation_history_v1,
    load_trading_account_live_readiness_v1,
)

LIVE_ACCOUNT_MODE: Final[str] = "live"
_SOURCE_PROVENANCE_MAX_LENGTH: Final[int] = 128

CHECK_STATE_READY_TO_GRANT: Final[str] = "READY_TO_GRANT"
CHECK_STATE_ALREADY_GRANTED: Final[str] = "ALREADY_GRANTED"
CHECK_STATE_BLOCKED: Final[str] = "BLOCKED"
SUPPORTED_CHECK_STATES: Final[frozenset[str]] = frozenset(
    {CHECK_STATE_READY_TO_GRANT, CHECK_STATE_ALREADY_GRANTED, CHECK_STATE_BLOCKED},
)

REASON_OK: Final[str] = "OK"
REASON_UNKNOWN_TRADING_ACCOUNT: Final[str] = "UNKNOWN_TRADING_ACCOUNT"
REASON_ACCOUNT_DISABLED: Final[str] = "ACCOUNT_DISABLED"
REASON_ACCOUNT_NOT_LIVE_MODE: Final[str] = "ACCOUNT_NOT_LIVE_MODE"
REASON_LIVE_TRADING_NOT_ENABLED: Final[str] = "LIVE_TRADING_NOT_ENABLED"
REASON_CONFLICTING_LIVE_PERMISSION_STATE: Final[str] = "CONFLICTING_LIVE_PERMISSION_STATE"
REASON_OVERLAPPING_LIVE_PERMISSION_STATE: Final[str] = "OVERLAPPING_LIVE_PERMISSION_STATE"
REASON_PERSISTED_PERMISSION_EVIDENCE_INVALID: Final[str] = "PERSISTED_PERMISSION_EVIDENCE_INVALID"


class AutomaticExitLivePermissionGrantError(RuntimeError):
    """Fail-closed grant validation error. ``args[0]`` is the reason code."""


@dataclass(frozen=True)
class AutomaticExitLivePermissionGrantRequestV1:
    trading_account_id: int
    requested_ts_utc: datetime
    permission_version: str
    source_provenance: str


@dataclass(frozen=True)
class AutomaticExitLivePermissionGrantCheckV1:
    trading_account_id: int
    check_state: str  # READY_TO_GRANT | ALREADY_GRANTED | BLOCKED
    reason_code: str
    existing_permission_id: int | None


@dataclass(frozen=True)
class AutomaticExitLivePermissionGrantResultV1:
    trading_account_id: int
    permission_id: int
    idempotent: bool


def _aware(value: object) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_request(request: AutomaticExitLivePermissionGrantRequestV1) -> None:
    if request.trading_account_id <= 0:
        raise AutomaticExitLivePermissionGrantError("INVALID_TRADING_ACCOUNT_ID")
    if not _aware(request.requested_ts_utc):
        raise AutomaticExitLivePermissionGrantError("INVALID_REQUESTED_TIMESTAMP")
    if request.permission_version not in SUPPORTED_PERMISSION_VERSIONS:
        raise AutomaticExitLivePermissionGrantError("UNSUPPORTED_PERMISSION_VERSION")
    if (
        not _nonempty(request.source_provenance)
        or len(request.source_provenance) > _SOURCE_PROVENANCE_MAX_LENGTH
    ):
        raise AutomaticExitLivePermissionGrantError("INVALID_SOURCE_PROVENANCE")


def _validate_account_readiness(readiness: Any) -> None:
    if readiness is None:
        raise AutomaticExitLivePermissionGrantError(REASON_UNKNOWN_TRADING_ACCOUNT)
    if not readiness.enabled:
        raise AutomaticExitLivePermissionGrantError(REASON_ACCOUNT_DISABLED)
    if readiness.account_mode != LIVE_ACCOUNT_MODE:
        raise AutomaticExitLivePermissionGrantError(REASON_ACCOUNT_NOT_LIVE_MODE)
    if not readiness.live_trading_enabled:
        raise AutomaticExitLivePermissionGrantError(REASON_LIVE_TRADING_NOT_ENABLED)


def _permission_effective_end(
    row: AutomaticExitLiveDecisionGatePermissionV1,
    *,
    revocations: tuple[Any, ...],
) -> datetime | None:
    ends = [row.effective_until_ts_utc] if row.effective_until_ts_utc is not None else []
    ends.extend(
        revocation.effective_ts_utc for revocation in revocations if revocation.permission_id == row.permission_id
    )
    return min(ends) if ends else None


def _overlaps_any_existing_permission(
    rows: tuple[AutomaticExitLiveDecisionGatePermissionV1, ...],
    revocations: tuple[Any, ...],
    *,
    trading_account_id: int,
    candidate_start: datetime,
) -> bool:
    """Detect any existing (including future-dated) row that would make an
    open-ended grant starting at ``candidate_start`` ambiguous.

    The candidate grant is open-ended (``effective_until_ts_utc is None``),
    so it overlaps any existing row whose own effective window has not
    ended strictly before ``candidate_start``.
    """
    for row in rows:
        if row.trading_account_id != trading_account_id:
            continue
        row_end = _permission_effective_end(row, revocations=revocations)
        if row_end is None or row_end > candidate_start:
            return True
    return False


def _resolve_existing_grant_state(
    conn: Any, *, trading_account_id: int, requested_ts_utc: datetime,
) -> tuple[str, int | None]:
    """Return ``(CHECK_STATE_ALREADY_GRANTED, id)`` or ``(CHECK_STATE_READY_TO_GRANT, None)``.

    Raises :class:`AutomaticExitLivePermissionGrantError` (fail-closed) for
    any ambiguous/conflicting persisted state -- never guesses.
    """
    try:
        rows = load_automatic_exit_live_permission_history_v1(conn, trading_account_id=trading_account_id)
        revocations = load_automatic_exit_live_permission_revocation_history_v1(
            conn, trading_account_id=trading_account_id,
        )
    except AutomaticExitLivePermissionRepositoryError as exc:
        raise AutomaticExitLivePermissionGrantError(REASON_PERSISTED_PERMISSION_EVIDENCE_INVALID) from exc

    try:
        resolved = resolve_automatic_exit_live_decision_gate_permission_v1(
            rows, revocations, trading_account_id=trading_account_id, at=requested_ts_utc,
        )
    except AutomaticExitLivePermissionContractError as exc:
        raise AutomaticExitLivePermissionGrantError(REASON_CONFLICTING_LIVE_PERMISSION_STATE) from exc

    if resolved is not None:
        if resolved.live_execution_permitted:
            return CHECK_STATE_ALREADY_GRANTED, resolved.permission_id
        # An active, non-revoked DENY fact blocks an implicit grant; revoking
        # it is a separate canonical path, not performed by this grant seam.
        raise AutomaticExitLivePermissionGrantError(REASON_CONFLICTING_LIVE_PERMISSION_STATE)

    if _overlaps_any_existing_permission(
        rows, revocations, trading_account_id=trading_account_id, candidate_start=requested_ts_utc,
    ):
        raise AutomaticExitLivePermissionGrantError(REASON_OVERLAPPING_LIVE_PERMISSION_STATE)

    return CHECK_STATE_READY_TO_GRANT, None


def check_automatic_exit_live_permission_grant_v1(
    conn: Any, *, request: AutomaticExitLivePermissionGrantRequestV1,
) -> AutomaticExitLivePermissionGrantCheckV1:
    """Report grant eligibility without writing anything.

    Runs the identical validation as ``apply_...`` (account readiness,
    idempotency, conflict/overlap detection) but never inserts a row.
    """
    _validate_request(request)
    try:
        readiness = load_trading_account_live_readiness_v1(
            conn, trading_account_id=request.trading_account_id,
        )
        _validate_account_readiness(readiness)
        check_state, existing_id = _resolve_existing_grant_state(
            conn, trading_account_id=request.trading_account_id, requested_ts_utc=request.requested_ts_utc,
        )
    except AutomaticExitLivePermissionGrantError as exc:
        reason = exc.args[0] if exc.args else CHECK_STATE_BLOCKED
        return AutomaticExitLivePermissionGrantCheckV1(
            trading_account_id=request.trading_account_id,
            check_state=CHECK_STATE_BLOCKED,
            reason_code=reason,
            existing_permission_id=None,
        )
    return AutomaticExitLivePermissionGrantCheckV1(
        trading_account_id=request.trading_account_id,
        check_state=check_state,
        reason_code=REASON_OK if check_state == CHECK_STATE_READY_TO_GRANT else CHECK_STATE_ALREADY_GRANTED,
        existing_permission_id=existing_id,
    )


def apply_automatic_exit_live_permission_grant_v1(
    conn: Any, *, request: AutomaticExitLivePermissionGrantRequestV1,
) -> AutomaticExitLivePermissionGrantResultV1:
    """Append one new LIVE permission grant fact, or return the existing grant.

    The caller owns transaction commit/rollback. Raises
    :class:`AutomaticExitLivePermissionGrantError` (fail-closed) for any
    ineligible/ambiguous/conflicting state; nothing is written in that case.
    ``FOR UPDATE`` on the account row serializes concurrent grant calls for
    the same account.
    """
    _validate_request(request)
    readiness = load_trading_account_live_readiness_v1(
        conn, trading_account_id=request.trading_account_id, for_update=True,
    )
    _validate_account_readiness(readiness)
    check_state, existing_id = _resolve_existing_grant_state(
        conn, trading_account_id=request.trading_account_id, requested_ts_utc=request.requested_ts_utc,
    )
    if check_state == CHECK_STATE_ALREADY_GRANTED:
        assert existing_id is not None
        return AutomaticExitLivePermissionGrantResultV1(
            trading_account_id=request.trading_account_id,
            permission_id=existing_id,
            idempotent=True,
        )

    new_id = insert_automatic_exit_live_decision_gate_permission_v1(
        conn,
        trading_account_id=request.trading_account_id,
        live_execution_permitted=True,
        effective_from_ts_utc=request.requested_ts_utc,
        effective_until_ts_utc=None,
        permission_version=request.permission_version,
        source_provenance=request.source_provenance,
    )
    return AutomaticExitLivePermissionGrantResultV1(
        trading_account_id=request.trading_account_id,
        permission_id=new_id,
        idempotent=False,
    )
