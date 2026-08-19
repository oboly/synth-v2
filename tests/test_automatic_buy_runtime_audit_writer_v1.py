from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.entry_policy.automatic_buy_runtime_audit_writer_v1 import (
    AutomaticBuyIdempotencyPayloadConflictError,
    canonical_json,
    write_automatic_buy_evaluation_audit_v1,
)


class _Cursor:
    def __init__(self, conn: "_Conn") -> None:
        self.conn = conn
        self.lastrowid = 0
        self._row = None

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        if sql.lstrip().startswith("SELECT"):
            self._row = self.conn.row
            return
        assert sql.lstrip().startswith("INSERT")
        self.lastrowid = 1
        self.conn.row = {
            "automatic_buy_evaluation_audit_id": 1,
            "source_evidence_json": params[6],
            "candidate_state": params[7],
            "candidate_action": params[8],
            "candidate_reason_code": params[9],
            "candidate_evidence_id": params[10],
            "gate_state": params[11],
            "gate_reason_code": params[12],
            "approved_notional_ceiling_eur": params[13],
            "strategy_bucket_reason_code": params[14],
            "protection_code": params[15],
            "protection_reason_code": params[16],
            "planner_state": params[17],
            "planner_reason_code": params[18],
            "immutable_plan_json": params[19],
        }

    def fetchone(self) -> dict[str, object] | None:
        return self._row


class _Conn:
    def __init__(self) -> None:
        self.row: dict[str, object] | None = None

    def cursor(self) -> _Cursor:
        return _Cursor(self)


def _kwargs() -> dict[str, object]:
    now = datetime(2026, 8, 19, 16, 0, tzinfo=UTC)
    return {
        "idempotency_key": "a" * 64,
        "runtime_version": "automatic_buy_policy_runtime_v1",
        "trading_account_id": 101,
        "venue": "bitvavo",
        "asset_id": 42,
        "market": "BTC-EUR",
        "source_evidence_json": {"source_snapshot_key": "b" * 64},
        "candidate_state": "CANDIDATE",
        "candidate_action": "ENTER",
        "candidate_reason_code": "ENTRY_ZONE_REACHED",
        "candidate_evidence_id": "evidence-1",
        "gate_state": "APPROVED",
        "gate_reason_code": "OK",
        "approved_notional_ceiling_eur": Decimal("50"),
        "strategy_bucket_reason_code": "OK",
        "protection_code": None,
        "protection_reason_code": "NO_ACTIVE_PROTECTION",
        "planner_state": "STAGED",
        "planner_reason_code": None,
        "immutable_plan_json": {"side": "BUY", "legs": []},
        "evaluation_ts_utc": now,
        "planning_ts_utc": now,
    }


def test_audit_writer_is_idempotent_for_identical_decision() -> None:
    conn = _Conn()
    first = write_automatic_buy_evaluation_audit_v1(conn, **_kwargs())
    second = write_automatic_buy_evaluation_audit_v1(conn, **_kwargs())
    assert first.outcome == "inserted"
    assert second.outcome == "idempotent_existing"
    assert conn.row is not None
    assert conn.row["source_evidence_json"] == canonical_json({"source_snapshot_key": "b" * 64})


def test_audit_writer_rejects_same_key_with_changed_decision() -> None:
    conn = _Conn()
    write_automatic_buy_evaluation_audit_v1(conn, **_kwargs())
    changed = _kwargs()
    changed["gate_reason_code"] = "CHANGED"
    with pytest.raises(AutomaticBuyIdempotencyPayloadConflictError):
        write_automatic_buy_evaluation_audit_v1(conn, **changed)
