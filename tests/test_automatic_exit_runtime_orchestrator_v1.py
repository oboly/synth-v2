from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from src.exit_policy.automatic_exit_runtime_orchestrator_v1 import evaluate_automatic_exit_runtime_item_v1
from src.exit_policy.automatic_exit_runtime_repository_v1 import (
    build_runtime_item_v1,
    load_eligible_trading_accounts,
    load_latest_complete_account_state_bundle,
    load_positive_positions,
)
from tests.automatic_exit_runtime_fixtures_v1 import (
    FakeConnection,
    TS,
    insert_market_price,
    seed_happy_path,
)


NOW = TS + timedelta(minutes=5)


def _build_item(conn: FakeConnection):
    accounts = load_eligible_trading_accounts(conn, venue="bitvavo")
    bundle = load_latest_complete_account_state_bundle(conn, trading_account_id=7, venue="bitvavo", now=NOW)
    positions = load_positive_positions(conn, bundle=bundle)
    return build_runtime_item_v1(conn, account=accounts[0], bundle=bundle, position=positions[0], now=NOW)


def _audit_rows(conn: FakeConnection) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM automatic_exit_evaluation_audit_v1")
        return cur.fetchall()


def test_healthy_evidence_reaches_staged_plan() -> None:
    conn = FakeConnection()
    seed_happy_path(conn)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM market_price_snapshot")
    insert_market_price(conn, price=Decimal("65000"))  # above target -> REDUCE candidate
    item = _build_item(conn)
    outcome = evaluate_automatic_exit_runtime_item_v1(conn, item=item, evaluation_ts_utc=NOW)
    assert outcome.candidate_state == "CANDIDATE"
    assert outcome.gate_state == "APPROVED"
    assert outcome.planner_state == "STAGED"
    rows = _audit_rows(conn)
    assert len(rows) == 1
    assert rows[0]["immutable_plan_json"] is not None


def test_no_action_writes_audit_without_gate_or_planner() -> None:
    conn = FakeConnection()
    seed_happy_path(conn)  # price 50000, between invalidation 40000 and target 60000
    item = _build_item(conn)
    outcome = evaluate_automatic_exit_runtime_item_v1(conn, item=item, evaluation_ts_utc=NOW)
    assert outcome.candidate_state == "NO_ACTION"
    assert outcome.gate_state is None
    assert outcome.planner_state == "NOT_REACHED"
    rows = _audit_rows(conn)
    assert rows[0]["gate_state"] is None
    assert rows[0]["immutable_plan_json"] is None


def test_non_actionable_candidate_writes_audit_without_gate_or_planner() -> None:
    conn = FakeConnection()
    seed_happy_path(conn)
    item = _build_item(conn)
    stale_item = replace(item, account_state_observed_ts_utc=TS - timedelta(hours=2))
    outcome = evaluate_automatic_exit_runtime_item_v1(conn, item=stale_item, evaluation_ts_utc=NOW)
    assert outcome.candidate_state == "NON_ACTIONABLE"
    assert outcome.gate_state is None
    assert outcome.planner_state == "NOT_REACHED"


def test_gate_denied_writes_audit_without_planner() -> None:
    conn = FakeConnection()
    seed_happy_path(conn)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM market_price_snapshot")
    insert_market_price(conn, price=Decimal("65000"))
    item = _build_item(conn)
    denied_item = replace(item, automatic_exit_execution_enabled=False)
    outcome = evaluate_automatic_exit_runtime_item_v1(conn, item=denied_item, evaluation_ts_utc=NOW)
    assert outcome.candidate_state == "CANDIDATE"
    assert outcome.gate_state == "DENIED"
    assert outcome.planner_state == "NOT_REACHED"
    rows = _audit_rows(conn)
    assert rows[0]["immutable_plan_json"] is None


def test_planner_rejection_is_audited_fail_closed() -> None:
    conn = FakeConnection()
    seed_happy_path(conn)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM market_price_snapshot")
    insert_market_price(conn, price=Decimal("65000"))
    item = _build_item(conn)
    # A too-small free quantity rounds the approved ceiling down to zero at the planner.
    starved_item = replace(item, free_quantity_base=Decimal("0.00001"))
    outcome = evaluate_automatic_exit_runtime_item_v1(conn, item=starved_item, evaluation_ts_utc=NOW)
    assert outcome.gate_state == "APPROVED"
    assert outcome.planner_state == "REJECTED"
    rows = _audit_rows(conn)
    assert rows[0]["planner_reason_code"] is not None
    assert rows[0]["immutable_plan_json"] is None


def test_runtime_cannot_bypass_gate_even_when_execution_enabled() -> None:
    """Live-trading-enabled account still hits LIVE_EXECUTION_NOT_GRANTED at the gate."""
    conn = FakeConnection()
    seed_happy_path(conn)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM market_price_snapshot")
    insert_market_price(conn, price=Decimal("65000"))
    item = _build_item(conn)
    live_item = replace(item, live_trading_enabled=True)
    outcome = evaluate_automatic_exit_runtime_item_v1(conn, item=live_item, evaluation_ts_utc=NOW)
    assert outcome.gate_state == "DENIED"
    assert outcome.planner_state == "NOT_REACHED"


def test_rerun_same_evidence_is_idempotent_no_duplicate_row() -> None:
    conn = FakeConnection()
    seed_happy_path(conn)
    item = _build_item(conn)
    first = evaluate_automatic_exit_runtime_item_v1(conn, item=item, evaluation_ts_utc=NOW)
    second = evaluate_automatic_exit_runtime_item_v1(conn, item=item, evaluation_ts_utc=NOW + timedelta(minutes=1))
    assert first.idempotency_key == second.idempotency_key
    assert first.audit_outcome == "inserted"
    assert second.audit_outcome == "idempotent_existing"
    rows = _audit_rows(conn)
    assert len(rows) == 1


def test_changed_market_price_snapshot_creates_new_key() -> None:
    conn = FakeConnection()
    seed_happy_path(conn)
    item = _build_item(conn)
    outcome_1 = evaluate_automatic_exit_runtime_item_v1(conn, item=item, evaluation_ts_utc=NOW)

    insert_market_price(conn, price=Decimal("50100"))
    item_2 = _build_item(conn)
    outcome_2 = evaluate_automatic_exit_runtime_item_v1(conn, item=item_2, evaluation_ts_utc=NOW)

    assert outcome_1.idempotency_key != outcome_2.idempotency_key
    assert len(_audit_rows(conn)) == 2


def test_replay_source_evidence_is_complete_in_audit_row() -> None:
    conn = FakeConnection()
    seed_happy_path(conn)
    item = _build_item(conn)
    evaluate_automatic_exit_runtime_item_v1(conn, item=item, evaluation_ts_utc=NOW)
    row = _audit_rows(conn)[0]
    import json
    evidence = json.loads(row["source_evidence_json"])
    for key in (
        "trading_account_id", "position_reference", "venue", "asset_id", "market",
        "position_snapshot_id", "balance_snapshot_id", "open_order_snapshot_run_id",
        "market_price_snapshot_id", "automatic_exit_permission_id", "exit_profile_id",
        "exit_profile_version", "exit_profile_observed_ts_utc", "venue_constraint_id",
        "venue_metadata_synced_ts_utc", "runtime_version",
    ):
        assert key in evidence and evidence[key] not in (None, "")
