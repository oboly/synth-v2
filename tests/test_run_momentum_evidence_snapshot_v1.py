from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from src.features import run_momentum_evidence_snapshot_v1 as runner


class _Cursor:
    def __init__(self, rows):
        self.rows = rows
        self.executed = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params):
        self.executed = (sql, params)

    def fetchall(self):
        return list(self.rows)


class _Conn:
    def __init__(self, rows=None):
        self.closed = False
        self.rows = rows if rows is not None else [
            {"venue": "bitvavo", "market": "BTC-EUR", "base_asset_id": 1}
        ]
        self.last_cursor = None

    def cursor(self):
        self.last_cursor = _Cursor(self.rows)
        return self.last_cursor

    def close(self):
        self.closed = True


def _args() -> list[str]:
    return ["--asof-ts", "2026-09-01T00:00:00Z", "--asset-id", "1", "--market", "BTC-EUR"]


def test_resolve_market_identity_uses_exact_canonical_venue_market_pair():
    conn = _Conn()

    resolved = runner.resolve_market_identity(
        conn,
        venue="bitvavo",
        market="BTC-EUR",
        expected_asset_id=1,
    )

    assert resolved == runner.ResolvedMarketIdentity(venue="bitvavo", market="BTC-EUR", asset_id=1)
    sql, params = conn.last_cursor.executed
    assert "FROM venue_market" in sql
    assert "WHERE venue = %s AND market = %s" in sql
    assert params == ("bitvavo", "BTC-EUR")


def test_resolve_market_identity_unknown_market_fails_closed():
    conn = _Conn(rows=[])

    with pytest.raises(ValueError, match="CANONICAL_MARKET_NOT_FOUND"):
        runner.resolve_market_identity(
            conn,
            venue="bitvavo",
            market="UNKNOWN-EUR",
            expected_asset_id=1,
        )


def test_resolve_market_identity_asset_mismatch_fails_closed():
    conn = _Conn(rows=[{"venue": "bitvavo", "market": "BTC-EUR", "base_asset_id": 2}])

    with pytest.raises(ValueError, match="CANONICAL_MARKET_ASSET_MISMATCH"):
        runner.resolve_market_identity(
            conn,
            venue="bitvavo",
            market="BTC-EUR",
            expected_asset_id=1,
        )


def test_resolve_market_identity_ambiguity_fails_closed():
    conn = _Conn(rows=[
        {"venue": "bitvavo", "market": "BTC-EUR", "base_asset_id": 1},
        {"venue": "bitvavo", "market": "BTC-EUR", "base_asset_id": 1},
    ])

    with pytest.raises(RuntimeError, match="CANONICAL_MARKET_AMBIGUOUS"):
        runner.resolve_market_identity(
            conn,
            venue="bitvavo",
            market="BTC-EUR",
            expected_asset_id=1,
        )


def test_runner_emits_phase_query_and_single_finished_summary(monkeypatch, capsys):
    conn = _Conn()
    fetched = {}
    built = {}
    monkeypatch.setattr(runner, "get_db_connection", lambda: conn)

    def fetch(*_args, **kwargs):
        fetched.update(kwargs)
        return pd.DataFrame()

    monkeypatch.setattr(runner, "fetch_candles_for_asof", fetch)

    def build(**kwargs):
        built.update(kwargs)
        return SimpleNamespace(
            data_quality="MISSING_SOURCE_CANDLE", status="INSUFFICIENT_DATA",
            macd_value=None, histogram_delta=None,
        )

    monkeypatch.setattr(runner, "build_momentum_evidence", build)

    assert runner.main(_args()) == 0
    output = capsys.readouterr().out
    assert "STARTED runner=momentum_evidence_snapshot_v1" in output
    assert "PHASE_END runner=momentum_evidence_snapshot_v1 phase=resolve_market_identity" in output
    assert "PHASE_END runner=momentum_evidence_snapshot_v1 phase=fetch_candles rows=0" in output
    assert output.count("FINISHED runner=momentum_evidence_snapshot_v1") == 1
    assert "status=DRY_RUN" in output
    assert fetched["asset_id"] == 1
    assert fetched["venue"] == "bitvavo"
    assert built["asset_id"] == 1
    assert built["venue"] == "bitvavo"
    assert built["market"] == "BTC-EUR"
    assert conn.closed


def test_runner_market_asset_mismatch_never_fetches_candles(monkeypatch, capsys):
    conn = _Conn(rows=[{"venue": "bitvavo", "market": "BTC-EUR", "base_asset_id": 2}])
    monkeypatch.setattr(runner, "get_db_connection", lambda: conn)
    monkeypatch.setattr(
        runner,
        "fetch_candles_for_asof",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not fetch mismatched asset")),
    )

    assert runner.main(_args()) == 1
    output = capsys.readouterr().out
    assert output.count("FAILED runner=momentum_evidence_snapshot_v1") == 1
    assert "phase=fetch_candles" not in output
    assert conn.closed


def test_runner_failure_emits_exactly_one_failed_summary(monkeypatch, capsys):
    monkeypatch.setattr(runner, "get_db_connection", _Conn)
    monkeypatch.setattr(
        runner, "fetch_candles_for_asof", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    assert runner.main(_args()) == 1
    output = capsys.readouterr().out
    assert output.count("FAILED runner=momentum_evidence_snapshot_v1") == 1
    assert "error_type=RuntimeError" in output


def test_runner_interrupt_emits_single_terminal_summary(monkeypatch, capsys):
    monkeypatch.setattr(runner, "get_db_connection", _Conn)
    monkeypatch.setattr(
        runner, "fetch_candles_for_asof", lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt("SIGTERM"))
    )

    assert runner.main(_args()) == 130
    output = capsys.readouterr().out
    assert output.count("INTERRUPTED runner=momentum_evidence_snapshot_v1") == 1
    assert "signal=SIGTERM" in output


def test_runner_authorization_denial_preserves_exit_code_and_emits_one_failed_summary(monkeypatch, capsys):
    def deny(*_args, **_kwargs):
        raise SystemExit(3)

    monkeypatch.setattr(
        "src.operations.writer_capability_authorization_v1.require_capability_write_authorization",
        deny,
    )
    monkeypatch.setattr(runner, "get_db_connection", lambda: (_ for _ in ()).throw(AssertionError("DB must not open")))
    monkeypatch.setattr(runner, "persist_snapshot", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not persist")))

    assert runner.main([*_args(), "--write-db"]) == 3
    output = capsys.readouterr().out
    assert output.count("FAILED runner=momentum_evidence_snapshot_v1") == 1
    assert "FINISHED runner=momentum_evidence_snapshot_v1" not in output


def test_write_db_capability_is_unregistered_and_always_fails_closed():
    """`momentum_evidence_snapshot` is deliberately not registered in
    `CAPABILITY_IDENTITY` (writer_capability_authorization_v1). This mirrors
    the existing `ma_breadth_snapshot` precedent: --write-db always denies
    until an explicit, reviewed registration decision is made."""
    from pathlib import Path
    from src.operations.writer_capability_authorization_v1 import CAPABILITY_IDENTITY

    assert "momentum_evidence_snapshot" not in CAPABILITY_IDENTITY
    source = Path("src/operations/writer_capability_authorization_v1.py").read_text()
    assert "momentum_evidence_snapshot" not in source
