"""
manual_execution_service_v1 — the one canonical manual execution
orchestration entrypoint.

Layer: application service, upstream of decision_gate and execution_planner.
This module exists to close finding B1 in
docs/reviews/manual_execution_ladder_p0_implementation_review_20260725.md
("There is no authoritative end-to-end manual SELL ladder call graph"):
process() is the single call graph from a persisted
ManualExecutionRequest (src.manual_execution.manual_execution_request_v1)
through decision_gate
(src.decision_gate.manual_execution_gate_v1.approve_and_reserve, the single
authoritative source of account-derived quantity, approval, and atomic SELL
reservation creation) to a read-only execution_planner preview
(src.execution_planner.contract_preview_v1.build_manual_sell_execution_plan_preview,
which resolves only the decision_gate-persisted approval ID),
never the reverse and never in parallel.

process() deliberately does not absorb:
  - permission logic            -> src.decision_gate.manual_execution_gate_v1
  - account quantity resolution -> src.decision_gate.free_base_quantity_v1
  - atomic reservation creation -> src.decision_gate.manual_execution_gate_v1.approve_and_reserve
  - venue/price rounding        -> src.execution_planner.canonical_rounding_v1
  - plan construction           -> src.execution_planner.contract_preview_v1
  - broker submission           -> not implemented anywhere yet (no executor
                                    consumes this preview)
  - reconciliation ownership    -> src.decision_gate.sell_reservation_v1
                                    (reconcile_reservation_state, unused here)

Explicitly out of scope for this version (see
docs/reviews/manual_execution_ladder_p0_remediation_implementation_20260726.md):
reconciliation, live broker submission, and A+ ladder anchor-based quantity
calculation. mode=LIVE requests are rejected before decision_gate is ever
called, because live trading permission is NOT_GRANTED — see AGENTS.md.

Ordering note: venue-constraint freshness is checked *before*
decision_gate.approve_and_reserve() is called, specifically so a stale/
missing venue metadata precondition never causes a real SELL reservation to
be created and then abandoned. A plan-construction failure *after* a
successful approval can still leave an approved-but-unused reservation
(execution_planner's own leg/ladder-shape validation runs after the
reservation already exists) — releasing that reservation is a
reconciliation-layer concern and is explicitly out of scope here; see the
remediation doc's remaining-blockers section.

broker_private_calls=0
broker_writes=0
order_submission=0
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from src.decision_gate.manual_execution_gate_v1 import (
    GATE_DECISION_EXECUTION_ALLOWED,
    ManualExecutionGateRepository,
    ManualExecutionGateResult,
)
from src.execution_planner.contract_preview_v1 import (
    ExecutionMarketContextPreview,
    ExecutionPlanPreview,
    ManualSellPlanningInputs,
    build_manual_sell_execution_plan_preview,
)
from src.manual_execution.manual_execution_request_v1 import (
    MODE_PAPER,
    REQUEST_STATE_FAILED,
    REQUEST_STATE_GATE_BLOCKED,
    REQUEST_STATE_PLAN_REJECTED,
    REQUEST_STATE_PLANNED,
    ManualExecutionRequest,
    ManualExecutionRequestRepository,
    advance_manual_execution_request_state,
)
from src.market_rules.venue_execution_constraints_v1 import (
    STATUS_FRESH,
    VenueExecutionConstraints,
)
from src.manual_execution import _trusted_clock_v1 as trusted_clock


SERVICE_NAME: Final[str] = "manual_execution_service_v1"

REASON_LIVE_TRADING_NOT_GRANTED: Final[str] = "LIVE_TRADING_NOT_GRANTED"
REASON_VENUE_CONSTRAINTS_NOT_FRESH: Final[str] = "VENUE_CONSTRAINTS_NOT_FRESH"


@dataclass(frozen=True)
class ManualExecutionOutcome:
    request: ManualExecutionRequest
    gate_result: ManualExecutionGateResult | None
    approval_id: int | None
    plan_preview: ExecutionPlanPreview | None
    notes: str


def process(
    request: ManualExecutionRequest,
    *,
    market_context: ExecutionMarketContextPreview,
    venue_constraints: VenueExecutionConstraints,
    sleeve_code: str,
) -> ManualExecutionOutcome:
    """Process one manual execution request end to end (PAPER preview only).

    market_context carries public market data (reference/bid/ask price,
    spread, regime) supplied by the caller — that is account-agnostic and
    not a permission input. venue_constraints must already be resolved via
    src.market_rules.venue_execution_constraints_v1.resolve_venue_execution_constraints
    (status must be FRESH); this function does not accept a bare tick_size.

    sleeve_code selects an execution-style profile in contract_preview_v1
    (post-only/reprice/urgency behavior) — it is not an account-permission
    input and carries no capital-allocation meaning for a manual SELL
    request.
    """
    resolved_now = trusted_clock.utc_now()
    request_repository = ManualExecutionRequestRepository()
    gate_repository = ManualExecutionGateRepository()

    if request.mode != MODE_PAPER:
        failed_request = advance_manual_execution_request_state(
            request,
            new_state=REQUEST_STATE_FAILED,
            processed_ts_utc=resolved_now,
            rejection_code=REASON_LIVE_TRADING_NOT_GRANTED,
            rejection_detail="live trading permission is NOT_GRANTED; mode=LIVE is rejected before decision_gate",
        )
        return ManualExecutionOutcome(
            request=failed_request,
            gate_result=None,
            approval_id=None,
            plan_preview=None,
            notes="rejected before decision_gate: mode != PAPER",
        )

    persisted_request = request_repository.create_request_idempotent(request)

    if venue_constraints.status != STATUS_FRESH:
        rejected_request = advance_manual_execution_request_state(
            persisted_request,
            new_state=REQUEST_STATE_PLAN_REJECTED,
            processed_ts_utc=resolved_now,
            rejection_code=REASON_VENUE_CONSTRAINTS_NOT_FRESH,
            rejection_detail=f"venue_constraints.status={venue_constraints.status}",
        )
        request_repository.update_request_state(rejected_request)
        return ManualExecutionOutcome(
            request=rejected_request,
            gate_result=None,
            approval_id=None,
            plan_preview=None,
            notes="rejected before decision_gate: venue execution constraints not fresh",
        )

    approval_outcome = gate_repository.approve_and_reserve(persisted_request)
    gate_result = approval_outcome.gate_result

    if gate_result.decision_state != GATE_DECISION_EXECUTION_ALLOWED:
        blocked_request = advance_manual_execution_request_state(
            persisted_request,
            new_state=REQUEST_STATE_GATE_BLOCKED,
            processed_ts_utc=resolved_now,
            rejection_code=gate_result.decision_reason,
            rejection_detail=", ".join(gate_result.blocking_reasons) or gate_result.decision_reason,
        )
        request_repository.update_request_state(blocked_request)
        return ManualExecutionOutcome(
            request=blocked_request,
            gate_result=gate_result,
            approval_id=None,
            plan_preview=None,
            notes="blocked at decision_gate; no reservation was created; execution_planner was not called",
        )

    approval_id = approval_outcome.approval_id
    assert approval_id is not None
    assert persisted_request.request_id is not None

    try:
        plan_preview = build_manual_sell_execution_plan_preview(
            request_id=persisted_request.request_id,
            approval_id=approval_id,
            planning_inputs=ManualSellPlanningInputs(
                market_context=market_context,
                venue_constraints=venue_constraints,
                sleeve_code=sleeve_code,
            ),
        )
    except (ValueError, PermissionError) as exc:
        rejected_request = advance_manual_execution_request_state(
            persisted_request,
            new_state=REQUEST_STATE_PLAN_REJECTED,
            processed_ts_utc=resolved_now,
            rejection_code="PLAN_CONSTRUCTION_REJECTED",
            rejection_detail=str(exc),
        )
        request_repository.update_request_state(rejected_request)
        return ManualExecutionOutcome(
            request=rejected_request,
            gate_result=gate_result,
            approval_id=approval_id,
            plan_preview=None,
            notes=f"execution_planner rejected the gate-approved intent: {exc}",
        )

    planned_request = advance_manual_execution_request_state(
        persisted_request,
        new_state=REQUEST_STATE_PLANNED,
        processed_ts_utc=resolved_now,
    )
    request_repository.update_request_state(planned_request)

    return ManualExecutionOutcome(
        request=planned_request,
        gate_result=gate_result,
        approval_id=approval_id,
        plan_preview=plan_preview,
        notes="preview_only=1; no_db_writes_beyond_request_state_and_reservation=1; no_executor=1",
    )
