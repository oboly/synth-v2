from __future__ import annotations

import ast
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.entry_policy.automatic_buy_acceptance_dry_run_v1 as acceptance
from src.entry_policy.automatic_buy_runtime_orchestrator_v1 import (
    PLANNER_STATE_NOT_REACHED,
    PLANNER_STATE_STAGED,
    AutomaticBuyRuntimeItemOutcomeV1,
)
from src.execution_planner.automatic_buy_planner_v1 import (
    AutomaticBuyGateApprovalProvenanceV1,
    AutomaticBuyPlanLegV1,
    AutomaticBuyPlanV1,
)


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
            AutomaticBuyPlanLegV1(
                leg_index=1,
                side="BUY",
                limit_price=Decimal("100"),
                quantity_base=Decimal("0.05"),
                quote_notional=Decimal("5.00"),
                post_only=True,
                time_in_force="GTC",
            ),
            AutomaticBuyPlanLegV1(
                leg_index=2,
                side="BUY",
                limit_price=Decimal("99.75"),
                quantity_base=Decimal("0.05"),
                quote_notional=Decimal("4.9875"),
                post_only=True,
                time_in_force="GTC",
            ),
        ),
        candidate_action="ENTER",
        candidate_reason_code="ENTRY_ZONE_REACHED",
        candidate_evidence_id="ev-1",
        strategy_id="strategy-a",
        strategy_version="1",
        setup_id="setup-1",
        gate_approval=AutomaticBuyGateApprovalProvenanceV1(
            state="APPROVED",
            reason_code="OK",
            approved_notional_ceiling_eur=Decimal("10"),
        ),
        planner_version="automatic_buy_planner_v1",
        planning_ts_utc=now,
    )


def _item(account_mode: str = "paper") -> SimpleNamespace:
    return SimpleNamespace(
        runtime_input=SimpleNamespace(
            trading_account_id=101,
            venue="bitvavo",
            asset_id=42,
            market="BTC-EUR",
            account_mode=account_mode,
        )
    )


def test_staged_preview_uses_exact_typed_plan_without_reconstruction() -> None:
    plan = _plan()
    outcome = AutomaticBuyRuntimeItemOutcomeV1(
        idempotency_key="a" * 64,
        candidate_state="CANDIDATE",
        gate_state="APPROVED",
        planner_state=PLANNER_STATE_STAGED,
        audit_outcome="inserted",
        plan=plan,
    )
    persisted = acceptance.canonical_json(acceptance.build_immutable_buy_plan_json(plan))
    preview = acceptance._preview_from_outcome(
        item=_item(), outcome=outcome, persisted_plan_json=persisted,
    )
    assert preview is not None
    assert preview.mode == "PAPER_DRY_RUN"
    assert preview.plan is plan
    assert preview.idempotency_key == outcome.idempotency_key


def test_non_staged_outcome_produces_no_handoff_preview() -> None:
    outcome = AutomaticBuyRuntimeItemOutcomeV1(
        idempotency_key="b" * 64,
        candidate_state="NO_ACTION",
        gate_state=None,
        planner_state=PLANNER_STATE_NOT_REACHED,
        audit_outcome="inserted",
        plan=None,
    )
    assert acceptance._preview_from_outcome(
        item=_item(), outcome=outcome, persisted_plan_json=None,
    ) is None


def test_phase5_cannot_escalate_non_paper_account_to_preview() -> None:
    plan = _plan()
    outcome = AutomaticBuyRuntimeItemOutcomeV1(
        idempotency_key="c" * 64,
        candidate_state="CANDIDATE",
        gate_state="APPROVED",
        planner_state=PLANNER_STATE_STAGED,
        audit_outcome="inserted",
        plan=plan,
    )
    persisted = acceptance.canonical_json(acceptance.build_immutable_buy_plan_json(plan))
    with pytest.raises(acceptance.AutomaticBuyAcceptanceDryRunError, match="NON_PAPER"):
        acceptance._preview_from_outcome(
            item=_item("live"), outcome=outcome, persisted_plan_json=persisted,
        )


def test_persisted_plan_must_match_exact_typed_plan() -> None:
    plan = _plan()
    outcome = AutomaticBuyRuntimeItemOutcomeV1(
        idempotency_key="d" * 64,
        candidate_state="CANDIDATE",
        gate_state="APPROVED",
        planner_state=PLANNER_STATE_STAGED,
        audit_outcome="inserted",
        plan=plan,
    )
    with pytest.raises(acceptance.AutomaticBuyAcceptanceDryRunError, match="AUDIT_MISMATCH"):
        acceptance._preview_from_outcome(
            item=_item(), outcome=outcome, persisted_plan_json='{"different":true}',
        )


def test_duplicate_replay_reuses_same_idempotent_preview(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _plan()
    outcome = AutomaticBuyRuntimeItemOutcomeV1(
        idempotency_key="e" * 64,
        candidate_state="CANDIDATE",
        gate_state="APPROVED",
        planner_state=PLANNER_STATE_STAGED,
        audit_outcome="idempotent_existing",
        plan=plan,
    )
    source = {"source_snapshot_key": "f" * 64}
    source_json = acceptance.canonical_json(source)
    plan_json = acceptance.canonical_json(acceptance.build_immutable_buy_plan_json(plan))

    monkeypatch.setattr(acceptance, "evaluate_automatic_buy_runtime_item_v1", lambda conn, item: outcome)
    monkeypatch.setattr(acceptance, "build_automatic_buy_source_evidence_v1", lambda item: source)

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params):
            assert params == (outcome.idempotency_key,)

        def fetchone(self):
            return {
                "source_evidence_json": source_json,
                "immutable_plan_json": plan_json,
                "planner_state": PLANNER_STATE_STAGED,
            }

    class Conn:
        def cursor(self):
            return Cursor()

    first = acceptance.run_automatic_buy_acceptance_dry_run_v1(Conn(), item=_item())
    second = acceptance.run_automatic_buy_acceptance_dry_run_v1(Conn(), item=_item())
    assert first.idempotency_key == second.idempotency_key == outcome.idempotency_key
    assert first.audit_outcome == second.audit_outcome == "idempotent_existing"
    assert first.handoff_preview is not None and second.handoff_preview is not None
    assert first.handoff_preview.plan is plan
    assert second.handoff_preview.plan is plan


def test_phase5_has_no_executor_broker_or_manual_execution_imports() -> None:
    path = Path("src/entry_policy/automatic_buy_acceptance_dry_run_v1.py")
    tree = ast.parse(path.read_text())
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    forbidden = ("src.executor", "src.broker", "src.manual_execution")
    assert all(not imported.startswith(forbidden) for imported in imports)
    assert "live_authority=0" in acceptance.SAFETY_MARKERS
