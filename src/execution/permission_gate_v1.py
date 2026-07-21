from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Mapping

from src.common.db import db_cursor
from src.execution.bitvavo_client import (
    BROKER_WRITE_PERMISSION_ENV,
    BROKER_WRITE_PERMISSION_GRANTED_VALUE,
)


LIVE_EXECUTION_PERMISSION_ENV = "SYNTH_LIVE_EXECUTION_PERMISSION"
LIVE_EXECUTION_PERMISSION_GRANTED_VALUE = "I_UNDERSTAND_THIS_ENABLES_LIVE_EXECUTION"

ALLOWED_DECISION_STATE = "EXECUTION_ALLOWED"
ALLOWED_PERMISSION_STATE = "EXECUTION_PERMITTED"
ACTIVE_EVIDENCE_STATE = "ACTIVE"
LIVE_ACTIONABLE_PLAN_STATES = frozenset(
    {"IDLE", "PLACED", "MONITOR_QUEUE", "REPRICE_PENDING"}
)

INTENT_BY_DESIRED_ACTION = {
    "SPREAD_CAPTURE_PASSIVE": "PLACE_PASSIVE_LIMIT",
    "ENTER": "PLACE_PASSIVE_LIMIT",
    "ENTER_LONG": "PLACE_PASSIVE_LIMIT",
}


@dataclass(frozen=True)
class TradingAccountState:
    trading_account_id: int
    venue: str
    enabled: bool
    live_trading_enabled: bool


@dataclass(frozen=True)
class PermissionEvidence:
    execution_permission_evidence_id: int
    execution_plan_id: int
    trading_account_id: int
    venue: str
    asset_id: int
    market: str
    execution_intent: str
    action_type: str
    requested_side: str | None
    permission_state: str
    decision_state: str
    evidence_state: str
    valid_until_ts_utc: datetime | None
    revoked_ts_utc: datetime | None
    superseded_by_evidence_id: int | None


class LiveExecutionPermissionError(PermissionError):
    pass


class ExecutionPermissionRepository:
    def fetch_account_state(self, trading_account_id: int) -> TradingAccountState | None:
        sql = """
        SELECT
            trading_account_id,
            venue,
            enabled,
            live_trading_enabled
        FROM trading_account
        WHERE trading_account_id = %s
        LIMIT 1
        """

        with db_cursor(commit=False) as (_conn, cur):
            cur.execute(sql, (trading_account_id,))
            row = cur.fetchone()

        if not row:
            return None

        return TradingAccountState(
            trading_account_id=int(row["trading_account_id"]),
            venue=str(row["venue"]),
            enabled=bool(row["enabled"]),
            live_trading_enabled=bool(row["live_trading_enabled"]),
        )

    def fetch_permission_evidence(self, execution_plan_id: int) -> list[PermissionEvidence]:
        sql = """
        SELECT
            execution_permission_evidence_id,
            execution_plan_id,
            trading_account_id,
            venue,
            asset_id,
            market,
            execution_intent,
            action_type,
            requested_side,
            permission_state,
            decision_state,
            evidence_state,
            valid_until_ts_utc,
            revoked_ts_utc,
            superseded_by_evidence_id
        FROM execution_permission_evidence
        WHERE execution_plan_id = %s
        ORDER BY execution_permission_evidence_id ASC
        LIMIT 2
        """

        with db_cursor(commit=False) as (_conn, cur):
            cur.execute(sql, (execution_plan_id,))
            rows = cur.fetchall()

        return [_permission_evidence_from_row(row) for row in rows]


def _permission_evidence_from_row(row: Mapping[str, Any]) -> PermissionEvidence:
    return PermissionEvidence(
        execution_permission_evidence_id=int(row["execution_permission_evidence_id"]),
        execution_plan_id=int(row["execution_plan_id"]),
        trading_account_id=int(row["trading_account_id"]),
        venue=str(row["venue"]),
        asset_id=int(row["asset_id"]),
        market=str(row["market"]),
        execution_intent=str(row["execution_intent"]),
        action_type=str(row["action_type"]),
        requested_side=(
            None if row["requested_side"] is None else str(row["requested_side"])
        ),
        permission_state=str(row["permission_state"]),
        decision_state=str(row["decision_state"]),
        evidence_state=str(row["evidence_state"]),
        valid_until_ts_utc=row["valid_until_ts_utc"],
        revoked_ts_utc=row["revoked_ts_utc"],
        superseded_by_evidence_id=(
            None
            if row["superseded_by_evidence_id"] is None
            else int(row["superseded_by_evidence_id"])
        ),
    )


def utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def expected_execution_intent(desired_action: str) -> str | None:
    return INTENT_BY_DESIRED_ACTION.get(str(desired_action).upper())


def require_live_execution_environment(env: Mapping[str, str] | None = None) -> None:
    env = env or os.environ

    live_permission = env.get(LIVE_EXECUTION_PERMISSION_ENV, "")
    if live_permission != LIVE_EXECUTION_PERMISSION_GRANTED_VALUE:
        raise LiveExecutionPermissionError(
            "Live execution blocked fail-closed. "
            f"env={LIVE_EXECUTION_PERMISSION_ENV} is not explicitly granted."
        )

    broker_write_permission = env.get(BROKER_WRITE_PERMISSION_ENV, "")
    if broker_write_permission != BROKER_WRITE_PERMISSION_GRANTED_VALUE:
        raise LiveExecutionPermissionError(
            "Broker write blocked fail-closed before broker client call. "
            f"env={BROKER_WRITE_PERMISSION_ENV} is not explicitly granted."
        )


def validate_live_execution_permission(
    *,
    plan: Any,
    market: str,
    repo: ExecutionPermissionRepository,
    env: Mapping[str, str] | None = None,
    now_utc: datetime | None = None,
) -> PermissionEvidence:
    now = now_utc or utc_now_naive()
    require_live_execution_environment(env)

    execution_plan_id = int(getattr(plan, "execution_plan_id"))
    trading_account_id = getattr(plan, "trading_account_id", None)
    if trading_account_id is None:
        raise LiveExecutionPermissionError("Live execution blocked: missing trading_account_id on execution plan.")

    account = repo.fetch_account_state(int(trading_account_id))
    if account is None:
        raise LiveExecutionPermissionError("Live execution blocked: trading account evidence missing.")
    if not account.enabled:
        raise LiveExecutionPermissionError("Live execution blocked: trading account is disabled.")
    if not account.live_trading_enabled:
        raise LiveExecutionPermissionError("Live execution blocked: trading_account.live_trading_enabled is false.")

    plan_venue = str(getattr(plan, "venue", "") or "")
    if not plan_venue:
        raise LiveExecutionPermissionError("Live execution blocked: execution plan venue missing.")
    if account.venue != plan_venue:
        raise LiveExecutionPermissionError("Live execution blocked: trading account venue mismatch.")

    plan_state = str(getattr(plan, "plan_state", "")).upper()
    if plan_state not in LIVE_ACTIONABLE_PLAN_STATES:
        raise LiveExecutionPermissionError("Live execution blocked: execution plan is not actionable.")

    valid_until = getattr(plan, "valid_until_ts_utc", None)
    if valid_until is not None and valid_until <= now:
        raise LiveExecutionPermissionError("Live execution blocked: execution plan is stale.")

    rows = repo.fetch_permission_evidence(execution_plan_id)
    if not rows:
        raise LiveExecutionPermissionError("Live execution blocked: missing decision-gate permission evidence.")
    if len(rows) > 1:
        raise LiveExecutionPermissionError("Live execution blocked: multiple decision-gate permission evidence rows.")

    evidence = rows[0]
    expected_intent = expected_execution_intent(str(getattr(plan, "desired_action", "")))
    if expected_intent is None:
        raise LiveExecutionPermissionError("Live execution blocked: unsupported execution intent.")

    if evidence.execution_plan_id != execution_plan_id:
        raise LiveExecutionPermissionError("Live execution blocked: execution_plan_id mismatch.")
    if evidence.trading_account_id != int(trading_account_id):
        raise LiveExecutionPermissionError("Live execution blocked: trading_account_id mismatch.")
    if evidence.venue != plan_venue:
        raise LiveExecutionPermissionError("Live execution blocked: venue mismatch.")
    if evidence.asset_id != int(getattr(plan, "asset_id")):
        raise LiveExecutionPermissionError("Live execution blocked: instrument asset_id mismatch.")
    if evidence.market != market:
        raise LiveExecutionPermissionError("Live execution blocked: market identity mismatch.")
    if evidence.execution_intent != expected_intent:
        raise LiveExecutionPermissionError("Live execution blocked: execution intent mismatch.")
    if evidence.action_type != str(getattr(plan, "desired_action")):
        raise LiveExecutionPermissionError("Live execution blocked: execution action mismatch.")

    requested_side = evidence.requested_side.upper() if evidence.requested_side else None
    plan_side = str(getattr(plan, "side", "") or "").upper()
    if requested_side is not None and requested_side != plan_side:
        raise LiveExecutionPermissionError("Live execution blocked: requested side mismatch.")

    if evidence.decision_state != ALLOWED_DECISION_STATE:
        raise LiveExecutionPermissionError("Live execution blocked: decision-gate outcome does not permit execution.")
    if evidence.permission_state != ALLOWED_PERMISSION_STATE:
        raise LiveExecutionPermissionError("Live execution blocked: permission state is not execution-permitted.")
    if evidence.evidence_state != ACTIVE_EVIDENCE_STATE:
        raise LiveExecutionPermissionError("Live execution blocked: permission evidence is not active.")
    if evidence.valid_until_ts_utc is None or evidence.valid_until_ts_utc <= now:
        raise LiveExecutionPermissionError("Live execution blocked: permission evidence is stale.")
    if evidence.revoked_ts_utc is not None:
        raise LiveExecutionPermissionError("Live execution blocked: permission evidence is revoked.")
    if evidence.superseded_by_evidence_id is not None:
        raise LiveExecutionPermissionError("Live execution blocked: permission evidence is superseded.")

    return evidence
