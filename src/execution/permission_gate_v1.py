from __future__ import annotations

import hashlib
import os
import socket
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Mapping

from src.common.db import get_connection
from src.decision_gate.permission_evidence_v1 import (
    ALLOWED_DECISION_STATE,
    ALLOWED_PERMISSION_STATE,
    PRODUCER_NAME,
    build_provenance_payload,
    verify_provenance_signature,
)
from src.execution.bitvavo_client import (
    BROKER_WRITE_PERMISSION_ENV,
    BROKER_WRITE_PERMISSION_GRANTED_VALUE,
)


LIVE_EXECUTION_PERMISSION_ENV = "SYNTH_LIVE_EXECUTION_PERMISSION"
LIVE_EXECUTION_PERMISSION_GRANTED_VALUE = "I_UNDERSTAND_THIS_ENABLES_LIVE_EXECUTION"
VALID_SIDES = frozenset({"BUY", "SELL"})
VALID_ACTION_TYPES = frozenset({"PLACE_ORDER", "CANCEL_ORDER", "MONITOR_ORDER"})
PLACE_ACTIONABLE_PLAN_STATES = frozenset({"IDLE"})


class LiveExecutionPermissionError(PermissionError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ExecutionClaim:
    execution_attempt_id: int
    execution_plan_id: int
    decision_gate_permission_evidence_id: int
    trading_account_id: int
    asset_id: int
    venue: str
    market: str
    execution_intent: str
    action_type: str
    requested_side: str
    reference_price_eur: Decimal
    passive_price_eur: Decimal
    target_fraction: Decimal
    claim_token: str
    claim_owner: str
    claimed_ts_utc: datetime
    authorization_snapshot_ts_utc: datetime
    idempotency_key: str
    broker_client_order_id: str


def utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def default_claim_owner() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def require_live_execution_environment(env: Mapping[str, str] | None = None) -> None:
    values = os.environ if env is None else env
    if values.get(LIVE_EXECUTION_PERMISSION_ENV, "") != LIVE_EXECUTION_PERMISSION_GRANTED_VALUE:
        raise LiveExecutionPermissionError("LIVE_EXECUTION_ENV_NOT_GRANTED")
    if values.get(BROKER_WRITE_PERMISSION_ENV, "") != BROKER_WRITE_PERMISSION_GRANTED_VALUE:
        raise LiveExecutionPermissionError("BROKER_WRITE_ENV_NOT_GRANTED")


def _required_text(row: Mapping[str, Any], key: str, code: str) -> str:
    value = row.get(key)
    if value is None or str(value) == "":
        raise LiveExecutionPermissionError(code)
    return str(value)


def _validate_exact_scope(
    row: Mapping[str, Any],
    *,
    action_type: str,
    now: datetime,
    env: Mapping[str, str] | None,
) -> None:
    require_live_execution_environment(env)
    if action_type not in VALID_ACTION_TYPES:
        raise LiveExecutionPermissionError("ACTION_TYPE_NOT_CANONICAL")
    if row.get("plan_execution_mode") != "LIVE":
        raise LiveExecutionPermissionError("PLAN_NOT_LIVE")
    if row.get("plan_state") not in PLACE_ACTIONABLE_PLAN_STATES:
        raise LiveExecutionPermissionError("PLAN_NOT_ACTIONABLE")
    plan_valid_until = row.get("plan_valid_until_ts_utc")
    if plan_valid_until is None or plan_valid_until < now:
        raise LiveExecutionPermissionError("PLAN_EXPIRED_OR_UNBOUNDED")

    plan_account_id = row.get("plan_trading_account_id")
    if plan_account_id is None:
        raise LiveExecutionPermissionError("PLAN_TRADING_ACCOUNT_ID_MISSING")
    if int(plan_account_id) != int(row["evidence_trading_account_id"]):
        raise LiveExecutionPermissionError("PLAN_EVIDENCE_ACCOUNT_MISMATCH")
    if row.get("account_trading_account_id") is None:
        raise LiveExecutionPermissionError("TRADING_ACCOUNT_NOT_FOUND")
    if int(plan_account_id) != int(row["account_trading_account_id"]):
        raise LiveExecutionPermissionError("PLAN_ACCOUNT_ROW_MISMATCH")
    if row.get("account_venue") != row.get("evidence_venue"):
        raise LiveExecutionPermissionError("ACCOUNT_VENUE_MISMATCH")
    if not bool(row["account_enabled"]):
        raise LiveExecutionPermissionError("TRADING_ACCOUNT_DISABLED")
    if not bool(row["account_live_trading_enabled"]):
        raise LiveExecutionPermissionError("TRADING_ACCOUNT_LIVE_DISABLED")

    exact_pairs = (
        ("plan_venue", "evidence_venue", "VENUE_MISMATCH"),
        ("plan_market", "evidence_market", "MARKET_MISMATCH"),
        ("plan_execution_intent", "evidence_execution_intent", "EXECUTION_INTENT_MISMATCH"),
        ("plan_action_type", "evidence_action_type", "ACTION_TYPE_MISMATCH"),
        ("plan_requested_side", "evidence_requested_side", "REQUESTED_SIDE_MISMATCH"),
    )
    for plan_key, evidence_key, code in exact_pairs:
        plan_value = _required_text(row, plan_key, code)
        evidence_value = _required_text(row, evidence_key, code)
        if plan_value != evidence_value:
            raise LiveExecutionPermissionError(code)
    if int(row["plan_asset_id"]) != int(row["evidence_asset_id"]):
        raise LiveExecutionPermissionError("ASSET_ID_MISMATCH")
    if row["plan_action_type"] != action_type:
        raise LiveExecutionPermissionError("CLAIM_ACTION_TYPE_MISMATCH")
    if row["plan_requested_side"] not in VALID_SIDES:
        raise LiveExecutionPermissionError("REQUESTED_SIDE_NOT_CANONICAL")
    if row.get("plan_side") != row["plan_requested_side"]:
        raise LiveExecutionPermissionError("PLAN_SIDE_SCOPE_MISMATCH")
    if action_type == "PLACE_ORDER":
        try:
            reference_price = Decimal(str(row["reference_price_eur"]))
            passive_price = Decimal(str(row["passive_price_eur"]))
            target_fraction = Decimal(str(row["target_fraction"]))
        except Exception as exc:
            raise LiveExecutionPermissionError("PLACEMENT_VALUES_INVALID") from exc
        if reference_price <= 0 or passive_price <= 0 or target_fraction <= 0:
            raise LiveExecutionPermissionError("PLACEMENT_VALUES_INVALID")

    if row.get("producer_name") != PRODUCER_NAME:
        raise LiveExecutionPermissionError("PERMISSION_PRODUCER_INVALID")
    audit_id = row.get("decision_gate_audit_log_id")
    if audit_id is None:
        raise LiveExecutionPermissionError("PERMISSION_AUDIT_PROVENANCE_MISSING")
    if row.get("audit_row_id") is None:
        raise LiveExecutionPermissionError("PERMISSION_AUDIT_ROW_NOT_FOUND")
    if row.get("permission_state") != ALLOWED_PERMISSION_STATE:
        raise LiveExecutionPermissionError("PERMISSION_STATE_DENIED")
    if row.get("decision_state") != ALLOWED_DECISION_STATE:
        raise LiveExecutionPermissionError("DECISION_STATE_DENIED")
    successor_id = row.get("superseded_by_evidence_id")
    if successor_id is not None:
        if int(successor_id) == int(row["evidence_permission_evidence_id"]):
            raise LiveExecutionPermissionError("PERMISSION_SELF_SUPERSEDED")
        raise LiveExecutionPermissionError("PERMISSION_SUPERSEDED")
    if row.get("revoked_ts_utc") is not None:
        raise LiveExecutionPermissionError("PERMISSION_REVOKED")
    if row.get("evidence_state") != "ACTIVE":
        raise LiveExecutionPermissionError("PERMISSION_NOT_ACTIVE")
    if row["permitted_ts_utc"] > now or row["valid_until_ts_utc"] < now:
        raise LiveExecutionPermissionError("PERMISSION_NOT_CURRENT")

    audit_pairs = (
        ("audit_trading_account_id", "evidence_trading_account_id", "AUDIT_ACCOUNT_MISMATCH"),
        ("audit_venue", "evidence_venue", "AUDIT_VENUE_MISMATCH"),
        ("audit_market", "evidence_market", "AUDIT_MARKET_MISMATCH"),
        ("audit_execution_intent", "evidence_execution_intent", "AUDIT_INTENT_MISMATCH"),
        ("audit_action_type", "evidence_action_type", "AUDIT_ACTION_MISMATCH"),
        ("audit_requested_side", "evidence_requested_side", "AUDIT_SIDE_MISMATCH"),
        ("audit_permission_state", "permission_state", "AUDIT_PERMISSION_MISMATCH"),
        ("audit_decision_state", "decision_state", "AUDIT_DECISION_MISMATCH"),
    )
    for audit_key, evidence_key, code in audit_pairs:
        if row.get(audit_key) != row.get(evidence_key):
            raise LiveExecutionPermissionError(code)
    if int(row["audit_asset_id"]) != int(row["evidence_asset_id"]):
        raise LiveExecutionPermissionError("AUDIT_ASSET_MISMATCH")
    if row.get("audit_execution_mode") != "LIVE":
        raise LiveExecutionPermissionError("AUDIT_NOT_LIVE")

    payload = build_provenance_payload(
        decision_gate_audit_log_id=int(audit_id),
        trading_account_id=int(row["evidence_trading_account_id"]),
        venue=str(row["evidence_venue"]),
        asset_id=int(row["evidence_asset_id"]),
        market=str(row["evidence_market"]),
        execution_intent=str(row["evidence_execution_intent"]),
        action_type=str(row["evidence_action_type"]),
        requested_side=str(row["evidence_requested_side"]),
        permission_state=str(row["permission_state"]),
        decision_state=str(row["decision_state"]),
        permitted_ts_utc=row["permitted_ts_utc"],
        valid_until_ts_utc=row["valid_until_ts_utc"],
    )
    try:
        signature_valid = verify_provenance_signature(
            payload,
            str(row.get("provenance_signature") or ""),
            env,
        )
    except Exception as exc:
        raise LiveExecutionPermissionError("PERMISSION_PROVENANCE_UNVERIFIABLE") from exc
    if not signature_valid:
        raise LiveExecutionPermissionError("PERMISSION_PROVENANCE_INVALID")


class ExecutionPermissionRepository:
    def claim_live_action(
        self,
        *,
        execution_plan_id: int,
        action_type: str,
        claim_owner: str | None = None,
        env: Mapping[str, str] | None = None,
        now_utc: datetime | None = None,
    ) -> ExecutionClaim:
        now = now_utc or utc_now_naive()
        owner = claim_owner or default_claim_owner()
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        p.execution_plan_id,
                        p.trading_account_id AS plan_trading_account_id,
                        p.decision_gate_permission_evidence_id AS plan_permission_evidence_id,
                        p.asset_id AS plan_asset_id,
                        p.venue AS plan_venue,
                        p.market AS plan_market,
                        p.side AS plan_side,
                        p.execution_intent AS plan_execution_intent,
                        p.action_type AS plan_action_type,
                        p.requested_side AS plan_requested_side,
                        p.execution_mode AS plan_execution_mode,
                        p.plan_state,
                        p.valid_until_ts_utc AS plan_valid_until_ts_utc,
                        p.reference_price_eur,
                        p.passive_price_eur,
                        p.target_fraction,
                        e.decision_gate_permission_evidence_id AS evidence_permission_evidence_id,
                        e.decision_gate_audit_log_id,
                        e.producer_name,
                        e.provenance_signature,
                        e.trading_account_id AS evidence_trading_account_id,
                        e.venue AS evidence_venue,
                        e.asset_id AS evidence_asset_id,
                        e.market AS evidence_market,
                        e.execution_intent AS evidence_execution_intent,
                        e.action_type AS evidence_action_type,
                        e.requested_side AS evidence_requested_side,
                        e.permission_state,
                        e.decision_state,
                        e.evidence_state,
                        e.permitted_ts_utc,
                        e.valid_until_ts_utc,
                        e.revoked_ts_utc,
                        e.superseded_by_evidence_id,
                        a.decision_gate_audit_log_id AS audit_row_id,
                        a.trading_account_id AS audit_trading_account_id,
                        a.venue AS audit_venue,
                        a.asset_id AS audit_asset_id,
                        a.market AS audit_market,
                        a.execution_intent AS audit_execution_intent,
                        a.action_type AS audit_action_type,
                        a.requested_side AS audit_requested_side,
                        a.permission_state AS audit_permission_state,
                        a.decision_state AS audit_decision_state,
                        a.execution_mode AS audit_execution_mode,
                        ta.trading_account_id AS account_trading_account_id,
                        ta.venue AS account_venue,
                        ta.enabled AS account_enabled,
                        ta.live_trading_enabled AS account_live_trading_enabled
                    FROM execution_plan p
                    LEFT JOIN decision_gate_permission_evidence e
                      ON e.decision_gate_permission_evidence_id = p.decision_gate_permission_evidence_id
                    LEFT JOIN decision_gate_audit_log a
                      ON a.decision_gate_audit_log_id = e.decision_gate_audit_log_id
                    LEFT JOIN trading_account ta
                      ON ta.trading_account_id = p.trading_account_id
                    WHERE p.execution_plan_id = %s
                    FOR UPDATE
                    """,
                    (execution_plan_id,),
                )
                row = cur.fetchone()
                if row is None:
                    raise LiveExecutionPermissionError("EXECUTION_PLAN_NOT_FOUND")
                if row.get("plan_permission_evidence_id") is None:
                    raise LiveExecutionPermissionError("PLAN_PERMISSION_BINDING_MISSING")
                if row.get("evidence_permission_evidence_id") is None:
                    raise LiveExecutionPermissionError("BOUND_PERMISSION_EVIDENCE_NOT_FOUND")
                if int(row["plan_permission_evidence_id"]) != int(
                    row["evidence_permission_evidence_id"]
                ):
                    raise LiveExecutionPermissionError("PLAN_PERMISSION_BINDING_MISMATCH")
                _validate_exact_scope(row, action_type=action_type, now=now, env=env)

                cur.execute(
                    """
                    SELECT attempt_state
                    FROM execution_attempt
                    WHERE execution_plan_id = %s AND action_type = %s
                    FOR UPDATE
                    """,
                    (execution_plan_id, action_type),
                )
                existing = cur.fetchone()
                if existing is not None:
                    raise LiveExecutionPermissionError(
                        f"EXECUTION_ATTEMPT_ALREADY_{existing['attempt_state']}"
                    )

                evidence_id = int(row["evidence_permission_evidence_id"])
                idempotency_key = hashlib.sha256(
                    f"{execution_plan_id}:{evidence_id}:{action_type}:1".encode("ascii")
                ).hexdigest()
                broker_client_order_id = str(
                    uuid.uuid5(uuid.NAMESPACE_URL, f"synth:{idempotency_key}")
                )
                claim_token = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO execution_attempt (
                        execution_plan_id,
                        decision_gate_permission_evidence_id,
                        trading_account_id,
                        action_type,
                        attempt_number,
                        claim_token,
                        claim_owner,
                        claimed_ts_utc,
                        authorization_snapshot_ts_utc,
                        idempotency_key,
                        broker_client_order_id,
                        attempt_state
                    ) VALUES (%s, %s, %s, %s, 1, %s, %s, %s, %s, %s, %s, 'CLAIMED')
                    """,
                    (
                        execution_plan_id,
                        evidence_id,
                        int(row["plan_trading_account_id"]),
                        action_type,
                        claim_token,
                        owner,
                        now,
                        now,
                        idempotency_key,
                        broker_client_order_id,
                    ),
                )
                attempt_id = int(cur.lastrowid)
                cur.execute(
                    """
                    UPDATE execution_plan
                    SET plan_state = 'SUBMISSION_CLAIMED', updated_ts_utc = UTC_TIMESTAMP(6)
                    WHERE execution_plan_id = %s AND plan_state = 'IDLE'
                    """,
                    (execution_plan_id,),
                )
                if cur.rowcount != 1:
                    raise LiveExecutionPermissionError("PLAN_CLAIM_STATE_CHANGED")
            conn.commit()
            return ExecutionClaim(
                execution_attempt_id=attempt_id,
                execution_plan_id=execution_plan_id,
                decision_gate_permission_evidence_id=evidence_id,
                trading_account_id=int(row["plan_trading_account_id"]),
                asset_id=int(row["plan_asset_id"]),
                venue=str(row["plan_venue"]),
                market=str(row["plan_market"]),
                execution_intent=str(row["plan_execution_intent"]),
                action_type=action_type,
                requested_side=str(row["plan_requested_side"]),
                reference_price_eur=Decimal(str(row["reference_price_eur"])),
                passive_price_eur=Decimal(str(row["passive_price_eur"])),
                target_fraction=Decimal(str(row["target_fraction"])),
                claim_token=claim_token,
                claim_owner=owner,
                claimed_ts_utc=now,
                authorization_snapshot_ts_utc=now,
                idempotency_key=idempotency_key,
                broker_client_order_id=broker_client_order_id,
            )
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def confirm_attempt(self, claim: ExecutionClaim, broker_order_id: str) -> None:
        self._finish_attempt(claim, "CONFIRMED", broker_order_id=broker_order_id)

    def mark_attempt_uncertain(self, claim: ExecutionClaim, failure_code: str) -> None:
        self._finish_attempt(claim, "UNCERTAIN", failure_code=failure_code)

    def mark_attempt_failed(self, claim: ExecutionClaim, failure_code: str) -> None:
        self._finish_attempt(claim, "FAILED", failure_code=failure_code)

    def _finish_attempt(
        self,
        claim: ExecutionClaim,
        state: str,
        *,
        broker_order_id: str | None = None,
        failure_code: str | None = None,
    ) -> None:
        plan_state = {
            "CONFIRMED": "PLACED",
            "UNCERTAIN": "SUBMISSION_UNCERTAIN",
            "FAILED": "FAILED",
        }[state]
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE execution_attempt
                    SET attempt_state = %s, broker_order_id = %s, failure_code = %s
                    WHERE execution_attempt_id = %s
                      AND claim_token = %s
                      AND attempt_state = 'CLAIMED'
                    """,
                    (
                        state,
                        broker_order_id,
                        failure_code,
                        claim.execution_attempt_id,
                        claim.claim_token,
                    ),
                )
                if cur.rowcount != 1:
                    raise LiveExecutionPermissionError("EXECUTION_ATTEMPT_FINISH_CONFLICT")
                cur.execute(
                    """
                    UPDATE execution_plan
                    SET plan_state = %s, updated_ts_utc = UTC_TIMESTAMP(6)
                    WHERE execution_plan_id = %s AND plan_state = 'SUBMISSION_CLAIMED'
                    """,
                    (plan_state, claim.execution_plan_id),
                )
                if cur.rowcount != 1:
                    raise LiveExecutionPermissionError("EXECUTION_PLAN_FINISH_CONFLICT")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
