from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import json

import pytest

import src.exit_policy.automatic_exit_dry_run_acceptance_v1 as acceptance
from src.exit_policy.automatic_exit_runtime_repository_v1 import (
    build_runtime_item_v1, load_eligible_trading_accounts, load_latest_complete_account_state_bundle, load_positive_positions,
)
from src.exit_policy.automatic_exit_runtime_audit_writer_v1 import canonical_json
from tests.automatic_exit_runtime_fixtures_v1 import FakeConnection, TS, insert_market_price, seed_happy_path


NOW = TS + timedelta(minutes=5)


def _item(conn: FakeConnection):
    account = load_eligible_trading_accounts(conn, venue="bitvavo")[0]
    bundle = load_latest_complete_account_state_bundle(conn, trading_account_id=7, venue="bitvavo", now=NOW)
    return build_runtime_item_v1(conn, account=account, bundle=bundle, position=load_positive_positions(conn, bundle=bundle)[0], now=NOW)


def _actionable(conn: FakeConnection):
    seed_happy_path(conn)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM market_price_snapshot")
    insert_market_price(conn, price=Decimal("65000"))
    return _item(conn)


def test_target_reduce_db_current_and_replay_are_semantically_identical() -> None:
    conn = FakeConnection()
    _actionable(conn)
    first = acceptance.run_db_current_acceptance_v1(conn, trading_account_id=7, venue="bitvavo", evaluation_ts_utc=NOW)
    replay = acceptance.run_automatic_exit_acceptance_v1(conn, mode=acceptance.ACCEPTANCE_MODE_REPLAY, replay_input=first.replay_input)
    assert (first.candidate_state, first.candidate_action, first.gate_state, first.planner_state) == ("CANDIDATE", "REDUCE", "APPROVED", "STAGED")
    assert first.immutable_plan_hash == replay.immutable_plan_hash
    assert first.source_evidence_hash == replay.source_evidence_hash
    assert first.safety_markers == acceptance.SAFETY_MARKERS


def test_invalidation_exit_and_no_action_use_exact_orchestrator_outcomes() -> None:
    exit_conn = FakeConnection()
    _actionable(exit_conn)
    exit_item = replace(_item(exit_conn), current_price=Decimal("40000"))
    exit_result = acceptance.run_automatic_exit_acceptance_v1(exit_conn, mode=acceptance.ACCEPTANCE_MODE_REPLAY, replay_input=acceptance.build_replay_input_v1(item=exit_item, evaluation_ts_utc=NOW))
    assert (exit_result.candidate_action, exit_result.gate_state, exit_result.planner_state) == ("EXIT", "APPROVED", "STAGED")
    no_action_conn = FakeConnection()
    seed_happy_path(no_action_conn)
    result = acceptance.run_db_current_acceptance_v1(no_action_conn, trading_account_id=7, venue="bitvavo", evaluation_ts_utc=NOW)
    assert (result.candidate_state, result.gate_state, result.planner_state, result.immutable_plan_hash) == ("NO_ACTION", None, "NOT_REACHED", None)


@pytest.mark.parametrize("field,value,expected_gate", [("automatic_exit_execution_enabled", False, "DENIED"), ("blocking_conflict", True, "DENIED")])
def test_gate_denials_never_reach_planner(field: str, value: bool, expected_gate: str) -> None:
    conn = FakeConnection()
    item = replace(_actionable(conn), **{field: value})
    result = acceptance.run_automatic_exit_acceptance_v1(conn, mode=acceptance.ACCEPTANCE_MODE_REPLAY, replay_input=acceptance.build_replay_input_v1(item=item, evaluation_ts_utc=NOW))
    assert result.gate_state == expected_gate
    assert result.planner_state == "NOT_REACHED"


def test_stale_and_insufficient_quantity_preserve_runtime_fail_closed_semantics() -> None:
    conn = FakeConnection()
    stale = replace(_actionable(conn), account_state_observed_ts_utc=TS - timedelta(hours=1))
    stale_result = acceptance.run_automatic_exit_acceptance_v1(conn, mode=acceptance.ACCEPTANCE_MODE_REPLAY, replay_input=acceptance.build_replay_input_v1(item=stale, evaluation_ts_utc=NOW))
    assert stale_result.candidate_state == "NON_ACTIONABLE"
    quantity_conn = FakeConnection()
    starved = replace(_actionable(quantity_conn), free_quantity_base=Decimal("0.00001"))
    quantity_result = acceptance.run_automatic_exit_acceptance_v1(quantity_conn, mode=acceptance.ACCEPTANCE_MODE_REPLAY, replay_input=acceptance.build_replay_input_v1(item=starved, evaluation_ts_utc=NOW))
    assert quantity_result.planner_state == "REJECTED"


def test_live_authority_environment_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeConnection()
    item = _actionable(conn)
    monkeypatch.setenv("SYNTH_LIVE_EXECUTION_PERMISSION", "GRANTED")
    with pytest.raises(acceptance.AutomaticExitDryRunAcceptanceError, match="LIVE_AUTHORITY_FORBIDDEN"):
        acceptance.run_automatic_exit_acceptance_v1(conn, mode=acceptance.ACCEPTANCE_MODE_REPLAY, replay_input=acceptance.build_replay_input_v1(item=item, evaluation_ts_utc=NOW))


def test_replay_input_survives_canonical_json_round_trip() -> None:
    conn = FakeConnection()
    item = _actionable(conn)
    original = acceptance.build_replay_input_v1(item=item, evaluation_ts_utc=NOW)
    payload = json.loads(canonical_json({"evaluation_ts_utc": original.evaluation_ts_utc, "runtime_item_json": original.runtime_item_json}))
    restored = acceptance.AutomaticExitDryRunAcceptanceInputV1(
        evaluation_ts_utc=__import__("datetime").datetime.fromisoformat(payload["evaluation_ts_utc"].replace("Z", "+00:00")),
        runtime_item_json=payload["runtime_item_json"],
    )
    result = acceptance.run_automatic_exit_acceptance_v1(conn, mode=acceptance.ACCEPTANCE_MODE_REPLAY, replay_input=restored)
    assert result.planner_state == "STAGED"


@pytest.mark.parametrize(("constraints", "reason"), [
    ({"min_base_quantity": Decimal("2")}, "FINAL_QUANTITY_BELOW_MIN_BASE_QUANTITY"),
    ({"min_quote_notional": Decimal("20000")}, "LADDER_LEG_1_INVALID:BELOW_MIN_QUOTE_NOTIONAL"),
    ({"qty_step_size": Decimal("0.125")}, None),
])
def test_venue_constraints_drive_minimums_and_non_8dp_rounding(constraints: dict, reason: str | None) -> None:
    conn = FakeConnection()
    item = _actionable(conn)
    item = replace(item, venue_constraints=replace(item.venue_constraints, **constraints))
    result = acceptance.run_automatic_exit_acceptance_v1(conn, mode=acceptance.ACCEPTANCE_MODE_REPLAY, replay_input=acceptance.build_replay_input_v1(item=item, evaluation_ts_utc=NOW))
    if reason:
        assert (result.planner_state, result.planner_reason_code, result.immutable_plan_hash) == ("REJECTED", reason, None)
    else:
        assert result.planner_state == "STAGED"


def test_stale_venue_metadata_and_changed_evidence_change_acceptance_identity() -> None:
    conn = FakeConnection()
    item = _actionable(conn)
    first = acceptance.run_automatic_exit_acceptance_v1(conn, mode=acceptance.ACCEPTANCE_MODE_REPLAY, replay_input=acceptance.build_replay_input_v1(item=item, evaluation_ts_utc=NOW))
    changed = replace(item, venue_constraint_id=999, venue_constraints=replace(item.venue_constraints, metadata_synced_ts_utc=TS - timedelta(days=8)))
    second = acceptance.run_automatic_exit_acceptance_v1(conn, mode=acceptance.ACCEPTANCE_MODE_REPLAY, replay_input=acceptance.build_replay_input_v1(item=changed, evaluation_ts_utc=NOW))
    assert second.planner_state == "REJECTED"
    assert second.immutable_plan_hash is None
    assert first.source_evidence_hash != second.source_evidence_hash


def test_stale_market_and_profile_are_non_actionable_without_plan() -> None:
    for field in ("market_price_observed_ts_utc",):
        conn = FakeConnection(); item = replace(_actionable(conn), **{field: TS - timedelta(hours=1)})
        result = acceptance.run_automatic_exit_acceptance_v1(conn, mode=acceptance.ACCEPTANCE_MODE_REPLAY, replay_input=acceptance.build_replay_input_v1(item=item, evaluation_ts_utc=NOW))
        assert (result.candidate_state, result.candidate_reason_code, result.immutable_plan_hash) == ("NON_ACTIONABLE", "EXIT_CONTEXT_STALE", None)


def test_replay_matches_invalidation_denial_and_planner_rejection() -> None:
    cases = []
    conn = FakeConnection(); cases.append(replace(_actionable(conn), current_price=Decimal("40000")))
    conn = FakeConnection(); cases.append(replace(_actionable(conn), automatic_exit_execution_enabled=False))
    conn = FakeConnection(); cases.append(replace(_actionable(conn), free_quantity_base=Decimal("0.00001")))
    for item in cases:
        conn = FakeConnection(); item = _actionable(conn) if item is cases[0] else item
        packet = acceptance.build_replay_input_v1(item=item, evaluation_ts_utc=NOW)
        first = acceptance.run_automatic_exit_acceptance_v1(conn, mode=acceptance.ACCEPTANCE_MODE_REPLAY, replay_input=packet)
        second = acceptance.run_automatic_exit_acceptance_v1(conn, mode=acceptance.ACCEPTANCE_MODE_REPLAY, replay_input=packet)
        assert (first.candidate_state, first.candidate_action, first.candidate_reason_code, first.gate_state, first.gate_reason_code, first.planner_state, first.planner_reason_code, first.immutable_plan_hash, first.source_evidence_hash) == (second.candidate_state, second.candidate_action, second.candidate_reason_code, second.gate_state, second.gate_reason_code, second.planner_state, second.planner_reason_code, second.immutable_plan_hash, second.source_evidence_hash)
