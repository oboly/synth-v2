from __future__ import annotations

from src.decision_gate.automatic_buy_account_permission_repository_v1 import (
    load_automatic_buy_account_permission_history_v1,
    load_automatic_buy_account_permission_revocation_history_v1,
)
from tests.automatic_buy_account_allocation_evidence_fixtures_v1 import FakeConnection, insert_buy_permission


def test_load_history_round_trips_execution_enabled_flag() -> None:
    conn = FakeConnection()
    insert_buy_permission(conn, account_id=7, execution_enabled=True)
    rows = load_automatic_buy_account_permission_history_v1(conn, trading_account_id=7)
    assert len(rows) == 1
    assert rows[0].execution_enabled is True
    assert rows[0].trading_account_id == 7


def test_load_history_scoped_to_account() -> None:
    conn = FakeConnection()
    insert_buy_permission(conn, account_id=7)
    insert_buy_permission(conn, account_id=3)
    rows = load_automatic_buy_account_permission_history_v1(conn, trading_account_id=7)
    assert all(row.trading_account_id == 7 for row in rows)


def test_load_revocation_history_empty_by_default() -> None:
    conn = FakeConnection()
    insert_buy_permission(conn, account_id=7)
    revocations = load_automatic_buy_account_permission_revocation_history_v1(conn, trading_account_id=7)
    assert revocations == ()
