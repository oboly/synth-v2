"""Issue #399 Phase 4 canonical automatic BUY runtime sequence.

Owns sequencing only: Phase 1 candidate -> Phase 2 decision_gate -> Phase 3
planner -> append-only audit. No executor handoff or broker behavior exists.
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Final

from src.decision_gate.automatic_buy_gate_v1 import (
    STATE_APPROVED,
    AutomaticBuyGateContextV1,
    evaluate_automatic_buy_candidate_permission_v1,
)
from src.entry_policy.automatic_buy_candidate_v1 import (
    STATE_CANDIDATE,
    AutomaticBuyPolicyConfigV1,
    AutomaticBuySetupContextV1,
    evaluate_automatic_buy_candidate_v1,
)
from src.entry_policy.automatic_buy_runtime_audit_writer_v1 import (
    build_immutable_buy_plan_json,
    canonical_json,
    write_automatic_buy_evaluation_audit_v1,
)
from src.entry_policy.automatic_buy_runtime_contract_v1 import automatic_buy_idempotency_key_v1
from src.entry_policy.automatic_buy_runtime_repository_v1 import RuntimeItemV1
from src.execution_planner.automatic_buy_planner_v1 import (
    AutomaticBuyPlanningContextV1,
    AutomaticBuyPlanningError,
    AutomaticBuyPlanV1,
    build_automatic_buy_plan_v1,
)


RUNTIME_VERSION: Final[str] = "automatic_buy_policy_runtime_v1"
PLANNER_STATE_NOT_REACHED: Final[str] = "NOT_REACHED"
PLANNER_STATE_STAGED: Final[str] = "STAGED"
PLANNER_STATE_REJECTED: Final[str] = "REJECTED"


@dataclass(frozen=True)
class AutomaticBuyRuntimeItemOutcomeV1:
    idempotency_key: str
    candidate_state: str
    gate_state: str | None
    planner_state: str
    audit_outcome: str
    plan: AutomaticBuyPlanV1 | None = None


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def build_automatic_buy_source_evidence_v1(item: RuntimeItemV1) -> dict[str, Any]:
    value = item.runtime_input
    config_ids = tuple(sorted(row.strategy_bucket_account_config_id for row in item.strategy_bucket_config_rows))
    revocation_ids = tuple(sorted(
        row.strategy_bucket_account_config_revocation_id
        for row in item.strategy_bucket_config_revocations
    ))
    protection_fingerprint = _fingerprint(asdict(item.account_protection_evaluation))
    constraints = item.venue_constraints
    constraint_identity = {
        "venue": constraints.venue,
        "market": constraints.market,
        "source_provenance": constraints.source_provenance,
        "metadata_synced_ts_utc": constraints.metadata_synced_ts_utc,
        "tick_size": constraints.tick_size,
        "qty_step_size": constraints.qty_step_size,
        "min_base_quantity": constraints.min_base_quantity,
        "min_quote_notional": constraints.min_quote_notional,
        "supported_order_types": constraints.supported_order_types,
        "supported_time_in_force": constraints.supported_time_in_force,
    }
    return {
        "source_snapshot_key": value.source_snapshot_key,
        "trading_account_id": value.trading_account_id,
        "venue": value.venue,
        "asset_id": value.asset_id,
        "market": value.market,
        "strategy_id": value.strategy_id,
        "strategy_version": value.strategy_version,
        "setup_id": value.setup_id,
        "setup_evidence_id": value.setup_evidence_id,
        "strategy_bucket_config_ids": config_ids,
        "strategy_bucket_revocation_ids": revocation_ids,
        "account_protection_fingerprint": protection_fingerprint,
        "venue_constraint_identity": constraint_identity,
    }


def evaluate_automatic_buy_runtime_item_v1(
    conn: Any,
    *,
    item: RuntimeItemV1,
    evaluation_ts_utc: datetime,
    config: AutomaticBuyPolicyConfigV1 = AutomaticBuyPolicyConfigV1(),
) -> AutomaticBuyRuntimeItemOutcomeV1:
    runtime_input = item.runtime_input
    evidence = build_automatic_buy_source_evidence_v1(item)
    idempotency_key = automatic_buy_idempotency_key_v1(evidence)
    audit_identity = dict(
        idempotency_key=idempotency_key,
        runtime_version=RUNTIME_VERSION,
        trading_account_id=runtime_input.trading_account_id,
        venue=runtime_input.venue,
        asset_id=runtime_input.asset_id,
        market=runtime_input.market,
        source_evidence_json=evidence,
        evaluation_ts_utc=evaluation_ts_utc,
    )

    setup_context = AutomaticBuySetupContextV1(
        venue=runtime_input.venue,
        asset_id=runtime_input.asset_id,
        market=runtime_input.market,
        strategy_id=runtime_input.strategy_id,
        strategy_version=runtime_input.strategy_version,
        setup_id=runtime_input.setup_id,
        setup_ready=runtime_input.setup_ready,
        current_price=runtime_input.current_price,
        entry_zone_low=runtime_input.entry_zone_low,
        entry_zone_high=runtime_input.entry_zone_high,
        re_entry_zone_low=runtime_input.re_entry_zone_low,
        re_entry_zone_high=runtime_input.re_entry_zone_high,
        evidence_id=runtime_input.setup_evidence_id,
        observed_ts_utc=runtime_input.setup_observed_ts_utc,
    )
    evaluation = evaluate_automatic_buy_candidate_v1(
        setup_context=setup_context,
        evaluation_ts_utc=evaluation_ts_utc,
        config=config,
    )
    if evaluation.state != STATE_CANDIDATE:
        result = write_automatic_buy_evaluation_audit_v1(
            conn,
            **audit_identity,
            candidate_state=evaluation.state,
            candidate_action=None,
            candidate_reason_code=evaluation.reason_code,
            candidate_evidence_id=None,
            gate_state=None,
            gate_reason_code=None,
            approved_notional_ceiling_eur=None,
            strategy_bucket_reason_code=None,
            protection_code=None,
            protection_reason_code=None,
            planner_state=PLANNER_STATE_NOT_REACHED,
            planner_reason_code=None,
            immutable_plan_json=None,
            planning_ts_utc=None,
        )
        return AutomaticBuyRuntimeItemOutcomeV1(
            idempotency_key, evaluation.state, None, PLANNER_STATE_NOT_REACHED, result.outcome,
        )

    assert evaluation.candidate is not None
    candidate = evaluation.candidate
    gate_context = AutomaticBuyGateContextV1(
        trading_account_id=runtime_input.trading_account_id,
        venue=runtime_input.venue,
        asset_id=runtime_input.asset_id,
        market=runtime_input.market,
        strategy_bucket_id=runtime_input.strategy_bucket_id,
        account_observed_ts_utc=runtime_input.account_observed_ts_utc,
        account_enabled=runtime_input.account_enabled,
        account_mode=runtime_input.account_mode,
        automatic_buy_execution_enabled=runtime_input.automatic_buy_execution_enabled,
        free_quote_balance_eur=runtime_input.free_quote_balance_eur,
        free_quote_balance_observed_ts_utc=runtime_input.free_quote_balance_observed_ts_utc,
        blocking_conflict=runtime_input.blocking_conflict,
        proposed_position_amount_eur=runtime_input.proposed_position_amount_eur,
        current_bucket_amount_eur=runtime_input.current_bucket_amount_eur,
        current_open_positions=runtime_input.current_open_positions,
        current_asset_exposure_pct=runtime_input.current_asset_exposure_pct,
        evaluation_ts_utc=evaluation_ts_utc,
        max_automatic_buy_notional_eur=runtime_input.max_automatic_buy_notional_eur,
        strategy_bucket_config_rows=item.strategy_bucket_config_rows,
        strategy_bucket_config_revocations=item.strategy_bucket_config_revocations,
        account_protection_evaluation=item.account_protection_evaluation,
    )
    decision = evaluate_automatic_buy_candidate_permission_v1(candidate=candidate, context=gate_context)

    def write_pre_plan(planner_state: str, planner_reason: str | None) -> Any:
        return write_automatic_buy_evaluation_audit_v1(
            conn,
            **audit_identity,
            candidate_state=evaluation.state,
            candidate_action=candidate.candidate_action,
            candidate_reason_code=candidate.reason_code,
            candidate_evidence_id=candidate.evidence_id,
            gate_state=decision.state,
            gate_reason_code=decision.reason_code,
            approved_notional_ceiling_eur=decision.approved_notional_ceiling_eur,
            strategy_bucket_reason_code=decision.strategy_bucket_reason_code,
            protection_code=decision.protection_code,
            protection_reason_code=decision.protection_reason_code,
            planner_state=planner_state,
            planner_reason_code=planner_reason,
            immutable_plan_json=None,
            planning_ts_utc=None,
        )

    if decision.state != STATE_APPROVED:
        result = write_pre_plan(PLANNER_STATE_NOT_REACHED, None)
        return AutomaticBuyRuntimeItemOutcomeV1(
            idempotency_key, evaluation.state, decision.state, PLANNER_STATE_NOT_REACHED, result.outcome,
        )

    planning_context = AutomaticBuyPlanningContextV1(
        trading_account_id=runtime_input.trading_account_id,
        venue=runtime_input.venue,
        asset_id=runtime_input.asset_id,
        market=runtime_input.market,
        reference_price=runtime_input.current_price,
        venue_constraints=item.venue_constraints,
        planning_ts_utc=evaluation_ts_utc,
    )
    try:
        plan = build_automatic_buy_plan_v1(decision=decision, context=planning_context)
    except AutomaticBuyPlanningError as exc:
        result = write_pre_plan(PLANNER_STATE_REJECTED, exc.reason_code)
        return AutomaticBuyRuntimeItemOutcomeV1(
            idempotency_key, evaluation.state, decision.state, PLANNER_STATE_REJECTED, result.outcome,
        )

    immutable_plan = build_immutable_buy_plan_json(plan)
    # Wall-clock planning time is audit metadata, not logical execution intent.
    immutable_plan.pop("planning_ts_utc", None)
    result = write_automatic_buy_evaluation_audit_v1(
        conn,
        **audit_identity,
        candidate_state=evaluation.state,
        candidate_action=candidate.candidate_action,
        candidate_reason_code=candidate.reason_code,
        candidate_evidence_id=candidate.evidence_id,
        gate_state=decision.state,
        gate_reason_code=decision.reason_code,
        approved_notional_ceiling_eur=decision.approved_notional_ceiling_eur,
        strategy_bucket_reason_code=decision.strategy_bucket_reason_code,
        protection_code=decision.protection_code,
        protection_reason_code=decision.protection_reason_code,
        planner_state=PLANNER_STATE_STAGED,
        planner_reason_code=None,
        immutable_plan_json=immutable_plan,
        planning_ts_utc=evaluation_ts_utc,
    )
    return AutomaticBuyRuntimeItemOutcomeV1(
        idempotency_key, evaluation.state, decision.state, PLANNER_STATE_STAGED, result.outcome, plan=plan,
    )
