from decimal import Decimal
from types import SimpleNamespace

import src.research.run_entry_quality_shadow_bounded_v1 as runner


class _Cursor:
    def __init__(self, rows):
        self.rows = rows
        self.sql = None
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params):
        self.sql = sql
        self.params = params

    def fetchall(self):
        return self.rows


class _Connection:
    def __init__(self, rows):
        self.cursor_obj = _Cursor(rows)
        self.closed = False
        self.rolled_back = False

    def cursor(self):
        return self.cursor_obj

    def close(self):
        self.closed = True

    def rollback(self):
        self.rolled_back = True


def _candidate_row():
    return {
        "asset_id": 7,
        "symbol": "AAVE",
        "quality_status_1d": "TRUSTED",
        "quality_status_4h": "TRUSTED",
        "quality_status_1h": "TRUSTED",
        "trend_score_1d": Decimal("0.7"),
        "setup_score_1d": Decimal("0.6"),
        "signal_confidence_1d": Decimal("0.8"),
        "risk_score_1d": Decimal("0.1"),
        "volume_score_4h": Decimal("0.5"),
        "compass_score_4h": Decimal("0.6"),
        "setup_score_4h": Decimal("0.7"),
        "relative_score_4h": Decimal("0.4"),
        "signal_confidence_4h": Decimal("0.8"),
        "expansion_position_score_4h": Decimal("0.3"),
        "pullback_quality_score_4h": Decimal("0.9"),
        "risk_score_4h": Decimal("0.2"),
        "setup_score_1h": Decimal("0.5"),
        "signal_confidence_1h": Decimal("0.6"),
        "risk_score_1h": Decimal("0.1"),
        "latest_quality_asof_ts_utc": "2026-08-29 12:00:00",
        "advice_ts_1h_utc": "2026-08-29 12:05:00",
        "advice_ts_4h_utc": "2026-08-29 12:05:00",
    }


def test_bounded_candidate_query_limits_asset_population_before_history() -> None:
    conn = _Connection([_candidate_row()])
    result = runner.fetch_bounded_selection_candidates(
        conn, venue="bitvavo", asset_id=7, limit=1
    )

    sql = conn.cursor_obj.sql
    assert sql is not None
    assert "FROM (" in sql
    assert "ORDER BY asset_id\n        LIMIT %s\n    ) a" in sql
    assert sql.index("LIMIT %s") < sql.index("LEFT JOIN asset_interval_quality")
    assert "SELECT MAX(q.asof_ts_utc)" in sql
    assert "SELECT MAX(s.signal_ts_utc)" in sql
    assert result[0].asset_id == 7
    assert result[0].symbol == "AAVE"
    assert result[0].venue == "bitvavo"


def test_bounded_candidate_limit_is_fail_closed() -> None:
    conn = _Connection([])
    for bad_limit in (0, 1001):
        try:
            runner.fetch_bounded_selection_candidates(
                conn, venue="bitvavo", asset_id=None, limit=bad_limit
            )
        except ValueError as exc:
            assert "1..1000" in str(exc)
        else:
            raise AssertionError("invalid limit must fail")


def test_evidence_query_uses_scalar_latest_lookups_without_history_join_product() -> None:
    conn = _Connection(
        [
            {
                "asset_id": 7,
                "quality_ts_1d_utc": "2026-08-29 00:00:00",
                "quality_ts_4h_utc": "2026-08-29 08:00:00",
                "quality_ts_1h_utc": "2026-08-29 12:00:00",
                "signal_ts_1d_utc": "2026-08-29 00:05:00",
                "signal_ts_4h_utc": "2026-08-29 08:05:00",
                "signal_ts_1h_utc": "2026-08-29 12:05:00",
            }
        ]
    )
    result = runner.fetch_bounded_evidence_timestamps(
        conn, venue="bitvavo", asset_ids=[7]
    )

    sql = conn.cursor_obj.sql
    assert sql is not None
    assert "LEFT JOIN asset_interval_quality" not in sql
    assert "LEFT JOIN signal_engine_state" not in sql
    assert sql.count("SELECT CAST(MAX(") == 6
    assert result[7]["signal_ts_1h_utc"] == "2026-08-29 12:05:00"


def _args(*, write_db: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        config="unused.yaml",
        venue="bitvavo",
        limit=1,
        asset_id=7,
        ppp_csv=None,
        out_csv="unused.csv",
        write_db=write_db,
    )


def test_run_emits_phase_start_end_and_row_counts(monkeypatch, capsys) -> None:
    conn = _Connection([])
    candidate = SimpleNamespace(asset_id=7)

    monkeypatch.setattr(runner, "get_db_connection", lambda: conn)
    monkeypatch.setattr(runner, "load_selection_config", lambda _path: {})
    monkeypatch.setattr(
        runner,
        "fetch_bounded_selection_candidates",
        lambda *_args, **_kwargs: [candidate],
    )
    monkeypatch.setattr(runner, "rank_candidates", lambda _rows, _config: [candidate])
    monkeypatch.setattr(
        runner,
        "fetch_bounded_evidence_timestamps",
        lambda *_args, **_kwargs: {7: {}},
    )
    monkeypatch.setattr(runner, "_load_ppp_csv", lambda _path: {})
    monkeypatch.setattr(runner, "build_shadow_rows", lambda **_kwargs: [])
    monkeypatch.setattr(runner, "write_csv", lambda _path, _rows: None)

    assert runner.run(_args()) == 0
    output = capsys.readouterr().out

    for phase in (
        "fetch_bounded_selection_candidates",
        "rank_candidates",
        "fetch_bounded_evidence_timestamps",
        "build_shadow",
        "write_csv",
    ):
        assert f"PHASE_START name={phase}" in output
        assert f"PHASE_END name={phase}" in output

    assert "PHASE_END name=fetch_bounded_selection_candidates rows=1" in output
    assert "PHASE_END name=fetch_bounded_evidence_timestamps rows=1" in output
    assert "elapsed_s=" in output
    assert "FINISHED runner=entry_quality_shadow_bounded_v1" in output
    assert conn.closed is True


def test_interrupt_preserves_completed_csv_and_emits_single_terminal(monkeypatch, capsys) -> None:
    conn = _Connection([])
    candidate = SimpleNamespace(asset_id=7)
    installed_handlers = {}
    csv_written = []

    monkeypatch.setattr(runner.signal, "getsignal", lambda _signum: "previous")

    def fake_signal(signum, handler):
        if callable(handler):
            installed_handlers[signum] = handler

    monkeypatch.setattr(runner.signal, "signal", fake_signal)
    monkeypatch.setattr(runner, "get_db_connection", lambda: conn)
    monkeypatch.setattr(runner, "load_selection_config", lambda _path: {})
    monkeypatch.setattr(
        runner,
        "fetch_bounded_selection_candidates",
        lambda *_args, **_kwargs: [candidate],
    )
    monkeypatch.setattr(runner, "rank_candidates", lambda _rows, _config: [candidate])
    monkeypatch.setattr(
        runner,
        "fetch_bounded_evidence_timestamps",
        lambda *_args, **_kwargs: {7: {}},
    )
    monkeypatch.setattr(runner, "_load_ppp_csv", lambda _path: {})
    monkeypatch.setattr(runner, "build_shadow_rows", lambda **_kwargs: [])
    monkeypatch.setattr(runner, "write_csv", lambda path, _rows: csv_written.append(path))

    def interrupt_during_db(_conn, _rows):
        installed_handlers[runner.signal.SIGTERM](runner.signal.SIGTERM, None)
        raise AssertionError("signal handler must interrupt")

    monkeypatch.setattr(runner, "write_shadow_rows", interrupt_during_db)

    assert runner.run(_args(write_db=True)) == 130
    output = capsys.readouterr().out

    assert csv_written == ["unused.csv"]
    assert output.count("INTERRUPTED runner=entry_quality_shadow_bounded_v1") == 1
    assert "FINISHED runner=entry_quality_shadow_bounded_v1" not in output
    assert "FAILED runner=entry_quality_shadow_bounded_v1" not in output
    assert "resumable=1" in output
    assert conn.rolled_back is True
    assert conn.closed is True
