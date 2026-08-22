"""Controlled, DRY_RUN-only automatic BUY acceptance composition.

The entrypoint is deliberately bounded: source snapshot -> candidate ->
decision gate -> immutable BUY plan -> shared persisted handoff.  It never
constructs a broker/private client, resolves credentials, or consumes orders.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from typing import Any, Iterator

from src.entry_policy.automatic_buy_live_handoff_composition_v1 import (
    evaluate_and_handoff_automatic_buy_runtime_item_v1,
)
from src.entry_policy.automatic_buy_runtime_input_writer_v1 import (
    AutomaticBuyRuntimeInputSourceV1,
    write_automatic_buy_runtime_input_v1,
)
from src.entry_policy.automatic_buy_runtime_repository_v1 import build_runtime_item_v1
from src.executor.execution_handoff_v1 import (
    RUNTIME_MODE_DRY_RUN,
    ExecutionHandoffRepositoryV1,
)

EXECUTOR_MODE = RUNTIME_MODE_DRY_RUN
RUNTIME_OWNER = "gurkdb"
EXECUTOR_IDENTITY = "shared-executor-v1"
SAFETY_MARKERS = (
    "broker_private_calls=0",
    "broker_writes=0",
    "order_submission=0",
    "live_orders=0",
    "live_authority=0",
)


@dataclass(frozen=True)
class AutomaticBuyDryRunAcceptanceResultV1:
    runtime_input_id: int
    runtime_input_outcome: str
    candidate_state: str
    gate_state: str | None
    planner_state: str
    handoff_id: int | None
    plan_reference_id: str | None
    plan_content_hash: str | None
    executor_mode: str
    runtime_owner: str
    executor_identity: str
    safety_markers: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@contextmanager
def _connection_cursor_factory(conn: Any, *, commit: bool = False, database: str | None = None) -> Iterator[Any]:
    if database is not None:
        raise ValueError("DRY_RUN_ACCEPTANCE_DATABASE_OVERRIDE_FORBIDDEN")
    with conn.cursor() as cur:
        yield cur
    if commit:
        conn.commit()


def run_automatic_buy_dry_run_acceptance_v1(
    conn: Any,
    *,
    source: AutomaticBuyRuntimeInputSourceV1,
    handoff_repository: ExecutionHandoffRepositoryV1 | None = None,
) -> AutomaticBuyDryRunAcceptanceResultV1:
    """Persist one source input and, if gate-approved, its DRY_RUN handoff."""
    input_write = write_automatic_buy_runtime_input_v1(conn, source=source)
    item = build_runtime_item_v1(conn, runtime_input=input_write.runtime_input)
    repository = handoff_repository or ExecutionHandoffRepositoryV1(
        cursor_factory=lambda **kwargs: _connection_cursor_factory(conn, **kwargs),
    )
    outcome = evaluate_and_handoff_automatic_buy_runtime_item_v1(
        conn,
        item=item,
        executor_identity=EXECUTOR_IDENTITY,
        runtime_owner=RUNTIME_OWNER,
        handoff_repository=repository,
        executor_mode_override=EXECUTOR_MODE,
    )
    handoff = outcome.handoff
    if handoff is not None and handoff.executor_credential_binding_id is not None:
        raise RuntimeError("DRY_RUN_HANDOFF_CREDENTIAL_BINDING_FORBIDDEN")
    conn.commit()
    return AutomaticBuyDryRunAcceptanceResultV1(
        runtime_input_id=input_write.runtime_input.automatic_buy_runtime_input_id,
        runtime_input_outcome=input_write.outcome,
        candidate_state=outcome.runtime_outcome.candidate_state,
        gate_state=outcome.runtime_outcome.gate_state,
        planner_state=outcome.runtime_outcome.planner_state,
        handoff_id=None if handoff is None else handoff.handoff_id,
        plan_reference_id=None if handoff is None else handoff.plan_reference_id,
        plan_content_hash=None if handoff is None else handoff.plan_content_hash,
        executor_mode=EXECUTOR_MODE,
        runtime_owner=RUNTIME_OWNER,
        executor_identity=EXECUTOR_IDENTITY,
        safety_markers=SAFETY_MARKERS,
    )
