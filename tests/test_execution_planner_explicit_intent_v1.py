from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from decimal import Decimal

from src.decision_gate.models import DecisionResult
from src.execution_planner.execution_planner_v1 import build_execution_plan
from src.execution_planner.models import ExecutionPlannerConfig


def _decision(**overrides: object) -> DecisionResult:
    base = DecisionResult(
        account_id=7,
        sleeve_code="CORE",
        selection_state_id=10,
        asset_id=42,
        symbol="BTC",
        venue="bitvavo",
        asof_ts_utc="2026-07-21T12:00:00Z",
        selection_state="SELECTED",
        decision_state="EXECUTION_ALLOWED",
        decision_reason="OK",
        execution_intent="PLACE_PASSIVE_LIMIT",
        min_available_equity_eur=Decimal("25.00"),
        available_equity_eur=Decimal("100.00"),
        has_active_plan=False,
        has_open_position=False,
        allowed_sleeves="CORE",
        setup_filter_state="PASS",
        setup_filter_reason="OK",
        target_horizon="short",
        summary_text=None,
        regime_label_4h="TREND_UP",
    )
    return replace(base, **overrides)


def test_execution_plan_stores_explicit_passive_limit_intent() -> None:
    plan = build_execution_plan(
        decision=_decision(),
        config=ExecutionPlannerConfig(
            execution_mode="LIVE",
            trading_account_id=17,
            decision_gate_permission_evidence_id=23,
        ),
        reference_price_eur=Decimal("100.00"),
    )

    assert plan is not None
    assert plan.execution_intent == "PLACE_PASSIVE_LIMIT"
    assert plan.desired_action == "SPREAD_CAPTURE_PASSIVE"
    assert plan.execution_mode == "LIVE"
    assert plan.trading_account_id == 17
    assert plan.decision_gate_permission_evidence_id == 23
    assert plan.action_type == "PLACE_ORDER"
    assert plan.requested_side == "BUY"
    assert plan.plan_state == "IDLE"
    assert isinstance(plan.valid_until_ts_utc, datetime)


def test_execution_plan_stores_explicit_prepare_intent() -> None:
    plan = build_execution_plan(
        decision=_decision(
            decision_state="PREPARE_ALLOWED",
            execution_intent="PREPARE_PLAN",
        ),
        config=ExecutionPlannerConfig(execution_mode="PAPER"),
        reference_price_eur=Decimal("100.00"),
    )

    assert plan is not None
    assert plan.execution_intent == "PREPARE_PLAN"
    assert plan.desired_action == "PREPARE_PLAN"


def test_live_plan_requires_explicit_trading_account_and_permission_binding() -> None:
    for config, message in [
        (ExecutionPlannerConfig(execution_mode="LIVE"), "trading_account_id"),
        (
            ExecutionPlannerConfig(execution_mode="LIVE", trading_account_id=17),
            "decision_gate_permission_evidence_id",
        ),
    ]:
        try:
            build_execution_plan(_decision(), config, Decimal("100"))
        except ValueError as exc:
            assert message in str(exc)
        else:
            raise AssertionError("LIVE plan without exact binding must fail")


def test_legacy_lowercase_execution_mode_is_not_silently_normalized() -> None:
    try:
        build_execution_plan(
            _decision(),
            ExecutionPlannerConfig(execution_mode="live", trading_account_id=17),
            Decimal("100"),
        )
    except ValueError as exc:
        assert str(exc) == "execution_mode must be canonical PAPER or LIVE"
    else:
        raise AssertionError("lowercase mode must fail closed")


def test_live_prepare_plan_is_rejected() -> None:
    try:
        build_execution_plan(
            _decision(decision_state="PREPARE_ALLOWED", execution_intent="PREPARE_PLAN"),
            ExecutionPlannerConfig(
                execution_mode="LIVE",
                trading_account_id=17,
                decision_gate_permission_evidence_id=23,
            ),
            Decimal("100"),
        )
    except ValueError as exc:
        assert str(exc) == "LIVE planning only supports PLACE_PASSIVE_LIMIT"
    else:
        raise AssertionError("LIVE preplan must fail closed")
