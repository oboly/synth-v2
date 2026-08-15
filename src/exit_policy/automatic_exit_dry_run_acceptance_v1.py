"""Phase 5 automatic-exit decision/planning acceptance, terminal at staging.

``AUTOMATIC_EXIT_ACCEPTANCE_DRY_RUN`` verifies the Phase 4B repository /
candidate / gate / planner chain without traversing any executor boundary.
It has no broker, credential, order, or LIVE authority.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

from src.exit_policy.automatic_exit_runtime_audit_writer_v1 import canonical_json
from src.exit_policy.automatic_exit_runtime_contract_v1 import AutomaticExitProfileV1
from src.exit_policy.automatic_exit_runtime_orchestrator_v1 import evaluate_automatic_exit_runtime_item_v1
from src.exit_policy.automatic_exit_runtime_repository_v1 import (
    RuntimeItemV1,
    build_runtime_item_v1,
    load_eligible_trading_accounts,
    load_latest_complete_account_state_bundle,
    load_positive_positions,
)
from src.market_rules.venue_execution_constraints_v1 import VenueExecutionConstraints


ACCEPTANCE_MODE_DB_CURRENT: Final[str] = "DB_CURRENT"
ACCEPTANCE_MODE_REPLAY: Final[str] = "REPLAY"
ACCEPTANCE_VERSION: Final[str] = "automatic_exit_acceptance_dry_run_v1"
SAFETY_MARKERS: Final[dict[str, int]] = {
    "broker_private_calls_by_phase5": 0,
    "broker_writes": 0,
    "order_submission": 0,
    "live_orders": 0,
    "executor_calls": 0,
    "credential_resolution_calls": 0,
}


class AutomaticExitDryRunAcceptanceError(RuntimeError):
    pass


@dataclass(frozen=True)
class AutomaticExitDryRunAcceptanceInputV1:
    """Immutable value-level replay input; separate from Phase 4B audit identity."""

    evaluation_ts_utc: datetime
    runtime_item_json: dict[str, Any]


@dataclass(frozen=True)
class AutomaticExitDryRunAcceptanceResultV1:
    mode: str
    idempotency_key: str
    trading_account_id: int
    position_reference: str
    venue: str
    asset_id: int
    market: str
    candidate_state: str
    candidate_action: str | None
    candidate_reason_code: str
    gate_state: str | None
    gate_reason_code: str | None
    planner_state: str
    planner_reason_code: str | None
    approved_fraction_candidate: str | None
    approved_quantity_ceiling_base: str | None
    source_evidence_hash: str
    immutable_plan_hash: str | None
    replay_input: AutomaticExitDryRunAcceptanceInputV1
    safety_markers: dict[str, int]


def _sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _require_non_live_environment() -> None:
    for name in ("SYNTH_BROKER_WRITE_PERMISSION", "SYNTH_LIVE_EXECUTION_PERMISSION"):
        if os.environ.get(name) == "GRANTED":
            raise AutomaticExitDryRunAcceptanceError(f"LIVE_AUTHORITY_FORBIDDEN:{name}")


def _item_json(item: RuntimeItemV1) -> dict[str, Any]:
    profile = item.exit_profile
    constraints = item.venue_constraints
    return {
        "trading_account_id": item.trading_account_id, "account_code": item.account_code,
        "position_reference": item.position_reference, "venue": item.venue, "asset_id": item.asset_id,
        "market": item.market, "symbol": item.symbol, "held_quantity_base": item.held_quantity_base,
        "free_quantity_base": item.free_quantity_base, "current_price": item.current_price,
        "account_enabled": item.account_enabled, "account_mode": item.account_mode,
        "live_trading_enabled": item.live_trading_enabled,
        "automatic_exit_execution_enabled": item.automatic_exit_execution_enabled,
        "blocking_conflict": item.blocking_conflict,
        "account_state_observed_ts_utc": item.account_state_observed_ts_utc,
        "market_price_observed_ts_utc": item.market_price_observed_ts_utc,
        "exit_profile": profile.__dict__, "venue_constraints": constraints.__dict__,
        "account_state_snapshot_run_id": item.account_state_snapshot_run_id,
        "position_snapshot_id": item.position_snapshot_id, "balance_snapshot_id": item.balance_snapshot_id,
        "open_order_snapshot_run_id": item.open_order_snapshot_run_id,
        "market_price_snapshot_id": item.market_price_snapshot_id,
        "automatic_exit_permission_id": item.automatic_exit_permission_id,
        "venue_constraint_id": item.venue_constraint_id,
    }


def _item_from_json(value: dict[str, Any]) -> RuntimeItemV1:
    profile = dict(value["exit_profile"])
    constraints = dict(value["venue_constraints"])
    for name in ("active_target_price", "invalidation_price"):
        if profile[name] is not None:
            profile[name] = Decimal(str(profile[name]))
    for name in ("observed_ts_utc", "effective_from_ts_utc", "effective_until_ts_utc"):
        if profile[name] is not None and isinstance(profile[name], str):
            profile[name] = datetime.fromisoformat(profile[name].replace("Z", "+00:00"))
    for name in ("tick_size", "qty_step_size", "min_base_quantity", "min_quote_notional"):
        constraints[name] = Decimal(str(constraints[name]))
    constraints["supported_order_types"] = tuple(constraints["supported_order_types"])
    constraints["supported_time_in_force"] = tuple(constraints["supported_time_in_force"])
    if isinstance(constraints["metadata_synced_ts_utc"], str):
        constraints["metadata_synced_ts_utc"] = datetime.fromisoformat(constraints["metadata_synced_ts_utc"].replace("Z", "+00:00"))
    item = dict(value)
    item["exit_profile"] = AutomaticExitProfileV1(**profile)
    item["venue_constraints"] = VenueExecutionConstraints(**constraints)
    for name in ("held_quantity_base", "free_quantity_base", "current_price"):
        item[name] = Decimal(str(item[name]))
    for name in ("account_state_observed_ts_utc", "market_price_observed_ts_utc"):
        if isinstance(item[name], str):
            item[name] = datetime.fromisoformat(item[name].replace("Z", "+00:00"))
    return RuntimeItemV1(**item)


def build_replay_input_v1(*, item: RuntimeItemV1, evaluation_ts_utc: datetime) -> AutomaticExitDryRunAcceptanceInputV1:
    return AutomaticExitDryRunAcceptanceInputV1(evaluation_ts_utc=evaluation_ts_utc, runtime_item_json=_item_json(item))


def _audit_row(conn: Any, idempotency_key: str) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM automatic_exit_evaluation_audit_v1 WHERE idempotency_key = %s", (idempotency_key,))
        row = cur.fetchone()
    if row is None:
        raise AutomaticExitDryRunAcceptanceError("ACCEPTANCE_AUDIT_ROW_MISSING")
    return dict(row)


def run_automatic_exit_acceptance_v1(
    conn: Any, *, mode: str, replay_input: AutomaticExitDryRunAcceptanceInputV1,
) -> AutomaticExitDryRunAcceptanceResultV1:
    """Run the exact Phase 4B orchestrator from frozen value-level evidence."""
    _require_non_live_environment()
    if mode not in {ACCEPTANCE_MODE_DB_CURRENT, ACCEPTANCE_MODE_REPLAY}:
        raise AutomaticExitDryRunAcceptanceError("ACCEPTANCE_MODE_INVALID")
    item = _item_from_json(replay_input.runtime_item_json)
    outcome = evaluate_automatic_exit_runtime_item_v1(conn, item=item, evaluation_ts_utc=replay_input.evaluation_ts_utc)
    row = _audit_row(conn, outcome.idempotency_key)
    source_evidence = json.loads(row["source_evidence_json"])
    immutable_plan = json.loads(row["immutable_plan_json"]) if row["immutable_plan_json"] else None
    return AutomaticExitDryRunAcceptanceResultV1(
        mode=mode, idempotency_key=outcome.idempotency_key, trading_account_id=item.trading_account_id,
        position_reference=item.position_reference, venue=item.venue, asset_id=item.asset_id, market=item.market,
        candidate_state=row["candidate_state"], candidate_action=row["candidate_action"],
        candidate_reason_code=row["candidate_reason_code"], gate_state=row["gate_state"],
        gate_reason_code=row["gate_reason_code"], planner_state=row["planner_state"],
        planner_reason_code=row["planner_reason_code"],
        approved_fraction_candidate=(str(row["approved_fraction_candidate"]) if row["approved_fraction_candidate"] is not None else None),
        approved_quantity_ceiling_base=(str(row["approved_quantity_ceiling_base"]) if row["approved_quantity_ceiling_base"] is not None else None),
        source_evidence_hash=_sha256(source_evidence), immutable_plan_hash=(_sha256(immutable_plan) if immutable_plan is not None else None),
        replay_input=replay_input, safety_markers=dict(SAFETY_MARKERS),
    )


def run_db_current_acceptance_v1(conn: Any, *, trading_account_id: int, venue: str, evaluation_ts_utc: datetime) -> AutomaticExitDryRunAcceptanceResultV1:
    """Load one exact current persisted item, then use the same acceptance path."""
    accounts = [a for a in load_eligible_trading_accounts(conn, venue=venue) if a.trading_account_id == trading_account_id]
    if len(accounts) != 1:
        raise AutomaticExitDryRunAcceptanceError("DB_CURRENT_ACCOUNT_NOT_ELIGIBLE")
    bundle = load_latest_complete_account_state_bundle(conn, trading_account_id=trading_account_id, venue=venue, now=evaluation_ts_utc)
    positions = load_positive_positions(conn, bundle=bundle)
    if len(positions) != 1:
        raise AutomaticExitDryRunAcceptanceError("DB_CURRENT_POSITION_AMBIGUOUS")
    item = build_runtime_item_v1(conn, account=accounts[0], bundle=bundle, position=positions[0], now=evaluation_ts_utc)
    return run_automatic_exit_acceptance_v1(
        conn, mode=ACCEPTANCE_MODE_DB_CURRENT,
        replay_input=build_replay_input_v1(item=item, evaluation_ts_utc=evaluation_ts_utc),
    )
