"""Issue #399 Phase 5 verification-only DRY_RUN/PAPER acceptance seam.

Exercises the exact merged Phase 4 pre-broker path and produces a typed
handoff preview only when that path staged an AutomaticBuyPlanV1. The preview
contains the exact in-memory plan returned by the canonical runtime
orchestrator; persisted JSON is verification evidence only and is never
reconstructed into execution intent.

executor_calls=0
credential_calls=0
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Final

from src.entry_policy.automatic_buy_runtime_audit_writer_v1 import (
    build_immutable_buy_plan_json,
    canonical_json,
)
from src.entry_policy.automatic_buy_runtime_orchestrator_v1 import (
    PLANNER_STATE_STAGED,
    AutomaticBuyRuntimeItemOutcomeV1,
    build_automatic_buy_source_evidence_v1,
    evaluate_automatic_buy_runtime_item_v1,
)
from src.entry_policy.automatic_buy_runtime_repository_v1 import RuntimeItemV1
from src.execution_planner.automatic_buy_planner_v1 import AutomaticBuyPlanV1


ACCEPTANCE_MODE: Final[str] = "PAPER_DRY_RUN"
ACCEPTANCE_STATE_PASS: Final[str] = "PASS"

SAFETY_MARKERS: Final[tuple[str, ...]] = (
    "executor_calls=0",
    "credential_calls=0",
    "broker_private_calls=0",
    "broker_writes=0",
    "order_submission=0",
    "live_orders=0",
    "live_authority=0",
)


class AutomaticBuyAcceptanceDryRunError(RuntimeError):
    pass


@dataclass(frozen=True)
class AutomaticBuyHandoffPreviewV1:
    """Verification-only future handoff preview; never executor input itself."""

    mode: str
    trading_account_id: int
    venue: str
    asset_id: int
    market: str
    idempotency_key: str
    plan: AutomaticBuyPlanV1
    plan_hash: str


@dataclass(frozen=True)
class AutomaticBuyAcceptanceDryRunResultV1:
    trading_account_id: int
    venue: str
    asset_id: int
    market: str
    idempotency_key: str
    candidate_state: str
    gate_state: str | None
    planner_state: str
    audit_outcome: str
    source_evidence_hash: str
    persisted_plan_hash: str | None
    acceptance_state: str
    handoff_preview: AutomaticBuyHandoffPreviewV1 | None
    safety_markers: tuple[str, ...]


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _preview_from_outcome(
    *,
    item: RuntimeItemV1,
    outcome: AutomaticBuyRuntimeItemOutcomeV1,
    persisted_plan_json: str | None,
) -> AutomaticBuyHandoffPreviewV1 | None:
    """Return a preview only for the exact staged typed plan from Phase 4."""
    if outcome.planner_state != PLANNER_STATE_STAGED:
        if outcome.plan is not None or persisted_plan_json is not None:
            raise AutomaticBuyAcceptanceDryRunError("NON_STAGED_OUTCOME_HAS_PLAN_EVIDENCE")
        return None

    if item.runtime_input.account_mode != "paper":
        raise AutomaticBuyAcceptanceDryRunError("PHASE5_NON_PAPER_ACCOUNT_FORBIDDEN")
    if outcome.plan is None:
        raise AutomaticBuyAcceptanceDryRunError("PHASE5_TYPED_PLAN_MISSING")
    if persisted_plan_json is None:
        raise AutomaticBuyAcceptanceDryRunError("PHASE5_PERSISTED_PLAN_MISSING")

    typed_plan_json = canonical_json(build_immutable_buy_plan_json(outcome.plan))
    if typed_plan_json != persisted_plan_json:
        raise AutomaticBuyAcceptanceDryRunError("PHASE5_TYPED_PLAN_AUDIT_MISMATCH")

    return AutomaticBuyHandoffPreviewV1(
        mode=ACCEPTANCE_MODE,
        trading_account_id=outcome.plan.trading_account_id,
        venue=outcome.plan.venue,
        asset_id=outcome.plan.asset_id,
        market=outcome.plan.market,
        idempotency_key=outcome.idempotency_key,
        plan=outcome.plan,
        plan_hash=_sha256_text(persisted_plan_json),
    )


def run_automatic_buy_acceptance_dry_run_v1(
    conn: Any,
    *,
    item: RuntimeItemV1,
) -> AutomaticBuyAcceptanceDryRunResultV1:
    """Run the exact Phase 4 path and verify its persisted evidence/preview."""
    if item.runtime_input.account_mode != "paper":
        raise AutomaticBuyAcceptanceDryRunError("PHASE5_NON_PAPER_ACCOUNT_FORBIDDEN")

    outcome = evaluate_automatic_buy_runtime_item_v1(conn, item=item)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT source_evidence_json, immutable_plan_json, planner_state
            FROM automatic_buy_evaluation_audit_v1
            WHERE idempotency_key = %s
            LIMIT 1
            """,
            (outcome.idempotency_key,),
        )
        row = cur.fetchone()
    if row is None:
        raise AutomaticBuyAcceptanceDryRunError("PHASE5_AUDIT_EVIDENCE_MISSING")

    persisted_source_json = row["source_evidence_json"]
    persisted_plan_json = row["immutable_plan_json"]
    if row["planner_state"] != outcome.planner_state:
        raise AutomaticBuyAcceptanceDryRunError("PHASE5_PLANNER_STATE_AUDIT_MISMATCH")

    expected_source_json = canonical_json(build_automatic_buy_source_evidence_v1(item))
    if persisted_source_json != expected_source_json:
        raise AutomaticBuyAcceptanceDryRunError("PHASE5_SOURCE_EVIDENCE_MISMATCH")

    preview = _preview_from_outcome(
        item=item,
        outcome=outcome,
        persisted_plan_json=persisted_plan_json,
    )

    runtime_input = item.runtime_input
    return AutomaticBuyAcceptanceDryRunResultV1(
        trading_account_id=runtime_input.trading_account_id,
        venue=runtime_input.venue,
        asset_id=runtime_input.asset_id,
        market=runtime_input.market,
        idempotency_key=outcome.idempotency_key,
        candidate_state=outcome.candidate_state,
        gate_state=outcome.gate_state,
        planner_state=outcome.planner_state,
        audit_outcome=outcome.audit_outcome,
        source_evidence_hash=_sha256_text(persisted_source_json),
        persisted_plan_hash=(
            _sha256_text(persisted_plan_json) if persisted_plan_json is not None else None
        ),
        acceptance_state=ACCEPTANCE_STATE_PASS,
        handoff_preview=preview,
        safety_markers=SAFETY_MARKERS,
    )
