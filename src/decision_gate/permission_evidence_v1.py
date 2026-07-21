from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from src.common.db import get_connection
from src.decision_gate.models import DecisionResult


EVIDENCE_PRIVATE_KEY_ENV = "SYNTH_DECISION_GATE_EVIDENCE_PRIVATE_KEY_B64"
EVIDENCE_PUBLIC_KEY_ENV = "SYNTH_DECISION_GATE_EVIDENCE_PUBLIC_KEY_B64"
PRODUCER_NAME = "decision_gate_permission_service_v1"
ALLOWED_DECISION_STATE = "EXECUTION_ALLOWED"
ALLOWED_PERMISSION_STATE = "EXECUTION_PERMITTED"
VALID_ACTION_TYPES = frozenset({"PLACE_ORDER", "CANCEL_ORDER", "MONITOR_ORDER"})
VALID_SIDES = frozenset({"BUY", "SELL"})


class PermissionEvidenceProducerError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class PermissionEvidenceRequest:
    trading_account_id: int
    market: str
    interval_code: str
    execution_intent: str
    action_type: str
    requested_side: str
    permitted_ts_utc: datetime
    valid_until_ts_utc: datetime


def _key_bytes(name: str, env: Mapping[str, str] | None = None) -> bytes:
    values = os.environ if env is None else env
    encoded = values.get(name, "")
    try:
        key = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise PermissionEvidenceProducerError("PERMISSION_PROVENANCE_KEY_INVALID") from exc
    if len(key) != 32:
        raise PermissionEvidenceProducerError("PERMISSION_PROVENANCE_KEY_INVALID")
    return key


def build_provenance_payload(
    *,
    decision_gate_audit_log_id: int,
    trading_account_id: int,
    venue: str,
    asset_id: int,
    market: str,
    execution_intent: str,
    action_type: str,
    requested_side: str,
    permission_state: str,
    decision_state: str,
    permitted_ts_utc: datetime,
    valid_until_ts_utc: datetime,
) -> str:
    payload = {
        "action_type": action_type,
        "asset_id": asset_id,
        "decision_gate_audit_log_id": decision_gate_audit_log_id,
        "decision_state": decision_state,
        "execution_intent": execution_intent,
        "market": market,
        "permission_state": permission_state,
        "permitted_ts_utc": permitted_ts_utc.isoformat(timespec="microseconds"),
        "producer": PRODUCER_NAME,
        "requested_side": requested_side,
        "trading_account_id": trading_account_id,
        "valid_until_ts_utc": valid_until_ts_utc.isoformat(timespec="microseconds"),
        "venue": venue,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def sign_provenance(payload: str, env: Mapping[str, str] | None = None) -> str:
    private_key = Ed25519PrivateKey.from_private_bytes(_key_bytes(EVIDENCE_PRIVATE_KEY_ENV, env))
    return base64.b64encode(private_key.sign(payload.encode("utf-8"))).decode("ascii")


def verify_provenance_signature(
    payload: str,
    signature: str,
    env: Mapping[str, str] | None = None,
) -> bool:
    try:
        signature_bytes = base64.b64decode(signature, validate=True)
        public_key = Ed25519PublicKey.from_public_bytes(_key_bytes(EVIDENCE_PUBLIC_KEY_ENV, env))
        public_key.verify(signature_bytes, payload.encode("utf-8"))
    except (InvalidSignature, ValueError, PermissionEvidenceProducerError):
        return False
    return True


def _validate_request(decision: DecisionResult, request: PermissionEvidenceRequest) -> None:
    if decision.decision_state != ALLOWED_DECISION_STATE:
        raise PermissionEvidenceProducerError("DECISION_GATE_OUTCOME_NOT_ALLOWED")
    if decision.execution_intent != request.execution_intent:
        raise PermissionEvidenceProducerError("DECISION_GATE_INTENT_MISMATCH")
    if decision.venue != str(decision.venue).strip() or not decision.venue:
        raise PermissionEvidenceProducerError("DECISION_GATE_VENUE_NOT_CANONICAL")
    if request.market != f"{decision.symbol}-EUR":
        raise PermissionEvidenceProducerError("DECISION_GATE_MARKET_MISMATCH")
    if request.action_type not in VALID_ACTION_TYPES:
        raise PermissionEvidenceProducerError("DECISION_GATE_ACTION_TYPE_INVALID")
    if request.requested_side not in VALID_SIDES:
        raise PermissionEvidenceProducerError("DECISION_GATE_REQUESTED_SIDE_INVALID")
    if request.permitted_ts_utc.tzinfo is not None or request.valid_until_ts_utc.tzinfo is not None:
        raise PermissionEvidenceProducerError("DECISION_GATE_TIMESTAMP_NOT_NAIVE_UTC")
    if request.valid_until_ts_utc < request.permitted_ts_utc:
        raise PermissionEvidenceProducerError("DECISION_GATE_PERMISSION_WINDOW_INVALID")


@dataclass
class DecisionGatePermissionRepository:
    env: Mapping[str, str] | None = None

    def create_permission(
        self,
        *,
        decision: DecisionResult,
        request: PermissionEvidenceRequest,
    ) -> int:
        _validate_request(decision, request)
        _key_bytes(EVIDENCE_PRIVATE_KEY_ENV, self.env)

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT trading_account_id, venue, enabled, live_trading_enabled
                    FROM trading_account
                    WHERE trading_account_id = %s
                    FOR UPDATE
                    """,
                    (request.trading_account_id,),
                )
                account = cur.fetchone()
                if account is None:
                    raise PermissionEvidenceProducerError("DECISION_GATE_TRADING_ACCOUNT_NOT_FOUND")
                if int(account["trading_account_id"]) != request.trading_account_id:
                    raise PermissionEvidenceProducerError("DECISION_GATE_TRADING_ACCOUNT_MISMATCH")
                if account["venue"] != decision.venue:
                    raise PermissionEvidenceProducerError("DECISION_GATE_ACCOUNT_VENUE_MISMATCH")
                if not bool(account["enabled"]):
                    raise PermissionEvidenceProducerError("DECISION_GATE_TRADING_ACCOUNT_DISABLED")
                if not bool(account["live_trading_enabled"]):
                    raise PermissionEvidenceProducerError("DECISION_GATE_LIVE_TRADING_DISABLED")
                cur.execute(
                    """
                    INSERT INTO decision_gate_audit_log (
                        trading_account_id,
                        venue,
                        asset_id,
                        symbol,
                        market,
                        interval_code,
                        execution_mode,
                        permission_state,
                        decision_state,
                        decision_reason,
                        execution_intent,
                        action_type,
                        requested_side,
                        asof_ts_utc,
                        created_ts_utc
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, 'LIVE',
                        %s, %s, %s, %s, %s, %s, %s, UTC_TIMESTAMP(6)
                    )
                    """,
                    (
                        request.trading_account_id,
                        decision.venue,
                        decision.asset_id,
                        decision.symbol,
                        request.market,
                        request.interval_code,
                        ALLOWED_PERMISSION_STATE,
                        decision.decision_state,
                        decision.decision_reason,
                        decision.execution_intent,
                        request.action_type,
                        request.requested_side,
                        request.permitted_ts_utc,
                    ),
                )
                audit_id = int(cur.lastrowid)
                payload = build_provenance_payload(
                    decision_gate_audit_log_id=audit_id,
                    trading_account_id=request.trading_account_id,
                    venue=decision.venue,
                    asset_id=decision.asset_id,
                    market=request.market,
                    execution_intent=request.execution_intent,
                    action_type=request.action_type,
                    requested_side=request.requested_side,
                    permission_state=ALLOWED_PERMISSION_STATE,
                    decision_state=decision.decision_state,
                    permitted_ts_utc=request.permitted_ts_utc,
                    valid_until_ts_utc=request.valid_until_ts_utc,
                )
                signature = sign_provenance(payload, self.env)
                cur.execute(
                    """
                    INSERT INTO decision_gate_permission_evidence (
                        decision_gate_audit_log_id,
                        producer_name,
                        provenance_signature,
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
                        permitted_ts_utc,
                        valid_until_ts_utc
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, 'ACTIVE', %s, %s
                    )
                    """,
                    (
                        audit_id,
                        PRODUCER_NAME,
                        signature,
                        request.trading_account_id,
                        decision.venue,
                        decision.asset_id,
                        request.market,
                        request.execution_intent,
                        request.action_type,
                        request.requested_side,
                        ALLOWED_PERMISSION_STATE,
                        decision.decision_state,
                        request.permitted_ts_utc,
                        request.valid_until_ts_utc,
                    ),
                )
                evidence_id = int(cur.lastrowid)
            conn.commit()
            return evidence_id
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def revoke_permission(self, evidence_id: int, revoked_ts_utc: datetime) -> None:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE decision_gate_permission_evidence
                    SET evidence_state = 'REVOKED', revoked_ts_utc = %s
                    WHERE decision_gate_permission_evidence_id = %s
                      AND evidence_state = 'ACTIVE'
                      AND revoked_ts_utc IS NULL
                      AND superseded_by_evidence_id IS NULL
                    """,
                    (revoked_ts_utc, evidence_id),
                )
                if cur.rowcount != 1:
                    raise PermissionEvidenceProducerError("PERMISSION_REVOKE_NOT_ACTIVE")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def supersede_permission(self, evidence_id: int, successor_evidence_id: int) -> None:
        if evidence_id == successor_evidence_id:
            raise PermissionEvidenceProducerError("PERMISSION_SELF_SUPERSESSION")

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        decision_gate_permission_evidence_id,
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
                        revoked_ts_utc,
                        superseded_by_evidence_id
                    FROM decision_gate_permission_evidence
                    WHERE decision_gate_permission_evidence_id IN (%s, %s)
                    ORDER BY decision_gate_permission_evidence_id
                    FOR UPDATE
                    """,
                    (evidence_id, successor_evidence_id),
                )
                rows = {
                    int(row["decision_gate_permission_evidence_id"]): row
                    for row in cur.fetchall()
                }
                if set(rows) != {evidence_id, successor_evidence_id}:
                    raise PermissionEvidenceProducerError("PERMISSION_SUCCESSOR_NOT_FOUND")
                source = rows[evidence_id]
                successor = rows[successor_evidence_id]
                if (
                    source["evidence_state"] != "ACTIVE"
                    or source["revoked_ts_utc"] is not None
                    or source["superseded_by_evidence_id"] is not None
                ):
                    raise PermissionEvidenceProducerError("PERMISSION_SUPERSEDE_NOT_ACTIVE")
                if (
                    successor["evidence_state"] != "ACTIVE"
                    or successor["revoked_ts_utc"] is not None
                    or successor["superseded_by_evidence_id"] is not None
                ):
                    raise PermissionEvidenceProducerError("PERMISSION_SUCCESSOR_NOT_ACTIVE")
                scope_fields = (
                    "trading_account_id",
                    "venue",
                    "asset_id",
                    "market",
                    "execution_intent",
                    "action_type",
                    "requested_side",
                    "permission_state",
                    "decision_state",
                )
                if any(source[field] != successor[field] for field in scope_fields):
                    raise PermissionEvidenceProducerError("PERMISSION_SUCCESSOR_SCOPE_MISMATCH")
                cur.execute(
                    """
                    UPDATE decision_gate_permission_evidence
                    SET evidence_state = 'SUPERSEDED', superseded_by_evidence_id = %s
                    WHERE decision_gate_permission_evidence_id = %s
                      AND evidence_state = 'ACTIVE'
                      AND revoked_ts_utc IS NULL
                      AND superseded_by_evidence_id IS NULL
                    """,
                    (successor_evidence_id, evidence_id),
                )
                if cur.rowcount != 1:
                    raise PermissionEvidenceProducerError("PERMISSION_SUPERSEDE_NOT_ACTIVE")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
