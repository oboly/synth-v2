from __future__ import annotations

import base64
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.decision_gate.models import DecisionResult
from src.decision_gate import permission_evidence_v1 as producer


NOW = datetime(2026, 7, 21, 12, 0, 0)
PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
ENV = {
    producer.EVIDENCE_PRIVATE_KEY_ENV: base64.b64encode(
        PRIVATE_KEY.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
    ).decode("ascii")
}
VERIFY_ENV = {
    producer.EVIDENCE_PUBLIC_KEY_ENV: base64.b64encode(
        PRIVATE_KEY.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
    ).decode("ascii")
}


def _decision(**overrides: Any) -> DecisionResult:
    decision = DecisionResult(
        account_id=99,
        sleeve_code="CORE",
        selection_state_id=1,
        asset_id=42,
        symbol="BTC",
        venue="bitvavo",
        asof_ts_utc="2026-07-21T12:00:00Z",
        selection_state="SELECTED",
        decision_state="EXECUTION_ALLOWED",
        decision_reason="ALL_ACCOUNT_GATES_PASSED",
        execution_intent="PLACE_PASSIVE_LIMIT",
        min_available_equity_eur=Decimal("25"),
        available_equity_eur=Decimal("100"),
        has_active_plan=False,
        has_open_position=False,
        allowed_sleeves="CORE",
        setup_filter_state="PASS",
        setup_filter_reason="OK",
        target_horizon="short",
        summary_text=None,
        regime_label_4h="TREND_UP",
    )
    return replace(decision, **overrides)


def _request(**overrides: Any) -> producer.PermissionEvidenceRequest:
    request = producer.PermissionEvidenceRequest(
        trading_account_id=7,
        market="BTC-EUR",
        interval_code="1h",
        execution_intent="PLACE_PASSIVE_LIMIT",
        action_type="PLACE_ORDER",
        requested_side="BUY",
        permitted_ts_utc=NOW,
        valid_until_ts_utc=NOW + timedelta(minutes=5),
    )
    return replace(request, **overrides)


class FakeCursor:
    def __init__(self) -> None:
        self.statements: list[tuple[str, tuple[Any, ...]]] = []
        self.lastrowid = 0
        self.rowcount = 1
        self._fetchall: list[dict[str, int]] = []
        self._fetchone: dict[str, Any] | None = None

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...]) -> None:
        self.statements.append((sql, params))
        if "FROM trading_account" in sql:
            self._fetchone = {
                "trading_account_id": int(params[0]),
                "venue": "bitvavo",
                "enabled": 1,
                "live_trading_enabled": 1,
            }
        elif "INSERT INTO decision_gate_audit_log" in sql:
            self.lastrowid = 9
        elif "INSERT INTO decision_gate_permission_evidence" in sql:
            self.lastrowid = 11
        elif "WHERE decision_gate_permission_evidence_id IN" in sql:
            scope = {
                "trading_account_id": 7,
                "venue": "bitvavo",
                "asset_id": 42,
                "market": "BTC-EUR",
                "execution_intent": "PLACE_PASSIVE_LIMIT",
                "action_type": "PLACE_ORDER",
                "requested_side": "BUY",
                "permission_state": "EXECUTION_PERMITTED",
                "decision_state": "EXECUTION_ALLOWED",
                "evidence_state": "ACTIVE",
                "revoked_ts_utc": None,
                "superseded_by_evidence_id": None,
            }
            self._fetchall = [
                {"decision_gate_permission_evidence_id": int(params[0]), **scope},
                {"decision_gate_permission_evidence_id": int(params[1]), **scope},
            ]

    def fetchall(self) -> list[dict[str, int]]:
        return self._fetchall

    def fetchone(self) -> dict[str, Any] | None:
        return self._fetchone


class FakeConnection:
    def __init__(self) -> None:
        self.cur = FakeCursor()
        self.commits = 0
        self.rollbacks = 0

    def cursor(self) -> FakeCursor:
        return self.cur

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        return None


def test_canonical_decision_gate_producer_writes_audit_then_signed_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = FakeConnection()
    monkeypatch.setattr(producer, "get_connection", lambda: conn)
    evidence_id = producer.DecisionGatePermissionRepository(env=ENV).create_permission(
        decision=_decision(), request=_request()
    )
    assert evidence_id == 11
    assert conn.commits == 1
    assert "FROM trading_account" in conn.cur.statements[0][0]
    assert "INSERT INTO decision_gate_audit_log" in conn.cur.statements[1][0]
    assert "INSERT INTO decision_gate_permission_evidence" in conn.cur.statements[2][0]
    assert conn.cur.statements[2][1][1] == producer.PRODUCER_NAME
    assert len(str(conn.cur.statements[2][1][2])) == 88


@pytest.mark.parametrize(
    ("decision", "permission_request", "code"),
    [
        (_decision(decision_state="EXECUTION_DENIED"), _request(), "DECISION_GATE_OUTCOME_NOT_ALLOWED"),
        (_decision(), _request(market="ETH-EUR"), "DECISION_GATE_MARKET_MISMATCH"),
        (_decision(), _request(requested_side="buy"), "DECISION_GATE_REQUESTED_SIDE_INVALID"),
        (_decision(), _request(action_type="SUBMIT"), "DECISION_GATE_ACTION_TYPE_INVALID"),
    ],
)
def test_producer_rejects_noncanonical_gate_results(
    decision: DecisionResult,
    permission_request: producer.PermissionEvidenceRequest,
    code: str,
) -> None:
    with pytest.raises(producer.PermissionEvidenceProducerError) as exc_info:
        producer.DecisionGatePermissionRepository(env=ENV).create_permission(
            decision=decision, request=permission_request
        )
    assert exc_info.value.code == code


def test_repository_rejects_self_supersession() -> None:
    with pytest.raises(producer.PermissionEvidenceProducerError) as exc_info:
        producer.DecisionGatePermissionRepository(env=ENV).supersede_permission(11, 11)
    assert exc_info.value.code == "PERMISSION_SELF_SUPERSESSION"


def test_executor_public_key_can_verify_but_cannot_mint_permission() -> None:
    payload = "canonical-payload"
    signature = producer.sign_provenance(payload, ENV)
    assert producer.verify_provenance_signature(payload, signature, VERIFY_ENV)
    with pytest.raises(producer.PermissionEvidenceProducerError) as exc_info:
        producer.sign_provenance(payload, VERIFY_ENV)
    assert exc_info.value.code == "PERMISSION_PROVENANCE_KEY_INVALID"


def test_repository_revoke_and_supersede_are_decision_gate_owned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connections: list[FakeConnection] = []

    def connect() -> FakeConnection:
        conn = FakeConnection()
        connections.append(conn)
        return conn

    monkeypatch.setattr(producer, "get_connection", connect)
    repo = producer.DecisionGatePermissionRepository(env=ENV)
    repo.revoke_permission(11, NOW)
    repo.supersede_permission(12, 13)
    assert "evidence_state = 'REVOKED'" in connections[0].cur.statements[0][0]
    assert "evidence_state = 'SUPERSEDED'" in connections[1].cur.statements[1][0]
