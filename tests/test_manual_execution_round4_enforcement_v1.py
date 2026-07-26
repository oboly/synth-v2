from __future__ import annotations

import inspect
from argparse import Namespace
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.decision_gate import run_sell_only_decision_gate_preview_v1 as legacy_gate
from src.decision_gate.free_base_quantity_v1 import resolve_free_base_quantity
from src.decision_gate.manual_execution_approval_v1 import (
    resolve_persisted_manual_execution_authority,
)
from src.decision_gate.manual_execution_gate_v1 import (
    ManualExecutionGateInput,
    ManualExecutionGateRepository,
)
from src.execution import limit_sell_ladder_v1 as legacy_orders
from src.execution_ladder import resolver as legacy_ladder
from src.execution_ladder.models import LadderPreview
from src.execution_planner import execution_planner_v1 as generic_planner
from src.execution_planner import run_execution_planner_v1 as planner_cli
from src.execution_planner.contract_preview_v1 import (
    UnauthorizedManualExecutionCallError,
    build_manual_sell_execution_plan_preview,
)
from src.execution_planner.models import ExecutionPlannerConfig
from src.execution_planner.repository import ExecutionPlannerRepository
from src.executor.executor_v1 import execute_plan_paper
from src.executor.paper_contract_v1 import PaperExecutorContractError
from src.manual_execution.manual_execution_service_v1 import process
from src.orchestration import run_paper_cycle_v1 as paper_cycle
from src.policy.exit_policy_v1 import ExitPolicyConfig, run_exit_policy_v1
from tests.manual_sell_entrypoint_discovery_v1 import (
    discover_sell_entrypoints,
    unclassified_sell_entrypoints,
)
from tests.test_execution_planner_explicit_intent_v1 import _config, _decision


ROUTED_CANONICALLY = "ROUTED_CANONICALLY"
HARD_BLOCKED = "HARD_BLOCKED"

SELL_ENTRYPOINT_CLASSIFICATIONS = {
    "scripts.run_live_paper_trader.main": HARD_BLOCKED,
    "scripts.trade_place_limit_sell_order_ladders_from_csv.<module>": HARD_BLOCKED,
    "src.decision_gate.manual_execution_gate_v1.evaluate_manual_execution_request":
        ROUTED_CANONICALLY,
    "src.decision_gate.run_sell_only_decision_gate_preview_v1.insert_event": HARD_BLOCKED,
    "src.decision_gate.run_sell_only_decision_gate_preview_v1.insert_intent": HARD_BLOCKED,
    "src.decision_gate.run_sell_only_decision_gate_preview_v1.run": HARD_BLOCKED,
    "src.execution.limit_sell_ladder_v1.build_limit_sell_ladder_orders": HARD_BLOCKED,
    "src.execution.limit_sell_ladder_v1.place_limit_sell_ladder_orders": HARD_BLOCKED,
    "src.execution.limit_sell_ladder_v1.preview_limit_sell_ladder_orders": HARD_BLOCKED,
    "src.execution.run_paper_execution_runner_v1.run": HARD_BLOCKED,
    "src.execution.worker._validate_paper_plan": HARD_BLOCKED,
    "src.execution.worker.process_execution_plans": HARD_BLOCKED,
    "src.execution_ladder.resolver.resolve_ladder_preview": HARD_BLOCKED,
    "src.execution_ladder.resolver.round_ladder_preview": HARD_BLOCKED,
    "src.execution_ladder.run_ladder_profile_preview_v1.main": HARD_BLOCKED,
    "src.execution_planner.canonical_rounding_v1.round_price_for_side":
        ROUTED_CANONICALLY,
    "src.execution_planner.contract_preview_v1._build_buy_execution_plan_preview":
        HARD_BLOCKED,
    "src.execution_planner.contract_preview_v1._build_ladder_legs":
        ROUTED_CANONICALLY,
    "src.execution_planner.contract_preview_v1._build_single_leg":
        ROUTED_CANONICALLY,
    "src.execution_planner.contract_preview_v1.build_execution_plan_preview":
        HARD_BLOCKED,
    "src.execution_planner.contract_preview_v1.build_manual_sell_execution_plan_preview":
        ROUTED_CANONICALLY,
    "src.execution_planner.execution_planner_v1.build_execution_plan": HARD_BLOCKED,
    "src.execution_planner.execution_planner_v1.build_exit_plan_from_position":
        HARD_BLOCKED,
    "src.execution_planner.repository.ExecutionPlannerRepository._insert_execution_plan":
        HARD_BLOCKED,
    "src.execution_planner.repository.ExecutionPlannerRepository.create_exit_plan_without_reservation":
        HARD_BLOCKED,
    "src.execution_planner.repository.ExecutionPlannerRepository.create_plan_with_reservation":
        HARD_BLOCKED,
    "src.execution_planner.repository.ExecutionPlannerRepository.create_plan_without_reservation":
        HARD_BLOCKED,
    "src.execution_planner.repository.ExecutionPlannerRepository.update_plan":
        HARD_BLOCKED,
    "src.execution_planner.run_execution_planner_contract_preview_v1.main": HARD_BLOCKED,
    "src.execution_planner.run_execution_planner_contract_preview_v1.parse_args":
        HARD_BLOCKED,
    "src.execution_planner.run_execution_planner_v1.main": HARD_BLOCKED,
    "src.execution_planner.run_sell_only_execution_plan_preview_v1.insert_event":
        HARD_BLOCKED,
    "src.execution_planner.run_sell_only_execution_plan_preview_v1.insert_plan":
        HARD_BLOCKED,
    "src.execution_planner.run_sell_only_execution_plan_preview_v1.run": HARD_BLOCKED,
    "src.executor.executor_v1.execute_plan_paper": HARD_BLOCKED,
    "src.executor.run_executor_v1.main": HARD_BLOCKED,
    "src.executor.run_sell_only_paper_executor_preview_v1.insert_event": HARD_BLOCKED,
    "src.executor.run_sell_only_paper_executor_preview_v1.run": HARD_BLOCKED,
    "src.executor.run_sell_only_paper_executor_preview_v1.update_plan_state":
        HARD_BLOCKED,
    "src.manual_execution.manual_execution_service_v1.process": ROUTED_CANONICALLY,
    "src.orchestration.run_live_paper_cycle_v1.run_single_cycle": HARD_BLOCKED,
    "src.orchestration.run_live_paper_loop_v1.run_single_cycle": HARD_BLOCKED,
    "src.orchestration.run_paper_cycle_v1.main": HARD_BLOCKED,
    "src.policy.exit_policy_v1.run_exit_policy_v1": HARD_BLOCKED,
}


def test_discovery_proves_classification_completeness() -> None:
    discovered = discover_sell_entrypoints(Path.cwd())
    assert discovered == set(SELL_ENTRYPOINT_CLASSIFICATIONS)
    assert unclassified_sell_entrypoints(
        discovered,
        SELL_ENTRYPOINT_CLASSIFICATIONS,
    ) == set()
    assert set(SELL_ENTRYPOINT_CLASSIFICATIONS.values()) == {
        ROUTED_CANONICALLY,
        HARD_BLOCKED,
    }


def test_new_unclassified_sell_alias_fails_discovery(
    tmp_path: Path,
) -> None:
    module_dir = tmp_path / "src" / "execution_planner"
    module_dir.mkdir(parents=True)
    path = module_dir / "new_alias.py"
    path.write_text(
        "def build_new_sell_alias(side):\n"
        "    if side == 'SELL':\n"
        "        return 'EXIT_LADDER'\n",
        encoding="utf-8",
    )
    discovered = discover_sell_entrypoints(tmp_path, roots=("src",))
    assert unclassified_sell_entrypoints(discovered, {}) == {
        "src.execution_planner.new_alias.build_new_sell_alias"
    }


def test_generic_sell_planner_and_exit_planner_are_hard_blocked() -> None:
    with pytest.raises(UnauthorizedManualExecutionCallError):
        generic_planner.build_execution_plan(
            _decision(),
            _config(requested_side="SELL"),
            Decimal("100"),
        )
    with pytest.raises(UnauthorizedManualExecutionCallError):
        generic_planner.build_exit_plan_from_position(
            SimpleNamespace(),
            _config(requested_side="SELL"),
            Decimal("100"),
        )


def test_generic_sell_planner_clis_block_before_repository_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        planner_cli,
        "parse_args",
        lambda: Namespace(requested_side="SELL"),
    )
    monkeypatch.setattr(
        planner_cli,
        "ExecutionPlannerRepository",
        lambda: (_ for _ in ()).throw(AssertionError("repository reached")),
    )
    assert planner_cli.main() == 2

    monkeypatch.setattr(
        paper_cycle,
        "parse_args",
        lambda: Namespace(requested_side="SELL"),
    )
    monkeypatch.setattr(
        paper_cycle,
        "DecisionGateRepository",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("repository reached")
        ),
    )
    assert paper_cycle.main() == 2


def _buy_plan():
    plan = generic_planner.build_execution_plan(
        _decision(),
        _config(requested_side="BUY"),
        Decimal("100"),
    )
    assert plan is not None
    return plan


def test_every_generic_sell_persistence_surface_fails_before_connection() -> None:
    def forbidden_connection(*args, **kwargs):
        raise AssertionError("connection reached")

    repository = ExecutionPlannerRepository(connection_factory=forbidden_connection)
    sell_plan = replace(_buy_plan(), side="SELL", requested_side="SELL")

    with pytest.raises(UnauthorizedManualExecutionCallError):
        repository.create_plan_without_reservation(sell_plan)
    with pytest.raises(UnauthorizedManualExecutionCallError):
        repository.create_plan_with_reservation(sell_plan)
    with pytest.raises(UnauthorizedManualExecutionCallError):
        repository.create_exit_plan_without_reservation(sell_plan)
    with pytest.raises(UnauthorizedManualExecutionCallError):
        repository.update_plan(execution_plan_id=1, plan=sell_plan)

    cursor = SimpleNamespace(execute=lambda *_args, **_kwargs: None, lastrowid=1)
    with pytest.raises(UnauthorizedManualExecutionCallError):
        repository._insert_execution_plan(cursor, sell_plan)


def test_exit_policy_fails_before_connection() -> None:
    with pytest.raises(UnauthorizedManualExecutionCallError):
        run_exit_policy_v1(
            account_id=1,
            trading_account_id=1,
            sleeve_code="CORE",
            venue="bitvavo",
            config=ExitPolicyConfig(Decimal("0.1"), Decimal("0.1")),
            connection_factory=lambda: (_ for _ in ()).throw(
                AssertionError("connection reached")
            ),
        )


def test_round3_non_authoritative_sell_helpers_are_now_hard_blocked() -> None:
    with pytest.raises(PermissionError):
        legacy_gate.decide_position(
            None,  # type: ignore[arg-type]
            request_fraction=Decimal("1"),
            approve_paper_preview=True,
        )
    preview = LadderPreview(
        profile_code="SELL",
        profile_version=1,
        side="SELL",
        anchor_type="TEST",
        anchor_price=Decimal("1"),
        quote_amount=Decimal("1"),
        legs=(),
        total_allocation_bps=0,
        estimated_total_base_quantity=Decimal("0"),
    )
    with pytest.raises(PermissionError):
        legacy_ladder.round_ladder_preview(
            preview,
            constraints=SimpleNamespace(),  # type: ignore[arg-type]
        )
    with pytest.raises(PermissionError):
        legacy_orders.preview_limit_sell_ladder_orders([])


def test_generic_paper_executor_rejects_sell_before_repository_access() -> None:
    plan = SimpleNamespace(
        execution_mode="PAPER",
        trading_account_id=1,
        venue="bitvavo",
        asset_symbol="BTC",
        market="BTC-EUR",
        action_type="PLACE_ORDER",
        requested_side="SELL",
        side="SELL",
        desired_action="SPREAD_CAPTURE_PASSIVE",
        execution_intent="PLACE_PASSIVE_LIMIT",
        plan_state="PLANNED",
    )
    repository = SimpleNamespace(
        fetch_latest_price_eur=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("repository reached")
        )
    )
    with pytest.raises(
        PaperExecutorContractError,
        match="PAPER_EXECUTOR_SELL_REQUIRES_MANUAL_AUTHORITY",
    ):
        execute_plan_paper(plan, repository)  # type: ignore[arg-type]


def test_no_public_authority_or_freshness_injection_parameters() -> None:
    forbidden = {
        "approval_repository",
        "request_repository",
        "gate_repository",
        "repository",
        "now",
        "current_time",
        "clock",
        "approval",
        "quantity_base",
        "decision_state",
    }
    production_apis = (
        process,
        build_manual_sell_execution_plan_preview,
        resolve_persisted_manual_execution_authority,
        resolve_free_base_quantity,
        ManualExecutionGateRepository.approve_and_reserve,
        ManualExecutionGateRepository.load_gate_input,
    )
    for production_api in production_apis:
        assert forbidden.isdisjoint(inspect.signature(production_api).parameters)
    assert "now" not in ManualExecutionGateInput.__dataclass_fields__


def test_round3_production_importable_forgery_helper_was_removed() -> None:
    source = Path("tests/test_manual_execution_service_v1.py").read_text(
        encoding="utf-8"
    )
    assert "def _canonical" not in source
