from __future__ import annotations

import ast
import copy
import io
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
    ADMIN_REMOVAL_REASON_CODE,
    CANONICAL_CADENCE_CONTRACT_VERSION,
    CANONICAL_EVALUATION_GRACE_SECONDS,
    CANONICAL_PRIMARY_SOURCE_FRESHNESS_LIMIT_SECONDS,
    CANONICAL_RECENT_SCOPE_GRACE_SECONDS,
    CANONICAL_SUPPORTING_SOURCE_FRESHNESS_LIMIT_SECONDS,
    CANONICAL_TARGET_EVALUATION_INTERVAL,
    AdminOperationRow,
    AdministrationDecision,
    CadenceRowState,
    CommitState,
    ExistingOperation,
    NativeShortScopeAdministrationExecutionError,
    OperationAction,
    ScopeClassification,
    ScopeStateSnapshot,
    SupportEventRow,
    advisory_lock_name,
    classify_scope_state,
    decide_administration,
    decide_operation_replay,
    execute_scope_administration,
    plan_scope_administration,
)


@pytest.fixture(autouse=True)
def _default_no_global_blockers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unless a test explicitly overrides it (see the GLOBAL_BLOCKERS_ACTIVE
    enforcement tests below), no canonical global blocker is active. This
    keeps every non-blocker-focused write/dry-run/CLI test in this file
    exercising exactly its original behavior without needing the fake
    connection to also serve writer-provenance/operation-ledger audit
    queries. Monkeypatching this module-level function is the same
    established test-seam pattern already used for
    ``read_scope_state_snapshot`` / ``_insert_support_event`` elsewhere in
    this file -- not a caller-facing bypass: ``execute_scope_administration``
    and ``plan_scope_administration`` take no blocker-state parameter at all,
    so no production caller can fabricate cleared blockers this way.
    """
    monkeypatch.setattr(txn, "evaluate_current_global_blockers", lambda conn: ((), {}))


# --------------------------------------------------------------------------- #
# Request builders                                                            #
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


# --------------------------------------------------------------------------- #
# Snapshot builders                                                           #
# --------------------------------------------------------------------------- #


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


def _support_event(
    *,
    event_id: int = 1,
    generation: int | None = None,
    state: str = "SUPPORTED",
    operation_id: int | None = None,
) -> SupportEventRow:
    return SupportEventRow(
        scope_support_event_id=event_id,
        scope_support_state=state,
        scope_admin_operation_id=operation_id,
        support_generation=generation,
    )


def _admin_op(
    *,
    operation_id: int,
    operation_type: str = "PROMOTE_SCOPE",
    result_class: str | None = "SUCCESS",
    result_code: str = "PROMOTED_NEW_SCOPE",
    terminal: bool = True,
    generation_before: int | None = None,
    generation_after: int | None = None,
) -> AdminOperationRow:
    return AdminOperationRow(
        scope_admin_operation_id=operation_id,
        operation_type=operation_type,
        result_class=result_class,
        result_code=result_code,
        is_terminal=terminal,
        support_generation_before=generation_before,
        support_generation_after=generation_after,
    )


def _snapshot(
    *,
    scope_present: bool = True,
    scope_id: int | None = 1,
    state: str | None = "SUPPORTED",
    generation: int | None = None,
    cadence_rows: tuple[CadenceRowState, ...] = (),
    support_events: tuple[SupportEventRow, ...] = (),
    operations: tuple[AdminOperationRow, ...] = (),
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
        support_events=support_events,
        operations=operations,
        scope_status_residue_count=status_residue,
        map_level_status_residue_count=level_residue,
    )


def _legacy_supported(canonical: bool = True) -> ScopeStateSnapshot:
    return _snapshot(
        generation=None,
        state="SUPPORTED",
        cadence_rows=(
            _cadence(
                is_active=1,
                activation_op=None,
                support_generation=None,
                canonical_profile=canonical,
            ),
        ),
        support_events=(_support_event(generation=None, state="SUPPORTED"),),
    )


def _managed_supported(generation: int = 1, activation_op: int = 50) -> ScopeStateSnapshot:
    if generation == 1:
        op = _admin_op(
            operation_id=activation_op,
            operation_type="PROMOTE_SCOPE",
            result_code="PROMOTED_NEW_SCOPE",
            generation_before=None,
            generation_after=1,
        )
    else:
        op = _admin_op(
            operation_id=activation_op,
            operation_type="PROMOTE_SCOPE",
            result_code="PROMOTED_FROM_PRIOR_WITHDRAWAL",
            generation_before=generation - 1,
            generation_after=generation,
        )
    return _snapshot(
        generation=generation,
        state="SUPPORTED",
        cadence_rows=(
            _cadence(
                cadence_config_id=10,
                is_active=1,
                activation_op=activation_op,
                support_generation=generation,
            ),
        ),
        support_events=(
            _support_event(
                event_id=generation,
                generation=generation,
                state="SUPPORTED",
                operation_id=activation_op,
            ),
        ),
        operations=(op,),
    )


def _supported_snapshot_with_operation(
    operation: AdminOperationRow,
    *,
    generation: int,
) -> ScopeStateSnapshot:
    return _snapshot(
        generation=generation,
        cadence_rows=(
            _cadence(
                cadence_config_id=10,
                activation_op=operation.scope_admin_operation_id,
                support_generation=generation,
            ),
        ),
        support_events=(
            _support_event(
                generation=generation,
                state="SUPPORTED",
                operation_id=operation.scope_admin_operation_id,
            ),
        ),
        operations=(operation,),
    )


def _managed_removed(
    generation: int = 2, *, status_residue: int = 0, level_residue: int = 0
) -> ScopeStateSnapshot:
    supported_gen = generation - 1
    activation_op = 50
    removal_op = 60
    return _snapshot(
        state="NOT_APPLICABLE",
        generation=generation,
        reason_code=ADMIN_REMOVAL_REASON_CODE,
        cadence_rows=(
            _cadence(
                cadence_config_id=10,
                is_active=0,
                activation_op=activation_op,
                deactivation_op=removal_op,
                support_generation=supported_gen,
                effective_to=datetime(2026, 7, 15),
            ),
        ),
        support_events=(
            _support_event(
                event_id=1, generation=supported_gen, state="SUPPORTED", operation_id=activation_op
            ),
            _support_event(
                event_id=2,
                generation=generation,
                state="NOT_APPLICABLE",
                operation_id=removal_op,
            ),
        ),
        operations=(
            _admin_op(
                operation_id=activation_op,
                operation_type="PROMOTE_SCOPE",
                result_code="PROMOTED_NEW_SCOPE",
                generation_before=None,
                generation_after=supported_gen,
            ),
            _admin_op(
                operation_id=removal_op,
                operation_type="REMOVE_SCOPE",
                result_code="REMOVED_SCOPE",
                generation_before=supported_gen,
                generation_after=generation,
            ),
        ),
        status_residue=status_residue,
        level_residue=level_residue,
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
    decision = decide_administration(
        OperationType.PROMOTE_SCOPE,
        _snapshot(scope_present=False, scope_id=None),
        active_global_blockers=(),
    )
    assert decision.action == OperationAction.PROMOTE_NEW
    assert decision.result_code == ResultCode.PROMOTED_NEW_SCOPE
    assert decision.support_generation_before is None
    assert decision.support_generation_after == 1
    assert decision.writes_ledger


def test_adopt_coherent_legacy_scope() -> None:
    decision = decide_administration(
        OperationType.ADOPT_LEGACY_SCOPE,
        _legacy_supported(),
        active_global_blockers=(),
    )
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
    decision = decide_administration(
        OperationType.ADOPT_LEGACY_SCOPE, snap, active_global_blockers=()
    )
    assert decision.result_code == ResultCode.MULTIPLE_ACTIVE_CADENCE_ROWS


def test_adopt_rejects_noncanonical_cadence_profile() -> None:
    decision = decide_administration(
        OperationType.ADOPT_LEGACY_SCOPE,
        _legacy_supported(canonical=False),
        active_global_blockers=(),
    )
    assert decision.result_code == ResultCode.CADENCE_PROFILE_CONFLICT


def test_adopt_rejects_partial_administration_state() -> None:
    snap = _snapshot(
        generation=None,
        cadence_rows=(_cadence(),),
        support_events=(_support_event(generation=1, operation_id=5),),
    )
    decision = decide_administration(
        OperationType.ADOPT_LEGACY_SCOPE, snap, active_global_blockers=()
    )
    assert decision.result_code == ResultCode.PARTIAL_SCOPE_STATE


def test_adopt_already_managed_is_idempotent() -> None:
    decision = decide_administration(
        OperationType.ADOPT_LEGACY_SCOPE,
        _managed_supported(generation=3),
        active_global_blockers=(),
    )
    assert decision.action == OperationAction.NOOP
    assert decision.result_code == ResultCode.SCOPE_ALREADY_ADOPTED


def test_managed_removal() -> None:
    decision = decide_administration(
        OperationType.REMOVE_SCOPE,
        _managed_supported(generation=3),
        active_global_blockers=(),
    )
    assert decision.action == OperationAction.REMOVE
    assert decision.result_code == ResultCode.REMOVED_SCOPE
    assert decision.support_generation_before == 3
    assert decision.support_generation_after == 4
    assert decision.target_cadence_config_id == 10


def test_repeat_removal_is_idempotent_without_residue() -> None:
    decision = decide_administration(
        OperationType.REMOVE_SCOPE, _managed_removed(2), active_global_blockers=()
    )
    assert decision.action == OperationAction.NOOP
    assert decision.result_code == ResultCode.SCOPE_ALREADY_REMOVED


def test_repeat_removal_clears_derived_residue_is_ledgered() -> None:
    decision = decide_administration(
        OperationType.REMOVE_SCOPE,
        _managed_removed(2, level_residue=2),
        active_global_blockers=(),
    )
    assert decision.action == OperationAction.CLEAR_RESIDUE
    assert decision.result_code == ResultCode.ALREADY_REMOVED_DERIVED_RESIDUE_CLEARED
    # Blocker 1: residue cleanup is now a ledgered action.
    assert decision.writes_ledger
    assert decision.support_generation_before == decision.support_generation_after == 2


def test_re_promotion_after_removal() -> None:
    decision = decide_administration(
        OperationType.PROMOTE_SCOPE, _managed_removed(4), active_global_blockers=()
    )
    assert decision.action == OperationAction.PROMOTE_REACTIVATE
    assert decision.result_code == ResultCode.PROMOTED_FROM_PRIOR_WITHDRAWAL
    assert decision.support_generation_before == 4
    assert decision.support_generation_after == 5


def test_already_supported_is_idempotent() -> None:
    decision = decide_administration(
        OperationType.PROMOTE_SCOPE,
        _managed_supported(generation=1),
        active_global_blockers=(),
    )
    assert decision.action == OperationAction.NOOP
    assert decision.result_code == ResultCode.SCOPE_ALREADY_SUPPORTED


def test_promote_legacy_requires_adoption() -> None:
    decision = decide_administration(
        OperationType.PROMOTE_SCOPE, _legacy_supported(), active_global_blockers=()
    )
    assert decision.result_code == ResultCode.LEGACY_SCOPE_REQUIRES_ADOPTION


def test_remove_legacy_requires_adoption() -> None:
    decision = decide_administration(
        OperationType.REMOVE_SCOPE, _legacy_supported(), active_global_blockers=()
    )
    assert decision.result_code == ResultCode.LEGACY_SCOPE_REQUIRES_ADOPTION


# --------------------------------------------------------------------------- #
# GLOBAL_BLOCKERS_ACTIVE gate: pure decide_administration enforcement          #
# --------------------------------------------------------------------------- #
#
# These tests prove decide_administration -- the single decision function
# used by both execute_scope_administration and plan_scope_administration --
# itself enforces the gate before any operation-specific dispatch, using the
# operation-specific applicable-blocker matrix defined in the transaction
# module (WRITER_PROVENANCE_UNATTRIBUTED gates all three operations;
# PROMOTE_SCOPE is additionally gated by PROMOTION_CONTRACT_MISSING,
# BOOTSTRAP_ORCHESTRATION_BLOCKED, and MULTI_SCOPE_FAILURE_ISOLATION_MISSING
# -- the rollout-expansion-specific blockers -- but NOT by
# REMOVAL_CONTRACT_MISSING, which has no bearing on whether a forward,
# additive PROMOTE_SCOPE transaction is safe or reversible (see the
# rationale comment on ``_APPLICABLE_GLOBAL_BLOCKERS_BY_OPERATION``);
# REMOVE_SCOPE is additionally gated by REMOVAL_CONTRACT_MISSING only, not by
# the rollout-expansion-specific PROMOTION_CONTRACT_MISSING /
# BOOTSTRAP_ORCHESTRATION_BLOCKED / MULTI_SCOPE_FAILURE_ISOLATION_MISSING
# blockers -- proving removal/rollback safety semantics explicitly).


def test_decide_promote_blocked_by_active_promotion_contract_missing() -> None:
    decision = decide_administration(
        OperationType.PROMOTE_SCOPE,
        _snapshot(scope_present=False, scope_id=None),
        active_global_blockers=("PROMOTION_CONTRACT_MISSING",),
    )
    assert decision.action == OperationAction.REJECT
    assert decision.result_code == ResultCode.GLOBAL_BLOCKERS_ACTIVE
    assert str(decision.result_class) == "BLOCKED"
    assert decision.blocking_global_blockers == ("PROMOTION_CONTRACT_MISSING",)


def test_decide_promote_blocked_by_writer_provenance_unattributed() -> None:
    decision = decide_administration(
        OperationType.PROMOTE_SCOPE,
        _snapshot(scope_present=False, scope_id=None),
        active_global_blockers=("WRITER_PROVENANCE_UNATTRIBUTED",),
    )
    assert decision.result_code == ResultCode.GLOBAL_BLOCKERS_ACTIVE
    assert decision.blocking_global_blockers == ("WRITER_PROVENANCE_UNATTRIBUTED",)


def test_decide_promote_blocked_by_bootstrap_or_isolation_blockers() -> None:
    for code in ("BOOTSTRAP_ORCHESTRATION_BLOCKED", "MULTI_SCOPE_FAILURE_ISOLATION_MISSING"):
        decision = decide_administration(
            OperationType.PROMOTE_SCOPE,
            _snapshot(scope_present=False, scope_id=None),
            active_global_blockers=(code,),
        )
        assert decision.result_code == ResultCode.GLOBAL_BLOCKERS_ACTIVE, code
        assert decision.blocking_global_blockers == (code,)


def test_decide_promote_not_blocked_by_removal_contract_missing() -> None:
    # REMOVAL_CONTRACT_MISSING proves REMOVE_SCOPE is safe to execute; it has
    # no bearing on a forward, additive PROMOTE_SCOPE transaction, which
    # never touches removal machinery (_update_scope_remove,
    # _deactivate_cadence, ADMIN_REMOVAL_REASON_CODE) and is independently
    # re-proven coherent by _revalidate_post_state before commit regardless.
    decision = decide_administration(
        OperationType.PROMOTE_SCOPE,
        _snapshot(scope_present=False, scope_id=None),
        active_global_blockers=("REMOVAL_CONTRACT_MISSING",),
    )
    assert decision.action == OperationAction.PROMOTE_NEW
    assert decision.result_code == ResultCode.PROMOTED_NEW_SCOPE
    assert decision.blocking_global_blockers == ()


def test_decide_adopt_blocked_by_writer_provenance_unattributed() -> None:
    decision = decide_administration(
        OperationType.ADOPT_LEGACY_SCOPE,
        _legacy_supported(),
        active_global_blockers=("WRITER_PROVENANCE_UNATTRIBUTED",),
    )
    assert decision.result_code == ResultCode.GLOBAL_BLOCKERS_ACTIVE
    assert decision.blocking_global_blockers == ("WRITER_PROVENANCE_UNATTRIBUTED",)


def test_decide_adopt_not_blocked_by_promotion_or_removal_contract_missing() -> None:
    # ADOPT_LEGACY_SCOPE is not a rollout expansion or a removal; the
    # promotion/removal acceptance-evidence blockers do not apply to it.
    decision = decide_administration(
        OperationType.ADOPT_LEGACY_SCOPE,
        _legacy_supported(),
        active_global_blockers=(
            "PROMOTION_CONTRACT_MISSING",
            "REMOVAL_CONTRACT_MISSING",
            "BOOTSTRAP_ORCHESTRATION_BLOCKED",
            "MULTI_SCOPE_FAILURE_ISOLATION_MISSING",
        ),
    )
    assert decision.action == OperationAction.ADOPT
    assert decision.result_code == ResultCode.ADOPTED_LEGACY_SCOPE


def test_decide_remove_blocked_by_removal_contract_missing() -> None:
    decision = decide_administration(
        OperationType.REMOVE_SCOPE,
        _managed_supported(generation=1),
        active_global_blockers=("REMOVAL_CONTRACT_MISSING",),
    )
    assert decision.result_code == ResultCode.GLOBAL_BLOCKERS_ACTIVE
    assert decision.blocking_global_blockers == ("REMOVAL_CONTRACT_MISSING",)


def test_decide_remove_blocked_by_writer_provenance_unattributed() -> None:
    decision = decide_administration(
        OperationType.REMOVE_SCOPE,
        _managed_supported(generation=1),
        active_global_blockers=("WRITER_PROVENANCE_UNATTRIBUTED",),
    )
    assert decision.result_code == ResultCode.GLOBAL_BLOCKERS_ACTIVE


def test_decide_remove_not_blocked_by_promotion_bootstrap_or_isolation_blockers() -> None:
    # Removal is a safety/rollback action: rollout-expansion-specific
    # blockers (promotion acceptance, bootstrap orchestration, multi-scope
    # isolation) must not prevent it from proceeding when otherwise coherent.
    decision = decide_administration(
        OperationType.REMOVE_SCOPE,
        _managed_supported(generation=1),
        active_global_blockers=(
            "PROMOTION_CONTRACT_MISSING",
            "BOOTSTRAP_ORCHESTRATION_BLOCKED",
            "MULTI_SCOPE_FAILURE_ISOLATION_MISSING",
        ),
    )
    assert decision.action == OperationAction.REMOVE
    assert decision.result_code == ResultCode.REMOVED_SCOPE
    assert decision.blocking_global_blockers == ()


def test_decide_administration_no_active_blockers_is_unaffected() -> None:
    decision = decide_administration(
        OperationType.PROMOTE_SCOPE,
        _snapshot(scope_present=False, scope_id=None),
        active_global_blockers=(),
    )
    assert decision.action == OperationAction.PROMOTE_NEW
    assert decision.blocking_global_blockers == ()


def test_decide_administration_requires_explicit_blocker_state() -> None:
    import inspect

    parameter = inspect.signature(decide_administration).parameters[
        "active_global_blockers"
    ]
    assert parameter.kind == inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is inspect.Parameter.empty


def test_applicable_active_global_blockers_is_deterministic_and_sorted() -> None:
    unsorted = (
        "WRITER_PROVENANCE_UNATTRIBUTED",
        "MULTI_SCOPE_FAILURE_ISOLATION_MISSING",
        "BOOTSTRAP_ORCHESTRATION_BLOCKED",
        "PROMOTION_CONTRACT_MISSING",
    )
    expected = tuple(sorted(unsorted))
    result = txn.applicable_active_global_blockers(OperationType.PROMOTE_SCOPE, unsorted)
    assert result == expected
    # Deterministic regardless of input ordering.
    reordered = tuple(reversed(unsorted))
    assert (
        txn.applicable_active_global_blockers(OperationType.PROMOTE_SCOPE, reordered)
        == expected
    )
    # REMOVAL_CONTRACT_MISSING is not applicable to PROMOTE_SCOPE at all, so
    # including it in the input changes nothing about the result.
    with_removal = unsorted + ("REMOVAL_CONTRACT_MISSING",)
    assert (
        txn.applicable_active_global_blockers(OperationType.PROMOTE_SCOPE, with_removal)
        == expected
    )


def test_applicable_active_global_blockers_ignores_unrelated_codes() -> None:
    result = txn.applicable_active_global_blockers(
        OperationType.REMOVE_SCOPE,
        (
            "PROMOTION_CONTRACT_MISSING",
            "BOOTSTRAP_ORCHESTRATION_BLOCKED",
            "MULTI_SCOPE_FAILURE_ISOLATION_MISSING",
        ),
    )
    assert result == ()


# --- Blocker 3: complete managed cadence/generation invariants -------------- #


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
        support_events=(_support_event(generation=1, operation_id=1),),
    )
    decision = decide_administration(
        OperationType.PROMOTE_SCOPE, snap, active_global_blockers=()
    )
    assert decision.result_code == ResultCode.MULTIPLE_ACTIVE_CADENCE_ROWS


def test_active_cadence_generation_differs_from_scope_generation() -> None:
    snap = _managed_supported(generation=3)
    tampered = _snapshot(
        generation=3,
        cadence_rows=(
            _cadence(cadence_config_id=10, activation_op=50, support_generation=2),
        ),
        support_events=snap.support_events,
    )
    _, code, _ = classify_scope_state(tampered)
    assert code == ResultCode.SUPPORT_GENERATION_MISMATCH


def test_noncanonical_managed_cadence_profile_is_conflict() -> None:
    snap = _snapshot(
        generation=1,
        cadence_rows=(
            _cadence(
                cadence_config_id=10,
                activation_op=50,
                support_generation=1,
                canonical_profile=False,
            ),
        ),
        support_events=(_support_event(generation=1, operation_id=50),),
    )
    _, code, _ = classify_scope_state(snap)
    assert code == ResultCode.CADENCE_PROFILE_CONFLICT


def test_managed_supported_missing_activation_operation() -> None:
    snap = _snapshot(
        generation=1,
        cadence_rows=(
            _cadence(cadence_config_id=10, activation_op=None, support_generation=1),
        ),
        support_events=(_support_event(generation=1, operation_id=50),),
    )
    _, code, _ = classify_scope_state(snap)
    # activation-op / generation attribution shape mismatch is caught first.
    assert code == ResultCode.PARTIAL_SCOPE_STATE


def test_active_cadence_with_deactivation_operation_is_corrupt() -> None:
    snap = _snapshot(
        generation=1,
        cadence_rows=(
            _cadence(
                cadence_config_id=10,
                activation_op=50,
                deactivation_op=60,
                support_generation=1,
            ),
        ),
        support_events=(_support_event(generation=1, operation_id=50),),
    )
    _, code, _ = classify_scope_state(snap)
    assert code == ResultCode.PARTIAL_SCOPE_STATE


def test_removed_row_missing_deactivation_operation_is_corrupt() -> None:
    snap = _snapshot(
        state="NOT_APPLICABLE",
        generation=2,
        reason_code=ADMIN_REMOVAL_REASON_CODE,
        cadence_rows=(
            _cadence(
                cadence_config_id=10,
                is_active=0,
                activation_op=50,
                deactivation_op=None,
                support_generation=1,
                effective_to=datetime(2026, 7, 15),
            ),
        ),
        support_events=(
            _support_event(event_id=1, generation=1, state="SUPPORTED", operation_id=50),
            _support_event(
                event_id=2, generation=2, state="NOT_APPLICABLE", operation_id=60
            ),
        ),
    )
    _, code, _ = classify_scope_state(snap)
    assert code == ResultCode.AUTHORITATIVE_WITHDRAWAL_STATE_INCOHERENT


def test_removed_row_missing_effective_to_is_corrupt() -> None:
    snap = _snapshot(
        state="NOT_APPLICABLE",
        generation=2,
        reason_code=ADMIN_REMOVAL_REASON_CODE,
        cadence_rows=(
            _cadence(
                cadence_config_id=10,
                is_active=0,
                activation_op=50,
                deactivation_op=60,
                support_generation=1,
                effective_to=None,
            ),
        ),
        support_events=(
            _support_event(event_id=1, generation=1, state="SUPPORTED", operation_id=50),
            _support_event(
                event_id=2, generation=2, state="NOT_APPLICABLE", operation_id=60
            ),
        ),
    )
    _, code, _ = classify_scope_state(snap)
    assert code == ResultCode.AUTHORITATIVE_WITHDRAWAL_STATE_INCOHERENT


def test_support_event_correct_generation_wrong_state() -> None:
    snap = _snapshot(
        generation=1,
        cadence_rows=(
            _cadence(cadence_config_id=10, activation_op=50, support_generation=1),
        ),
        support_events=(
            _support_event(generation=1, state="NOT_APPLICABLE", operation_id=50),
        ),
    )
    _, code, _ = classify_scope_state(snap)
    assert code == ResultCode.PARTIAL_SCOPE_STATE


def test_support_event_missing_operation_attribution() -> None:
    snap = _snapshot(
        generation=1,
        cadence_rows=(
            _cadence(cadence_config_id=10, activation_op=50, support_generation=1),
        ),
        support_events=(_support_event(generation=1, state="SUPPORTED", operation_id=None),),
    )
    _, code, _ = classify_scope_state(snap)
    assert code == ResultCode.PARTIAL_SCOPE_STATE


def test_multiple_support_events_for_same_managed_generation() -> None:
    snap = _snapshot(
        generation=1,
        cadence_rows=(
            _cadence(cadence_config_id=10, activation_op=50, support_generation=1),
        ),
        support_events=(
            _support_event(event_id=1, generation=1, state="SUPPORTED", operation_id=50),
            _support_event(event_id=2, generation=1, state="SUPPORTED", operation_id=51),
        ),
    )
    _, code, _ = classify_scope_state(snap)
    assert code == ResultCode.SUPPORT_GENERATION_MISMATCH


def test_cadence_generation_ahead_of_scope_generation() -> None:
    snap = _snapshot(
        generation=1,
        cadence_rows=(
            _cadence(cadence_config_id=10, activation_op=50, support_generation=2),
        ),
        support_events=(_support_event(generation=1, operation_id=50),),
    )
    _, code, _ = classify_scope_state(snap)
    assert code == ResultCode.SUPPORT_GENERATION_MISMATCH


def test_partial_scope_state_cadence_without_scope() -> None:
    snap = _snapshot(scope_present=False, scope_id=None, cadence_rows=(_cadence(),))
    decision = decide_administration(
        OperationType.PROMOTE_SCOPE, snap, active_global_blockers=()
    )
    assert decision.result_code == ResultCode.PARTIAL_SCOPE_STATE


def test_withdrawal_state_incoherent_active_cadence_when_removed() -> None:
    snap = _snapshot(
        state="NOT_APPLICABLE",
        generation=4,
        cadence_rows=(_cadence(activation_op=5, support_generation=3),),
        support_events=(
            _support_event(event_id=1, generation=3, state="SUPPORTED", operation_id=5),
            _support_event(
                event_id=2, generation=4, state="NOT_APPLICABLE", operation_id=6
            ),
        ),
    )
    decision = decide_administration(
        OperationType.PROMOTE_SCOPE, snap, active_global_blockers=()
    )
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


# --- Step 2: complete managed operation-lineage validation ------------------ #


def test_supported_event_operation_differs_from_cadence_activation() -> None:
    snap = _snapshot(
        generation=1,
        cadence_rows=(
            _cadence(cadence_config_id=10, activation_op=50, support_generation=1),
        ),
        support_events=(_support_event(generation=1, state="SUPPORTED", operation_id=51),),
        operations=(
            _admin_op(operation_id=50, generation_after=1),
            _admin_op(operation_id=51, generation_after=1),
        ),
    )
    _, code, detail = classify_scope_state(snap)
    assert code == ResultCode.PARTIAL_SCOPE_STATE
    assert "differs from cadence activation" in detail


def test_supported_referenced_activation_operation_absent() -> None:
    snap = _snapshot(
        generation=1,
        cadence_rows=(
            _cadence(cadence_config_id=10, activation_op=50, support_generation=1),
        ),
        support_events=(_support_event(generation=1, state="SUPPORTED", operation_id=50),),
        operations=(),  # operation 50 not present for this scope
    )
    _, code, detail = classify_scope_state(snap)
    assert code == ResultCode.PARTIAL_SCOPE_STATE
    assert "absent or bound to another scope" in detail


def test_supported_referenced_operation_nonterminal() -> None:
    snap = _snapshot(
        generation=1,
        cadence_rows=(
            _cadence(cadence_config_id=10, activation_op=50, support_generation=1),
        ),
        support_events=(_support_event(generation=1, state="SUPPORTED", operation_id=50),),
        operations=(_admin_op(operation_id=50, terminal=False, generation_after=1),),
    )
    _, code, _ = classify_scope_state(snap)
    assert code == ResultCode.COMMIT_STATUS_UNKNOWN


def test_supported_referenced_operation_wrong_type() -> None:
    snap = _snapshot(
        generation=1,
        cadence_rows=(
            _cadence(cadence_config_id=10, activation_op=50, support_generation=1),
        ),
        support_events=(_support_event(generation=1, state="SUPPORTED", operation_id=50),),
        operations=(
            _admin_op(
                operation_id=50,
                operation_type="REMOVE_SCOPE",
                result_code="REMOVED_SCOPE",
                generation_after=1,
            ),
        ),
    )
    _, code, _ = classify_scope_state(snap)
    assert code == ResultCode.PARTIAL_SCOPE_STATE


def test_supported_referenced_operation_wrong_result() -> None:
    snap = _snapshot(
        generation=1,
        cadence_rows=(
            _cadence(cadence_config_id=10, activation_op=50, support_generation=1),
        ),
        support_events=(_support_event(generation=1, state="SUPPORTED", operation_id=50),),
        operations=(
            _admin_op(
                operation_id=50,
                operation_type="PROMOTE_SCOPE",
                result_code="SCOPE_ALREADY_SUPPORTED",
                generation_after=1,
            ),
        ),
    )
    _, code, _ = classify_scope_state(snap)
    assert code == ResultCode.PARTIAL_SCOPE_STATE


def test_supported_operation_generation_after_mismatch() -> None:
    snap = _snapshot(
        generation=1,
        cadence_rows=(
            _cadence(cadence_config_id=10, activation_op=50, support_generation=1),
        ),
        support_events=(_support_event(generation=1, state="SUPPORTED", operation_id=50),),
        operations=(_admin_op(operation_id=50, generation_after=2),),
    )
    _, code, _ = classify_scope_state(snap)
    assert code == ResultCode.SUPPORT_GENERATION_MISMATCH


@pytest.mark.parametrize(
    ("operation_type", "result_code"),
    (
        ("ADOPT_LEGACY_SCOPE", "PROMOTED_NEW_SCOPE"),
        ("PROMOTE_SCOPE", "ADOPTED_LEGACY_SCOPE"),
    ),
)
def test_supported_rejects_impossible_operation_cross_pairings(
    operation_type: str,
    result_code: str,
) -> None:
    operation = _admin_op(
        operation_id=50,
        operation_type=operation_type,
        result_code=result_code,
        generation_before=None,
        generation_after=1,
    )
    _, code, _ = classify_scope_state(
        _supported_snapshot_with_operation(operation, generation=1)
    )
    assert code == ResultCode.PARTIAL_SCOPE_STATE


def test_supported_referenced_operation_result_class_must_be_success() -> None:
    operation = _admin_op(
        operation_id=50,
        result_class="IDEMPOTENT_SUCCESS",
        generation_before=None,
        generation_after=1,
    )
    _, code, _ = classify_scope_state(
        _supported_snapshot_with_operation(operation, generation=1)
    )
    assert code == ResultCode.PARTIAL_SCOPE_STATE


@pytest.mark.parametrize(
    ("generation_before", "generation_after", "scope_generation"),
    (
        (0, 1, 1),
        (None, 2, 2),
    ),
)
def test_adoption_requires_null_before_and_generation_one(
    generation_before: int | None,
    generation_after: int,
    scope_generation: int,
) -> None:
    operation = _admin_op(
        operation_id=50,
        operation_type="ADOPT_LEGACY_SCOPE",
        result_code="ADOPTED_LEGACY_SCOPE",
        generation_before=generation_before,
        generation_after=generation_after,
    )
    _, code, _ = classify_scope_state(
        _supported_snapshot_with_operation(operation, generation=scope_generation)
    )
    assert code == ResultCode.SUPPORT_GENERATION_MISMATCH


@pytest.mark.parametrize(
    ("generation_before", "generation_after", "scope_generation"),
    (
        (0, 1, 1),
        (None, 2, 2),
    ),
)
def test_new_promotion_requires_null_before_and_generation_one(
    generation_before: int | None,
    generation_after: int,
    scope_generation: int,
) -> None:
    operation = _admin_op(
        operation_id=50,
        operation_type="PROMOTE_SCOPE",
        result_code="PROMOTED_NEW_SCOPE",
        generation_before=generation_before,
        generation_after=generation_after,
    )
    _, code, _ = classify_scope_state(
        _supported_snapshot_with_operation(operation, generation=scope_generation)
    )
    assert code == ResultCode.SUPPORT_GENERATION_MISMATCH


def test_repromotion_requires_immediate_predecessor_generation() -> None:
    operation = _admin_op(
        operation_id=50,
        operation_type="PROMOTE_SCOPE",
        result_code="PROMOTED_FROM_PRIOR_WITHDRAWAL",
        generation_before=1,
        generation_after=3,
    )
    _, code, _ = classify_scope_state(
        _supported_snapshot_with_operation(operation, generation=3)
    )
    assert code == ResultCode.SUPPORT_GENERATION_MISMATCH


@pytest.mark.parametrize(
    "snapshot",
    (
        pytest.param(
            _supported_snapshot_with_operation(
                _admin_op(
                    operation_id=50,
                    operation_type="ADOPT_LEGACY_SCOPE",
                    result_code="ADOPTED_LEGACY_SCOPE",
                    generation_before=None,
                    generation_after=1,
                ),
                generation=1,
            ),
            id="adopt-legacy-scope",
        ),
        pytest.param(_managed_supported(1), id="promote-new-scope"),
        pytest.param(_managed_supported(3), id="promote-from-prior-withdrawal"),
        pytest.param(_managed_removed(2), id="remove-scope"),
    ),
)
def test_all_canonical_operation_tuples_are_valid(
    snapshot: ScopeStateSnapshot,
) -> None:
    classification, code, _ = classify_scope_state(snapshot)
    expected = (
        ScopeClassification.MANAGED_REMOVED
        if snapshot.scope_support_state == "NOT_APPLICABLE"
        else ScopeClassification.MANAGED_SUPPORTED
    )
    assert classification == expected
    assert code is None


def test_removed_event_operation_differs_from_cadence_deactivation() -> None:
    snap = _managed_removed(2)
    tampered = _snapshot(
        state="NOT_APPLICABLE",
        generation=2,
        reason_code=ADMIN_REMOVAL_REASON_CODE,
        cadence_rows=snap.cadence_rows,
        support_events=(
            _support_event(event_id=1, generation=1, state="SUPPORTED", operation_id=50),
            _support_event(event_id=2, generation=2, state="NOT_APPLICABLE", operation_id=99),
        ),
        operations=snap.operations,
    )
    _, code, detail = classify_scope_state(tampered)
    assert code == ResultCode.PARTIAL_SCOPE_STATE
    assert "differs from cadence deactivation" in detail


def test_removed_cadence_generation_skips_generations() -> None:
    # Scope generation 5 but withdrawn cadence generation 2 (skips generations).
    snap = _snapshot(
        state="NOT_APPLICABLE",
        generation=5,
        reason_code=ADMIN_REMOVAL_REASON_CODE,
        cadence_rows=(
            _cadence(
                cadence_config_id=10,
                is_active=0,
                activation_op=50,
                deactivation_op=60,
                support_generation=2,
                effective_to=datetime(2026, 7, 15),
            ),
        ),
        support_events=(
            _support_event(event_id=1, generation=2, state="SUPPORTED", operation_id=50),
            _support_event(event_id=2, generation=5, state="NOT_APPLICABLE", operation_id=60),
        ),
        operations=(
            _admin_op(operation_id=50, generation_after=2),
            _admin_op(
                operation_id=60,
                operation_type="REMOVE_SCOPE",
                result_code="REMOVED_SCOPE",
                generation_before=2,
                generation_after=5,
            ),
        ),
    )
    _, code, _ = classify_scope_state(snap)
    assert code == ResultCode.SUPPORT_GENERATION_MISMATCH


def test_removed_noncanonical_withdrawn_cadence_is_conflict() -> None:
    snap = _snapshot(
        state="NOT_APPLICABLE",
        generation=2,
        reason_code=ADMIN_REMOVAL_REASON_CODE,
        cadence_rows=(
            _cadence(
                cadence_config_id=10,
                is_active=0,
                activation_op=50,
                deactivation_op=60,
                support_generation=1,
                effective_to=datetime(2026, 7, 15),
                canonical_profile=False,
            ),
        ),
        support_events=(
            _support_event(event_id=1, generation=1, state="SUPPORTED", operation_id=50),
            _support_event(event_id=2, generation=2, state="NOT_APPLICABLE", operation_id=60),
        ),
        operations=(
            _admin_op(operation_id=50, generation_after=1),
            _admin_op(
                operation_id=60,
                operation_type="REMOVE_SCOPE",
                result_code="REMOVED_SCOPE",
                generation_before=1,
                generation_after=2,
            ),
        ),
    )
    _, code, _ = classify_scope_state(snap)
    assert code == ResultCode.CADENCE_PROFILE_CONFLICT


def test_removed_wrong_withdrawal_reason() -> None:
    snap = _managed_removed(2)
    tampered = _snapshot(
        state="NOT_APPLICABLE",
        generation=2,
        reason_code="MARKET_INVALIDATED",  # not the administration-removal reason
        cadence_rows=snap.cadence_rows,
        support_events=snap.support_events,
        operations=snap.operations,
    )
    _, code, _ = classify_scope_state(tampered)
    assert code == ResultCode.AUTHORITATIVE_WITHDRAWAL_STATE_INCOHERENT


def test_removed_operation_generation_before_mismatch() -> None:
    snap = _snapshot(
        state="NOT_APPLICABLE",
        generation=2,
        reason_code=ADMIN_REMOVAL_REASON_CODE,
        cadence_rows=(
            _cadence(
                cadence_config_id=10,
                is_active=0,
                activation_op=50,
                deactivation_op=60,
                support_generation=1,
                effective_to=datetime(2026, 7, 15),
            ),
        ),
        support_events=(
            _support_event(event_id=1, generation=1, state="SUPPORTED", operation_id=50),
            _support_event(event_id=2, generation=2, state="NOT_APPLICABLE", operation_id=60),
        ),
        operations=(
            _admin_op(operation_id=50, generation_after=1),
            _admin_op(
                operation_id=60,
                operation_type="REMOVE_SCOPE",
                result_code="REMOVED_SCOPE",
                generation_before=99,  # should be 1
                generation_after=2,
            ),
        ),
    )
    _, code, _ = classify_scope_state(snap)
    assert code == ResultCode.SUPPORT_GENERATION_MISMATCH


def test_fk_valid_but_logically_cross_wired_operation() -> None:
    # Operation row exists and is scope-bound (FK-valid) but its type/result is
    # for a different logical transition than the state it is wired into.
    snap = _snapshot(
        generation=1,
        cadence_rows=(
            _cadence(cadence_config_id=10, activation_op=60, support_generation=1),
        ),
        support_events=(_support_event(generation=1, state="SUPPORTED", operation_id=60),),
        operations=(
            _admin_op(
                operation_id=60,
                operation_type="REMOVE_SCOPE",
                result_code="REMOVED_SCOPE",
                generation_before=1,
                generation_after=2,
            ),
        ),
    )
    _, code, _ = classify_scope_state(snap)
    # A REMOVE operation wired as a SUPPORTED activation is rejected.
    assert code in (ResultCode.PARTIAL_SCOPE_STATE, ResultCode.SUPPORT_GENERATION_MISMATCH)


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
# Post-mutation revalidation binding (Blocker 3)                              #
# --------------------------------------------------------------------------- #


def test_post_state_bound_to_wrong_operation_id_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    decision = AdministrationDecision(
        action=OperationAction.PROMOTE_NEW,
        result_code=ResultCode.PROMOTED_NEW_SCOPE,
        result_class=txn.ResultClass.SUCCESS,
        support_generation_before=None,
        support_generation_after=1,
        target_cadence_config_id=None,
        classification=ScopeClassification.NO_SCOPE,
        detail="",
    )
    # The persisted cadence row's activation_operation_id points at a different
    # operation than the ledger row we just wrote.
    post = _snapshot(
        generation=1,
        cadence_rows=(
            _cadence(cadence_config_id=10, activation_op=999, support_generation=1),
        ),
        support_events=(_support_event(generation=1, state="SUPPORTED", operation_id=500),),
    )
    op = ExistingOperation(
        scope_admin_operation_id=500,
        operation_type=str(request.operation_type),
        metadata_digest=request.request_digest,
        completed_at_utc=datetime(2026, 7, 18, 10, 0),
        result_class="SUCCESS",
        result_code="PROMOTED_NEW_SCOPE",
        support_generation_before=None,
        support_generation_after=1,
        scope_key=request.scope_key.as_dict(),
    )
    monkeypatch.setattr(txn, "read_scope_state_snapshot", lambda *a, **k: post)
    monkeypatch.setattr(txn, "read_existing_operation", lambda *a, **k: op)
    with pytest.raises(txn._RevalidationError) as exc:
        txn._revalidate_post_state(
            None, request, decision, operation_id=500, now_utc=datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
        )
    assert exc.value.result_code == ResultCode.COMMIT_STATUS_UNKNOWN


# --------------------------------------------------------------------------- #
# Stateful fake connection for write-mode mechanics                           #
# --------------------------------------------------------------------------- #


_SHARED_LOCKS: set[str] = set()


class _FakeState:
    def __init__(self) -> None:
        self.writer_runs: list[dict[str, Any]] = []
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


def _op_error(code: int, message: str) -> Exception:
    import pymysql

    return pymysql.err.OperationalError(code, message)


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

        if "FROM native_short_materializer_run_v1" in norm and norm.startswith(
            "SELECT"
        ):
            if self._conn.fail_on == "writer_evidence_read":
                raise RuntimeError("injected unreadable writer evidence")
            self._rows = copy.deepcopy(state.writer_runs)
            return
        if "FROM native_short_scope_admin_operation_v1" in norm and norm.startswith(
            "SELECT"
        ):
            if "WHERE operation_uuid" in norm:
                uuid_val = params[0]
                self._rows = [
                    dict(op)
                    for op in state.operations
                    if op["operation_uuid"] == uuid_val
                ]
            elif "WHERE operation_type = 'PROMOTE_SCOPE'" in norm:
                self._rows = [
                    copy.deepcopy(op)
                    for op in state.operations
                    if op["operation_type"] == "PROMOTE_SCOPE"
                ]
            else:  # scope-keyed operation-lineage projection read
                self._rows = _match_scope(state.operations, params[:6])
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

    def _maybe_fail(self, target: str) -> None:
        if self._conn.fail_on == target:
            raise RuntimeError(f"injected {target} insert failure")
        if self._conn.db_error_on and self._conn.db_error_on[0] == target:
            raise _op_error(self._conn.db_error_on[1], "injected db error")

    def _insert_operation(self, params: tuple, state: _FakeState) -> None:
        self._maybe_fail("operation")
        for op in state.operations:
            if op["operation_uuid"] == params[0]:
                raise _op_error(1062, "duplicate operation_uuid")
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
        self._maybe_fail("scope")
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
                if row["scope_id"] == scope_id and row["scope_support_state"] == expected:
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
                if row["scope_id"] == scope_id and row["scope_support_state"] == expected:
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
                if row["scope_id"] == scope_id and row["support_generation"] is None:
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
        self._maybe_fail("support")
        generation = params[8]
        operation_id = params[7]
        for row in state.support:
            if (
                generation is not None
                and row["support_generation"] == generation
                and _same_scope(row, params[:6])
            ):
                raise _op_error(1062, "duplicate support generation")
            if operation_id and row["scope_admin_operation_id"] == operation_id:
                raise _op_error(1062, "duplicate support operation")
        state.support.append(
            {
                "scope_support_event_id": state.next_support_id,
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
        state.next_support_id += 1

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
        self.db_error_on: tuple[str, int] | None = None
        self.commit_behavior: str = "normal"  # normal | raise_before | raise_after

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
        if self.commit_behavior == "raise_before":
            raise _op_error(2013, "Lost connection to server during commit")
        if self.working is not None:
            self.committed = self.working
            self.working = None
        if self.commit_behavior == "raise_after":
            raise _op_error(2013, "Lost connection after server committed")

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


_AUTH = object()


@pytest.fixture(autouse=True)
def _stub_writer_authorization(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.operations.writer_capability_authorization_v1 as authmod

    monkeypatch.setattr(
        authmod,
        "require_writer_mutation_authorization",
        lambda authorization, capability_id: authorization,
    )


def _seed_supported(state: _FakeState, *, generation: int, symbol: str = "BTC") -> None:
    scope_id = state.next_scope_id
    state.next_scope_id += 1
    op_id = state.next_operation_id
    state.next_operation_id += 1
    cadence_id = state.next_cadence_id
    state.next_cadence_id += 1
    base = {
        "venue": "bitvavo",
        "symbol": symbol,
        "quote_currency": "EUR",
        "fib_trading_horizon": "SHORT",
        "primary_interval": "4h",
        "supporting_interval": "1h",
    }
    state.scopes.append(
        {
            **base,
            "scope_id": scope_id,
            "scope_support_state": "SUPPORTED",
            "scope_reason_code": None,
            "scope_reason_detail": None,
            "support_generation": generation,
        }
    )
    state.operations.append(
        {
            **base,
            "scope_admin_operation_id": op_id,
            "operation_uuid": f"seed-{symbol}-{generation}",
            "operation_type": "PROMOTE_SCOPE",
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
            **base,
            "cadence_config_id": cadence_id,
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
            **base,
            "scope_support_event_id": state.next_support_id,
            "scope_support_state": "SUPPORTED",
            "scope_admin_operation_id": op_id,
            "support_generation": generation,
        }
    )
    state.next_support_id += 1


def _other_uuid(suffix: str) -> str:
    return f"00000000-0000-4000-8000-0000000000{suffix}"


def test_write_promote_new_scope_commits_full_state() -> None:
    conn = _FakeConn()
    outcome = execute_scope_administration(
        conn, _request(), authorization=_AUTH, now_utc=datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
    )
    assert outcome.result.result_code == ResultCode.PROMOTED_NEW_SCOPE
    assert outcome.persisted is True
    assert outcome.commit_state == CommitState.COMMITTED
    assert conn.commit_count == 1
    assert len(conn.committed.scopes) == 1
    assert conn.committed.scopes[0]["support_generation"] == 1
    assert len(conn.committed.cadence) == 1
    assert conn.committed.cadence[0]["is_active"] == 1
    assert len(conn.committed.support) == 1
    assert len(conn.committed.operations) == 1
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
    assert second.commit_state == CommitState.ROLLED_BACK
    assert len(conn.committed.operations) == ops_after_first
    assert len(conn.committed.scopes) == 1


def test_write_already_supported_new_uuid_does_not_persist() -> None:
    state = _FakeState()
    _seed_supported(state, generation=1)
    conn = _FakeConn(state)
    outcome = execute_scope_administration(
        conn,
        _request(provenance=_provenance(operation_uuid=_other_uuid("aa"))),
        authorization=_AUTH,
    )
    assert outcome.result.result_code == ResultCode.SCOPE_ALREADY_SUPPORTED
    assert outcome.persisted is False
    assert outcome.commit_state == CommitState.ROLLED_BACK
    assert len(conn.committed.operations) == 1  # only the seed operation


def test_write_removal_then_repromotion_preserves_prior_rows() -> None:
    state = _FakeState()
    _seed_supported(state, generation=1)
    conn = _FakeConn(state)

    remove = execute_scope_administration(
        conn,
        _request(OperationType.REMOVE_SCOPE, provenance=_provenance(operation_uuid=_other_uuid("b1"))),
        authorization=_AUTH,
    )
    assert remove.result.result_code == ResultCode.REMOVED_SCOPE
    assert remove.commit_state == CommitState.COMMITTED
    assert conn.committed.scopes[0]["scope_support_state"] == "NOT_APPLICABLE"
    assert conn.committed.scopes[0]["support_generation"] == 2
    assert conn.committed.scopes[0]["scope_reason_code"] == ADMIN_REMOVAL_REASON_CODE
    assert all(row["is_active"] == 0 for row in conn.committed.cadence)

    repromote = execute_scope_administration(
        conn,
        _request(OperationType.PROMOTE_SCOPE, provenance=_provenance(operation_uuid=_other_uuid("b2"))),
        authorization=_AUTH,
    )
    assert repromote.result.result_code == ResultCode.PROMOTED_FROM_PRIOR_WITHDRAWAL
    assert conn.committed.scopes[0]["scope_support_state"] == "SUPPORTED"
    assert conn.committed.scopes[0]["support_generation"] == 3
    assert len(conn.committed.cadence) == 2
    assert sum(1 for r in conn.committed.cadence if r["is_active"] == 1) == 1
    assert len(conn.committed.support) == 3


def test_write_cleanup_writes_one_terminal_operation_row() -> None:
    # Blocker 1: repeat removal with removable residue writes exactly one
    # terminal operation row and performs only residue cleanup.
    state = _FakeState()
    _seed_supported(state, generation=1)
    conn = _FakeConn(state)
    execute_scope_administration(
        conn,
        _request(OperationType.REMOVE_SCOPE, provenance=_provenance(operation_uuid=_other_uuid("c1"))),
        authorization=_AUTH,
    )
    ops_after_remove = len(conn.committed.operations)
    support_after_remove = len(conn.committed.support)
    gen_after_remove = conn.committed.scopes[0]["support_generation"]
    # Simulate falsely-actionable derived residue reappearing.
    conn.committed.scope_status.append(
        {
            "venue": "bitvavo",
            "symbol": "BTC",
            "quote_currency": "EUR",
            "fib_trading_horizon": "SHORT",
            "primary_interval": "4h",
            "supporting_interval": "1h",
        }
    )

    cleanup = execute_scope_administration(
        conn,
        _request(OperationType.REMOVE_SCOPE, provenance=_provenance(operation_uuid=_other_uuid("c2"))),
        authorization=_AUTH,
    )
    assert cleanup.result.result_code == ResultCode.ALREADY_REMOVED_DERIVED_RESIDUE_CLEARED
    assert cleanup.persisted is True
    assert cleanup.commit_state == CommitState.COMMITTED
    # Exactly one new terminal operation row for the cleanup UUID.
    assert len(conn.committed.operations) == ops_after_remove + 1
    cleanup_op = next(
        op for op in conn.committed.operations if op["operation_uuid"] == _other_uuid("c2")
    )
    assert cleanup_op["completed_at_utc"] is not None
    assert cleanup_op["result_code"] == "ALREADY_REMOVED_DERIVED_RESIDUE_CLEARED"
    # No new support event, no generation increment.
    assert len(conn.committed.support) == support_after_remove
    assert conn.committed.scopes[0]["support_generation"] == gen_after_remove
    # Residue removed.
    assert conn.committed.scope_status == []


def test_write_cleanup_replay_performs_no_second_deletion() -> None:
    state = _FakeState()
    _seed_supported(state, generation=1)
    conn = _FakeConn(state)
    execute_scope_administration(
        conn,
        _request(OperationType.REMOVE_SCOPE, provenance=_provenance(operation_uuid=_other_uuid("d1"))),
        authorization=_AUTH,
    )
    conn.committed.scope_status.append(
        {
            "venue": "bitvavo", "symbol": "BTC", "quote_currency": "EUR",
            "fib_trading_horizon": "SHORT", "primary_interval": "4h",
            "supporting_interval": "1h",
        }
    )
    cleanup_request = _request(
        OperationType.REMOVE_SCOPE, provenance=_provenance(operation_uuid=_other_uuid("d2"))
    )
    execute_scope_administration(conn, cleanup_request, authorization=_AUTH)
    ops_after = len(conn.committed.operations)

    # Replay the same cleanup UUID/digest: operation-ledger idempotent, no second
    # deletion or ledger row.
    replay = execute_scope_administration(conn, cleanup_request, authorization=_AUTH)
    assert replay.result.result_code == ResultCode.OPERATION_ALREADY_COMPLETED
    assert replay.persisted is False
    assert len(conn.committed.operations) == ops_after


def test_write_cleanup_changed_digest_conflicts() -> None:
    state = _FakeState()
    _seed_supported(state, generation=1)
    conn = _FakeConn(state)
    execute_scope_administration(
        conn,
        _request(OperationType.REMOVE_SCOPE, provenance=_provenance(operation_uuid=_other_uuid("e1"))),
        authorization=_AUTH,
    )
    conn.committed.scope_status.append(
        {
            "venue": "bitvavo", "symbol": "BTC", "quote_currency": "EUR",
            "fib_trading_horizon": "SHORT", "primary_interval": "4h",
            "supporting_interval": "1h",
        }
    )
    uuid = _other_uuid("e2")
    execute_scope_administration(
        conn,
        _request(OperationType.REMOVE_SCOPE, provenance=_provenance(operation_uuid=uuid), metadata={"k": "v1"}),
        authorization=_AUTH,
    )
    conflict = execute_scope_administration(
        conn,
        _request(OperationType.REMOVE_SCOPE, provenance=_provenance(operation_uuid=uuid), metadata={"k": "v2"}),
        authorization=_AUTH,
    )
    assert conflict.result.result_code == ResultCode.OPERATION_METADATA_MISMATCH
    assert conflict.persisted is False


def test_write_no_residue_repeat_removal_performs_no_write() -> None:
    state = _FakeState()
    _seed_supported(state, generation=1)
    conn = _FakeConn(state)
    execute_scope_administration(
        conn,
        _request(OperationType.REMOVE_SCOPE, provenance=_provenance(operation_uuid=_other_uuid("f1"))),
        authorization=_AUTH,
    )
    ops_after_remove = len(conn.committed.operations)
    repeat = execute_scope_administration(
        conn,
        _request(OperationType.REMOVE_SCOPE, provenance=_provenance(operation_uuid=_other_uuid("f2"))),
        authorization=_AUTH,
    )
    assert repeat.result.result_code == ResultCode.SCOPE_ALREADY_REMOVED
    assert repeat.persisted is False
    assert repeat.commit_state == CommitState.ROLLED_BACK
    assert len(conn.committed.operations) == ops_after_remove


# --------------------------------------------------------------------------- #
# GLOBAL_BLOCKERS_ACTIVE gate: authoritative transaction-path enforcement      #
# --------------------------------------------------------------------------- #
#
# These tests exercise the real, authoritative execute_scope_administration /
# plan_scope_administration entrypoints (not the pure decide_administration
# function directly), monkeypatching only the module-level
# evaluate_current_global_blockers read seam -- the same established
# dependency-injection pattern already used for read_scope_state_snapshot /
# _insert_support_event elsewhere in this file. No boolean bypass flag and no
# caller-supplied "blockers clear" parameter exists on either public function.


def _stub_active_global_blockers(
    monkeypatch: pytest.MonkeyPatch, codes: tuple[str, ...]
) -> None:
    monkeypatch.setattr(
        txn, "evaluate_current_global_blockers", lambda conn: (codes, {})
    )


def test_execute_promote_blocked_causes_zero_scope_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_active_global_blockers(monkeypatch, ("PROMOTION_CONTRACT_MISSING",))
    conn = _FakeConn()
    outcome = execute_scope_administration(conn, _request(), authorization=_AUTH)
    assert outcome.result.result_code == ResultCode.GLOBAL_BLOCKERS_ACTIVE
    assert str(outcome.result.result_class) == "BLOCKED"
    assert outcome.persisted is False
    assert outcome.commit_state == CommitState.ROLLED_BACK
    # Zero scope-state mutation and zero materialization/backfill: nothing at
    # all was written to any table, including the operation ledger (a blocked
    # attempt is not normally ledgered, matching every other REJECT outcome).
    assert conn.committed.scopes == []
    assert conn.committed.cadence == []
    assert conn.committed.support == []
    assert conn.committed.operations == []
    assert conn.commit_count == 0
    assert not conn.held_locks
    assert not _SHARED_LOCKS


def test_execute_promote_blocked_exposes_deterministic_sorted_blocker_codes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_active_global_blockers(
        monkeypatch,
        ("WRITER_PROVENANCE_UNATTRIBUTED", "PROMOTION_CONTRACT_MISSING"),
    )
    conn = _FakeConn()
    outcome = execute_scope_administration(conn, _request(), authorization=_AUTH)
    assert outcome.current_state["blocking_global_blockers"] == [
        "PROMOTION_CONTRACT_MISSING",
        "WRITER_PROVENANCE_UNATTRIBUTED",
    ]


def test_execute_adopt_blocked_by_writer_provenance_causes_zero_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_active_global_blockers(monkeypatch, ("WRITER_PROVENANCE_UNATTRIBUTED",))
    state = _FakeState()
    conn = _FakeConn(state)
    base = {
        "venue": "bitvavo", "symbol": "BTC", "quote_currency": "EUR",
        "fib_trading_horizon": "SHORT", "primary_interval": "4h",
        "supporting_interval": "1h",
    }
    state.scopes.append({
        **base, "scope_id": 1, "scope_support_state": "SUPPORTED",
        "scope_reason_code": None, "scope_reason_detail": None,
        "support_generation": None,
    })
    state.cadence.append({
        **base, "cadence_config_id": 10,
        "cadence_contract_version": CANONICAL_CADENCE_CONTRACT_VERSION,
        "target_evaluation_interval": CANONICAL_TARGET_EVALUATION_INTERVAL,
        "primary_source_freshness_limit_seconds": CANONICAL_PRIMARY_SOURCE_FRESHNESS_LIMIT_SECONDS,
        "supporting_source_freshness_limit_seconds": CANONICAL_SUPPORTING_SOURCE_FRESHNESS_LIMIT_SECONDS,
        "evaluation_grace_seconds": CANONICAL_EVALUATION_GRACE_SECONDS,
        "recent_scope_grace_seconds": CANONICAL_RECENT_SCOPE_GRACE_SECONDS,
        "effective_from_utc": datetime(2026, 7, 1, 0, 0), "effective_to_utc": None,
        "is_active": 1, "activation_operation_id": None,
        "deactivation_operation_id": None, "support_generation": None,
    })
    outcome = execute_scope_administration(
        conn,
        _request(OperationType.ADOPT_LEGACY_SCOPE),
        authorization=_AUTH,
    )
    assert outcome.result.result_code == ResultCode.GLOBAL_BLOCKERS_ACTIVE
    assert outcome.persisted is False
    assert len(conn.committed.operations) == 0
    assert conn.committed.scopes[0]["support_generation"] is None  # unchanged


def test_execute_remove_blocked_by_removal_contract_missing_causes_zero_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _FakeState()
    _seed_supported(state, generation=1)
    conn = _FakeConn(state)
    ops_before = len(conn.committed.operations)
    scopes_before = copy.deepcopy(conn.committed.scopes)

    _stub_active_global_blockers(monkeypatch, ("REMOVAL_CONTRACT_MISSING",))
    outcome = execute_scope_administration(
        conn,
        _request(OperationType.REMOVE_SCOPE, provenance=_provenance(operation_uuid=_other_uuid("c1"))),
        authorization=_AUTH,
    )
    assert outcome.result.result_code == ResultCode.GLOBAL_BLOCKERS_ACTIVE
    assert outcome.persisted is False
    assert len(conn.committed.operations) == ops_before
    assert conn.committed.scopes == scopes_before


def test_execute_remove_not_blocked_by_unrelated_blockers_still_removes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Proves removal/rollback safety is not incidentally broken by this gate:
    # a REMOVE_SCOPE unaffected by its applicable blocker set still commits.
    state = _FakeState()
    _seed_supported(state, generation=1)
    conn = _FakeConn(state)
    _stub_active_global_blockers(
        monkeypatch,
        (
            "PROMOTION_CONTRACT_MISSING",
            "BOOTSTRAP_ORCHESTRATION_BLOCKED",
            "MULTI_SCOPE_FAILURE_ISOLATION_MISSING",
        ),
    )
    outcome = execute_scope_administration(
        conn,
        _request(OperationType.REMOVE_SCOPE, provenance=_provenance(operation_uuid=_other_uuid("c2"))),
        authorization=_AUTH,
    )
    assert outcome.result.result_code == ResultCode.REMOVED_SCOPE
    assert outcome.persisted is True
    assert outcome.commit_state == CommitState.COMMITTED


def test_execute_replay_of_completed_operation_is_unaffected_by_active_blockers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Replay behavior remains deterministic: a previously completed operation
    # is not re-decided against current blocker state (nothing new is being
    # authorized -- the terminal ledger row is already the authority).
    conn = _FakeConn()
    request = _request()
    first = execute_scope_administration(conn, request, authorization=_AUTH)
    assert first.persisted is True

    _stub_active_global_blockers(monkeypatch, ("PROMOTION_CONTRACT_MISSING",))
    second = execute_scope_administration(conn, request, authorization=_AUTH)
    assert second.result.result_code == ResultCode.OPERATION_ALREADY_COMPLETED
    assert second.persisted is False
    assert second.commit_state == CommitState.ROLLED_BACK


def test_execute_direct_invocation_cannot_bypass_gate_via_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # execute_scope_administration takes no blocker-state parameter; a direct
    # caller cannot pass "blockers clear" through the public signature.
    import inspect

    signature = inspect.signature(execute_scope_administration)
    assert "active_global_blockers" not in signature.parameters
    assert "global_blockers_clear" not in signature.parameters
    _stub_active_global_blockers(monkeypatch, ("PROMOTION_CONTRACT_MISSING",))
    conn = _FakeConn()
    outcome = execute_scope_administration(conn, _request(), authorization=_AUTH)
    assert outcome.result.result_code == ResultCode.GLOBAL_BLOCKERS_ACTIVE


def test_plan_dry_run_reflects_blocked_state_without_any_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_active_global_blockers(monkeypatch, ("PROMOTION_CONTRACT_MISSING",))
    conn = _FakeConn()
    outcome = plan_scope_administration(conn, _request())
    assert outcome.mode == txn.TransactionMode.DRY_RUN
    assert outcome.write is False
    assert outcome.result.result_code == ResultCode.GLOBAL_BLOCKERS_ACTIVE
    assert conn.committed.scopes == []
    assert conn.committed.operations == []


def test_missing_blocker_evidence_fails_closed_via_default_evaluator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Simulate the canonical evaluator's own fail-closed contract: absent
    # writer-provenance/promotion evidence must surface as active blockers,
    # not as a silently-cleared/empty tuple. This proves the transaction path
    # actually calls through to (and is gated by) whatever the canonical
    # evaluator determines, not a permissive stand-in.
    def _fail_closed_missing_evidence(conn: Any) -> tuple[tuple[str, ...], dict[str, str]]:
        return (
            ("WRITER_PROVENANCE_UNATTRIBUTED", "PROMOTION_CONTRACT_MISSING"),
            {"WRITER_PROVENANCE_UNATTRIBUTED": "EVIDENCE_ABSENT_OR_INVALID"},
        )

    monkeypatch.setattr(
        txn, "evaluate_current_global_blockers", _fail_closed_missing_evidence
    )
    conn = _FakeConn()
    outcome = execute_scope_administration(conn, _request(), authorization=_AUTH)
    assert outcome.result.result_code == ResultCode.GLOBAL_BLOCKERS_ACTIVE
    assert outcome.persisted is False


def test_malformed_blocker_evidence_read_failure_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # If the canonical evaluator's read path itself raises (malformed/
    # unreadable evidence), the transaction must roll back and report a typed
    # failure rather than proceed as if no blockers were active.
    def _raise(conn: Any) -> tuple[tuple[str, ...], dict[str, str]]:
        raise RuntimeError("simulated malformed blocker evidence")

    monkeypatch.setattr(txn, "evaluate_current_global_blockers", _raise)
    conn = _FakeConn()
    with pytest.raises(NativeShortScopeAdministrationExecutionError):
        execute_scope_administration(conn, _request(), authorization=_AUTH)
    assert conn.committed.scopes == []
    assert conn.committed.operations == []
    assert conn.commit_count == 0


def test_cli_write_blocked_by_active_global_blocker_persists_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_write_auth(monkeypatch)
    conn = _FakeConn()
    code, raw_out, _ = _run_cli_raw(
        monkeypatch,
        [*_BASE_CLI_ARGS, "--write"],
        conn=conn,
        global_blockers=("PROMOTION_CONTRACT_MISSING",),
    )
    doc = _assert_single_json_stdout(raw_out)
    assert doc["result_code"] == "GLOBAL_BLOCKERS_ACTIVE"
    assert conn.committed.scopes == []
    assert conn.committed.operations == []


def test_cli_dry_run_blocked_reports_without_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeConn()
    argv = list(_BASE_CLI_ARGS)
    argv[argv.index("--operation") + 1] = "REMOVE_SCOPE"
    code, stdout_docs, _ = _run_cli(
        monkeypatch, argv, conn=conn, global_blockers=("REMOVAL_CONTRACT_MISSING",)
    )
    assert stdout_docs[0]["result_code"] == "GLOBAL_BLOCKERS_ACTIVE"
    assert conn.committed.scopes == []


# --- Blocker 2: commit-state contract --------------------------------------- #


def test_write_commit_success_is_committed() -> None:
    conn = _FakeConn()
    outcome = execute_scope_administration(conn, _request(), authorization=_AUTH)
    assert outcome.commit_state == CommitState.COMMITTED
    assert outcome.persisted is True


def test_write_commit_raises_is_unknown_without_rollback_claim() -> None:
    conn = _FakeConn()
    conn.commit_behavior = "raise_before"
    outcome = execute_scope_administration(conn, _request(), authorization=_AUTH)
    assert outcome.result.result_code == ResultCode.COMMIT_STATUS_UNKNOWN
    assert outcome.commit_state == CommitState.UNKNOWN
    # Unknown commit does not assert rollback certainty nor persisted=false.
    assert outcome.persisted is None
    assert conn.rollback_count == 0
    # current_state must not carry the authoritative pre-mutation snapshot.
    assert outcome.current_state.get("state_unknown") is True
    assert "scope_present" not in outcome.current_state
    # The operation id is labelled attempted/unverified, not proven persisted.
    assert outcome.scope_admin_operation_id is None
    assert "attempted_operation_id_unverified" in outcome.current_state
    assert not _SHARED_LOCKS  # lock still released in finally


def test_write_unknown_commit_then_retry_resolves_via_ledger() -> None:
    # Simulate the server committing but the client losing the connection at the
    # commit boundary; a retry resolves through the operation ledger.
    conn = _FakeConn()
    conn.commit_behavior = "raise_after"
    request = _request()
    first = execute_scope_administration(conn, request, authorization=_AUTH)
    assert first.commit_state == CommitState.UNKNOWN
    assert len(conn.committed.operations) == 1  # server-side commit landed

    conn.commit_behavior = "normal"
    retry = execute_scope_administration(conn, request, authorization=_AUTH)
    assert retry.result.result_code == ResultCode.OPERATION_ALREADY_COMPLETED
    assert retry.persisted is False


def test_write_deadlock_before_commit_maps_typed_and_rolls_back() -> None:
    conn = _FakeConn()
    conn.db_error_on = ("scope", 1213)
    outcome = execute_scope_administration(conn, _request(), authorization=_AUTH)
    assert outcome.result.result_code == ResultCode.DEADLOCK
    assert outcome.commit_state == CommitState.ROLLED_BACK
    assert outcome.persisted is False
    assert conn.committed.scopes == []
    assert conn.committed.operations == []
    assert not _SHARED_LOCKS


def test_write_lock_wait_timeout_before_commit_maps_typed() -> None:
    conn = _FakeConn()
    conn.db_error_on = ("scope", 1205)
    outcome = execute_scope_administration(conn, _request(), authorization=_AUTH)
    assert outcome.result.result_code == ResultCode.LOCK_TIMEOUT
    assert outcome.commit_state == CommitState.ROLLED_BACK


def test_write_unmapped_precommit_failure_raises_typed_rolled_back() -> None:
    # Step 3: an unexpected mutation failure after begin is rolled back and
    # surfaced as a typed execution error carrying commit_state=ROLLED_BACK and
    # persisted=False, preserving the original defect as __cause__.
    conn = _FakeConn()
    conn.fail_on = "support"
    with pytest.raises(NativeShortScopeAdministrationExecutionError) as exc:
        execute_scope_administration(conn, _request(), authorization=_AUTH)
    assert exc.value.commit_state == CommitState.ROLLED_BACK
    assert exc.value.persisted is False
    assert isinstance(exc.value.__cause__, RuntimeError)
    assert "injected support insert failure" in str(exc.value.__cause__)
    assert conn.rollback_count >= 1
    assert conn.committed.scopes == []
    assert conn.committed.operations == []
    assert not _SHARED_LOCKS


def test_write_advisory_lock_timeout_maps_to_retryable() -> None:
    conn = _FakeConn()
    _SHARED_LOCKS.add(advisory_lock_name(_key().as_dict()))
    outcome = execute_scope_administration(conn, _request(), authorization=_AUTH)
    assert outcome.result.result_code == ResultCode.LOCK_TIMEOUT
    assert outcome.persisted is False
    assert outcome.commit_state == CommitState.ROLLED_BACK
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
    assert conn.begin_count == 0
    assert conn.committed.scopes == []


def test_dry_run_performs_no_writes_and_no_transaction() -> None:
    conn = _FakeConn()
    outcome = plan_scope_administration(conn, _request())
    assert outcome.mode == txn.TransactionMode.DRY_RUN
    assert outcome.commit_state == CommitState.NOT_ATTEMPTED
    assert outcome.result.result_code == ResultCode.PROMOTED_NEW_SCOPE
    assert outcome.persisted is False
    assert conn.begin_count == 0
    assert conn.commit_count == 0
    assert all(not e.startswith("INSERT") for e in conn.executions)
    assert all(not e.startswith("UPDATE") for e in conn.executions)
    assert all(not e.startswith("DELETE") for e in conn.executions)
    assert all("FOR UPDATE" not in e for e in conn.executions)


def test_dry_run_fails_closed_on_incoherent_state() -> None:
    state = _FakeState()
    _seed_supported(state, generation=1)
    state.cadence.append(dict(state.cadence[0], cadence_config_id=999))
    conn = _FakeConn(state)
    outcome = plan_scope_administration(conn, _request(OperationType.REMOVE_SCOPE))
    assert outcome.result.result_code == ResultCode.MULTIPLE_ACTIVE_CADENCE_ROWS
    assert outcome.persisted is False


# --------------------------------------------------------------------------- #
# CLI tests — one-document stdout contract                                    #
# --------------------------------------------------------------------------- #


from src.market_data import run_native_short_scope_administration_v1 as cli
from src.market_data.native_short_repository_source_identity_v1 import (
    NativeShortRepositorySourceState,
)


_BASE_CLI_ARGS = [
    "--symbol", "BTC",
    "--operation", "PROMOTE_SCOPE",
    "--actor-type", "HUMAN_OPERATOR",
    "--actor-id", "operator-1",
    "--trigger-type", "MANUAL_CLI",
    "--reason", "explicit review",
    "--operation-uuid", "00000000-0000-4000-8000-00000000c001",
    "--request-source", "cli-test",
    "--repository-commit", "a" * 40,
    "--trigger-ref", "admin-cli-test",
    "--requested-at-utc", "2026-07-18T10:00:00Z",
]


def _clean_source() -> NativeShortRepositorySourceState:
    return NativeShortRepositorySourceState(head_sha="a" * 40, status_porcelain="")


def _run_cli(
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
    *,
    conn: _FakeConn | None,
    global_blockers: tuple[str, ...] = (),
) -> tuple[int, list[dict[str, Any]], list[dict[str, Any]]]:
    import src.common.db as dbmod

    # This helper's own monkeypatch.undo() below reverts every patch applied
    # via this monkeypatch fixture, including the module-level autouse
    # _default_no_global_blockers patch, so re-apply it here for every call
    # (this helper may be invoked more than once per test).
    monkeypatch.setattr(
        txn, "evaluate_current_global_blockers", lambda conn: (global_blockers, {})
    )
    if conn is not None:
        monkeypatch.setattr(dbmod, "get_connection", lambda: conn)
    out, err = io.StringIO(), io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    monkeypatch.setattr("sys.stderr", err)
    code = cli.main(argv, inspect_repository_source=_clean_source)
    monkeypatch.undo()
    stdout_docs = [json.loads(x) for x in out.getvalue().splitlines() if x.strip()]
    stderr_docs = [json.loads(x) for x in err.getvalue().splitlines() if x.strip()]
    return code, stdout_docs, stderr_docs


def test_cli_help_exits_zero() -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0


def test_cli_dry_run_is_default_and_emits_exactly_one_stdout_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeConn()
    code, stdout_docs, stderr_docs = _run_cli(monkeypatch, _BASE_CLI_ARGS, conn=conn)
    assert code == 0
    assert len(stdout_docs) == 1  # exactly one JSON result document on stdout
    result = stdout_docs[0]
    assert result["event"] == "RESULT"
    assert result["mode"] == "DRY_RUN"
    assert result["commit_state"] == "NOT_ATTEMPTED"
    assert result["persisted"] is False
    assert result["result_code"] == "PROMOTED_NEW_SCOPE"
    for marker in (
        "broker_private_calls", "broker_writes", "order_submission", "live_orders",
        "systemd_changes", "timer_changes", "runtime_activation", "host_mutations",
    ):
        assert marker in result
    # Progress went to stderr, not stdout.
    assert any(doc.get("event") == "STARTED" for doc in stderr_docs)
    assert conn.commit_count == 0


def _stub_write_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.operations.writer_capability_authorization_v1 as authmod

    monkeypatch.setattr(
        authmod, "enforce_capability_write_authorization",
        lambda capability_id, **kwargs: _AUTH,
    )
    monkeypatch.setattr(
        authmod, "require_writer_mutation_authorization",
        lambda authorization, capability_id: authorization,
    )


def _run_cli_raw(
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
    *,
    conn: _FakeConn,
    global_blockers: tuple[str, ...] = (),
) -> tuple[int, str, str]:
    import src.common.db as dbmod

    # See _run_cli: re-apply the blocker-stub seam per call for the same reason.
    monkeypatch.setattr(
        txn, "evaluate_current_global_blockers", lambda conn: (global_blockers, {})
    )
    monkeypatch.setattr(dbmod, "get_connection", lambda: conn)
    out, err = io.StringIO(), io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    monkeypatch.setattr("sys.stderr", err)
    code = cli.main(argv, inspect_repository_source=_clean_source)
    monkeypatch.undo()
    return code, out.getvalue(), err.getvalue()


def _assert_single_json_stdout(raw_stdout: str) -> dict[str, Any]:
    lines = raw_stdout.splitlines()
    nonempty = [line for line in lines if line.strip()]
    assert len(nonempty) == 1, f"expected one stdout document, got {nonempty!r}"
    return json.loads(nonempty[0])  # raises if any unexpected plaintext


def test_cli_write_is_explicit_and_persists(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_write_auth(monkeypatch)
    conn = _FakeConn()
    code, stdout_docs, _ = _run_cli(monkeypatch, [*_BASE_CLI_ARGS, "--write"], conn=conn)
    assert code == 0
    assert len(stdout_docs) == 1
    result = stdout_docs[0]
    assert result["mode"] == "WRITE"
    assert result["persisted"] is True
    assert result["commit_state"] == "COMMITTED"
    assert result["result_code"] == "PROMOTED_NEW_SCOPE"
    assert result["production_db_writes"] == 1
    assert conn.commit_count == 1


def test_cli_validation_failure_is_not_attempted_one_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Invalid request before any connection/transaction => NOT_ATTEMPTED.
    args = list(_BASE_CLI_ARGS)
    args[args.index("--operation-uuid") + 1] = "not-a-uuid"
    code, raw_out, _ = _run_cli_raw(monkeypatch, [*args, "--write"], conn=_FakeConn())
    doc = _assert_single_json_stdout(raw_out)
    assert code == 2
    assert doc["event"] == "FAILED"
    assert doc["commit_state"] == "NOT_ATTEMPTED"
    assert doc["reason_code"] == "INVALID_REQUEST"


def test_cli_write_injected_mutation_failure_is_rolled_back_one_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_write_auth(monkeypatch)
    conn = _FakeConn()
    conn.fail_on = "support"
    code, raw_out, _ = _run_cli_raw(monkeypatch, [*_BASE_CLI_ARGS, "--write"], conn=conn)
    doc = _assert_single_json_stdout(raw_out)
    assert code == 1
    assert doc["event"] == "FAILED"
    assert doc["commit_state"] == "ROLLED_BACK"
    assert doc["persisted"] is False
    assert conn.committed.operations == []


def test_cli_write_deadlock_before_commit_is_rolled_back_one_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_write_auth(monkeypatch)
    conn = _FakeConn()
    conn.db_error_on = ("scope", 1213)
    code, raw_out, _ = _run_cli_raw(monkeypatch, [*_BASE_CLI_ARGS, "--write"], conn=conn)
    doc = _assert_single_json_stdout(raw_out)
    assert code == 1
    assert doc["result_code"] == "DEADLOCK"
    assert doc["commit_state"] == "ROLLED_BACK"


def test_cli_write_commit_exception_is_unknown_one_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_write_auth(monkeypatch)
    conn = _FakeConn()
    conn.commit_behavior = "raise_before"
    code, raw_out, _ = _run_cli_raw(monkeypatch, [*_BASE_CLI_ARGS, "--write"], conn=conn)
    doc = _assert_single_json_stdout(raw_out)
    assert code == 1
    assert doc["result_code"] == "COMMIT_STATUS_UNKNOWN"
    assert doc["commit_state"] == "UNKNOWN"
    assert doc["persisted"] is None
    assert doc["current_state"].get("state_unknown") is True


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
    out, err = io.StringIO(), io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    monkeypatch.setattr("sys.stderr", err)
    code = cli.main([*_BASE_CLI_ARGS, "--write"], inspect_repository_source=_dirty)
    monkeypatch.undo()
    stdout_docs = [json.loads(x) for x in out.getvalue().splitlines() if x.strip()]
    assert code == 2
    assert len(stdout_docs) == 1
    assert stdout_docs[0]["event"] == "FAILED"
    assert stdout_docs[0]["reason_code"] == "INVALID_REPOSITORY_SOURCE"
    assert conn.begin_count == 0


def test_cli_write_auth_denial_emits_one_json_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.operations.writer_capability_authorization_v1 as authmod

    def _deny(capability_id: str, **kwargs: Any) -> Any:
        raise authmod.AuthorizationDenied(
            capability_id, authmod.ExecutionMode.READ_ONLY, ["not authorized"]
        )

    monkeypatch.setattr(authmod, "enforce_capability_write_authorization", _deny)
    conn = _FakeConn()
    code, stdout_docs, _ = _run_cli(monkeypatch, [*_BASE_CLI_ARGS, "--write"], conn=conn)
    assert code == 3
    assert len(stdout_docs) == 1
    assert stdout_docs[0]["event"] == "FAILED"
    assert stdout_docs[0]["reason_code"] == "WRITER_AUTHORIZATION_DENIED"
    assert conn.begin_count == 0


def test_cli_rejects_multi_symbol_and_wildcards(monkeypatch: pytest.MonkeyPatch) -> None:
    for bad in ("BTC,ETH", "*", "BTC ETH"):
        args = list(_BASE_CLI_ARGS)
        args[1] = bad
        code, stdout_docs, _ = _run_cli(monkeypatch, args, conn=None)
        assert code == 2
        assert len(stdout_docs) == 1
        assert stdout_docs[0]["event"] == "FAILED"


def test_cli_requires_explicit_provenance() -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(
            ["--symbol", "BTC", "--operation", "PROMOTE_SCOPE", "--actor-type", "HUMAN_OPERATOR"]
        )
    assert exc.value.code != 0


def test_cli_result_json_is_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    conn1 = _FakeConn()
    _, docs1, _ = _run_cli(monkeypatch, _BASE_CLI_ARGS, conn=conn1)
    conn2 = _FakeConn()
    _, docs2, _ = _run_cli(monkeypatch, _BASE_CLI_ARGS, conn=conn2)
    assert json.dumps(docs1[0], sort_keys=True) == json.dumps(docs2[0], sort_keys=True)


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
        "selection", "decision_gate", "execution_planner", "executor",
        "broker", "src.account", "wallet", "reporting", ".order",
    )
    for module_name in _imports(path):
        assert not any(
            token in module_name for token in forbidden
        ), f"forbidden dependency import: {module_name}"


# --------------------------------------------------------------------------- #
# Opt-in isolated-MariaDB integration tests                                   #
# --------------------------------------------------------------------------- #


BASE_MIGRATION = Path("db/migrations/20260626_native_short_map_lifecycle_v1.sql")
STATUS_MIGRATION = Path(
    "db/migrations/20260706_native_short_scope_status_persistence_v1.sql"
)
LEVEL_MIGRATION = Path("db/migrations/20260708_native_short_map_level_status_v1.sql")
CADENCE_UNAVAILABLE_MIGRATION = Path(
    "db/migrations/20260707_native_short_cadence_unavailable_v1.sql"
)
ADMIN_MIGRATION = Path(
    "db/migrations/20260718_native_short_scope_administration_v1.sql"
)
TEMP_DB_PREFIX = "synth_native_short_scope_admin_txn_v1_tmp"
_PRODUCTION_DB_NAMES = frozenset({"synth"})

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
    config = {name: os.environ[name] for name in _REQUIRED_ENV}
    # Verify the DB target name explicitly: never point at the production schema.
    if config["SYNTH_TEST_MARIADB_ADMIN_DATABASE"] in _PRODUCTION_DB_NAMES:
        pytest.fail("refusing to run against a production database name")
    return config


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
    assert database not in _PRODUCTION_DB_NAMES and database.startswith(TEMP_DB_PREFIX)
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
            CADENCE_UNAVAILABLE_MIGRATION,
            LEVEL_MIGRATION,
            ADMIN_MIGRATION,
        ):
            with connection.cursor() as cursor:
                for statement in _split_sql_statements(path.read_text(encoding="utf-8")):
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


def _mariadb_request(operation: OperationType, uuid: str, *, symbol: str = "BTC", metadata=None):
    return _request(
        operation, symbol=symbol, provenance=_provenance(operation_uuid=uuid), metadata=metadata
    )


@pytest.fixture
def _mariadb_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.operations.writer_capability_authorization_v1 as authmod

    monkeypatch.setattr(
        authmod, "require_writer_mutation_authorization",
        lambda authorization, capability_id: authorization,
    )


def _seed_legacy_scope(conn: Any, symbol: str = "BTC") -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO native_short_map_scope_v1 (
                venue, symbol, quote_currency, fib_trading_horizon,
                primary_interval, supporting_interval, scope_support_state
            ) VALUES ('bitvavo', %s, 'EUR', 'SHORT', '4h', '1h', 'SUPPORTED')
            """,
            (symbol,),
        )
        cur.execute(
            """
            INSERT INTO native_short_scope_support_event_v1 (
                venue, symbol, quote_currency, fib_trading_horizon,
                primary_interval, supporting_interval, scope_support_state,
                event_ts_utc, reason_code, source_name, source_version
            ) VALUES (
                'bitvavo', %s, 'EUR', 'SHORT', '4h', '1h', 'SUPPORTED',
                '2026-07-01 00:00:00', 'LEGACY', 'legacy_fixture', 'v1'
            )
            """,
            (symbol,),
        )
        cur.execute(
            """
            INSERT INTO native_short_scope_cadence_config_v1 (
                venue, symbol, quote_currency, fib_trading_horizon,
                primary_interval, supporting_interval, cadence_contract_version,
                target_evaluation_interval,
                primary_source_freshness_limit_seconds,
                supporting_source_freshness_limit_seconds,
                evaluation_grace_seconds, recent_scope_grace_seconds,
                effective_from_utc, effective_to_utc, is_active
            ) VALUES (
                'bitvavo', %s, 'EUR', 'SHORT', '4h', '1h', 'native_short_cadence_v1',
                '1h', 43200, 10800, 900, 3600, '2026-07-01 00:00:00', NULL, 1
            )
            """,
            (symbol,),
        )
    conn.commit()


def _insert_scope_status_residue(conn: Any, symbol: str = "BTC") -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO native_short_scope_status_v1 (
                venue, symbol, quote_currency, fib_trading_horizon,
                primary_interval, supporting_interval, scope_support_state,
                scope_status_code, map_lifecycle_state, observation_freshness_state,
                source_freshness_state, actionability_state,
                primary_source_freshness_limit_seconds,
                supporting_source_freshness_limit_seconds,
                cadence_contract_version, projection_as_of_utc
            ) VALUES (
                'bitvavo', %s, 'EUR', 'SHORT', '4h', '1h', 'SUPPORTED',
                'CURRENT_EVALUATION', 'NO_CURRENT_MAP', 'NO_OBSERVATION',
                'SOURCE_CURRENT', 'NO_ACTIONABLE_MAP', 43200, 10800,
                'native_short_cadence_v1', '2026-07-18 10:00:00'
            )
            """,
            (symbol,),
        )
    conn.commit()


@_MARIADB
def test_mariadb_promote_new_and_replay_idempotent(_mariadb_auth) -> None:
    with _disposable_schema("promote") as (conn, _config, database):
        assert database not in _PRODUCTION_DB_NAMES
        request = _mariadb_request(OperationType.PROMOTE_SCOPE, _other_uuid("d1"))
        outcome = execute_scope_administration(conn, request, authorization=_AUTH)
        assert outcome.result.result_code == ResultCode.PROMOTED_NEW_SCOPE
        assert outcome.persisted is True
        assert outcome.commit_state == CommitState.COMMITTED

        replay = execute_scope_administration(conn, request, authorization=_AUTH)
        assert replay.result.result_code == ResultCode.OPERATION_ALREADY_COMPLETED
        assert replay.persisted is False

        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS n FROM native_short_map_scope_v1")
            assert cursor.fetchone()["n"] == 1
            cursor.execute("SELECT COUNT(*) AS n FROM native_short_scope_admin_operation_v1")
            assert cursor.fetchone()["n"] == 1
            cursor.execute(
                "SELECT COUNT(*) AS n FROM native_short_scope_cadence_config_v1 WHERE is_active = 1"
            )
            assert cursor.fetchone()["n"] == 1


@_MARIADB
def test_mariadb_persisted_operation_tuple_is_canonical(_mariadb_auth) -> None:
    with _disposable_schema("operationtuple") as (conn, _config, _database):
        operation_uuid = _other_uuid("c1")
        outcome = execute_scope_administration(
            conn,
            _mariadb_request(OperationType.PROMOTE_SCOPE, operation_uuid),
            authorization=_AUTH,
        )
        assert outcome.result.result_code == ResultCode.PROMOTED_NEW_SCOPE
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT operation_type, result_class, result_code,
                       support_generation_before, support_generation_after
                FROM native_short_scope_admin_operation_v1
                WHERE operation_uuid = %s
                """,
                (operation_uuid,),
            )
            assert cursor.fetchone() == {
                "operation_type": "PROMOTE_SCOPE",
                "result_class": "SUCCESS",
                "result_code": "PROMOTED_NEW_SCOPE",
                "support_generation_before": None,
                "support_generation_after": 1,
            }


@_MARIADB
def test_mariadb_adopt_legacy_scope(_mariadb_auth) -> None:
    with _disposable_schema("adopt") as (conn, _config, _database):
        _seed_legacy_scope(conn)
        outcome = execute_scope_administration(
            conn, _mariadb_request(OperationType.ADOPT_LEGACY_SCOPE, _other_uuid("a1")),
            authorization=_AUTH,
        )
        assert outcome.result.result_code == ResultCode.ADOPTED_LEGACY_SCOPE
        with conn.cursor() as cursor:
            cursor.execute("SELECT support_generation FROM native_short_map_scope_v1")
            assert cursor.fetchone()["support_generation"] == 1
            cursor.execute(
                "SELECT support_generation, activation_operation_id "
                "FROM native_short_scope_cadence_config_v1 WHERE is_active = 1"
            )
            row = cursor.fetchone()
            assert row["support_generation"] == 1
            assert row["activation_operation_id"] is not None


@_MARIADB
def test_mariadb_remove_then_cleanup_then_repromote(_mariadb_auth) -> None:
    with _disposable_schema("removecycle") as (conn, _config, _database):
        execute_scope_administration(
            conn, _mariadb_request(OperationType.PROMOTE_SCOPE, _other_uuid("01")),
            authorization=_AUTH,
        )
        remove = execute_scope_administration(
            conn, _mariadb_request(OperationType.REMOVE_SCOPE, _other_uuid("02")),
            authorization=_AUTH,
        )
        assert remove.result.result_code == ResultCode.REMOVED_SCOPE
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT scope_support_state, scope_reason_code, support_generation "
                "FROM native_short_map_scope_v1"
            )
            row = cursor.fetchone()
            assert row["scope_support_state"] == "NOT_APPLICABLE"
            assert row["scope_reason_code"] == ADMIN_REMOVAL_REASON_CODE
            assert row["support_generation"] == 2
            cursor.execute(
                "SELECT COUNT(*) AS n FROM native_short_scope_cadence_config_v1 WHERE is_active = 1"
            )
            assert cursor.fetchone()["n"] == 0

        # Ledgered residue cleanup on a second removal.
        _insert_scope_status_residue(conn)
        cleanup = execute_scope_administration(
            conn, _mariadb_request(OperationType.REMOVE_SCOPE, _other_uuid("03")),
            authorization=_AUTH,
        )
        assert cleanup.result.result_code == ResultCode.ALREADY_REMOVED_DERIVED_RESIDUE_CLEARED
        assert cleanup.persisted is True
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS n FROM native_short_scope_status_v1")
            assert cursor.fetchone()["n"] == 0
            cursor.execute(
                "SELECT COUNT(*) AS n FROM native_short_scope_admin_operation_v1 "
                "WHERE result_code = 'ALREADY_REMOVED_DERIVED_RESIDUE_CLEARED'"
            )
            assert cursor.fetchone()["n"] == 1

        # Re-promotion after withdrawal preserves prior rows.
        repromote = execute_scope_administration(
            conn, _mariadb_request(OperationType.PROMOTE_SCOPE, _other_uuid("04")),
            authorization=_AUTH,
        )
        assert repromote.result.result_code == ResultCode.PROMOTED_FROM_PRIOR_WITHDRAWAL
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT scope_support_state, support_generation FROM native_short_map_scope_v1"
            )
            row = cursor.fetchone()
            assert row["scope_support_state"] == "SUPPORTED"
            assert row["support_generation"] == 3
            cursor.execute("SELECT COUNT(*) AS n FROM native_short_scope_cadence_config_v1")
            assert cursor.fetchone()["n"] == 2
            cursor.execute(
                "SELECT COUNT(*) AS n FROM native_short_scope_cadence_config_v1 WHERE is_active = 1"
            )
            assert cursor.fetchone()["n"] == 1


@_MARIADB
def test_mariadb_changed_digest_conflict(_mariadb_auth) -> None:
    with _disposable_schema("digest") as (conn, _config, _database):
        uuid = _other_uuid("f1")
        execute_scope_administration(
            conn,
            _mariadb_request(OperationType.PROMOTE_SCOPE, uuid, metadata={"k": "v1"}),
            authorization=_AUTH,
        )
        conflict = execute_scope_administration(
            conn,
            _mariadb_request(OperationType.PROMOTE_SCOPE, uuid, metadata={"k": "v2"}),
            authorization=_AUTH,
        )
        assert conflict.result.result_code == ResultCode.OPERATION_METADATA_MISMATCH
        assert conflict.persisted is False


@_MARIADB
def test_mariadb_first_creation_serialization(_mariadb_auth) -> None:
    with _disposable_schema("serialize") as (conn, config, database):
        conn_b = _connect(config, database=database)
        try:
            results: dict[str, Any] = {}
            barrier = threading.Barrier(2)

            def _promote(tag: str, connection: Any, uuid: str) -> None:
                barrier.wait()
                results[tag] = execute_scope_administration(
                    connection, _mariadb_request(OperationType.PROMOTE_SCOPE, uuid),
                    authorization=_AUTH,
                )

            t1 = threading.Thread(target=_promote, args=("a", conn, _other_uuid("a1")))
            t2 = threading.Thread(target=_promote, args=("b", conn_b, _other_uuid("a2")))
            t1.start(); t2.start(); t1.join(); t2.join()

            codes = {str(results["a"].result.result_code), str(results["b"].result.result_code)}
            assert "PROMOTED_NEW_SCOPE" in codes
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) AS n FROM native_short_map_scope_v1")
                assert cursor.fetchone()["n"] == 1
                cursor.execute(
                    "SELECT COUNT(*) AS n FROM native_short_scope_cadence_config_v1 WHERE is_active = 1"
                )
                assert cursor.fetchone()["n"] == 1
        finally:
            conn_b.close()


@_MARIADB
def test_mariadb_rollback_leaves_no_partial_state(
    monkeypatch: pytest.MonkeyPatch, _mariadb_auth
) -> None:
    with _disposable_schema("rollback") as (conn, _config, _database):
        original = txn._insert_support_event

        def _boom(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("injected failure")

        monkeypatch.setattr(txn, "_insert_support_event", _boom)
        with pytest.raises(RuntimeError, match="injected failure"):
            execute_scope_administration(
                conn, _mariadb_request(OperationType.PROMOTE_SCOPE, _other_uuid("31")),
                authorization=_AUTH,
            )
        monkeypatch.setattr(txn, "_insert_support_event", original)
        with conn.cursor() as cursor:
            for table in (
                "native_short_map_scope_v1",
                "native_short_scope_admin_operation_v1",
                "native_short_scope_support_event_v1",
                "native_short_scope_cadence_config_v1",
            ):
                cursor.execute(f"SELECT COUNT(*) AS n FROM {table}")
                assert cursor.fetchone()["n"] == 0, table


@_MARIADB
def test_mariadb_active_cadence_uniqueness_enforced(_mariadb_auth) -> None:
    import pymysql

    with _disposable_schema("cadenceuq") as (conn, _config, _database):
        execute_scope_administration(
            conn, _mariadb_request(OperationType.PROMOTE_SCOPE, _other_uuid("51")),
            authorization=_AUTH,
        )
        # A direct attempt to insert a second active cadence row for the exact
        # scope must violate the active-slot unique key.
        with pytest.raises(pymysql.err.IntegrityError):
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO native_short_scope_cadence_config_v1 (
                        venue, symbol, quote_currency, fib_trading_horizon,
                        primary_interval, supporting_interval, cadence_contract_version,
                        target_evaluation_interval,
                        primary_source_freshness_limit_seconds,
                        supporting_source_freshness_limit_seconds,
                        evaluation_grace_seconds, recent_scope_grace_seconds,
                        effective_from_utc, effective_to_utc, is_active
                    ) VALUES (
                        'bitvavo', 'BTC', 'EUR', 'SHORT', '4h', '1h', 'other_v2',
                        '1h', 43200, 10800, 900, 3600, '2026-07-20 00:00:00', NULL, 1
                    )
                    """
                )
        conn.rollback()


@_MARIADB
def test_mariadb_support_generation_uniqueness_enforced(_mariadb_auth) -> None:
    import pymysql

    with _disposable_schema("supportuq") as (conn, _config, _database):
        execute_scope_administration(
            conn, _mariadb_request(OperationType.PROMOTE_SCOPE, _other_uuid("61")),
            authorization=_AUTH,
        )
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT scope_admin_operation_id AS id FROM native_short_scope_admin_operation_v1"
            )
            op_id = cursor.fetchone()["id"]
        # A second attributable support event for the same scope+generation must
        # violate the scope-generation unique key.
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
                        'bitvavo', 'BTC', 'EUR', 'SHORT', '4h', '1h', 'SUPPORTED',
                        %s, 1, '2026-07-19 00:00:00', 'dup', 'v1'
                    )
                    """,
                    (op_id,),
                )
        conn.rollback()


@_MARIADB
def test_mariadb_cross_scope_operation_attribution_is_rejected() -> None:
    import pymysql

    with _disposable_schema("crossscope") as (conn, _config, _database):
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
                "SELECT scope_admin_operation_id AS id FROM native_short_scope_admin_operation_v1"
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
