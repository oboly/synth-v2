from __future__ import annotations

import ast
import copy
import json
import os
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

import pytest

from src.market_data.native_short_scope_administration_v1 import (
    NativeShortScopeAdministrationActorType,
    NativeShortScopeAdministrationKey,
    NativeShortScopeAdministrationOperationType as OperationType,
    NativeShortScopeAdministrationProvenance,
    NativeShortScopeAdministrationRequest,
    NativeShortScopeAdministrationResultCode as ResultCode,
    NativeShortScopeAdministrationTriggerType,
)
from src.market_data import (
    native_short_scope_administration_transaction_v1 as txn,
)
from src.market_data.native_short_scope_administration_transaction_v1 import (
    CANONICAL_CADENCE_CONTRACT_VERSION,
    CANONICAL_EVALUATION_GRACE_SECONDS,
    CANONICAL_PRIMARY_SOURCE_FRESHNESS_LIMIT_SECONDS,
    CANONICAL_RECENT_SCOPE_GRACE_SECONDS,
    CANONICAL_SUPPORTING_SOURCE_FRESHNESS_LIMIT_SECONDS,
    CANONICAL_TARGET_EVALUATION_INTERVAL,
    CadenceRowState,
    ExistingOperation,
    OperationAction,
    ScopeStateSnapshot,
    advisory_lock_name,
    classify_scope_state,
    decide_administration,
    decide_operation_replay,
    execute_scope_administration,
    plan_scope_administration,
)


# --------------------------------------------------------------------------- #
# Shared request/snapshot builders                                            #
# --------------------------------------------------------------------------- #


def _key(symbol: str = "BTC") -> NativeShortScopeAdministrationKey:
    return NativeShortScopeAdministrationKey(
        venue="bitvavo",
        symbol=symbol,
        quote_currency="EUR",
        fib_trading_horizon="SHORT",
        primary_interval="4h",
        supporting_interval="1h",
    )


def _provenance(**changes: Any) -> NativeShortScopeAdministrationProvenance:
    values: dict[str, Any] = {
        "operation_uuid": "00000000-0000-4000-8000-000000000001",
        "actor_type": NativeShortScopeAdministrationActorType.TEST,
        "actor_id": "admin-txn-test",
        "trigger_type": NativeShortScopeAdministrationTriggerType.TEST,
        "request_source": "tests/test_native_short_scope_administration_transaction_v1.py",
        "reason": "explicit test provenance",
        "requested_at_utc": datetime(2026, 7, 18, 10, 0, tzinfo=UTC),
        "repository_sha": "0" * 40,
        "schema_version": "native_short_scope_administration_v1",
    }
    values.update(changes)
    return NativeShortScopeAdministrationProvenance(**values)


def _request(
    operation: OperationType = OperationType.PROMOTE_SCOPE,
    *,
    symbol: str = "BTC",
    provenance: NativeShortScopeAdministrationProvenance | None = None,
    metadata: dict[str, Any] | None = None,
) -> NativeShortScopeAdministrationRequest:
    return NativeShortScopeAdministrationRequest(
        operation_type=operation,
        scope_key=_key(symbol),
        provenance=provenance or _provenance(),
        canonical_metadata=metadata or {"ticket": "scope-1"},
    )


def _cadence(
    *,
    cadence_config_id: int = 10,
    is_active: int = 1,
    activation_op: int | None = None,
    deactivation_op: int | None = None,
    support_generation: int | None = None,
    version: str = CANONICAL_CADENCE_CONTRACT_VERSION,
    effective_from: datetime = datetime(2026, 7, 1, 0, 0),
    effective_to: datetime | None = None,
    canonical_profile: bool = True,
) -> CadenceRowState:
    return CadenceRowState(
        cadence_config_id=cadence_config_id,
        cadence_contract_version=version,
        is_active=is_active,
        effective_from_utc=effective_from,
        effective_to_utc=effective_to,
        activation_operation_id=activation_op,
        deactivation_operation_id=deactivation_op,
        support_generation=support_generation,
        target_evaluation_interval=CANONICAL_TARGET_EVALUATION_INTERVAL,
        primary_source_freshness_limit_seconds=(
            CANONICAL_PRIMARY_SOURCE_FRESHNESS_LIMIT_SECONDS
            if canonical_profile
            else 111
        ),
        supporting_source_freshness_limit_seconds=(
            CANONICAL_SUPPORTING_SOURCE_FRESHNESS_LIMIT_SECONDS
        ),
        evaluation_grace_seconds=CANONICAL_EVALUATION_GRACE_SECONDS,
        recent_scope_grace_seconds=CANONICAL_RECENT_SCOPE_GRACE_SECONDS,
    )


def _snapshot(
    *,
    scope_present: bool = True,
    scope_id: int | None = 1,
    state: str | None = "SUPPORTED",
    generation: int | None = None,
    cadence_rows: tuple[CadenceRowState, ...] = (),
    attributable: tuple[int, ...] = (),
    legacy_support: int = 0,
    status_residue: int = 0,
    level_residue: int = 0,
    reason_code: str | None = None,
) -> ScopeStateSnapshot:
    return ScopeStateSnapshot(
        scope_present=scope_present,
        scope_id=scope_id if scope_present else None,
        scope_support_state=state if scope_present else None,
        support_generation=generation if scope_present else None,
        scope_reason_code=reason_code,
        scope_reason_detail=None,
        cadence_rows=cadence_rows,
        attributable_support_generations=attributable,
        legacy_support_event_count=legacy_support,
        scope_status_residue_count=status_residue,
        map_level_status_residue_count=level_residue,
    )


# --------------------------------------------------------------------------- #
# Pure decision tests                                                         #
# --------------------------------------------------------------------------- #


def test_advisory_lock_name_is_deterministic_and_bounded() -> None:
    key = _key().as_dict()
    name = advisory_lock_name(key)
    assert name == advisory_lock_name(dict(key))
    assert name != advisory_lock_name(_key("ETH").as_dict())
    assert len(name) <= 64


def test_promote_new_scope_from_empty() -> None:
    snap = _snapshot(scope_present=False, scope_id=None)
    decision = decide_administration(OperationType.PROMOTE_SCOPE, snap)
    assert decision.action == OperationAction.PROMOTE_NEW
    assert decision.result_code == ResultCode.PROMOTED_NEW_SCOPE
    assert decision.support_generation_before is None
    assert decision.support_generation_after == 1
    assert decision.persists_operation


def test_adopt_coherent_legacy_scope() -> None:
    snap = _snapshot(generation=None, cadence_rows=(_cadence(),), legacy_support=1)
    decision = decide_administration(OperationType.ADOPT_LEGACY_SCOPE, snap)
    assert decision.action == OperationAction.ADOPT
    assert decision.result_code == ResultCode.ADOPTED_LEGACY_SCOPE
    assert decision.support_generation_after == 1
    assert decision.target_cadence_config_id == 10


def test_adopt_rejects_multiple_active_cadence_rows() -> None:
    snap = _snapshot(
        generation=None,
        cadence_rows=(
            _cadence(cadence_config_id=10),
            _cadence(cadence_config_id=11, effective_from=datetime(2026, 7, 5)),
        ),
    )
    decision = decide_administration(OperationType.ADOPT_LEGACY_SCOPE, snap)
    assert decision.action == OperationAction.REJECT
    assert decision.result_code == ResultCode.MULTIPLE_ACTIVE_CADENCE_ROWS


def test_adopt_rejects_noncanonical_cadence_profile() -> None:
    snap = _snapshot(
        generation=None, cadence_rows=(_cadence(canonical_profile=False),)
    )
    decision = decide_administration(OperationType.ADOPT_LEGACY_SCOPE, snap)
    assert decision.result_code == ResultCode.CADENCE_PROFILE_CONFLICT


def test_adopt_rejects_partial_administration_state() -> None:
    snap = _snapshot(
        generation=None,
        cadence_rows=(_cadence(),),
        attributable=(1,),
    )
    decision = decide_administration(OperationType.ADOPT_LEGACY_SCOPE, snap)
    assert decision.result_code == ResultCode.PARTIAL_SCOPE_STATE


def test_adopt_already_managed_is_idempotent() -> None:
    snap = _snapshot(
        generation=3,
        cadence_rows=(_cadence(activation_op=5, support_generation=3),),
        attributable=(3,),
    )
    decision = decide_administration(OperationType.ADOPT_LEGACY_SCOPE, snap)
    assert decision.action == OperationAction.NOOP
    assert decision.result_code == ResultCode.SCOPE_ALREADY_ADOPTED


def test_managed_removal() -> None:
    snap = _snapshot(
        generation=3,
        cadence_rows=(_cadence(activation_op=5, support_generation=3),),
        attributable=(3,),
        status_residue=1,
    )
    decision = decide_administration(OperationType.REMOVE_SCOPE, snap)
    assert decision.action == OperationAction.REMOVE
    assert decision.result_code == ResultCode.REMOVED_SCOPE
    assert decision.support_generation_before == 3
    assert decision.support_generation_after == 4
    assert decision.target_cadence_config_id == 10


def test_repeat_removal_is_idempotent_without_residue() -> None:
    snap = _snapshot(state="NOT_APPLICABLE", generation=4, cadence_rows=())
    decision = decide_administration(OperationType.REMOVE_SCOPE, snap)
    assert decision.action == OperationAction.NOOP
    assert decision.result_code == ResultCode.SCOPE_ALREADY_REMOVED


def test_repeat_removal_clears_derived_residue() -> None:
    snap = _snapshot(
        state="NOT_APPLICABLE", generation=4, cadence_rows=(), level_residue=2
    )
    decision = decide_administration(OperationType.REMOVE_SCOPE, snap)
    assert decision.action == OperationAction.CLEAR_RESIDUE
    assert decision.result_code == ResultCode.ALREADY_REMOVED_DERIVED_RESIDUE_CLEARED
    assert not decision.persists_operation


def test_re_promotion_after_removal() -> None:
    snap = _snapshot(state="NOT_APPLICABLE", generation=4, cadence_rows=())
    decision = decide_administration(OperationType.PROMOTE_SCOPE, snap)
    assert decision.action == OperationAction.PROMOTE_REACTIVATE
    assert decision.result_code == ResultCode.PROMOTED_FROM_PRIOR_WITHDRAWAL
    assert decision.support_generation_before == 4
    assert decision.support_generation_after == 5


def test_already_supported_is_idempotent() -> None:
    snap = _snapshot(
        generation=1,
        cadence_rows=(_cadence(activation_op=1, support_generation=1),),
        attributable=(1,),
    )
    decision = decide_administration(OperationType.PROMOTE_SCOPE, snap)
    assert decision.action == OperationAction.NOOP
    assert decision.result_code == ResultCode.SCOPE_ALREADY_SUPPORTED


def test_promote_legacy_requires_adoption() -> None:
    snap = _snapshot(generation=None, cadence_rows=(_cadence(),))
    decision = decide_administration(OperationType.PROMOTE_SCOPE, snap)
    assert decision.result_code == ResultCode.LEGACY_SCOPE_REQUIRES_ADOPTION


def test_remove_legacy_requires_adoption() -> None:
    snap = _snapshot(generation=None, cadence_rows=(_cadence(),))
    decision = decide_administration(OperationType.REMOVE_SCOPE, snap)
    assert decision.result_code == ResultCode.LEGACY_SCOPE_REQUIRES_ADOPTION


def test_managed_supported_multiple_active_cadence_is_corrupt() -> None:
    snap = _snapshot(
        generation=1,
        cadence_rows=(
            _cadence(cadence_config_id=10, activation_op=1, support_generation=1),
            _cadence(
                cadence_config_id=11,
                activation_op=2,
                support_generation=1,
                effective_from=datetime(2026, 7, 9),
            ),
        ),
        attributable=(1,),
    )
    decision = decide_administration(OperationType.PROMOTE_SCOPE, snap)
    assert decision.result_code == ResultCode.MULTIPLE_ACTIVE_CADENCE_ROWS


def test_support_generation_mismatch_is_corrupt() -> None:
    snap = _snapshot(
        generation=5,
        cadence_rows=(_cadence(activation_op=1, support_generation=5),),
        attributable=(1,),
    )
    decision = decide_administration(OperationType.REMOVE_SCOPE, snap)
    assert decision.result_code == ResultCode.SUPPORT_GENERATION_MISMATCH


def test_partial_scope_state_cadence_without_scope() -> None:
    snap = _snapshot(scope_present=False, scope_id=None, cadence_rows=(_cadence(),))
    decision = decide_administration(OperationType.PROMOTE_SCOPE, snap)
    assert decision.result_code == ResultCode.PARTIAL_SCOPE_STATE


def test_withdrawal_state_incoherent_active_cadence_when_removed() -> None:
    snap = _snapshot(
        state="NOT_APPLICABLE",
        generation=4,
        cadence_rows=(_cadence(activation_op=5, support_generation=3),),
    )
    decision = decide_administration(OperationType.PROMOTE_SCOPE, snap)
    assert decision.result_code == ResultCode.AUTHORITATIVE_WITHDRAWAL_STATE_INCOHERENT


def test_overlapping_effective_windows_is_incoherent() -> None:
    snap = _snapshot(
        generation=None,
        cadence_rows=(
            _cadence(
                cadence_config_id=10,
                is_active=0,
                effective_from=datetime(2026, 7, 1),
                effective_to=datetime(2026, 7, 10),
            ),
            _cadence(
                cadence_config_id=11,
                is_active=1,
                effective_from=datetime(2026, 7, 5),
                effective_to=None,
            ),
        ),
    )
    _, code, _ = classify_scope_state(snap)
    assert code == ResultCode.LEGACY_STATE_INCOHERENT


# --------------------------------------------------------------------------- #
# Operation-ledger replay (idempotency)                                       #
# --------------------------------------------------------------------------- #


def _existing_operation(
    request: NativeShortScopeAdministrationRequest,
    *,
    completed: bool = True,
    digest: str | None = None,
) -> ExistingOperation:
    return ExistingOperation(
        scope_admin_operation_id=77,
        operation_type=str(request.operation_type),
        metadata_digest=digest or request.request_digest,
        completed_at_utc=datetime(2026, 7, 18, 10, 0) if completed else None,
        result_class="SUCCESS",
        result_code="PROMOTED_NEW_SCOPE",
        support_generation_before=None,
        support_generation_after=1,
        scope_key=request.scope_key.as_dict(),
    )


def test_operation_replay_identical_digest_is_idempotent_success() -> None:
    request = _request()
    decision = decide_operation_replay(request, _existing_operation(request))
    assert decision.action == OperationAction.IDEMPOTENT_COMPLETE
    assert decision.result_code == ResultCode.OPERATION_ALREADY_COMPLETED
    assert decision.support_generation_after == 1


def test_operation_replay_changed_digest_is_metadata_mismatch() -> None:
    request = _request()
    decision = decide_operation_replay(
        request, _existing_operation(request, digest="f" * 64)
    )
    assert decision.result_code == ResultCode.OPERATION_METADATA_MISMATCH


def test_operation_replay_non_terminal_is_commit_status_unknown() -> None:
    request = _request()
    decision = decide_operation_replay(
        request, _existing_operation(request, completed=False)
    )
    assert decision.result_code == ResultCode.COMMIT_STATUS_UNKNOWN


# --------------------------------------------------------------------------- #
# Stateful fake connection for write-mode mechanics                           #
# --------------------------------------------------------------------------- #


_PROFILE_DEFAULTS = {
    "target_evaluation_interval": CANONICAL_TARGET_EVALUATION_INTERVAL,
    "primary_source_freshness_limit_seconds": (
        CANONICAL_PRIMARY_SOURCE_FRESHNESS_LIMIT_SECONDS
    ),
    "supporting_source_freshness_limit_seconds": (
        CANONICAL_SUPPORTING_SOURCE_FRESHNESS_LIMIT_SECONDS
    ),
    "evaluation_grace_seconds": CANONICAL_EVALUATION_GRACE_SECONDS,
    "recent_scope_grace_seconds": CANONICAL_RECENT_SCOPE_GRACE_SECONDS,
}


class _FakeState:
    def __init__(self) -> None:
        self.scopes: list[dict[str, Any]] = []
        self.cadence: list[dict[str, Any]] = []
        self.support: list[dict[str, Any]] = []
        self.operations: list[dict[str, Any]] = []
        self.scope_status: list[dict[str, Any]] = []
        self.map_level_status: list[dict[str, Any]] = []
        self.next_scope_id = 1
        self.next_cadence_id = 100
        self.next_support_id = 1000
        self.next_operation_id = 5000


_SHARED_LOCKS: set[str] = set()


class _FakeCursor:
    def __init__(self, conn: "_FakeConn") -> None:
        self._conn = conn
        self._rows: list[dict[str, Any]] = []
        self.rowcount = 0
        self.lastrowid = 0

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *args: Any) -> bool:
        return False

    def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self._rows)

    def execute(self, sql: str, params: Any = None) -> None:
        params = tuple(params or ())
        norm = " ".join(sql.split())
        state = self._conn.state
        self._conn.executions.append(norm)

        if norm.startswith("SELECT GET_LOCK"):
            name = params[0]
            if name in _SHARED_LOCKS:
                self._rows = [{"acquired": 0}]
            else:
                _SHARED_LOCKS.add(name)
                self._conn.held_locks.add(name)
                self._rows = [{"acquired": 1}]
            return
        if norm.startswith("SELECT RELEASE_LOCK"):
            name = params[0]
            _SHARED_LOCKS.discard(name)
            self._conn.held_locks.discard(name)
            self._rows = [{"released": 1}]
            return

        if "FROM native_short_scope_admin_operation_v1" in norm and norm.startswith(
            "SELECT"
        ):
            uuid_val = params[0]
            self._rows = [
                dict(op) for op in state.operations if op["operation_uuid"] == uuid_val
            ]
            return
        if norm.startswith("INSERT INTO native_short_scope_admin_operation_v1"):
            self._insert_operation(params, state)
            return

        if "FROM native_short_map_scope_v1" in norm and norm.startswith("SELECT"):
            self._rows = _match_scope(state.scopes, params[:6])
            return
        if norm.startswith("INSERT INTO native_short_map_scope_v1"):
            self._insert_scope(params, state)
            return
        if norm.startswith("UPDATE native_short_map_scope_v1"):
            self._update_scope(norm, params, state)
            return

        if (
            "FROM native_short_scope_cadence_config_v1" in norm
            and norm.startswith("SELECT")
        ):
            self._rows = _match_scope(state.cadence, params[:6])
            return
        if norm.startswith("INSERT INTO native_short_scope_cadence_config_v1"):
            self._insert_cadence(params, state)
            return
        if norm.startswith("UPDATE native_short_scope_cadence_config_v1"):
            self._update_cadence(norm, params, state)
            return

        if (
            "FROM native_short_scope_support_event_v1" in norm
            and norm.startswith("SELECT")
        ):
            self._rows = _match_scope(state.support, params[:6])
            return
        if norm.startswith("INSERT INTO native_short_scope_support_event_v1"):
            self._insert_support(params, state)
            return

        if "COUNT(*) AS n FROM native_short_scope_status_v1" in norm:
            self._rows = [{"n": len(_match_scope(state.scope_status, params[:6]))}]
            return
        if "COUNT(*) AS n FROM native_short_map_level_status_v1" in norm:
            self._rows = [
                {"n": len(_match_scope(state.map_level_status, params[:6]))}
            ]
            return
        if norm.startswith("DELETE FROM native_short_scope_status_v1"):
            self._delete_scope(state.scope_status, params[:6])
            return
        if norm.startswith("DELETE FROM native_short_map_level_status_v1"):
            self._delete_scope(state.map_level_status, params[:6])
            return

        raise AssertionError(f"Unexpected SQL: {norm}")

    def _insert_operation(self, params: tuple, state: _FakeState) -> None:
        if self._conn.fail_on == "operation":
            raise RuntimeError("injected operation insert failure")
        for op in state.operations:
            if op["operation_uuid"] == params[0]:
                raise _fake_integrity("duplicate operation_uuid")
        op_id = state.next_operation_id
        state.next_operation_id += 1
        state.operations.append(
            {
                "scope_admin_operation_id": op_id,
                "operation_uuid": params[0],
                "operation_type": params[1],
                "venue": params[2],
                "symbol": params[3],
                "quote_currency": params[4],
                "fib_trading_horizon": params[5],
                "primary_interval": params[6],
                "supporting_interval": params[7],
                "metadata_digest": params[16],
                "completed_at_utc": params[18],
                "result_class": params[19],
                "result_code": params[20],
                "support_generation_before": params[21],
                "support_generation_after": params[22],
            }
        )
        self.lastrowid = op_id

    def _insert_scope(self, params: tuple, state: _FakeState) -> None:
        if self._conn.fail_on == "scope":
            raise RuntimeError("injected scope insert failure")
        scope_id = state.next_scope_id
        state.next_scope_id += 1
        state.scopes.append(
            {
                "scope_id": scope_id,
                "venue": params[0],
                "symbol": params[1],
                "quote_currency": params[2],
                "fib_trading_horizon": params[3],
                "primary_interval": params[4],
                "supporting_interval": params[5],
                "scope_support_state": params[6],
                "scope_reason_code": None,
                "scope_reason_detail": None,
                "support_generation": params[7],
            }
        )
        self.lastrowid = scope_id

    def _update_scope(self, norm: str, params: tuple, state: _FakeState) -> None:
        affected = 0
        if "scope_reason_code = %s" in norm:  # remove
            state_val, reason_code, reason_detail, generation, scope_id, expected = (
                params
            )
            for row in state.scopes:
                if (
                    row["scope_id"] == scope_id
                    and row["scope_support_state"] == expected
                ):
                    row.update(
                        scope_support_state=state_val,
                        scope_reason_code=reason_code,
                        scope_reason_detail=reason_detail,
                        support_generation=generation,
                    )
                    affected += 1
        elif "scope_reason_code = NULL" in norm:  # promote reactivate
            state_val, generation, scope_id, expected = params
            for row in state.scopes:
                if (
                    row["scope_id"] == scope_id
                    and row["scope_support_state"] == expected
                ):
                    row.update(
                        scope_support_state=state_val,
                        scope_reason_code=None,
                        scope_reason_detail=None,
                        support_generation=generation,
                    )
                    affected += 1
        else:  # adopt generation-only
            generation, scope_id = params
            for row in state.scopes:
                if (
                    row["scope_id"] == scope_id
                    and row["support_generation"] is None
                ):
                    row["support_generation"] = generation
                    affected += 1
        self.rowcount = affected

    def _insert_cadence(self, params: tuple, state: _FakeState) -> None:
        cadence_id = state.next_cadence_id
        state.next_cadence_id += 1
        state.cadence.append(
            {
                "cadence_config_id": cadence_id,
                "venue": params[0],
                "symbol": params[1],
                "quote_currency": params[2],
                "fib_trading_horizon": params[3],
                "primary_interval": params[4],
                "supporting_interval": params[5],
                "cadence_contract_version": params[6],
                "target_evaluation_interval": params[7],
                "primary_source_freshness_limit_seconds": params[8],
                "supporting_source_freshness_limit_seconds": params[9],
                "evaluation_grace_seconds": params[10],
                "recent_scope_grace_seconds": params[11],
                "effective_from_utc": params[12],
                "effective_to_utc": None,
                "is_active": 1,
                "activation_operation_id": params[13],
                "deactivation_operation_id": None,
                "support_generation": params[14],
            }
        )
        self.lastrowid = cadence_id

    def _update_cadence(self, norm: str, params: tuple, state: _FakeState) -> None:
        affected = 0
        if "SET is_active = 0" in norm:  # deactivate
            operation_id, effective_to, cadence_id = params
            for row in state.cadence:
                if (
                    row["cadence_config_id"] == cadence_id
                    and row["is_active"] == 1
                    and row["activation_operation_id"] is not None
                    and row["deactivation_operation_id"] is None
                ):
                    row.update(
                        is_active=0,
                        deactivation_operation_id=operation_id,
                        effective_to_utc=effective_to,
                    )
                    affected += 1
        else:  # bind legacy
            operation_id, generation, cadence_id = params
            for row in state.cadence:
                if (
                    row["cadence_config_id"] == cadence_id
                    and row["is_active"] == 1
                    and row["activation_operation_id"] is None
                    and row["support_generation"] is None
                ):
                    row.update(
                        activation_operation_id=operation_id,
                        support_generation=generation,
                    )
                    affected += 1
        self.rowcount = affected

    def _insert_support(self, params: tuple, state: _FakeState) -> None:
        support_id = state.next_support_id
        state.next_support_id += 1
        generation = params[8]
        operation_id = params[7]
        for row in state.support:
            if (
                row["support_generation"] == generation
                and generation is not None
                and _same_scope(row, params[:6])
            ):
                raise _fake_integrity("duplicate support generation")
            if row["scope_admin_operation_id"] == operation_id and operation_id:
                raise _fake_integrity("duplicate support operation")
        state.support.append(
            {
                "scope_support_event_id": support_id,
                "venue": params[0],
                "symbol": params[1],
                "quote_currency": params[2],
                "fib_trading_horizon": params[3],
                "primary_interval": params[4],
                "supporting_interval": params[5],
                "scope_support_state": params[6],
                "scope_admin_operation_id": operation_id,
                "support_generation": generation,
            }
        )
        self.lastrowid = support_id

    def _delete_scope(self, rows: list[dict[str, Any]], key: tuple) -> None:
        keep = [r for r in rows if not _same_scope(r, key)]
        self.rowcount = len(rows) - len(keep)
        rows[:] = keep


def _same_scope(row: dict[str, Any], key: tuple) -> bool:
    fields = (
        "venue",
        "symbol",
        "quote_currency",
        "fib_trading_horizon",
        "primary_interval",
        "supporting_interval",
    )
    return all(row[field] == key[i] for i, field in enumerate(fields))


def _match_scope(rows: list[dict[str, Any]], key: tuple) -> list[dict[str, Any]]:
    return [copy.deepcopy(r) for r in rows if _same_scope(r, key)]


def _fake_integrity(detail: str) -> Exception:
    exc = RuntimeError(detail)
    return exc


class _FakeConn:
    def __init__(self, committed: _FakeState | None = None) -> None:
        self.committed = committed or _FakeState()
        self.working: _FakeState | None = None
        self.executions: list[str] = []
        self.begin_count = 0
        self.commit_count = 0
        self.rollback_count = 0
        self.held_locks: set[str] = set()
        self.fail_on: str | None = None

    @property
    def state(self) -> _FakeState:
        return self.working if self.working is not None else self.committed

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def begin(self) -> None:
        self.begin_count += 1
        self.working = copy.deepcopy(self.committed)

    def commit(self) -> None:
        self.commit_count += 1
        if self.working is not None:
            self.committed = self.working
            self.working = None

    def rollback(self) -> None:
        self.rollback_count += 1
        self.working = None

    def close(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _clear_locks() -> Iterator[None]:
    _SHARED_LOCKS.clear()
    yield
    _SHARED_LOCKS.clear()


def _seed_supported(state: _FakeState, *, generation: int, symbol: str = "BTC") -> None:
    scope_id = state.next_scope_id
    state.next_scope_id += 1
    op_id = state.next_operation_id
    state.next_operation_id += 1
    cadence_id = state.next_cadence_id
    state.next_cadence_id += 1
    key = ("bitvavo", symbol, "EUR", "SHORT", "4h", "1h")
    state.scopes.append(
        dict(
            zip(
                (
                    "venue",
                    "symbol",
                    "quote_currency",
                    "fib_trading_horizon",
                    "primary_interval",
                    "supporting_interval",
                ),
                key,
            ),
            scope_id=scope_id,
            scope_support_state="SUPPORTED",
            scope_reason_code=None,
            scope_reason_detail=None,
            support_generation=generation,
        )
    )
    state.operations.append(
        {
            "scope_admin_operation_id": op_id,
            "operation_uuid": f"seed-{symbol}-{generation}",
            "operation_type": "PROMOTE_SCOPE",
            "venue": "bitvavo",
            "symbol": symbol,
            "quote_currency": "EUR",
            "fib_trading_horizon": "SHORT",
            "primary_interval": "4h",
            "supporting_interval": "1h",
            "metadata_digest": "0" * 64,
            "completed_at_utc": datetime(2026, 7, 10, 0, 0),
            "result_class": "SUCCESS",
            "result_code": "PROMOTED_NEW_SCOPE",
            "support_generation_before": None,
            "support_generation_after": generation,
        }
    )
    state.cadence.append(
        {
            "cadence_config_id": cadence_id,
            "venue": "bitvavo",
            "symbol": symbol,
            "quote_currency": "EUR",
            "fib_trading_horizon": "SHORT",
            "primary_interval": "4h",
            "supporting_interval": "1h",
            "cadence_contract_version": CANONICAL_CADENCE_CONTRACT_VERSION,
            "target_evaluation_interval": CANONICAL_TARGET_EVALUATION_INTERVAL,
            "primary_source_freshness_limit_seconds": (
                CANONICAL_PRIMARY_SOURCE_FRESHNESS_LIMIT_SECONDS
            ),
            "supporting_source_freshness_limit_seconds": (
                CANONICAL_SUPPORTING_SOURCE_FRESHNESS_LIMIT_SECONDS
            ),
            "evaluation_grace_seconds": CANONICAL_EVALUATION_GRACE_SECONDS,
            "recent_scope_grace_seconds": CANONICAL_RECENT_SCOPE_GRACE_SECONDS,
            "effective_from_utc": datetime(2026, 7, 10, 0, 0),
            "effective_to_utc": None,
            "is_active": 1,
            "activation_operation_id": op_id,
            "deactivation_operation_id": None,
            "support_generation": generation,
        }
    )
    state.support.append(
        {
            "scope_support_event_id": state.next_support_id,
            "venue": "bitvavo",
            "symbol": symbol,
            "quote_currency": "EUR",
            "fib_trading_horizon": "SHORT",
            "primary_interval": "4h",
            "supporting_interval": "1h",
            "scope_support_state": "SUPPORTED",
            "scope_admin_operation_id": op_id,
            "support_generation": generation,
        }
    )
    state.next_support_id += 1


_AUTH = object()


@pytest.fixture(autouse=True)
def _stub_writer_authorization(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.operations.writer_capability_authorization_v1 as authmod

    monkeypatch.setattr(
        authmod,
        "require_writer_mutation_authorization",
        lambda authorization, capability_id: authorization,
    )


def test_write_promote_new_scope_commits_full_state() -> None:
    conn = _FakeConn()
    outcome = execute_scope_administration(
        conn, _request(), authorization=_AUTH, now_utc=datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
    )
    assert outcome.result.result_code == ResultCode.PROMOTED_NEW_SCOPE
    assert outcome.persisted is True
    assert conn.commit_count == 1
    assert len(conn.committed.scopes) == 1
    assert conn.committed.scopes[0]["support_generation"] == 1
    assert len(conn.committed.cadence) == 1
    assert conn.committed.cadence[0]["is_active"] == 1
    assert len(conn.committed.support) == 1
    assert len(conn.committed.operations) == 1
    # Advisory lock acquired and released.
    assert not conn.held_locks
    assert not _SHARED_LOCKS


def test_write_replay_is_idempotent_without_second_mutation() -> None:
    conn = _FakeConn()
    request = _request()
    first = execute_scope_administration(conn, request, authorization=_AUTH)
    assert first.persisted is True
    ops_after_first = len(conn.committed.operations)

    second = execute_scope_administration(conn, request, authorization=_AUTH)
    assert second.result.result_code == ResultCode.OPERATION_ALREADY_COMPLETED
    assert second.persisted is False
    assert len(conn.committed.operations) == ops_after_first
    assert len(conn.committed.scopes) == 1


def test_write_already_supported_new_uuid_does_not_persist() -> None:
    state = _FakeState()
    _seed_supported(state, generation=1)
    conn = _FakeConn(state)
    outcome = execute_scope_administration(
        conn, _request(provenance=_provenance(operation_uuid="00000000-0000-4000-8000-0000000000aa")), authorization=_AUTH
    )
    assert outcome.result.result_code == ResultCode.SCOPE_ALREADY_SUPPORTED
    assert outcome.persisted is False
    assert len(conn.committed.operations) == 1  # only the seed operation
    assert conn.rollback_count >= 1


def test_write_removal_then_repromotion_preserves_prior_rows() -> None:
    state = _FakeState()
    _seed_supported(state, generation=1)
    conn = _FakeConn(state)

    remove = execute_scope_administration(
        conn,
        _request(
            OperationType.REMOVE_SCOPE,
            provenance=_provenance(operation_uuid="00000000-0000-4000-8000-0000000000b1"),
        ),
        authorization=_AUTH,
    )
    assert remove.result.result_code == ResultCode.REMOVED_SCOPE
    assert conn.committed.scopes[0]["scope_support_state"] == "NOT_APPLICABLE"
    assert conn.committed.scopes[0]["support_generation"] == 2
    assert all(row["is_active"] == 0 for row in conn.committed.cadence)

    repromote = execute_scope_administration(
        conn,
        _request(
            OperationType.PROMOTE_SCOPE,
            provenance=_provenance(operation_uuid="00000000-0000-4000-8000-0000000000b2"),
        ),
        authorization=_AUTH,
    )
    assert repromote.result.result_code == ResultCode.PROMOTED_FROM_PRIOR_WITHDRAWAL
    assert conn.committed.scopes[0]["scope_support_state"] == "SUPPORTED"
    assert conn.committed.scopes[0]["support_generation"] == 3
    # Prior inactive cadence preserved plus one new active row.
    assert len(conn.committed.cadence) == 2
    assert sum(1 for r in conn.committed.cadence if r["is_active"] == 1) == 1
    # Prior support events preserved plus new ones (seed + remove + repromote).
    assert len(conn.committed.support) == 3


def test_write_rollback_after_injected_failure_leaves_no_partial_state() -> None:
    conn = _FakeConn()
    conn.fail_on = "scope"
    with pytest.raises(RuntimeError, match="injected scope insert failure"):
        execute_scope_administration(conn, _request(), authorization=_AUTH)
    assert conn.rollback_count >= 1
    assert conn.committed.scopes == []
    assert conn.committed.operations == []
    assert conn.committed.cadence == []
    assert not _SHARED_LOCKS  # lock released in finally


def test_write_lock_timeout_maps_to_retryable_code() -> None:
    conn = _FakeConn()
    _SHARED_LOCKS.add(advisory_lock_name(_key().as_dict()))
    outcome = execute_scope_administration(conn, _request(), authorization=_AUTH)
    assert outcome.result.result_code == ResultCode.LOCK_TIMEOUT
    assert outcome.persisted is False
    assert conn.commit_count == 0


def test_write_requires_authorization_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.operations.writer_capability_authorization_v1 as authmod

    def _deny(authorization: Any, capability_id: str) -> Any:
        raise authmod.AuthorizationDenied(
            capability_id, authmod.ExecutionMode.READ_ONLY, ["missing"]
        )

    monkeypatch.setattr(authmod, "require_writer_mutation_authorization", _deny)
    conn = _FakeConn()
    with pytest.raises(authmod.AuthorizationDenied):
        execute_scope_administration(conn, _request(), authorization=None)
    assert conn.begin_count == 0  # never opened a transaction
    assert conn.committed.scopes == []


def test_dry_run_performs_no_writes_and_no_transaction() -> None:
    conn = _FakeConn()
    outcome = plan_scope_administration(conn, _request())
    assert outcome.mode == txn.TransactionMode.DRY_RUN
    assert outcome.result.result_code == ResultCode.PROMOTED_NEW_SCOPE
    assert outcome.persisted is False
    assert conn.begin_count == 0
    assert conn.commit_count == 0
    assert all(not e.startswith("INSERT") for e in conn.executions)
    assert all(not e.startswith("UPDATE") for e in conn.executions)
    assert all("FOR UPDATE" not in e for e in conn.executions)


def test_dry_run_fails_closed_on_incoherent_state() -> None:
    state = _FakeState()
    _seed_supported(state, generation=1)
    # Inject a second active cadence row to create corruption.
    state.cadence.append(dict(state.cadence[0], cadence_config_id=999))
    conn = _FakeConn(state)
    outcome = plan_scope_administration(conn, _request(OperationType.REMOVE_SCOPE))
    assert outcome.result.result_code == ResultCode.MULTIPLE_ACTIVE_CADENCE_ROWS
    assert outcome.persisted is False


# --------------------------------------------------------------------------- #
# CLI tests                                                                    #
# --------------------------------------------------------------------------- #


import io

from src.market_data import run_native_short_scope_administration_v1 as cli
from src.market_data.native_short_repository_source_identity_v1 import (
    NativeShortRepositorySourceState,
)


_BASE_CLI_ARGS = [
    "--symbol",
    "BTC",
    "--operation",
    "PROMOTE_SCOPE",
    "--actor-type",
    "HUMAN_OPERATOR",
    "--actor-id",
    "operator-1",
    "--trigger-type",
    "MANUAL_CLI",
    "--reason",
    "explicit review",
    "--operation-uuid",
    "00000000-0000-4000-8000-00000000c001",
    "--request-source",
    "cli-test",
    "--repository-commit",
    "a" * 40,
    "--trigger-ref",
    "admin-cli-test",
    "--requested-at-utc",
    "2026-07-18T10:00:00Z",
]


def _clean_source() -> NativeShortRepositorySourceState:
    return NativeShortRepositorySourceState(head_sha="a" * 40, status_porcelain="")


def _run_cli(
    monkeypatch: pytest.MonkeyPatch, argv: list[str], *, conn: _FakeConn
) -> tuple[int, list[dict[str, Any]]]:
    import src.common.db as dbmod

    monkeypatch.setattr(dbmod, "get_connection", lambda: conn)
    buf = io.StringIO()
    monkeypatch.setattr("sys.stdout", buf)
    code = cli.main(argv, inspect_repository_source=_clean_source)
    monkeypatch.undo()
    lines = [json.loads(line) for line in buf.getvalue().splitlines() if line.strip()]
    return code, lines


def test_cli_help_exits_zero() -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0


def test_cli_dry_run_is_default(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    code, lines = _run_cli(monkeypatch, _BASE_CLI_ARGS, conn=conn)
    assert code == 0
    started = next(line for line in lines if line["event"] == "STARTED")
    result = next(line for line in lines if line["event"] == "RESULT")
    assert started["dry_run"] is True
    assert started["write"] is False
    assert result["mode"] == "DRY_RUN"
    assert result["persisted"] is False
    assert result["result_code"] == "PROMOTED_NEW_SCOPE"
    # Safety markers present.
    for marker in (
        "broker_private_calls",
        "broker_writes",
        "order_submission",
        "live_orders",
        "systemd_changes",
        "timer_changes",
        "runtime_activation",
        "host_mutations",
    ):
        assert marker in result
    assert conn.commit_count == 0


def test_cli_write_is_explicit_and_persists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.operations.writer_capability_authorization_v1 as authmod

    monkeypatch.setattr(
        authmod,
        "require_capability_write_authorization",
        lambda capability_id, **kwargs: _AUTH,
    )
    monkeypatch.setattr(
        authmod,
        "require_writer_mutation_authorization",
        lambda authorization, capability_id: authorization,
    )
    conn = _FakeConn()
    code, lines = _run_cli(monkeypatch, [*_BASE_CLI_ARGS, "--write"], conn=conn)
    assert code == 0
    result = next(line for line in lines if line["event"] == "RESULT")
    assert result["mode"] == "WRITE"
    assert result["persisted"] is True
    assert result["result_code"] == "PROMOTED_NEW_SCOPE"
    assert result["production_db_writes"] == 1
    assert conn.commit_count == 1


def test_cli_write_rejects_dirty_source_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeConn()

    def _dirty() -> NativeShortRepositorySourceState:
        return NativeShortRepositorySourceState(
            head_sha="a" * 40, status_porcelain=" M src/foo.py"
        )

    import src.common.db as dbmod

    monkeypatch.setattr(dbmod, "get_connection", lambda: conn)
    buf = io.StringIO()
    monkeypatch.setattr("sys.stdout", buf)
    code = cli.main([*_BASE_CLI_ARGS, "--write"], inspect_repository_source=_dirty)
    monkeypatch.undo()
    lines = [json.loads(x) for x in buf.getvalue().splitlines() if x.strip()]
    assert code == 2
    failed = next(line for line in lines if line["event"] == "FAILED")
    assert failed["reason_code"] == "INVALID_REPOSITORY_SOURCE"
    assert conn.begin_count == 0


def test_cli_rejects_multi_symbol_and_wildcards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeConn()
    for bad in ("BTC,ETH", "*", "BTC ETH"):
        args = list(_BASE_CLI_ARGS)
        args[1] = bad
        code, lines = _run_cli(monkeypatch, args, conn=conn)
        assert code == 2
        assert any(line["event"] == "FAILED" for line in lines)


def test_cli_requires_explicit_provenance() -> None:
    # Missing required provenance argument aborts argparse with a nonzero exit.
    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "--symbol",
                "BTC",
                "--operation",
                "PROMOTE_SCOPE",
                "--actor-type",
                "HUMAN_OPERATOR",
            ]
        )
    assert exc.value.code != 0


def test_cli_result_json_is_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    conn1 = _FakeConn()
    _, lines1 = _run_cli(monkeypatch, _BASE_CLI_ARGS, conn=conn1)
    conn2 = _FakeConn()
    _, lines2 = _run_cli(monkeypatch, _BASE_CLI_ARGS, conn=conn2)
    result1 = next(line for line in lines1 if line["event"] == "RESULT")
    result2 = next(line for line in lines2 if line["event"] == "RESULT")
    assert json.dumps(result1, sort_keys=True) == json.dumps(result2, sort_keys=True)


# --------------------------------------------------------------------------- #
# Layer-boundary hygiene                                                       #
# --------------------------------------------------------------------------- #


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


@pytest.mark.parametrize(
    "path",
    (
        Path("src/market_data/native_short_scope_administration_transaction_v1.py"),
        Path("src/market_data/run_native_short_scope_administration_v1.py"),
    ),
)
def test_no_forbidden_layer_imports(path: Path) -> None:
    forbidden = (
        "selection",
        "decision_gate",
        "execution_planner",
        "executor",
        "broker",
        "src.account",
        "wallet",
        "reporting",
        ".order",
    )
    for module_name in _imports(path):
        assert not any(
            token in module_name for token in forbidden
        ), f"forbidden dependency import: {module_name}"


# --------------------------------------------------------------------------- #
# Opt-in MariaDB integration tests                                            #
# --------------------------------------------------------------------------- #


BASE_MIGRATION = Path("db/migrations/20260626_native_short_map_lifecycle_v1.sql")
STATUS_MIGRATION = Path(
    "db/migrations/20260706_native_short_scope_status_persistence_v1.sql"
)
LEVEL_MIGRATION = Path("db/migrations/20260708_native_short_map_level_status_v1.sql")
ADMIN_MIGRATION = Path(
    "db/migrations/20260718_native_short_scope_administration_v1.sql"
)
TEMP_DB_PREFIX = "synth_native_short_scope_admin_txn_v1_tmp"

_REQUIRED_ENV = (
    "SYNTH_TEST_MARIADB_HOST",
    "SYNTH_TEST_MARIADB_PORT",
    "SYNTH_TEST_MARIADB_USER",
    "SYNTH_TEST_MARIADB_PASSWORD",
    "SYNTH_TEST_MARIADB_ADMIN_DATABASE",
)

_MARIADB = pytest.mark.skipif(
    os.getenv("RUN_MARIADB_DDL_TEST") != "1",
    reason="Set RUN_MARIADB_DDL_TEST=1 with explicit disposable MariaDB settings.",
)


def _split_sql_statements(sql_text: str) -> list[str]:
    statements: list[str] = []
    buffer: list[str] = []
    for line in sql_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        buffer.append(line)
        if stripped.endswith(";"):
            statement = "\n".join(buffer).strip()
            statements.append(statement[:-1] if statement.endswith(";") else statement)
            buffer = []
    if buffer:
        statements.append("\n".join(buffer).strip())
    return statements


def _explicit_test_config() -> dict[str, str]:
    missing = [name for name in _REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        pytest.skip("explicit disposable MariaDB configuration is absent")
    if os.environ.get("SYNTH_TEST_MARIADB_DISPOSABLE") != "1":
        pytest.skip("SYNTH_TEST_MARIADB_DISPOSABLE=1 is required")
    return {name: os.environ[name] for name in _REQUIRED_ENV}


def _connect(config: dict[str, str], *, database: str) -> Any:
    import pymysql
    from pymysql.cursors import DictCursor

    return pymysql.connect(
        host=config["SYNTH_TEST_MARIADB_HOST"],
        port=int(config["SYNTH_TEST_MARIADB_PORT"]),
        user=config["SYNTH_TEST_MARIADB_USER"],
        password=config["SYNTH_TEST_MARIADB_PASSWORD"],
        database=database,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
    )


@contextmanager
def _disposable_schema(label: str) -> Iterator[Any]:
    config = _explicit_test_config()
    database = f"{TEMP_DB_PREFIX}_{label}_{os.getpid()}"
    admin = _connect(config, database=config["SYNTH_TEST_MARIADB_ADMIN_DATABASE"])
    connection = None
    try:
        with admin.cursor() as cursor:
            cursor.execute(f"DROP DATABASE IF EXISTS `{database}`")
            cursor.execute(
                f"CREATE DATABASE `{database}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        admin.commit()
        connection = _connect(config, database=database)
        for path in (
            BASE_MIGRATION,
            STATUS_MIGRATION,
            LEVEL_MIGRATION,
            ADMIN_MIGRATION,
        ):
            with connection.cursor() as cursor:
                for statement in _split_sql_statements(
                    path.read_text(encoding="utf-8")
                ):
                    cursor.execute(statement)
            connection.commit()
        yield connection, config, database
    finally:
        if connection is not None:
            connection.close()
        with admin.cursor() as cursor:
            cursor.execute(f"DROP DATABASE IF EXISTS `{database}`")
        admin.commit()
        admin.close()


def _mariadb_request(operation: OperationType, uuid: str, *, symbol: str = "BTC"):
    return _request(
        operation,
        symbol=symbol,
        provenance=_provenance(operation_uuid=uuid),
    )


@_MARIADB
def test_mariadb_promote_new_and_replay_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        __import__(
            "src.operations.writer_capability_authorization_v1",
            fromlist=["require_writer_mutation_authorization"],
        ),
        "require_writer_mutation_authorization",
        lambda authorization, capability_id: authorization,
    )
    with _disposable_schema("promote") as (conn, _config, _db):
        request = _mariadb_request(
            OperationType.PROMOTE_SCOPE, "00000000-0000-4000-8000-00000000d001"
        )
        outcome = execute_scope_administration(conn, request, authorization=_AUTH)
        assert outcome.result.result_code == ResultCode.PROMOTED_NEW_SCOPE
        assert outcome.persisted is True

        replay = execute_scope_administration(conn, request, authorization=_AUTH)
        assert replay.result.result_code == ResultCode.OPERATION_ALREADY_COMPLETED
        assert replay.persisted is False

        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS n FROM native_short_map_scope_v1")
            assert cursor.fetchone()["n"] == 1
            cursor.execute(
                "SELECT COUNT(*) AS n FROM native_short_scope_admin_operation_v1"
            )
            assert cursor.fetchone()["n"] == 1
            cursor.execute(
                "SELECT COUNT(*) AS n FROM native_short_scope_cadence_config_v1 "
                "WHERE is_active = 1"
            )
            assert cursor.fetchone()["n"] == 1


@_MARIADB
def test_mariadb_first_creation_serialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        __import__(
            "src.operations.writer_capability_authorization_v1",
            fromlist=["require_writer_mutation_authorization"],
        ),
        "require_writer_mutation_authorization",
        lambda authorization, capability_id: authorization,
    )
    with _disposable_schema("serialize") as (conn, config, database):
        conn_b = _connect(config, database=database)
        try:
            results: dict[str, Any] = {}
            barrier = threading.Barrier(2)

            def _promote(tag: str, connection: Any, uuid: str) -> None:
                barrier.wait()
                results[tag] = execute_scope_administration(
                    connection,
                    _mariadb_request(OperationType.PROMOTE_SCOPE, uuid),
                    authorization=_AUTH,
                )

            t1 = threading.Thread(
                target=_promote,
                args=("a", conn, "00000000-0000-4000-8000-00000000d0a1"),
            )
            t2 = threading.Thread(
                target=_promote,
                args=("b", conn_b, "00000000-0000-4000-8000-00000000d0a2"),
            )
            t1.start()
            t2.start()
            t1.join()
            t2.join()

            codes = {str(results["a"].result.result_code), str(results["b"].result.result_code)}
            # Exactly one creates the scope; the other observes it already
            # supported or fails closed on the lock. Never two scopes.
            assert "PROMOTED_NEW_SCOPE" in codes
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) AS n FROM native_short_map_scope_v1")
                assert cursor.fetchone()["n"] == 1
                cursor.execute(
                    "SELECT COUNT(*) AS n FROM native_short_scope_cadence_config_v1 "
                    "WHERE is_active = 1"
                )
                assert cursor.fetchone()["n"] == 1
        finally:
            conn_b.close()


@_MARIADB
def test_mariadb_rollback_leaves_no_partial_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authmod = __import__(
        "src.operations.writer_capability_authorization_v1",
        fromlist=["require_writer_mutation_authorization"],
    )
    monkeypatch.setattr(
        authmod,
        "require_writer_mutation_authorization",
        lambda authorization, capability_id: authorization,
    )
    with _disposable_schema("rollback") as (conn, _config, _db):
        # Inject a failure by monkeypatching the support-event insert to raise
        # after the scope/cadence/operation writes in the same transaction.
        original = txn._insert_support_event

        def _boom(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("injected failure")

        monkeypatch.setattr(txn, "_insert_support_event", _boom)
        with pytest.raises(RuntimeError, match="injected failure"):
            execute_scope_administration(
                conn,
                _mariadb_request(
                    OperationType.PROMOTE_SCOPE,
                    "00000000-0000-4000-8000-00000000d301",
                ),
                authorization=_AUTH,
            )
        monkeypatch.setattr(txn, "_insert_support_event", original)
        with conn.cursor() as cursor:
            for table in (
                "native_short_map_scope_v1",
                "native_short_scope_admin_operation_v1",
                "native_short_scope_support_event_v1",
            ):
                cursor.execute(f"SELECT COUNT(*) AS n FROM {table}")
                assert cursor.fetchone()["n"] == 0, table


@_MARIADB
def test_mariadb_cross_scope_operation_attribution_is_rejected() -> None:
    with _disposable_schema("crossscope") as (conn, _config, _db):
        # An operation recorded for BTC cannot be referenced by an ETH support
        # event: the scope-bound composite FK forbids it.
        import pymysql

        with conn.cursor() as cursor:
            cursor.execute(
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
                    '00000000-0000-4000-8000-00000000d401', 'PROMOTE_SCOPE',
                    'bitvavo', 'BTC', 'EUR', 'SHORT', '4h', '1h',
                    'TEST', 'x', 'TEST', 'src', 'r',
                    '2026-07-18 10:00:00', %s, 'v', %s,
                    '2026-07-18 10:00:00', '2026-07-18 10:00:00',
                    'SUCCESS', 'PROMOTED_NEW_SCOPE', NULL, 1
                )
                """,
                ("0" * 40, "1" * 64),
            )
            cursor.execute(
                "SELECT scope_admin_operation_id AS id "
                "FROM native_short_scope_admin_operation_v1"
            )
            op_id = cursor.fetchone()["id"]
        conn.commit()

        with pytest.raises(pymysql.err.IntegrityError):
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO native_short_scope_support_event_v1 (
                        venue, symbol, quote_currency, fib_trading_horizon,
                        primary_interval, supporting_interval, scope_support_state,
                        scope_admin_operation_id, support_generation, event_ts_utc,
                        source_name, source_version
                    ) VALUES (
                        'bitvavo', 'ETH', 'EUR', 'SHORT', '4h', '1h', 'SUPPORTED',
                        %s, 1, '2026-07-18 11:00:00', 'admin_test', 'v1'
                    )
                    """,
                    (op_id,),
                )
        conn.rollback()
