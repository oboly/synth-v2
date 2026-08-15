from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.exit_policy.automatic_exit_runtime_audit_writer_v1 import (
    IdempotencyPayloadConflictError,
    canonical_json,
    write_automatic_exit_evaluation_audit_v1,
)
from tests.automatic_exit_runtime_fixtures_v1 import FakeConnection


TS = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


def _base_kwargs(idempotency_key: str = "a" * 64) -> dict:
    return dict(
        idempotency_key=idempotency_key,
        runtime_version="automatic_exit_policy_runtime_v1",
        trading_account_id=7,
        position_reference="account_position_snapshot:1",
        venue="bitvavo",
        asset_id=101,
        market="BTC-EUR",
        source_evidence_json={"trading_account_id": 7, "price": Decimal("50000")},
        candidate_state="NO_ACTION",
        candidate_action=None,
        candidate_reason_code="NO_EXIT_CONDITION",
        candidate_evidence_id=None,
        exit_profile_id="profile-1",
        exit_profile_version="1",
        gate_state=None,
        gate_reason_code=None,
        approved_fraction_candidate=None,
        approved_quantity_ceiling_base=None,
        planner_state="NOT_REACHED",
        planner_reason_code=None,
        immutable_plan_json=None,
        evaluation_ts_utc=TS,
        planning_ts_utc=None,
    )


def test_canonical_json_is_deterministic_sorted_and_decimal_safe() -> None:
    value = {"b": Decimal("1.50"), "a": TS}
    first = canonical_json(value)
    second = canonical_json({"a": TS, "b": Decimal("1.50")})
    assert first == second
    assert first.startswith('{"a":"2026-08-15T12:00:00Z","b":"1.50"}')
    assert "." not in first.split(":")[0]  # sort_keys/no whitespace sanity


def test_append_only_insert_creates_row() -> None:
    conn = FakeConnection()
    result = write_automatic_exit_evaluation_audit_v1(conn, **_base_kwargs())
    assert result.outcome == "inserted"
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS c FROM automatic_exit_evaluation_audit_v1")
        assert cur.fetchone()["c"] == 1


def test_rerun_same_key_same_payload_is_idempotent_no_duplicate() -> None:
    conn = FakeConnection()
    kwargs = _base_kwargs()
    first = write_automatic_exit_evaluation_audit_v1(conn, **kwargs)
    second = write_automatic_exit_evaluation_audit_v1(conn, **kwargs)
    assert first.outcome == "inserted"
    assert second.outcome == "idempotent_existing"
    assert first.automatic_exit_evaluation_audit_id == second.automatic_exit_evaluation_audit_id
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS c FROM automatic_exit_evaluation_audit_v1")
        assert cur.fetchone()["c"] == 1


def test_same_key_different_decision_fails_closed() -> None:
    conn = FakeConnection()
    kwargs = _base_kwargs()
    write_automatic_exit_evaluation_audit_v1(conn, **kwargs)
    conflicting = dict(kwargs)
    conflicting["candidate_state"] = "CANDIDATE"
    conflicting["candidate_action"] = "REDUCE"
    with pytest.raises(IdempotencyPayloadConflictError):
        write_automatic_exit_evaluation_audit_v1(conn, **conflicting)


def test_wall_clock_timestamp_drift_alone_does_not_conflict() -> None:
    """Same decision, later evaluation_ts_utc: legitimate idempotent replay, not a conflict."""
    conn = FakeConnection()
    kwargs = _base_kwargs()
    write_automatic_exit_evaluation_audit_v1(conn, **kwargs)
    later = dict(kwargs)
    later["evaluation_ts_utc"] = TS.replace(minute=5)
    result = write_automatic_exit_evaluation_audit_v1(conn, **later)
    assert result.outcome == "idempotent_existing"


def test_history_is_append_only_never_updated() -> None:
    conn = FakeConnection()
    write_automatic_exit_evaluation_audit_v1(conn, **_base_kwargs("a" * 64))
    write_automatic_exit_evaluation_audit_v1(conn, **_base_kwargs("b" * 64))
    with conn.cursor() as cur:
        cur.execute("SELECT idempotency_key FROM automatic_exit_evaluation_audit_v1 ORDER BY automatic_exit_evaluation_audit_id")
        rows = cur.fetchall()
    assert [row["idempotency_key"] for row in rows] == ["a" * 64, "b" * 64]
