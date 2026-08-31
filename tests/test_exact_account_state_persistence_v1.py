from __future__ import annotations

from pathlib import Path

import pytest

from src.account.exact_account_state_persistence_v1 import fetch_exact_persistence_account


class _Cursor:
    def __init__(self, row):
        self._row = row
        self.executed = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params):
        self.executed = (sql, params)

    def fetchone(self):
        return self._row


class _Conn:
    def __init__(self, row):
        self.cursor_obj = _Cursor(row)

    def cursor(self):
        return self.cursor_obj


def _live_row(**overrides):
    row = {
        "trading_account_id": 5,
        "account_code": "bitvavo_joost_live",
        "venue": "bitvavo",
        "account_mode": "live",
        "enabled": 1,
        "live_trading_enabled": 1,
    }
    row.update(overrides)
    return row


def test_exact_persistence_loader_accepts_enabled_live_account() -> None:
    conn = _Conn(_live_row())

    account = fetch_exact_persistence_account(
        conn,
        trading_account_id=5,
        account_code="bitvavo_joost_live",
        venue="bitvavo",
    )

    assert account.trading_account_id == 5
    assert account.account_mode == "live"
    assert account.live_trading_enabled == 1
    assert conn.cursor_obj.executed is not None
    _sql, params = conn.cursor_obj.executed
    assert params == (5, "bitvavo")


@pytest.mark.parametrize(
    "row,code",
    (
        (None, "EXACT_ACCOUNT_PERSISTENCE_ACCOUNT_NOT_FOUND"),
        (_live_row(account_code="other"), "EXACT_ACCOUNT_PERSISTENCE_ACCOUNT_CODE_MISMATCH"),
        (_live_row(enabled=0), "EXACT_ACCOUNT_PERSISTENCE_ACCOUNT_DISABLED"),
    ),
)
def test_exact_persistence_loader_fails_closed(row, code: str) -> None:
    with pytest.raises(RuntimeError, match=code):
        fetch_exact_persistence_account(
            _Conn(row),
            trading_account_id=5,
            account_code="bitvavo_joost_live",
            venue="bitvavo",
        )


def test_legacy_position_writer_still_rejects_live_accounts() -> None:
    src = Path("src/operations/run_broker_account_position_snapshot_writer_v1.py").read_text()
    assert "if account.live_trading_enabled != 0:" in src
    assert "Refusing position snapshot writer because trading_account.live_trading_enabled is not 0." in src


def test_exact_runner_uses_dedicated_persistence_and_keeps_rollback() -> None:
    src = Path("src/account/run_exact_account_state_refresh_v1.py").read_text()
    assert "write_exact_aligned_account_state_snapshot" in src
    assert "write_aligned_account_state_snapshot" not in src
    assert "conn.rollback()" in src
    assert "conn.commit()" in src


def test_exact_persistence_seam_has_no_broker_or_execution_imports() -> None:
    src = Path("src/account/exact_account_state_persistence_v1.py").read_text()
    assert "BitvavoClient" not in src
    assert "decision_gate" not in src.split('"""', 2)[-1]
    assert "execution_planner" not in src.split('"""', 2)[-1]
    assert "submit_order" not in src
    assert "place_order" not in src
