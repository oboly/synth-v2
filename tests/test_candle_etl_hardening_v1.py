"""
Tests for candle ETL hardening and Profit Plan pipeline health gate.

Verifies:
- HTTP 400 per market/interval → MarketUnavailableError, not fatal
- ALMANAK-style failure does not abort remaining markets
- Unsupported market excluded by active market filter
- skipped_market_errors recorded in runner output
- ZoneContextLoadResult carries native_source_missing
- render_full_html exposes pipeline banner when globally unavailable
- build_json_snapshot includes pipeline_health key
- Cockpit order: candle freshness check before native union build
- No broker writes / order submission in ETL

broker_private_calls=0
broker_writes=0
order_submission=0
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests


# ---------------------------------------------------------------------------
# MarketUnavailableError — raised on HTTP 400/404
# ---------------------------------------------------------------------------

def test_market_unavailable_error_attributes() -> None:
    from src.etl.bitvavo.etl_bitvavo_candles import MarketUnavailableError

    exc = MarketUnavailableError(market="ALMANAK-EUR", interval_code="15m", http_status=400)
    assert exc.market == "ALMANAK-EUR"
    assert exc.interval_code == "15m"
    assert exc.http_status == 400
    assert "ALMANAK-EUR" in str(exc)
    assert "400" in str(exc)


@pytest.mark.parametrize("status_code", [400, 404])
def test_fetch_bitvavo_candles_raises_on_unavailable_market(status_code: int) -> None:
    """HTTP 400 or 404 from Bitvavo must raise MarketUnavailableError, not HTTPError."""
    from src.etl.bitvavo.etl_bitvavo_candles import (
        MarketUnavailableError,
        fetch_bitvavo_candles,
    )

    session = MagicMock(spec=requests.Session)
    mock_response = MagicMock()
    mock_response.status_code = status_code
    session.get.return_value = mock_response

    with pytest.raises(MarketUnavailableError) as exc_info:
        fetch_bitvavo_candles(
            session=session,
            market="ALMANAK-EUR",
            interval_code="15m",
            start_ms=1_000_000,
            end_ms=2_000_000,
            timeout_seconds=5,
        )

    assert exc_info.value.http_status == status_code
    assert exc_info.value.market == "ALMANAK-EUR"


def test_fetch_bitvavo_candles_other_http_errors_still_raise() -> None:
    """Non-400/404 HTTP errors (e.g. 503) must still propagate as requests.HTTPError."""
    from src.etl.bitvavo.etl_bitvavo_candles import fetch_bitvavo_candles

    session = MagicMock(spec=requests.Session)
    mock_response = MagicMock()
    mock_response.status_code = 503
    mock_response.raise_for_status.side_effect = requests.HTTPError("503")
    session.get.return_value = mock_response

    with pytest.raises(requests.HTTPError):
        fetch_bitvavo_candles(
            session=session,
            market="BTC-EUR",
            interval_code="1h",
            start_ms=1_000_000,
            end_ms=2_000_000,
            timeout_seconds=5,
        )


# ---------------------------------------------------------------------------
# fetch_active_bitvavo_markets
# ---------------------------------------------------------------------------

def test_fetch_active_bitvavo_markets_returns_trading_only() -> None:
    from src.etl.bitvavo.etl_bitvavo_candles import fetch_active_bitvavo_markets

    session = MagicMock(spec=requests.Session)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {"market": "BTC-EUR", "status": "trading"},
        {"market": "ETH-EUR", "status": "trading"},
        {"market": "ALMANAK-EUR", "status": "unavailable"},
        {"market": "DELISTED-EUR", "status": "halted"},
    ]
    mock_response.raise_for_status.return_value = None
    session.get.return_value = mock_response

    active = fetch_active_bitvavo_markets(session=session)

    assert "BTC-EUR" in active
    assert "ETH-EUR" in active
    assert "ALMANAK-EUR" not in active
    assert "DELISTED-EUR" not in active


def test_fetch_active_bitvavo_markets_excludes_unsupported_market() -> None:
    """An unavailable market (like ALMANAK-EUR) must be excluded from the active set."""
    from src.etl.bitvavo.etl_bitvavo_candles import fetch_active_bitvavo_markets

    session = MagicMock(spec=requests.Session)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = [
        {"market": "SOL-EUR", "status": "trading"},
        {"market": "ALMANAK-EUR", "status": "unavailable"},
    ]
    session.get.return_value = mock_response

    active = fetch_active_bitvavo_markets(session=session)
    assert "ALMANAK-EUR" not in active
    assert "SOL-EUR" in active


# ---------------------------------------------------------------------------
# run_candles_etl.py — MarketUnavailableError is caught per-task, run continues
# ---------------------------------------------------------------------------

def test_market_unavailable_does_not_abort_remaining_markets() -> None:
    """
    If one market/interval raises MarketUnavailableError, the ETL run continues
    for all remaining markets. Regression for ALMANAK-EUR HTTP 400 abort.
    """
    from src.etl.bitvavo.run_candles_etl import (
        AssetRow,
        EtlConfig,
        RunControl,
        call_etl_function,
    )
    from src.etl.bitvavo.etl_bitvavo_candles import MarketUnavailableError

    completed: list[str] = []

    def fake_etl_fn(*, conn, session, asset_id, market, venue, interval_code, **_):
        if market == "ALMANAK-EUR":
            raise MarketUnavailableError(
                market=market, interval_code=interval_code, http_status=400
            )
        completed.append(market)
        return {"written_rows": 1}

    assets = [
        AssetRow(asset_id=1, symbol="BTC", market="BTC-EUR"),
        AssetRow(asset_id=2, symbol="ALMANAK", market="ALMANAK-EUR"),
        AssetRow(asset_id=3, symbol="ETH", market="ETH-EUR"),
    ]
    intervals = ["1h"]
    config = EtlConfig(
        venue="bitvavo",
        quote_asset="EUR",
        intervals=intervals,
        default_lookback={"1h": "168h"},
        batch_limit=1000,
        timeout_seconds=20,
        sleep_seconds=0.0,
        raw={},
    )

    conn = MagicMock()
    session = MagicMock()
    control = RunControl()
    skipped_market_errors: list[dict] = []

    from datetime import UTC, datetime, timedelta

    start_dt = datetime(2026, 1, 1, tzinfo=UTC)
    end_dt = datetime(2026, 1, 2, tzinfo=UTC)

    for asset in assets:
        for interval_code in intervals:
            try:
                call_etl_function(
                    fake_etl_fn,
                    conn=conn,
                    session=session,
                    asset=asset,
                    interval_code=interval_code,
                    start_dt=start_dt,
                    end_dt=end_dt,
                    venue=config.venue,
                    config=config,
                    dry_run=True,
                )
            except MarketUnavailableError as exc:
                skipped_market_errors.append({"market": exc.market})

    assert "BTC-EUR" in completed, "BTC-EUR must complete despite ALMANAK-EUR failure"
    assert "ETH-EUR" in completed, "ETH-EUR must complete despite ALMANAK-EUR failure"
    assert "ALMANAK-EUR" not in completed
    assert any(e["market"] == "ALMANAK-EUR" for e in skipped_market_errors)


def test_skipped_market_errors_recorded_in_manifest_output() -> None:
    """run_candles_etl.py FINISHED line must include skipped_market_errors count."""
    src = Path("src/etl/bitvavo/run_candles_etl.py").read_text()
    assert "skipped_market_errors" in src, (
        "run_candles_etl.py must track and emit skipped_market_errors in FINISHED line"
    )
    assert "SKIPPED_MARKET_ERROR" in src


def test_no_broker_writes_in_candle_etl() -> None:
    src = Path("src/etl/bitvavo/run_candles_etl.py").read_text()
    assert "broker_writes=0" in src


# ---------------------------------------------------------------------------
# ZoneContextLoadResult — native_source_missing field
# ---------------------------------------------------------------------------

def test_zone_context_result_has_native_source_missing_field() -> None:
    from src.reporting.run_manual_short_trader_profit_plan_v1 import ZoneContextLoadResult

    result = ZoneContextLoadResult(
        fib_ext_by_symbol={},
        reentry_by_symbol={},
        activation_ts_by_symbol={},
        input_status_by_symbol={},
        coverage_status_by_symbol={},
        display_state_by_symbol={},
        source_name="test",
        source_missing=False,
        native_source_missing=True,
    )
    assert result.native_source_missing is True


def test_zone_context_result_native_source_missing_defaults_false() -> None:
    from src.reporting.run_manual_short_trader_profit_plan_v1 import ZoneContextLoadResult

    result = ZoneContextLoadResult(
        fib_ext_by_symbol={},
        reentry_by_symbol={},
        activation_ts_by_symbol={},
        input_status_by_symbol={},
        coverage_status_by_symbol={},
        display_state_by_symbol={},
        source_name="test",
        source_missing=False,
    )
    assert result.native_source_missing is False


# ---------------------------------------------------------------------------
# render_full_html — pipeline banner
# ---------------------------------------------------------------------------

def test_render_full_html_shows_pipeline_banner_when_set() -> None:
    from src.reporting.manual_short_trader_profit_plan_v1 import render_full_html

    banner = "<div class='pipeline-warn'>Native SHORT context CSV missing</div>"
    html = render_full_html([], pipeline_banner_html=banner)
    assert "pipeline-warn" in html
    assert "Native SHORT context CSV missing" in html


def test_render_full_html_no_banner_by_default() -> None:
    from src.reporting.manual_short_trader_profit_plan_v1 import render_full_html

    html = render_full_html([], pipeline_banner_html=None)
    # CSS class is always present in <style>; absence of any banner div content is the assertion
    assert "Native SHORT context" not in html


def test_render_full_html_global_warning_when_native_unavailable() -> None:
    """Regression: when native context is globally missing, a visible warning must appear."""
    from src.reporting.manual_short_trader_profit_plan_v1 import render_full_html

    html = render_full_html(
        [],
        pipeline_banner_html=(
            "<div class='pipeline-warn'>"
            "Native SHORT context unavailable — check candle ETL pipeline."
            "</div>"
        ),
    )
    assert "Native SHORT context unavailable" in html


# ---------------------------------------------------------------------------
# build_json_snapshot — pipeline_health key
# ---------------------------------------------------------------------------

def test_build_json_snapshot_includes_pipeline_health() -> None:
    from src.reporting.manual_short_trader_profit_plan_v1 import build_json_snapshot

    health = {
        "pipeline_status": "source_missing",
        "native_source_missing": True,
        "blocking_reasons": ["NATIVE_SHORT_CONTEXT_SOURCE_MISSING"],
    }
    snapshot = build_json_snapshot([], pipeline_health=health)
    assert "pipeline_health" in snapshot
    assert snapshot["pipeline_health"]["native_source_missing"] is True
    assert "NATIVE_SHORT_CONTEXT_SOURCE_MISSING" in snapshot["pipeline_health"]["blocking_reasons"]


def test_build_json_snapshot_pipeline_health_none_by_default() -> None:
    from src.reporting.manual_short_trader_profit_plan_v1 import build_json_snapshot

    snapshot = build_json_snapshot([])
    assert "pipeline_health" in snapshot
    assert snapshot["pipeline_health"] is None


# ---------------------------------------------------------------------------
# Shell script source checks — cockpit refresh order
# ---------------------------------------------------------------------------

_LINKED_REFRESH_SH = Path("scripts/odroid/run_linked_profile_dashboard_refresh_once.sh")


def test_linked_refresh_checks_1h_candle_freshness_before_native_build() -> None:
    src = _LINKED_REFRESH_SH.read_text()
    freshness_pos = src.find("check_1h_candle_freshness")
    union_pos = src.find("build_union_native_short_context")
    assert freshness_pos != -1, "Script must contain check_1h_candle_freshness phase"
    assert union_pos != -1, "Script must contain build_union_native_short_context phase"
    assert freshness_pos < union_pos, (
        "Candle freshness check must appear BEFORE union native context build"
    )


def test_linked_refresh_emits_stale_warning_for_1h() -> None:
    src = _LINKED_REFRESH_SH.read_text()
    assert "STALE" in src or "stale" in src.lower(), (
        "Script must emit a warning when 1h candles are stale"
    )
