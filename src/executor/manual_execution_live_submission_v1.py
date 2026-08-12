"""
manual_execution_live_submission_v1 — the single LIVE submission entrypoint
combining both required LIVE gates before ever reaching the broker boundary
(Issue #369 review follow-up).

Layer: executor. This is the only place that composes:

    1. persisted LIVE authority (src.executor.manual_execution_live_authority_v1)
       — the canonical, handoff-bound permission; absent by default.
    2. runtime activation env gate (src.executor.manual_live_authorization_v1)
       — an additional same-process explicit gate; absent by default.
    3. the #206 credential chain (src.executor.manual_execution_bitvavo_order_adapter_v1)
    4. the one crash-safe orchestrator (src.executor.manual_execution_submission_orchestrator_v1)
       run against the real DB-backed submission-leg repository.

Both (1) and (2) are independently required; neither is inferred from the
other, and neither is inferred from handoff.executor_mode (which is always
DRY_RUN/PAPER — #206 intake never allows anything else). A DRY_RUN/PAPER
handoff therefore can never reach the broker merely because the env gate is
set: this module denies first on missing persisted authority.

broker_private_calls=1 when actually invoked (this is the live lane)
broker_writes=1 when place_order is actually invoked
order_submission=1 when place_order is actually invoked
"""
from __future__ import annotations

from typing import Any

from src.execution_planner.manual_execution_plan_snapshot_v1 import ManualExecutionPlanSnapshot
from src.executor.manual_execution_bitvavo_order_adapter_v1 import (
    LiveBitvavoOrderAdapter,
    build_live_bitvavo_client,
)
from src.executor.manual_execution_handoff_v1 import ManualExecutionExecutorHandoff
from src.executor.manual_execution_live_authority_v1 import ManualExecutionLiveAuthorityRepository
from src.executor.manual_execution_submission_leg_v1 import ManualExecutionSubmissionLegRepository
from src.executor.manual_execution_submission_orchestrator_v1 import (
    LadderSubmissionResult,
    submit_manual_sell_ladder,
)
from src.executor.manual_live_authorization_v1 import require_manual_live_authorization


def submit_manual_sell_ladder_live(
    *,
    handoff: ManualExecutionExecutorHandoff,
    plan_snapshot: ManualExecutionPlanSnapshot,
    operator_id: int,
    conn: Any,
    master_key_bytes: bytes,
    cred_repo_factory: Any,
    live_authority_repository: ManualExecutionLiveAuthorityRepository | None = None,
    submission_leg_repository: ManualExecutionSubmissionLegRepository | None = None,
) -> LadderSubmissionResult:
    """Deny-by-default LIVE submission. Raises (never silently downgrades)
    unless BOTH persisted authority and the env activation gate are
    present, in that order, before any credential decryption or broker
    call. Always uses the real DB-backed submission-leg repository — this
    function is never used for dry-run rehearsal."""
    if handoff.handoff_id is None:
        raise ValueError("handoff must be persisted")

    authority_repo = live_authority_repository or ManualExecutionLiveAuthorityRepository()
    authority_repo.require_matching(handoff)

    require_manual_live_authorization(handoff_id=handoff.handoff_id)

    client = build_live_bitvavo_client(
        conn=conn,
        trading_account_id=handoff.trading_account_id,
        venue=handoff.venue,
        executor_identity=handoff.executor_identity,
        runtime_owner=handoff.runtime_owner,
        master_key_bytes=master_key_bytes,
        cred_repo_factory=cred_repo_factory,
    )
    adapter = LiveBitvavoOrderAdapter(client=client)

    return submit_manual_sell_ladder(
        handoff=handoff,
        plan_snapshot=plan_snapshot,
        operator_id=operator_id,
        adapter=adapter,
        submission_leg_repository=submission_leg_repository or ManualExecutionSubmissionLegRepository(),
    )
