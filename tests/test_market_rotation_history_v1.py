from __future__ import annotations

from tests.writer_auth_support import make_test_authorization
_RP_AUTH = make_test_authorization("market_rotation_pressure")

import ast
import io
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests as req_lib
import pytest

from src.research.run_market_rotation_history_v1 import (
    AssetRow,
    CandleRecord,
    CANDLE_INTERVAL,
    FETCH_BATCH_ROWS,
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
    fetch_candles_bulk,
    fetch_coingecko_global,
    floor_to_hour,
    main,
    normalize_coingecko_global,
    split_missing_tables,
    write_global_snapshot,
    write_rotation_snapshot,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _authorized_writer_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests exercise write/rollback mechanics and assume authorization is
    already granted. The writer-capability authorization boundary itself is
    covered by tests/test_writer_capability_authorization_v1.py."""
    from tests.writer_auth_support import install_authorized_writer_context

    install_authorized_writer_context(monkeypatch)

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


def _make_conn_mock(fetchone_return=None, fetchone_side_effect=None):
    cursor = MagicMock()
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)
    if fetchone_side_effect is not None:
        cursor.fetchone.side_effect = fetchone_side_effect
    else:
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


def test_canonical_rotation_pressure_source_is_closed_hourly_candles():
    assert CANDLE_INTERVAL == "1h"
    assert floor_to_hour(datetime(2026, 1, 15, 8, 59, 59)) == datetime(2026, 1, 15, 8)


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
    assert result.provider_updated_at_utc == datetime.fromtimestamp(1735000000, UTC).replace(tzinfo=None)


def test_normalize_coingecko_global_empty_payload_is_unavailable():
    result = normalize_coingecko_global({}, datetime(2026, 1, 15, 10, 0, 0))
    assert result.source_status == "UNAVAILABLE"
    assert (result.source_error_reason or "").startswith("INVALID_PAYLOAD:")


def test_normalize_coingecko_global_missing_required_field_is_unavailable():
    data = dict(MOCK_CG_DATA)
    data.pop("volume_change_percentage_24h_usd")
    result = normalize_coingecko_global(data, datetime(2026, 1, 15, 10, 0, 0))
    assert result.source_status == "UNAVAILABLE"
    assert "volume_change_percentage_24h_usd" in (result.source_error_reason or "")


def test_normalize_coingecko_global_nan_or_infinite_is_unavailable():
    data = dict(MOCK_CG_DATA)
    data["market_cap_percentage"] = {"btc": "NaN", "eth": "Infinity"}
    result = normalize_coingecko_global(data, datetime(2026, 1, 15, 10, 0, 0))
    assert result.source_status == "UNAVAILABLE"
    assert "market_cap_percentage.btc" in (result.source_error_reason or "")


def test_normalize_coingecko_global_invalid_updated_at_is_unavailable():
    data = dict(MOCK_CG_DATA)
    data["updated_at"] = "bad"
    result = normalize_coingecko_global(data, datetime(2026, 1, 15, 10, 0, 0))
    assert result.source_status == "UNAVAILABLE"
    assert "updated_at" in (result.source_error_reason or "")


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


def test_fetch_coingecko_global_invalid_payload_never_returns_available():
    with patch(f"{_MOD}.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": {}}
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp
        result = fetch_coingecko_global("demo-key")
    assert result.source_status == "UNAVAILABLE"
    assert (result.source_error_reason or "").startswith("INVALID_PAYLOAD:")


def test_fetch_coingecko_global_invalid_json_is_invalid_payload():
    with patch(f"{_MOD}.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.side_effect = ValueError("bad json")
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp
        result = fetch_coingecko_global("demo-key")
    assert result.source_status == "UNAVAILABLE"
    assert result.source_error_reason == "INVALID_PAYLOAD:JSON_DECODE"


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
    written, action = write_global_snapshot(conn, AS_OF, _available_result(), authorization=_RP_AUTH)
    assert written is True and action == "INSERT"
    conn.commit.assert_not_called()


def test_write_global_snapshot_existing_available_is_noop():
    conn, cursor = _make_conn_mock(fetchone_return={"source_status": "AVAILABLE"})
    written, action = write_global_snapshot(conn, AS_OF, _available_result(), authorization=_RP_AUTH)
    assert written is False and action == "SKIP_AVAILABLE_EXISTS"
    conn.commit.assert_not_called()


def test_write_global_snapshot_existing_available_not_downgraded_by_unavailable():
    conn, cursor = _make_conn_mock(fetchone_return={"source_status": "AVAILABLE"})
    written, action = write_global_snapshot(conn, AS_OF, _unavailable_result(), authorization=_RP_AUTH)
    assert written is False and action == "SKIP_AVAILABLE_EXISTS"
    conn.commit.assert_not_called()


def test_write_global_snapshot_existing_available_not_downgraded_by_skipped():
    conn, cursor = _make_conn_mock(fetchone_return={"source_status": "AVAILABLE"})
    written, action = write_global_snapshot(conn, AS_OF, _skipped_result(), authorization=_RP_AUTH)
    assert written is False and action == "SKIP_AVAILABLE_EXISTS"
    conn.commit.assert_not_called()


def test_write_global_snapshot_unavailable_promotes_when_available_arrives():
    conn, cursor = _make_conn_mock(fetchone_return={"source_status": "UNAVAILABLE"})
    written, action = write_global_snapshot(conn, AS_OF, _available_result(), authorization=_RP_AUTH)
    assert written is True and action == "PROMOTE"
    conn.commit.assert_not_called()


def test_write_global_snapshot_skipped_promotes_when_available_arrives():
    conn, cursor = _make_conn_mock(fetchone_return={"source_status": "SKIPPED_NO_CREDENTIAL"})
    written, action = write_global_snapshot(conn, AS_OF, _available_result(), authorization=_RP_AUTH)
    assert written is True and action == "PROMOTE"
    conn.commit.assert_not_called()


def test_write_global_snapshot_unavailable_does_not_promote_on_unavailable():
    conn, cursor = _make_conn_mock(fetchone_return={"source_status": "UNAVAILABLE"})
    written, action = write_global_snapshot(conn, AS_OF, _unavailable_result(), authorization=_RP_AUTH)
    assert written is False and action == "SKIP_NO_IMPROVEMENT"
    conn.commit.assert_not_called()


def test_write_global_snapshot_dry_run_skips_write():
    conn, cursor = _make_conn_mock(fetchone_return=None)
    written, action = write_global_snapshot(conn, AS_OF, _available_result(), dry_run=True, authorization=_RP_AUTH)
    assert written is False and action == "INSERT"
    conn.commit.assert_not_called()


# ---------------------------------------------------------------------------
# write_rotation_snapshot — no internal commit; caller owns the transaction
# ---------------------------------------------------------------------------

def test_write_rotation_snapshot_no_commit():
    conn, cursor = _make_conn_mock(fetchone_side_effect=[
        {"snapshot_id": 7, "eligible_market_count": 0, "excluded_market_count": 0, "observation_count": 0},
        {"observation_count": 2},
    ])
    cursor.execute.side_effect = [1, None, 1, 1, None, 1]
    write_rotation_snapshot(conn, AS_OF, 24, "bitvavo", 2, 0, [_make_obs(1), _make_obs(2, "ETH-EUR")], authorization=_RP_AUTH)
    conn.commit.assert_not_called()


def test_write_rotation_snapshot_idempotent_on_duplicate():
    conn, cursor = _make_conn_mock(fetchone_side_effect=[
        {"snapshot_id": 42, "eligible_market_count": 2, "excluded_market_count": 0, "observation_count": 2},
        {"observation_count": 2},
    ])
    cursor.execute.side_effect = [0, None, 0, 0, None, 0]
    status, obs_written = write_rotation_snapshot(
        conn, AS_OF, 24, "bitvavo", 2, 0, [_make_obs(1), _make_obs(2, "ETH-EUR")]
    , authorization=_RP_AUTH)
    assert status == "NOOP_ALREADY_COMPLETE" and obs_written == 0
    conn.commit.assert_not_called()


def test_write_rotation_snapshot_new_inserts():
    conn, cursor = _make_conn_mock(fetchone_side_effect=[
        {"snapshot_id": 7, "eligible_market_count": 0, "excluded_market_count": 0, "observation_count": 0},
        {"observation_count": 2},
    ])
    cursor.execute.side_effect = [1, None, 1, 1, None, 1]
    status, obs_written = write_rotation_snapshot(
        conn, AS_OF, 24, "bitvavo", 2, 0, [_make_obs(1), _make_obs(2, "ETH-EUR")]
    , authorization=_RP_AUTH)
    assert status == "CREATED" and obs_written == 2
    conn.commit.assert_not_called()


def test_write_rotation_snapshot_same_hour_rerun_reconciles_header_counts():
    conn, cursor = _make_conn_mock(fetchone_side_effect=[
        {"snapshot_id": 42, "eligible_market_count": 1, "excluded_market_count": 1, "observation_count": 1},
        {"observation_count": 2},
    ])
    cursor.execute.side_effect = [0, None, 1, None, 1]
    status, obs_written = write_rotation_snapshot(
        conn, AS_OF, 24, "bitvavo", 2, 0, [_make_obs(2, "ETH-EUR")]
    , authorization=_RP_AUTH)
    assert status == "RECONCILED"
    assert obs_written == 1
    update_params = cursor.execute.call_args_list[-1].args[1]
    assert update_params == (2, 0, 2, 42, 2, 0, 2)


def test_write_rotation_snapshot_same_hour_noop_reports_already_complete():
    conn, cursor = _make_conn_mock(fetchone_side_effect=[
        {"snapshot_id": 42, "eligible_market_count": 2, "excluded_market_count": 0, "observation_count": 2},
        {"observation_count": 2},
    ])
    cursor.execute.side_effect = [0, None, 0, 0, None, 0]
    status, obs_written = write_rotation_snapshot(
        conn, AS_OF, 24, "bitvavo", 2, 0, [_make_obs(1), _make_obs(2, "ETH-EUR")]
    , authorization=_RP_AUTH)
    assert status == "NOOP_ALREADY_COMPLETE"
    assert obs_written == 0
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


def test_split_missing_tables():
    local_missing, global_missing = split_missing_tables([
        "market_rotation_snapshot_v1",
        "market_global_snapshot_v1",
    ])
    assert local_missing == ["market_rotation_snapshot_v1"]
    assert global_missing == ["market_global_snapshot_v1"]


class _StreamingCursor:
    def __init__(self, batches: list[list[dict[str, object]]]):
        self._batches = list(batches)
        self.fetchmany_calls: list[int] = []
        self.execute_calls: list[tuple[str, list[object]]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql: str, params: list[object]):
        self.execute_calls.append((sql, params))
        return None

    def fetchmany(self, size: int) -> list[dict[str, object]]:
        self.fetchmany_calls.append(size)
        if self._batches:
            return self._batches.pop(0)
        return []

    def fetchall(self):
        raise AssertionError("fetchall must not be used for candle streaming")


class _StreamingConn:
    def __init__(self, cursor: _StreamingCursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


def test_fetch_candles_bulk_uses_fetchmany():
    batches = [
        [
            {
                "asset_id": 1,
                "open_ts_utc": AS_OF - timedelta(hours=2),
                "close_ts_utc": AS_OF - timedelta(hours=1),
                "close_price": "1000.5",
                "volume_quote_eur": "55.25",
            }
        ],
        [
            {
                "asset_id": 2,
                "open_ts_utc": AS_OF - timedelta(hours=1),
                "close_ts_utc": AS_OF,
                "close_price": "2000.5",
                "volume_quote_eur": "65.25",
            }
        ],
        [],
    ]
    cursor = _StreamingCursor(batches)
    conn = _StreamingConn(cursor)
    result = fetch_candles_bulk(conn, [1, 2], "bitvavo", AS_OF - timedelta(hours=10), AS_OF)
    assert sorted(result.keys()) == [1, 2]
    assert result[1][0].close_price == Decimal("1000.5")
    assert result[2][0].volume_quote_eur == Decimal("65.25")
    assert cursor.fetchmany_calls == [FETCH_BATCH_ROWS, FETCH_BATCH_ROWS, FETCH_BATCH_ROWS]


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
        write_rot_kw = {"return_value": ("CREATED", 0)}
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
    assert "LOCAL_ROTATION_TARGET_SCHEMA_MISSING" in out
    assert "GLOBAL_CONTEXT_TARGET_SCHEMA_MISSING" in out


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
        missing_tables=["market_rotation_observation_v1", "market_global_snapshot_v1"],
    )
    assert rc == 1
    assert "FAILED  LOCAL_ROTATION_TARGET_SCHEMA_MISSING" in out


def test_write_db_pending_migration_performs_zero_writes():
    rc, out, conn, m_rot, m_glob = _run(
        ["--write-db", "--as-of-ts", "2026-01-15T12:00:00"],
        missing_tables=["market_rotation_observation_v1", "market_global_snapshot_v1"],
    )
    m_rot.assert_not_called()
    m_glob.assert_not_called()
    conn.commit.assert_not_called()


def test_write_db_global_schema_missing_commits_local_and_exits_nonzero():
    rc, out, conn, m_rot, m_glob = _run(
        ["--write-db", "--as-of-ts", "2026-01-15T12:00:00"],
        missing_tables=["market_global_snapshot_v1"],
    )
    assert rc == 1
    assert "GLOBAL_CONTEXT_TARGET_SCHEMA_MISSING" in out
    assert m_rot.call_count == 2
    m_glob.assert_not_called()
    conn.commit.assert_called_once()


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


def test_write_db_global_db_failure_returns_nonzero_after_local_commit():
    mock_conn = MagicMock()
    ps = _build_patches(write_glob_kw={"side_effect": RuntimeError("global DB failure")},
                        global_result=_available_result())
    buf = io.StringIO()
    with ps[0] as mc, ps[1], ps[2], ps[3], ps[4] as m_rot, ps[5], ps[6], redirect_stdout(buf):
        mc.return_value = mock_conn
        rc = main(["--write-db", "--as-of-ts", "2026-01-15T12:00:00"])
    assert rc == 1
    assert "GLOBAL_CONTEXT_PERSIST_FAILED" in buf.getvalue()
    assert m_rot.call_count == 2
    assert mock_conn.commit.call_count == 1
    mock_conn.rollback.assert_called_once()


def test_write_db_local_rotation_commit_survives_global_db_failure():
    mock_conn = MagicMock()
    ps = _build_patches(write_glob_kw={"side_effect": RuntimeError("global DB failure")},
                        global_result=_available_result())
    with ps[0] as mc, ps[1], ps[2], ps[3], ps[4] as m_rot, ps[5], ps[6]:
        mc.return_value = mock_conn
        rc = main(["--write-db", "--as-of-ts", "2026-01-15T12:00:00"])
    assert rc == 1
    assert m_rot.call_count == 2
    assert mock_conn.commit.call_count == 1


def test_write_db_provider_unavailable_still_commits():
    mock_conn = MagicMock()
    ps = _build_patches(global_result=_unavailable_result())
    with ps[0] as mc, ps[1], ps[2], ps[3], ps[4], ps[5], ps[6]:
        mc.return_value = mock_conn
        rc = main(["--write-db", "--as-of-ts", "2026-01-15T12:00:00"])
    assert rc == 0
    assert mock_conn.commit.call_count == 2
    mock_conn.rollback.assert_not_called()


def test_write_db_commits_local_then_global():
    mock_conn = MagicMock()
    ps = _build_patches(global_result=_available_result())
    with ps[0] as mc, ps[1], ps[2], ps[3], ps[4] as m_rot, ps[5] as m_glob, ps[6]:
        mc.return_value = mock_conn
        rc = main(["--write-db", "--as-of-ts", "2026-01-15T12:00:00"])
    assert rc == 0
    assert m_rot.call_count == 2
    m_glob.assert_called_once()
    assert mock_conn.commit.call_count == 2


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
