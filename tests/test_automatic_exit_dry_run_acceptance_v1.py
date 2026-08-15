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
