from __future__ import annotations


import pytest as _pytest_authz


@_pytest_authz.fixture(autouse=True)
def _authorized_writer_context(monkeypatch):
    """Run write mechanics as an already-authorized writer capability. Denial is
    covered by tests/test_native_short_sql_helper_authorization_v1.py and
    tests/test_writer_capability_authorization_v1.py."""
    from tests.writer_auth_support import install_authorized_writer_context
    install_authorized_writer_context(monkeypatch)

import ast
import io
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from src.market_data import run_native_short_map_level_status_materializer_v1 as runner
from src.market_data.native_short_repository_source_identity_v1 import (
    NativeShortRepositorySourceState,
)
from src.market_data.native_short_map_level_status_materializer_v1 import (
    ACTIVE_EVALUATION,
    BLOCKED,
    PROJECTION_INVALID,
    PROJECTION_MISSING,
    MapLevelStatusMaterializationOutcome,
)


_AS_OF = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
_BTC_ARGS = [
    "--venue",
    "bitvavo",
    "--symbols",
    "BTC",
    "--quote-currency",
    "EUR",
    "--fib-trading-horizon",
    "SHORT",
    "--primary-interval",
    "4h",
    "--supporting-interval",
    "1h",
    "--execution-mode",
    "MANUAL",
    "--repository-commit",
    "a" * 40,
    "--trigger-ref",
    "map-level-test",
    "--output",
    "jsonl",
]


@pytest.fixture(autouse=True)
def _stub_writer_run_persistence(monkeypatch: pytest.MonkeyPatch) -> None:
    def start(provenance: Any, *, requested_scope_count: int, authorization: Any = None):
        return (
            runner.NativeShortRunBuilder(
                provenance=provenance,
                contract_version="native_short_map_level_status_v1",
                started_at_utc=_AS_OF,
                requested_scope_count=requested_scope_count,
            ),
            1,
        )

    def finish(builder: Any, run_id: int, *, terminal_status: Any, authorization: Any = None) -> None:
        builder.finish(finished_at_utc=_AS_OF, terminal_status=terminal_status)

    monkeypatch.setattr(runner, "_start_writer_run", start)
    monkeypatch.setattr(runner, "_finish_writer_run", finish)


class _FakeConn:
    def __init__(self) -> None:
        self.begin_count = 0
        self.commit_count = 0
        self.rollback_count = 0
        self.close_count = 0

    def begin(self) -> None:
        self.begin_count += 1

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1

    def close(self) -> None:
        self.close_count += 1


def _capture_main(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    monkeypatch.setattr(runner, "utc_now", lambda: _AS_OF)
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.stdout = stdout
    sys.stderr = stderr
    try:
        code = runner.main(
            argv,
            inspect_repository_source=lambda: NativeShortRepositorySourceState(
                head_sha="a" * 40,
                status_porcelain="",
            ),
        )
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
    return code, stdout.getvalue(), stderr.getvalue()


def _outcome(key: Any, *, branch: str = ACTIVE_EVALUATION, row_count: int = 3):
    return MapLevelStatusMaterializationOutcome(
        key=key,
        branch=branch,
        reason_code=None,
        row_count=row_count,
        current_map_id=71,
        map_cycle_id="btc-cycle",
        level_status_as_of_utc=_AS_OF,
    )


def _records_for_event(output: str, event: str) -> list[dict[str, Any]]:
    return [
        record
        for record in (json.loads(line) for line in output.splitlines())
        if record["event"] == event
    ]


def test_parse_args_accepts_exact_btc_scope() -> None:
    args = runner.parse_args(_BTC_ARGS)

    assert (
        args.venue,
        args.symbols,
        args.quote_currency,
        args.fib_trading_horizon,
        args.primary_interval,
        args.supporting_interval,
        args.output,
    ) == ("bitvavo", "BTC", "EUR", "SHORT", "4h", "1h", "jsonl")


def test_parse_symbols_is_explicit_deduplicated_and_deterministic() -> None:
    assert runner.parse_symbols("eth, BTC,eth, SOL") == ["BTC", "ETH", "SOL"]
    with pytest.raises(ValueError, match="at least one explicit symbol"):
        runner.parse_symbols(" , ")


@pytest.mark.parametrize(
    "missing_option",
    (
        "--venue",
        "--symbols",
        "--quote-currency",
        "--fib-trading-horizon",
        "--primary-interval",
        "--supporting-interval",
    ),
)
def test_parse_args_rejects_missing_required_scope_fields(missing_option: str) -> None:
    index = _BTC_ARGS.index(missing_option)
    argv = _BTC_ARGS[:index] + _BTC_ARGS[index + 2 :]
    with pytest.raises(SystemExit) as exc:
        runner.parse_args(argv)
    assert exc.value.code == 2


def test_parse_args_rejects_empty_required_scope_field() -> None:
    argv = list(_BTC_ARGS)
    argv[argv.index("--primary-interval") + 1] = "  "
    with pytest.raises(SystemExit) as exc:
        runner.parse_args(argv)
    assert exc.value.code == 2


def test_runner_calls_materializer_once_per_symbol_with_exact_full_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conns = [_FakeConn(), _FakeConn()]
    opened = iter(conns)
    calls: list[tuple[Any, Any, Any]] = []
    monkeypatch.setattr(runner, "get_connection", lambda: next(opened))

    def fake_materialize(conn: Any, *, key: Any, operational_clock: Any, provenance: Any):
        calls.append((conn, key, operational_clock))
        assert operational_clock() == _AS_OF
        return _outcome(key)

    monkeypatch.setattr(
        runner,
        "materialize_native_short_map_level_status_for_scope",
        fake_materialize,
    )
    argv = list(_BTC_ARGS)
    argv[argv.index("--symbols") + 1] = "ETH,BTC,ETH"

    code, out, err = _capture_main(monkeypatch, argv)

    assert code == 0
    assert err == ""
    assert [call[1].symbol for call in calls] == ["BTC", "ETH"]
    for _, key, _ in calls:
        assert (
            key.venue,
            key.quote_currency,
            key.fib_trading_horizon,
            key.primary_interval,
            key.supporting_interval,
        ) == ("bitvavo", "EUR", "SHORT", "4h", "1h")
    assert all(conn.begin_count == 1 for conn in conns)
    assert all(conn.commit_count == 1 for conn in conns)
    assert all(conn.rollback_count == 0 for conn in conns)
    assert all(conn.close_count == 1 for conn in conns)
    records = [json.loads(line) for line in out.splitlines()]
    assert records[-1]["event"] == "FINISHED"
    assert records[-1]["materialized"] == 2


@pytest.mark.parametrize(
    ("reason_code", "expected_detail"),
    (
        (PROJECTION_MISSING, "scope projection row missing"),
        (PROJECTION_INVALID, "selected map missing"),
        ("CONFIGURATION_UNAVAILABLE", "unsupported scope state blocks row emission"),
    ),
)
def test_runner_reports_blocked_states_as_failure(
    monkeypatch: pytest.MonkeyPatch,
    reason_code: str,
    expected_detail: str,
) -> None:
    conn = _FakeConn()
    monkeypatch.setattr(runner, "get_connection", lambda: conn)

    def fake_materialize(conn: Any, *, key: Any, operational_clock: Any, provenance: Any):
        return MapLevelStatusMaterializationOutcome(
            key=key,
            branch=BLOCKED,
            reason_code=reason_code,
            row_count=0,
            current_map_id=71,
            map_cycle_id="btc-cycle",
            level_status_as_of_utc=None,
        )

    monkeypatch.setattr(
        runner,
        "materialize_native_short_map_level_status_for_scope",
        fake_materialize,
    )

    code, out, err = _capture_main(monkeypatch, _BTC_ARGS)

    assert code == 1
    result = _records_for_event(out, "RESULT")[0]
    assert result["status"] == "blocked"
    assert result["row_count"] == 0
    assert expected_detail in result["detail"]
    assert json.loads(out.splitlines()[-1])["event"] == "FAILED"
    assert reason_code in err
    assert conn.commit_count == 1
    assert conn.rollback_count == 0


def test_runner_reports_missing_persistence_table_and_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeConn()
    monkeypatch.setattr(runner, "get_connection", lambda: conn)

    def fail_missing_table(conn: Any, *, key: Any, operational_clock: Any, provenance: Any):
        raise RuntimeError("Table 'synth.native_short_map_level_status_v1' doesn't exist")

    monkeypatch.setattr(
        runner,
        "materialize_native_short_map_level_status_for_scope",
        fail_missing_table,
    )

    code, out, err = _capture_main(monkeypatch, _BTC_ARGS)

    assert code == 1
    result = _records_for_event(out, "RESULT")[0]
    assert result["status"] == "failed"
    assert "native_short_map_level_status_v1" in result["detail"]
    assert "doesn't exist" in err
    assert conn.commit_count == 0
    assert conn.rollback_count == 1
    assert conn.close_count == 1


def test_runner_rolls_back_unexpected_success_row_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeConn()
    monkeypatch.setattr(runner, "get_connection", lambda: conn)
    monkeypatch.setattr(
        runner,
        "materialize_native_short_map_level_status_for_scope",
        lambda conn, *, key, operational_clock, provenance: _outcome(key, row_count=2),
    )

    code, out, _ = _capture_main(monkeypatch, _BTC_ARGS)

    assert code == 1
    result = _records_for_event(out, "RESULT")[0]
    assert result["reason_code"] == "UNEXPECTED_ROW_COUNT"
    assert conn.commit_count == 0
    assert conn.rollback_count == 1


def test_sigint_multi_symbol_run_emits_one_interrupted_summary_and_preserves_prior_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conns = [_FakeConn(), _FakeConn()]
    opened = iter(conns)
    monkeypatch.setattr(runner, "get_connection", lambda: next(opened))
    calls = 0

    def interrupt_second_symbol(conn: Any, *, key: Any, operational_clock: Any, provenance: Any):
        nonlocal calls
        calls += 1
        if calls == 2:
            runner.signal.raise_signal(runner.signal.SIGINT)
        return _outcome(key)

    monkeypatch.setattr(runner, "materialize_native_short_map_level_status_for_scope", interrupt_second_symbol)
    argv = list(_BTC_ARGS)
    argv[argv.index("--symbols") + 1] = "BTC,ETH"

    code, out, err = _capture_main(monkeypatch, argv)

    assert code == 130
    assert err == ""
    interrupted = _records_for_event(out, "INTERRUPTED")
    assert len(interrupted) == 1
    terminal = interrupted[0]
    assert terminal["status"] == "INTERRUPTED"
    assert terminal["interruption_signal"] == "SIGINT"
    assert terminal["symbols_requested"] == 2
    assert terminal["symbols_completed"] == 1
    assert terminal["symbols_remaining"] == 1
    assert conns[0].commit_count == 1
    assert conns[1].commit_count == 0
    assert conns[1].rollback_count == 1
    assert "Traceback" not in out + err


def test_sigterm_run_emits_one_interrupted_summary_and_rolls_back_active_symbol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeConn()
    monkeypatch.setattr(runner, "get_connection", lambda: conn)

    def interrupt_active_symbol(conn: Any, *, key: Any, operational_clock: Any, provenance: Any):
        runner.signal.raise_signal(runner.signal.SIGTERM)
        return _outcome(key)

    monkeypatch.setattr(runner, "materialize_native_short_map_level_status_for_scope", interrupt_active_symbol)

    code, out, err = _capture_main(monkeypatch, _BTC_ARGS)

    assert code == 143
    assert err == ""
    interrupted = _records_for_event(out, "INTERRUPTED")
    assert len(interrupted) == 1
    terminal = interrupted[0]
    assert terminal["interruption_signal"] == "SIGTERM"
    assert terminal["symbols_completed"] == 0
    assert terminal["symbols_remaining"] == 1
    assert conn.commit_count == 0
    assert conn.rollback_count == 1
    assert "Traceback" not in out + err


def test_successful_multi_symbol_run_reports_heartbeat_and_elapsed_timings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conns = [_FakeConn(), _FakeConn()]
    opened = iter(conns)
    monkeypatch.setattr(runner, "get_connection", lambda: next(opened))
    monkeypatch.setattr(
        runner,
        "materialize_native_short_map_level_status_for_scope",
        lambda conn, *, key, operational_clock, provenance: _outcome(key),
    )
    argv = list(_BTC_ARGS)
    argv[argv.index("--symbols") + 1] = "BTC,ETH"

    code, out, err = _capture_main(monkeypatch, argv)

    assert code == 0
    assert err == ""
    heartbeats = _records_for_event(out, "HEARTBEAT")
    assert len(heartbeats) == 4
    assert heartbeats[0]["current_phase"] == "BEFORE_SYMBOL"
    assert heartbeats[-1]["current_phase"] == "SYMBOL_COMPLETED"
    assert all({"rows_read", "rows_written", "total_elapsed_ms"} <= heartbeat.keys() for heartbeat in heartbeats)
    terminal = _records_for_event(out, "FINISHED")
    assert len(terminal) == 1
    assert terminal[0]["status"] == "SUCCESS"
    assert "MATERIALIZE_LEVEL_STATUS" in terminal[0]["phase_elapsed_ms_by_name"]
    assert "COMMIT_SYMBOL" in terminal[0]["phase_elapsed_ms_by_name"]
    assert "MATERIALIZE_LEVEL_STATUS" in terminal[0]["query_elapsed_ms_by_name"]
    assert terminal[0]["elapsed_ms"] >= 0
    assert set(terminal[0]["per_symbol_elapsed_ms"]) == {"BTC", "ETH"}


def test_single_symbol_run_emits_one_success_terminal_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    monkeypatch.setattr(runner, "get_connection", lambda: conn)
    monkeypatch.setattr(
        runner,
        "materialize_native_short_map_level_status_for_scope",
        lambda conn, *, key, operational_clock, provenance: _outcome(key),
    )

    code, out, err = _capture_main(monkeypatch, _BTC_ARGS)

    assert code == 0
    assert err == ""
    terminal = _records_for_event(out, "FINISHED")
    assert len(terminal) == 1
    assert terminal[0]["symbols_requested"] == 1
    assert terminal[0]["symbols_completed"] == 1
    assert terminal[0]["symbols_remaining"] == 0


def test_runner_reports_all_required_safety_markers(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    monkeypatch.setattr(runner, "get_connection", lambda: conn)
    monkeypatch.setattr(
        runner,
        "materialize_native_short_map_level_status_for_scope",
        lambda conn, *, key, operational_clock, provenance: _outcome(key),
    )

    code, out, _ = _capture_main(monkeypatch, _BTC_ARGS)

    assert code == 0
    started = json.loads(out.splitlines()[0])
    assert {key: started[key] for key in runner.SAFETY_MARKERS} == runner.SAFETY_MARKERS
    terminal = _records_for_event(out, "FINISHED")[0]
    assert {key: terminal[key] for key in runner.SAFETY_MARKERS} == runner.SAFETY_MARKERS


def test_runner_has_no_forbidden_imports_or_broad_materialization() -> None:
    root = Path(__file__).parent.parent
    runner_path = root / "src/market_data/run_native_short_map_level_status_materializer_v1.py"
    tree = ast.parse(runner_path.read_text(encoding="utf-8"))
    forbidden_imports = (
        "src.acc" + "ount",
        "src.bro" + "ker",
        "src.select" + "ion",
        "src.decision" + "_gate",
        "src.exec" + "ution",
        "src.reporting",
        "src.operations",
    )
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    # The shared writer-capability authorization guard is safety infrastructure,
    # not a forbidden account/reporting/operations layer.
    imported.discard("src.operations.writer_capability_authorization_v1")
    assert not any(
        module == forbidden or module.startswith(f"{forbidden}.")
        for module in imported
        for forbidden in forbidden_imports
    )

    source = runner_path.read_text(encoding="utf-8")
    assert "fetch_supported_scopes" not in source
    assert "materialize_all" not in source
    symbol_arguments = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add_argument"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "--symbols"
    ]
    assert len(symbol_arguments) == 1
    required_keyword = next(
        keyword for keyword in symbol_arguments[0].keywords if keyword.arg == "required"
    )
    assert isinstance(required_keyword.value, ast.Constant)
    assert required_keyword.value.value is True
    for forbidden_reference in ("subprocess", "systemd", "cron", "timer", "service"):
        assert forbidden_reference not in source.lower()


def test_pure_materializer_evaluator_does_not_read_wall_clock() -> None:
    root = Path(__file__).parent.parent
    path = root / "src/market_data/native_short_map_level_status_materializer_v1.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    pure_functions = {
        "select_gate_decision",
        "extract_v1_sell_geometry",
        "select_eligible_primary_candles",
        "classify_level_state",
        "build_level_status_rows",
    }
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name not in pure_functions:
            continue
        calls = {
            ast.unparse(call.func)
            for call in ast.walk(node)
            if isinstance(call, ast.Call)
        }
        assert "datetime.now" not in calls
        assert "datetime.utcnow" not in calls
