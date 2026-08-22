"""Issue #471: canonical automatic BUY DRY_RUN acceptance producer.

The sole bounded composition root that carries controlled, caller-supplied
market/setup evidence through the exact canonical path:

    automatic_buy_runtime_input_writer_v1 (Issue #471, this producer's only
        creation path for automatic_buy_runtime_input_v1)
    -> build_runtime_item_v1 (Issue #474: binds decision-gate-owned account
        allocation evidence; discards every account-owned field the writer's
        placeholder row carried)
    -> evaluate_and_handoff_automatic_buy_runtime_item_v1 (candidate ->
        automatic_buy_gate_v1 -> automatic_buy_planner_v1 -> #206 shared
        executor handoff, unchanged)

``executor_mode``, ``runtime_owner``, and ``executor_identity`` are fixed
module constants, never CLI flags or caller input: this producer only ever
reaches DRY_RUN intake on the ``gurkdb``-owned ``shared-executor-v1``
identity. A LIVE account whose canonical evidence shows
``live_trading_enabled=False`` is rejected by ``automatic_buy_gate_v1``
before the planner or handoff are ever reached, exactly like every other
caller of this runtime -- this producer adds no bypass and no special case.

broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
live_authority=0
decision_gate=automatic_buy_gate_v1 (called, not bypassed)
execution_planner=automatic_buy_planner_v1 (called, not bypassed)
executor=execution_handoff_v1 (intake DRY_RUN only; no submission)
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

from src.common.db import get_db_connection
from src.entry_policy.automatic_buy_live_handoff_composition_v1 import (
    AutomaticBuyLiveHandoffCompositionError,
    evaluate_and_handoff_automatic_buy_runtime_item_v1,
)
from src.entry_policy.automatic_buy_runtime_audit_writer_v1 import (
    AutomaticBuyIdempotencyPayloadConflictError,
)
from src.entry_policy.automatic_buy_runtime_contract_v1 import AutomaticBuyRuntimeContractError
from src.entry_policy.automatic_buy_runtime_input_writer_v1 import (
    AutomaticBuySourceEvidenceV1,
    AutomaticBuyRuntimeInputWriteError,
    write_automatic_buy_runtime_input_v1,
)
from src.entry_policy.automatic_buy_runtime_repository_v1 import (
    AutomaticBuyRuntimeRepositoryError,
    build_runtime_item_v1,
)
from src.executor.execution_handoff_v1 import (
    ExecutionHandoffDeniedError,
    ExecutionHandoffIdentityConflictError,
    ExecutionHandoffRepositoryV1,
)

RUNNER_NAME: Final[str] = "run_automatic_buy_dry_run_acceptance_producer_v1"

EXECUTOR_MODE: Final[str] = "DRY_RUN"
RUNTIME_OWNER: Final[str] = "gurkdb"
EXECUTOR_IDENTITY: Final[str] = "shared-executor-v1"

SAFETY_MARKERS: Final[tuple[str, ...]] = (
    "broker_private_calls=0",
    "broker_writes=0",
    "order_submission=0",
    "live_orders=0",
    "live_authority=0",
    "decision_gate=automatic_buy_gate_v1",
    "execution_planner=automatic_buy_planner_v1",
    "executor=execution_handoff_v1(intake_dry_run_only)",
)

# Caller-controlled market/setup evidence and locating identity only.
_ALLOWED_SOURCE_KEYS: Final[frozenset[str]] = frozenset({
    "source_snapshot_key", "evaluation_ts_utc", "trading_account_id", "venue",
    "asset_id", "market", "strategy_bucket_id", "strategy_id", "strategy_version",
    "setup_id", "setup_ready", "current_price", "entry_zone_low", "entry_zone_high",
    "re_entry_zone_low", "re_entry_zone_high", "setup_evidence_id",
    "setup_observed_ts_utc", "source_provenance",
})

# Account-owned/decision-gate-owned fields (Issue #474) that this producer
# structurally never accepts from caller/operator JSON. Their presence in
# the input file is a fail-closed error, not a silently-ignored key: PR #473
# was reverted for accepting exactly these fields from operator JSON.
_FORBIDDEN_ACCOUNT_OWNED_KEYS: Final[frozenset[str]] = frozenset({
    "account_observed_ts_utc", "account_enabled", "account_mode",
    "automatic_buy_execution_enabled", "live_trading_enabled",
    "free_quote_balance_eur", "free_quote_balance_observed_ts_utc",
    "blocking_conflict", "proposed_position_amount_eur",
    "current_bucket_amount_eur", "current_open_positions",
    "current_asset_exposure_pct", "max_automatic_buy_notional_eur",
    "automatic_buy_runtime_input_id", "input_contract_version",
})

_TIMESTAMP_FIELDS: Final[frozenset[str]] = frozenset({"evaluation_ts_utc", "setup_observed_ts_utc"})
_DECIMAL_FIELDS: Final[frozenset[str]] = frozenset({
    "current_price", "entry_zone_low", "entry_zone_high",
    "re_entry_zone_low", "re_entry_zone_high",
})


class AutomaticBuySourceJsonError(ValueError):
    pass


class AutomaticBuyDryRunAcceptanceError(RuntimeError):
    pass


def source_from_json(value: dict[str, Any]) -> AutomaticBuySourceEvidenceV1:
    """Parse caller JSON into source evidence, failing closed on any
    account-owned or unrecognized key rather than silently dropping it."""
    keys = set(value)
    forbidden_present = keys & _FORBIDDEN_ACCOUNT_OWNED_KEYS
    if forbidden_present:
        raise AutomaticBuySourceJsonError(
            "FORBIDDEN_ACCOUNT_OWNED_SOURCE_FIELDS:" + ",".join(sorted(forbidden_present))
        )
    unknown = keys - _ALLOWED_SOURCE_KEYS
    if unknown:
        raise AutomaticBuySourceJsonError("UNKNOWN_SOURCE_FIELDS:" + ",".join(sorted(unknown)))
    missing = _ALLOWED_SOURCE_KEYS - keys
    if missing:
        raise AutomaticBuySourceJsonError("MISSING_SOURCE_FIELDS:" + ",".join(sorted(missing)))

    converted: dict[str, Any] = dict(value)
    for field in _TIMESTAMP_FIELDS:
        converted[field] = datetime.fromisoformat(str(converted[field]).replace("Z", "+00:00"))
    for field in _DECIMAL_FIELDS:
        if converted.get(field) is not None:
            converted[field] = Decimal(str(converted[field]))
    return AutomaticBuySourceEvidenceV1(**converted)


@dataclass(frozen=True)
class AutomaticBuyDryRunAcceptanceResultV1:
    runtime_input_id: int
    source_snapshot_key: str
    trading_account_id: int
    venue: str
    asset_id: int
    market: str
    candidate_state: str
    gate_state: str | None
    gate_reason: str | None
    planner_state: str
    planner_reason: str | None
    handoff_id: int | None
    plan_reference_id: str | None
    plan_content_hash: str | None
    executor_mode: str
    runtime_owner: str
    executor_identity: str
    executor_credential_binding_id: int | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "runtime_input_id": self.runtime_input_id,
            "source_snapshot_key": self.source_snapshot_key,
            "trading_account_id": self.trading_account_id,
            "venue": self.venue,
            "asset_id": self.asset_id,
            "market": self.market,
            "candidate_state": self.candidate_state,
            "gate_state": self.gate_state,
            "gate_reason": self.gate_reason,
            "planner_state": self.planner_state,
            "planner_reason": self.planner_reason,
            "handoff_id": self.handoff_id,
            "plan_reference_id": self.plan_reference_id,
            "plan_content_hash": self.plan_content_hash,
            "executor_mode": self.executor_mode,
            "runtime_owner": self.runtime_owner,
            "executor_identity": self.executor_identity,
            "executor_credential_binding_id": self.executor_credential_binding_id,
            "safety_markers": list(SAFETY_MARKERS),
        }


def _load_audit_reasons(conn: Any, *, idempotency_key: str) -> tuple[str | None, str | None]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT gate_reason_code, planner_reason_code FROM automatic_buy_evaluation_audit_v1 "
            "WHERE idempotency_key = %s LIMIT 1",
            (idempotency_key,),
        )
        row = cur.fetchone()
    if row is None:
        raise AutomaticBuyDryRunAcceptanceError("AUDIT_EVIDENCE_MISSING")
    return row["gate_reason_code"], row["planner_reason_code"]


def run_automatic_buy_dry_run_acceptance_producer_v1(
    conn: Any,
    *,
    source: AutomaticBuySourceEvidenceV1,
    handoff_repository: ExecutionHandoffRepositoryV1,
) -> AutomaticBuyDryRunAcceptanceResultV1:
    """Compose the exact canonical DRY_RUN acceptance path for one snapshot."""
    write_result = write_automatic_buy_runtime_input_v1(conn, source=source)
    item = build_runtime_item_v1(conn, runtime_input=write_result.runtime_input)
    handoff_outcome = evaluate_and_handoff_automatic_buy_runtime_item_v1(
        conn,
        item=item,
        executor_identity=EXECUTOR_IDENTITY,
        runtime_owner=RUNTIME_OWNER,
        handoff_repository=handoff_repository,
        executor_mode_override=EXECUTOR_MODE,
    )
    conn.commit()

    runtime_outcome = handoff_outcome.runtime_outcome
    gate_reason, planner_reason = _load_audit_reasons(conn, idempotency_key=runtime_outcome.idempotency_key)
    handoff = handoff_outcome.handoff
    return AutomaticBuyDryRunAcceptanceResultV1(
        runtime_input_id=write_result.runtime_input.automatic_buy_runtime_input_id,
        source_snapshot_key=write_result.runtime_input.source_snapshot_key,
        trading_account_id=source.trading_account_id,
        venue=source.venue,
        asset_id=source.asset_id,
        market=source.market,
        candidate_state=runtime_outcome.candidate_state,
        gate_state=runtime_outcome.gate_state,
        gate_reason=gate_reason,
        planner_state=runtime_outcome.planner_state,
        planner_reason=planner_reason,
        handoff_id=handoff.handoff_id if handoff is not None else None,
        plan_reference_id=handoff.plan_reference_id if handoff is not None else None,
        plan_content_hash=handoff.plan_content_hash if handoff is not None else None,
        executor_mode=EXECUTOR_MODE,
        runtime_owner=RUNTIME_OWNER,
        executor_identity=EXECUTOR_IDENTITY,
        executor_credential_binding_id=(
            handoff.executor_credential_binding_id if handoff is not None else None
        ),
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Controlled automatic BUY DRY_RUN acceptance producer. Accepts only "
            "market/setup source evidence; executor_mode/runtime_owner/"
            "executor_identity are fixed and cannot be overridden."
        )
    )
    parser.add_argument("--input-json", required=True, type=Path)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    started_ts = datetime.now(UTC)
    print(
        f"STARTED runner={RUNNER_NAME} executor_mode={EXECUTOR_MODE} "
        f"runtime_owner={RUNTIME_OWNER} executor_identity={EXECUTOR_IDENTITY} "
        f"started_ts_utc={started_ts.isoformat()}",
        flush=True,
    )
    print(" ".join(SAFETY_MARKERS), flush=True)

    try:
        payload = json.loads(args.input_json.read_text())
        source = source_from_json(payload)
    except (OSError, json.JSONDecodeError, AutomaticBuySourceJsonError, TypeError, ValueError) as exc:
        print(f"FAILED runner={RUNNER_NAME} result=invalid_input detail={exc}", file=sys.stderr, flush=True)
        return 1

    try:
        conn = get_db_connection()
    except Exception as exc:
        print(f"FAILED runner={RUNNER_NAME} result=db_unavailable detail={exc}", file=sys.stderr, flush=True)
        return 1

    try:
        handoff_repository = ExecutionHandoffRepositoryV1()
        result = run_automatic_buy_dry_run_acceptance_producer_v1(
            conn, source=source, handoff_repository=handoff_repository,
        )
    except (
        AutomaticBuyRuntimeInputWriteError,
        AutomaticBuyRuntimeRepositoryError,
        AutomaticBuyRuntimeContractError,
        AutomaticBuyIdempotencyPayloadConflictError,
        AutomaticBuyLiveHandoffCompositionError,
        ExecutionHandoffDeniedError,
        ExecutionHandoffIdentityConflictError,
        AutomaticBuyDryRunAcceptanceError,
    ) as exc:
        conn.rollback()
        conn.close()
        print(f"FAILED runner={RUNNER_NAME} result=acceptance_failed detail={exc}", file=sys.stderr, flush=True)
        return 1
    except Exception as exc:
        conn.rollback()
        conn.close()
        print(f"FAILED runner={RUNNER_NAME} result=unexpected_error detail={exc}", file=sys.stderr, flush=True)
        return 1
    conn.close()

    print(json.dumps(result.as_dict(), sort_keys=True, default=str), flush=True)
    finished_ts = datetime.now(UTC)
    print(
        f"FINISHED runner={RUNNER_NAME} result=ok "
        f"elapsed_seconds={(finished_ts - started_ts).total_seconds():.3f} "
        f"candidate_state={result.candidate_state} gate_state={result.gate_state} "
        f"planner_state={result.planner_state} handoff_id={result.handoff_id}",
        flush=True,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
