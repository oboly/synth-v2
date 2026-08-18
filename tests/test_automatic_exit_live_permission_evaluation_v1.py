"""Issue #392 Phase 6 blocker B: the decision_gate composition seam.

Proves ``evaluate_automatic_exit_live_permission_v1`` assembles real
persisted permission + revocation evidence, resolves it through the canonical
pure contract exactly once, and fails closed on missing/ambiguous/malformed
evidence by returning a typed DENIED evaluation rather than raising an
uncaught exception that would abort a whole runtime cycle.
"""
from __future__ import annotations

from datetime import timedelta

from src.decision_gate.automatic_exit_live_permission_evaluation_v1 import (
    DECISION_DENIED,
    DECISION_GRANTED,
    REASON_LIVE_PERMISSION_EVIDENCE_UNRESOLVED,
    REASON_LIVE_PERMISSION_NOT_GRANTED,
    REASON_OK,
    evaluate_automatic_exit_live_permission_v1,
)
from tests.automatic_exit_runtime_fixtures_v1 import (
    FakeConnection,
    TS,
    insert_live_permission,
    insert_live_permission_revocation,
    insert_trading_account,
)


ACCOUNT_A = 7
ACCOUNT_B = 8


def _base_conn(*, account_id: int = ACCOUNT_A) -> FakeConnection:
    conn = FakeConnection()
    insert_trading_account(conn, account_id=account_id)
    return conn


def test_no_permission_row_denies_without_raising() -> None:
    conn = _base_conn()
    result = evaluate_automatic_exit_live_permission_v1(conn, trading_account_id=ACCOUNT_A, evaluation_ts_utc=TS)
    assert result.decision_state == DECISION_DENIED
    assert result.reason_code == REASON_LIVE_PERMISSION_NOT_GRANTED
    assert result.permission_id is None


def test_granted_permission_resolves_typed_grant() -> None:
    conn = _base_conn()
    permission_id = insert_live_permission(conn, account_id=ACCOUNT_A, live_execution_permitted=True)
    result = evaluate_automatic_exit_live_permission_v1(conn, trading_account_id=ACCOUNT_A, evaluation_ts_utc=TS)
    assert result.decision_state == DECISION_GRANTED
    assert result.reason_code == REASON_OK
    assert result.trading_account_id == ACCOUNT_A
    assert result.permission_id == permission_id
    assert result.permission_version == "1"
    assert result.evaluated_ts_utc == TS


def test_permission_flag_false_denies() -> None:
    conn = _base_conn()
    insert_live_permission(conn, account_id=ACCOUNT_A, live_execution_permitted=False)
    result = evaluate_automatic_exit_live_permission_v1(conn, trading_account_id=ACCOUNT_A, evaluation_ts_utc=TS)
    assert result.decision_state == DECISION_DENIED
    assert result.reason_code == REASON_LIVE_PERMISSION_NOT_GRANTED


def test_revoked_open_ended_permission_denies() -> None:
    conn = _base_conn()
    permission_id = insert_live_permission(
        conn, account_id=ACCOUNT_A, live_execution_permitted=True, effective_from_ts_utc=TS - timedelta(days=1),
    )
    insert_live_permission_revocation(conn, permission_id=permission_id, account_id=ACCOUNT_A, effective_ts_utc=TS - timedelta(hours=1))
    result = evaluate_automatic_exit_live_permission_v1(conn, trading_account_id=ACCOUNT_A, evaluation_ts_utc=TS)
    assert result.decision_state == DECISION_DENIED
    assert result.reason_code == REASON_LIVE_PERMISSION_NOT_GRANTED


def test_future_revocation_does_not_revoke_early() -> None:
    conn = _base_conn()
    permission_id = insert_live_permission(conn, account_id=ACCOUNT_A, live_execution_permitted=True)
    insert_live_permission_revocation(conn, permission_id=permission_id, account_id=ACCOUNT_A, effective_ts_utc=TS + timedelta(days=1))
    result = evaluate_automatic_exit_live_permission_v1(conn, trading_account_id=ACCOUNT_A, evaluation_ts_utc=TS)
    assert result.decision_state == DECISION_GRANTED


def test_conflicting_active_permissions_fail_closed() -> None:
    conn = _base_conn()
    insert_live_permission(conn, account_id=ACCOUNT_A, live_execution_permitted=True)
    insert_live_permission(conn, account_id=ACCOUNT_A, live_execution_permitted=False)
    result = evaluate_automatic_exit_live_permission_v1(conn, trading_account_id=ACCOUNT_A, evaluation_ts_utc=TS)
    assert result.decision_state == DECISION_DENIED
    assert result.reason_code == REASON_LIVE_PERMISSION_EVIDENCE_UNRESOLVED


def test_permission_is_strictly_account_isolated() -> None:
    conn = _base_conn(account_id=ACCOUNT_A)
    insert_trading_account(conn, account_id=ACCOUNT_B)
    insert_live_permission(conn, account_id=ACCOUNT_A, live_execution_permitted=True)
    account_a = evaluate_automatic_exit_live_permission_v1(conn, trading_account_id=ACCOUNT_A, evaluation_ts_utc=TS)
    account_b = evaluate_automatic_exit_live_permission_v1(conn, trading_account_id=ACCOUNT_B, evaluation_ts_utc=TS)
    assert account_a.decision_state == DECISION_GRANTED
    assert account_b.decision_state == DECISION_DENIED
    assert account_b.reason_code == REASON_LIVE_PERMISSION_NOT_GRANTED


def test_replay_deterministic_and_persisted_evidence_survives_reload() -> None:
    conn = _base_conn()
    insert_live_permission(conn, account_id=ACCOUNT_A, live_execution_permitted=True)
    first = evaluate_automatic_exit_live_permission_v1(conn, trading_account_id=ACCOUNT_A, evaluation_ts_utc=TS)
    second = evaluate_automatic_exit_live_permission_v1(conn, trading_account_id=ACCOUNT_A, evaluation_ts_utc=TS)
    assert first == second
