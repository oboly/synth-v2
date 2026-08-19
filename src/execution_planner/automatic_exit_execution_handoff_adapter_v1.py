"""Issue #392 Phase 6 blocker A: pure lossless adapter.

Translates an already-produced, already-approved, immutable in-memory
``AutomaticExitPlanV1`` (Issue #392) into the shared executor handoff
contract ``ApprovedExecutionPlanV1`` (Issue #206), with no re-evaluation of
exit policy, no re-run of ``decision_gate``, no quantity/price recompute or
re-rounding, no broker/credential/authority/kill-switch inspection, and no
order submission.

This module is the sole deliberate #392 -> #206 import boundary: it is the
only place under ``src/execution_planner`` that imports the executor's
shared plan-reference contract. ``src/executor`` core modules remain
unaware of ``AutomaticExitPlanV1``; ``src/exit_policy`` strategy/candidate
modules do not import this module or anything under ``src/executor``.

The audit table (``automatic_exit_evaluation_audit_v1``) is never read by
this module. Callers must pass the in-memory ``AutomaticExitPlanV1`` object
produced by ``build_automatic_exit_plan_v1`` in the same evaluation cycle.

broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
"""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Final

from src.execution_planner.automatic_exit_planner_v1 import (
    AutomaticExitPlanLegV1,
    AutomaticExitPlanV1,
)
from src.executor.execution_plan_reference_v1 import (
    ApprovedExecutionPlanV1,
    ExecutionPlanLegV1,
)

# Stable source identifier for the shared executor handoff. This is the
# adapter's own source label, distinct from (and not derived from) the
# planner's own version string, so a future planner-version bump cannot
# silently change plan_source.
PLAN_SOURCE_AUTOMATIC_EXIT_V1: Final[str] = "automatic_exit_planner_v1"

SIDE_SELL: Final[str] = "SELL"
SUPPORTED_CANDIDATE_ACTIONS: Final[frozenset[str]] = frozenset({"REDUCE", "EXIT"})
REQUIRED_GATE_APPROVAL_STATE: Final[str] = "APPROVED"

_PLAN_REFERENCE_ID_CONTRACT_VERSION: Final[str] = "automatic_exit_execution_handoff_adapter_v1"


class AutomaticExitPlanAdapterError(ValueError):
    """Fail-closed adapter rejection with a stable machine reason."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _reject(condition: bool, reason_code: str) -> None:
    if condition:
        raise AutomaticExitPlanAdapterError(reason_code)


def _decimal_text(value: Decimal) -> str:
    normalized = format(value.normalize(), "f")
    if "." not in normalized:
        return normalized
    normalized = normalized.rstrip("0").rstrip(".")
    return normalized or "0"


def _validate_plan_structure(plan: AutomaticExitPlanV1) -> None:
    """Fail closed on any malformed or ambiguous AutomaticExitPlanV1.

    This validates internal consistency only. It never re-derives or
    re-approves anything; a structurally valid plan is passed through
    unchanged.
    """
    _reject(
        plan.trading_account_id <= 0 or plan.asset_id <= 0,
        "PLAN_IDENTITY_NOT_POSITIVE",
    )
    _reject(
        not all(_nonempty(value) for value in (plan.position_reference, plan.venue, plan.market)),
        "PLAN_IDENTITY_FIELD_EMPTY",
    )
    _reject(plan.side != SIDE_SELL, "PLAN_SIDE_NOT_SELL")
    _reject(
        plan.candidate_action not in SUPPORTED_CANDIDATE_ACTIONS,
        "PLAN_CANDIDATE_ACTION_UNSUPPORTED",
    )
    _reject(
        not all(
            _nonempty(value)
            for value in (
                plan.candidate_reason_code,
                plan.candidate_evidence_id,
                plan.exit_profile_id,
                plan.exit_profile_version,
                plan.planner_version,
            )
        ),
        "PLAN_PROVENANCE_FIELD_EMPTY",
    )
    gate_approval = plan.gate_approval
    _reject(
        gate_approval is None or gate_approval.state != REQUIRED_GATE_APPROVAL_STATE,
        "PLAN_GATE_APPROVAL_NOT_APPROVED",
    )
    _reject(
        gate_approval.approved_fraction_candidate is None
        or gate_approval.approved_fraction_candidate <= 0
        or gate_approval.approved_fraction_candidate > 1,
        "PLAN_GATE_APPROVED_FRACTION_INVALID",
    )
    _reject(
        gate_approval.approved_quantity_ceiling_base is None
        or gate_approval.approved_quantity_ceiling_base <= 0,
        "PLAN_GATE_APPROVED_CEILING_INVALID",
    )
    _reject(plan.final_quantity_base <= 0, "PLAN_FINAL_QUANTITY_NOT_POSITIVE")
    _reject(not isinstance(plan.legs, tuple) or not plan.legs, "PLAN_LEGS_EMPTY")

    indices = tuple(leg.leg_index for leg in plan.legs)
    expected_indices = tuple(range(1, len(plan.legs) + 1))
    _reject(indices != expected_indices, "PLAN_LEG_INDICES_NOT_STRICTLY_ORDERED")

    leg_total = Decimal("0")
    for leg in plan.legs:
        _reject(leg.side != plan.side, "PLAN_LEG_SIDE_MISMATCH")
        _reject(leg.limit_price <= 0, "PLAN_LEG_PRICE_NOT_POSITIVE")
        _reject(leg.quantity_base <= 0, "PLAN_LEG_QUANTITY_NOT_POSITIVE")
        _reject(leg.quote_notional <= 0, "PLAN_LEG_NOTIONAL_NOT_POSITIVE")
        leg_total += leg.quantity_base
    _reject(leg_total != plan.final_quantity_base, "PLAN_LEG_QUANTITY_SUM_MISMATCH")


def _leg_reference_payload(leg: AutomaticExitPlanLegV1) -> dict[str, object]:
    return {
        "leg_index": leg.leg_index,
        "side": leg.side,
        "limit_price": _decimal_text(leg.limit_price),
        "quantity_base": _decimal_text(leg.quantity_base),
        "quote_notional": _decimal_text(leg.quote_notional),
        "post_only": leg.post_only,
        "time_in_force": leg.time_in_force,
    }


def _plan_identity_payload(plan: AutomaticExitPlanV1) -> dict[str, object]:
    """Canonical logical-identity payload used to derive plan_reference_id.

    Deliberately excludes ``planning_ts_utc`` (wall-clock, not part of
    logical intent) so retries and restarts of the same logical evaluation
    produce the same identity. Every other field that can change the
    approved execution intent -- including REDUCE/EXIT action, evidence
    identity, exit profile version, gate approval provenance, planner
    version, and exact leg prices/quantities -- is included so that two
    logically distinct plans never collide, even if their resulting SELL
    ladder is numerically identical.
    """
    gate_approval = plan.gate_approval
    return {
        "contract_version": _PLAN_REFERENCE_ID_CONTRACT_VERSION,
        "trading_account_id": plan.trading_account_id,
        "position_reference": plan.position_reference,
        "venue": plan.venue,
        "asset_id": plan.asset_id,
        "market": plan.market,
        "side": plan.side,
        "final_quantity_base": _decimal_text(plan.final_quantity_base),
        "candidate_action": plan.candidate_action,
        "candidate_reason_code": plan.candidate_reason_code,
        "candidate_evidence_id": plan.candidate_evidence_id,
        "exit_profile_id": plan.exit_profile_id,
        "exit_profile_version": plan.exit_profile_version,
        "gate_approval": {
            "state": gate_approval.state,
            "reason_code": gate_approval.reason_code,
            "approved_fraction_candidate": _decimal_text(gate_approval.approved_fraction_candidate),
            "approved_quantity_ceiling_base": _decimal_text(gate_approval.approved_quantity_ceiling_base),
        },
        "planner_version": plan.planner_version,
        "legs": [_leg_reference_payload(leg) for leg in plan.legs],
    }


def derive_automatic_exit_plan_reference_id_v1(plan: AutomaticExitPlanV1) -> str:
    """Deterministic, retry-stable, evidence-traceable plan_reference_id.

    Same logical plan (including on retry or process restart) always
    derives the same id. Any change to REDUCE/EXIT action, evidence
    identity, exit profile id/version, gate approval provenance, planner
    version, or any leg price/quantity/index changes the id. Does not read
    or depend on any persisted audit/reporting row.
    """
    payload = _plan_identity_payload(plan)
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    content_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return (
        f"automatic_exit_v1:{plan.trading_account_id}:{plan.position_reference}:"
        f"{plan.candidate_evidence_id}:{content_hash}"
    )


def adapt_automatic_exit_plan_to_approved_execution_plan_v1(
    plan: AutomaticExitPlanV1,
) -> ApprovedExecutionPlanV1:
    """Lossless, pure translation of an approved AutomaticExitPlanV1.

    Fails closed (AutomaticExitPlanAdapterError) on any structurally
    malformed or ambiguous input. Never recomputes quantity, price, or
    quote notional; never re-rounds; never reorders, merges, or splits
    legs; never rewrites side; never mutates the input plan.
    """
    _validate_plan_structure(plan)
    plan_reference_id = derive_automatic_exit_plan_reference_id_v1(plan)
    legs = tuple(
        ExecutionPlanLegV1(
            leg_index=leg.leg_index,
            side=leg.side,
            price=leg.limit_price,
            quantity=leg.quantity_base,
        )
        for leg in plan.legs
    )
    return ApprovedExecutionPlanV1(
        plan_source=PLAN_SOURCE_AUTOMATIC_EXIT_V1,
        plan_reference_id=plan_reference_id,
        trading_account_id=plan.trading_account_id,
        venue=plan.venue,
        market=plan.market,
        side=plan.side,
        legs=legs,
    )
