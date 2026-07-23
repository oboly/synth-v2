from __future__ import annotations

"""Deterministic repository transaction layer for exact one-scope Native SHORT
administration (ADOPT_LEGACY_SCOPE / PROMOTE_SCOPE / REMOVE_SCOPE).

Boundary: market-only, account-agnostic, exact-one-scope, manual/reviewed
administration. This module owns the state-transition decision logic and one
bounded database transaction per operation. It imports no selection, account,
wallet, reporting, decision_gate, execution_planner, executor, broker, or order
code.

Design:

- The pure request/identity contract lives in
  ``native_short_scope_administration_v1``.
- Decision logic (``classify_scope_state`` and ``decide_administration``) is a
  pure function of an already-read state snapshot and is unit-testable without a
  database.
- Database I/O is explicit, one SQL statement per concern, with no generic
  administration framework.
- ``native_short_scope_admin_operation_v1`` is the sole idempotency authority.
  A terminal operation ledger row and its scope mutation commit atomically in
  one transaction; a crash rolls back both, so a committed ledger row is always
  terminal.
- Serialization uses one deterministic MariaDB advisory lock derived from the
  exact six-part canonical scope key (zero-wait) plus ``SELECT ... FOR UPDATE``
  row locks on the existing scope, cadence, support, and operation rows.

Safety markers:
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Callable, Mapping, Sequence

from src.market_data.native_short_scope_administration_v1 import (
    NativeShortScopeAdministrationOperationType as OperationType,
    NativeShortScopeAdministrationRequest,
    NativeShortScopeAdministrationResult,
    NativeShortScopeAdministrationResultClass as ResultClass,
    NativeShortScopeAdministrationResultCode as ResultCode,
)


# --------------------------------------------------------------------------- #
# Canonical constants                                                         #
# --------------------------------------------------------------------------- #

WRITER_CAPABILITY_ID = "native_short_4h_chain"

ADVISORY_LOCK_PREFIX = "nssa1"

CANONICAL_CADENCE_CONTRACT_VERSION = "native_short_cadence_v1"
CANONICAL_TARGET_EVALUATION_INTERVAL = "1h"
CANONICAL_PRIMARY_SOURCE_FRESHNESS_LIMIT_SECONDS = 43200
CANONICAL_SUPPORTING_SOURCE_FRESHNESS_LIMIT_SECONDS = 10800
CANONICAL_EVALUATION_GRACE_SECONDS = 900
CANONICAL_RECENT_SCOPE_GRACE_SECONDS = 3600

SUPPORTED_STATE = "SUPPORTED"
NOT_APPLICABLE_STATE = "NOT_APPLICABLE"

# Stable, documented administration-removal reason code. It intentionally does
# not reuse any market-lifecycle outcome code so a withdrawal can never be
# misread as a market completion/expiry/invalidation.
ADMIN_REMOVAL_REASON_CODE = "ADMIN_SCOPE_WITHDRAWN"
ADMIN_REMOVAL_REASON_DETAIL = "Scope withdrawn by reviewed Native SHORT administration"

ADMIN_SOURCE_NAME = "native_short_scope_administration_transaction_v1"
ADMIN_SOURCE_VERSION = "1"

_SUPPORT_EVENT_REASON_CODE = {
    "ADOPT": "ADMIN_ADOPTED_LEGACY_SCOPE",
    "PROMOTE_NEW": "ADMIN_PROMOTED_NEW_SCOPE",
    "PROMOTE_REACTIVATE": "ADMIN_PROMOTED_FROM_PRIOR_WITHDRAWAL",
    "REMOVE": "ADMIN_REMOVED_SCOPE",
}

# MariaDB error codes.
_ER_LOCK_DEADLOCK = 1213
_ER_LOCK_WAIT_TIMEOUT = 1205


# --------------------------------------------------------------------------- #
# Transaction-level enums and errors                                          #
# --------------------------------------------------------------------------- #


class NativeShortScopeAdministrationTransactionError(RuntimeError):
    pass


class TransactionMode(StrEnum):
    DRY_RUN = "DRY_RUN"
    WRITE = "WRITE"


class OperationAction(StrEnum):
    """Concrete mutation branch selected by the pure decider."""

    ADOPT = "ADOPT"
    PROMOTE_NEW = "PROMOTE_NEW"
    PROMOTE_REACTIVATE = "PROMOTE_REACTIVATE"
    REMOVE = "REMOVE"
    CLEAR_RESIDUE = "CLEAR_RESIDUE"
    IDEMPOTENT_COMPLETE = "IDEMPOTENT_COMPLETE"
    NOOP = "NOOP"
    REJECT = "REJECT"


class ScopeClassification(StrEnum):
    NO_SCOPE = "NO_SCOPE"
    LEGACY_UNADOPTED = "LEGACY_UNADOPTED"
    MANAGED_SUPPORTED = "MANAGED_SUPPORTED"
    MANAGED_REMOVED = "MANAGED_REMOVED"
    INCOHERENT = "INCOHERENT"


# Actions that persist a new terminal operation ledger row and mutate support
# state. Everything else either replays an existing terminal operation, is an
# idempotent no-op, performs only narrow residue cleanup, or is rejected.
_PERSISTING_ACTIONS = frozenset(
    {
        OperationAction.ADOPT,
        OperationAction.PROMOTE_NEW,
        OperationAction.PROMOTE_REACTIVATE,
        OperationAction.REMOVE,
    }
)


class _RetryableResult(Exception):
    """Internal control-flow signal that maps a locking/commit condition to a
    typed RETRYABLE result code after rollback + lock release."""

    def __init__(self, result_code: ResultCode) -> None:
        super().__init__(result_code.value)
        self.result_code = result_code


class _RevalidationError(Exception):
    def __init__(self, result_code: ResultCode, detail: str) -> None:
        super().__init__(f"{result_code.value}: {detail}")
        self.result_code = result_code
        self.detail = detail


# --------------------------------------------------------------------------- #
# State snapshot dataclasses                                                   #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CadenceRowState:
    cadence_config_id: int
    cadence_contract_version: str
    is_active: int
    effective_from_utc: datetime
    effective_to_utc: datetime | None
    activation_operation_id: int | None
    deactivation_operation_id: int | None
    support_generation: int | None
    target_evaluation_interval: str
    primary_source_freshness_limit_seconds: int
    supporting_source_freshness_limit_seconds: int
    evaluation_grace_seconds: int
    recent_scope_grace_seconds: int


@dataclass(frozen=True)
class ScopeStateSnapshot:
    scope_present: bool
    scope_id: int | None
    scope_support_state: str | None
    support_generation: int | None
    scope_reason_code: str | None
    scope_reason_detail: str | None
    cadence_rows: tuple[CadenceRowState, ...]
    attributable_support_generations: tuple[int, ...]
    legacy_support_event_count: int
    scope_status_residue_count: int
    map_level_status_residue_count: int

    @property
    def active_cadence_rows(self) -> tuple[CadenceRowState, ...]:
        return tuple(row for row in self.cadence_rows if int(row.is_active) == 1)

    @property
    def residue_present(self) -> bool:
        return (
            self.scope_status_residue_count > 0
            or self.map_level_status_residue_count > 0
        )

    def summary(self) -> dict[str, Any]:
        return {
            "scope_present": self.scope_present,
            "scope_support_state": self.scope_support_state,
            "support_generation": self.support_generation,
            "cadence_row_count": len(self.cadence_rows),
            "active_cadence_count": len(self.active_cadence_rows),
            "attributable_support_event_count": len(
                self.attributable_support_generations
            ),
            "legacy_support_event_count": self.legacy_support_event_count,
            "scope_status_residue_count": self.scope_status_residue_count,
            "map_level_status_residue_count": self.map_level_status_residue_count,
        }


@dataclass(frozen=True)
class ExistingOperation:
    scope_admin_operation_id: int
    operation_type: str
    metadata_digest: str
    completed_at_utc: datetime | None
    result_class: str | None
    result_code: str | None
    support_generation_before: int | None
    support_generation_after: int | None
    scope_key: dict[str, str]


@dataclass(frozen=True)
class AdministrationDecision:
    action: OperationAction
    result_code: ResultCode
    result_class: ResultClass
    support_generation_before: int | None
    support_generation_after: int | None
    target_cadence_config_id: int | None
    classification: ScopeClassification
    detail: str

    @property
    def persists_operation(self) -> bool:
        return self.action in _PERSISTING_ACTIONS


@dataclass(frozen=True)
class AdministrationTransactionOutcome:
    mode: TransactionMode
    write: bool
    persisted: bool
    operation_type: str
    operation_uuid: str
    request_digest: str
    scope_key: dict[str, str]
    action: OperationAction
    result: NativeShortScopeAdministrationResult
    scope_admin_operation_id: int | None
    advisory_lock_name: str
    current_state: dict[str, Any]
    detail: str

    def as_json_dict(self) -> dict[str, Any]:
        return {
            "mode": str(self.mode),
            "write": self.write,
            "persisted": self.persisted,
            "operation_type": self.operation_type,
            "operation_uuid": self.operation_uuid,
            "request_digest": self.request_digest,
            "scope_key": dict(self.scope_key),
            "action": str(self.action),
            "result_class": str(self.result.result_class),
            "result_code": str(self.result.result_code),
            "support_generation_before": self.result.support_generation_before,
            "support_generation_after": self.result.support_generation_after,
            "scope_admin_operation_id": self.scope_admin_operation_id,
            "advisory_lock_name": self.advisory_lock_name,
            "current_state": self.current_state,
            "detail": self.detail,
        }


# --------------------------------------------------------------------------- #
# Advisory lock                                                               #
# --------------------------------------------------------------------------- #


def advisory_lock_name(scope_key: Mapping[str, str]) -> str:
    """Deterministic, bounded MariaDB advisory-lock name for the exact six-part
    canonical scope key. Uses a stable hash so any canonical symbol length fits
    inside the MariaDB lock-name limit while remaining collision-resistant."""
    canonical = json.dumps(
        {
            "venue": scope_key["venue"],
            "symbol": scope_key["symbol"],
            "quote_currency": scope_key["quote_currency"],
            "fib_trading_horizon": scope_key["fib_trading_horizon"],
            "primary_interval": scope_key["primary_interval"],
            "supporting_interval": scope_key["supporting_interval"],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:48]
    return f"{ADVISORY_LOCK_PREFIX}:{digest}"


def _acquire_advisory_lock(conn: Any, lock_name: str) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT GET_LOCK(%s, 0) AS acquired", (lock_name,))
        row = cur.fetchone()
    acquired = None if row is None else row.get("acquired")
    if acquired is None or int(acquired) != 1:
        raise _RetryableResult(ResultCode.LOCK_TIMEOUT)


def _release_advisory_lock(conn: Any, lock_name: str) -> None:
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT RELEASE_LOCK(%s) AS released", (lock_name,))
            cur.fetchone()
    except Exception:
        # A failed release must never mask the primary outcome; the lock is
        # session-scoped and is released when the connection closes.
        pass


# --------------------------------------------------------------------------- #
# State reads                                                                  #
# --------------------------------------------------------------------------- #

_SCOPE_KEY_WHERE = (
    "venue = %s AND symbol = %s AND quote_currency = %s "
    "AND fib_trading_horizon = %s AND primary_interval = %s "
    "AND supporting_interval = %s"
)


def _scope_key_params(scope_key: Mapping[str, str]) -> tuple[str, ...]:
    return (
        scope_key["venue"],
        scope_key["symbol"],
        scope_key["quote_currency"],
        scope_key["fib_trading_horizon"],
        scope_key["primary_interval"],
        scope_key["supporting_interval"],
    )


def read_scope_state_snapshot(
    conn: Any,
    scope_key: Mapping[str, str],
    *,
    for_update: bool,
) -> ScopeStateSnapshot:
    lock = " FOR UPDATE" if for_update else ""
    params = _scope_key_params(scope_key)

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT scope_id, scope_support_state, support_generation,
                   scope_reason_code, scope_reason_detail
            FROM native_short_map_scope_v1
            WHERE {_SCOPE_KEY_WHERE}
            ORDER BY scope_id ASC{lock}
            """,
            params,
        )
        scope_rows = [dict(r) for r in cur.fetchall()]

    if len(scope_rows) > 1:
        raise _RevalidationError(
            ResultCode.PARTIAL_SCOPE_STATE,
            f"expected at most one canonical scope row, found {len(scope_rows)}",
        )

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT cadence_config_id, cadence_contract_version, is_active,
                   effective_from_utc, effective_to_utc,
                   activation_operation_id, deactivation_operation_id,
                   support_generation, target_evaluation_interval,
                   primary_source_freshness_limit_seconds,
                   supporting_source_freshness_limit_seconds,
                   evaluation_grace_seconds, recent_scope_grace_seconds
            FROM native_short_scope_cadence_config_v1
            WHERE {_SCOPE_KEY_WHERE}
            ORDER BY cadence_config_id ASC{lock}
            """,
            params,
        )
        cadence_rows = tuple(
            CadenceRowState(
                cadence_config_id=int(r["cadence_config_id"]),
                cadence_contract_version=str(r["cadence_contract_version"]),
                is_active=int(r["is_active"]),
                effective_from_utc=r["effective_from_utc"],
                effective_to_utc=r["effective_to_utc"],
                activation_operation_id=(
                    None
                    if r["activation_operation_id"] is None
                    else int(r["activation_operation_id"])
                ),
                deactivation_operation_id=(
                    None
                    if r["deactivation_operation_id"] is None
                    else int(r["deactivation_operation_id"])
                ),
                support_generation=(
                    None
                    if r["support_generation"] is None
                    else int(r["support_generation"])
                ),
                target_evaluation_interval=str(r["target_evaluation_interval"]),
                primary_source_freshness_limit_seconds=int(
                    r["primary_source_freshness_limit_seconds"]
                ),
                supporting_source_freshness_limit_seconds=int(
                    r["supporting_source_freshness_limit_seconds"]
                ),
                evaluation_grace_seconds=int(r["evaluation_grace_seconds"]),
                recent_scope_grace_seconds=int(r["recent_scope_grace_seconds"]),
            )
            for r in (dict(row) for row in cur.fetchall())
        )

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT scope_support_event_id, support_generation,
                   scope_admin_operation_id
            FROM native_short_scope_support_event_v1
            WHERE {_SCOPE_KEY_WHERE}
            ORDER BY scope_support_event_id ASC{lock}
            """,
            params,
        )
        support_rows = [dict(r) for r in cur.fetchall()]

    attributable = tuple(
        sorted(
            int(r["support_generation"])
            for r in support_rows
            if r["support_generation"] is not None
        )
    )
    legacy_count = sum(1 for r in support_rows if r["support_generation"] is None)

    scope_status_residue = _count(
        conn,
        f"SELECT COUNT(*) AS n FROM native_short_scope_status_v1 WHERE {_SCOPE_KEY_WHERE}",
        params,
    )
    map_level_residue = _count(
        conn,
        f"SELECT COUNT(*) AS n FROM native_short_map_level_status_v1 WHERE {_SCOPE_KEY_WHERE}",
        params,
    )

    scope = scope_rows[0] if scope_rows else None
    return ScopeStateSnapshot(
        scope_present=scope is not None,
        scope_id=None if scope is None else int(scope["scope_id"]),
        scope_support_state=None if scope is None else scope["scope_support_state"],
        support_generation=(
            None
            if scope is None or scope["support_generation"] is None
            else int(scope["support_generation"])
        ),
        scope_reason_code=None if scope is None else scope["scope_reason_code"],
        scope_reason_detail=None if scope is None else scope["scope_reason_detail"],
        cadence_rows=cadence_rows,
        attributable_support_generations=attributable,
        legacy_support_event_count=legacy_count,
        scope_status_residue_count=scope_status_residue,
        map_level_status_residue_count=map_level_residue,
    )


def _count(conn: Any, sql: str, params: Sequence[Any]) -> int:
    with conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        row = cur.fetchone()
    return int(row["n"]) if row else 0


def read_existing_operation(
    conn: Any,
    operation_uuid: str,
    *,
    for_update: bool,
) -> ExistingOperation | None:
    lock = " FOR UPDATE" if for_update else ""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT scope_admin_operation_id, operation_type, metadata_digest,
                   completed_at_utc, result_class, result_code,
                   support_generation_before, support_generation_after,
                   venue, symbol, quote_currency, fib_trading_horizon,
                   primary_interval, supporting_interval
            FROM native_short_scope_admin_operation_v1
            WHERE operation_uuid = %s{lock}
            """,
            (operation_uuid,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    r = dict(row)
    return ExistingOperation(
        scope_admin_operation_id=int(r["scope_admin_operation_id"]),
        operation_type=str(r["operation_type"]),
        metadata_digest=str(r["metadata_digest"]),
        completed_at_utc=r["completed_at_utc"],
        result_class=r["result_class"],
        result_code=r["result_code"],
        support_generation_before=(
            None
            if r["support_generation_before"] is None
            else int(r["support_generation_before"])
        ),
        support_generation_after=(
            None
            if r["support_generation_after"] is None
            else int(r["support_generation_after"])
        ),
        scope_key={
            "venue": r["venue"],
            "symbol": r["symbol"],
            "quote_currency": r["quote_currency"],
            "fib_trading_horizon": r["fib_trading_horizon"],
            "primary_interval": r["primary_interval"],
            "supporting_interval": r["supporting_interval"],
        },
    )


# --------------------------------------------------------------------------- #
# Pure classification and decision                                            #
# --------------------------------------------------------------------------- #


def _effective_windows_overlap(rows: Sequence[CadenceRowState]) -> bool:
    """Detect overlapping [effective_from, effective_to) windows. Open-ended
    (NULL effective_to) rows extend to the far future."""
    far_future = datetime(9999, 12, 31, 23, 59, 59, 999999)
    windows = sorted(
        (
            (r.effective_from_utc, r.effective_to_utc or far_future)
            for r in rows
        ),
        key=lambda w: w[0],
    )
    for earlier, later in zip(windows, windows[1:]):
        if later[0] < earlier[1]:
            return True
    return False


def _cadence_profile_matches_canonical(row: CadenceRowState) -> bool:
    return (
        row.cadence_contract_version == CANONICAL_CADENCE_CONTRACT_VERSION
        and row.target_evaluation_interval == CANONICAL_TARGET_EVALUATION_INTERVAL
        and row.primary_source_freshness_limit_seconds
        == CANONICAL_PRIMARY_SOURCE_FRESHNESS_LIMIT_SECONDS
        and row.supporting_source_freshness_limit_seconds
        == CANONICAL_SUPPORTING_SOURCE_FRESHNESS_LIMIT_SECONDS
        and row.evaluation_grace_seconds == CANONICAL_EVALUATION_GRACE_SECONDS
        and row.recent_scope_grace_seconds == CANONICAL_RECENT_SCOPE_GRACE_SECONDS
    )


def classify_scope_state(
    snapshot: ScopeStateSnapshot,
) -> tuple[ScopeClassification, ResultCode | None, str]:
    """Pure structural classification of the current scope state.

    Returns (classification, corrupt_code, detail). ``corrupt_code`` is set only
    when the state is structurally incoherent for any operation."""
    active = snapshot.active_cadence_rows

    if not snapshot.scope_present:
        # A cadence or attributable/legacy support row without a scope row is a
        # partial administration state.
        if snapshot.cadence_rows or snapshot.attributable_support_generations or (
            snapshot.legacy_support_event_count > 0
        ):
            return (
                ScopeClassification.INCOHERENT,
                ResultCode.PARTIAL_SCOPE_STATE,
                "cadence/support rows exist without a canonical scope row",
            )
        return (ScopeClassification.NO_SCOPE, None, "no canonical scope row")

    # More-than-one active cadence row is the most specific corruption; check it
    # before the effective-window overlap test (two open-ended active rows also
    # trivially overlap).
    if len(active) > 1:
        return (
            ScopeClassification.INCOHERENT,
            ResultCode.MULTIPLE_ACTIVE_CADENCE_ROWS,
            f"{len(active)} active cadence rows for one exact scope",
        )

    if len(snapshot.cadence_rows) > 0 and _effective_windows_overlap(
        snapshot.cadence_rows
    ):
        return (
            ScopeClassification.INCOHERENT,
            ResultCode.LEGACY_STATE_INCOHERENT,
            "overlapping effective cadence windows",
        )

    if snapshot.support_generation is None:
        # Legacy, unadopted scope.
        if snapshot.attributable_support_generations:
            return (
                ScopeClassification.INCOHERENT,
                ResultCode.PARTIAL_SCOPE_STATE,
                "legacy scope has attributable support generations",
            )
        if any(
            row.activation_operation_id is not None for row in snapshot.cadence_rows
        ):
            return (
                ScopeClassification.INCOHERENT,
                ResultCode.PARTIAL_SCOPE_STATE,
                "legacy scope has an operation-attributed cadence row",
            )
        return (
            ScopeClassification.LEGACY_UNADOPTED,
            None,
            "legacy scope with NULL support_generation",
        )

    # Managed scope (support_generation is a positive int).
    if snapshot.scope_support_state == SUPPORTED_STATE:
        if len(active) != 1:
            return (
                ScopeClassification.INCOHERENT,
                ResultCode.PARTIAL_SCOPE_STATE,
                f"managed SUPPORTED scope has {len(active)} active cadence rows",
            )
        if snapshot.support_generation not in snapshot.attributable_support_generations:
            return (
                ScopeClassification.INCOHERENT,
                ResultCode.SUPPORT_GENERATION_MISMATCH,
                "no attributable support event for the scope support_generation",
            )
        return (
            ScopeClassification.MANAGED_SUPPORTED,
            None,
            "managed SUPPORTED scope",
        )

    if snapshot.scope_support_state == NOT_APPLICABLE_STATE:
        if len(active) != 0:
            return (
                ScopeClassification.INCOHERENT,
                ResultCode.AUTHORITATIVE_WITHDRAWAL_STATE_INCOHERENT,
                f"managed removed scope has {len(active)} active cadence rows",
            )
        return (
            ScopeClassification.MANAGED_REMOVED,
            None,
            "managed NOT_APPLICABLE scope",
        )

    return (
        ScopeClassification.INCOHERENT,
        ResultCode.PARTIAL_SCOPE_STATE,
        f"unexpected scope_support_state={snapshot.scope_support_state}",
    )


def _reject(
    classification: ScopeClassification, code: ResultCode, detail: str
) -> AdministrationDecision:
    return AdministrationDecision(
        action=OperationAction.REJECT,
        result_code=code,
        result_class=_result_class_for(code),
        support_generation_before=None,
        support_generation_after=None,
        target_cadence_config_id=None,
        classification=classification,
        detail=detail,
    )


def _result_class_for(code: ResultCode) -> ResultClass:
    from src.market_data.native_short_scope_administration_v1 import (
        _RESULT_CODE_CLASS,
    )

    return _RESULT_CODE_CLASS[code]


def _decide_adopt(
    snapshot: ScopeStateSnapshot,
    classification: ScopeClassification,
    corrupt_code: ResultCode | None,
    detail: str,
) -> AdministrationDecision:
    if corrupt_code is not None:
        return _reject(classification, corrupt_code, detail)
    if classification == ScopeClassification.NO_SCOPE:
        return _reject(
            classification,
            ResultCode.LEGACY_STATE_INCOHERENT,
            "no legacy scope to adopt",
        )
    if classification in (
        ScopeClassification.MANAGED_SUPPORTED,
        ScopeClassification.MANAGED_REMOVED,
    ):
        return AdministrationDecision(
            action=OperationAction.NOOP,
            result_code=ResultCode.SCOPE_ALREADY_ADOPTED,
            result_class=ResultClass.IDEMPOTENT_SUCCESS,
            support_generation_before=snapshot.support_generation,
            support_generation_after=snapshot.support_generation,
            target_cadence_config_id=None,
            classification=classification,
            detail="scope already carries a positive administration generation",
        )
    # LEGACY_UNADOPTED: must be a coherent, canonical, single-active-cadence
    # legacy SUPPORTED scope.
    if snapshot.scope_support_state != SUPPORTED_STATE:
        return _reject(
            classification,
            ResultCode.LEGACY_STATE_INCOHERENT,
            f"legacy scope is not SUPPORTED (state={snapshot.scope_support_state})",
        )
    active = snapshot.active_cadence_rows
    if len(active) != 1:
        return _reject(
            classification,
            ResultCode.LEGACY_STATE_INCOHERENT,
            f"legacy SUPPORTED scope has {len(active)} active cadence rows",
        )
    legacy_cadence = active[0]
    if not _cadence_profile_matches_canonical(legacy_cadence):
        return _reject(
            classification,
            ResultCode.CADENCE_PROFILE_CONFLICT,
            "active legacy cadence profile is not the canonical profile",
        )
    return AdministrationDecision(
        action=OperationAction.ADOPT,
        result_code=ResultCode.ADOPTED_LEGACY_SCOPE,
        result_class=ResultClass.SUCCESS,
        support_generation_before=None,
        support_generation_after=1,
        target_cadence_config_id=legacy_cadence.cadence_config_id,
        classification=classification,
        detail="adopt coherent legacy scope as administration generation 1",
    )


def _decide_promote(
    snapshot: ScopeStateSnapshot,
    classification: ScopeClassification,
    corrupt_code: ResultCode | None,
    detail: str,
) -> AdministrationDecision:
    if corrupt_code is not None:
        return _reject(classification, corrupt_code, detail)
    if classification == ScopeClassification.NO_SCOPE:
        return AdministrationDecision(
            action=OperationAction.PROMOTE_NEW,
            result_code=ResultCode.PROMOTED_NEW_SCOPE,
            result_class=ResultClass.SUCCESS,
            support_generation_before=None,
            support_generation_after=1,
            target_cadence_config_id=None,
            classification=classification,
            detail="create first canonical scope as administration generation 1",
        )
    if classification == ScopeClassification.LEGACY_UNADOPTED:
        return _reject(
            classification,
            ResultCode.LEGACY_SCOPE_REQUIRES_ADOPTION,
            "legacy scope must be adopted before promotion",
        )
    if classification == ScopeClassification.MANAGED_SUPPORTED:
        return AdministrationDecision(
            action=OperationAction.NOOP,
            result_code=ResultCode.SCOPE_ALREADY_SUPPORTED,
            result_class=ResultClass.IDEMPOTENT_SUCCESS,
            support_generation_before=snapshot.support_generation,
            support_generation_after=snapshot.support_generation,
            target_cadence_config_id=None,
            classification=classification,
            detail="scope is already coherently SUPPORTED",
        )
    # MANAGED_REMOVED: reactivate with a new generation.
    before = snapshot.support_generation
    assert before is not None
    return AdministrationDecision(
        action=OperationAction.PROMOTE_REACTIVATE,
        result_code=ResultCode.PROMOTED_FROM_PRIOR_WITHDRAWAL,
        result_class=ResultClass.SUCCESS,
        support_generation_before=before,
        support_generation_after=before + 1,
        target_cadence_config_id=None,
        classification=classification,
        detail="re-support a coherently withdrawn managed scope",
    )


def _decide_remove(
    snapshot: ScopeStateSnapshot,
    classification: ScopeClassification,
    corrupt_code: ResultCode | None,
    detail: str,
) -> AdministrationDecision:
    if corrupt_code is not None:
        return _reject(classification, corrupt_code, detail)
    if classification == ScopeClassification.NO_SCOPE:
        return _already_removed_or_residue(snapshot, classification)
    if classification == ScopeClassification.LEGACY_UNADOPTED:
        return _reject(
            classification,
            ResultCode.LEGACY_SCOPE_REQUIRES_ADOPTION,
            "legacy scope must be adopted before removal",
        )
    if classification == ScopeClassification.MANAGED_REMOVED:
        return _already_removed_or_residue(snapshot, classification)
    # MANAGED_SUPPORTED: withdraw.
    before = snapshot.support_generation
    assert before is not None
    active = snapshot.active_cadence_rows
    return AdministrationDecision(
        action=OperationAction.REMOVE,
        result_code=ResultCode.REMOVED_SCOPE,
        result_class=ResultClass.SUCCESS,
        support_generation_before=before,
        support_generation_after=before + 1,
        target_cadence_config_id=active[0].cadence_config_id,
        classification=classification,
        detail="withdraw a coherent managed SUPPORTED scope",
    )


def _already_removed_or_residue(
    snapshot: ScopeStateSnapshot,
    classification: ScopeClassification,
) -> AdministrationDecision:
    generation = snapshot.support_generation
    if snapshot.residue_present:
        return AdministrationDecision(
            action=OperationAction.CLEAR_RESIDUE,
            result_code=ResultCode.ALREADY_REMOVED_DERIVED_RESIDUE_CLEARED,
            result_class=ResultClass.IDEMPOTENT_SUCCESS,
            support_generation_before=generation,
            support_generation_after=generation,
            target_cadence_config_id=None,
            classification=classification,
            detail="clear falsely-actionable derived projection residue",
        )
    return AdministrationDecision(
        action=OperationAction.NOOP,
        result_code=ResultCode.SCOPE_ALREADY_REMOVED,
        result_class=ResultClass.IDEMPOTENT_SUCCESS,
        support_generation_before=generation,
        support_generation_after=generation,
        target_cadence_config_id=None,
        classification=classification,
        detail="scope is already not supported",
    )


def decide_administration(
    operation_type: OperationType,
    snapshot: ScopeStateSnapshot,
) -> AdministrationDecision:
    """Pure decision function: given the operation and a state snapshot, choose
    exactly one action and typed result code. No database access."""
    classification, corrupt_code, detail = classify_scope_state(snapshot)
    if operation_type == OperationType.ADOPT_LEGACY_SCOPE:
        return _decide_adopt(snapshot, classification, corrupt_code, detail)
    if operation_type == OperationType.PROMOTE_SCOPE:
        return _decide_promote(snapshot, classification, corrupt_code, detail)
    if operation_type == OperationType.REMOVE_SCOPE:
        return _decide_remove(snapshot, classification, corrupt_code, detail)
    raise NativeShortScopeAdministrationTransactionError(
        f"unsupported operation_type={operation_type!r}"
    )


def decide_operation_replay(
    request: NativeShortScopeAdministrationRequest,
    existing: ExistingOperation,
) -> AdministrationDecision:
    """Idempotency decision for an operation UUID that already exists."""
    request_scope = request.scope_key.as_dict()
    if (
        existing.metadata_digest != request.request_digest
        or existing.operation_type != str(request.operation_type)
        or existing.scope_key != request_scope
    ):
        return _reject(
            ScopeClassification.INCOHERENT,
            ResultCode.OPERATION_METADATA_MISMATCH,
            "operation_uuid already exists with different immutable identity",
        )
    if existing.completed_at_utc is None:
        # A committed ledger row is always terminal because the row and its
        # scope mutation commit atomically. A non-terminal committed row means
        # the prior attempt's commit status is unknown; fail closed, retryable.
        return AdministrationDecision(
            action=OperationAction.REJECT,
            result_code=ResultCode.COMMIT_STATUS_UNKNOWN,
            result_class=ResultClass.RETRYABLE,
            support_generation_before=existing.support_generation_before,
            support_generation_after=existing.support_generation_after,
            target_cadence_config_id=None,
            classification=ScopeClassification.INCOHERENT,
            detail="existing operation row is not terminal",
        )
    return AdministrationDecision(
        action=OperationAction.IDEMPOTENT_COMPLETE,
        result_code=ResultCode.OPERATION_ALREADY_COMPLETED,
        result_class=ResultClass.IDEMPOTENT_SUCCESS,
        support_generation_before=existing.support_generation_before,
        support_generation_after=existing.support_generation_after,
        target_cadence_config_id=None,
        classification=ScopeClassification.INCOHERENT,
        detail=f"operation already completed as {existing.result_code}",
    )


# --------------------------------------------------------------------------- #
# Mutations (explicit SQL per branch)                                         #
# --------------------------------------------------------------------------- #


def _insert_operation(
    conn: Any,
    request: NativeShortScopeAdministrationRequest,
    decision: AdministrationDecision,
    *,
    now_utc: datetime,
) -> int:
    prov = request.provenance
    scope = request.scope_key
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO native_short_scope_admin_operation_v1 (
                operation_uuid, operation_type,
                venue, symbol, quote_currency, fib_trading_horizon,
                primary_interval, supporting_interval,
                actor_type, actor_id, trigger_type, request_source, reason,
                requested_at_utc, repository_sha, schema_version,
                metadata_digest, started_at_utc, completed_at_utc,
                result_class, result_code,
                support_generation_before, support_generation_after
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                prov.operation_uuid,
                str(request.operation_type),
                scope.venue,
                scope.symbol,
                scope.quote_currency,
                scope.fib_trading_horizon,
                scope.primary_interval,
                scope.supporting_interval,
                str(prov.actor_type),
                prov.actor_id,
                str(prov.trigger_type),
                prov.request_source,
                prov.reason,
                _naive_utc(prov.requested_at_utc),
                prov.repository_sha,
                prov.schema_version,
                request.request_digest,
                _naive_utc(now_utc),
                _naive_utc(now_utc),
                str(decision.result_class),
                str(decision.result_code),
                decision.support_generation_before,
                decision.support_generation_after,
            ),
        )
        return int(cur.lastrowid)


def _naive_utc(value: datetime) -> datetime:
    """MariaDB DATETIME(6) columns store no timezone; persist canonical UTC as a
    naive value so comparison constraints behave deterministically."""
    if value.tzinfo is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    return value


def _insert_support_event(
    conn: Any,
    request: NativeShortScopeAdministrationRequest,
    *,
    operation_id: int,
    support_generation: int,
    support_state: str,
    reason_code: str,
    now_utc: datetime,
) -> None:
    scope = request.scope_key
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO native_short_scope_support_event_v1 (
                venue, symbol, quote_currency, fib_trading_horizon,
                primary_interval, supporting_interval, scope_support_state,
                scope_admin_operation_id, support_generation, event_ts_utc,
                reason_code, reason_detail, source_name, source_version,
                event_metadata_json
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                scope.venue,
                scope.symbol,
                scope.quote_currency,
                scope.fib_trading_horizon,
                scope.primary_interval,
                scope.supporting_interval,
                support_state,
                operation_id,
                support_generation,
                _naive_utc(now_utc),
                reason_code,
                request.provenance.reason,
                ADMIN_SOURCE_NAME,
                ADMIN_SOURCE_VERSION,
                request.canonical_metadata_json,
            ),
        )


def _insert_scope_supported(
    conn: Any,
    request: NativeShortScopeAdministrationRequest,
    *,
    support_generation: int,
    now_utc: datetime,
) -> None:
    scope = request.scope_key
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO native_short_map_scope_v1 (
                venue, symbol, quote_currency, fib_trading_horizon,
                primary_interval, supporting_interval,
                scope_support_state, scope_reason_code, scope_reason_detail,
                support_generation
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, NULL, NULL, %s)
            """,
            (
                scope.venue,
                scope.symbol,
                scope.quote_currency,
                scope.fib_trading_horizon,
                scope.primary_interval,
                scope.supporting_interval,
                SUPPORTED_STATE,
                support_generation,
            ),
        )


def _update_scope_generation(
    conn: Any, scope_id: int, *, support_generation: int
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE native_short_map_scope_v1
            SET support_generation = %s
            WHERE scope_id = %s AND support_generation IS NULL
            """,
            (support_generation, scope_id),
        )
        if cur.rowcount != 1:
            raise _RevalidationError(
                ResultCode.PARTIAL_SCOPE_STATE,
                "adopt generation update did not affect exactly one legacy row",
            )


def _update_scope_promote(
    conn: Any, scope_id: int, *, support_generation: int
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE native_short_map_scope_v1
            SET scope_support_state = %s,
                scope_reason_code = NULL,
                scope_reason_detail = NULL,
                support_generation = %s
            WHERE scope_id = %s AND scope_support_state = %s
            """,
            (SUPPORTED_STATE, support_generation, scope_id, NOT_APPLICABLE_STATE),
        )
        if cur.rowcount != 1:
            raise _RevalidationError(
                ResultCode.PARTIAL_SCOPE_STATE,
                "promote update did not affect exactly one withdrawn row",
            )


def _update_scope_remove(
    conn: Any, scope_id: int, *, support_generation: int
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE native_short_map_scope_v1
            SET scope_support_state = %s,
                scope_reason_code = %s,
                scope_reason_detail = %s,
                support_generation = %s
            WHERE scope_id = %s AND scope_support_state = %s
            """,
            (
                NOT_APPLICABLE_STATE,
                ADMIN_REMOVAL_REASON_CODE,
                ADMIN_REMOVAL_REASON_DETAIL,
                support_generation,
                scope_id,
                SUPPORTED_STATE,
            ),
        )
        if cur.rowcount != 1:
            raise _RevalidationError(
                ResultCode.PARTIAL_SCOPE_STATE,
                "remove update did not affect exactly one supported row",
            )


def _bind_legacy_cadence(
    conn: Any, cadence_config_id: int, *, operation_id: int, support_generation: int
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE native_short_scope_cadence_config_v1
            SET activation_operation_id = %s,
                support_generation = %s
            WHERE cadence_config_id = %s
              AND is_active = 1
              AND activation_operation_id IS NULL
              AND support_generation IS NULL
            """,
            (operation_id, support_generation, cadence_config_id),
        )
        if cur.rowcount != 1:
            raise _RevalidationError(
                ResultCode.PARTIAL_SCOPE_STATE,
                "legacy cadence bind did not affect exactly one row",
            )


def _insert_active_cadence(
    conn: Any,
    request: NativeShortScopeAdministrationRequest,
    *,
    operation_id: int,
    support_generation: int,
    now_utc: datetime,
) -> None:
    scope = request.scope_key
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO native_short_scope_cadence_config_v1 (
                venue, symbol, quote_currency, fib_trading_horizon,
                primary_interval, supporting_interval,
                cadence_contract_version, target_evaluation_interval,
                primary_source_freshness_limit_seconds,
                supporting_source_freshness_limit_seconds,
                evaluation_grace_seconds, recent_scope_grace_seconds,
                effective_from_utc, effective_to_utc, is_active,
                activation_operation_id, deactivation_operation_id,
                support_generation
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL, 1,
                %s, NULL, %s
            )
            """,
            (
                scope.venue,
                scope.symbol,
                scope.quote_currency,
                scope.fib_trading_horizon,
                scope.primary_interval,
                scope.supporting_interval,
                CANONICAL_CADENCE_CONTRACT_VERSION,
                CANONICAL_TARGET_EVALUATION_INTERVAL,
                CANONICAL_PRIMARY_SOURCE_FRESHNESS_LIMIT_SECONDS,
                CANONICAL_SUPPORTING_SOURCE_FRESHNESS_LIMIT_SECONDS,
                CANONICAL_EVALUATION_GRACE_SECONDS,
                CANONICAL_RECENT_SCOPE_GRACE_SECONDS,
                _naive_utc(now_utc),
                operation_id,
                support_generation,
            ),
        )


def _deactivate_cadence(
    conn: Any, cadence_config_id: int, *, operation_id: int, now_utc: datetime
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE native_short_scope_cadence_config_v1
            SET is_active = 0,
                deactivation_operation_id = %s,
                effective_to_utc = %s
            WHERE cadence_config_id = %s
              AND is_active = 1
              AND activation_operation_id IS NOT NULL
              AND deactivation_operation_id IS NULL
            """,
            (operation_id, _naive_utc(now_utc), cadence_config_id),
        )
        if cur.rowcount != 1:
            raise _RevalidationError(
                ResultCode.AUTHORITATIVE_WITHDRAWAL_STATE_INCOHERENT,
                "cadence deactivation did not affect exactly one managed active row",
            )


def _clear_derived_projections(conn: Any, scope_key: Mapping[str, str]) -> int:
    """Narrow deterministic cleanup of current derived projections that would be
    falsely actionable after withdrawal. Immutable history is never deleted."""
    params = _scope_key_params(scope_key)
    deleted = 0
    for table in (
        "native_short_scope_status_v1",
        "native_short_map_level_status_v1",
    ):
        with conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {table} WHERE {_SCOPE_KEY_WHERE}", params
            )
            deleted += int(cur.rowcount)
    return deleted


# --------------------------------------------------------------------------- #
# Apply + revalidation                                                        #
# --------------------------------------------------------------------------- #


def _apply_decision(
    conn: Any,
    request: NativeShortScopeAdministrationRequest,
    decision: AdministrationDecision,
    snapshot: ScopeStateSnapshot,
    *,
    now_utc: datetime,
) -> int | None:
    """Execute the concrete mutation branch. Returns the new operation id when a
    ledger row was written, else None."""
    action = decision.action

    if action == OperationAction.CLEAR_RESIDUE:
        _clear_derived_projections(conn, request.scope_key.as_dict())
        return None

    if action not in _PERSISTING_ACTIONS:
        return None

    generation_after = decision.support_generation_after
    assert generation_after is not None
    operation_id = _insert_operation(conn, request, decision, now_utc=now_utc)

    if action == OperationAction.ADOPT:
        _update_scope_generation(
            conn, _require_scope_id(snapshot), support_generation=generation_after
        )
        _bind_legacy_cadence(
            conn,
            _require_cadence_id(decision),
            operation_id=operation_id,
            support_generation=generation_after,
        )
        _insert_support_event(
            conn,
            request,
            operation_id=operation_id,
            support_generation=generation_after,
            support_state=SUPPORTED_STATE,
            reason_code=_SUPPORT_EVENT_REASON_CODE["ADOPT"],
            now_utc=now_utc,
        )
    elif action == OperationAction.PROMOTE_NEW:
        _insert_scope_supported(
            conn, request, support_generation=generation_after, now_utc=now_utc
        )
        _insert_active_cadence(
            conn,
            request,
            operation_id=operation_id,
            support_generation=generation_after,
            now_utc=now_utc,
        )
        _insert_support_event(
            conn,
            request,
            operation_id=operation_id,
            support_generation=generation_after,
            support_state=SUPPORTED_STATE,
            reason_code=_SUPPORT_EVENT_REASON_CODE["PROMOTE_NEW"],
            now_utc=now_utc,
        )
    elif action == OperationAction.PROMOTE_REACTIVATE:
        _update_scope_promote(
            conn, _require_scope_id(snapshot), support_generation=generation_after
        )
        _insert_active_cadence(
            conn,
            request,
            operation_id=operation_id,
            support_generation=generation_after,
            now_utc=now_utc,
        )
        _insert_support_event(
            conn,
            request,
            operation_id=operation_id,
            support_generation=generation_after,
            support_state=SUPPORTED_STATE,
            reason_code=_SUPPORT_EVENT_REASON_CODE["PROMOTE_REACTIVATE"],
            now_utc=now_utc,
        )
    elif action == OperationAction.REMOVE:
        _update_scope_remove(
            conn, _require_scope_id(snapshot), support_generation=generation_after
        )
        _deactivate_cadence(
            conn,
            _require_cadence_id(decision),
            operation_id=operation_id,
            now_utc=now_utc,
        )
        _insert_support_event(
            conn,
            request,
            operation_id=operation_id,
            support_generation=generation_after,
            support_state=NOT_APPLICABLE_STATE,
            reason_code=_SUPPORT_EVENT_REASON_CODE["REMOVE"],
            now_utc=now_utc,
        )
        _clear_derived_projections(conn, request.scope_key.as_dict())

    return operation_id


def _require_scope_id(snapshot: ScopeStateSnapshot) -> int:
    if snapshot.scope_id is None:
        raise _RevalidationError(
            ResultCode.PARTIAL_SCOPE_STATE, "expected an existing scope row"
        )
    return snapshot.scope_id


def _require_cadence_id(decision: AdministrationDecision) -> int:
    if decision.target_cadence_config_id is None:
        raise _RevalidationError(
            ResultCode.PARTIAL_SCOPE_STATE, "expected a target cadence row"
        )
    return decision.target_cadence_config_id


def _revalidate_post_state(
    conn: Any,
    request: NativeShortScopeAdministrationRequest,
    decision: AdministrationDecision,
    *,
    operation_id: int,
) -> None:
    """Immediately-before-commit revalidation of all invariants for a persisting
    action, re-reading the mutated state under the same locked transaction."""
    scope_key = request.scope_key.as_dict()
    post = read_scope_state_snapshot(conn, scope_key, for_update=True)

    if not post.scope_present:
        raise _RevalidationError(
            ResultCode.PARTIAL_SCOPE_STATE, "scope row missing after mutation"
        )
    if post.support_generation != decision.support_generation_after:
        raise _RevalidationError(
            ResultCode.SUPPORT_GENERATION_MISMATCH,
            f"post generation {post.support_generation} != "
            f"{decision.support_generation_after}",
        )

    if decision.action == OperationAction.REMOVE:
        expected_state = NOT_APPLICABLE_STATE
        expected_active = 0
    else:
        expected_state = SUPPORTED_STATE
        expected_active = 1

    if post.scope_support_state != expected_state:
        raise _RevalidationError(
            ResultCode.PARTIAL_SCOPE_STATE,
            f"post support state {post.scope_support_state} != {expected_state}",
        )
    active = post.active_cadence_rows
    if len(active) != expected_active:
        code = (
            ResultCode.MULTIPLE_ACTIVE_CADENCE_ROWS
            if len(active) > 1
            else ResultCode.PARTIAL_SCOPE_STATE
        )
        raise _RevalidationError(
            code, f"post active cadence count {len(active)} != {expected_active}"
        )
    if _effective_windows_overlap(post.cadence_rows):
        raise _RevalidationError(
            ResultCode.AUTHORITATIVE_WITHDRAWAL_STATE_INCOHERENT,
            "post cadence effective windows overlap",
        )

    generation_after = decision.support_generation_after
    assert generation_after is not None
    if post.attributable_support_generations.count(generation_after) != 1:
        raise _RevalidationError(
            ResultCode.SUPPORT_GENERATION_MISMATCH,
            "expected exactly one attributable support event for the new generation",
        )
    if len(post.attributable_support_generations) != len(
        set(post.attributable_support_generations)
    ):
        raise _RevalidationError(
            ResultCode.SUPPORT_GENERATION_MISMATCH,
            "duplicate attributable support generation detected",
        )

    # The persisted operation must exist, be terminal, and be bound to this exact
    # scope (no cross-scope attribution).
    existing = read_existing_operation(
        conn, request.provenance.operation_uuid, for_update=True
    )
    if existing is None or existing.scope_admin_operation_id != operation_id:
        raise _RevalidationError(
            ResultCode.COMMIT_STATUS_UNKNOWN, "operation ledger row not found"
        )
    if existing.metadata_digest != request.request_digest:
        raise _RevalidationError(
            ResultCode.OPERATION_METADATA_MISMATCH, "operation digest changed"
        )
    if existing.scope_key != scope_key:
        raise _RevalidationError(
            ResultCode.COMMIT_STATUS_UNKNOWN, "operation bound to a different scope"
        )
    if existing.completed_at_utc is None:
        raise _RevalidationError(
            ResultCode.COMMIT_STATUS_UNKNOWN, "operation ledger row not terminal"
        )


# --------------------------------------------------------------------------- #
# Orchestration                                                               #
# --------------------------------------------------------------------------- #


def _build_result(decision: AdministrationDecision) -> NativeShortScopeAdministrationResult:
    return NativeShortScopeAdministrationResult(
        result_class=decision.result_class,
        result_code=decision.result_code,
        support_generation_before=decision.support_generation_before,
        support_generation_after=decision.support_generation_after,
    )


def plan_scope_administration(
    conn: Any,
    request: NativeShortScopeAdministrationRequest,
) -> AdministrationTransactionOutcome:
    """Read-only dry run: compute the planned transition and expected result
    without any persistent write, lock acquisition, or operation ledger row.

    Fails closed on the same incoherent states as write mode."""
    scope_key = request.scope_key.as_dict()
    lock_name = advisory_lock_name(scope_key)

    existing = read_existing_operation(
        conn, request.provenance.operation_uuid, for_update=False
    )
    if existing is not None:
        decision = decide_operation_replay(request, existing)
        snapshot = read_scope_state_snapshot(conn, scope_key, for_update=False)
    else:
        try:
            snapshot = read_scope_state_snapshot(conn, scope_key, for_update=False)
        except _RevalidationError as exc:
            snapshot = None  # type: ignore[assignment]
            decision = _reject(
                ScopeClassification.INCOHERENT, exc.result_code, exc.detail
            )
        else:
            decision = decide_administration(request.operation_type, snapshot)

    current_state = snapshot.summary() if snapshot is not None else {
        "scope_present": None,
        "unreadable_state": True,
    }
    return AdministrationTransactionOutcome(
        mode=TransactionMode.DRY_RUN,
        write=False,
        persisted=False,
        operation_type=str(request.operation_type),
        operation_uuid=request.provenance.operation_uuid,
        request_digest=request.request_digest,
        scope_key=scope_key,
        action=decision.action,
        result=_build_result(decision),
        scope_admin_operation_id=(
            existing.scope_admin_operation_id if existing is not None else None
        ),
        advisory_lock_name=lock_name,
        current_state=current_state,
        detail=decision.detail,
    )


def execute_scope_administration(
    conn: Any,
    request: NativeShortScopeAdministrationRequest,
    *,
    authorization: Any,
    now_utc: datetime | None = None,
) -> AdministrationTransactionOutcome:
    """Write mode: one bounded transaction under a deterministic advisory lock
    plus row locks. Commits terminal operation state and scope mutation
    atomically, or fails closed with a typed result code and no partial state.

    ``authorization`` must be a validated writer mutation authorization for the
    ``native_short_4h_chain`` capability; it is required before any mutation."""
    from src.operations.writer_capability_authorization_v1 import (
        require_writer_mutation_authorization,
    )

    # Fail closed before any lock or mutation if authorization is absent/invalid.
    require_writer_mutation_authorization(authorization, WRITER_CAPABILITY_ID)

    now = now_utc or datetime.now(UTC)
    scope_key = request.scope_key.as_dict()
    lock_name = advisory_lock_name(scope_key)

    conn.begin()
    lock_held = False
    try:
        _acquire_advisory_lock(conn, lock_name)
        lock_held = True

        existing = read_existing_operation(
            conn, request.provenance.operation_uuid, for_update=True
        )
        if existing is not None:
            decision = decide_operation_replay(request, existing)
            snapshot = read_scope_state_snapshot(conn, scope_key, for_update=True)
            conn.rollback()
            return _outcome(
                request,
                decision,
                snapshot,
                lock_name=lock_name,
                persisted=False,
                scope_admin_operation_id=existing.scope_admin_operation_id,
            )

        snapshot = read_scope_state_snapshot(conn, scope_key, for_update=True)
        decision = decide_administration(request.operation_type, snapshot)

        if decision.action == OperationAction.CLEAR_RESIDUE:
            _apply_decision(conn, request, decision, snapshot, now_utc=now)
            conn.commit()
            return _outcome(
                request,
                decision,
                snapshot,
                lock_name=lock_name,
                persisted=True,
                scope_admin_operation_id=None,
            )

        if not decision.persists_operation:
            # Idempotent no-op, conflict, blocked, or corrupt: never persist.
            conn.rollback()
            return _outcome(
                request,
                decision,
                snapshot,
                lock_name=lock_name,
                persisted=False,
                scope_admin_operation_id=None,
            )

        operation_id = _apply_decision(
            conn, request, decision, snapshot, now_utc=now
        )
        assert operation_id is not None
        _revalidate_post_state(conn, request, decision, operation_id=operation_id)
        conn.commit()
        return _outcome(
            request,
            decision,
            snapshot,
            lock_name=lock_name,
            persisted=True,
            scope_admin_operation_id=operation_id,
        )
    except _RetryableResult as exc:
        conn.rollback()
        decision = _reject(
            ScopeClassification.INCOHERENT, exc.result_code, "lock unavailable"
        )
        return _outcome(
            request,
            decision,
            None,
            lock_name=lock_name,
            persisted=False,
            scope_admin_operation_id=None,
        )
    except _RevalidationError as exc:
        conn.rollback()
        decision = _reject(
            ScopeClassification.INCOHERENT, exc.result_code, exc.detail
        )
        return _outcome(
            request,
            decision,
            None,
            lock_name=lock_name,
            persisted=False,
            scope_admin_operation_id=None,
        )
    except Exception as exc:  # noqa: BLE001 - map DB locking errors to typed codes.
        conn.rollback()
        mapped = _map_operational_error(exc)
        if mapped is None:
            raise
        decision = _reject(
            ScopeClassification.INCOHERENT, mapped, "database locking condition"
        )
        return _outcome(
            request,
            decision,
            None,
            lock_name=lock_name,
            persisted=False,
            scope_admin_operation_id=None,
        )
    finally:
        if lock_held:
            _release_advisory_lock(conn, lock_name)


def _map_operational_error(exc: Exception) -> ResultCode | None:
    """Map only recognized MariaDB deadlock/lock-timeout conditions to typed
    RETRYABLE codes. Any other exception returns None so genuine defects
    propagate instead of being silently swallowed."""
    args = getattr(exc, "args", None)
    code = args[0] if args and isinstance(args[0], int) else None
    if code == _ER_LOCK_DEADLOCK:
        return ResultCode.DEADLOCK
    if code == _ER_LOCK_WAIT_TIMEOUT:
        return ResultCode.LOCK_TIMEOUT
    return None


def _outcome(
    request: NativeShortScopeAdministrationRequest,
    decision: AdministrationDecision,
    snapshot: ScopeStateSnapshot | None,
    *,
    lock_name: str,
    persisted: bool,
    scope_admin_operation_id: int | None,
) -> AdministrationTransactionOutcome:
    current_state = (
        snapshot.summary()
        if snapshot is not None
        else {"scope_present": None, "state_unread": True}
    )
    return AdministrationTransactionOutcome(
        mode=TransactionMode.WRITE,
        write=True,
        persisted=persisted,
        operation_type=str(request.operation_type),
        operation_uuid=request.provenance.operation_uuid,
        request_digest=request.request_digest,
        scope_key=request.scope_key.as_dict(),
        action=decision.action,
        result=_build_result(decision),
        scope_admin_operation_id=scope_admin_operation_id,
        advisory_lock_name=lock_name,
        current_state=current_state,
        detail=decision.detail,
    )


__all__ = [
    "ADMIN_REMOVAL_REASON_CODE",
    "AdministrationDecision",
    "AdministrationTransactionOutcome",
    "CANONICAL_CADENCE_CONTRACT_VERSION",
    "CadenceRowState",
    "ExistingOperation",
    "NativeShortScopeAdministrationTransactionError",
    "OperationAction",
    "ScopeClassification",
    "ScopeStateSnapshot",
    "TransactionMode",
    "WRITER_CAPABILITY_ID",
    "advisory_lock_name",
    "classify_scope_state",
    "decide_administration",
    "decide_operation_replay",
    "execute_scope_administration",
    "plan_scope_administration",
    "read_existing_operation",
    "read_scope_state_snapshot",
]
