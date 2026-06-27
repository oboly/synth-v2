from __future__ import annotations

import ast
import io
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests as req_lib
import pytest

from src.research.run_market_rotation_history_v1 import (
    AssetRow,
    CandleRecord,
    GlobalContextResult,
    HorizonObservation,
    _determine_global_action,
    _partition_candles,
    check_eligibility,
    check_schema_ready,
    compute_coverage_ratio,
    compute_observation,
    compute_price_change_pct,
    compute_relative_volume,
    fetch_coingecko_global,
    floor_to_hour,
    main,
    normalize_coingecko_global,
    write_global_snapshot,
    write_rotation_snapshot,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

AS_OF = datetime(2026, 1, 15, 12, 0, 0)  # naive UTC hourly boundary

MOCK_CG_DATA = {
    "total_market_cap": {"usd": 3_500_000_000_000.0},
    "total_volume": {"usd": 300_000_000_000.0},
    "market_cap_percentage": {"btc": 62.5, "eth": 9.2},
    "market_cap_change_percentage_24h_usd": -1.5,
    "volume_change_percentage_24h_usd": 5.2,
    "updated_at": 1735000000,
}

_MOD = "src.research.run_market_rotation_history_v1"


def _candle(asset_id: int, close_ts: datetime, price: float, volume: float) -> CandleRecord:
    return CandleRecord(
        asset_id=asset_id,
        open_ts_utc=close_ts - timedelta(hours=1),
        close_ts_utc=close_ts,
        close_price=Decimal(str(price)),
        volume_quote_eur=Decimal(str(volume)),
    )


def _make_current_24h(asset_id: int = 1, price: float = 1050.0, volume: float = 50.0) -> list[CandleRecord]:
    return [_candle(asset_id, AS_OF - timedelta(hours=23 - i), price, volume) for i in range(24)]


def _make_baseline_24h(asset_id: int = 1, price: float = 1000.0, volume: float = 40.0) -> list[CandleRecord]:
    return [_candle(asset_id, AS_OF - timedelta(hours=47 - i), price, volume) for i in range(24)]


def _make_current_7d(asset_id: int = 1, price: float = 1100.0, volume: float = 60.0) -> list[CandleRecord]:
    return [_candle(asset_id, AS_OF - timedelta(hours=167 - i), price, volume) for i in range(168)]


def _make_baseline_7d(asset_id: int = 1, price: float = 1000.0, volume: float = 50.0) -> list[CandleRecord]:
    return [_candle(asset_id, AS_OF - timedelta(hours=335 - i), price, volume) for i in range(168)]


def _make_obs(asset_id: int = 1, market: str = "BTC-EUR") -> HorizonObservation:
    return HorizonObservation(
        asset_id=asset_id,
        market=market,
        horizon_h=24,
        window_open_ts_utc=AS_OF - timedelta(hours=24),
        window_close_ts_utc=AS_OF,
        price_open=Decimal("1000"),
        price_close=Decimal("1050"),
        price_change_pct=Decimal("5.000000"),
        quote_volume=Decimal("1200.000000"),
        baseline_quote_volume=Decimal("960.000000"),
        relative_volume=Decimal("1.250000"),
        candle_count=24,
        expected_candle_count=24,
        coverage_ratio=Decimal("1.0000"),
        baseline_candle_count=24,
        baseline_expected_candle_count=24,
        baseline_coverage_ratio=Decimal("1.0000"),
        as_of_ts_utc=AS_OF,
    )


def _available_result() -> GlobalContextResult:
    return GlobalContextResult(
        source_status="AVAILABLE",
        source_error_reason=None,
        total_volume_24h_usd=Decimal("300000000000"),
        volume_change_pct_24h=Decimal("5.2"),
        total_market_cap_usd=Decimal("3500000000000"),
        market_cap_change_pct_24h=Decimal("-1.5"),
        btc_dominance_pct=Decimal("62.5"),
        eth_dominance_pct=Decimal("9.2"),
        provider_updated_at_utc=None,
        fetched_at_utc=datetime(2026, 1, 15, 10, 5, 0),
    )


def _unavailable_result() -> GlobalContextResult:
    return GlobalContextResult(
        source_status="UNAVAILABLE",
        source_error_reason="HTTP_429",
        total_volume_24h_usd=None,
        volume_change_pct_24h=None,
        total_market_cap_usd=None,
        market_cap_change_pct_24h=None,
        btc_dominance_pct=None,
        eth_dominance_pct=None,
        provider_updated_at_utc=None,
        fetched_at_utc=datetime(2026, 1, 15, 11, 0, 0),
    )


def _skipped_result() -> GlobalContextResult:
    return GlobalContextResult(
        source_status="SKIPPED_NO_CREDENTIAL",
        source_error_reason=None,
        total_volume_24h_usd=None,
        volume_change_pct_24h=None,
        total_market_cap_usd=None,
        market_cap_change_pct_24h=None,
        btc_dominance_pct=None,
        eth_dominance_pct=None,
        provider_updated_at_utc=None,
        fetched_at_utc=datetime(2026, 1, 15, 10, 0, 0),
    )


def _make_conn_mock(fetchone_return=None):
    cursor = MagicMock()
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)
    cursor.fetchone.return_value = fetchone_return
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn, cursor


# ---------------------------------------------------------------------------
# Pure math
# ---------------------------------------------------------------------------

def test_floor_to_hour():
    assert floor_to_hour(datetime(2026, 1, 15, 14, 37, 52, 123456)) == datetime(2026, 1, 15, 14, 0, 0)


def test_floor_to_hour_already_on_boundary():
    ts = datetime(2026, 1, 15, 8, 0, 0)
    assert floor_to_hour(ts) == ts


def test_compute_price_change_pct_positive():
    assert compute_price_change_pct(Decimal("1000"), Decimal("1050")) == Decimal("5")


def test_compute_price_change_pct_negative():
    assert compute_price_change_pct(Decimal("1000"), Decimal("900")) == Decimal("-10")


def test_compute_price_change_pct_zero():
    assert compute_price_change_pct(Decimal("500"), Decimal("500")) == Decimal("0")


def test_compute_price_change_pct_zero_open_raises():
    with pytest.raises(ValueError, match="non-zero"):
        compute_price_change_pct(Decimal("0"), Decimal("100"))


def test_compute_relative_volume():
    assert compute_relative_volume(Decimal("1200"), Decimal("1000")) == Decimal("1.2")


def test_compute_relative_volume_zero_baseline_raises():
    with pytest.raises(ValueError, match="non-zero"):
        compute_relative_volume(Decimal("100"), Decimal("0"))


def test_compute_coverage_ratio_full():
    assert compute_coverage_ratio(24, 24) == Decimal("1")


def test_compute_coverage_ratio_partial():
    assert compute_coverage_ratio(21, 24) == Decimal("21") / Decimal("24")


def test_compute_coverage_ratio_zero_expected():
    assert compute_coverage_ratio(0, 0) == Decimal("0")


# ---------------------------------------------------------------------------
# Candle partitioning
# ---------------------------------------------------------------------------

def test_partition_candles_24h_counts():
    c, b = _partition_candles(_make_current_24h() + _make_baseline_24h(), AS_OF, 24)
    assert len(c) == 24 and len(b) == 24


def test_partition_candles_24h_boundaries():
    c, b = _partition_candles(_make_current_24h() + _make_baseline_24h(), AS_OF, 24)
    assert max(x.close_ts_utc for x in c) == AS_OF
    assert max(x.close_ts_utc for x in b) == AS_OF - timedelta(hours=24)


def test_partition_candles_7d_counts():
    c, b = _partition_candles(_make_current_7d() + _make_baseline_7d(), AS_OF, 168)
    assert len(c) == 168 and len(b) == 168


def test_partition_candles_excludes_out_of_range():
    c, b = _partition_candles([_candle(1, AS_OF - timedelta(hours=400), 1000.0, 50.0)], AS_OF, 24)
    assert c == [] and b == []


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------

def test_check_eligibility_ok_24h():
    ok, reason = check_eligibility(_make_current_24h(), _make_baseline_24h(), AS_OF, 24)
    assert ok is True and reason == "OK"


def test_check_eligibility_ok_7d():
    ok, reason = check_eligibility(_make_current_7d(), _make_baseline_7d(), AS_OF, 168)
    assert ok is True


def test_check_eligibility_no_current_candles():
    ok, reason = check_eligibility([], _make_baseline_24h(), AS_OF, 24)
    assert ok is False and reason == "NO_CURRENT_CANDLES"


def test_check_eligibility_no_baseline_candles():
    ok, reason = check_eligibility(_make_current_24h(), [], AS_OF, 24)
    assert ok is False and reason == "NO_BASELINE_CANDLES"


def test_check_eligibility_low_current_coverage():
    ok, reason = check_eligibility(_make_current_24h()[:19], _make_baseline_24h(), AS_OF, 24)
    assert ok is False and reason.startswith("LOW_CURRENT_COVERAGE:")


def test_check_eligibility_low_baseline_coverage():
    ok, reason = check_eligibility(_make_current_24h(), _make_baseline_24h()[:19], AS_OF, 24)
    assert ok is False and reason.startswith("LOW_BASELINE_COVERAGE:")


def test_check_eligibility_stale_data():
    current = [_candle(1, AS_OF - timedelta(hours=i + 3), 1000.0, 50.0) for i in range(24)]
    ok, reason = check_eligibility(current, _make_baseline_24h(), AS_OF, 24)
    assert ok is False and reason.startswith("STALE_DATA:")


def test_check_eligibility_baseline_zero_volume():
    baseline = [_candle(1, AS_OF - timedelta(hours=47 - i), 1000.0, 0.0) for i in range(24)]
    ok, reason = check_eligibility(_make_current_24h(), baseline, AS_OF, 24)
    assert ok is False and reason == "BASELINE_ZERO_VOLUME"


# ---------------------------------------------------------------------------
# Observation computation
# ---------------------------------------------------------------------------

def test_compute_observation_24h():
    obs = compute_observation(1, "BTC-EUR", 24, _make_current_24h(), _make_baseline_24h(), AS_OF)
    assert obs.price_change_pct == Decimal("5.000000")
    assert obs.quote_volume == Decimal("1200.000000")
    assert obs.relative_volume == Decimal("1.250000")
    assert obs.candle_count == 24
    assert obs.window_close_ts_utc == AS_OF


def test_compute_observation_7d():
    obs = compute_observation(2, "ETH-EUR", 168, _make_current_7d(), _make_baseline_7d(), AS_OF)
    assert obs.price_change_pct == Decimal("10.000000")
    assert obs.quote_volume == Decimal("10080.000000")
    assert obs.relative_volume == Decimal("1.200000")


def test_compute_observation_window_open_ts():
    obs = compute_observation(1, "BTC-EUR", 24, _make_current_24h(), _make_baseline_24h(), AS_OF)
    assert obs.window_open_ts_utc == AS_OF - timedelta(hours=24)


# ---------------------------------------------------------------------------
# CoinGecko normalization
# ---------------------------------------------------------------------------

def test_normalize_coingecko_global_all_fields():
    result = normalize_coingecko_global(MOCK_CG_DATA, datetime(2026, 1, 15, 10, 30, 0))
    assert result.source_status == "AVAILABLE"
    assert result.total_volume_24h_usd == Decimal("300000000000.0")
    assert result.volume_change_pct_24h == Decimal("5.2")
    assert result.btc_dominance_pct == Decimal("62.5")
    assert result.provider_updated_at_utc == datetime.utcfromtimestamp(1735000000)


def test_normalize_coingecko_global_volume_change_pct_populated():
    data = {"volume_change_percentage_24h_usd": 3.7, "total_volume": {},
            "total_market_cap": {}, "market_cap_percentage": {}}
    result = normalize_coingecko_global(data, datetime(2026, 1, 15, 10, 0, 0))
    assert result.volume_change_pct_24h == Decimal("3.7")


def test_normalize_coingecko_global_missing_fields_returns_none():
    result = normalize_coingecko_global({}, datetime(2026, 1, 15, 10, 0, 0))
    assert result.source_status == "AVAILABLE"
    assert result.total_volume_24h_usd is None and result.volume_change_pct_24h is None


def test_normalize_coingecko_global_bad_updated_at_does_not_raise():
    data = {"updated_at": "bad", "total_volume": {}, "total_market_cap": {}, "market_cap_percentage": {}}
    result = normalize_coingecko_global(data, datetime(2026, 1, 15, 10, 0, 0))
    assert result.provider_updated_at_utc is None


# ---------------------------------------------------------------------------
# CoinGecko HTTP client
# ---------------------------------------------------------------------------

def test_fetch_coingecko_global_no_credential():
    result = fetch_coingecko_global(None)
    assert result.source_status == "SKIPPED_NO_CREDENTIAL"


def test_fetch_coingecko_global_empty_string_credential():
    assert fetch_coingecko_global("").source_status == "SKIPPED_NO_CREDENTIAL"


def test_fetch_coingecko_global_timeout():
    with patch(f"{_MOD}.requests.get") as mock_get:
        mock_get.side_effect = req_lib.Timeout()
        result = fetch_coingecko_global("demo-key")
    assert result.source_status == "UNAVAILABLE"
    assert "TIMEOUT" in (result.source_error_reason or "")


def test_fetch_coingecko_global_http_429():
    with patch(f"{_MOD}.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_get.return_value = mock_resp
        mock_resp.raise_for_status.side_effect = req_lib.HTTPError(response=mock_resp)
        result = fetch_coingecko_global("demo-key")
    assert result.source_status == "UNAVAILABLE"
    assert "429" in (result.source_error_reason or "")


def test_fetch_coingecko_global_success():
    with patch(f"{_MOD}.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": MOCK_CG_DATA}
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp
        result = fetch_coingecko_global("demo-key")
    assert result.source_status == "AVAILABLE"
    assert result.volume_change_pct_24h == Decimal("5.2")


def test_fetch_coingecko_global_uses_demo_header():
    with patch(f"{_MOD}.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": {}}
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp
        fetch_coingecko_global("my-api-key")
    assert mock_get.call_args[1]["headers"]["x-cg-demo-api-key"] == "my-api-key"


# ---------------------------------------------------------------------------
# Global context action logic
# ---------------------------------------------------------------------------

def test_determine_global_action_insert_when_no_existing():
    assert _determine_global_action(None, "AVAILABLE") == "INSERT"
    assert _determine_global_action(None, "UNAVAILABLE") == "INSERT"
    assert _determine_global_action(None, "SKIPPED_NO_CREDENTIAL") == "INSERT"


def test_determine_global_action_skip_when_available_exists():
    assert _determine_global_action("AVAILABLE", "AVAILABLE") == "SKIP_AVAILABLE_EXISTS"
    assert _determine_global_action("AVAILABLE", "UNAVAILABLE") == "SKIP_AVAILABLE_EXISTS"
    assert _determine_global_action("AVAILABLE", "SKIPPED_NO_CREDENTIAL") == "SKIP_AVAILABLE_EXISTS"


def test_determine_global_action_promote_from_non_available():
    assert _determine_global_action("UNAVAILABLE", "AVAILABLE") == "PROMOTE"
    assert _determine_global_action("SKIPPED_NO_CREDENTIAL", "AVAILABLE") == "PROMOTE"


def test_determine_global_action_skip_no_improvement():
    assert _determine_global_action("UNAVAILABLE", "UNAVAILABLE") == "SKIP_NO_IMPROVEMENT"
    assert _determine_global_action("UNAVAILABLE", "SKIPPED_NO_CREDENTIAL") == "SKIP_NO_IMPROVEMENT"
    assert _determine_global_action("SKIPPED_NO_CREDENTIAL", "UNAVAILABLE") == "SKIP_NO_IMPROVEMENT"


# ---------------------------------------------------------------------------
# write_global_snapshot — no internal commit; caller owns the transaction
# ---------------------------------------------------------------------------

def test_write_global_snapshot_inserts_new_row_no_commit():
    conn, cursor = _make_conn_mock(fetchone_return=None)
    written, action = write_global_snapshot(conn, AS_OF, _available_result())
    assert written is True and action == "INSERT"
    conn.commit.assert_not_called()


def test_write_global_snapshot_existing_available_is_noop():
    # Existing AVAILABLE row must never be overwritten
    conn, cursor = _make_conn_mock(fetchone_return={"source_status": "AVAILABLE"})
    written, action = write_global_snapshot(conn, AS_OF, _available_result())
    assert written is False and action == "SKIP_AVAILABLE_EXISTS"
    conn.commit.assert_not_called()


def test_write_global_snapshot_existing_available_not_downgraded_by_unavailable():
    conn, cursor = _make_conn_mock(fetchone_return={"source_status": "AVAILABLE"})
    written, action = write_global_snapshot(conn, AS_OF, _unavailable_result())
    assert written is False and action == "SKIP_AVAILABLE_EXISTS"
    conn.commit.assert_not_called()


def test_write_global_snapshot_existing_available_not_downgraded_by_skipped():
    conn, cursor = _make_conn_mock(fetchone_return={"source_status": "AVAILABLE"})
    written, action = write_global_snapshot(conn, AS_OF, _skipped_result())
    assert written is False and action == "SKIP_AVAILABLE_EXISTS"
    conn.commit.assert_not_called()


def test_write_global_snapshot_unavailable_promotes_when_available_arrives():
    # Existing UNAVAILABLE row must promote when AVAILABLE result arrives
    conn, cursor = _make_conn_mock(fetchone_return={"source_status": "UNAVAILABLE"})
    written, action = write_global_snapshot(conn, AS_OF, _available_result())
    assert written is True and action == "PROMOTE"
    conn.commit.assert_not_called()


def test_write_global_snapshot_skipped_promotes_when_available_arrives():
    conn, cursor = _make_conn_mock(fetchone_return={"source_status": "SKIPPED_NO_CREDENTIAL"})
    written, action = write_global_snapshot(conn, AS_OF, _available_result())
    assert written is True and action == "PROMOTE"
    conn.commit.assert_not_called()


def test_write_global_snapshot_unavailable_does_not_promote_on_unavailable():
    conn, cursor = _make_conn_mock(fetchone_return={"source_status": "UNAVAILABLE"})
    written, action = write_global_snapshot(conn, AS_OF, _unavailable_result())
    assert written is False and action == "SKIP_NO_IMPROVEMENT"
    conn.commit.assert_not_called()


def test_write_global_snapshot_dry_run_skips_write():
    conn, cursor = _make_conn_mock(fetchone_return=None)
    written, action = write_global_snapshot(conn, AS_OF, _available_result(), dry_run=True)
    assert written is False and action == "INSERT"
    conn.commit.assert_not_called()


# ---------------------------------------------------------------------------
# write_rotation_snapshot — no internal commit; caller owns the transaction
# ---------------------------------------------------------------------------

def test_write_rotation_snapshot_no_commit():
    conn, cursor = _make_conn_mock(fetchone_return={"snapshot_id": 7})
    cursor.execute.side_effect = [1, None, 1, 1]
    write_rotation_snapshot(conn, AS_OF, 24, "bitvavo", 2, 0, [_make_obs(1), _make_obs(2, "ETH-EUR")])
    conn.commit.assert_not_called()


def test_write_rotation_snapshot_idempotent_on_duplicate():
    conn, cursor = _make_conn_mock(fetchone_return={"snapshot_id": 42})
    cursor.execute.side_effect = [0, None, 0, 0]
    new_snap, obs_written = write_rotation_snapshot(
        conn, AS_OF, 24, "bitvavo", 2, 0, [_make_obs(1), _make_obs(2, "ETH-EUR")]
    )
    assert new_snap is False and obs_written == 0
    conn.commit.assert_not_called()


def test_write_rotation_snapshot_new_inserts():
    conn, cursor = _make_conn_mock(fetchone_return={"snapshot_id": 7})
    cursor.execute.side_effect = [1, None, 1, 1]
    new_snap, obs_written = write_rotation_snapshot(
        conn, AS_OF, 24, "bitvavo", 2, 0, [_make_obs(1), _make_obs(2, "ETH-EUR")]
    )
    assert new_snap is True and obs_written == 2
    conn.commit.assert_not_called()


# ---------------------------------------------------------------------------
# check_schema_ready
# ---------------------------------------------------------------------------

def test_check_schema_ready_all_present():
    conn, cursor = _make_conn_mock()
    cursor.fetchall.return_value = [
        {"TABLE_NAME": "market_rotation_snapshot_v1"},
        {"TABLE_NAME": "market_rotation_observation_v1"},
        {"TABLE_NAME": "market_global_snapshot_v1"},
    ]
    assert check_schema_ready(conn) == []


def test_check_schema_ready_reports_missing():
    conn, cursor = _make_conn_mock()
    cursor.fetchall.return_value = [{"TABLE_NAME": "market_rotation_snapshot_v1"}]
    missing = check_schema_ready(conn)
    assert "market_rotation_observation_v1" in missing
    assert "market_global_snapshot_v1" in missing
    assert "market_rotation_snapshot_v1" not in missing


def test_check_schema_ready_all_missing():
    conn, cursor = _make_conn_mock()
    cursor.fetchall.return_value = []
    assert len(check_schema_ready(conn)) == 3


# ---------------------------------------------------------------------------
# main() integration — schema preflight
# ---------------------------------------------------------------------------

def _build_patches(*, missing_tables=None, assets=None, candles=None,
                   write_rot_kw=None, write_glob_kw=None, global_result=None):
    if missing_tables is None:
        missing_tables = []
    if assets is None:
        assets = [AssetRow(1, "BTC", "BTC-EUR")]
    if candles is None:
        candles = {}
    if write_rot_kw is None:
        write_rot_kw = {"return_value": (True, 0)}
    if write_glob_kw is None:
        write_glob_kw = {"return_value": (True, "INSERT")}
    ps = [
        patch(f"{_MOD}.get_connection"),
        patch(f"{_MOD}.check_schema_ready", return_value=missing_tables),
        patch(f"{_MOD}.fetch_eligible_assets", return_value=assets),
        patch(f"{_MOD}.fetch_candles_bulk", return_value=candles),
        patch(f"{_MOD}.write_rotation_snapshot", **write_rot_kw),
        patch(f"{_MOD}.write_global_snapshot", **write_glob_kw),
        patch(f"{_MOD}.fetch_coingecko_global",
              return_value=(global_result or _skipped_result())),
    ]
    return ps


def _run(argv, *, missing_tables=None, assets=None, candles=None,
         write_rot_kw=None, write_glob_kw=None, global_result=None):
    mock_conn = MagicMock()
    ps = _build_patches(missing_tables=missing_tables, assets=assets, candles=candles,
                        write_rot_kw=write_rot_kw, write_glob_kw=write_glob_kw,
                        global_result=global_result)
    buf = io.StringIO()
    with ps[0] as mc, ps[1], ps[2], ps[3], ps[4] as mr, ps[5] as mg, ps[6], redirect_stdout(buf):
        mc.return_value = mock_conn
        rc = main(argv)
    return rc, buf.getvalue(), mock_conn, mr, mg


def test_dry_run_pending_migration_exits_zero():
    rc, out, _, _, _ = _run(
        ["--dry-run", "--as-of-ts", "2026-01-15T12:00:00"],
        missing_tables=["market_rotation_snapshot_v1", "market_rotation_observation_v1",
                        "market_global_snapshot_v1"],
    )
    assert rc == 0
    assert "TARGET_SCHEMA=PENDING_MIGRATION" in out


def test_dry_run_pending_migration_shows_eligible_counts():
    rc, out, conn, _, _ = _run(
        ["--dry-run", "--as-of-ts", "2026-01-15T12:00:00"],
        missing_tables=["market_rotation_snapshot_v1"],
    )
    assert rc == 0
    assert "DRY_RUN" in out
    conn.commit.assert_not_called()


def test_write_db_pending_migration_exits_nonzero():
    rc, out, conn, m_rot, m_glob = _run(
        ["--write-db", "--as-of-ts", "2026-01-15T12:00:00"],
        missing_tables=["market_global_snapshot_v1"],
    )
    assert rc == 1
    assert "PENDING_MIGRATION" in out


def test_write_db_pending_migration_performs_zero_writes():
    rc, out, conn, m_rot, m_glob = _run(
        ["--write-db", "--as-of-ts", "2026-01-15T12:00:00"],
        missing_tables=["market_global_snapshot_v1"],
    )
    m_rot.assert_not_called()
    m_glob.assert_not_called()
    conn.commit.assert_not_called()


# ---------------------------------------------------------------------------
# main() integration — transactional semantics
# ---------------------------------------------------------------------------

def test_write_db_second_horizon_failure_rolls_back():
    call_count = 0

    def rot_fail_on_second(*a, **kw):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("forced second-horizon failure")
        return (True, 0)

    mock_conn = MagicMock()
    ps = _build_patches(write_rot_kw={"side_effect": rot_fail_on_second},
                        global_result=_available_result())
    with ps[0] as mc, ps[1], ps[2], ps[3], ps[4], ps[5], ps[6]:
        mc.return_value = mock_conn
        with pytest.raises(RuntimeError, match="forced second-horizon failure"):
            main(["--write-db", "--as-of-ts", "2026-01-15T12:00:00"])
    mock_conn.rollback.assert_called_once()
    mock_conn.commit.assert_not_called()


def test_write_db_global_db_failure_rolls_back_both_horizons():
    mock_conn = MagicMock()
    ps = _build_patches(write_glob_kw={"side_effect": RuntimeError("global DB failure")},
                        global_result=_available_result())
    with ps[0] as mc, ps[1], ps[2], ps[3], ps[4] as m_rot, ps[5], ps[6]:
        mc.return_value = mock_conn
        with pytest.raises(RuntimeError, match="global DB failure"):
            main(["--write-db", "--as-of-ts", "2026-01-15T12:00:00"])
    mock_conn.rollback.assert_called_once()
    mock_conn.commit.assert_not_called()
    assert m_rot.call_count == 2   # both horizons were attempted before global failed


def test_write_db_provider_unavailable_still_commits():
    # Provider failure is a valid status; the UNAVAILABLE row is part of the normal transaction
    mock_conn = MagicMock()
    ps = _build_patches(global_result=_unavailable_result())
    with ps[0] as mc, ps[1], ps[2], ps[3], ps[4], ps[5], ps[6]:
        mc.return_value = mock_conn
        rc = main(["--write-db", "--as-of-ts", "2026-01-15T12:00:00"])
    assert rc == 0
    mock_conn.commit.assert_called_once()
    mock_conn.rollback.assert_not_called()


def test_write_db_single_commit_covers_all_horizons_and_global():
    mock_conn = MagicMock()
    ps = _build_patches(global_result=_available_result())
    with ps[0] as mc, ps[1], ps[2], ps[3], ps[4] as m_rot, ps[5] as m_glob, ps[6]:
        mc.return_value = mock_conn
        rc = main(["--write-db", "--as-of-ts", "2026-01-15T12:00:00"])
    assert rc == 0
    assert m_rot.call_count == 2
    m_glob.assert_called_once()
    mock_conn.commit.assert_called_once()


# ---------------------------------------------------------------------------
# validate-only mode — no DB connection
# ---------------------------------------------------------------------------

def test_validate_only_does_not_open_db():
    with patch(f"{_MOD}.get_connection") as mock_conn:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--validate-only", "--as-of-ts", "2026-01-15T12:00:00"])
    assert rc == 0
    mock_conn.assert_not_called()


def test_validate_only_output_contains_key_fields():
    buf = io.StringIO()
    with redirect_stdout(buf):
        main(["--validate-only", "--as-of-ts", "2026-01-15T12:00:00"])
    out = buf.getvalue()
    assert "validate-only" in out
    assert "coingecko" in out


# ---------------------------------------------------------------------------
# Architecture: no forbidden imports
# ---------------------------------------------------------------------------

def test_no_account_or_execution_imports():
    src = Path("src/research/run_market_rotation_history_v1.py").read_text()
    tree = ast.parse(src)
    forbidden = (
        "src.decision", "src.decision_gate", "src.execution_planner",
        "src.executor", "src.account", "src.synth_sleeves",
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for prefix in forbidden:
                assert not node.module.startswith(prefix), (
                    f"Runner imports from forbidden layer: {node.module}"
                )
