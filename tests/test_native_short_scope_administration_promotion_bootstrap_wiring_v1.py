from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Any

import pytest

from src.market_data.native_short_multi_asset_audit_v1 import (
    BOOTSTRAP_ORCHESTRATION_BLOCKED,
    MULTI_SCOPE_FAILURE_ISOLATION_MISSING,
    PROMOTION_CONTRACT_MISSING,
    PROVENANCE_AUDIT_RUN_UUID,
    REMOVAL_CONTRACT_MISSING,
    WRITER_PROVENANCE_UNATTRIBUTED,
)
from src.market_data.native_short_promotion_bootstrap_evidence_v1 import (
    BootstrapPromotionEvaluation,
    REASON_EVIDENCE_ACCEPTED,
    REASON_MANIFEST_NOT_ACCEPTED,
)
from src.market_data.native_short_scope_administration_v1 import (
    NativeShortScopeAdministrationOperationType as OperationType,
    NativeShortScopeAdministrationResultCode as ResultCode,
)
from src.market_data import (
    native_short_scope_administration_transaction_v1 as txn,
)
from src.market_data.native_short_scope_administration_transaction_v1 import (
    AdminOperationRow,
    OperationAction,
    ScopeClassification,
    ScopeStateSnapshot,
    decide_administration,
    execute_scope_administration,
    plan_scope_administration,
)
from tests.test_native_short_scope_administration_transaction_v1 import (
    _AUTH,
    _FakeConn,
    _FakeState,
    _admin_op,
    _cadence,
    _provenance,
    _request,
    _support_event,
)


_ACCEPTED_EVIDENCE = BootstrapPromotionEvaluation(
    accepted=True,
    reason=REASON_EVIDENCE_ACCEPTED,
    symbol="SOL",
    repository_commit_sha="a" * 40,
)
_UNACCEPTED_EVIDENCE = BootstrapPromotionEvaluation(
    accepted=False,
    reason=REASON_MANIFEST_NOT_ACCEPTED,
    symbol=None,
    repository_commit_sha=None,
)


def _no_scope_snapshot() -> ScopeStateSnapshot:
    return ScopeStateSnapshot(
        scope_present=False,
        scope_id=None,
        scope_support_state=None,
        support_generation=None,
        scope_reason_code=None,
        scope_reason_detail=None,
        cadence_rows=(),
        support_events=(),
        operations=(),
        scope_status_residue_count=0,
        map_level_status_residue_count=0,
    )


def _managed_supported_snapshot() -> ScopeStateSnapshot:
    return ScopeStateSnapshot(
        scope_present=True,
        scope_id=1,
        scope_support_state="SUPPORTED",
        support_generation=1,
        scope_reason_code=None,
        scope_reason_detail=None,
        cadence_rows=(_cadence(activation_op=5000, support_generation=1),),
        support_events=(_support_event(generation=1, operation_id=5000),),
        operations=(_admin_op(operation_id=5000),),
        scope_status_residue_count=0,
        map_level_status_residue_count=0,
    )


# --------------------------------------------------------------------------- #
# decide_administration: pure bootstrap-evidence wiring                       #
# --------------------------------------------------------------------------- #


def test_bootstrap_evidence_promotes_new_scope_when_only_blocker() -> None:
    decision = decide_administration(
        OperationType.PROMOTE_SCOPE,
        _no_scope_snapshot(),
        active_global_blockers=(PROMOTION_CONTRACT_MISSING,),
        bootstrap_promotion_evidence=_ACCEPTED_EVIDENCE,
    )
    assert decision.action == OperationAction.PROMOTE_NEW
    assert decision.result_code == ResultCode.PROMOTED_NEW_SCOPE
    assert decision.bootstrap_evidence_applied is True
    assert decision.blocking_global_blockers == ()


def test_bootstrap_evidence_narrows_only_the_named_codes_never_others() -> None:
    """PROMOTION_CONTRACT_MISSING, BOOTSTRAP_ORCHESTRATION_BLOCKED, and
    MULTI_SCOPE_FAILURE_ISOLATION_MISSING are all narrowed for the exact
    bootstrap-matched scope, but REMOVAL_CONTRACT_MISSING (unrelated to this
    lane's first-canary story) is never touched."""
    decision = decide_administration(
        OperationType.PROMOTE_SCOPE,
        _no_scope_snapshot(),
        active_global_blockers=(
            PROMOTION_CONTRACT_MISSING,
            BOOTSTRAP_ORCHESTRATION_BLOCKED,
            MULTI_SCOPE_FAILURE_ISOLATION_MISSING,
            REMOVAL_CONTRACT_MISSING,
        ),
        bootstrap_promotion_evidence=_ACCEPTED_EVIDENCE,
    )
    assert decision.action == OperationAction.REJECT
    assert decision.result_code == ResultCode.GLOBAL_BLOCKERS_ACTIVE
    assert decision.blocking_global_blockers == (REMOVAL_CONTRACT_MISSING,)
    assert PROMOTION_CONTRACT_MISSING not in decision.blocking_global_blockers
    assert BOOTSTRAP_ORCHESTRATION_BLOCKED not in decision.blocking_global_blockers
    assert MULTI_SCOPE_FAILURE_ISOLATION_MISSING not in decision.blocking_global_blockers
    # Narrowing only clears the named sub-checks; it is not applied/exposed on
    # a decision that still rejects.
    assert decision.bootstrap_evidence_applied is False


def test_unaccepted_bootstrap_evidence_never_narrows_blocking_set() -> None:
    decision = decide_administration(
        OperationType.PROMOTE_SCOPE,
        _no_scope_snapshot(),
        active_global_blockers=(PROMOTION_CONTRACT_MISSING,),
        bootstrap_promotion_evidence=_UNACCEPTED_EVIDENCE,
    )
    assert decision.action == OperationAction.REJECT
    assert decision.blocking_global_blockers == (PROMOTION_CONTRACT_MISSING,)


def test_missing_bootstrap_evidence_default_never_narrows_blocking_set() -> None:
    decision = decide_administration(
        OperationType.PROMOTE_SCOPE,
        _no_scope_snapshot(),
        active_global_blockers=(PROMOTION_CONTRACT_MISSING,),
    )
    assert decision.action == OperationAction.REJECT
    assert decision.blocking_global_blockers == (PROMOTION_CONTRACT_MISSING,)


def test_bootstrap_evidence_never_applies_to_adopt() -> None:
    decision = decide_administration(
        OperationType.ADOPT_LEGACY_SCOPE,
        _no_scope_snapshot(),
        active_global_blockers=(WRITER_PROVENANCE_UNATTRIBUTED,),
        bootstrap_promotion_evidence=_ACCEPTED_EVIDENCE,
    )
    assert decision.blocking_global_blockers == (WRITER_PROVENANCE_UNATTRIBUTED,)
    assert decision.bootstrap_evidence_applied is False


def test_bootstrap_evidence_never_applies_to_remove() -> None:
    decision = decide_administration(
        OperationType.REMOVE_SCOPE,
        _managed_supported_snapshot(),
        active_global_blockers=(REMOVAL_CONTRACT_MISSING,),
        bootstrap_promotion_evidence=_ACCEPTED_EVIDENCE,
    )
    assert decision.blocking_global_blockers == (REMOVAL_CONTRACT_MISSING,)
    assert decision.bootstrap_evidence_applied is False


def test_bootstrap_evidence_does_not_apply_to_already_managed_scope() -> None:
    """Structural single-use: once a scope has any history, it can never
    classify NO_SCOPE again, so bootstrap evidence naming that exact scope
    can never re-apply -- proven directly against a MANAGED_SUPPORTED
    snapshot (already promoted once)."""
    decision = decide_administration(
        OperationType.PROMOTE_SCOPE,
        _managed_supported_snapshot(),
        active_global_blockers=(PROMOTION_CONTRACT_MISSING,),
        bootstrap_promotion_evidence=_ACCEPTED_EVIDENCE,
    )
    assert decision.blocking_global_blockers == (PROMOTION_CONTRACT_MISSING,)
    assert decision.bootstrap_evidence_applied is False


def test_bootstrap_evidence_fails_closed_on_incoherent_state_with_ledger_history() -> None:
    """Defensive guard: even if some future defect produced a NO_SCOPE
    classification (no scope/cadence/support rows) while an administration-
    operation ledger row nonetheless exists for that exact scope, the
    bootstrap exception must not apply -- an incoherent existing state fails
    closed rather than silently authorizing a second promotion."""
    incoherent_snapshot = ScopeStateSnapshot(
        scope_present=False,
        scope_id=None,
        scope_support_state=None,
        support_generation=None,
        scope_reason_code=None,
        scope_reason_detail=None,
        cadence_rows=(),
        support_events=(),
        operations=(AdminOperationRow(
            scope_admin_operation_id=1,
            operation_type="PROMOTE_SCOPE",
            result_class="SUCCESS",
            result_code="PROMOTED_NEW_SCOPE",
            is_terminal=True,
            support_generation_before=None,
            support_generation_after=1,
        ),),
        scope_status_residue_count=0,
        map_level_status_residue_count=0,
    )
    decision = decide_administration(
        OperationType.PROMOTE_SCOPE,
        incoherent_snapshot,
        active_global_blockers=(PROMOTION_CONTRACT_MISSING,),
        bootstrap_promotion_evidence=_ACCEPTED_EVIDENCE,
    )
    assert decision.blocking_global_blockers == (PROMOTION_CONTRACT_MISSING,)
    assert decision.bootstrap_evidence_applied is False


# --------------------------------------------------------------------------- #
# execute_scope_administration / plan_scope_administration integration        #
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _authorize_test_writer(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.operations.writer_capability_authorization_v1 as authmod

    monkeypatch.setattr(
        authmod,
        "require_writer_mutation_authorization",
        lambda authorization, capability_id: None,
    )


def _sol_request(*, repository_sha: str = "a" * 40, operation_uuid: str | None = None):
    provenance_changes: dict[str, Any] = {"repository_sha": repository_sha}
    if operation_uuid is not None:
        provenance_changes["operation_uuid"] = operation_uuid
    return _request(
        OperationType.PROMOTE_SCOPE,
        symbol="SOL",
        provenance=_provenance(**provenance_changes),
        metadata={"ticket": "bootstrap-test"},
    )


def test_execute_end_to_end_promotes_bootstrap_scope_when_only_blocker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        txn, "evaluate_current_global_blockers", lambda conn: ((PROMOTION_CONTRACT_MISSING,), {})
    )
    monkeypatch.setattr(
        txn,
        "evaluate_promotion_bootstrap_evidence",
        lambda **kwargs: _ACCEPTED_EVIDENCE,
    )
    conn = _FakeConn()
    before = copy.deepcopy(conn.committed)

    outcome = execute_scope_administration(conn, _sol_request(), authorization=_AUTH)

    assert outcome.result.result_code == ResultCode.PROMOTED_NEW_SCOPE
    assert outcome.current_state["bootstrap_evidence_applied"] is True
    assert outcome.current_state["bootstrap_evidence"]["accepted"] is True
    assert conn.commit_count == 1
    assert conn.committed.scopes != before.scopes
    assert conn.committed.operations[-1]["symbol"] == "SOL"


def test_execute_end_to_end_still_blocked_by_orthogonal_blocker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even a fully accepted bootstrap manifest only narrows the three named
    codes; an unrelated active blocker (REMOVAL_CONTRACT_MISSING, which has
    its own separate, unimplemented evidence gap) continues to reject the
    promotion, proving this lane does not weaken an unrelated global
    blocker."""
    monkeypatch.setattr(
        txn,
        "evaluate_current_global_blockers",
        lambda conn: (
            (PROMOTION_CONTRACT_MISSING, REMOVAL_CONTRACT_MISSING),
            {},
        ),
    )
    monkeypatch.setattr(
        txn,
        "evaluate_promotion_bootstrap_evidence",
        lambda **kwargs: _ACCEPTED_EVIDENCE,
    )
    conn = _FakeConn()
    before = copy.deepcopy(conn.committed)

    outcome = execute_scope_administration(conn, _sol_request(), authorization=_AUTH)

    assert outcome.result.result_code == ResultCode.GLOBAL_BLOCKERS_ACTIVE
    assert outcome.current_state["blocking_global_blockers"] == [
        REMOVAL_CONTRACT_MISSING
    ]
    assert conn.commit_count == 0
    assert conn.committed.scopes == before.scopes


def _accepted_writer_evidence_row() -> dict[str, Any]:
    return {
        "run_uuid": PROVENANCE_AUDIT_RUN_UUID,
        "runner_name": "run_native_short_scope_status_chain_v1",
        "runner_version": "0.1",
        "trigger_type": "REPOSITORY_4H_MARKET_CHAIN",
        "trigger_ref": "scripts/run_native_short_scope_status_chain_once.sh",
        "host_name": "devlap",
        "process_id": 26030,
        "provenance_contract_version": "native_short_writer_provenance_v1",
        "writer_entrypoint": "scripts/run_native_short_scope_status_chain_once.sh",
        "repository_writer_owner": "synth-chain-4h",
        "execution_mode": "CHAIN",
        "repository_commit_sha": "38346fc1460453469ca5bd3bc2f45159f0dc303e",
    }


def test_execute_real_evaluators_still_block_sol_before_commit_is_pinned() -> None:
    """With the real (unmodified) evaluate_current_global_blockers and the
    real, checked-in, accepted-for-SOL bootstrap manifest, a SOL PROMOTE_SCOPE
    request from any commit other than the manifest's pinned
    repository_commit_sha remains blocked: the shipped repository state
    cannot silently authorize production from an arbitrary checkout."""
    state = _FakeState()
    state.writer_runs.append(_accepted_writer_evidence_row())
    conn = _FakeConn(state)

    outcome = execute_scope_administration(conn, _sol_request(), authorization=_AUTH)

    assert outcome.result.result_code == ResultCode.GLOBAL_BLOCKERS_ACTIVE
    blocking = set(outcome.current_state["blocking_global_blockers"])
    assert PROMOTION_CONTRACT_MISSING in blocking
    assert BOOTSTRAP_ORCHESTRATION_BLOCKED in blocking
    assert MULTI_SCOPE_FAILURE_ISOLATION_MISSING in blocking
    assert REMOVAL_CONTRACT_MISSING in blocking
    assert outcome.current_state["bootstrap_evidence"]["accepted"] is False


@pytest.mark.parametrize("symbol", ["ETH", "XRP", "BTC", "DOGE"])
def test_execute_real_evaluator_fails_closed_for_every_non_sol_symbol(symbol: str) -> None:
    """The real, checked-in manifest names exactly one symbol (SOL). Every
    other symbol -- including the two named-but-not-approved review
    candidates ETH and XRP, and the legacy BTC scope -- fails the bootstrap
    scope-match check regardless of blocker state or repository commit, and
    therefore never narrows any blocker."""
    state = _FakeState()
    state.writer_runs.append(_accepted_writer_evidence_row())
    conn = _FakeConn(state)

    outcome = execute_scope_administration(
        conn, _request(OperationType.PROMOTE_SCOPE, symbol=symbol), authorization=_AUTH
    )

    assert outcome.result.result_code == ResultCode.GLOBAL_BLOCKERS_ACTIVE
    blocking = set(outcome.current_state["blocking_global_blockers"])
    assert PROMOTION_CONTRACT_MISSING in blocking
    assert BOOTSTRAP_ORCHESTRATION_BLOCKED in blocking
    assert MULTI_SCOPE_FAILURE_ISOLATION_MISSING in blocking
    assert outcome.current_state["bootstrap_evidence"]["accepted"] is False
    assert outcome.current_state["bootstrap_evidence"]["reason"] != REASON_EVIDENCE_ACCEPTED
    assert conn.commit_count == 0


def test_execute_second_promote_attempt_after_sol_bootstrap_success_is_not_reauthorized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Once SOL's bootstrap promotion has committed once, a brand-new,
    differently-uuid'd PROMOTE_SCOPE attempt against the same scope no
    longer classifies NO_SCOPE, so the bootstrap exception structurally
    cannot re-apply -- proving single-use without any mutable 'consumed'
    flag."""
    monkeypatch.setattr(
        txn, "evaluate_current_global_blockers", lambda conn: ((PROMOTION_CONTRACT_MISSING,), {})
    )
    monkeypatch.setattr(
        txn, "evaluate_promotion_bootstrap_evidence", lambda **kwargs: _ACCEPTED_EVIDENCE
    )
    conn = _FakeConn()
    first = execute_scope_administration(conn, _sol_request(), authorization=_AUTH)
    assert first.result.result_code == ResultCode.PROMOTED_NEW_SCOPE
    assert conn.commit_count == 1

    second_request = _sol_request(
        operation_uuid="00000000-0000-4000-8000-000000000002"
    )
    second = execute_scope_administration(conn, second_request, authorization=_AUTH)

    assert second.result.result_code == ResultCode.GLOBAL_BLOCKERS_ACTIVE
    assert PROMOTION_CONTRACT_MISSING in second.current_state["blocking_global_blockers"]
    assert conn.commit_count == 1
    assert len(conn.committed.operations) == 1


def test_execute_retry_of_same_operation_uuid_is_idempotent_and_creates_no_second_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Requirement: after successful promotion, retry must be idempotent and
    must not create a second operation. A retry (same operation_uuid, same
    immutable request identity) replays OPERATION_ALREADY_COMPLETED without
    consulting blockers or bootstrap evidence again."""
    monkeypatch.setattr(
        txn, "evaluate_current_global_blockers", lambda conn: ((PROMOTION_CONTRACT_MISSING,), {})
    )
    monkeypatch.setattr(
        txn, "evaluate_promotion_bootstrap_evidence", lambda **kwargs: _ACCEPTED_EVIDENCE
    )
    conn = _FakeConn()
    request = _sol_request()

    first = execute_scope_administration(conn, request, authorization=_AUTH)
    assert first.result.result_code == ResultCode.PROMOTED_NEW_SCOPE
    assert conn.commit_count == 1
    operation_count_after_first = len(conn.committed.operations)

    retry = execute_scope_administration(conn, request, authorization=_AUTH)

    assert retry.result.result_code == ResultCode.OPERATION_ALREADY_COMPLETED
    assert str(retry.result.result_class) == "IDEMPOTENT_SUCCESS"
    assert retry.persisted is False
    assert len(conn.committed.operations) == operation_count_after_first
    # Commit count does not advance on replay: the replay path rolls back
    # immediately after re-reading state, it never opens a second commit.
    assert conn.commit_count == 1


def test_plan_shows_full_decision_and_evidence_without_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        txn, "evaluate_current_global_blockers", lambda conn: ((PROMOTION_CONTRACT_MISSING,), {})
    )
    monkeypatch.setattr(
        txn,
        "evaluate_promotion_bootstrap_evidence",
        lambda **kwargs: _ACCEPTED_EVIDENCE,
    )
    conn = _FakeConn()

    outcome = plan_scope_administration(conn, _sol_request())

    assert outcome.write is False
    assert outcome.persisted is False
    assert outcome.result.result_code == ResultCode.PROMOTED_NEW_SCOPE
    assert outcome.current_state["bootstrap_evidence_applied"] is True
    assert outcome.current_state["bootstrap_evidence"] == {
        "accepted": True,
        "reason": REASON_EVIDENCE_ACCEPTED,
        "symbol": "SOL",
        "repository_commit_sha": "a" * 40,
    }
    assert conn.commit_count == 0


def test_plan_never_evaluates_bootstrap_evidence_for_adopt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fail(**kwargs: Any) -> BootstrapPromotionEvaluation:
        raise AssertionError("bootstrap evidence must not be evaluated for ADOPT_LEGACY_SCOPE")

    monkeypatch.setattr(txn, "evaluate_current_global_blockers", lambda conn: ((), {}))
    monkeypatch.setattr(txn, "evaluate_promotion_bootstrap_evidence", _fail)
    conn = _FakeConn()

    outcome = plan_scope_administration(
        conn, _request(OperationType.ADOPT_LEGACY_SCOPE, symbol="BTC")
    )

    assert outcome.current_state["bootstrap_evidence"] is None
