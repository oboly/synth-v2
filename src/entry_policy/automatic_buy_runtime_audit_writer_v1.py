"""Append-only audit writer for Issue #399 Phase 4 automatic BUY runtime."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from src.execution_planner.automatic_buy_planner_v1 import AutomaticBuyPlanV1


class AutomaticBuyIdempotencyPayloadConflictError(RuntimeError):
    pass


def _json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        return aware.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    raise TypeError(f"UNSERIALIZABLE_AUDIT_VALUE:{type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=_json_default)


def build_immutable_buy_plan_json(plan: AutomaticBuyPlanV1) -> dict[str, Any]:
    return {
        "trading_account_id": plan.trading_account_id,
        "venue": plan.venue,
        "asset_id": plan.asset_id,
        "market": plan.market,
        "side": plan.side,
        "final_quantity_base": plan.final_quantity_base,
        "legs": [
            {
                "leg_index": leg.leg_index,
                "side": leg.side,
                "limit_price": leg.limit_price,
                "quantity_base": leg.quantity_base,
                "quote_notional": leg.quote_notional,
                "post_only": leg.post_only,
                "time_in_force": leg.time_in_force,
            }
            for leg in plan.legs
        ],
        "candidate_action": plan.candidate_action,
        "candidate_reason_code": plan.candidate_reason_code,
        "candidate_evidence_id": plan.candidate_evidence_id,
        "strategy_id": plan.strategy_id,
        "strategy_version": plan.strategy_version,
        "setup_id": plan.setup_id,
        "gate_approval": {
            "state": plan.gate_approval.state,
            "reason_code": plan.gate_approval.reason_code,
            "approved_notional_ceiling_eur": plan.gate_approval.approved_notional_ceiling_eur,
        },
        "planner_version": plan.planner_version,
        "planning_ts_utc": plan.planning_ts_utc,
    }


@dataclass(frozen=True)
class AutomaticBuyAuditWriteResultV1:
    automatic_buy_evaluation_audit_id: int
    idempotency_key: str
    outcome: str  # inserted | idempotent_existing


_DECISION_FIELDS = (
    "source_evidence_json",
    "candidate_state",
    "candidate_action",
    "candidate_reason_code",
    "candidate_evidence_id",
    "gate_state",
    "gate_reason_code",
    "approved_notional_ceiling_eur",
    "strategy_bucket_reason_code",
    "protection_code",
    "protection_reason_code",
    "planner_state",
    "planner_reason_code",
    "immutable_plan_json",
)


def _decision_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {field: row.get(field) for field in _DECISION_FIELDS}


def write_automatic_buy_evaluation_audit_v1(
    conn: Any,
    *,
    idempotency_key: str,
    runtime_version: str,
    trading_account_id: int,
    venue: str,
    asset_id: int,
    market: str,
    source_evidence_json: dict[str, Any],
    candidate_state: str,
    candidate_action: str | None,
    candidate_reason_code: str,
    candidate_evidence_id: str | None,
    gate_state: str | None,
    gate_reason_code: str | None,
    approved_notional_ceiling_eur: Decimal | None,
    strategy_bucket_reason_code: str | None,
    protection_code: str | None,
    protection_reason_code: str | None,
    planner_state: str,
    planner_reason_code: str | None,
    immutable_plan_json: dict[str, Any] | None,
    evaluation_ts_utc: datetime,
    planning_ts_utc: datetime | None,
) -> AutomaticBuyAuditWriteResultV1:
    source_text = canonical_json(source_evidence_json)
    plan_text = canonical_json(immutable_plan_json) if immutable_plan_json is not None else None
    lookup_sql = """
    SELECT automatic_buy_evaluation_audit_id, source_evidence_json,
           candidate_state, candidate_action, candidate_reason_code,
           candidate_evidence_id, gate_state, gate_reason_code,
           approved_notional_ceiling_eur, strategy_bucket_reason_code,
           protection_code, protection_reason_code,
           planner_state, planner_reason_code, immutable_plan_json
    FROM automatic_buy_evaluation_audit_v1
    WHERE idempotency_key = %s
    LIMIT 1
    """
    with conn.cursor() as cur:
        cur.execute(lookup_sql, (idempotency_key,))
        row = cur.fetchone()
        existing = None if row is None else dict(row)

    new_payload = _decision_payload({
        "source_evidence_json": source_text,
        "candidate_state": candidate_state,
        "candidate_action": candidate_action,
        "candidate_reason_code": candidate_reason_code,
        "candidate_evidence_id": candidate_evidence_id,
        "gate_state": gate_state,
        "gate_reason_code": gate_reason_code,
        "approved_notional_ceiling_eur": str(approved_notional_ceiling_eur) if approved_notional_ceiling_eur is not None else None,
        "strategy_bucket_reason_code": strategy_bucket_reason_code,
        "protection_code": protection_code,
        "protection_reason_code": protection_reason_code,
        "planner_state": planner_state,
        "planner_reason_code": planner_reason_code,
        "immutable_plan_json": plan_text,
    })
    if existing is not None:
        existing_payload = _decision_payload({
            **existing,
            "approved_notional_ceiling_eur": (
                str(existing["approved_notional_ceiling_eur"])
                if existing["approved_notional_ceiling_eur"] is not None else None
            ),
        })
        if existing_payload != new_payload:
            raise AutomaticBuyIdempotencyPayloadConflictError(idempotency_key)
        return AutomaticBuyAuditWriteResultV1(
            automatic_buy_evaluation_audit_id=int(existing["automatic_buy_evaluation_audit_id"]),
            idempotency_key=idempotency_key,
            outcome="idempotent_existing",
        )

    insert_sql = """
    INSERT INTO automatic_buy_evaluation_audit_v1 (
        idempotency_key, runtime_version, trading_account_id, venue, asset_id, market,
        source_evidence_json, candidate_state, candidate_action, candidate_reason_code,
        candidate_evidence_id, gate_state, gate_reason_code, approved_notional_ceiling_eur,
        strategy_bucket_reason_code, protection_code, protection_reason_code,
        planner_state, planner_reason_code, immutable_plan_json,
        evaluation_ts_utc, planning_ts_utc
    ) VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
    )
    """
    with conn.cursor() as cur:
        cur.execute(insert_sql, (
            idempotency_key, runtime_version, trading_account_id, venue, asset_id, market,
            source_text, candidate_state, candidate_action, candidate_reason_code,
            candidate_evidence_id, gate_state, gate_reason_code, approved_notional_ceiling_eur,
            strategy_bucket_reason_code, protection_code, protection_reason_code,
            planner_state, planner_reason_code, plan_text, evaluation_ts_utc, planning_ts_utc,
        ))
        new_id = int(cur.lastrowid)
    return AutomaticBuyAuditWriteResultV1(new_id, idempotency_key, "inserted")
