from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

import src.exit_policy.automatic_exit_runtime_orchestrator_v1 as orchestrator_module
from src.decision_gate.account_protection_contract_v1 import (
    PROTECTION_MANUAL_ACCOUNT_LOCK,
    PROTECTION_MAX_ACCOUNT_DRAWDOWN_BLOCK,
    REASON_OK,
    REASON_PROTECTION_CONFIGURATION_UNRESOLVED,
)
from src.exit_policy.automatic_exit_runtime_audit_writer_v1 import IdempotencyPayloadConflictError
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
    insert_live_permission,
    insert_market_price,
    insert_protection_lock_fact,
    insert_protection_policy_config,
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


def test_runtime_cannot_bypass_gate_via_legacy_live_flag_alone() -> None:
    """A retained live_trading_enabled=True on a paper-mode account is inconsistent evidence, not a bypass."""
    conn = FakeConnection()
    seed_happy_path(conn)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM market_price_snapshot")
    insert_market_price(conn, price=Decimal("65000"))
    item = _build_item(conn)
    live_item = replace(item, live_trading_enabled=True)
    outcome = evaluate_automatic_exit_runtime_item_v1(conn, item=live_item, evaluation_ts_utc=NOW)
    assert outcome.gate_state == "NON_ACTIONABLE"
    assert outcome.planner_state == "NOT_REACHED"


def test_runtime_live_account_mode_alone_without_explicit_permission_is_denied() -> None:
    """Issue #392 Phase 6 blocker B: account_mode=live alone is never sufficient.

    No row exists in automatic_exit_live_decision_gate_permission_v1 for this
    account; the decision_gate-owned evaluation seam resolves that to a typed
    DENIED evaluation, which the orchestrator forwards unchanged.
    """
    conn = FakeConnection()
    seed_happy_path(conn)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM market_price_snapshot")
    insert_market_price(conn, price=Decimal("65000"))
    item = _build_item(conn)
    live_item = replace(item, account_mode="live", live_trading_enabled=True)
    outcome = evaluate_automatic_exit_runtime_item_v1(conn, item=live_item, evaluation_ts_utc=NOW)
    assert outcome.gate_state == "DENIED"
    assert outcome.planner_state == "NOT_REACHED"


def test_runtime_live_account_with_explicit_permission_reaches_staged_plan() -> None:
    """Issue #392 Phase 6 blocker B: explicit decision-gate LIVE permission lets a LIVE candidate stage a plan.

    The permission fact is persisted in automatic_exit_live_decision_gate_permission_v1
    and resolved fresh by the orchestrator's call into decision_gate, not
    carried on RuntimeItemV1 -- exit_policy never resolves LIVE permission
    itself (Issue #392 Phase 6 blocker B ownership fix).
    """
    conn = FakeConnection()
    seed_happy_path(conn)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM market_price_snapshot")
    insert_market_price(conn, price=Decimal("65000"))
    insert_live_permission(conn, account_id=7, live_execution_permitted=True)
    item = _build_item(conn)
    live_item = replace(item, account_mode="live", live_trading_enabled=True)
    outcome = evaluate_automatic_exit_runtime_item_v1(conn, item=live_item, evaluation_ts_utc=NOW)
    assert outcome.gate_state == "APPROVED"
    assert outcome.planner_state == "STAGED"
    rows = _audit_rows(conn)
    assert rows[0]["immutable_plan_json"] is not None


def test_runtime_live_account_manual_lock_denies() -> None:
    """LIVE candidates still compose with #318 account protection identically to paper: manual lock denies."""
    conn = FakeConnection()
    seed_happy_path(conn)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM market_price_snapshot")
    insert_market_price(conn, price=Decimal("65000"))
    insert_live_permission(conn, account_id=7, live_execution_permitted=True)
    live_item = replace(_build_item(conn), account_mode="live", live_trading_enabled=True)
    insert_protection_lock_fact(
        conn, lifecycle_id="manual-1", event_id="manual-event-1", protection_code=PROTECTION_MANUAL_ACCOUNT_LOCK,
    )
    outcome = evaluate_automatic_exit_runtime_item_v1(conn, item=live_item, evaluation_ts_utc=NOW)
    assert outcome.gate_state == "DENIED"
    assert outcome.planner_state == "NOT_REACHED"


def test_runtime_live_account_drawdown_protection_permits_reduce() -> None:
    """LIVE candidates still compose with #318 account protection identically to paper: drawdown permits REDUCE."""
    conn = FakeConnection()
    seed_happy_path(conn)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM market_price_snapshot")
    insert_market_price(conn, price=Decimal("65000"))
    insert_live_permission(conn, account_id=7, live_execution_permitted=True)
    live_item = replace(_build_item(conn), account_mode="live", live_trading_enabled=True)
    insert_protection_lock_fact(
        conn, lifecycle_id="drawdown-1", event_id="drawdown-event-1", protection_code=PROTECTION_MAX_ACCOUNT_DRAWDOWN_BLOCK,
    )
    outcome = evaluate_automatic_exit_runtime_item_v1(conn, item=live_item, evaluation_ts_utc=NOW)
    assert outcome.gate_state == "APPROVED"
    assert outcome.planner_state == "STAGED"


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
        "venue_metadata_synced_ts_utc",
    ):
        assert key in evidence and evidence[key] not in (None, "")
    assert "runtime_version" not in evidence
    assert row["runtime_version"] == orchestrator_module.RUNTIME_VERSION


def test_runtime_version_change_keeps_same_evidence_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeConnection()
    seed_happy_path(conn)
    item = _build_item(conn)
    monkeypatch.setattr(orchestrator_module, "RUNTIME_VERSION", "runtime-v1")
    first = evaluate_automatic_exit_runtime_item_v1(conn, item=item, evaluation_ts_utc=NOW)
    monkeypatch.setattr(orchestrator_module, "RUNTIME_VERSION", "runtime-v2")
    second = evaluate_automatic_exit_runtime_item_v1(conn, item=item, evaluation_ts_utc=NOW + timedelta(minutes=1))
    assert first.audit_outcome == "inserted"
    assert second.audit_outcome == "idempotent_existing"
    row = _audit_rows(conn)[0]
    assert row["runtime_version"] == "runtime-v1"


def test_same_evidence_with_changed_decision_fails_closed() -> None:
    conn = FakeConnection()
    seed_happy_path(conn)
    item = _build_item(conn)
    evaluate_automatic_exit_runtime_item_v1(conn, item=item, evaluation_ts_utc=NOW)
    with pytest.raises(IdempotencyPayloadConflictError):
        evaluate_automatic_exit_runtime_item_v1(
            conn,
            item=replace(item, current_price=Decimal("65000")),
            evaluation_ts_utc=NOW + timedelta(minutes=1),
        )


# --- Issue #392 Phase 6 blocker C: real #318 account-protection wiring -----


def test_reduce_with_no_active_protection_matches_prior_behavior() -> None:
    """Issue #392 Phase 6 blocker C, case 1: REDUCE + no active protection -> existing behavior."""
    conn = FakeConnection()
    seed_happy_path(conn)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM market_price_snapshot")
    insert_market_price(conn, price=Decimal("65000"))  # above target -> REDUCE candidate
    item = _build_item(conn)
    outcome = evaluate_automatic_exit_runtime_item_v1(conn, item=item, evaluation_ts_utc=NOW)
    assert outcome.gate_state == "APPROVED"
    assert outcome.planner_state == "STAGED"
    row = _audit_rows(conn)[0]
    assert row["protection_code"] is None
    assert row["protection_reason_code"] == REASON_OK


def test_exit_with_no_active_protection_matches_prior_behavior() -> None:
    """Issue #392 Phase 6 blocker C, case 2: EXIT + no active protection -> existing behavior."""
    conn = FakeConnection()
    seed_happy_path(conn)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM market_price_snapshot")
    insert_market_price(conn, price=Decimal("35000"))  # below invalidation -> EXIT candidate
    item = _build_item(conn)
    outcome = evaluate_automatic_exit_runtime_item_v1(conn, item=item, evaluation_ts_utc=NOW)
    assert outcome.candidate_state == "CANDIDATE"
    assert outcome.gate_state == "APPROVED"
    assert outcome.planner_state == "STAGED"
    row = _audit_rows(conn)[0]
    assert row["protection_code"] is None
    assert row["protection_reason_code"] == REASON_OK


def test_drawdown_protection_permits_reduce_via_real_wiring() -> None:
    """Case 3: REDUCE + drawdown protection -> protection itself permits (risk-reducing action)."""
    conn = FakeConnection()
    seed_happy_path(conn)
    insert_protection_lock_fact(
        conn, lifecycle_id="lc-dd", event_id="ev-dd", protection_code=PROTECTION_MAX_ACCOUNT_DRAWDOWN_BLOCK,
    )
    with conn.cursor() as cur:
        cur.execute("DELETE FROM market_price_snapshot")
    insert_market_price(conn, price=Decimal("65000"))
    item = _build_item(conn)
    outcome = evaluate_automatic_exit_runtime_item_v1(conn, item=item, evaluation_ts_utc=NOW)
    assert outcome.gate_state == "APPROVED"
    assert outcome.planner_state == "STAGED"
    row = _audit_rows(conn)[0]
    assert row["protection_code"] is None  # protection permitted -> gate's own reason (OK) is recorded, not a block
    assert row["protection_reason_code"] == REASON_OK


def test_drawdown_protection_permits_exit_via_real_wiring() -> None:
    """Case 4: EXIT + drawdown protection -> protection itself permits (risk-reducing action)."""
    conn = FakeConnection()
    seed_happy_path(conn)
    insert_protection_lock_fact(
        conn, lifecycle_id="lc-dd", event_id="ev-dd", protection_code=PROTECTION_MAX_ACCOUNT_DRAWDOWN_BLOCK,
    )
    with conn.cursor() as cur:
        cur.execute("DELETE FROM market_price_snapshot")
    insert_market_price(conn, price=Decimal("35000"))
    item = _build_item(conn)
    outcome = evaluate_automatic_exit_runtime_item_v1(conn, item=item, evaluation_ts_utc=NOW)
    assert outcome.gate_state == "APPROVED"
    assert outcome.planner_state == "STAGED"


def test_manual_lock_denies_reduce_via_real_wiring() -> None:
    """Case 5: REDUCE + manual account lock -> gate denies."""
    conn = FakeConnection()
    seed_happy_path(conn)
    insert_protection_lock_fact(
        conn, lifecycle_id="lc-manual", event_id="ev-manual", protection_code=PROTECTION_MANUAL_ACCOUNT_LOCK,
    )
    with conn.cursor() as cur:
        cur.execute("DELETE FROM market_price_snapshot")
    insert_market_price(conn, price=Decimal("65000"))
    item = _build_item(conn)
    outcome = evaluate_automatic_exit_runtime_item_v1(conn, item=item, evaluation_ts_utc=NOW)
    assert outcome.gate_state == "DENIED"
    assert outcome.planner_state == "NOT_REACHED"
    row = _audit_rows(conn)[0]
    assert row["protection_code"] == PROTECTION_MANUAL_ACCOUNT_LOCK
    assert row["immutable_plan_json"] is None


def test_manual_lock_denies_exit_via_real_wiring() -> None:
    """Case 6: EXIT + manual account lock -> gate denies."""
    conn = FakeConnection()
    seed_happy_path(conn)
    insert_protection_lock_fact(
        conn, lifecycle_id="lc-manual", event_id="ev-manual", protection_code=PROTECTION_MANUAL_ACCOUNT_LOCK,
    )
    with conn.cursor() as cur:
        cur.execute("DELETE FROM market_price_snapshot")
    insert_market_price(conn, price=Decimal("35000"))
    item = _build_item(conn)
    outcome = evaluate_automatic_exit_runtime_item_v1(conn, item=item, evaluation_ts_utc=NOW)
    assert outcome.gate_state == "DENIED"
    assert outcome.planner_state == "NOT_REACHED"


def test_missing_protection_config_fails_closed_and_planner_not_reached() -> None:
    """Case 7 (config variant of the fail-closed matrix): no resolvable protection config blocks approval."""
    conn = FakeConnection()
    seed_happy_path(conn)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM account_protection_policy_config_v1")
        cur.execute("DELETE FROM market_price_snapshot")
    insert_market_price(conn, price=Decimal("65000"))
    item = _build_item(conn)
    outcome = evaluate_automatic_exit_runtime_item_v1(conn, item=item, evaluation_ts_utc=NOW)
    assert outcome.gate_state == "DENIED"
    assert outcome.planner_state == "NOT_REACHED"
    row = _audit_rows(conn)[0]
    assert row["gate_reason_code"] == REASON_PROTECTION_CONFIGURATION_UNRESOLVED
    assert row["immutable_plan_json"] is None


def test_missing_configured_metric_producer_fails_closed() -> None:
    """Case 7: a configured metric threshold with no wired producer must block, not silently permit."""
    conn = FakeConnection()
    seed_happy_path(conn, account_id=7)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM account_protection_policy_config_v1")
    insert_protection_policy_config(conn, account_id=7, max_account_drawdown=Decimal("10"))
    with conn.cursor() as cur:
        cur.execute("DELETE FROM market_price_snapshot")
    insert_market_price(conn, price=Decimal("65000"))
    item = _build_item(conn)
    outcome = evaluate_automatic_exit_runtime_item_v1(conn, item=item, evaluation_ts_utc=NOW)
    assert outcome.gate_state == "DENIED"
    assert outcome.planner_state == "NOT_REACHED"


def test_account_a_protection_lock_does_not_affect_account_b() -> None:
    """Case 14: Account A protection does not affect Account B."""
    from tests.automatic_exit_runtime_fixtures_v1 import (
        bind_account_market,
        insert_balance,
        insert_complete_bundle,
        insert_permission,
        insert_position,
        insert_trading_account,
    )

    conn = FakeConnection()
    seed_happy_path(conn, account_id=7)
    # Account B reuses the same shared venue_market/venue_constraint rows
    # (both UNIQUE on (venue, market)) instead of re-seeding them.
    insert_trading_account(conn, account_id=8)
    insert_complete_bundle(conn, account_id=8)
    insert_position(conn, account_id=8)
    bind_account_market(conn, account_id=8, venue_market_id=1)
    insert_balance(conn, account_id=8)
    insert_permission(conn, account_id=8)
    insert_protection_policy_config(conn, account_id=8)
    insert_protection_lock_fact(
        conn, lifecycle_id="lc-manual-a", event_id="ev-manual-a", protection_code=PROTECTION_MANUAL_ACCOUNT_LOCK,
        account_id=7,
    )
    with conn.cursor() as cur:
        cur.execute("DELETE FROM market_price_snapshot")
    insert_market_price(conn, price=Decimal("65000"))

    accounts = load_eligible_trading_accounts(conn, venue="bitvavo")
    bundle_a = load_latest_complete_account_state_bundle(conn, trading_account_id=7, venue="bitvavo", now=NOW)
    positions_a = load_positive_positions(conn, bundle=bundle_a)
    item_a = build_runtime_item_v1(conn, account=accounts[0], bundle=bundle_a, position=positions_a[0], now=NOW)

    bundle_b = load_latest_complete_account_state_bundle(conn, trading_account_id=8, venue="bitvavo", now=NOW)
    positions_b = load_positive_positions(conn, bundle=bundle_b)
    account_b = next(a for a in accounts if a.trading_account_id == 8)
    item_b = build_runtime_item_v1(conn, account=account_b, bundle=bundle_b, position=positions_b[0], now=NOW)

    outcome_a = evaluate_automatic_exit_runtime_item_v1(conn, item=item_a, evaluation_ts_utc=NOW)
    outcome_b = evaluate_automatic_exit_runtime_item_v1(conn, item=item_b, evaluation_ts_utc=NOW)
    assert outcome_a.gate_state == "DENIED"
    assert outcome_b.gate_state == "APPROVED"


def test_real_gate_context_receives_populated_protection_evaluation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Case 15: protection result is actually populated into the real #392 gate context, not left None."""
    conn = FakeConnection()
    seed_happy_path(conn)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM market_price_snapshot")
    insert_market_price(conn, price=Decimal("65000"))
    item = _build_item(conn)

    captured = {}
    real_evaluate = orchestrator_module.evaluate_automatic_exit_candidate_permission_v1

    def _spy(*, candidate, context):
        captured["account_protection_evaluation"] = context.account_protection_evaluation
        return real_evaluate(candidate=candidate, context=context)

    monkeypatch.setattr(orchestrator_module, "evaluate_automatic_exit_candidate_permission_v1", _spy)
    evaluate_automatic_exit_runtime_item_v1(conn, item=item, evaluation_ts_utc=NOW)
    assert captured["account_protection_evaluation"] is not None
    assert captured["account_protection_evaluation"].trading_account_id == item.trading_account_id


def test_no_executor_or_broker_imports_in_protection_wiring_modules() -> None:
    """Cases 19/20: the new wiring modules import no executor or broker code."""
    import ast
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    modules = (
        repo_root / "src/decision_gate/account_protection_evaluation_v1.py",
        repo_root / "src/decision_gate/account_protection_policy_contract_v1.py",
        repo_root / "src/decision_gate/account_protection_policy_repository_v1.py",
    )
    forbidden_prefixes = ("src.executor", "src.manual_execution", "src.account_provisioning")
    for module_path in modules:
        tree = ast.parse(module_path.read_text(), filename=str(module_path))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
        for name in names:
            for forbidden in forbidden_prefixes:
                assert not (name == forbidden or name.startswith(forbidden + ".")), (
                    f"{module_path.name} imports forbidden module {name}"
                )
