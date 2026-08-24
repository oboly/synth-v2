"""Issue #498: canonical provisioning path for ``automatic_buy_account_permission_v1``.

``automatic_buy_execution_enabled`` (Issue #474) is durable, decision-gate-
owned operator opt-in evidence, not derived from other account state: the
repository (`automatic_buy_account_permission_repository_v1.py`) only reads
persisted rows, and the resolver's own docstring states "absence of a row is
not evidence of permission" -- there is no formula that computes it from
balances, positions, or any other snapshot. It therefore needs its own
explicit provisioning path, exactly like ``strategy_bucket_account_config_v1``
(see ``strategy_bucket_account_config_provisioning_v1.py``, whose idempotency/
conflict/account-resolution shape this module mirrors).

This is the sole writer for ``automatic_buy_account_permission_v1`` in the
repository. It provisions by canonical ``(account_code, venue)`` identity,
never a caller-supplied numeric ``trading_account_id``. It never updates or
deletes a row (append-only by DB trigger); revoking an existing permission is
deliberately out of this module's scope, so a conflicting rerun fails closed.

No broker, executor, credential, or order import. No market candidate truth
is created or modified. Grants no executor authority, credential, broker
permission, or LIVE trading permission -- this is the general PAPER+LIVE
automatic-BUY opt-in only, wholly separate from
``automatic_buy_live_decision_gate_permission_v1``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from src.decision_gate.automatic_buy_account_permission_contract_v1 import (
    PERMISSION_CONTRACT_VERSION,
    AutomaticBuyAccountPermissionContractError,
    AutomaticBuyAccountPermissionRevocationV1,
    AutomaticBuyAccountPermissionV1,
    resolve_automatic_buy_account_permission_v1,
)
from src.decision_gate.automatic_buy_account_permission_repository_v1 import (
    AutomaticBuyAccountPermissionRepositoryError,
    load_automatic_buy_account_permission_history_v1,
    load_automatic_buy_account_permission_revocation_history_v1,
)

_SOURCE_PROVENANCE_MAX_LENGTH: Final[int] = 128

# The permission contract validates permission_id > 0, so the pre-insert
# validation candidate needs a positive placeholder id (discarded, never
# persisted).
_PRE_VALIDATION_PERMISSION_ID: Final[int] = 1


class AutomaticBuyAccountPermissionProvisioningError(RuntimeError):
    """Fail-closed provisioning error. ``args[0]`` is the reason code."""


class AutomaticBuyAccountPermissionConflictError(AutomaticBuyAccountPermissionProvisioningError):
    """An effective, non-revoked permission already covers this account with a different value."""


@dataclass(frozen=True)
class AutomaticBuyAccountPermissionProvisioningRequestV1:
    account_code: str
    venue: str
    execution_enabled: bool
    effective_from_ts_utc: datetime
    source_provenance: str


@dataclass(frozen=True)
class AutomaticBuyAccountPermissionProvisioningResultV1:
    trading_account_id: int
    automatic_buy_account_permission_id: int
    idempotent: bool


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _aware(value: object) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _validate_request(request: AutomaticBuyAccountPermissionProvisioningRequestV1) -> None:
    if not _nonempty(request.account_code) or not _nonempty(request.venue):
        raise AutomaticBuyAccountPermissionProvisioningError("INVALID_ACCOUNT_IDENTITY")
    if not _nonempty(request.source_provenance) or len(request.source_provenance) > _SOURCE_PROVENANCE_MAX_LENGTH:
        raise AutomaticBuyAccountPermissionProvisioningError("INVALID_SOURCE_PROVENANCE")
    if not _aware(request.effective_from_ts_utc):
        raise AutomaticBuyAccountPermissionProvisioningError("INVALID_EFFECTIVE_FROM_TIMESTAMP")
    if type(request.execution_enabled) is not bool:
        raise AutomaticBuyAccountPermissionProvisioningError("INVALID_BOOLEAN_FIELD")


def _resolve_trading_account_id(conn: Any, *, account_code: str, venue: str) -> int:
    sql = "SELECT trading_account_id FROM trading_account WHERE account_code = %s AND venue = %s LIMIT 1"
    with conn.cursor() as cur:
        cur.execute(sql, (account_code, venue))
        row = cur.fetchone()
    if row is None:
        raise AutomaticBuyAccountPermissionProvisioningError("UNKNOWN_TRADING_ACCOUNT")
    return int(row["trading_account_id"])


def _candidate_row(
    *, trading_account_id: int, request: AutomaticBuyAccountPermissionProvisioningRequestV1,
) -> AutomaticBuyAccountPermissionV1:
    return AutomaticBuyAccountPermissionV1(
        permission_id=_PRE_VALIDATION_PERMISSION_ID,
        trading_account_id=trading_account_id,
        execution_enabled=request.execution_enabled,
        effective_from_ts_utc=request.effective_from_ts_utc,
        effective_until_ts_utc=None,
        permission_version=PERMISSION_CONTRACT_VERSION,
        source_provenance=request.source_provenance,
    )


def _active_at(row: AutomaticBuyAccountPermissionV1, *, at: datetime) -> bool:
    return row.effective_from_ts_utc <= at and (row.effective_until_ts_utc is None or at < row.effective_until_ts_utc)


def _revoked_at(
    permission_id: int, *, revocations: tuple[AutomaticBuyAccountPermissionRevocationV1, ...], at: datetime,
) -> bool:
    return any(row.permission_id == permission_id and row.effective_ts_utc <= at for row in revocations)


def _find_effective_raw_row(
    rows: tuple[AutomaticBuyAccountPermissionV1, ...],
    revocations: tuple[AutomaticBuyAccountPermissionRevocationV1, ...],
    *,
    trading_account_id: int,
    at: datetime,
) -> AutomaticBuyAccountPermissionV1:
    """Mirror the two ``resolve_automatic_buy_account_permission_v1`` predicates.

    Only called after that resolver has already proven exactly one such row
    exists, so this always finds exactly one match.
    """
    matches = [
        row for row in rows
        if row.trading_account_id == trading_account_id
        and _active_at(row, at=at)
        and not _revoked_at(row.permission_id, revocations=revocations, at=at)
    ]
    if len(matches) != 1:
        raise AutomaticBuyAccountPermissionProvisioningError("AUTOMATIC_BUY_ACCOUNT_PERMISSION_STATE_INVALID")
    return matches[0]


def _future_row_would_conflict(
    rows: tuple[AutomaticBuyAccountPermissionV1, ...], *, trading_account_id: int, candidate_start: datetime,
) -> bool:
    """True if any persisted permission row for this account starts after ``candidate_start``.

    A newly-inserted row is always open-ended, so once ``candidate_start``
    passes, it stays active forever. Any row not yet active at
    ``candidate_start`` (excluded by the caller's own-time resolve check) but
    scheduled to become active later would collide with the new open-ended
    row the moment it starts, making both simultaneously active and the
    runtime resolver ambiguous -- unconditionally: the contract requires a
    revocation's ``effective_ts_utc`` to be strictly after the row's own
    ``effective_from_ts_utc`` (``_validate_revocation``), so a future row can
    never already be revoked at-or-before its own start; it is always alive
    for at least an instant once it begins, which is enough to overlap an
    indefinitely open-ended candidate. Rows with an earlier or equal
    ``effective_from_ts_utc`` are already covered by the caller's resolve-at-
    ``candidate_start`` check and are skipped here.
    """
    return any(
        row.trading_account_id == trading_account_id and row.effective_from_ts_utc > candidate_start
        for row in rows
    )


def _same_values(
    existing: AutomaticBuyAccountPermissionV1, request: AutomaticBuyAccountPermissionProvisioningRequestV1,
) -> bool:
    return (
        existing.permission_version == PERMISSION_CONTRACT_VERSION
        and existing.execution_enabled == request.execution_enabled
        and existing.effective_from_ts_utc == request.effective_from_ts_utc
        and existing.effective_until_ts_utc is None
        and existing.source_provenance == request.source_provenance
    )


def provision_automatic_buy_account_permission_v1(
    conn: Any, *, request: AutomaticBuyAccountPermissionProvisioningRequestV1,
) -> AutomaticBuyAccountPermissionProvisioningResultV1:
    """Provision one durable, deterministic, idempotent execution-permission row.

    Caller owns the DB transaction boundary (commit/rollback).
    """
    _validate_request(request)
    trading_account_id = _resolve_trading_account_id(conn, account_code=request.account_code, venue=request.venue)

    candidate = _candidate_row(trading_account_id=trading_account_id, request=request)
    try:
        resolve_automatic_buy_account_permission_v1(
            (candidate,), (), trading_account_id=trading_account_id, at=request.effective_from_ts_utc,
        )
    except AutomaticBuyAccountPermissionContractError as exc:
        reason = exc.args[0] if exc.args else "INVALID_AUTOMATIC_BUY_ACCOUNT_PERMISSION"
        raise AutomaticBuyAccountPermissionProvisioningError(reason) from exc

    try:
        existing_rows = load_automatic_buy_account_permission_history_v1(conn, trading_account_id=trading_account_id)
        existing_revocations = load_automatic_buy_account_permission_revocation_history_v1(
            conn, trading_account_id=trading_account_id,
        )
    except AutomaticBuyAccountPermissionRepositoryError as exc:
        raise AutomaticBuyAccountPermissionProvisioningError(
            "PERSISTED_AUTOMATIC_BUY_ACCOUNT_PERMISSION_EVIDENCE_INVALID"
        ) from exc

    try:
        effective = resolve_automatic_buy_account_permission_v1(
            existing_rows, existing_revocations, trading_account_id=trading_account_id, at=request.effective_from_ts_utc,
        )
    except AutomaticBuyAccountPermissionContractError as exc:
        raise AutomaticBuyAccountPermissionProvisioningError(
            (exc.args[0] if exc.args else None) or "AUTOMATIC_BUY_ACCOUNT_PERMISSION_STATE_INVALID"
        ) from exc

    if effective is not None:
        raw = _find_effective_raw_row(
            existing_rows, existing_revocations, trading_account_id=trading_account_id, at=request.effective_from_ts_utc,
        )
        if _same_values(raw, request):
            return AutomaticBuyAccountPermissionProvisioningResultV1(
                trading_account_id=trading_account_id,
                automatic_buy_account_permission_id=raw.permission_id,
                idempotent=True,
            )
        raise AutomaticBuyAccountPermissionConflictError("CONFLICTING_AUTOMATIC_BUY_ACCOUNT_PERMISSION")

    if _future_row_would_conflict(
        existing_rows, trading_account_id=trading_account_id, candidate_start=request.effective_from_ts_utc,
    ):
        raise AutomaticBuyAccountPermissionConflictError("FUTURE_AUTOMATIC_BUY_ACCOUNT_PERMISSION_OVERLAP")

    insert_sql = """
    INSERT INTO automatic_buy_account_permission_v1 (
        trading_account_id, execution_enabled, effective_from_ts_utc, effective_until_ts_utc,
        permission_version, source_provenance
    ) VALUES (%s, %s, %s, %s, %s, %s)
    """
    params = (
        trading_account_id, request.execution_enabled, request.effective_from_ts_utc, None,
        PERMISSION_CONTRACT_VERSION, request.source_provenance,
    )
    with conn.cursor() as cur:
        cur.execute(insert_sql, params)
        new_id = int(cur.lastrowid)

    return AutomaticBuyAccountPermissionProvisioningResultV1(
        trading_account_id=trading_account_id,
        automatic_buy_account_permission_id=new_id,
        idempotent=False,
    )
