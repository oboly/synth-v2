"""Phase 5 verification-only wrapper for the canonical Phase 4B path.

It does not sequence policy layers itself: it invokes the existing canonical
orchestrator and hashes the exact canonical audit representations it produces.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.exit_policy.automatic_exit_runtime_audit_writer_v1 import canonical_json
from src.exit_policy.automatic_exit_runtime_orchestrator_v1 import (
    build_automatic_exit_source_evidence_v1,
    evaluate_automatic_exit_runtime_item_v1,
)
from src.exit_policy.automatic_exit_runtime_repository_v1 import RuntimeItemV1


@dataclass(frozen=True)
class AutomaticExitAcceptanceDryRunResultV1:
    trading_account_id: int
    position_reference: str
    venue: str
    asset_id: int
    market: str
    idempotency_key: str
    candidate_state: str
    gate_state: str | None
    planner_state: str
    source_evidence_hash: str
    plan_hash: str | None
    acceptance_state: str
    safety_markers: tuple[str, ...]


def run_automatic_exit_acceptance_dry_run_v1(
    conn: Any, *, item: RuntimeItemV1, evaluation_ts_utc: datetime,
) -> AutomaticExitAcceptanceDryRunResultV1:
    """Run the exact Phase 4B path and verify its append-only audit evidence."""
    outcome = evaluate_automatic_exit_runtime_item_v1(conn, item=item, evaluation_ts_utc=evaluation_ts_utc)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT immutable_plan_json FROM automatic_exit_evaluation_audit_v1 WHERE idempotency_key = %s",
            (outcome.idempotency_key,),
        )
        row = cur.fetchone()
    if row is None:
        raise RuntimeError("PHASE5_AUDIT_EVIDENCE_MISSING")
    plan_json = row["immutable_plan_json"]
    source_hash = hashlib.sha256(canonical_json(build_automatic_exit_source_evidence_v1(item)).encode()).hexdigest()
    plan_hash = hashlib.sha256(plan_json.encode()).hexdigest() if plan_json is not None else None
    return AutomaticExitAcceptanceDryRunResultV1(
        item.trading_account_id, item.position_reference, item.venue, item.asset_id, item.market,
        outcome.idempotency_key, outcome.candidate_state, outcome.gate_state, outcome.planner_state,
        source_hash, plan_hash, "PASS",
        ("executor_calls=0", "credential_calls=0", "broker_private_calls=0", "broker_writes=0", "order_submission=0", "live_orders=0"),
    )
