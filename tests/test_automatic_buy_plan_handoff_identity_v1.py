"""Issue #753 B4: end-to-end identity survival regression.

Exercises the real candidate -> gate -> planner -> shared handoff adapter
chain (not hand-built fixtures) to prove strategy_bucket_id and trade_id
survive intact, duplicate replay of the same accepted lineage yields the
same identity, and genuinely distinct lineages never collide.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.decision_gate.automatic_buy_gate_v1 import (
    STATE_APPROVED,
    AutomaticBuyGateContextV1,
    evaluate_automatic_buy_candidate_permission_v1,
)
from src.decision_gate.strategy_bucket_account_config_contract_v1 import StrategyBucketAccountConfigRowV1
from src.entry_policy import POLICY_NAME, POLICY_VERSION
from src.entry_policy.automatic_buy_candidate_v1 import AutomaticBuyCandidateV1
from src.execution_planner.automatic_buy_execution_handoff_adapter_v1 import (
    adapt_automatic_buy_plan_to_approved_execution_plan_v1,
    derive_automatic_buy_plan_reference_id_v1,
)
from src.execution_planner.automatic_buy_planner_v1 import (
    AutomaticBuyPlanningContextV1,
    build_automatic_buy_plan_v1,
)
from src.market_rules.venue_execution_constraints_v1 import STATUS_FRESH, VenueExecutionConstraints

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)
BUCKET = "SHORT_TERM_ROTATION"


def _candidate(**overrides: object) -> AutomaticBuyCandidateV1:
    values: dict[str, object] = dict(
        venue="bitvavo", asset_id=42, market="SOL-EUR", strategy_id="strat-1",
        strategy_version="1", setup_id="setup-1", candidate_action="ENTER",
        reason_code="ENTRY_ZONE_REACHED", evidence_id="evidence-1",
        entry_zone_low=Decimal("90"), entry_zone_high=Decimal("100"),
        observed_ts_utc=NOW, policy_name=POLICY_NAME, policy_version=POLICY_VERSION,
    )
    values.update(overrides)
    return AutomaticBuyCandidateV1(**values)  # type: ignore[arg-type]


def _bucket_row(**overrides: object) -> StrategyBucketAccountConfigRowV1:
    values: dict[str, object] = dict(
        strategy_bucket_account_config_id=1, trading_account_id=7, strategy_bucket_id=BUCKET,
        config_version="1", is_enabled=True, risk_profile="MODERATE",
        max_position_amount_eur=None, max_bucket_amount_eur=None, max_asset_exposure_pct=None,
        max_open_positions=None, allow_new_entries=True, allow_reduce_reviews=True,
        effective_from_ts_utc=NOW - timedelta(days=1), effective_until_ts_utc=None,
        source_provenance="manual_review",
    )
    values.update(overrides)
    return StrategyBucketAccountConfigRowV1(**values)  # type: ignore[arg-type]


def _context(**overrides: object) -> AutomaticBuyGateContextV1:
    values: dict[str, object] = dict(
        trading_account_id=7, venue="bitvavo", asset_id=42, market="SOL-EUR",
        strategy_bucket_id=BUCKET, account_observed_ts_utc=NOW, account_enabled=True,
        account_mode="paper", automatic_buy_execution_enabled=True,
        free_quote_balance_eur=Decimal("500"), free_quote_balance_observed_ts_utc=NOW,
        blocking_conflict=False, proposed_position_amount_eur=Decimal("100"),
        current_bucket_amount_eur=Decimal("0"), current_open_positions=0,
        current_asset_exposure_pct=Decimal("0"), evaluation_ts_utc=NOW,
        strategy_bucket_config_rows=(_bucket_row(),),
    )
    values.update(overrides)
    return AutomaticBuyGateContextV1(**values)  # type: ignore[arg-type]


def _constraints(**overrides: object) -> VenueExecutionConstraints:
    values: dict[str, object] = dict(
        venue="bitvavo", market="SOL-EUR", tick_size=Decimal("0.05"), qty_step_size=Decimal("0.1"),
        min_base_quantity=Decimal("0.1"), min_quote_notional=Decimal("5"),
        supported_order_types=("limit",), supported_time_in_force=("GTC",),
        source_provenance="PUBLIC", metadata_synced_ts_utc=NOW, status=STATUS_FRESH,
    )
    values.update(overrides)
    return VenueExecutionConstraints(**values)  # type: ignore[arg-type]


def _planning_context(**overrides: object) -> AutomaticBuyPlanningContextV1:
    values: dict[str, object] = dict(
        trading_account_id=7, venue="bitvavo", asset_id=42, market="SOL-EUR",
        reference_price=Decimal("100.01"), venue_constraints=_constraints(), planning_ts_utc=NOW,
    )
    values.update(overrides)
    return AutomaticBuyPlanningContextV1(**values)  # type: ignore[arg-type]


def _build_plan(
    *,
    candidate_overrides: dict | None = None,
    context_overrides: dict | None = None,
    planning_overrides: dict | None = None,
):
    candidate = _candidate(**(candidate_overrides or {}))
    decision = evaluate_automatic_buy_candidate_permission_v1(
        candidate=candidate, context=_context(**(context_overrides or {})),
    )
    assert decision.state == STATE_APPROVED
    plan = build_automatic_buy_plan_v1(
        decision=decision, context=_planning_context(**(planning_overrides or {})),
    )
    return decision, plan


def test_identity_survives_candidate_gate_plan_handoff() -> None:
    decision, plan = _build_plan()
    assert decision.strategy_bucket_id == BUCKET
    assert plan.strategy_bucket_id == BUCKET
    assert plan.trade_id

    approved = adapt_automatic_buy_plan_to_approved_execution_plan_v1(plan)
    reference_id = derive_automatic_buy_plan_reference_id_v1(plan)
    assert approved.plan_reference_id == reference_id


def test_duplicate_replay_of_the_same_accepted_lineage_yields_same_identity() -> None:
    _, first_plan = _build_plan()
    _, second_plan = _build_plan()
    assert first_plan.strategy_bucket_id == second_plan.strategy_bucket_id
    assert first_plan.trade_id == second_plan.trade_id
    assert (
        derive_automatic_buy_plan_reference_id_v1(first_plan)
        == derive_automatic_buy_plan_reference_id_v1(second_plan)
    )


def test_genuinely_distinct_lineages_never_collide() -> None:
    _, base_plan = _build_plan()
    _, other_bucket_plan = _build_plan(context_overrides={
        "strategy_bucket_id": "OTHER_BUCKET",
        "strategy_bucket_config_rows": (_bucket_row(strategy_bucket_id="OTHER_BUCKET"),),
    })
    _, other_evidence_plan = _build_plan(candidate_overrides={"evidence_id": "evidence-2"})
    _, other_account_plan = _build_plan(
        context_overrides={
            "trading_account_id": 8,
            "strategy_bucket_config_rows": (_bucket_row(trading_account_id=8),),
        },
        planning_overrides={"trading_account_id": 8},
    )

    trade_ids = {
        base_plan.trade_id, other_bucket_plan.trade_id,
        other_evidence_plan.trade_id, other_account_plan.trade_id,
    }
    assert len(trade_ids) == 4
    reference_ids = {
        derive_automatic_buy_plan_reference_id_v1(base_plan),
        derive_automatic_buy_plan_reference_id_v1(other_bucket_plan),
        derive_automatic_buy_plan_reference_id_v1(other_evidence_plan),
        derive_automatic_buy_plan_reference_id_v1(other_account_plan),
    }
    assert len(reference_ids) == 4


def test_denied_decision_never_reaches_planner_with_stale_bucket_identity() -> None:
    candidate = _candidate()
    denied = evaluate_automatic_buy_candidate_permission_v1(
        candidate=candidate, context=_context(account_enabled=False),
    )
    assert denied.strategy_bucket_id is None
