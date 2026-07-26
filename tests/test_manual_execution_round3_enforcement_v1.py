from __future__ import annotations

from argparse import Namespace
from decimal import Decimal

import pytest

from src.decision_gate import run_sell_only_decision_gate_preview_v1 as legacy_gate
from src.execution import limit_sell_ladder_v1 as legacy_orders
from src.execution_ladder import resolver as legacy_ladder
from src.execution_ladder.models import LadderProfile
from src.execution_planner import contract_preview_v1 as planner
from src.execution_planner import run_execution_planner_contract_preview_v1 as contract_cli
from src.execution_planner import run_sell_only_execution_plan_preview_v1 as legacy_plan
from src.executor import run_sell_only_paper_executor_preview_v1 as legacy_executor

def _sell_intent(intent_type: str) -> planner.ExecutionIntentPreview:
    return planner.ExecutionIntentPreview(
        account_id=1,
        sleeve_code="CORE_STRUCTURAL",
        asset_id=42,
        symbol="BTC",
        venue="bitvavo",
        side="SELL",
        intent_type=intent_type,
        max_notional_eur=None,
        quantity_base=Decimal("1"),
        decision_state="EXECUTION_ALLOWED",
        decision_reason="CALLER",
        ladder_levels=((Decimal("50000"), Decimal("1")),),
    )


def _context() -> planner.ExecutionMarketContextPreview:
    return planner.ExecutionMarketContextPreview(
        Decimal("50000"),
        Decimal("49990"),
        Decimal("50010"),
        Decimal("1"),
        None,
        None,
        None,
    )


@pytest.mark.parametrize(
    "intent_type",
    ["EXIT_PASSIVE_LIMIT", "EXIT_LADDER", "PLACE_PASSIVE_LIMIT"],
)
def test_generic_planner_sell_spellings_are_hard_blocked(intent_type) -> None:
    with pytest.raises(planner.UnauthorizedManualExecutionCallError):
        planner.build_execution_plan_preview(
            intent=_sell_intent(intent_type),
            context=_context(),
        )


def test_private_full_plan_builder_is_structurally_buy_only() -> None:
    with pytest.raises(planner.UnauthorizedManualExecutionCallError):
        planner._build_buy_execution_plan_preview(
            intent=_sell_intent("PLACE_PASSIVE_LIMIT"),
            context=_context(),
        )


def test_generic_contract_cli_blocks_sell_before_plan_construction(monkeypatch) -> None:
    monkeypatch.setattr(
        contract_cli,
        "parse_args",
        lambda: Namespace(side="SELL", intent_type="PLACE_PASSIVE_LIMIT"),
    )
    assert contract_cli.main() == 2


@pytest.mark.parametrize(
    "runner",
    [legacy_gate.run, legacy_plan.run, legacy_executor.run],
)
def test_legacy_sell_chain_runners_are_hard_blocked(runner) -> None:
    assert runner(Namespace()) == 2


def test_legacy_sell_chain_mutation_helpers_are_hard_blocked() -> None:
    with pytest.raises(PermissionError):
        legacy_gate.insert_intent(
            None,
            position=None,
            intent_state="APPROVED",
            reason_code="CALLER",
            requested_quantity_base=Decimal("1"),
            live_trading_enabled=0,
            decision_gate_enabled=1,
            execution_enabled=0,
        )
    with pytest.raises(PermissionError):
        legacy_plan.insert_plan(None, None)
    with pytest.raises(PermissionError):
        legacy_executor.update_plan_state(
            None,
            plan=None,
            to_state="SUBMITTED",
            note="CALLER",
        )


def test_direct_sell_ladder_resolver_is_hard_blocked() -> None:
    profile = LadderProfile(
        1, 1, "SELL", "Sell", "legacy", "SELL",
        "NATIVE_SHORT_ANCHOR_HIGH", 1, True, 1,
    )
    with pytest.raises(PermissionError):
        legacy_ladder.resolve_ladder_preview(
            profile,
            [],
            Decimal("1"),
            Decimal("1"),
        )


def test_direct_limit_sell_order_builder_and_placer_are_hard_blocked() -> None:
    with pytest.raises(PermissionError):
        legacy_orders.build_limit_sell_ladder_orders(
            market="BTC-EUR",
            available_qty=Decimal("1"),
            levels=[],
        )
    with pytest.raises(PermissionError):
        legacy_orders.place_limit_sell_ladder_orders(
            client=object(),  # type: ignore[arg-type]
            orders=[],
            confirm_real_orders=True,
        )
