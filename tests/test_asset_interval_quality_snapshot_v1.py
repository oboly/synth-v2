from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from src.measurement import run_asset_interval_quality_snapshot as runner


def _dt(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC).replace(tzinfo=None)


NOW = _dt(2026, 9, 6, 22, 14, 37)


def _row(interval_code: str, opens: list[datetime], *, now: datetime = NOW):
    latest = opens[-1] if opens else None
    return runner._build_quality_row(
        asset_id=7,
        venue="bitvavo",
        interval_code=interval_code,
        now_utc=now,
        first_open_ts_utc=opens[0] if opens else None,
        latest_open_ts_utc=latest,
        latest_close_ts_utc=latest + timedelta(hours=1) if latest else None,
        open_times=opens,
    )


def test_complete_current_1h_window_matches_v3_trusted_semantics():
    latest = _dt(2026, 9, 6, 21)
    opens = [latest - timedelta(hours=offset) for offset in reversed(range(720))]

    row = _row("1h", opens)
    assert row["quality_status"] == "TRUSTED"
    assert row["quality_score"] == Decimal("1.000000")
    assert row["rows_observed"] == 720
    assert row["expected_rows"] == 720
    assert row["coverage_ratio"] == Decimal("1.000000")
    assert row["gap_events"] == 0
    assert row["freshness_lag_hours"] == 1


def test_4h_small_gap_matches_v3_gap_and_score_semantics():
    latest = _dt(2026, 9, 6, 16)
    opens = [latest - timedelta(hours=4 * offset) for offset in reversed(range(540))]
    del opens[100]

    row = _row("4h", opens)

    assert row["gap_events"] == 1
    assert row["missing_candles_total"] == 1
    assert row["small_gap_events"] == 1
    assert row["large_gap_events"] == 0
    assert row["quality_score"] == Decimal("0.992000")
    assert row["quality_status"] == "TRUSTED"


def test_missing_interval_matches_v3_new_semantics():
    row = _row("1d", [])

    assert row["quality_status"] == "NEW"
    assert row["quality_score"] == Decimal("0.500000")
    assert row["rows_observed"] == 0
    assert row["expected_rows"] == 0
    assert row["coverage_ratio"] == Decimal("0.000000")
    assert row["freshness_lag_hours"] is None
    assert "lag_i=-1" in row["notes"]


def test_stale_1h_interval_matches_v3_blocked_threshold():
    latest = _dt(2026, 9, 6, 17)
    opens = [latest - timedelta(hours=offset) for offset in reversed(range(720))]

    row = _row("1h", opens)

    assert row["freshness_lag_hours"] == 5
    assert row["quality_status"] == "BLOCKED"
    assert row["quality_score"] == Decimal("0.850000")


class _Cursor:
    def __init__(self):
        self.calls: list[tuple[str, tuple | None]] = []
        self._rows: list[dict] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        self.calls.append((normalized, params))
        if "FROM asset" in normalized:
            self._rows = [{"asset_id": 7}]
        elif params and params[1] == "1h" and "ORDER BY open_ts_utc ASC" in normalized:
            self._rows = [{"open_ts_utc": _dt(2026, 8, 7, 21)}]
        elif params and params[1] == "1h" and "ORDER BY open_ts_utc DESC" in normalized:
            self._rows = [
                {
                    "open_ts_utc": _dt(2026, 9, 6, 21),
                    "close_ts_utc": _dt(2026, 9, 6, 22),
                }
            ]
        elif (
            params and params[1] == "1h" and "ORDER BY close_ts_utc DESC" in normalized
        ):
            self._rows = [{"close_ts_utc": _dt(2026, 9, 6, 22)}]
        elif params and params[1] == "1h" and "open_ts_utc >= %s" in normalized:
            self._rows = [{"open_ts_utc": _dt(2026, 9, 6, 21)}]
        else:
            self._rows = []

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _Connection:
    def __init__(self):
        self.cur = _Cursor()

    def cursor(self):
        return self.cur


def test_fetch_uses_exact_market_keys_and_never_reads_legacy_view():
    conn = _Connection()

    rows = runner.fetch_quality_rows(conn, venue="bitvavo", now_utc=NOW)

    assert len(rows) == 3
    sql_text = "\n".join(sql for sql, _params in conn.cur.calls)
    assert "v_asset_interval_quality" not in sql_text
    candle_calls = [
        (sql, params)
        for sql, params in conn.cur.calls
        if "FROM obs_market_candle" in sql
    ]
    assert len(candle_calls) == 8
    assert all(params[0] == 7 and params[2] == "bitvavo" for _, params in candle_calls)
    assert {params[1] for _, params in candle_calls} == {"1h", "4h", "1d"}
    window_calls = [
        (sql, params) for sql, params in candle_calls if "open_ts_utc >= %s" in sql
    ]
    assert len(window_calls) == 1
    assert window_calls[0][1][3:] == (
        _dt(2026, 8, 7, 21),
        _dt(2026, 9, 6, 21),
    )
    assert "FORCE INDEX (ix_market_candle_lookup)" in sql_text
