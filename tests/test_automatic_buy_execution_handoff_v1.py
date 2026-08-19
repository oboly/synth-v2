from __future__ import annotations

import ast
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from src.entry_policy.automatic_buy_acceptance_dry_run_v1 import AutomaticBuyHandoffPreviewV1
from src.entry_policy.automatic_buy_execution_handoff_application_v1 import (
    AutomaticBuyExecutorHandoffError,
    resolve_automatic_buy_executor_mode_v1,
    submit_automatic_buy_preview_to_shared_handoff_v1,
)
from src.execution_planner.automatic_buy_execution_handoff_adapter_v1 import (
    adapt_automatic_buy_plan_to_approved_execution_plan_v1,
    derive_automatic_buy_plan_reference_id_v1,
)
from src.execution_planner.automatic_buy_planner_v1 import (
    AutomaticBuyGateApprovalProvenanceV1,
    AutomaticBuyPlanLegV1,
    AutomaticBuyPlanV1,
)
from src.executor.execution_handoff_v1 import ExecutionHandoffV1, RUNTIME_MODE_DRY_RUN, RUNTIME_MODE_PAPER
from src.executor.execution_plan_reference_v1 import ApprovedExecutionPlanV1


def _plan() -> AutomaticBuyPlanV1:
    now = datetime(2026, 8, 19, 17, 0, tzinfo=UTC)
    return AutomaticBuyPlanV1(
        trading_account_id=101,
        venue="bitvavo",
        asset_id=42,
        market="BTC-EUR",
        side="BUY",
        final_quantity_base=Decimal("0.10"),
        legs=(
            AutomaticBuyPlanLegV1(1, "BUY", Decimal("100"), Decimal("0.05"), Decimal("5"), True, "GTC"),
            AutomaticBuyPlanLegV1(2, "BUY", Decimal("99.75"), Decimal("0.05"), Decimal("4.9875"), True, "GTC"),
        ),
        candidate_action="ENTER",
        candidate_reason_code="ENTRY_ZONE_REACHED",
        candidate_evidence_id="ev-1",
        strategy_id="strategy-a",
        strategy_version="1",
        setup_id="setup-1",
        gate_approval=AutomaticBuyGateApprovalProvenanceV1("APPROVED", "OK", Decimal("10")),
        planner_version="automatic_buy_planner_v1",
        planning_ts_utc=now,
    )


def _preview(plan: AutomaticBuyPlanV1) -> AutomaticBuyHandoffPreviewV1:
    return AutomaticBuyHandoffPreviewV1(
        mode="PAPER_DRY_RUN",
        trading_account_id=plan.trading_account_id,
        venue=plan.venue,
        asset_id=plan.asset_id,
        market=plan.market,
        idempotency_key="a" * 64,
        plan=plan,
        plan_hash="b" * 64,
    )


class FakeHandoffRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[ApprovedExecutionPlanV1, str, str, str]] = []
        self.by_reference: dict[tuple[str, str], ExecutionHandoffV1] = {}

    def intake(self, *, plan: ApprovedExecutionPlanV1, executor_mode: str, executor_identity: str, runtime_owner: str) -> ExecutionHandoffV1:
        self.calls.append((plan, executor_mode, executor_identity, runtime_owner))
        key = (plan.plan_source, plan.plan_reference_id)
        if key not in self.by_reference:
            self.by_reference[key] = ExecutionHandoffV1(
                handoff_id=1,
                plan_source=plan.plan_source,
                plan_reference_id=plan.plan_reference_id,
                plan_content_hash=plan.content_hash,
                trading_account_id=plan.trading_account_id,
                venue=plan.venue,
                market=plan.market,
                side=plan.side,
                executor_mode=executor_mode,
                executor_identity=executor_identity,
                runtime_owner=runtime_owner,
                executor_credential_binding_id=7,
            )
        return self.by_reference[key]


def test_buy_plan_adapts_losslessly_to_shared_side_neutral_contract() -> None:
    plan = _plan()
    approved = adapt_automatic_buy_plan_to_approved_execution_plan_v1(plan)
    assert isinstance(approved, ApprovedExecutionPlanV1)
    assert approved.side == "BUY"
    assert approved.trading_account_id == plan.trading_account_id
    assert [(leg.leg_index, leg.side, leg.price, leg.quantity) for leg in approved.legs] == [
        (leg.leg_index, leg.side, leg.limit_price, leg.quantity_base) for leg in plan.legs
    ]


def test_plan_reference_is_retry_stable_but_provenance_sensitive() -> None:
    plan = _plan()
    assert derive_automatic_buy_plan_reference_id_v1(plan) == derive_automatic_buy_plan_reference_id_v1(plan)
    changed = AutomaticBuyPlanV1(**{**plan.__dict__, "candidate_action": "RE_ENTER"})
    assert derive_automatic_buy_plan_reference_id_v1(plan) != derive_automatic_buy_plan_reference_id_v1(changed)


def test_duplicate_handoff_reuses_same_shared_plan_identity() -> None:
    plan = _plan()
    repo = FakeHandoffRepository()
    first = submit_automatic_buy_preview_to_shared_handoff_v1(
        preview=_preview(plan), account_mode="paper", executor_identity="shared-executor-v1", runtime_owner="automatic-buy",
        handoff_repository=repo,
    )
    second = submit_automatic_buy_preview_to_shared_handoff_v1(
        preview=_preview(plan), account_mode="paper", executor_identity="shared-executor-v1", runtime_owner="automatic-buy",
        handoff_repository=repo,
    )
    assert first.plan_reference_id == second.plan_reference_id
    assert first.plan_content_hash == second.plan_content_hash
    assert len(repo.by_reference) == 1


def test_phase6_is_paper_by_default_and_only_dry_run_override_is_allowed() -> None:
    assert resolve_automatic_buy_executor_mode_v1(account_mode="paper") == RUNTIME_MODE_PAPER
    assert resolve_automatic_buy_executor_mode_v1(account_mode="paper", executor_mode_override="DRY_RUN") == RUNTIME_MODE_DRY_RUN
    with pytest.raises(AutomaticBuyExecutorHandoffError):
        resolve_automatic_buy_executor_mode_v1(account_mode="paper", executor_mode_override="LIVE")
    with pytest.raises(AutomaticBuyExecutorHandoffError):
        resolve_automatic_buy_executor_mode_v1(account_mode="live")


def test_preview_identity_mismatch_fails_closed_before_shared_intake() -> None:
    plan = _plan()
    preview = _preview(plan)
    bad = AutomaticBuyHandoffPreviewV1(**{**preview.__dict__, "market": "ETH-EUR"})
    repo = FakeHandoffRepository()
    with pytest.raises(AutomaticBuyExecutorHandoffError, match="IDENTITY_MISMATCH"):
        submit_automatic_buy_preview_to_shared_handoff_v1(
            preview=bad, account_mode="paper", executor_identity="shared-executor-v1", runtime_owner="automatic-buy",
            handoff_repository=repo,
        )
    assert repo.calls == []


def test_phase6_introduces_no_buy_specific_executor_or_broker_stack() -> None:
    paths = (
        Path("src/execution_planner/automatic_buy_execution_handoff_adapter_v1.py"),
        Path("src/entry_policy/automatic_buy_execution_handoff_application_v1.py"),
    )
    for path in paths:
        tree = ast.parse(path.read_text())
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
        assert not any(name.startswith("src.broker") for name in imports)
        assert "src.executor.execution_handoff_v1" in imports or "src.executor.execution_plan_reference_v1" in imports
