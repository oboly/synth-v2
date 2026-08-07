from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Callable

import pytest

from src.market_data import run_native_short_scope_status_chain_v1 as runner
from src.market_data.native_short_map_lifecycle_v1 import NativeShortMapScopeKey
from src.market_data.native_short_scope_status_materializer_v1 import ScopeChainOutcome
from src.market_data.native_short_scope_status_v1 import (
    NativeShortMaterializerRunRecord,
)
from src.market_data.native_short_writer_commit_fence_v1 import (
    REASON_ACTIVE_CADENCE_CHANGED,
    REASON_SUPPORT_GENERATION_CHANGED,
    REASON_SUPPORT_WITHDRAWN,
)
from src.market_data.native_short_writer_provenance_v1 import (
    build_explicit_test_provenance,
)

_AS_OF = datetime(2026, 7, 24, 8, 0, tzinfo=UTC)
_BTC = NativeShortMapScopeKey(
    venue="bitvavo",
    symbol="BTC",
    quote_currency="EUR",
    fib_trading_horizon="SHORT",
    primary_interval="4h",
    supporting_interval="1h",
)
_PROVENANCE = build_explicit_test_provenance()
_EVIDENCE_TYPES = (
    "run",
    "generation",
    "map",
    "lifecycle",
    "observation",
    "projection",
)


@pytest.fixture(autouse=True)
def _authorized_native_short_context(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.writer_auth_support import install_authorized_writer_context

    install_authorized_writer_context(monkeypatch)


class _FenceCursor:
    def __init__(self, conn: "_FenceConn") -> None:
        self._conn = conn
        self._rows: list[dict[str, Any]] = []

    def execute(self, sql: str, params: Any = None) -> None:
        if "FROM native_short_map_scope_v1" in sql:
            self._rows = [dict(self._conn.scope_row)]
            return
        if "FROM native_short_scope_cadence_config_v1" in sql:
            self._rows = (
                [dict(self._conn.cadence_row)]
                if int(self._conn.cadence_row["is_active"]) == 1
                else []
            )
            return
        raise AssertionError(f"unexpected SQL: {sql.strip()[:120]}")

    def fetchall(self) -> list[dict[str, Any]]:
        return self._rows

    def __enter__(self) -> "_FenceCursor":
        return self

    def __exit__(self, *args: Any) -> bool:
        return False


class _FenceConn:
    def __init__(self, persisted: dict[str, list[str]] | None = None) -> None:
        self.persisted = persisted or {name: [] for name in _EVIDENCE_TYPES}
        self.pending = {name: [] for name in _EVIDENCE_TYPES}
        self.scope_row = {
            "scope_id": 1,
            "venue": _BTC.venue,
            "symbol": _BTC.symbol,
            "quote_currency": _BTC.quote_currency,
            "fib_trading_horizon": _BTC.fib_trading_horizon,
            "primary_interval": _BTC.primary_interval,
            "supporting_interval": _BTC.supporting_interval,
            "scope_support_state": "SUPPORTED",
            "support_generation": None,
        }
        self.cadence_row = {
            "cadence_config_id": 1,
            "cadence_contract_version": "native_short_cadence_v1",
            "target_evaluation_interval": "1h",
            "primary_source_freshness_limit_seconds": 43200,
            "supporting_source_freshness_limit_seconds": 10800,
            "evaluation_grace_seconds": 900,
            "recent_scope_grace_seconds": 3600,
            "effective_from_utc": datetime(2026, 7, 9),
            "effective_to_utc": None,
            "is_active": 1,
            "activation_operation_id": None,
            "deactivation_operation_id": None,
            "support_generation": None,
        }
        self.begin_count = 0
        self.commit_count = 0
        self.rollback_count = 0
        self.close_count = 0

    def cursor(self) -> _FenceCursor:
        return _FenceCursor(self)

    def begin(self) -> None:
        self.begin_count += 1

    def commit(self) -> None:
        for name in _EVIDENCE_TYPES:
            self.persisted[name].extend(self.pending[name])
            self.pending[name].clear()
        self.commit_count += 1

    def rollback(self) -> None:
        for name in _EVIDENCE_TYPES:
            self.pending[name].clear()
        self.rollback_count += 1

    def close(self) -> None:
        self.close_count += 1


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


def _scope_outcome() -> ScopeChainOutcome:
    return ScopeChainOutcome(
        key=_BTC,
        skipped_not_supported=False,
        published_map=False,
        lifecycle_event_appended=False,
        failed=False,
    )


def _install_run_row_doubles(
    monkeypatch: pytest.MonkeyPatch,
    finalized: list[NativeShortMaterializerRunRecord] | None = None,
) -> None:
    """The run row is written in its own transaction, outside every scope's
    failure domain, so it is stubbed here: these tests are about the
    exact-scope commit fence, not run-row SQL."""

    def _finalize(connection: Any, run_id: int, record: Any, **kwargs: Any) -> None:
        if finalized is not None:
            finalized.append(record)

    monkeypatch.setattr(runner, "_insert_run", lambda connection, record, **kwargs: 1)
    monkeypatch.setattr(runner, "_finalize_run", _finalize)


def _execute(
    monkeypatch: pytest.MonkeyPatch,
    conn: _FenceConn,
    scope_fn: Callable[..., ScopeChainOutcome],
    finalized: list[NativeShortMaterializerRunRecord] | None = None,
) -> runner.RuntimeResult:
    monkeypatch.setattr(runner, "get_connection", lambda: conn)
    monkeypatch.setattr(
        runner,
        "fetch_supported_scope_keys",
        lambda *args, **kwargs: [_BTC],
    )
    _install_run_row_doubles(monkeypatch, finalized)
    monkeypatch.setattr(runner, "evaluate_and_project_scope", scope_fn)
    return runner.execute_runtime(
        venue="bitvavo",
        symbols=["BTC"],
        quote_currency="EUR",
        fib_trading_horizon="SHORT",
        primary_interval="4h",
        supporting_interval="1h",
        as_of_utc=_AS_OF,
        provenance=_PROVENANCE,
    )


def _record_run_evidence(conn: _FenceConn) -> ScopeChainOutcome:
    conn.pending["run"].append("btc-run")
    return _scope_outcome()


def test_support_withdrawn_before_commit_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact-scope fence still discards that scope's evidence entirely.
    Under exact-scope transaction boundaries the fence violation is attributed
    to its own scope and terminalizes the run as FAILED with the fence reason,
    instead of destroying unrelated scopes' committed work."""
    conn = _FenceConn()
    finalized: list[NativeShortMaterializerRunRecord] = []

    def withdraw(connection: _FenceConn, **kwargs: Any) -> ScopeChainOutcome:
        connection.pending["run"].append("btc-run")
        connection.scope_row["scope_support_state"] = "NOT_APPLICABLE"
        connection.cadence_row["is_active"] = 0
        return _scope_outcome()

    with pytest.raises(runner.RuntimeScopeEvaluationError):
        _execute(monkeypatch, conn, withdraw, finalized)

    assert conn.persisted["run"] == []
    assert conn.rollback_count == 1
    assert REASON_SUPPORT_WITHDRAWN in finalized[0].failure_detail
    assert finalized[0].terminal_status == "FAILED"


def test_support_generation_changed_before_commit_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FenceConn()
    finalized: list[NativeShortMaterializerRunRecord] = []

    def change_generation(connection: _FenceConn, **kwargs: Any) -> ScopeChainOutcome:
        connection.pending["generation"].append("attempt")
        connection.scope_row["support_generation"] = 2
        return _scope_outcome()

    with pytest.raises(runner.RuntimeScopeEvaluationError):
        _execute(monkeypatch, conn, change_generation, finalized)

    assert conn.persisted["generation"] == []
    assert conn.rollback_count == 1
    assert REASON_SUPPORT_GENERATION_CHANGED in finalized[0].failure_detail


def test_active_cadence_changed_before_commit_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FenceConn()
    finalized: list[NativeShortMaterializerRunRecord] = []

    def change_cadence(connection: _FenceConn, **kwargs: Any) -> ScopeChainOutcome:
        connection.pending["projection"].append("btc-status")
        connection.cadence_row["cadence_config_id"] = 2
        return _scope_outcome()

    with pytest.raises(runner.RuntimeScopeEvaluationError):
        _execute(monkeypatch, conn, change_cadence, finalized)

    assert conn.persisted["projection"] == []
    assert conn.rollback_count == 1
    assert REASON_ACTIVE_CADENCE_CHANGED in finalized[0].failure_detail


def test_unchanged_commit_fence_commits_successfully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FenceConn()

    result = _execute(
        monkeypatch,
        conn,
        lambda connection, **kwargs: _record_run_evidence(connection),
    )

    assert result.selected_scope_count == 1
    # setup, run row, the single scope, finalize
    assert conn.commit_count == 4
    assert conn.rollback_count == 0
    assert conn.persisted["run"] == ["btc-run"]


def test_failed_fence_leaves_no_partial_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FenceConn()

    def write_then_drift(connection: _FenceConn, **kwargs: Any) -> ScopeChainOutcome:
        for name in _EVIDENCE_TYPES:
            connection.pending[name].append(f"btc-{name}")
        connection.scope_row["support_generation"] = 2
        return _scope_outcome()

    with pytest.raises(runner.RuntimeScopeEvaluationError):
        _execute(monkeypatch, conn, write_then_drift)

    assert all(conn.persisted[name] == [] for name in _EVIDENCE_TYPES)
    assert all(conn.pending[name] == [] for name in _EVIDENCE_TYPES)
    assert conn.rollback_count == 1


def test_btc_idempotent_rerun_remains_valid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persisted = {name: [] for name in _EVIDENCE_TYPES}
    connections = [_FenceConn(persisted), _FenceConn(persisted)]
    opened = iter(connections)
    monkeypatch.setattr(runner, "get_connection", lambda: next(opened))
    monkeypatch.setattr(
        runner,
        "fetch_supported_scope_keys",
        lambda *args, **kwargs: [_BTC],
    )
    _install_run_row_doubles(monkeypatch)

    def idempotent_scope(connection: _FenceConn, **kwargs: Any) -> ScopeChainOutcome:
        connection.pending["run"].append("btc-run")
        if "btc-map" not in connection.persisted["map"]:
            connection.pending["map"].append("btc-map")
        return _scope_outcome()

    monkeypatch.setattr(runner, "evaluate_and_project_scope", idempotent_scope)

    for _ in range(2):
        runner.execute_runtime(
            venue="bitvavo",
            symbols=["BTC"],
            quote_currency="EUR",
            fib_trading_horizon="SHORT",
            primary_interval="4h",
            supporting_interval="1h",
            as_of_utc=_AS_OF,
            provenance=_PROVENANCE,
        )

    assert [conn.commit_count for conn in connections] == [4, 4]
    assert [conn.rollback_count for conn in connections] == [0, 0]
    assert persisted["run"] == ["btc-run", "btc-run"]
    assert persisted["map"] == ["btc-map"]
