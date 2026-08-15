from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.decision_gate.account_protection_contract_v1 import (
    ACTION_BUY,
    LOCK_FACT_CONTRACT_VERSION,
    PROTECTION_MAX_ACCOUNT_DRAWDOWN_BLOCK,
    SCOPE_ACCOUNT,
    ProtectionLockFactV1,
    resolve_account_protection_state_for_action_v1,
)
from src.decision_gate.decision_gate_v1 import evaluate_selection_for_account
from src.decision_gate.models import DecisionGateConfig, DuplicateState, SelectionInputRow, SleeveState


NOW = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)


def _row() -> SelectionInputRow:
    return SelectionInputRow(
        selection_state_id=1, asset_id=42, symbol="BTC", venue="bitvavo", asof_ts_utc="2026-08-15T12:00:00Z",
        selection_state="BUY_READY", selection_bias=None, priority_rank=1, effective_selection_score=Decimal("1"),
        allowed_sleeves="CORE", summary_text=None, regime_label_4h=None,
        setup_filter_state="PASS", setup_filter_reason="OK", target_horizon="4h",
    )


def _sleeve() -> SleeveState:
    return SleeveState(7, "CORE", "ACTIVE", Decimal("1"), Decimal("100"), Decimal("0"), Decimal("0"), Decimal("100"))


def _protection(*, locked: bool):
    facts = ()
    if locked:
        facts = (ProtectionLockFactV1(
            lifecycle_id="drawdown", event_id="drawdown-active", protection_code=PROTECTION_MAX_ACCOUNT_DRAWDOWN_BLOCK,
            protection_version=LOCK_FACT_CONTRACT_VERSION, trading_account_id=7, scope_type=SCOPE_ACCOUNT, scope_id="7",
            observed_from_ts_utc=NOW - timedelta(minutes=1), observed_to_ts_utc=NOW, triggered_ts_utc=NOW,
            expires_ts_utc=None, reason_code="TEST", evidence_refs=("canonical:drawdown:1",), configuration_version="policy-1",
        ),)
    return resolve_account_protection_state_for_action_v1(
        facts, trading_account_id=7, sleeve_code="CORE", asset_id=42, requested_action=ACTION_BUY,
        account_state_observed_ts_utc=NOW, account_state_fresh=True, at=NOW,
    )


def _evaluate(*, duplicate=False, locked=False):
    return evaluate_selection_for_account(
        _row(), 7, "CORE", _sleeve(), DuplicateState(duplicate, False), DecisionGateConfig(),
        protection_evaluation=_protection(locked=locked),
        protection_evaluation_ts_utc=NOW,
    )


def test_protection_can_only_remove_existing_buy_permission():
    assert _evaluate(locked=False).decision_state == "EXECUTION_ALLOWED"
    blocked = _evaluate(locked=True)
    assert (blocked.decision_state, blocked.execution_intent) == ("BLOCKED_PROTECTION", "NONE")
    assert blocked.protection_code == PROTECTION_MAX_ACCOUNT_DRAWDOWN_BLOCK


def test_existing_denial_cannot_be_overridden_by_permitted_protection():
    denied = _evaluate(duplicate=True, locked=False)
    assert denied.decision_state == "BLOCKED_ACTIVE_PLAN"
    assert denied.execution_intent == "NONE"


def test_mismatched_action_evaluation_fails_closed_for_otherwise_allowed_buy():
    result = evaluate_selection_for_account(
        _row(), 7, "CORE", _sleeve(), DuplicateState(False, False), DecisionGateConfig(),
        protection_evaluation=resolve_account_protection_state_for_action_v1(
            (), trading_account_id=7, sleeve_code="CORE", asset_id=42, requested_action="EXIT",
            account_state_observed_ts_utc=NOW, account_state_fresh=True, at=NOW,
        ),
        protection_evaluation_ts_utc=NOW,
    )
    assert (result.decision_state, result.execution_intent) == ("BLOCKED_PROTECTION", "NONE")


def test_mismatched_evaluation_timestamp_fails_closed_for_otherwise_allowed_buy():
    result = evaluate_selection_for_account(
        _row(), 7, "CORE", _sleeve(), DuplicateState(False, False), DecisionGateConfig(),
        protection_evaluation=_protection(locked=False),
        protection_evaluation_ts_utc=NOW + timedelta(seconds=1),
    )
    assert (result.decision_state, result.decision_reason) == ("BLOCKED_PROTECTION", "INVALID_PROTECTION_EVALUATION_BINDING")
