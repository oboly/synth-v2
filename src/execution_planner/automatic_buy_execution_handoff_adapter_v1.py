"""Issue #399 Phase 6: pure automatic BUY -> shared executor plan adapter.

Translates one already-approved immutable ``AutomaticBuyPlanV1`` into the
side-neutral #206 ``ApprovedExecutionPlanV1`` contract. It does not re-run
candidate logic, decision_gate, planning, rounding, credentials, LIVE
authority, kill switch, broker logic, or submission.
"""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Final

from src.execution_planner.automatic_buy_planner_v1 import AutomaticBuyPlanLegV1, AutomaticBuyPlanV1
from src.executor.execution_plan_reference_v1 import ApprovedExecutionPlanV1, ExecutionPlanLegV1

PLAN_SOURCE_AUTOMATIC_BUY_V1: Final[str] = "automatic_buy_planner_v1"
SIDE_BUY: Final[str] = "BUY"
SUPPORTED_CANDIDATE_ACTIONS: Final[frozenset[str]] = frozenset({"ENTER", "RE_ENTER"})
REQUIRED_GATE_APPROVAL_STATE: Final[str] = "APPROVED"
_PLAN_REFERENCE_ID_CONTRACT_VERSION: Final[str] = "automatic_buy_execution_handoff_adapter_v1"


class AutomaticBuyPlanAdapterError(ValueError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def _reject(condition: bool, reason_code: str) -> None:
    if condition:
        raise AutomaticBuyPlanAdapterError(reason_code)


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _decimal_text(value: Decimal) -> str:
    normalized = format(value.normalize(), "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized or "0"


def _validate_plan_structure(plan: AutomaticBuyPlanV1) -> None:
    _reject(plan.trading_account_id <= 0 or plan.asset_id <= 0, "PLAN_IDENTITY_NOT_POSITIVE")
    _reject(not all(_nonempty(v) for v in (plan.venue, plan.market)), "PLAN_IDENTITY_FIELD_EMPTY")
    _reject(plan.side != SIDE_BUY, "PLAN_SIDE_NOT_BUY")
    _reject(plan.candidate_action not in SUPPORTED_CANDIDATE_ACTIONS, "PLAN_CANDIDATE_ACTION_UNSUPPORTED")
    _reject(
        not all(_nonempty(v) for v in (
            plan.candidate_reason_code,
            plan.candidate_evidence_id,
            plan.strategy_id,
            plan.strategy_version,
            plan.setup_id,
            plan.strategy_bucket_id,
            plan.planner_version,
        )),
        "PLAN_PROVENANCE_FIELD_EMPTY",
    )
    gate = plan.gate_approval
    _reject(gate is None or gate.state != REQUIRED_GATE_APPROVAL_STATE, "PLAN_GATE_APPROVAL_NOT_APPROVED")
    _reject(gate.approved_notional_ceiling_eur <= 0, "PLAN_GATE_APPROVED_NOTIONAL_INVALID")
    _reject(plan.final_quantity_base <= 0, "PLAN_FINAL_QUANTITY_NOT_POSITIVE")
    _reject(not isinstance(plan.legs, tuple) or not plan.legs, "PLAN_LEGS_EMPTY")
    indices = tuple(leg.leg_index for leg in plan.legs)
    _reject(indices != tuple(range(1, len(plan.legs) + 1)), "PLAN_LEG_INDICES_NOT_STRICTLY_ORDERED")
    total = Decimal("0")
    for leg in plan.legs:
        _reject(leg.side != SIDE_BUY, "PLAN_LEG_SIDE_MISMATCH")
        _reject(leg.limit_price <= 0 or leg.quantity_base <= 0 or leg.quote_notional <= 0, "PLAN_LEG_VALUE_NOT_POSITIVE")
        total += leg.quantity_base
    _reject(total != plan.final_quantity_base, "PLAN_LEG_QUANTITY_SUM_MISMATCH")


def _leg_payload(leg: AutomaticBuyPlanLegV1) -> dict[str, object]:
    return {
        "leg_index": leg.leg_index,
        "side": leg.side,
        "limit_price": _decimal_text(leg.limit_price),
        "quantity_base": _decimal_text(leg.quantity_base),
        "quote_notional": _decimal_text(leg.quote_notional),
        "post_only": leg.post_only,
        "time_in_force": leg.time_in_force,
    }


def _identity_payload(plan: AutomaticBuyPlanV1) -> dict[str, object]:
    gate = plan.gate_approval
    return {
        "contract_version": _PLAN_REFERENCE_ID_CONTRACT_VERSION,
        "trading_account_id": plan.trading_account_id,
        "venue": plan.venue,
        "asset_id": plan.asset_id,
        "market": plan.market,
        "side": plan.side,
        "final_quantity_base": _decimal_text(plan.final_quantity_base),
        "candidate_action": plan.candidate_action,
        "candidate_reason_code": plan.candidate_reason_code,
        "candidate_evidence_id": plan.candidate_evidence_id,
        "strategy_id": plan.strategy_id,
        "strategy_version": plan.strategy_version,
        "setup_id": plan.setup_id,
        "strategy_bucket_id": plan.strategy_bucket_id,
        "gate_approval": {
            "state": gate.state,
            "reason_code": gate.reason_code,
            "approved_notional_ceiling_eur": _decimal_text(gate.approved_notional_ceiling_eur),
        },
        "planner_version": plan.planner_version,
        "legs": [_leg_payload(leg) for leg in plan.legs],
    }


def derive_automatic_buy_plan_reference_id_v1(plan: AutomaticBuyPlanV1) -> str:
    _validate_plan_structure(plan)
    serialized = json.dumps(_identity_payload(plan), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return f"automatic_buy_v1:{plan.trading_account_id}:{plan.candidate_evidence_id}:{digest}"


def adapt_automatic_buy_plan_to_approved_execution_plan_v1(plan: AutomaticBuyPlanV1) -> ApprovedExecutionPlanV1:
    _validate_plan_structure(plan)
    return ApprovedExecutionPlanV1(
        plan_source=PLAN_SOURCE_AUTOMATIC_BUY_V1,
        plan_reference_id=derive_automatic_buy_plan_reference_id_v1(plan),
        trading_account_id=plan.trading_account_id,
        venue=plan.venue,
        market=plan.market,
        side=plan.side,
        legs=tuple(
            ExecutionPlanLegV1(
                leg_index=leg.leg_index,
                side=leg.side,
                price=leg.limit_price,
                quantity=leg.quantity_base,
            )
            for leg in plan.legs
        ),
    )
