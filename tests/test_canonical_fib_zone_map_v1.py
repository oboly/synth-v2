from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from src.market_data import canonical_fib_zone_map_v1 as subject
from src.market_data.canonical_fib_zone_map_v1 import (
    CanonicalFibMapError,
    build_publication,
    build_row,
)
from src.market_data.fib_navigation_map_v1 import (
    MAP_STATE_EMERGENCY_REBUILT,
    MAP_STATE_NO_DATA,
    MAP_STATE_STALE,
    FibNavCandle,
)
from src.reporting.run_breath_fibo_strategy_static_dashboard_v1 import (
    PriceSnapshot,
    atomic_text_write,
    build_row as build_dashboard_row,
    render_html,
)


NOW = datetime(2026, 7, 30, 12, 30, tzinfo=UTC)


def candles(*, latest: datetime = NOW - timedelta(minutes=30)) -> list[FibNavCandle]:
    lows = (
        "100", "98", "95", "90", "94", "99", "104", "108", "106", "109", "111", "112"
    )
    highs = (
        "105", "103", "100", "95", "100", "106", "112", "120", "116", "119", "121", "122"
    )
    start = latest - timedelta(hours=4 * (len(lows) - 1))
    return [
        FibNavCandle(
            close_ts_utc=start + timedelta(hours=4 * index),
            open_price=(Decimal(low) + Decimal(high)) / 2,
            high_price=Decimal(high),
            low_price=Decimal(low),
            close_price=(Decimal(low) + Decimal(high)) / 2,
            volume=Decimal("1000"),
        )
        for index, (low, high) in enumerate(zip(lows, highs, strict=True))
    ]


def test_publication_is_deterministic_and_uses_canonical_builder() -> None:
    first = build_publication(
        venue="bitvavo",
        quote_currency="EUR",
        interval_code="4h",
        symbols=["ETH", "BTC", "ETH"],
        candles_by_symbol={"BTC": candles(), "ETH": candles()},
        now_utc=NOW,
    )
    second = build_publication(
        venue="bitvavo",
        quote_currency="EUR",
        interval_code="4h",
        symbols=["BTC", "ETH"],
        candles_by_symbol={"ETH": candles(), "BTC": candles()},
        now_utc=NOW,
    )
    assert [row["symbol"] for row in first.rows] == ["BTC", "ETH"]
    assert first.content_digest == second.content_digest
    assert all(
        row["provenance_payload"]["canonical_builder"] == "FibNavigationMap"
        for row in first.rows
    )


def test_missing_and_stale_candles_fail_honestly() -> None:
    missing = build_row(
        venue="bitvavo",
        symbol="BTC",
        interval_code="4h",
        candles=[],
        now_utc=NOW,
    )
    stale = build_row(
        venue="bitvavo",
        symbol="ETH",
        interval_code="4h",
        candles=candles(latest=NOW - timedelta(hours=12)),
        now_utc=NOW,
    )
    assert missing["map_status"] == MAP_STATE_NO_DATA
    assert missing["source_freshness_state"] == "UNAVAILABLE"
    assert stale["map_status"] == MAP_STATE_STALE
    assert stale["source_freshness_state"] == "STALE"
    assert stale["target_t1"] is None


def test_exhausted_prior_uses_existing_emergency_rebuild_path() -> None:
    prior = {
        "map_status": "MAP_COMPLETED",
        "anchor_low_price": Decimal("70"),
        "anchor_high_price": Decimal("100"),
        "target_extension": Decimal("110"),
        "input_latest_candle_ts_utc": NOW - timedelta(hours=8),
    }
    row = build_row(
        venue="bitvavo",
        symbol="BTC",
        interval_code="4h",
        candles=candles(),
        now_utc=NOW,
        prior_row=prior,
    )
    assert row["map_status"] == MAP_STATE_EMERGENCY_REBUILT
    assert row["provenance_payload"]["rebuild_trigger"] in {
        "MAP_EXHAUSTED",
        "ALL_TARGETS_PASSED",
        "PRICE_ABOVE_TOP_TARGET",
    }
    assert row["target_t1"] is not None


def test_malformed_builder_output_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    original = subject.build_fib_navigation_map

    def malformed(**kwargs):
        result = original(**kwargs)
        return result.__class__(
            **{
                **result.__dict__,
                "extension_levels": (),
                "map_state": "FRESH",
            }
        )

    monkeypatch.setattr(subject, "build_fib_navigation_map", malformed)
    row = build_row(
        venue="bitvavo",
        symbol="BTC",
        interval_code="4h",
        candles=candles(),
        now_utc=NOW,
    )
    assert row["map_status"] == "FRESH"
    assert row["target_t1"] is None
    with pytest.raises(CanonicalFibMapError):
        subject.validate_rows((row,))


def test_dashboard_renders_persisted_levels_and_freshness_without_recalculation(
    tmp_path: Path,
) -> None:
    map_row = build_row(
        venue="bitvavo",
        symbol="BTC",
        interval_code="4h",
        candles=candles(),
        now_utc=NOW,
    )
    rendered = build_dashboard_row(
        "BTC",
        interval="4h",
        price_row=PriceSnapshot(
            symbol="BTC",
            current_price=Decimal("117"),
            latest_candle_ts_utc=NOW - timedelta(minutes=30),
            source="obs_market_candle",
        ),
        fib_row=map_row,
        regime_row=None,
    )
    assert rendered.current_leg == "UP"
    assert rendered.nearest_support_or_entry_zone != "—"
    assert rendered.nearest_target_or_t1 != "—"
    assert rendered.invalidation_zone != "—"
    assert "/FRESH" in rendered.fibo_map_state
    assert "canonical_fib_zone_map_v1" in rendered.fibo_map_state
    assert "canonical_fib_zone_map_v1" in rendered.source_modules
    html = render_html([rendered], venue="bitvavo", quote="EUR", interval="4h")
    output = tmp_path / "fibo-map.html"
    atomic_text_write(html, output)
    published = output.read_text(encoding="utf-8")
    assert "BTC" in published
    assert rendered.nearest_support_or_entry_zone in published
    assert rendered.nearest_target_or_t1 in published
    assert rendered.invalidation_zone in published

    dashboard_source = Path(
        "src/reporting/run_breath_fibo_strategy_static_dashboard_v1.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(dashboard_source)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert "src.market_data.fib_navigation_map_v1" not in imported
    assert "paper_advice_observation" not in dashboard_source
    assert "fibo_target_map_rows_v1.csv" not in dashboard_source


def test_runtime_boundaries_and_atomic_lock_are_explicit() -> None:
    producer_source = Path(
        "src/market_data/canonical_fib_zone_map_v1.py"
    ).read_text(encoding="utf-8")
    runner_source = Path(
        "src/market_data/run_canonical_fib_zone_map_v1.py"
    ).read_text(encoding="utf-8")
    forbidden = (
        "src.account",
        "src.decision_gate",
        "src.execution_planner",
        "src.executor",
        "src.broker",
        "src.research",
    )
    assert all(token not in producer_source for token in forbidden)
    assert "LOCK_EX | fcntl.LOCK_NB" in runner_source
    assert "conn.rollback()" in runner_source
    assert "conn.commit()" in runner_source
    assert "paper_advice_fallback" in producer_source
