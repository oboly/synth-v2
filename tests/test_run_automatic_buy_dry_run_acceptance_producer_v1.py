"""Issue #471 end-to-end acceptance producer tests.

Real candidate -> automatic_buy_gate_v1 -> automatic_buy_planner_v1 ->
#206 shared handoff path against the shared Issue #474 sqlite fixtures.
Handoff persistence uses the generic in-memory ``MemoryDatabase``/fake
credential/authority/kill-switch repositories already shared by the
automatic-exit handoff-wiring tests; no real DB writer, no broker.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from src.entry_policy.automatic_buy_runtime_input_writer_v1 import AutomaticBuySourceEvidenceV1
from src.entry_policy.run_automatic_buy_dry_run_acceptance_producer_v1 import (
    EXECUTOR_IDENTITY,
    EXECUTOR_MODE,
    RUNTIME_OWNER,
    AutomaticBuySourceJsonError,
    parse_args,
    run_automatic_buy_dry_run_acceptance_producer_v1,
    source_from_json,
)
from src.executor.execution_handoff_v1 import ExecutionHandoffRepositoryV1
from tests.automatic_buy_account_allocation_evidence_fixtures_v1 import TS, FakeConnection, seed_happy_path
from tests.test_automatic_exit_execution_handoff_application_v1 import (
    FakeCredentialRepository,
    FakeKillSwitchRepository,
    FakeLiveAuthorityRepository,
    MemoryDatabase,
)

NOW = TS + timedelta(minutes=5)


def _handoff_repository(
    database: MemoryDatabase, *, credentials=None, authority=None, kill_switch=None,
) -> ExecutionHandoffRepositoryV1:
    return ExecutionHandoffRepositoryV1(
        cursor_factory=database.cursor_factory,
        credential_scope_repository=credentials or FakeCredentialRepository(denied=True),
        live_authority_repository=authority or FakeLiveAuthorityRepository(permitted=False),
        kill_switch_repository=kill_switch or FakeKillSwitchRepository(engaged=True),
    )


def _source(**overrides: object) -> AutomaticBuySourceEvidenceV1:
    base = dict(
        source_snapshot_key="a" * 64,
        evaluation_ts_utc=NOW,
        trading_account_id=7,
        venue="bitvavo",
        asset_id=101,
        market="BTC-EUR",
        strategy_bucket_id="SHORT_TERM_ROTATION",
        strategy_id="strategy-a",
        strategy_version="1",
        setup_id="setup-1",
        setup_ready=True,
        current_price=Decimal("50000"),
        entry_zone_low=Decimal("49000"),
        entry_zone_high=Decimal("51000"),
        re_entry_zone_low=None,
        re_entry_zone_high=None,
        setup_evidence_id="ev-1",
        setup_observed_ts_utc=NOW,
        source_provenance="test_producer",
    )
    base.update(overrides)
    return AutomaticBuySourceEvidenceV1(**base)


def _paper_conn() -> FakeConnection:
    conn = FakeConnection()
    seed_happy_path(conn)
    return conn


def _live_conn(*, live_trading_enabled: bool = False) -> FakeConnection:
    conn = FakeConnection()
    seed_happy_path(conn)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE trading_account SET account_mode='live', live_trading_enabled=%s WHERE trading_account_id=%s",
            (live_trading_enabled, 7),
        )
    return conn


# --- PAPER: reaches APPROVED + STAGED + DRY_RUN handoff, NULL binding -----


def test_paper_account_reaches_approved_staged_dry_run_handoff_null_binding() -> None:
    conn = _paper_conn()
    database = MemoryDatabase()
    result = run_automatic_buy_dry_run_acceptance_producer_v1(
        conn, source=_source(), handoff_repository=_handoff_repository(database),
    )
    assert result.candidate_state == "CANDIDATE"
    assert result.gate_state == "APPROVED"
    assert result.planner_state == "STAGED"
    assert result.handoff_id is not None
    assert result.executor_mode == "DRY_RUN" == EXECUTOR_MODE
    assert result.runtime_owner == "gurkdb" == RUNTIME_OWNER
    assert result.executor_identity == "shared-executor-v1" == EXECUTOR_IDENTITY
    assert result.executor_credential_binding_id is None
    assert len(database.rows) == 1
    ((_source_id, _reference_id), row), = database.rows.items()
    assert row["executor_mode"] == "DRY_RUN"
    assert row["executor_credential_binding_id"] is None


def test_dry_run_never_calls_credential_authority_or_kill_switch_repository() -> None:
    conn = _paper_conn()
    database = MemoryDatabase()
    credentials = FakeCredentialRepository(denied=True)
    authority = FakeLiveAuthorityRepository(permitted=False)
    kill_switch = FakeKillSwitchRepository(engaged=True)
    result = run_automatic_buy_dry_run_acceptance_producer_v1(
        conn,
        source=_source(),
        handoff_repository=_handoff_repository(
            database, credentials=credentials, authority=authority, kill_switch=kill_switch,
        ),
    )
    assert result.handoff_id is not None
    assert credentials.calls == []
    assert authority.calls == []
    assert kill_switch.calls == 0


# --- LIVE with live_trading_enabled=False: rejected before planner/handoff -


def test_live_account_with_live_trading_enabled_false_rejected_before_planner() -> None:
    conn = _live_conn(live_trading_enabled=False)
    database = MemoryDatabase()
    result = run_automatic_buy_dry_run_acceptance_producer_v1(
        conn, source=_source(), handoff_repository=_handoff_repository(database),
    )
    assert result.candidate_state == "CANDIDATE"
    assert result.gate_state == "NON_ACTIONABLE"
    assert result.gate_reason == "ACCOUNT_MODE_LIVE_FLAG_EVIDENCE_INCONSISTENT"
    assert result.planner_state == "NOT_REACHED"
    assert result.handoff_id is None
    assert database.rows == {}


# --- Operator cannot override account-owned/decision-gate-owned fields ----


@pytest.mark.parametrize(
    "forbidden_key,forbidden_value",
    [
        ("account_mode", "live"),
        ("live_trading_enabled", True),
        ("account_enabled", True),
        ("automatic_buy_execution_enabled", True),
        ("free_quote_balance_eur", "999999"),
        ("proposed_position_amount_eur", "999999"),
        ("current_bucket_amount_eur", "0"),
        ("current_open_positions", 0),
        ("current_asset_exposure_pct", "0"),
        ("max_automatic_buy_notional_eur", "999999"),
    ],
)
def test_operator_json_cannot_supply_account_owned_field(forbidden_key: str, forbidden_value: object) -> None:
    payload = _valid_json_payload()
    payload[forbidden_key] = forbidden_value
    with pytest.raises(AutomaticBuySourceJsonError, match="FORBIDDEN_ACCOUNT_OWNED_SOURCE_FIELDS"):
        source_from_json(payload)


def test_operator_json_rejects_unknown_field() -> None:
    payload = _valid_json_payload()
    payload["some_unexpected_field"] = "x"
    with pytest.raises(AutomaticBuySourceJsonError, match="UNKNOWN_SOURCE_FIELDS"):
        source_from_json(payload)


def test_operator_json_rejects_missing_field() -> None:
    payload = _valid_json_payload()
    del payload["current_price"]
    with pytest.raises(AutomaticBuySourceJsonError, match="MISSING_SOURCE_FIELDS"):
        source_from_json(payload)


def test_operator_json_valid_payload_parses_to_source_evidence() -> None:
    source = source_from_json(_valid_json_payload())
    assert source.trading_account_id == 7
    assert source.current_price == Decimal("50000")


def _valid_json_payload() -> dict[str, object]:
    return {
        "source_snapshot_key": "a" * 64,
        "evaluation_ts_utc": NOW.isoformat(),
        "trading_account_id": 7,
        "venue": "bitvavo",
        "asset_id": 101,
        "market": "BTC-EUR",
        "strategy_bucket_id": "SHORT_TERM_ROTATION",
        "strategy_id": "strategy-a",
        "strategy_version": "1",
        "setup_id": "setup-1",
        "setup_ready": True,
        "current_price": "50000",
        "entry_zone_low": "49000",
        "entry_zone_high": "51000",
        "re_entry_zone_low": None,
        "re_entry_zone_high": None,
        "setup_evidence_id": "ev-1",
        "setup_observed_ts_utc": NOW.isoformat(),
        "source_provenance": "test_producer",
    }


# --- Replay does not duplicate runtime input / audit / plan / handoff -----


def test_replay_does_not_duplicate_input_audit_plan_or_handoff() -> None:
    conn = _paper_conn()
    database = MemoryDatabase()
    repo = _handoff_repository(database)
    first = run_automatic_buy_dry_run_acceptance_producer_v1(conn, source=_source(), handoff_repository=repo)
    second = run_automatic_buy_dry_run_acceptance_producer_v1(conn, source=_source(), handoff_repository=repo)

    assert first.runtime_input_id == second.runtime_input_id
    assert first.handoff_id == second.handoff_id
    assert first.plan_reference_id == second.plan_reference_id
    assert first.plan_content_hash == second.plan_content_hash

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM automatic_buy_runtime_input_v1")
        assert cur.fetchone()["n"] == 1
        cur.execute("SELECT COUNT(*) AS n FROM automatic_buy_evaluation_audit_v1")
        assert cur.fetchone()["n"] == 1
    assert len(database.rows) == 1


# --- CLI surface never exposes executor_mode / runtime_owner / identity ---


def test_cli_parser_has_no_executor_mode_or_identity_override_flags() -> None:
    args = parse_args(["--input-json", "/tmp/does-not-matter.json"])
    assert not hasattr(args, "executor_mode")
    assert not hasattr(args, "runtime_owner")
    assert not hasattr(args, "executor_identity")


def test_cli_parser_rejects_unknown_override_flags() -> None:
    with pytest.raises(SystemExit):
        parse_args(["--input-json", "x.json", "--executor-mode", "LIVE"])
    with pytest.raises(SystemExit):
        parse_args(["--input-json", "x.json", "--runtime-owner", "someone-else"])


# --- Architecture guards ---------------------------------------------------


def test_producer_and_writer_import_no_broker_module() -> None:
    import ast
    from pathlib import Path

    files = (
        Path("src/entry_policy/automatic_buy_runtime_input_writer_v1.py"),
        Path("src/entry_policy/run_automatic_buy_dry_run_acceptance_producer_v1.py"),
    )
    for path in files:
        tree = ast.parse(path.read_text())
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        for name in imported:
            assert not name.startswith("src.broker"), f"{path}: forbidden broker import {name}"


def test_producer_never_calls_credential_resolution_by_name() -> None:
    import ast
    from pathlib import Path

    text = Path("src/entry_policy/run_automatic_buy_dry_run_acceptance_producer_v1.py").read_text()
    tree = ast.parse(text)
    forbidden_call_names = {"resolve", "submit_order", "place_order", "cancel_order"}
    for node in ast.walk(tree):
        name = None
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
        if name is not None:
            assert name not in forbidden_call_names
