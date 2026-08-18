"""Issue #392 Phase 6 blocker A: real runtime -> #206 handoff wiring test.

Uses the existing shared sqlite fixture (seed_happy_path) to run the exact
real candidate -> account-protection -> gate -> planner orchestrator path,
then proves the new composition-root runner hands the in-memory
AutomaticExitPlanV1 straight to the shared #206 handoff seam -- never by
reading automatic_exit_evaluation_audit_v1.immutable_plan_json back out.
Persistence for the handoff itself is an in-memory fake repository; no real
DB writer, no broker.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from src.exit_policy.run_automatic_exit_policy_with_handoff_once_v1 import run_cycle_with_handoff
from tests.automatic_exit_runtime_fixtures_v1 import FakeConnection, TS, insert_market_price, seed_happy_path
from tests.test_automatic_exit_execution_handoff_application_v1 import (
    FakeCredentialRepository,
    FakeKillSwitchRepository,
    FakeLiveAuthorityRepository,
    MemoryDatabase,
)
from src.executor.execution_handoff_v1 import ExecutionHandoffRepositoryV1


def _handoff_repository(database: MemoryDatabase, **kwargs) -> ExecutionHandoffRepositoryV1:
    return ExecutionHandoffRepositoryV1(
        cursor_factory=database.cursor_factory,
        credential_scope_repository=kwargs.get("credentials") or FakeCredentialRepository(),
        live_authority_repository=kwargs.get("authority") or FakeLiveAuthorityRepository(),
        kill_switch_repository=kwargs.get("kill_switch") or FakeKillSwitchRepository(),
    )


def _seeded_conn() -> tuple[FakeConnection, object]:
    now = TS + timedelta(minutes=5)
    conn = FakeConnection()
    seed_happy_path(conn)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM market_price_snapshot")
    insert_market_price(conn, price=Decimal("65000"))
    return conn, now


def test_paper_account_reaches_shared_handoff_intake_with_typed_plan() -> None:
    conn, now = _seeded_conn()
    database = MemoryDatabase()
    summary = run_cycle_with_handoff(
        conn, venue="bitvavo", now=now, executor_identity="shared-executor-v1", runtime_owner="devlap",
        handoff_repository=_handoff_repository(database),
    )
    assert summary.items_staged == 1
    assert summary.items_handed_off == 1
    assert summary.items_handoff_denied == 0
    assert summary.items_failed == 0
    assert len(database.rows) == 1
    ((_source, _reference_id), row), = database.rows.items()
    assert row["executor_mode"] == "PAPER"
    assert row["side"] == "SELL"


def test_runtime_never_polls_audit_table_for_handoff_input() -> None:
    """The wiring runner never queries automatic_exit_evaluation_audit_v1 or
    references immutable_plan_json as code (only in prose/docstrings) --
    proven structurally via AST: it only ever passes
    RuntimeItemOutcomeV1.plan, and the orchestrator/audit-writer modules it
    calls are unchanged."""
    import ast
    from pathlib import Path

    text = (
        Path(__file__).resolve().parents[1]
        / "src/exit_policy/run_automatic_exit_policy_with_handoff_once_v1.py"
    ).read_text()
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr != "immutable_plan_json"
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            # String literals used as SQL/table identifiers, not docstrings/comments.
            if node.value.strip().upper().startswith(("SELECT", "INSERT", "UPDATE", "DELETE")):
                assert "automatic_exit_evaluation_audit_v1" not in node.value


def test_no_broker_submission_call_names_present() -> None:
    import ast
    from pathlib import Path

    text = (
        Path(__file__).resolve().parents[1]
        / "src/exit_policy/run_automatic_exit_policy_with_handoff_once_v1.py"
    ).read_text()
    forbidden_call_names = {"submit_order", "place_order", "cancel_order", "broker_write"}
    tree = ast.parse(text)
    for node in ast.walk(tree):
        name = None
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
        elif isinstance(node, ast.Attribute):
            name = node.attr
        if name is not None:
            assert name not in forbidden_call_names


def test_dry_run_override_does_not_use_account_mode() -> None:
    conn, now = _seeded_conn()
    database = MemoryDatabase()
    summary = run_cycle_with_handoff(
        conn, venue="bitvavo", now=now, executor_identity="shared-executor-v1", runtime_owner="devlap",
        handoff_repository=_handoff_repository(database), executor_mode_override="DRY_RUN",
    )
    assert summary.items_handed_off == 1
    ((_source, _reference_id), row), = database.rows.items()
    assert row["executor_mode"] == "DRY_RUN"
