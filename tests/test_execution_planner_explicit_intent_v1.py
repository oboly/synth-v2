from __future__ import annotations

from dataclasses import replace
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
        config=ExecutionPlannerConfig(execution_mode="live"),
        reference_price_eur=Decimal("100.00"),
    )

    assert plan is not None
    assert plan.execution_intent == "PLACE_PASSIVE_LIMIT"
    assert plan.desired_action == "SPREAD_CAPTURE_PASSIVE"


def test_execution_plan_stores_explicit_prepare_intent() -> None:
    plan = build_execution_plan(
        decision=_decision(
            decision_state="PREPARE_ALLOWED",
            execution_intent="PREPARE_PLAN",
        ),
        config=ExecutionPlannerConfig(execution_mode="paper"),
        reference_price_eur=Decimal("100.00"),
    )

    assert plan is not None
    assert plan.execution_intent == "PREPARE_PLAN"
    assert plan.desired_action == "PREPARE_PLAN"
