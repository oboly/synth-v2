from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from decimal import Decimal

import pytest

from src.decision_gate.models import DecisionResult
from src.execution_planner.contract_preview_v1 import (
    UnauthorizedManualExecutionCallError,
)
from src.execution_planner.execution_planner_v1 import build_execution_plan
from src.execution_planner.models import ExecutionPlannerConfig
from src.execution_planner.repository import ExecutionPlannerRepository


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


def _config(**overrides: object) -> ExecutionPlannerConfig:
    values: dict[str, object] = {
        "execution_mode": "PAPER",
        "trading_account_id": 17,
        "action_type": "PLACE_ORDER",
        "requested_side": "BUY",
    }
    values.update(overrides)
    return ExecutionPlannerConfig(**values)


@pytest.mark.parametrize("mode", ["PAPER", "LIVE"])
def test_plan_persists_exact_explicit_buy_contract(mode: str) -> None:
    plan = build_execution_plan(
        _decision(),
        _config(execution_mode=mode, requested_side="BUY"),
        Decimal("100"),
    )

    assert plan is not None
    assert plan.trading_account_id == 17
    assert plan.execution_mode == mode
    assert plan.execution_intent == "PLACE_PASSIVE_LIMIT"
    assert plan.action_type == "PLACE_ORDER"
    assert plan.requested_side == "BUY"
    assert plan.side == "BUY"
    assert plan.market == "BTC-EUR"
    assert isinstance(plan.valid_until_ts_utc, datetime) is (mode == "LIVE")


@pytest.mark.parametrize("side", [None, "", "buy", "sell", "Buy", "SELL ", "HOLD"])
def test_requested_side_must_be_exact(side: str | None) -> None:
    with pytest.raises(ValueError, match="^REQUESTED_SIDE_NOT_CANONICAL$"):
        build_execution_plan(_decision(), _config(requested_side=side), Decimal("100"))


@pytest.mark.parametrize("mode", [None, "", "paper", "live", "Paper", "TEST"])
def test_execution_mode_must_be_exact(mode: str | None) -> None:
    with pytest.raises(ValueError, match="^EXECUTION_MODE_NOT_CANONICAL$"):
        build_execution_plan(_decision(), _config(execution_mode=mode), Decimal("100"))


@pytest.mark.parametrize("action", [None, "", "place_order", "PLACE", "PLACE_ORDER "])
def test_action_type_must_be_exact(action: str | None) -> None:
    with pytest.raises(ValueError, match="^ACTION_TYPE_NOT_CANONICAL$"):
        build_execution_plan(_decision(), _config(action_type=action), Decimal("100"))


@pytest.mark.parametrize("intent", [None, "", " ", "PLACE_PASSIVE_LIMIT "])
def test_intent_must_be_nonblank_and_canonical(intent: str | None) -> None:
    expected = "EXECUTION_INTENT_REQUIRED" if intent is None or not intent.strip() else "EXECUTION_INTENT_NOT_CANONICAL"
    with pytest.raises(ValueError, match=f"^{expected}$"):
        build_execution_plan(_decision(execution_intent=intent), _config(), Decimal("100"))


def test_account_id_cannot_substitute_for_trading_account_id() -> None:
    with pytest.raises(ValueError, match="^TRADING_ACCOUNT_ID_REQUIRED$"):
        build_execution_plan(_decision(account_id=17), _config(trading_account_id=None), Decimal("100"))


def test_repository_rejects_incomplete_canonical_plan() -> None:
    plan = build_execution_plan(_decision(), _config(), Decimal("100"))
    assert plan is not None
    with pytest.raises(ValueError, match="^TRADING_ACCOUNT_ID_REQUIRED$"):
        ExecutionPlannerRepository._validate_plan_contract(
            replace(plan, trading_account_id=None)
        )


def test_generic_sell_contract_is_rejected_before_planning() -> None:
    with pytest.raises(UnauthorizedManualExecutionCallError):
        build_execution_plan(
            _decision(),
            _config(execution_mode="LIVE", requested_side="SELL"),
            Decimal("100"),
        )


def test_live_prepare_plan_remains_unsupported() -> None:
    with pytest.raises(ValueError, match="^LIVE_PLAN_INTENT_NOT_SUPPORTED$"):
        build_execution_plan(
            _decision(decision_state="PREPARE_ALLOWED", execution_intent="PREPARE_PLAN"),
            _config(execution_mode="LIVE"),
            Decimal("100"),
        )
