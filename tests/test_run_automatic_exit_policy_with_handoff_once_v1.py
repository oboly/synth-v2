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

import pytest

from src.execution_planner.automatic_exit_execution_handoff_application_v1 import (
    AutomaticExitExecutorModeError,
)
from src.exit_policy.run_automatic_exit_policy_with_handoff_once_v1 import (
    parse_args,
    run_cycle_with_handoff,
)
from tests.automatic_exit_runtime_fixtures_v1 import (
    FakeConnection,
    TS,
    insert_asset,
    insert_balance,
    insert_live_permission,
    insert_market_price,
    insert_position,
    seed_happy_path,
)
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


def _seeded_live_conn() -> tuple[FakeConnection, object]:
    conn, now = _seeded_conn()
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE trading_account SET account_mode='live', live_trading_enabled=1 WHERE trading_account_id=%s",
            (7,),
        )
    insert_live_permission(conn, account_id=7, live_execution_permitted=True)
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


# --- Mode-integrity fix: only DRY_RUN is a valid explicit override ------


def test_1_paper_account_with_no_override_reaches_paper_ordinary_intake() -> None:
    conn, now = _seeded_conn()
    database = MemoryDatabase()
    summary = run_cycle_with_handoff(
        conn, venue="bitvavo", now=now, executor_identity="shared-executor-v1", runtime_owner="devlap",
        handoff_repository=_handoff_repository(database),
    )
    assert summary.items_handed_off == 1
    ((_source, _reference_id), row), = database.rows.items()
    assert row["executor_mode"] == "PAPER"


def test_2_live_account_with_no_override_reaches_live_intake_live_authorized() -> None:
    conn, now = _seeded_live_conn()
    database = MemoryDatabase()
    authority = FakeLiveAuthorityRepository(permitted=True)
    summary = run_cycle_with_handoff(
        conn, venue="bitvavo", now=now, executor_identity="shared-executor-v1", runtime_owner="devlap",
        handoff_repository=_handoff_repository(database, authority=authority),
    )
    assert summary.items_staged == 1
    assert summary.items_handed_off == 1
    # LIVE authority resolution only happens on the intake_live_authorized path.
    assert len(authority.calls) == 1
    ((_source, _reference_id), row), = database.rows.items()
    assert row["executor_mode"] == "LIVE"


def test_3_paper_account_with_dry_run_override_reaches_dry_run_ordinary_intake() -> None:
    conn, now = _seeded_conn()
    database = MemoryDatabase()
    summary = run_cycle_with_handoff(
        conn, venue="bitvavo", now=now, executor_identity="shared-executor-v1", runtime_owner="devlap",
        handoff_repository=_handoff_repository(database), executor_mode_override="DRY_RUN",
    )
    assert summary.items_handed_off == 1
    ((_source, _reference_id), row), = database.rows.items()
    assert row["executor_mode"] == "DRY_RUN"


def test_4_live_account_with_dry_run_override_reaches_dry_run_only_after_live_gate_valid() -> None:
    """The DRY_RUN override still requires the real live decision_gate path
    (account-protection + live permission) to independently reach STAGED --
    the override only changes which executor_mode intake uses afterward, it
    never bypasses gate evaluation."""
    conn, now = _seeded_live_conn()
    database = MemoryDatabase()
    summary = run_cycle_with_handoff(
        conn, venue="bitvavo", now=now, executor_identity="shared-executor-v1", runtime_owner="devlap",
        handoff_repository=_handoff_repository(database), executor_mode_override="DRY_RUN",
    )
    assert summary.items_staged == 1
    assert summary.items_handed_off == 1
    ((_source, _reference_id), row), = database.rows.items()
    assert row["executor_mode"] == "DRY_RUN"


def test_5_paper_executor_mode_override_rejected_by_direct_python_caller() -> None:
    conn, now = _seeded_conn()
    database = MemoryDatabase()
    with pytest.raises(AutomaticExitExecutorModeError, match="EXECUTOR_MODE_OVERRIDE_MUST_BE_DRY_RUN_ONLY"):
        run_cycle_with_handoff(
            conn, venue="bitvavo", now=now, executor_identity="shared-executor-v1", runtime_owner="devlap",
            handoff_repository=_handoff_repository(database), executor_mode_override="PAPER",
        )
    assert database.rows == {}


def test_6_live_executor_mode_override_rejected_by_direct_python_caller() -> None:
    conn, now = _seeded_conn()
    database = MemoryDatabase()
    with pytest.raises(AutomaticExitExecutorModeError, match="EXECUTOR_MODE_OVERRIDE_MUST_BE_DRY_RUN_ONLY"):
        run_cycle_with_handoff(
            conn, venue="bitvavo", now=now, executor_identity="shared-executor-v1", runtime_owner="devlap",
            handoff_repository=_handoff_repository(database), executor_mode_override="LIVE",
        )
    assert database.rows == {}


def test_7_cli_parser_rejects_executor_mode_paper() -> None:
    with pytest.raises(SystemExit):
        parse_args(["--executor-identity", "x", "--runtime-owner", "y", "--executor-mode", "PAPER"])


def test_8_cli_parser_rejects_executor_mode_live() -> None:
    with pytest.raises(SystemExit):
        parse_args(["--executor-identity", "x", "--runtime-owner", "y", "--executor-mode", "LIVE"])


def test_9_cli_parser_accepts_executor_mode_dry_run() -> None:
    args = parse_args(["--executor-identity", "x", "--runtime-owner", "y", "--executor-mode", "DRY_RUN"])
    assert args.executor_mode == "DRY_RUN"


def test_10_no_override_preserves_current_account_mode_mapping() -> None:
    paper_conn, paper_now = _seeded_conn()
    live_conn, live_now = _seeded_live_conn()
    paper_database = MemoryDatabase()
    live_database = MemoryDatabase()
    run_cycle_with_handoff(
        paper_conn, venue="bitvavo", now=paper_now, executor_identity="shared-executor-v1", runtime_owner="devlap",
        handoff_repository=_handoff_repository(paper_database),
    )
    run_cycle_with_handoff(
        live_conn, venue="bitvavo", now=live_now, executor_identity="shared-executor-v1", runtime_owner="devlap",
        handoff_repository=_handoff_repository(live_database, authority=FakeLiveAuthorityRepository(permitted=True)),
    )
    ((_source, _reference_id), paper_row), = paper_database.rows.items()
    ((_source, _reference_id), live_row), = live_database.rows.items()
    assert paper_row["executor_mode"] == "PAPER"
    assert live_row["executor_mode"] == "LIVE"


def test_11_paper_cannot_reach_live_intake_and_live_cannot_reach_paper_intake_via_override() -> None:
    """No override value can decouple executor mode from account_mode/
    decision_gate: PAPER accounts can never reach intake_live_authorized and
    LIVE accounts can never reach ordinary PAPER intake through the override
    mechanism (the only override is DRY_RUN, which routes through ordinary
    intake regardless of account_mode)."""
    paper_conn, paper_now = _seeded_conn()
    live_conn, live_now = _seeded_live_conn()
    paper_database = MemoryDatabase()
    live_database = MemoryDatabase()
    run_cycle_with_handoff(
        paper_conn, venue="bitvavo", now=paper_now, executor_identity="shared-executor-v1", runtime_owner="devlap",
        handoff_repository=_handoff_repository(paper_database), executor_mode_override="DRY_RUN",
    )
    run_cycle_with_handoff(
        live_conn, venue="bitvavo", now=live_now, executor_identity="shared-executor-v1", runtime_owner="devlap",
        handoff_repository=_handoff_repository(live_database), executor_mode_override="DRY_RUN",
    )
    ((_source, _reference_id), paper_row), = paper_database.rows.items()
    ((_source, _reference_id), live_row), = live_database.rows.items()
    assert paper_row["executor_mode"] != "LIVE"
    assert live_row["executor_mode"] != "PAPER"


def test_12_credential_authority_kill_switch_ownership_and_no_broker_calls_unchanged() -> None:
    """#206 remains the sole owner of credential/LIVE-authority/kill-switch
    decisions; a denied fake still denies through this runner, and no broker
    call is ever made."""
    conn, now = _seeded_live_conn()
    database = MemoryDatabase()
    authority = FakeLiveAuthorityRepository(permitted=False)
    summary = run_cycle_with_handoff(
        conn, venue="bitvavo", now=now, executor_identity="shared-executor-v1", runtime_owner="devlap",
        handoff_repository=_handoff_repository(database, authority=authority),
    )
    assert summary.items_staged == 1
    assert summary.items_handoff_denied == 1
    assert summary.items_handed_off == 0
    assert database.rows == {}


# --- Issue #656: MANUAL_RFQ/MANUAL/NONE positions never reach handoff -----


def test_mixed_automated_and_manual_rfq_account_never_calls_handoff_for_manual_item(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A MANUAL_RFQ position (e.g. MDT) alongside an AUTOMATED position must
    be counted as items_manual_action_required and must never trigger
    submit_automatic_exit_plan_to_execution_handoff_v1; the AUTOMATED
    position is staged and handed off unaffected."""
    import src.exit_policy.run_automatic_exit_policy_with_handoff_once_v1 as runner_module

    conn, now = _seeded_conn()
    insert_asset(conn, asset_id=1372, symbol="MDT", execution_mode="MANUAL_RFQ")
    insert_position(
        conn, account_id=7, asset_id=1372, symbol="MDT",
        quantity_base=Decimal("40"), available_quantity_base=Decimal("40"),
    )
    insert_balance(conn, account_id=7, currency_code="MDT", available_amount=Decimal("40"))
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE account_state_snapshot_run_v1 SET position_snapshot_count = %s WHERE trading_account_id = %s",
            (2, 7),
        )

    handoff_calls: list[object] = []
    real_submit = runner_module.submit_automatic_exit_plan_to_execution_handoff_v1

    def spy_submit(*args, **kwargs):
        handoff_calls.append((args, kwargs))
        return real_submit(*args, **kwargs)

    monkeypatch.setattr(runner_module, "submit_automatic_exit_plan_to_execution_handoff_v1", spy_submit)

    database = MemoryDatabase()
    summary = run_cycle_with_handoff(
        conn, venue="bitvavo", now=now, executor_identity="shared-executor-v1", runtime_owner="devlap",
        handoff_repository=_handoff_repository(database),
    )

    assert summary.items_considered == 2
    assert summary.items_failed == 0
    assert not any("POSITION_MARKET_IDENTITY_MISSING" in failure for failure in summary.failures)
    assert summary.items_manual_action_required == 1
    assert summary.items_not_executable == 0
    assert summary.items_staged == 1
    assert summary.items_handed_off == 1
    assert any(
        "MANUAL_ACTION_REQUIRED" in line and "symbol=MDT" in line and "held_quantity_base=40" in line
        for line in summary.manual_actions
    )
    # Exactly one handoff call, for the AUTOMATED BTC item only.
    assert len(handoff_calls) == 1
    assert len(database.rows) == 1


def test_none_execution_mode_is_not_executable_and_never_calls_handoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.exit_policy.run_automatic_exit_policy_with_handoff_once_v1 as runner_module

    conn, now = _seeded_conn()
    insert_asset(conn, asset_id=301, symbol="DELISTED", execution_mode="NONE")
    insert_position(
        conn, account_id=7, asset_id=301, symbol="DELISTED",
        quantity_base=Decimal("5"), available_quantity_base=Decimal("5"),
    )
    insert_balance(conn, account_id=7, currency_code="DELISTED", available_amount=Decimal("5"))
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE account_state_snapshot_run_v1 SET position_snapshot_count = %s WHERE trading_account_id = %s",
            (2, 7),
        )

    handoff_calls: list[object] = []
    monkeypatch.setattr(
        runner_module,
        "submit_automatic_exit_plan_to_execution_handoff_v1",
        lambda *args, **kwargs: handoff_calls.append((args, kwargs)),
    )

    database = MemoryDatabase()
    summary = run_cycle_with_handoff(
        conn, venue="bitvavo", now=now, executor_identity="shared-executor-v1", runtime_owner="devlap",
        handoff_repository=_handoff_repository(database),
    )

    assert summary.items_failed == 0
    assert summary.items_not_executable == 1
    assert summary.items_manual_action_required == 0
    assert any("NOT_EXECUTABLE" in line and "symbol=DELISTED" in line for line in summary.manual_actions)
    # The AUTOMATED BTC item still stages and hands off normally.
    assert summary.items_staged == 1
    assert summary.items_handed_off == 1
    assert len(handoff_calls) == 1


def test_manual_only_account_makes_zero_handoff_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """An account holding only a MANUAL_RFQ position must make zero calls to
    submit_automatic_exit_plan_to_execution_handoff_v1 and zero handoff
    repository writes."""
    import src.exit_policy.run_automatic_exit_policy_with_handoff_once_v1 as runner_module

    now = TS + timedelta(minutes=5)
    conn = FakeConnection()
    seed_happy_path(conn)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM account_position_snapshot WHERE trading_account_id = %s", (7,))
    insert_asset(conn, asset_id=1372, symbol="MDT", execution_mode="MANUAL_RFQ")
    insert_position(
        conn, account_id=7, asset_id=1372, symbol="MDT",
        quantity_base=Decimal("40"), available_quantity_base=Decimal("40"),
    )
    insert_balance(conn, account_id=7, currency_code="MDT", available_amount=Decimal("40"))

    handoff_calls: list[object] = []
    monkeypatch.setattr(
        runner_module,
        "submit_automatic_exit_plan_to_execution_handoff_v1",
        lambda *args, **kwargs: handoff_calls.append((args, kwargs)),
    )

    database = MemoryDatabase()
    summary = run_cycle_with_handoff(
        conn, venue="bitvavo", now=now, executor_identity="shared-executor-v1", runtime_owner="devlap",
        handoff_repository=_handoff_repository(database),
    )

    assert summary.items_considered == 1
    assert summary.items_manual_action_required == 1
    assert summary.items_staged == 0
    assert summary.items_handed_off == 0
    assert handoff_calls == []
    assert database.rows == {}
