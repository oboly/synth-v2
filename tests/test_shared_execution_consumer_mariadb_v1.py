"""Opt-in disposable MariaDB acceptance for the generic shared consumer.

This uses only synthetic handoffs and a fake order adapter.  It intentionally
does not construct a venue client or read the configured application database.
"""
from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator

import pytest

from src.executor.broker_ack_classification_v1 import BrokerAckStateV1, OrderAckV1
from src.executor.execution_handoff_v1 import ExecutionHandoffRepositoryV1
from src.executor.execution_leg_v1 import ACTIVE, ExecutionLegRepositoryV1
from src.executor.execution_plan_reference_v1 import ApprovedExecutionPlanV1, ExecutionPlanLegV1
from src.executor.run_shared_execution_consumer_once_v1 import run_shared_execution_consumer_once_v1
from src.executor.shared_execution_consumer_v1 import hydrate_approved_execution_plan


DISPOSABLE_OPT_IN = "SYNTH_RUN_DISPOSABLE_MARIADB_SHARED_EXECUTOR_TESTS"
DISPOSABLE_DATABASE = "synth_acceptance_shared_executor_206"
AUTHORIZED_DISPOSABLE_HOST = "192.168.1.221"
REPO_ROOT = Path(__file__).resolve().parents[1]


def _require_disposable_mariadb() -> None:
    if os.getenv(DISPOSABLE_OPT_IN) != "1":
        pytest.skip(f"Set {DISPOSABLE_OPT_IN}=1 only for disposable MariaDB.")
    database = os.getenv("DB_NAME") or os.getenv("MYSQL_DATABASE") or ""
    host = os.getenv("DB_HOST") or os.getenv("MYSQL_HOST") or ""
    password = os.getenv("DB_PASSWORD") or os.getenv("MYSQL_PASSWORD") or ""
    if database not in {"", "information_schema", DISPOSABLE_DATABASE}:
        pytest.fail("shared consumer test refuses a configured application database")
    if host not in {"127.0.0.1", "localhost", AUTHORIZED_DISPOSABLE_HOST}:
        pytest.fail("shared consumer test refuses an unauthorized MariaDB host")
    if host not in {"127.0.0.1", "localhost"} and database != DISPOSABLE_DATABASE:
        pytest.fail("remote MariaDB requires the exact authorized disposable database")
    if host in {"127.0.0.1", "localhost"} and "disposable" not in password.lower():
        pytest.fail("shared consumer test password must contain disposable marker")


def _assert_database(cursor: Any, database: str) -> None:
    cursor.execute("SELECT DATABASE() AS db_name")
    assert cursor.fetchone()["db_name"] == database


def _migration_statements(path: Path) -> Iterator[str]:
    """Parse the repository's small DELIMITER-based MariaDB migration form."""
    delimiter = ";"
    parts: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("--"):
            continue
        if line.upper().startswith("DELIMITER "):
            delimiter = line.split(None, 1)[1]
            continue
        parts.append(raw_line)
        if line.endswith(delimiter):
            statement = "\n".join(parts).rstrip()
            yield statement[: -len(delimiter)].strip()
            parts = []
    assert not parts, f"unterminated migration statement: {path}"


def _apply_migration(cursor: Any, database: str, name: str) -> None:
    for statement in _migration_statements(REPO_ROOT / "db/migrations" / name):
        _assert_database(cursor, database)
        cursor.execute(statement)


def _create_prerequisite_schema(cursor: Any, database: str) -> None:
    # The shared substrate migration requires only this binding FK.  The test
    # seeds handoffs directly, so credential resolution and any live authority
    # schema are deliberately out of scope.
    _assert_database(cursor, database)
    cursor.execute(
        "CREATE TABLE executor_credential_binding ("
        "executor_credential_binding_id BIGINT UNSIGNED NOT NULL, "
        "PRIMARY KEY (executor_credential_binding_id)) ENGINE=InnoDB"
    )
    _assert_database(cursor, database)
    cursor.execute("INSERT INTO executor_credential_binding VALUES (1)")


@contextmanager
def _disposable_schema() -> Iterator[tuple[str, Any]]:
    from src.common.db_core_v1 import get_connection

    _require_disposable_mariadb()
    database = DISPOSABLE_DATABASE
    admin = get_connection(database="information_schema")
    try:
        with admin.cursor() as cursor:
            _assert_database(cursor, "information_schema")
            cursor.execute(f"CREATE DATABASE `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        admin.commit()
        conn = get_connection(database=database)
        try:
            with conn.cursor() as cursor:
                _create_prerequisite_schema(cursor, database)
                _apply_migration(cursor, database, "20260815_shared_executor_substrate_v1.sql")
                _apply_migration(cursor, database, "20260815_executor_reconciliation_evidence_v1.sql")
                _apply_migration(cursor, database, "20260819_shared_executor_persisted_consumer_v1.sql")
            conn.commit()
            yield database, get_connection
        finally:
            conn.close()
    finally:
        with admin.cursor() as cursor:
            _assert_database(cursor, "information_schema")
            cursor.execute(f"DROP DATABASE IF EXISTS `{database}`")
            _assert_database(cursor, "information_schema")
            cursor.execute("SHOW DATABASES LIKE %s", [database])
            assert cursor.fetchall() == ()
        admin.commit()
        admin.close()


def _cursor_factory(get_connection: Any, database: str):
    @contextmanager
    def factory(*, commit: bool = False, **_kwargs: Any) -> Iterator[tuple[Any, Any]]:
        conn = get_connection(database=database)
        try:
            with conn.cursor() as cursor:
                _assert_database(cursor, database)
                yield conn, cursor
            if commit:
                conn.commit()
            else:
                conn.rollback()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    return factory


def _seed_handoff(cursor_factory: Any, reference: str, *, legs: tuple[ExecutionPlanLegV1, ...], mode: str = "DRY_RUN", executor_identity: str = "acceptance") -> int:
    plan = ApprovedExecutionPlanV1("ACCEPTANCE", reference, 7, "bitvavo", "BTC-EUR", "SELL", legs)
    with cursor_factory(commit=True) as (_conn, cursor):
        cursor.execute(
            "INSERT INTO executor_execution_handoff "
            "(plan_source, plan_reference_id, plan_content_hash, trading_account_id, venue, market, side, executor_mode, executor_identity, runtime_owner, executor_credential_binding_id, created_ts_utc) "
            "VALUES (%s,%s,%s,7,'bitvavo','BTC-EUR','SELL',%s,%s,'devlap',1,UTC_TIMESTAMP(6))",
            [plan.plan_source, plan.plan_reference_id, plan.content_hash, mode, executor_identity],
        )
        handoff_id = int(cursor.lastrowid)
        for leg in legs:
            cursor.execute(
                "INSERT INTO executor_execution_handoff_plan_leg "
                "(executor_execution_handoff_id,leg_index,trading_account_id,venue,market,side,price,quantity,created_ts_utc) "
                "VALUES (%s,%s,7,'bitvavo','BTC-EUR',%s,%s,%s,UTC_TIMESTAMP(6))",
                [handoff_id, leg.leg_index, leg.side, leg.price, leg.quantity],
            )
        cursor.execute(
            "INSERT INTO executor_execution_handoff_consumption "
            "(executor_execution_handoff_id,state,created_ts_utc) VALUES (%s,'PENDING',UTC_TIMESTAMP(6))",
            [handoff_id],
        )
    return handoff_id


class _FakeAdapter:
    def __init__(self, *, timeout_once: bool = False) -> None:
        self.timeout_once = timeout_once
        self.place_calls: list[dict[str, Any]] = []
        self.lookup_calls: list[dict[str, Any]] = []

    def place_order(self, **kwargs: Any) -> OrderAckV1:
        self.place_calls.append(kwargs)
        if self.timeout_once and len(self.place_calls) == 1:
            raise TimeoutError("synthetic uncertain submission")
        return OrderAckV1(f"fake-{len(self.place_calls)}", BrokerAckStateV1.ACTIVE)

    def find_order_by_client_order_id(self, **kwargs: Any) -> OrderAckV1:
        self.lookup_calls.append(kwargs)
        return OrderAckV1("fake-reconciled", BrokerAckStateV1.ACTIVE)


def test_disposable_shared_execution_consumer_acceptance() -> None:
    with _disposable_schema() as (database, get_connection):
        factory = _cursor_factory(get_connection, database)
        handoffs_a = ExecutionHandoffRepositoryV1(cursor_factory=factory)
        handoffs_b = ExecutionHandoffRepositoryV1(cursor_factory=factory)
        legs_a = ExecutionLegRepositoryV1(cursor_factory=factory)
        standard_legs = (
            ExecutionPlanLegV1(1, "SELL", Decimal("101.20"), Decimal("0.11")),
            ExecutionPlanLegV1(2, "SELL", Decimal("102.30"), Decimal("0.22")),
        )
        first = _seed_handoff(factory, "first", legs=standard_legs)
        second = _seed_handoff(factory, "second", legs=standard_legs)
        _seed_handoff(factory, "paper-not-eligible", legs=standard_legs, mode="PAPER")

        # Discovery is mode-specific and persisted-id ordered; the separate
        # repository objects open independent MariaDB connection contexts.
        assert [h.handoff_id for h in handoffs_a.discover_eligible(executor_mode="DRY_RUN", runtime_owner="devlap", executor_identity="acceptance")] == [first, second]
        assert handoffs_a.claim(handoff_id=first, claim_token=str(uuid.uuid4()), claimed_by="worker-a")
        assert not handoffs_b.claim(handoff_id=first, claim_token=str(uuid.uuid4()), claimed_by="worker-b")
        with factory() as (_conn, cursor):
            cursor.execute("SELECT claim_token FROM executor_execution_handoff_consumption WHERE executor_execution_handoff_id=%s", [first])
            first_token = cursor.fetchone()["claim_token"]
        assert handoffs_a.renew_claim(handoff_id=first, claim_token=first_token, lease_seconds=60)
        assert not handoffs_b.claim(handoff_id=first, claim_token=str(uuid.uuid4()), claimed_by="worker-b")
        # An expired claim can be reclaimed, but its stale token cannot renew.
        with factory(commit=True) as (_conn, cursor):
            cursor.execute("UPDATE executor_execution_handoff_consumption SET claim_expires_ts_utc=UTC_TIMESTAMP(6) - INTERVAL 1 SECOND WHERE executor_execution_handoff_id=%s", [first])
        assert not handoffs_a.renew_claim(handoff_id=first, claim_token=first_token, lease_seconds=60)
        # An expired owner cannot release/finalize its still-token-matching row.
        assert not handoffs_a.finish_claim(handoff_id=first, claim_token=first_token, completed=False)
        with factory() as (_conn, cursor):
            cursor.execute("SELECT state, claim_token, claim_expires_ts_utc < UTC_TIMESTAMP(6) AS expired FROM executor_execution_handoff_consumption WHERE executor_execution_handoff_id=%s", [first])
            stale_row = cursor.fetchone()
        assert stale_row == {"state": "CLAIMED", "claim_token": first_token, "expired": 1}
        # A later worker may reclaim that untouched expired row.
        reclaim_token = str(uuid.uuid4())
        assert handoffs_b.claim(handoff_id=first, claim_token=reclaim_token, claimed_by="worker-b")
        assert not handoffs_a.finish_claim(handoff_id=first, claim_token=first_token, completed=False)
        reopened = ExecutionHandoffRepositoryV1(cursor_factory=factory)
        assert first not in [h.handoff_id for h in reopened.discover_eligible(executor_mode="DRY_RUN", runtime_owner="devlap", executor_identity="acceptance")]

        # Release the test claim; restart/reload remains DB authoritative.
        with factory() as (_conn, cursor):
            cursor.execute("SELECT claim_token FROM executor_execution_handoff_consumption WHERE executor_execution_handoff_id=%s", [first])
            token = cursor.fetchone()["claim_token"]
        assert handoffs_b.finish_claim(handoff_id=first, claim_token=token, completed=False)

        persisted = handoffs_a.find(first)
        assert persisted is not None
        immutable = handoffs_a.load_immutable_legs(first)
        assert [(leg.leg_index, leg.price, leg.quantity, leg.side) for leg in immutable] == [
            (1, Decimal("101.200000000000000000"), Decimal("0.110000000000000000"), "SELL"),
            (2, Decimal("102.300000000000000000"), Decimal("0.220000000000000000"), "SELL"),
        ]
        hydrated = hydrate_approved_execution_plan(handoff=persisted, repository=handoffs_a)
        assert hydrated.trading_account_id == persisted.trading_account_id
        assert [(leg.leg_index, leg.price, leg.quantity, leg.side) for leg in hydrated.legs] == [(1, Decimal("101.20"), Decimal("0.11"), "SELL"), (2, Decimal("102.30"), Decimal("0.22"), "SELL")]

        adapter = _FakeAdapter()
        outcomes = run_shared_execution_consumer_once_v1(handoff_repository=handoffs_a, leg_repository=legs_a, adapter=adapter, operator_id=9, worker_id="worker-a", runtime_owner="devlap", executor_identity="acceptance")
        assert [outcome.handoff_id for outcome in outcomes] == [first, second]
        assert len(adapter.place_calls) == 4
        # A fresh consumer/repository cannot re-post completed legs/handoffs.
        restarted = run_shared_execution_consumer_once_v1(handoff_repository=ExecutionHandoffRepositoryV1(cursor_factory=factory), leg_repository=ExecutionLegRepositoryV1(cursor_factory=factory), adapter=adapter, operator_id=9, worker_id="worker-restart", runtime_owner="devlap", executor_identity="acceptance")
        assert restarted == () and len(adapter.place_calls) == 4

        uncertain = _seed_handoff(factory, "uncertain", legs=(ExecutionPlanLegV1(1, "SELL", Decimal("99.10"), Decimal("0.10")),))
        uncertain_adapter = _FakeAdapter(timeout_once=True)
        first_run = run_shared_execution_consumer_once_v1(handoff_repository=handoffs_a, leg_repository=legs_a, adapter=uncertain_adapter, operator_id=9, worker_id="worker-a", runtime_owner="devlap", executor_identity="acceptance")
        assert first_run[-1].handoff_id == uncertain and first_run[-1].stopped_reason == "SUBMISSION_UNCERTAIN"
        assert len(uncertain_adapter.place_calls) == 1
        second_run = run_shared_execution_consumer_once_v1(handoff_repository=ExecutionHandoffRepositoryV1(cursor_factory=factory), leg_repository=ExecutionLegRepositoryV1(cursor_factory=factory), adapter=uncertain_adapter, operator_id=9, worker_id="worker-restart", runtime_owner="devlap", executor_identity="acceptance")
        assert second_run[-1].handoff_id == uncertain and second_run[-1].stopped_reason is None
        assert len(uncertain_adapter.place_calls) == 1
        assert len(uncertain_adapter.lookup_calls) == 1
        assert uncertain_adapter.lookup_calls[0]["client_order_id"] == uncertain_adapter.place_calls[0]["client_order_id"]
        with factory() as (_conn, cursor):
            cursor.execute("SELECT state FROM executor_execution_leg WHERE executor_execution_handoff_id=%s", [uncertain])
            assert cursor.fetchone()["state"] == ACTIVE
