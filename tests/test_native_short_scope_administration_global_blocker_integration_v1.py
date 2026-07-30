from __future__ import annotations

import copy
from typing import Any

import pytest

from src.market_data.native_short_multi_asset_audit_v1 import (
    PROMOTION_CONTRACT_MISSING,
    PROVENANCE_AUDIT_RUN_UUID,
    WRITER_PROVENANCE_UNATTRIBUTED,
)
from src.market_data.native_short_scope_administration_v1 import (
    NativeShortScopeAdministrationResultCode as ResultCode,
)
from src.market_data.native_short_scope_administration_transaction_v1 import (
    NativeShortScopeAdministrationExecutionError,
    execute_scope_administration,
)
from tests.test_native_short_scope_administration_transaction_v1 import (
    _AUTH,
    _FakeConn,
    _FakeState,
    _request,
)


@pytest.fixture(autouse=True)
def _authorize_test_writer(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.operations.writer_capability_authorization_v1 as authmod

    monkeypatch.setattr(
        authmod,
        "require_writer_mutation_authorization",
        lambda authorization, capability_id: None,
    )


def _accepted_writer_evidence() -> dict[str, Any]:
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


def _assert_real_evidence_queries_ran(conn: _FakeConn) -> None:
    assert any(
        "FROM native_short_materializer_run_v1" in sql for sql in conn.executions
    )
    assert any(
        "FROM native_short_scope_admin_operation_v1" in sql
        and "WHERE operation_type = 'PROMOTE_SCOPE'" in sql
        for sql in conn.executions
    )


def _assert_blocked_without_mutation(conn: _FakeConn, before: _FakeState) -> None:
    assert conn.committed.scopes == before.scopes
    assert conn.committed.cadence == before.cadence
    assert conn.committed.support == before.support
    assert conn.committed.scope_status == before.scope_status
    assert conn.committed.map_level_status == before.map_level_status
    assert conn.committed.operations == before.operations
    assert conn.commit_count == 0
    assert conn.rollback_count == 1


def test_execute_real_evaluator_absent_writer_evidence_fails_closed() -> None:
    conn = _FakeConn()
    before = copy.deepcopy(conn.committed)

    outcome = execute_scope_administration(conn, _request(), authorization=_AUTH)

    _assert_real_evidence_queries_ran(conn)
    assert outcome.result.result_code == ResultCode.GLOBAL_BLOCKERS_ACTIVE
    assert str(outcome.result.result_class) == "BLOCKED"
    assert WRITER_PROVENANCE_UNATTRIBUTED in outcome.current_state[
        "blocking_global_blockers"
    ]
    _assert_blocked_without_mutation(conn, before)


def test_execute_real_evaluator_absent_promotion_evidence_stays_active() -> None:
    state = _FakeState()
    state.writer_runs.append(_accepted_writer_evidence())
    conn = _FakeConn(state)
    before = copy.deepcopy(conn.committed)

    outcome = execute_scope_administration(conn, _request(), authorization=_AUTH)

    _assert_real_evidence_queries_ran(conn)
    assert outcome.result.result_code == ResultCode.GLOBAL_BLOCKERS_ACTIVE
    assert PROMOTION_CONTRACT_MISSING in outcome.current_state[
        "blocking_global_blockers"
    ]
    assert WRITER_PROVENANCE_UNATTRIBUTED not in outcome.current_state[
        "blocking_global_blockers"
    ]
    _assert_blocked_without_mutation(conn, before)


def test_execute_real_evaluator_malformed_evidence_never_clears_blockers() -> None:
    state = _FakeState()
    state.writer_runs.append(
        {
            **_accepted_writer_evidence(),
            "provenance_contract_version": "malformed-contract",
        }
    )
    conn = _FakeConn(state)
    before = copy.deepcopy(conn.committed)

    outcome = execute_scope_administration(conn, _request(), authorization=_AUTH)

    _assert_real_evidence_queries_ran(conn)
    blocking = outcome.current_state["blocking_global_blockers"]
    assert blocking
    assert WRITER_PROVENANCE_UNATTRIBUTED in blocking
    assert outcome.result.result_code == ResultCode.GLOBAL_BLOCKERS_ACTIVE
    _assert_blocked_without_mutation(conn, before)


def test_execute_real_evaluator_unreadable_evidence_fails_before_mutation() -> None:
    conn = _FakeConn()
    conn.fail_on = "writer_evidence_read"
    before = copy.deepcopy(conn.committed)

    with pytest.raises(NativeShortScopeAdministrationExecutionError):
        execute_scope_administration(conn, _request(), authorization=_AUTH)

    assert any(
        "FROM native_short_materializer_run_v1" in sql for sql in conn.executions
    )
    _assert_blocked_without_mutation(conn, before)
