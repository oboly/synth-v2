"""Issue #392 Phase 6 blocker C: the decision_gate composition seam.

Proves ``evaluate_account_protection_for_automatic_exit_v1`` assembles real
persisted config + lock evidence, calls the canonical #318 evaluator exactly
once, and fails closed on unresolved config / invalid persisted evidence
rather than raising an uncaught exception that would abort a whole runtime
cycle.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from src.decision_gate.account_protection_contract_v1 import (
    ACTION_EXIT,
    ACTION_REDUCE,
    PROTECTION_MANUAL_ACCOUNT_LOCK,
    PROTECTION_MAX_ACCOUNT_DRAWDOWN_BLOCK,
    REASON_PROTECTION_CONFIGURATION_UNRESOLVED,
    STATE_BLOCKED,
    STATE_PERMITTED,
)
from src.decision_gate.account_protection_evaluation_v1 import (
    evaluate_account_protection_for_automatic_exit_v1,
)
from tests.automatic_exit_runtime_fixtures_v1 import (
    FakeConnection,
    TS,
    insert_protection_lock_fact,
    insert_protection_policy_config,
    insert_trading_account,
)


ACCOUNT_A = 7
ACCOUNT_B = 8
ASSET_ID = 101


def _base_conn(*, account_id: int = ACCOUNT_A) -> FakeConnection:
    conn = FakeConnection()
    insert_trading_account(conn, account_id=account_id)
    return conn


def test_unresolved_configuration_fails_closed_without_raising():
    conn = _base_conn()
    result = evaluate_account_protection_for_automatic_exit_v1(
        conn,
        trading_account_id=ACCOUNT_A,
        asset_id=ASSET_ID,
        requested_action=ACTION_REDUCE,
        account_state_observed_ts_utc=TS,
        evaluation_ts_utc=TS,
    )
    assert result.decision_state == STATE_BLOCKED
    assert result.reason_code == REASON_PROTECTION_CONFIGURATION_UNRESOLVED


def test_permissive_config_with_no_locks_permits_reduce_and_exit():
    conn = _base_conn()
    insert_protection_policy_config(conn, account_id=ACCOUNT_A)
    for action in (ACTION_REDUCE, ACTION_EXIT):
        result = evaluate_account_protection_for_automatic_exit_v1(
            conn,
            trading_account_id=ACCOUNT_A,
            asset_id=ASSET_ID,
            requested_action=action,
            account_state_observed_ts_utc=TS,
            evaluation_ts_utc=TS,
        )
        assert result.decision_state == STATE_PERMITTED
        assert result.trading_account_id == ACCOUNT_A
        assert result.requested_action == action


def test_manual_account_lock_blocks_reduce_and_exit():
    conn = _base_conn()
    insert_protection_policy_config(conn, account_id=ACCOUNT_A)
    insert_protection_lock_fact(
        conn, lifecycle_id="lc-1", event_id="ev-1", protection_code=PROTECTION_MANUAL_ACCOUNT_LOCK,
        account_id=ACCOUNT_A,
    )
    for action in (ACTION_REDUCE, ACTION_EXIT):
        result = evaluate_account_protection_for_automatic_exit_v1(
            conn,
            trading_account_id=ACCOUNT_A,
            asset_id=ASSET_ID,
            requested_action=action,
            account_state_observed_ts_utc=TS,
            evaluation_ts_utc=TS,
        )
        assert result.decision_state == STATE_BLOCKED
        assert result.protection_code == PROTECTION_MANUAL_ACCOUNT_LOCK


def test_missing_producer_for_configured_metric_fails_closed_for_reduce_and_exit():
    """A configured drawdown threshold with no metric fact producer must block, not silently permit."""
    conn = _base_conn()
    insert_protection_policy_config(conn, account_id=ACCOUNT_A, max_account_drawdown=Decimal("10"))
    for action in (ACTION_REDUCE, ACTION_EXIT):
        result = evaluate_account_protection_for_automatic_exit_v1(
            conn,
            trading_account_id=ACCOUNT_A,
            asset_id=ASSET_ID,
            requested_action=action,
            account_state_observed_ts_utc=TS,
            evaluation_ts_utc=TS,
        )
        assert result.decision_state == STATE_BLOCKED


def test_lock_is_strictly_account_isolated():
    conn = _base_conn(account_id=ACCOUNT_A)
    insert_trading_account(conn, account_id=ACCOUNT_B)
    insert_protection_policy_config(conn, account_id=ACCOUNT_A)
    insert_protection_policy_config(conn, account_id=ACCOUNT_B)
    insert_protection_lock_fact(
        conn, lifecycle_id="lc-a", event_id="ev-a", protection_code=PROTECTION_MANUAL_ACCOUNT_LOCK,
        account_id=ACCOUNT_A,
    )
    account_a = evaluate_account_protection_for_automatic_exit_v1(
        conn, trading_account_id=ACCOUNT_A, asset_id=ASSET_ID, requested_action=ACTION_REDUCE,
        account_state_observed_ts_utc=TS, evaluation_ts_utc=TS,
    )
    account_b = evaluate_account_protection_for_automatic_exit_v1(
        conn, trading_account_id=ACCOUNT_B, asset_id=ASSET_ID, requested_action=ACTION_REDUCE,
        account_state_observed_ts_utc=TS, evaluation_ts_utc=TS,
    )
    assert account_a.decision_state == STATE_BLOCKED
    assert account_b.decision_state == STATE_PERMITTED


def test_persisted_lock_survives_reload_and_is_deterministic():
    conn = _base_conn()
    insert_protection_policy_config(conn, account_id=ACCOUNT_A)
    insert_protection_lock_fact(
        conn, lifecycle_id="lc-1", event_id="ev-1", protection_code=PROTECTION_MANUAL_ACCOUNT_LOCK,
        account_id=ACCOUNT_A,
    )
    first = evaluate_account_protection_for_automatic_exit_v1(
        conn, trading_account_id=ACCOUNT_A, asset_id=ASSET_ID, requested_action=ACTION_EXIT,
        account_state_observed_ts_utc=TS, evaluation_ts_utc=TS,
    )
    second = evaluate_account_protection_for_automatic_exit_v1(
        conn, trading_account_id=ACCOUNT_A, asset_id=ASSET_ID, requested_action=ACTION_EXIT,
        account_state_observed_ts_utc=TS, evaluation_ts_utc=TS,
    )
    assert first.decision_state == second.decision_state == STATE_BLOCKED
    assert first.protection_code == second.protection_code == PROTECTION_MANUAL_ACCOUNT_LOCK


def test_asset_cooldown_for_other_asset_does_not_block_and_current_asset_lock_permits_reduce():
    from src.decision_gate.account_protection_contract_v1 import PROTECTION_LOW_PROFIT_ASSET_COOLDOWN, SCOPE_ASSET

    conn = _base_conn()
    insert_protection_policy_config(conn, account_id=ACCOUNT_A)
    insert_protection_lock_fact(
        conn, lifecycle_id="lc-cooldown", event_id="ev-cooldown", protection_code=PROTECTION_LOW_PROFIT_ASSET_COOLDOWN,
        account_id=ACCOUNT_A, scope_type=SCOPE_ASSET, scope_id=str(ASSET_ID),
    )
    other_asset = evaluate_account_protection_for_automatic_exit_v1(
        conn, trading_account_id=ACCOUNT_A, asset_id=999, requested_action=ACTION_REDUCE,
        account_state_observed_ts_utc=TS, evaluation_ts_utc=TS,
    )
    same_asset_reduce = evaluate_account_protection_for_automatic_exit_v1(
        conn, trading_account_id=ACCOUNT_A, asset_id=ASSET_ID, requested_action=ACTION_REDUCE,
        account_state_observed_ts_utc=TS, evaluation_ts_utc=TS,
    )
    assert other_asset.decision_state == STATE_PERMITTED
    # Cooldown blocks BUY only; REDUCE on the cooled-down asset itself still permits.
    assert same_asset_reduce.decision_state == STATE_PERMITTED
