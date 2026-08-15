from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.account.account_state_snapshot_alignment_v1 import (
    ACCOUNT_STATE_SNAPSHOT_RUN_SOURCE,
    AccountStateSnapshotContractError,
    verify_persisted_component_counts,
    write_complete_account_state_snapshot_run,
    write_complete_open_order_snapshot_run,
)
import src.account.run_account_wallet_refresh_v1 as wallet_refresh


_SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE account_open_order_snapshot_run_v1 (
    account_open_order_snapshot_run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    trading_account_id INTEGER NOT NULL,
    venue TEXT NOT NULL,
    source_name TEXT NOT NULL,
    snapshot_ts_utc TEXT NOT NULL,
    snapshot_state TEXT NOT NULL,
    open_order_count INTEGER NOT NULL,
    UNIQUE(trading_account_id, venue, source_name, snapshot_ts_utc)
);
CREATE TABLE account_position_snapshot (
    account_position_snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    trading_account_id INTEGER NOT NULL,
    venue TEXT NOT NULL,
    source_name TEXT NOT NULL,
    snapshot_ts_utc TEXT NOT NULL
);
CREATE TABLE trading_account_balance_snapshot (
    trading_account_balance_snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    trading_account_id INTEGER NOT NULL,
    venue TEXT NOT NULL,
    source_name TEXT NOT NULL,
    snapshot_ts_utc TEXT NOT NULL
);
CREATE TABLE account_open_order_snapshot (
    account_open_order_snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    trading_account_id INTEGER NOT NULL,
    venue TEXT NOT NULL,
    snapshot_ts_utc TEXT NOT NULL
);
CREATE TABLE account_state_snapshot_run_v1 (
    account_state_snapshot_run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    trading_account_id INTEGER NOT NULL,
    venue TEXT NOT NULL,
    source_name TEXT NOT NULL,
    refresh_started_ts_utc TEXT NOT NULL,
    snapshot_ts_utc TEXT NOT NULL,
    completed_ts_utc TEXT NOT NULL,
    run_state TEXT NOT NULL,
    position_source_name TEXT NOT NULL,
    position_snapshot_count INTEGER NOT NULL,
    balance_source_name TEXT NOT NULL,
    balance_snapshot_count INTEGER NOT NULL,
    account_open_order_snapshot_run_id INTEGER NOT NULL,
    UNIQUE(trading_account_id, venue, source_name, snapshot_ts_utc),
    FOREIGN KEY(account_open_order_snapshot_run_id)
        REFERENCES account_open_order_snapshot_run_v1(account_open_order_snapshot_run_id)
);
"""


class _Cursor:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._cursor = conn.cursor()
        self.lastrowid = 0

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        normalized = sql.replace("%s", "?")
        values = tuple(
            value.isoformat(sep=" ") if isinstance(value, datetime) else value
            for value in params
        )
        self._cursor.execute(normalized, values)
        self.lastrowid = self._cursor.lastrowid

    def fetchone(self) -> dict[str, Any] | None:
        row = self._cursor.fetchone()
        return None if row is None else dict(row)

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, *args: Any) -> None:
        return None


class _Connection:
    def __init__(self) -> None:
        self.raw = sqlite3.connect(":memory:")
        self.raw.row_factory = sqlite3.Row
        self.raw.executescript(_SCHEMA)

    def cursor(self) -> _Cursor:
        return _Cursor(self.raw)


_TS = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


def _complete_bundle(
    conn: _Connection,
    *,
    account_id: int = 7,
    venue: str = "bitvavo",
    position_count: int = 1,
    balance_count: int = 2,
    order_count: int = 0,
) -> int:
    order_run_id = write_complete_open_order_snapshot_run(
        conn,
        trading_account_id=account_id,
        venue=venue,
        source_name="account_wallet_refresh_v1",
        snapshot_ts_utc=_TS,
        open_order_count=order_count,
    )
    return write_complete_account_state_snapshot_run(
        conn,
        trading_account_id=account_id,
        venue=venue,
        source_name=ACCOUNT_STATE_SNAPSHOT_RUN_SOURCE,
        refresh_started_ts_utc=_TS,
        snapshot_ts_utc=_TS,
        completed_ts_utc=_TS,
        position_source_name="bitvavo_private_balance_position_snapshot_v1",
        position_snapshot_count=position_count,
        balance_source_name="account_wallet_refresh_v1",
        balance_snapshot_count=balance_count,
        account_open_order_snapshot_run_id=order_run_id,
    ).account_state_snapshot_run_id


def test_zero_positions_balance_and_zero_orders_is_complete_account_evidence() -> None:
    conn = _Connection()
    run_id = _complete_bundle(conn, position_count=0, balance_count=1, order_count=0)
    row = conn.raw.execute(
        "SELECT run_state, position_snapshot_count, balance_snapshot_count FROM account_state_snapshot_run_v1 WHERE account_state_snapshot_run_id = ?",
        (run_id,),
    ).fetchone()
    assert dict(row) == {
        "run_state": "COMPLETE",
        "position_snapshot_count": 0,
        "balance_snapshot_count": 1,
    }


def test_positive_position_balance_and_n_orders_reference_exact_complete_header() -> None:
    conn = _Connection()
    run_id = _complete_bundle(conn, position_count=1, balance_count=2, order_count=3)
    row = conn.raw.execute(
        """
        SELECT state_run.position_snapshot_count, order_run.open_order_count
        FROM account_state_snapshot_run_v1 state_run
        JOIN account_open_order_snapshot_run_v1 order_run
          ON order_run.account_open_order_snapshot_run_id = state_run.account_open_order_snapshot_run_id
        WHERE state_run.account_state_snapshot_run_id = ?
        """,
        (run_id,),
    ).fetchone()
    assert dict(row) == {"position_snapshot_count": 1, "open_order_count": 3}


def test_complete_header_count_conflict_fails_closed() -> None:
    conn = _Connection()
    write_complete_open_order_snapshot_run(
        conn, trading_account_id=7, venue="bitvavo", source_name="account_wallet_refresh_v1",
        snapshot_ts_utc=_TS, open_order_count=0,
    )
    with pytest.raises(AccountStateSnapshotContractError, match="OPEN_ORDER_COMPLETE_HEADER_CONFLICT"):
        write_complete_open_order_snapshot_run(
            conn, trading_account_id=7, venue="bitvavo", source_name="account_wallet_refresh_v1",
            snapshot_ts_utc=_TS, open_order_count=1,
        )


def test_component_count_mismatch_fails_closed_before_complete_headers() -> None:
    conn = _Connection()
    ts = _TS.isoformat(sep=" ")
    conn.raw.execute(
        "INSERT INTO trading_account_balance_snapshot (trading_account_id, venue, source_name, snapshot_ts_utc) VALUES (7, 'bitvavo', 'account_wallet_refresh_v1', ?)",
        (ts,),
    )
    with pytest.raises(AccountStateSnapshotContractError, match="POSITION_SNAPSHOT_COUNT_MISMATCH"):
        verify_persisted_component_counts(
            conn,
            trading_account_id=7,
            venue="bitvavo",
            snapshot_ts_utc=_TS,
            position_source_name="bitvavo_private_balance_position_snapshot_v1",
            expected_position_count=1,
            balance_source_name="account_wallet_refresh_v1",
            expected_balance_count=1,
            expected_open_order_count=0,
        )
    assert conn.raw.execute("SELECT COUNT(*) FROM account_open_order_snapshot_run_v1").fetchone()[0] == 0
    assert conn.raw.execute("SELECT COUNT(*) FROM account_state_snapshot_run_v1").fetchone()[0] == 0


def test_missing_open_order_component_cannot_be_referenced() -> None:
    conn = _Connection()
    with pytest.raises(sqlite3.IntegrityError):
        write_complete_account_state_snapshot_run(
            conn, trading_account_id=7, venue="bitvavo", source_name=ACCOUNT_STATE_SNAPSHOT_RUN_SOURCE,
            refresh_started_ts_utc=_TS, snapshot_ts_utc=_TS, completed_ts_utc=_TS,
            position_source_name="positions", position_snapshot_count=0,
            balance_source_name="balances", balance_snapshot_count=1,
            account_open_order_snapshot_run_id=999,
        )


def test_same_refresh_is_idempotent_but_accounts_and_venues_are_isolated() -> None:
    conn = _Connection()
    first = _complete_bundle(conn, account_id=7, venue="bitvavo")
    assert _complete_bundle(conn, account_id=7, venue="bitvavo") == first
    other_account = _complete_bundle(conn, account_id=8, venue="bitvavo")
    other_venue = _complete_bundle(conn, account_id=7, venue="kraken")
    assert len({first, other_account, other_venue}) == 3


def test_wallet_refresh_integrates_positions_and_complete_headers_in_one_producer() -> None:
    source = Path("src/account/run_account_wallet_refresh_v1.py").read_text(encoding="utf-8")
    assert "write_positions_from_balance_snapshot" in source
    assert "write_complete_open_order_snapshot_run" in source
    assert "write_complete_account_state_snapshot_run" in source
    assert "conn.rollback()" in source


def _install_aligned_component_writers(
    monkeypatch: pytest.MonkeyPatch,
    conn: _Connection,
    *,
    position_count: int,
    balance_count: int,
    order_count: int,
) -> None:
    def write_balance(_conn: _Connection, **kwargs: Any) -> int:
        for _ in range(balance_count):
            conn.raw.execute(
                "INSERT INTO trading_account_balance_snapshot (trading_account_id, venue, source_name, snapshot_ts_utc) VALUES (?, ?, ?, ?)",
                (kwargs["trading_account_id"], kwargs["venue"], kwargs["source_name"], kwargs["snapshot_ts_utc"].isoformat(sep=" ")),
            )
        return balance_count

    def write_positions(_conn: _Connection, **kwargs: Any) -> tuple[list[Any], list[str]]:
        for _ in range(position_count):
            conn.raw.execute(
                "INSERT INTO account_position_snapshot (trading_account_id, venue, source_name, snapshot_ts_utc) VALUES (?, ?, ?, ?)",
                (kwargs["account"].trading_account_id, kwargs["account"].venue, "bitvavo_private_balance_position_snapshot_v1", kwargs["balance_snapshot_ts_utc"].isoformat(sep=" ")),
            )
        return [object() for _ in range(position_count)], []

    def write_orders(_conn: _Connection, **kwargs: Any) -> int:
        for _ in range(order_count):
            conn.raw.execute(
                "INSERT INTO account_open_order_snapshot (trading_account_id, venue, snapshot_ts_utc) VALUES (?, ?, ?)",
                (kwargs["trading_account_id"], kwargs["venue"], kwargs["snapshot_ts_utc"].isoformat(sep=" ")),
            )
        return order_count

    monkeypatch.setattr(
        wallet_refresh,
        "fetch_position_snapshot_account",
        lambda _conn, **_kwargs: SimpleNamespace(trading_account_id=7, venue="bitvavo"),
    )
    monkeypatch.setattr(wallet_refresh, "write_balance_snapshot", write_balance)
    monkeypatch.setattr(wallet_refresh, "write_positions_from_balance_snapshot", write_positions)
    monkeypatch.setattr(wallet_refresh, "write_open_order_snapshot", write_orders)


@pytest.mark.parametrize("position_count,balance_count,order_count", [(0, 1, 0), (1, 2, 0), (1, 2, 2)])
def test_wallet_producer_creates_complete_bundle_only_after_all_component_counts_match(
    monkeypatch: pytest.MonkeyPatch,
    position_count: int,
    balance_count: int,
    order_count: int,
) -> None:
    conn = _Connection()
    _install_aligned_component_writers(
        monkeypatch, conn, position_count=position_count,
        balance_count=balance_count, order_count=order_count,
    )
    run = wallet_refresh.write_aligned_account_state_snapshot(
        conn,
        trading_account_id=7,
        account_code="paper",
        venue="bitvavo",
        balances=[],
        orders=[object() for _ in range(order_count)],
        refresh_started_ts_utc=_TS,
        snapshot_ts_utc=_TS,
    )
    assert run.position_snapshot_count == position_count
    assert run.balance_snapshot_count == balance_count
    header = conn.raw.execute(
        "SELECT open_order_count FROM account_open_order_snapshot_run_v1"
    ).fetchone()
    assert header["open_order_count"] == order_count


def test_wallet_producer_position_failure_creates_no_complete_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _Connection()
    _install_aligned_component_writers(monkeypatch, conn, position_count=0, balance_count=1, order_count=0)
    monkeypatch.setattr(
        wallet_refresh,
        "write_positions_from_balance_snapshot",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("POSITION_READ_FAILED")),
    )
    with pytest.raises(RuntimeError, match="POSITION_READ_FAILED"):
        wallet_refresh.write_aligned_account_state_snapshot(
            conn,
            trading_account_id=7,
            account_code="paper",
            venue="bitvavo",
            balances=[],
            orders=[],
            refresh_started_ts_utc=_TS,
            snapshot_ts_utc=_TS,
        )
    conn.raw.rollback()
    assert conn.raw.execute("SELECT COUNT(*) FROM account_open_order_snapshot_run_v1").fetchone()[0] == 0
    assert conn.raw.execute("SELECT COUNT(*) FROM account_state_snapshot_run_v1").fetchone()[0] == 0


def test_alignment_contract_has_no_broker_or_executor_dependency() -> None:
    source = Path("src/account/account_state_snapshot_alignment_v1.py").read_text(encoding="utf-8").lower()
    for forbidden in ("bitvavo", "executor", "place_order", "cancel_order", "credential"):
        assert forbidden not in source


def test_account_snapshot_owner_is_odroid_and_policy_runtime_remains_unassigned() -> None:
    registry = json.loads(
        Path("deploy/ownership/account_runtime_capability_ownership_v1.json").read_text(
            encoding="utf-8"
        )
    )
    capabilities = {item["capability_id"]: item for item in registry["capabilities"]}
    assert capabilities["ACCOUNT_STATE_SNAPSHOT_REFRESH"]["owner_host"] == "odroid"
    assert capabilities["AUTOMATIC_EXIT_POLICY_RUNTIME"]["owner_host"] == "UNASSIGNED"
    assert capabilities["ACCOUNT_STATE_SNAPSHOT_REFRESH"]["broker_writes"] == 0
