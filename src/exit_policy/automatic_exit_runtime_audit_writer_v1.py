"""Phase 4B append-only audit writer for automatic_exit_evaluation_audit_v1.

Deterministic canonical JSON, idempotent insert on idempotency_key, and a
fail-closed conflict check when the same key would record a different
decision outcome. Historical rows are never updated.

broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from src.execution_planner.automatic_exit_planner_v1 import AutomaticExitPlanV1


class IdempotencyPayloadConflictError(RuntimeError):
    """Same idempotency_key, but a different recorded decision outcome."""


def _json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        return aware.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    raise TypeError(f"UNSERIALIZABLE_AUDIT_VALUE:{type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=_json_default)


def build_immutable_plan_json(plan: AutomaticExitPlanV1) -> dict[str, Any]:
    return {
        "trading_account_id": plan.trading_account_id,
        "position_reference": plan.position_reference,
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
        "exit_profile_id": plan.exit_profile_id,
        "exit_profile_version": plan.exit_profile_version,
        "gate_approval": {
            "state": plan.gate_approval.state,
            "reason_code": plan.gate_approval.reason_code,
            "approved_fraction_candidate": plan.gate_approval.approved_fraction_candidate,
            "approved_quantity_ceiling_base": plan.gate_approval.approved_quantity_ceiling_base,
        },
        "planner_version": plan.planner_version,
        "planning_ts_utc": plan.planning_ts_utc,
    }


@dataclass(frozen=True)
class AuditWriteResultV1:
    automatic_exit_evaluation_audit_id: int
    idempotency_key: str
    outcome: str  # "inserted" | "idempotent_existing"


# Fields that must match for a duplicate idempotency_key to be considered the
# same recorded outcome. Deliberately excludes evaluation_ts_utc/
# planning_ts_utc (wall-clock capture time legitimately differs between
# reruns of identical persisted evidence) and runtime_version alone (already
# implied by source_evidence_json; what matters is whether the *decision*
# changed). A mismatch here means the same evidence identity now produces a
# different decision -- almost always a runtime logic change -- which must
# fail closed rather than silently coexist with the earlier row.
_DECISION_COMPARISON_FIELDS = (
    "source_evidence_json",
    "candidate_state",
    "candidate_action",
    "candidate_reason_code",
    "candidate_evidence_id",
    "exit_profile_id",
    "exit_profile_version",
    "gate_state",
    "gate_reason_code",
    "approved_fraction_candidate",
    "approved_quantity_ceiling_base",
    "planner_state",
    "planner_reason_code",
    "immutable_plan_json",
)


def _decision_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {field: row.get(field) for field in _DECISION_COMPARISON_FIELDS}


def write_automatic_exit_evaluation_audit_v1(
    conn: Any,
    *,
    idempotency_key: str,
    runtime_version: str,
    trading_account_id: int,
    position_reference: str,
    venue: str,
    asset_id: int,
    market: str,
    source_evidence_json: dict[str, Any],
    candidate_state: str,
    candidate_action: str | None,
    candidate_reason_code: str,
    candidate_evidence_id: str | None,
    exit_profile_id: str | None,
    exit_profile_version: str | None,
    gate_state: str | None,
    gate_reason_code: str | None,
    approved_fraction_candidate: Decimal | None,
    approved_quantity_ceiling_base: Decimal | None,
    planner_state: str,
    planner_reason_code: str | None,
    immutable_plan_json: dict[str, Any] | None,
    evaluation_ts_utc: datetime,
    planning_ts_utc: datetime | None,
) -> AuditWriteResultV1:
    """Append one audit row, or confirm an existing row records the same decision."""
    source_evidence_text = canonical_json(source_evidence_json)
    immutable_plan_text = canonical_json(immutable_plan_json) if immutable_plan_json is not None else None

    lookup_sql = """
    SELECT automatic_exit_evaluation_audit_id, source_evidence_json, candidate_state,
           candidate_action, candidate_reason_code, candidate_evidence_id,
           exit_profile_id, exit_profile_version, gate_state, gate_reason_code,
           approved_fraction_candidate, approved_quantity_ceiling_base,
           planner_state, planner_reason_code, immutable_plan_json
    FROM automatic_exit_evaluation_audit_v1
    WHERE idempotency_key = %s
    LIMIT 1
    """
    with conn.cursor() as cur:
        cur.execute(lookup_sql, (idempotency_key,))
        row = cur.fetchone()
        existing = None if row is None else dict(row)

    new_payload = _decision_payload({
        "source_evidence_json": source_evidence_text,
        "candidate_state": candidate_state,
        "candidate_action": candidate_action,
        "candidate_reason_code": candidate_reason_code,
        "candidate_evidence_id": candidate_evidence_id,
        "exit_profile_id": exit_profile_id,
        "exit_profile_version": exit_profile_version,
        "gate_state": gate_state,
        "gate_reason_code": gate_reason_code,
        "approved_fraction_candidate": (str(approved_fraction_candidate) if approved_fraction_candidate is not None else None),
        "approved_quantity_ceiling_base": (str(approved_quantity_ceiling_base) if approved_quantity_ceiling_base is not None else None),
        "planner_state": planner_state,
        "planner_reason_code": planner_reason_code,
        "immutable_plan_json": immutable_plan_text,
    })

    if existing is not None:
        existing_payload = _decision_payload({
            "source_evidence_json": existing["source_evidence_json"],
            "candidate_state": existing["candidate_state"],
            "candidate_action": existing["candidate_action"],
            "candidate_reason_code": existing["candidate_reason_code"],
            "candidate_evidence_id": existing["candidate_evidence_id"],
            "exit_profile_id": existing["exit_profile_id"],
            "exit_profile_version": existing["exit_profile_version"],
            "gate_state": existing["gate_state"],
            "gate_reason_code": existing["gate_reason_code"],
            "approved_fraction_candidate": (
                str(existing["approved_fraction_candidate"]) if existing["approved_fraction_candidate"] is not None else None
            ),
            "approved_quantity_ceiling_base": (
                str(existing["approved_quantity_ceiling_base"]) if existing["approved_quantity_ceiling_base"] is not None else None
            ),
            "planner_state": existing["planner_state"],
            "planner_reason_code": existing["planner_reason_code"],
            "immutable_plan_json": existing["immutable_plan_json"],
        })
        if existing_payload != new_payload:
            raise IdempotencyPayloadConflictError(idempotency_key)
        return AuditWriteResultV1(
            automatic_exit_evaluation_audit_id=int(existing["automatic_exit_evaluation_audit_id"]),
            idempotency_key=idempotency_key,
            outcome="idempotent_existing",
        )

    insert_sql = """
    INSERT INTO automatic_exit_evaluation_audit_v1 (
        idempotency_key, runtime_version, trading_account_id, position_reference,
        venue, asset_id, market, source_evidence_json,
        candidate_state, candidate_action, candidate_reason_code, candidate_evidence_id,
        exit_profile_id, exit_profile_version,
        gate_state, gate_reason_code, approved_fraction_candidate, approved_quantity_ceiling_base,
        planner_state, planner_reason_code, immutable_plan_json,
        evaluation_ts_utc, planning_ts_utc
    ) VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
    )
    """
    with conn.cursor() as cur:
        cur.execute(
            insert_sql,
            (
                idempotency_key, runtime_version, trading_account_id, position_reference,
                venue, asset_id, market, source_evidence_text,
                candidate_state, candidate_action, candidate_reason_code, candidate_evidence_id,
                exit_profile_id, exit_profile_version,
                gate_state, gate_reason_code, approved_fraction_candidate, approved_quantity_ceiling_base,
                planner_state, planner_reason_code, immutable_plan_text,
                evaluation_ts_utc, planning_ts_utc,
            ),
        )
        new_id = int(cur.lastrowid)
    return AuditWriteResultV1(
        automatic_exit_evaluation_audit_id=new_id, idempotency_key=idempotency_key, outcome="inserted",
    )
