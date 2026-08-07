from __future__ import annotations

import ast
import io
import signal
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from src.market_data import run_native_short_scope_status_chain_v1 as runner
from src.market_data.native_short_repository_source_identity_v1 import (
    NativeShortRepositorySourceState,
)
from src.market_data.native_short_map_lifecycle_v1 import NativeShortMapScopeKey
from src.market_data.native_short_scope_status_materializer_v1 import ScopeChainOutcome
from src.market_data.native_short_scope_status_v1 import NativeShortMaterializerRunRecord
from src.market_data.native_short_writer_provenance_v1 import (
    CANONICAL_REPOSITORY_WRITER_OWNER,
    CHAIN_TRIGGER_TYPE,
    NativeShortWriterExecutionMode,
    NativeShortWriterProvenance,
)


ROOT = Path(__file__).parent.parent
CHAIN_PATH = ROOT / "scripts/run_chain_4h.sh"
WRAPPER_PATH = ROOT / "scripts/run_native_short_scope_status_chain_once.sh"


@pytest.fixture(autouse=True)
def _authorized_native_short_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """These wiring/smoke tests exercise the runtime adapter assuming the
    native_short_4h_chain capability is already authorized (an authorized
    PRODUCTION runtime). The mutation-boundary authorization itself — including
    UNASSIGNED denial for main() and execute_runtime() — is covered by
    tests/test_writer_capability_authorization_v1.py."""
    from tests.writer_auth_support import install_authorized_writer_context

    install_authorized_writer_context(monkeypatch)
    monkeypatch.setattr(
        runner,
        "capture_writer_commit_fences",
        lambda conn, scopes: (),
    )
    monkeypatch.setattr(
        runner,
        "revalidate_writer_commit_fences",
        lambda conn, expected_fences: None,
    )
RUNNER_PATH = ROOT / "src/market_data/run_native_short_scope_status_chain_v1.py"
SERVICE_PATH = ROOT / "deploy/systemd/synth-chain-4h.service"
TIMER_PATH = ROOT / "deploy/systemd/synth-chain-4h.timer"
_AS_OF = datetime(2026, 7, 12, 8, 15, tzinfo=UTC)
_BTC = NativeShortMapScopeKey(
    venue="bitvavo",
    symbol="BTC",
    quote_currency="EUR",
    fib_trading_horizon="SHORT",
    primary_interval="4h",
    supporting_interval="1h",
)
_PROVENANCE = NativeShortWriterProvenance(
    writer_entrypoint="scripts/run_chain_4h.sh",
    repository_writer_owner=CANONICAL_REPOSITORY_WRITER_OWNER,
    runner_name=runner.RUNNER_NAME,
    runner_version=runner.RUNNER_VERSION,
    execution_mode=NativeShortWriterExecutionMode.CHAIN,
    invocation_uuid="30000000-0000-4000-8000-000000000001",
    repository_commit_sha="a" * 40,
    host_name="test-host",
    process_id=1,
    trigger_type=CHAIN_TRIGGER_TYPE,
    trigger_ref="scripts/run_chain_4h.sh",
)
_CLI_PROVENANCE_ARGS = [
    "--execution-mode", "CHAIN",
    "--writer-entrypoint", "scripts/run_chain_4h.sh",
    "--repository-commit", "a" * 40,
    "--trigger-type", CHAIN_TRIGGER_TYPE,
    "--trigger-ref", "scripts/run_chain_4h.sh",
]


def _inspect_clean_source() -> NativeShortRepositorySourceState:
    return NativeShortRepositorySourceState(head_sha="a" * 40, status_porcelain="")


class _FakeConn:
    """Transaction-accurate fake: staged per-scope ledger writes only become
    visible on commit and are discarded on rollback, so a forced failure in one
    scope can be proven not to disturb any other scope's committed ledger."""

    def __init__(self) -> None:
        self.begin_count = 0
        self.commit_count = 0
        self.rollback_count = 0
        self.close_count = 0
        self.committed_ledger: dict[str, dict[str, Any]] = {}
        self._pending: dict[str, dict[str, Any]] = {}

    def begin(self) -> None:
        self.begin_count += 1
        self._pending = {}

    def commit(self) -> None:
        self.commit_count += 1
        self.committed_ledger.update(self._pending)
        self._pending = {}

    def rollback(self) -> None:
        self.rollback_count += 1
        self._pending = {}

    def stage(self, scope_label: str, row: dict[str, Any]) -> None:
        self._pending[scope_label] = row

    def close(self) -> None:
        self.close_count += 1


def _scope(symbol: str) -> NativeShortMapScopeKey:
    return NativeShortMapScopeKey(
        venue="bitvavo",
        symbol=symbol,
        quote_currency="EUR",
        fib_trading_horizon="SHORT",
        primary_interval="4h",
        supporting_interval="1h",
    )


def _chain_outcome(
    key: NativeShortMapScopeKey,
    *,
    skipped_not_supported: bool = False,
    failed: bool = False,
) -> ScopeChainOutcome:
    return ScopeChainOutcome(
        key=key,
        skipped_not_supported=skipped_not_supported,
        published_map=False,
        lifecycle_event_appended=False,
        failed=failed,
    )


def _install_chain_doubles(
    monkeypatch: pytest.MonkeyPatch,
    conn: _FakeConn,
    scopes: list[NativeShortMapScopeKey],
    scope_fn: Any,
) -> list[tuple[int, NativeShortMaterializerRunRecord]]:
    """Wire execute_runtime to fakes at the new per-scope call boundary and
    return the list of (run_id, record) terminalizations that were performed."""
    finalized: list[tuple[int, NativeShortMaterializerRunRecord]] = []
    monkeypatch.setattr(runner, "get_connection", lambda: conn)
    monkeypatch.setattr(runner, "fetch_supported_scope_keys", lambda *a, **k: list(scopes))
    monkeypatch.setattr(runner, "_insert_run", lambda connection, record, **k: 4242)
    monkeypatch.setattr(
        runner,
        "_finalize_run",
        lambda connection, run_id, record, **k: finalized.append((run_id, record)),
    )
    monkeypatch.setattr(runner, "evaluate_and_project_scope", scope_fn)
    return finalized


def _forced_failure_scope_fn(failures: dict[str, BaseException]) -> Any:
    """Per-scope double that stages a realistic two-row scope ledger and
    raises a forced failure for exactly the named symbols."""

    def _scope_fn(connection: Any, **kwargs: Any) -> ScopeChainOutcome:
        key = kwargs["key"]
        connection.stage(
            key.symbol,
            {"observation": key.symbol, "status_projection": key.symbol},
        )
        forced = failures.get(key.symbol)
        if forced is not None:
            raise forced
        return _chain_outcome(key)

    return _scope_fn


def _execute(**overrides: Any) -> runner.RuntimeResult:
    kwargs: dict[str, Any] = {
        "venue": "bitvavo",
        "symbols": [],
        "quote_currency": "EUR",
        "fib_trading_horizon": "SHORT",
        "primary_interval": "4h",
        "supporting_interval": "1h",
        "as_of_utc": _AS_OF,
        "provenance": _PROVENANCE,
    }
    kwargs.update(overrides)
    return runner.execute_runtime(**kwargs)


def _finished_run() -> NativeShortMaterializerRunRecord:
    return NativeShortMaterializerRunRecord(
        provenance=_PROVENANCE,
        contract_version="native_short_scope_status_v1",
        started_at_utc=_AS_OF,
        requested_scope_count=1,
        terminal_status="FINISHED",
        finished_at_utc=_AS_OF,
        observed_scope_count=1,
        published_map_count=0,
        lifecycle_event_count=0,
        failed_scope_count=0,
    )


def test_canonical_service_keeps_single_timer_and_invokes_native_chain_in_order() -> None:
    chain = CHAIN_PATH.read_text(encoding="utf-8")
    service = SERVICE_PATH.read_text(encoding="utf-8")
    timer = TIMER_PATH.read_text(encoding="utf-8")

    price_validation = "python -m src.operations.run_persisted_market_price_freshness_v1"
    candle_validation = "python -m src.operations.run_persisted_market_candle_freshness_v1"
    source_verification = "python -m src.market_data.native_short_repository_source_identity_v1"
    native = "bash scripts/run_native_short_scope_status_chain_once.sh"
    snapshot = "python -m src.market_data.run_native_short_fib_context_snapshot_v1"
    features = "python -m src.features.run_feat_candle"
    assert (
        chain.index(source_verification)
        < chain.index(price_validation)
        < chain.index(candle_validation)
        < chain.index(native)
        < chain.index(snapshot)
        < chain.index(features)
    )
    assert "src.market_data.run_market_price_snapshot_v1" not in chain
    assert "src.etl.bitvavo.run_candles_etl" not in chain
    assert "scripts/run_chain_4h.sh" in service
    assert "Unit=synth-chain-4h.service" in timer
    assert "native-short" not in service.lower()
    assert "native-short" not in timer.lower()
    assert 'NATIVE_SHORT_REPOSITORY_COMMIT="$(git rev-parse --verify HEAD)"' in chain
    assert 'SYNTH_NATIVE_SHORT_WRITER_ENTRYPOINT="scripts/run_chain_4h.sh"' in chain
    assert 'SYNTH_NATIVE_SHORT_TRIGGER_REF="scripts/run_chain_4h.sh"' in chain


def test_canonical_service_and_chain_exclude_reporting_remote_and_account_paths() -> None:
    combined = "\n".join(
        (
            CHAIN_PATH.read_text(encoding="utf-8"),
            SERVICE_PATH.read_text(encoding="utf-8"),
        )
    ).lower()
    for forbidden in (
        "synth_paper_advice_dashboard",
        "src.reporting",
        "publish_paper_advice_dashboard_to_odroid",
        "odroid",
        "ssh",
        "scp",
        "src.account",
        "decision_gate",
        "execution_planner",
        "src.executor",
        "src.broker",
        "order_submission",
    ):
        assert forbidden not in combined
    assert "environment=synth_live_execution_permission=not_granted" in combined
    assert "environment=synth_broker_write_permission=not_granted" in combined


def test_wrapper_has_native_lock_exact_scope_defaults_and_safety_markers() -> None:
    source = WRAPPER_PATH.read_text(encoding="utf-8")
    assert "/tmp/synth-native-short-scope-status-chain-v1.lock" in source
    assert "flock -n 9" in source
    assert "reason=LOCK_HELD exit_status=75" in source
    assert "python -m src.market_data.run_native_short_scope_status_chain_v1" in source
    for argument in (
        "--venue bitvavo",
        "--quote-currency EUR",
        "--fib-trading-horizon SHORT",
        "--primary-interval 4h",
        "--supporting-interval 1h",
        "--execution-mode CHAIN",
        '--writer-entrypoint "${WRITER_ENTRYPOINT}"',
        '--repository-commit "${REPOSITORY_COMMIT}"',
        "--trigger-type REPOSITORY_4H_MARKET_CHAIN",
        '--trigger-ref "${TRIGGER_REF}"',
    ):
        assert argument in source
    assert "SCHEDULED_4H_MARKET_CHAIN" not in source
    assert "git rev-parse --verify HEAD" in source
    assert "systemctl" not in source
    for marker in (
        "broker_private_calls=0",
        "broker_writes=0",
        "order_submission=0",
        "live_orders=0",
        "decision_gate=none",
        "execution_planner=none",
        "executor=none",
    ):
        assert marker in source
    assert "STARTED runner=" in source
    assert "mode=market_data_write" in source
    assert "worker_count=1" in source
    assert "FINISHED runner=" in source
    assert "FAILED runner=" in source


def test_runtime_adapter_calls_pr79_orchestrator_for_supported_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per-scope call boundary receives the exact canonical scope and the same
    canonical ledger readers as before, and one supported scope produces
    exactly four transactions: setup, run row, the scope itself, finalize."""
    conn = _FakeConn()
    captured: dict[str, Any] = {}

    def fake_scope(connection: Any, **kwargs: Any) -> ScopeChainOutcome:
        captured.update(kwargs)
        assert connection is conn
        return _chain_outcome(kwargs["key"])

    _install_chain_doubles(monkeypatch, conn, [_BTC], fake_scope)

    result = _execute(symbols=["BTC"])

    assert captured["key"] == _BTC
    assert captured["run_id"] == 4242
    assert captured["as_of_utc"] == _AS_OF
    assert captured["fetch_existing_maps"] is runner.map_materializer._fetch_maps_for_scope
    assert (
        captured["fetch_existing_generation_events"]
        is runner.map_materializer._fetch_generation_events_for_scope
    )
    assert (
        captured["fetch_existing_lifecycle_events"]
        is runner.map_materializer._fetch_lifecycle_events_for_map_ids
    )
    assert result.map_level_status_row_count == 3
    assert [item.status for item in result.scope_results] == [runner.SCOPE_STATUS_SUCCEEDED]
    assert conn.begin_count == 4
    assert conn.commit_count == 4
    assert conn.rollback_count == 0
    assert conn.close_count == 1


def test_runtime_adapter_records_skipped_not_supported_scope_unambiguously(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeConn()
    _install_chain_doubles(
        monkeypatch,
        conn,
        [_BTC],
        lambda connection, **kwargs: _chain_outcome(kwargs["key"], skipped_not_supported=True),
    )

    result = _execute(symbols=["BTC"])

    assert [item.status for item in result.scope_results] == [
        runner.SCOPE_STATUS_SKIPPED_NOT_SUPPORTED
    ]
    assert result.run.observed_scope_count == 0
    assert result.run.terminal_status == "FINISHED"


def test_exact_btc_smoke_arguments_and_terminal_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_execute(**kwargs: Any) -> runner.RuntimeResult:
        captured.update(kwargs)
        return runner.RuntimeResult(
            run=_finished_run(),
            selected_scope_count=1,
            candle_rows_read=72,
            elapsed_ms=15,
        )

    monkeypatch.setattr(runner, "execute_runtime", fake_execute)
    stdout = io.StringIO()
    previous_stdout = sys.stdout
    sys.stdout = stdout
    try:
        code = runner.main(
            [
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
                "--as-of-utc",
                _AS_OF.isoformat(),
                *_CLI_PROVENANCE_ARGS,
            ],
            inspect_repository_source=_inspect_clean_source,
        )
    finally:
        sys.stdout = previous_stdout

    assert code == 0
    assert captured["symbols"] == ["BTC"]
    assert captured["as_of_utc"] == _AS_OF
    output = stdout.getvalue()
    assert "event=STARTED" in output
    assert "mode=market_data_write" in output
    assert "worker_count=1" in output
    assert "scope_mode=EXPLICIT_SYMBOLS" in output
    assert "event=FINISHED" in output
    assert "map_level_status_rows=3" in output
    assert "exit_status=0" in output


def test_runtime_adapter_commits_expected_domain_blocked_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MAP_LEVEL_STATUS_BLOCKED remains the explicit domain-blocked contract
    and a hard stop for the run. Only the blocked scope's own transaction is
    discarded; the run row (committed before any scope work) is still
    terminalized FAILED with the unchanged blocked-domain failure shape."""
    conn = _FakeConn()
    finalized = _install_chain_doubles(
        monkeypatch,
        conn,
        [_BTC],
        lambda connection, **kwargs: (_ for _ in ()).throw(
            runner.NativeShortMapLevelStatusBlockedError("MAP_LEVEL_STATUS_BLOCKED symbol=BTC")
        ),
    )

    with pytest.raises(runner.RuntimeScopeEvaluationError, match="FAILED_SCOPES"):
        _execute(symbols=["BTC"])

    assert conn.begin_count == 4  # setup, run row, blocked scope, finalize
    assert conn.commit_count == 3  # the blocked scope's transaction is not one
    assert conn.rollback_count == 1
    assert conn.close_count == 1
    assert conn.committed_ledger == {}

    (_run_id, record) = finalized[0]
    assert record.terminal_status == "FAILED"
    assert record.failure_reason_code == "NativeShortMapLevelStatusBlockedError"
    assert "MAP_LEVEL_STATUS_BLOCKED" in record.failure_detail
    assert record.failed_scope_count == 1


def test_blocked_scope_stops_the_run_and_leaves_later_scopes_unattempted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit reviewed orchestration policy: BLOCKED stops the loop, while
    an unexpected failure continues it."""
    conn = _FakeConn()
    attempted: list[str] = []

    def fake_scope(connection: Any, **kwargs: Any) -> ScopeChainOutcome:
        key = kwargs["key"]
        attempted.append(key.symbol)
        if key.symbol == "ETH":
            raise runner.NativeShortMapLevelStatusBlockedError("MAP_LEVEL_STATUS_BLOCKED")
        connection.stage(key.symbol, {"observation": key.symbol})
        return _chain_outcome(key)

    _install_chain_doubles(
        monkeypatch, conn, [_scope("BTC"), _scope("ETH"), _scope("XRP")], fake_scope
    )

    with pytest.raises(runner.RuntimeScopeEvaluationError):
        _execute()

    assert attempted == ["BTC", "ETH"]
    assert set(conn.committed_ledger) == {"BTC"}


def test_unexpected_scope_failure_is_isolated_and_run_still_finalizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Core #200 acceptance criterion: an unexpected failure in scope 2 rolls
    back only scope 2's transaction. Scope 1 stays committed, the run row is
    still terminalized, and the outer result exposes both outcomes."""
    conn = _FakeConn()
    finalized = _install_chain_doubles(
        monkeypatch,
        conn,
        [_scope("BTC"), _scope("ETH")],
        _forced_failure_scope_fn({"ETH": RuntimeError("UNEXPECTED_DB_FAILURE")}),
    )

    with pytest.raises(runner.RuntimeScopeEvaluationError, match="FAILED_SCOPES count=1"):
        _execute()

    # setup + run row + 2 scopes + finalize
    assert conn.begin_count == 5
    # everything except the failed scope's transaction
    assert conn.commit_count == 4
    assert conn.rollback_count == 1
    assert conn.close_count == 1
    assert set(conn.committed_ledger) == {"BTC"}

    (_run_id, record) = finalized[0]
    assert record.terminal_status == "FAILED"
    assert record.failure_reason_code == runner.UNEXPECTED_FAILURE_REASON_CODE
    assert "bitvavo:ETH" in record.failure_detail
    assert "RuntimeError" in record.failure_detail
    assert record.observed_scope_count == 2
    assert record.failed_scope_count == 1


def test_unexpected_scope_failure_does_not_suppress_later_scopes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Continue policy plus the literal acceptance criterion: scope 3 is still
    evaluated after scope 2 crashes, and scope 1's and scope 3's ledgers are
    present, correct, and untouched by scope 2's rollback."""
    conn = _FakeConn()
    scopes = [_scope("BTC"), _scope("ETH"), _scope("XRP")]
    _install_chain_doubles(
        monkeypatch, conn, scopes, _forced_failure_scope_fn({"ETH": ValueError("FORCED")})
    )

    with pytest.raises(runner.RuntimeScopeEvaluationError):
        _execute()

    assert conn.committed_ledger == {
        "BTC": {"observation": "BTC", "status_projection": "BTC"},
        "XRP": {"observation": "XRP", "status_projection": "XRP"},
    }
    assert conn.begin_count == 6  # setup + run row + 3 scopes + finalize
    assert conn.commit_count == 5
    assert conn.rollback_count == 1


def test_unexpected_scope_result_evidence_is_unambiguous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeConn()
    scopes = [_scope("BTC"), _scope("ETH"), _scope("XRP")]
    _install_chain_doubles(
        monkeypatch, conn, scopes, _forced_failure_scope_fn({"ETH": ValueError("FORCED")})
    )

    events: list[dict[str, Any]] = []
    with pytest.raises(runner.RuntimeScopeEvaluationError) as excinfo:
        _execute(progress=events.append)

    scope_events = [event for event in events if event["event"] == "SCOPE_RESULT"]
    assert [(event["scope"], event["status"]) for event in scope_events] == [
        ("bitvavo:BTC", runner.SCOPE_STATUS_SUCCEEDED),
        ("bitvavo:ETH", runner.SCOPE_STATUS_UNEXPECTED_FAILED),
        ("bitvavo:XRP", runner.SCOPE_STATUS_SUCCEEDED),
    ]
    assert all(event["elapsed_ms"] >= 0 for event in scope_events)
    assert "FAILED_SCOPES" in str(excinfo.value)


def test_retrying_a_previously_failed_scope_succeeds_without_touching_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retry is deterministic: attempt 1 fails ETH only, attempt 2 (a fresh
    invocation over the same scopes) completes every scope cleanly and appends
    no duplicate terminal evidence, because each scope's writes were either
    fully committed or fully discarded."""
    scopes = [_scope("BTC"), _scope("ETH"), _scope("XRP")]

    first_conn = _FakeConn()
    _install_chain_doubles(
        monkeypatch, first_conn, scopes, _forced_failure_scope_fn({"ETH": RuntimeError("FLAKE")})
    )
    with pytest.raises(runner.RuntimeScopeEvaluationError):
        _execute()
    assert set(first_conn.committed_ledger) == {"BTC", "XRP"}

    second_conn = _FakeConn()
    finalized = _install_chain_doubles(
        monkeypatch, second_conn, scopes, _forced_failure_scope_fn({})
    )
    result = _execute()

    assert set(second_conn.committed_ledger) == {"BTC", "ETH", "XRP"}
    assert second_conn.rollback_count == 0
    assert [item.status for item in result.scope_results] == [
        runner.SCOPE_STATUS_SUCCEEDED
    ] * 3
    (_run_id, record) = finalized[0]
    assert record.terminal_status == "FINISHED"
    assert record.failed_scope_count == 0
    # Exactly one terminalization per invocation: the retry cannot duplicate
    # terminal run evidence.
    assert len(finalized) == 1


def test_soft_degraded_scope_still_terminalizes_finished(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Existing soft-degrade semantics preserved: an expected per-scope
    business failure stays committed as observation evidence and the run is
    FINISHED, not FAILED, while still surfacing a non-zero failed scope count
    to the caller."""
    conn = _FakeConn()
    finalized = _install_chain_doubles(
        monkeypatch,
        conn,
        [_BTC],
        lambda connection, **kwargs: _chain_outcome(kwargs["key"], failed=True),
    )

    with pytest.raises(runner.RuntimeScopeEvaluationError):
        _execute(symbols=["BTC"])

    (_run_id, record) = finalized[0]
    assert record.terminal_status == "FINISHED"
    assert record.failed_scope_count == 1
    assert conn.rollback_count == 0


def test_runtime_adapter_rolls_back_on_keyboard_interrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A SIGINT/SIGTERM-triggered KeyboardInterrupt must roll back only the
    in-flight scope, abort the remaining scopes, best-effort terminalize the
    already-committed run row as INTERRUPTED, and propagate."""
    conn = _FakeConn()
    attempted: list[str] = []

    def fake_scope(connection: Any, **kwargs: Any) -> ScopeChainOutcome:
        key = kwargs["key"]
        attempted.append(key.symbol)
        connection.stage(key.symbol, {"observation": key.symbol})
        if key.symbol == "ETH":
            raise KeyboardInterrupt("SIGTERM")
        return _chain_outcome(key)

    finalized = _install_chain_doubles(
        monkeypatch, conn, [_scope("BTC"), _scope("ETH"), _scope("XRP")], fake_scope
    )

    with pytest.raises(KeyboardInterrupt):
        _execute()

    assert attempted == ["BTC", "ETH"]
    assert conn.committed_ledger == {"BTC": {"observation": "BTC"}}
    assert conn.rollback_count == 1
    assert conn.close_count == 1
    (_run_id, record) = finalized[0]
    assert record.terminal_status == "INTERRUPTED"


def test_runtime_wiring_imports_only_market_data_and_common_db() -> None:
    tree = ast.parse(RUNNER_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    forbidden = (
        "src.reporting",
        "src.selection",
        "src.decision_gate",
        "src.execution_planner",
        "src.executor",
        "src.agents",
        "src.broker",
        "src.account",
    )
    assert not any(
        module == prefix or module.startswith(f"{prefix}.")
        for module in imported
        for prefix in forbidden
    )
    assert all(
        not module.startswith("src.")
        or module == "src.common.db"
        or module.startswith("src.market_data")
        # Shared writer-capability authorization boundary (safety infrastructure,
        # not a forbidden reporting/account/execution layer).
        or module == "src.operations.writer_capability_authorization_v1"
        for module in imported
    )


def test_wiring_adds_no_reporting_or_execution_command() -> None:
    wrapper = WRAPPER_PATH.read_text(encoding="utf-8")
    native_line = next(
        line for line in CHAIN_PATH.read_text(encoding="utf-8").splitlines()
        if "run_native_short_scope_status_chain_once.sh" in line
    )
    combined = f"{wrapper}\n{native_line}".lower()
    for forbidden_command in (
        "src.reporting",
        "src.selection",
        "src.decision_gate",
        "src.execution_planner",
        "src.executor",
        "src.broker",
        "src.account",
    ):
        assert forbidden_command not in combined


def test_scope_selection_is_persisted_supported_registry_not_enabled_assets() -> None:
    source = RUNNER_PATH.read_text(encoding="utf-8")
    selection = source.split("def fetch_supported_scope_keys", 1)[1].split(
        "def _fetch_candles", 1
    )[0]
    assert "FROM native_short_map_scope_v1" in selection
    assert "scope_support_state = 'SUPPORTED'" in selection
    assert "FROM asset" not in selection
    assert "is_enabled" not in selection


def test_execute_runtime_reports_phase_start_and_end_when_progress_supplied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeConn()
    _install_chain_doubles(
        monkeypatch,
        conn,
        [_BTC],
        lambda connection, **kwargs: _chain_outcome(kwargs["key"]),
    )

    events: list[dict[str, Any]] = []
    _execute(symbols=["BTC"], progress=events.append)

    phases = [(event["event"], event.get("phase")) for event in events]
    assert ("PHASE_START", "FETCH_SUPPORTED_SCOPES") in phases
    assert ("PHASE_END", "FETCH_SUPPORTED_SCOPES") in phases
    assert ("PHASE_START", "ORCHESTRATOR_RUN") in phases
    assert ("PHASE_END", "ORCHESTRATOR_RUN") in phases
    assert phases.index(("PHASE_END", "FETCH_SUPPORTED_SCOPES")) < phases.index(
        ("PHASE_START", "ORCHESTRATOR_RUN")
    )
    orchestrator_end = next(event for event in events if event.get("phase") == "ORCHESTRATOR_RUN" and event["event"] == "PHASE_END")
    assert orchestrator_end["observed_scopes"] == 1
    assert orchestrator_end["published_maps"] == 0
    assert orchestrator_end["failed_scopes"] == 0
    for event in events:
        if event["event"] == "PHASE_END":
            assert "elapsed_ms" in event
        assert event["runner"] == runner.RUNNER_NAME


def test_execute_runtime_reports_bounded_candle_query_timings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeConn()
    monkeypatch.setattr(runner, "_fetch_candles", lambda *a, **k: ())

    def fake_scope(connection: Any, **kwargs: Any) -> ScopeChainOutcome:
        kwargs["fetch_primary_candle_close_timestamps"](_BTC, _AS_OF)
        return _chain_outcome(kwargs["key"])

    _install_chain_doubles(monkeypatch, conn, [_BTC], fake_scope)

    events: list[dict[str, Any]] = []
    _execute(symbols=["BTC"], progress=events.append)

    query_events = [event for event in events if event["event"] == "QUERY"]
    assert [event["interval"] for event in query_events] == ["4h", "1h"]
    assert all(event["phase"] == "FETCH_CANDLES" for event in query_events)
    assert all(event["scope"] == "bitvavo:BTC" for event in query_events)
    assert all(event["rows_read"] == 0 for event in query_events)
    assert all(event["query_elapsed_ms"] >= 0 for event in query_events)
    assert all(event["elapsed_ms"] >= event["query_elapsed_ms"] for event in query_events)


def test_execute_runtime_without_progress_never_starts_heartbeat_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Existing tests/callers that omit progress must see zero behavioral
    change: no background thread, no callback overhead."""
    conn = _FakeConn()
    _install_chain_doubles(
        monkeypatch,
        conn,
        [_BTC],
        lambda connection, **kwargs: _chain_outcome(kwargs["key"]),
    )

    threads_before = threading.active_count()
    _execute(symbols=["BTC"])
    assert threading.active_count() == threads_before


def test_heartbeat_emitter_invokes_callback_periodically() -> None:
    invocation_count = 0
    invoked = threading.Event()

    def _callback() -> None:
        nonlocal invocation_count
        invocation_count += 1
        invoked.set()

    heartbeat = runner._HeartbeatEmitter(interval_seconds=0.01, callback=_callback)
    heartbeat.start()
    try:
        assert invoked.wait(timeout=2.0), "heartbeat callback never fired"
    finally:
        heartbeat.stop()

    assert invocation_count >= 1


def test_sigterm_handler_raises_keyboard_interrupt_with_signal_name() -> None:
    with pytest.raises(KeyboardInterrupt, match="SIGTERM"):
        runner._handle_sigterm(signal.SIGTERM, None)


def test_interruption_signal_name_defaults_to_sigint_for_bare_keyboard_interrupt() -> None:
    assert runner._interruption_signal_name(KeyboardInterrupt()) == "SIGINT"
    assert runner._interruption_signal_name(KeyboardInterrupt("SIGTERM")) == "SIGTERM"


def test_main_reports_sigint_with_exit_130(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        runner,
        "execute_runtime",
        lambda **kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    stdout = io.StringIO()
    previous_stdout = sys.stdout
    sys.stdout = stdout
    try:
        code = runner.main(
            [
                "--venue", "bitvavo",
                "--symbols", "BTC",
                "--quote-currency", "EUR",
                "--fib-trading-horizon", "SHORT",
                "--primary-interval", "4h",
                "--supporting-interval", "1h",
                "--as-of-utc", _AS_OF.isoformat(),
                *_CLI_PROVENANCE_ARGS,
            ],
            inspect_repository_source=_inspect_clean_source,
        )
    finally:
        sys.stdout = previous_stdout

    assert code == 130
    output = stdout.getvalue()
    assert "event=INTERRUPTED" in output
    assert "signal=SIGINT" in output
    assert "exit_status=130" in output


def test_main_reports_sigterm_with_exit_143(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        runner,
        "execute_runtime",
        lambda **kwargs: (_ for _ in ()).throw(KeyboardInterrupt("SIGTERM")),
    )
    stdout = io.StringIO()
    previous_stdout = sys.stdout
    sys.stdout = stdout
    try:
        code = runner.main(
            [
                "--venue", "bitvavo",
                "--symbols", "BTC",
                "--quote-currency", "EUR",
                "--fib-trading-horizon", "SHORT",
                "--primary-interval", "4h",
                "--supporting-interval", "1h",
                "--as-of-utc", _AS_OF.isoformat(),
                *_CLI_PROVENANCE_ARGS,
            ],
            inspect_repository_source=_inspect_clean_source,
        )
    finally:
        sys.stdout = previous_stdout

    assert code == 143
    output = stdout.getvalue()
    assert "event=INTERRUPTED" in output
    assert "signal=SIGTERM" in output
    assert "exit_status=143" in output


def test_main_installs_and_restores_sigterm_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    original_handler = signal.getsignal(signal.SIGTERM)
    monkeypatch.setattr(
        runner,
        "execute_runtime",
        lambda **kwargs: _finished_execute_result(),
    )
    stdout = io.StringIO()
    previous_stdout = sys.stdout
    sys.stdout = stdout
    try:
        runner.main(
            [
                "--venue", "bitvavo",
                "--symbols", "BTC",
                "--quote-currency", "EUR",
                "--fib-trading-horizon", "SHORT",
                "--primary-interval", "4h",
                "--supporting-interval", "1h",
                "--as-of-utc", _AS_OF.isoformat(),
                *_CLI_PROVENANCE_ARGS,
            ],
            inspect_repository_source=_inspect_clean_source,
        )
    finally:
        sys.stdout = previous_stdout

    assert signal.getsignal(signal.SIGTERM) is original_handler


def _finished_execute_result() -> "runner.RuntimeResult":
    return runner.RuntimeResult(
        run=_finished_run(),
        selected_scope_count=1,
        candle_rows_read=1,
        elapsed_ms=1,
    )
