from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

import src.entry_policy.automatic_buy_live_handoff_composition_v1 as composition
from src.entry_policy.automatic_buy_live_handoff_composition_v1 import (
    AutomaticBuyLiveHandoffCompositionError,
    evaluate_and_handoff_automatic_buy_runtime_item_v1,
)
from src.entry_policy.automatic_buy_runtime_orchestrator_v1 import (
    AutomaticBuyRuntimeItemOutcomeV1,
    PLANNER_STATE_NOT_REACHED,
    PLANNER_STATE_STAGED,
)
from src.execution_planner.automatic_buy_planner_v1 import (
    AutomaticBuyGateApprovalProvenanceV1,
    AutomaticBuyPlanLegV1,
    AutomaticBuyPlanV1,
)
from src.executor.execution_handoff_v1 import ExecutionHandoffV1


def _plan() -> AutomaticBuyPlanV1:
    return AutomaticBuyPlanV1(
        trading_account_id=101,
        venue="bitvavo",
        asset_id=42,
        market="BTC-EUR",
        side="BUY",
        final_quantity_base=Decimal("0.10"),
        legs=(
            AutomaticBuyPlanLegV1(
                1, "BUY", Decimal("100"), Decimal("0.05"), Decimal("5"), True, "GTC"
            ),
            AutomaticBuyPlanLegV1(
                2, "BUY", Decimal("99.75"), Decimal("0.05"), Decimal("4.9875"), True, "GTC"
            ),
        ),
        candidate_action="ENTER",
        candidate_reason_code="ENTRY_ZONE_REACHED",
        candidate_evidence_id="ev-1",
        strategy_id="strategy-a",
        strategy_version="1",
        setup_id="setup-1",
        gate_approval=AutomaticBuyGateApprovalProvenanceV1("APPROVED", "OK", Decimal("10")),
        planner_version="automatic_buy_planner_v1",
        planning_ts_utc=datetime(2026, 8, 19, 20, 0, tzinfo=UTC),
    )


def _item(*, account_mode: str = "live", version: str = "2") -> SimpleNamespace:
    return SimpleNamespace(
        runtime_input=SimpleNamespace(
            account_mode=account_mode,
            input_contract_version=version,
        )
    )


def _handoff() -> ExecutionHandoffV1:
    return ExecutionHandoffV1(
        handoff_id=99,
        plan_source="automatic_buy_planner_v1",
        plan_reference_id="ref-1",
        plan_content_hash="hash-1",
        trading_account_id=101,
        venue="bitvavo",
        market="BTC-EUR",
        side="BUY",
        executor_mode="LIVE",
        executor_identity="shared-executor-v1",
        runtime_owner="gurkdb",
        executor_credential_binding_id=7,
    )


def test_staged_runtime_plan_is_forwarded_by_object_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _plan()
    runtime_outcome = AutomaticBuyRuntimeItemOutcomeV1(
        idempotency_key="a" * 64,
        candidate_state="CANDIDATE",
        gate_state="APPROVED",
        planner_state=PLANNER_STATE_STAGED,
        audit_outcome="inserted",
        plan=plan,
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        composition,
        "evaluate_automatic_buy_runtime_item_v1",
        lambda conn, *, item: runtime_outcome,
    )

    def fake_submit(**kwargs: object) -> ExecutionHandoffV1:
        captured.update(kwargs)
        return _handoff()

    monkeypatch.setattr(composition, "submit_automatic_buy_plan_to_shared_handoff_v1", fake_submit)

    result = evaluate_and_handoff_automatic_buy_runtime_item_v1(
        object(),
        item=_item(),  # type: ignore[arg-type]
        executor_identity="shared-executor-v1",
        runtime_owner="gurkdb",
        handoff_repository=object(),  # type: ignore[arg-type]
    )
    assert captured["plan"] is plan
    assert captured["account_mode"] == "live"
    assert result.runtime_outcome is runtime_outcome
    assert result.handoff is not None


def test_non_staged_runtime_outcome_creates_no_handoff(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime_outcome = AutomaticBuyRuntimeItemOutcomeV1(
        idempotency_key="a" * 64,
        candidate_state="CANDIDATE",
        gate_state="DENIED",
        planner_state=PLANNER_STATE_NOT_REACHED,
        audit_outcome="inserted",
        plan=None,
    )
    monkeypatch.setattr(
        composition,
        "evaluate_automatic_buy_runtime_item_v1",
        lambda conn, *, item: runtime_outcome,
    )

    def forbidden_submit(**kwargs: object) -> ExecutionHandoffV1:
        raise AssertionError("handoff must not be called")

    monkeypatch.setattr(composition, "submit_automatic_buy_plan_to_shared_handoff_v1", forbidden_submit)
    result = evaluate_and_handoff_automatic_buy_runtime_item_v1(
        object(),
        item=_item(),  # type: ignore[arg-type]
        executor_identity="shared-executor-v1",
        runtime_owner="gurkdb",
        handoff_repository=object(),  # type: ignore[arg-type]
    )
    assert result.handoff is None


def test_live_composition_refuses_legacy_runtime_input_v1_before_evaluation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_evaluate(*args: object, **kwargs: object) -> AutomaticBuyRuntimeItemOutcomeV1:
        raise AssertionError("legacy LIVE input must fail before runtime evaluation")

    monkeypatch.setattr(composition, "evaluate_automatic_buy_runtime_item_v1", forbidden_evaluate)
    with pytest.raises(AutomaticBuyLiveHandoffCompositionError, match="LIVE_HANDOFF_REQUIRES_RUNTIME_INPUT_V2"):
        evaluate_and_handoff_automatic_buy_runtime_item_v1(
            object(),
            item=_item(version="1"),  # type: ignore[arg-type]
            executor_identity="shared-executor-v1",
            runtime_owner="gurkdb",
            handoff_repository=object(),  # type: ignore[arg-type]
        )
