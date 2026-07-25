from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Callable

import pytest

from src.market_data import run_native_short_scope_status_chain_v1 as runner
from src.market_data.native_short_map_lifecycle_v1 import NativeShortMapScopeKey
from src.market_data.native_short_scope_status_v1 import (
    NativeShortMaterializerRunRecord,
)
from src.market_data.native_short_writer_commit_fence_v1 import (
    REASON_ACTIVE_CADENCE_CHANGED,
    REASON_SUPPORT_GENERATION_CHANGED,
    REASON_SUPPORT_WITHDRAWN,
    NativeShortWriterCommitFenceError,
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


def _execute(
    monkeypatch: pytest.MonkeyPatch,
    conn: _FenceConn,
    orchestrator: Callable[..., NativeShortMaterializerRunRecord],
) -> runner.RuntimeResult:
    monkeypatch.setattr(runner, "get_connection", lambda: conn)
    monkeypatch.setattr(
        runner,
        "fetch_supported_scope_keys",
        lambda *args, **kwargs: [_BTC],
    )
    monkeypatch.setattr(
        runner,
        "run_native_short_scope_status_materializer",
        orchestrator,
    )
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


def _record_run_evidence(conn: _FenceConn) -> NativeShortMaterializerRunRecord:
    conn.pending["run"].append("btc-run")
    return _finished_run()


def test_support_withdrawn_before_commit_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FenceConn()

    def withdraw(connection: _FenceConn, **kwargs: Any) -> NativeShortMaterializerRunRecord:
        connection.pending["run"].append("btc-run")
        connection.scope_row["scope_support_state"] = "NOT_APPLICABLE"
        connection.cadence_row["is_active"] = 0
        return _finished_run()

    with pytest.raises(
        NativeShortWriterCommitFenceError,
        match=REASON_SUPPORT_WITHDRAWN,
    ):
        _execute(monkeypatch, conn, withdraw)

    assert conn.commit_count == 0
    assert conn.rollback_count == 1


def test_support_generation_changed_before_commit_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FenceConn()

    def change_generation(
        connection: _FenceConn,
        **kwargs: Any,
    ) -> NativeShortMaterializerRunRecord:
        connection.pending["generation"].append("attempt")
        connection.scope_row["support_generation"] = 2
        return _finished_run()

    with pytest.raises(
        NativeShortWriterCommitFenceError,
        match=REASON_SUPPORT_GENERATION_CHANGED,
    ):
        _execute(monkeypatch, conn, change_generation)

    assert conn.commit_count == 0
    assert conn.rollback_count == 1


def test_active_cadence_changed_before_commit_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FenceConn()

    def change_cadence(
        connection: _FenceConn,
        **kwargs: Any,
    ) -> NativeShortMaterializerRunRecord:
        connection.pending["projection"].append("btc-status")
        connection.cadence_row["cadence_config_id"] = 2
        return _finished_run()

    with pytest.raises(
        NativeShortWriterCommitFenceError,
        match=REASON_ACTIVE_CADENCE_CHANGED,
    ):
        _execute(monkeypatch, conn, change_cadence)

    assert conn.commit_count == 0
    assert conn.rollback_count == 1


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
    assert conn.commit_count == 1
    assert conn.rollback_count == 0
    assert conn.persisted["run"] == ["btc-run"]


def test_failed_fence_leaves_no_partial_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FenceConn()

    def write_then_drift(
        connection: _FenceConn,
        **kwargs: Any,
    ) -> NativeShortMaterializerRunRecord:
        for name in _EVIDENCE_TYPES:
            connection.pending[name].append(f"btc-{name}")
        connection.scope_row["support_generation"] = 2
        return _finished_run()

    with pytest.raises(NativeShortWriterCommitFenceError):
        _execute(monkeypatch, conn, write_then_drift)

    assert all(conn.persisted[name] == [] for name in _EVIDENCE_TYPES)
    assert all(conn.pending[name] == [] for name in _EVIDENCE_TYPES)
    assert conn.commit_count == 0
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

    def idempotent_orchestrator(
        connection: _FenceConn,
        **kwargs: Any,
    ) -> NativeShortMaterializerRunRecord:
        connection.pending["run"].append("btc-run")
        if "btc-map" not in connection.persisted["map"]:
            connection.pending["map"].append("btc-map")
        return _finished_run()

    monkeypatch.setattr(
        runner,
        "run_native_short_scope_status_materializer",
        idempotent_orchestrator,
    )

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

    assert [conn.commit_count for conn in connections] == [1, 1]
    assert [conn.rollback_count for conn in connections] == [0, 0]
    assert persisted["run"] == ["btc-run", "btc-run"]
    assert persisted["map"] == ["btc-map"]
