"""Phase 4B pure-enough one-item orchestration sequence.

Owns sequence only. Calls the existing candidate evaluator, decision gate,
and execution planner in order and writes exactly one append-only audit row
per item. No target/invalidation comparison, no REDUCE/EXIT choice, no
fraction/quantity/ladder decision, and no account-permission decision is
made here -- all of that stays in the modules this orchestrator calls.

broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from src.decision_gate.account_protection_evaluation_v1 import (
    evaluate_account_protection_for_automatic_exit_v1,
)
from src.decision_gate.automatic_exit_gate_v1 import (
    STATE_APPROVED,
    AutomaticExitGateContextV1,
    evaluate_automatic_exit_candidate_permission_v1,
)
from src.execution_planner.automatic_exit_planner_v1 import (
    AutomaticExitPlanningContextV1,
    AutomaticExitPlanningError,
    build_automatic_exit_plan_v1,
)
from src.exit_policy.automatic_exit_candidate_v1 import (
    STATE_NO_ACTION,
    STATE_NON_ACTIONABLE,
    AutomaticExitMarketContextV1,
    AutomaticExitPolicyConfigV1,
    AutomaticExitPositionContextV1,
    evaluate_automatic_exit_candidate_v1,
)
from src.exit_policy.automatic_exit_runtime_audit_writer_v1 import (
    AuditWriteResultV1,
    build_immutable_plan_json,
    write_automatic_exit_evaluation_audit_v1,
)
from src.exit_policy.automatic_exit_runtime_contract_v1 import automatic_exit_idempotency_key_v1
from src.exit_policy.automatic_exit_runtime_repository_v1 import RuntimeItemV1


RUNTIME_VERSION: Final[str] = "automatic_exit_policy_runtime_v1"

PLANNER_STATE_NOT_REACHED: Final[str] = "NOT_REACHED"
PLANNER_STATE_STAGED: Final[str] = "STAGED"
PLANNER_STATE_REJECTED: Final[str] = "REJECTED"


@dataclass(frozen=True)
class RuntimeItemOutcomeV1:
    idempotency_key: str
    candidate_state: str
    gate_state: str | None
    planner_state: str
    audit_outcome: str  # inserted | idempotent_existing


def build_automatic_exit_source_evidence_v1(item: RuntimeItemV1) -> dict[str, Any]:
    """Canonical immutable source identity used by runtime audit and Phase 5."""
    return {
        "trading_account_id": item.trading_account_id,
        "position_reference": item.position_reference,
        "venue": item.venue,
        "asset_id": item.asset_id,
        "market": item.market,
        "position_snapshot_id": item.position_snapshot_id,
        "balance_snapshot_id": item.balance_snapshot_id,
        "open_order_snapshot_run_id": item.open_order_snapshot_run_id,
        "market_price_snapshot_id": item.market_price_snapshot_id,
        "automatic_exit_permission_id": item.automatic_exit_permission_id,
        "exit_profile_id": item.exit_profile.profile_id,
        "exit_profile_version": item.exit_profile.profile_version,
        "exit_profile_observed_ts_utc": item.exit_profile.observed_ts_utc,
        "venue_constraint_id": item.venue_constraint_id,
        "venue_metadata_synced_ts_utc": item.venue_constraints.metadata_synced_ts_utc,
    }


def evaluate_automatic_exit_runtime_item_v1(
    conn: Any,
    *,
    item: RuntimeItemV1,
    evaluation_ts_utc: datetime,
    config: AutomaticExitPolicyConfigV1 = AutomaticExitPolicyConfigV1(),
) -> RuntimeItemOutcomeV1:
    """Evaluate one held position and append exactly one audit row."""
    evidence = build_automatic_exit_source_evidence_v1(item)
    idempotency_key = automatic_exit_idempotency_key_v1(evidence)
    # Logical evidence is immutable source/replay identity only. Runtime
    # provenance belongs in the audit column, so runtime upgrades do not make
    # an otherwise identical decision look like an idempotency conflict.
    source_evidence_json = evidence

    audit_identity = dict(
        idempotency_key=idempotency_key,
        runtime_version=RUNTIME_VERSION,
        trading_account_id=item.trading_account_id,
        position_reference=item.position_reference,
        venue=item.venue,
        asset_id=item.asset_id,
        market=item.market,
        source_evidence_json=source_evidence_json,
        evaluation_ts_utc=evaluation_ts_utc,
    )

    position_context = AutomaticExitPositionContextV1(
        trading_account_id=item.trading_account_id,
        position_reference=item.position_reference,
        venue=item.venue,
        asset_id=item.asset_id,
        market=item.market,
        held_quantity_base=item.held_quantity_base,
        observed_ts_utc=item.account_state_observed_ts_utc,
    )
    market_context = AutomaticExitMarketContextV1(
        venue=item.venue,
        asset_id=item.asset_id,
        market=item.market,
        current_price=item.current_price,
        active_target_price=item.exit_profile.active_target_price,
        invalidation_price=item.exit_profile.invalidation_price,
        exit_profile_id=item.exit_profile.profile_id,
        exit_profile_version=item.exit_profile.profile_version,
        evidence_id=item.exit_profile.evidence_id,
        observed_ts_utc=item.market_price_observed_ts_utc,
    )
    evaluation = evaluate_automatic_exit_candidate_v1(
        position=position_context, market_context=market_context, evaluation_ts_utc=evaluation_ts_utc, config=config,
    )

    if evaluation.state in (STATE_NO_ACTION, STATE_NON_ACTIONABLE):
        result = write_automatic_exit_evaluation_audit_v1(
            conn,
            **audit_identity,
            candidate_state=evaluation.state,
            candidate_action=None,
            candidate_reason_code=evaluation.reason_code,
            candidate_evidence_id=None,
            exit_profile_id=item.exit_profile.profile_id,
            exit_profile_version=item.exit_profile.profile_version,
            gate_state=None,
            gate_reason_code=None,
            approved_fraction_candidate=None,
            approved_quantity_ceiling_base=None,
            planner_state=PLANNER_STATE_NOT_REACHED,
            planner_reason_code=None,
            immutable_plan_json=None,
            planning_ts_utc=None,
        )
        return RuntimeItemOutcomeV1(idempotency_key, evaluation.state, None, PLANNER_STATE_NOT_REACHED, result.outcome)

    assert evaluation.candidate is not None
    candidate = evaluation.candidate

    account_protection_evaluation = evaluate_account_protection_for_automatic_exit_v1(
        conn,
        trading_account_id=item.trading_account_id,
        asset_id=item.asset_id,
        requested_action=candidate.candidate_action,
        account_state_observed_ts_utc=item.account_state_observed_ts_utc,
        evaluation_ts_utc=evaluation_ts_utc,
    )

    gate_context = AutomaticExitGateContextV1(
        trading_account_id=item.trading_account_id,
        position_reference=item.position_reference,
        venue=item.venue,
        asset_id=item.asset_id,
        market=item.market,
        position_snapshot_id=str(item.position_snapshot_id),
        held_quantity_base=item.held_quantity_base,
        free_quantity_base=item.free_quantity_base,
        account_observed_ts_utc=item.account_state_observed_ts_utc,
        position_observed_ts_utc=item.account_state_observed_ts_utc,
        free_quantity_observed_ts_utc=item.account_state_observed_ts_utc,
        account_enabled=item.account_enabled,
        account_mode=item.account_mode,
        automatic_exit_execution_enabled=item.automatic_exit_execution_enabled,
        live_trading_enabled=item.live_trading_enabled,
        automatic_exit_live_permission_enabled=item.automatic_exit_live_permission_enabled,
        blocking_conflict=item.blocking_conflict,
        evaluation_ts_utc=evaluation_ts_utc,
        account_protection_evaluation=account_protection_evaluation,
    )
    decision = evaluate_automatic_exit_candidate_permission_v1(candidate=candidate, context=gate_context)

    def _write_pre_plan_audit(planner_state: str, planner_reason_code: str | None, planning_ts_utc: datetime | None) -> AuditWriteResultV1:
        return write_automatic_exit_evaluation_audit_v1(
            conn,
            **audit_identity,
            candidate_state=evaluation.state,
            candidate_action=candidate.candidate_action,
            candidate_reason_code=candidate.reason_code,
            candidate_evidence_id=candidate.evidence_id,
            exit_profile_id=candidate.exit_profile_id,
            exit_profile_version=candidate.exit_profile_version,
            gate_state=decision.state,
            gate_reason_code=decision.reason_code,
            approved_fraction_candidate=decision.approved_fraction_candidate,
            approved_quantity_ceiling_base=decision.approved_quantity_ceiling_base,
            protection_code=decision.protection_code,
            protection_reason_code=decision.protection_reason_code,
            planner_state=planner_state,
            planner_reason_code=planner_reason_code,
            immutable_plan_json=None,
            planning_ts_utc=planning_ts_utc,
        )

    if decision.state != STATE_APPROVED:
        result = _write_pre_plan_audit(PLANNER_STATE_NOT_REACHED, None, None)
        return RuntimeItemOutcomeV1(idempotency_key, evaluation.state, decision.state, PLANNER_STATE_NOT_REACHED, result.outcome)

    planning_context = AutomaticExitPlanningContextV1(
        trading_account_id=item.trading_account_id,
        position_reference=item.position_reference,
        venue=item.venue,
        asset_id=item.asset_id,
        market=item.market,
        reference_price=item.current_price,
        venue_constraints=item.venue_constraints,
        planning_ts_utc=evaluation_ts_utc,
    )
    try:
        plan = build_automatic_exit_plan_v1(decision=decision, context=planning_context)
    except AutomaticExitPlanningError as exc:
        result = _write_pre_plan_audit(PLANNER_STATE_REJECTED, exc.reason_code, evaluation_ts_utc)
        return RuntimeItemOutcomeV1(idempotency_key, evaluation.state, decision.state, PLANNER_STATE_REJECTED, result.outcome)

    result = write_automatic_exit_evaluation_audit_v1(
        conn,
        **audit_identity,
        candidate_state=evaluation.state,
        candidate_action=candidate.candidate_action,
        candidate_reason_code=candidate.reason_code,
        candidate_evidence_id=candidate.evidence_id,
        exit_profile_id=candidate.exit_profile_id,
        exit_profile_version=candidate.exit_profile_version,
        gate_state=decision.state,
        gate_reason_code=decision.reason_code,
        approved_fraction_candidate=decision.approved_fraction_candidate,
        approved_quantity_ceiling_base=decision.approved_quantity_ceiling_base,
        protection_code=decision.protection_code,
        protection_reason_code=decision.protection_reason_code,
        planner_state=PLANNER_STATE_STAGED,
        planner_reason_code=None,
        immutable_plan_json=build_immutable_plan_json(plan),
        planning_ts_utc=evaluation_ts_utc,
    )
    return RuntimeItemOutcomeV1(idempotency_key, evaluation.state, decision.state, PLANNER_STATE_STAGED, result.outcome)
