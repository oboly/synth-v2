from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from src.market_data import canonical_fib_zone_map_v1 as subject
from src.market_data import run_canonical_fib_zone_map_v1 as runner
from src.market_data.canonical_fib_zone_map_v1 import (
    CanonicalFibMapError,
    build_publication,
    build_row,
)
from src.market_data.fib_navigation_map_v1 import (
    DIRECTION_BEARISH,
    DIRECTION_BULLISH,
    MAP_STATE_EMERGENCY_REBUILT,
    MAP_STATE_NO_DATA,
    MAP_STATE_STALE,
    FibNavCandle,
)
from src.reporting import run_breath_fibo_strategy_static_dashboard_v1 as dashboard
from src.reporting.run_breath_fibo_strategy_static_dashboard_v1 import (
    PriceSnapshot,
    atomic_text_write,
    build_row as build_dashboard_row,
    fmt_price,
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


def bearish_candles(*, latest: datetime = NOW - timedelta(minutes=30)) -> list[FibNavCandle]:
    lows = (
        "110", "112", "115", "120", "116", "110", "104", "98", "100", "96", "94", "92"
    )
    highs = (
        "115", "117", "120", "125", "122", "116", "110", "104", "108", "102", "100", "98"
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


def range_candles(*, latest: datetime = NOW - timedelta(minutes=30)) -> list[FibNavCandle]:
    start = latest - timedelta(hours=44)
    return [
        FibNavCandle(
            close_ts_utc=start + timedelta(hours=4 * index),
            open_price=Decimal("100"),
            high_price=Decimal("101") if index % 2 == 0 else Decimal("102"),
            low_price=Decimal("99") if index % 2 == 0 else Decimal("98"),
            close_price=Decimal("100"),
            volume=Decimal("1000"),
        )
        for index in range(12)
    ]


def trend_row(
    source_candles: list[FibNavCandle],
    *,
    state: str = "UP",
) -> dict[str, object]:
    values = {
        "UP": (Decimal("0.03"), Decimal("0.04"), Decimal("0.02")),
        "DOWN": (Decimal("-0.03"), Decimal("-0.04"), Decimal("-0.02")),
        "RANGE": (Decimal("0.001"), Decimal("0"), Decimal("0.001")),
    }[state]
    return {
        "close_ts_utc": source_candles[-1].close_ts_utc,
        "price_vs_ema20": values[0],
        "price_vs_ema50": values[1],
        "ema_spread_pct": values[2],
    }


def test_publication_is_deterministic_and_uses_canonical_builder() -> None:
    source_candles = candles()
    trends = {
        "BTC": trend_row(source_candles),
        "ETH": trend_row(source_candles),
    }
    first = build_publication(
        venue="bitvavo",
        quote_currency="EUR",
        interval_code="4h",
        symbols=["ETH", "BTC", "ETH"],
        candles_by_symbol={"BTC": source_candles, "ETH": source_candles},
        trend_rows_by_symbol=trends,
        now_utc=NOW,
    )
    second = build_publication(
        venue="bitvavo",
        quote_currency="EUR",
        interval_code="4h",
        symbols=["BTC", "ETH"],
        candles_by_symbol={"ETH": source_candles, "BTC": source_candles},
        trend_rows_by_symbol=trends,
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
    stale_candles = candles(latest=NOW - timedelta(hours=12))
    stale = build_row(
        venue="bitvavo",
        symbol="ETH",
        interval_code="4h",
        candles=stale_candles,
        trend_row=trend_row(stale_candles),
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
        "current_leg": "UP",
    }
    source_candles = candles()
    row = build_row(
        venue="bitvavo",
        symbol="BTC",
        interval_code="4h",
        candles=source_candles,
        now_utc=NOW,
        trend_row=trend_row(source_candles),
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
        candles=(source_candles := candles()),
        now_utc=NOW,
        trend_row=trend_row(source_candles),
    )
    assert row["map_status"] == "FRESH"
    assert row["target_t1"] is None
    with pytest.raises(CanonicalFibMapError):
        subject.validate_rows((row,))


def test_dashboard_renders_persisted_levels_and_freshness_without_recalculation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dashboard, "now_utc", lambda: NOW)
    map_row = build_row(
        venue="bitvavo",
        symbol="BTC",
        interval_code="4h",
        candles=(source_candles := candles()),
        now_utc=NOW,
        trend_row=trend_row(source_candles),
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
    assert rendered.invalidation_zone.startswith("floor=")
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


def test_dashboard_fixture_becomes_delayed_at_explicit_10_3_hour_age(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    map_row = build_row(
        venue="bitvavo",
        symbol="BTC",
        interval_code="4h",
        candles=(source_candles := candles()),
        now_utc=NOW,
        trend_row=trend_row(source_candles),
    )
    source_ts = source_candles[-1].close_ts_utc
    evaluation_time = source_ts + timedelta(hours=10, minutes=18)
    monkeypatch.setattr(dashboard, "now_utc", lambda: evaluation_time)

    rendered = build_dashboard_row(
        "BTC",
        interval="4h",
        price_row=PriceSnapshot(
            symbol="BTC",
            current_price=Decimal("117"),
            latest_candle_ts_utc=source_ts,
            source="obs_market_candle",
        ),
        fib_row=map_row,
        regime_row=None,
    )

    assert rendered.candle_freshness_state == "DELAYED"
    assert "age=10.3h/DELAYED" in rendered.fibo_map_state


@pytest.mark.parametrize(
    ("age", "expected"),
    (
        (timedelta(hours=6), "FRESH"),
        (timedelta(hours=6, microseconds=1), "DELAYED"),
        (timedelta(hours=16), "DELAYED"),
        (timedelta(hours=16, microseconds=1), "STALE"),
    ),
)
def test_dashboard_freshness_boundaries_are_deterministic(
    monkeypatch: pytest.MonkeyPatch,
    age: timedelta,
    expected: str,
) -> None:
    source_ts = NOW
    monkeypatch.setattr(dashboard, "now_utc", lambda: source_ts + age)

    assert dashboard.freshness_state("4h", source_ts) == expected


def test_dashboard_freshness_normalizes_timezone_aware_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_utc = NOW
    source_plus_two = source_utc.astimezone(timezone(timedelta(hours=2)))
    monkeypatch.setattr(
        dashboard,
        "now_utc",
        lambda: source_utc + timedelta(hours=5),
    )

    assert dashboard.freshness_state("4h", source_utc) == "FRESH"
    assert dashboard.freshness_state("4h", source_plus_two) == "FRESH"


@pytest.mark.parametrize("year", (2026, 2099))
def test_recent_fixture_is_independent_of_process_calendar_date(
    monkeypatch: pytest.MonkeyPatch,
    year: int,
) -> None:
    evaluation_time = datetime(year, 7, 30, 12, 30, tzinfo=UTC)
    source_ts = evaluation_time - timedelta(minutes=30)
    monkeypatch.setattr(dashboard, "now_utc", lambda: evaluation_time)

    assert dashboard.freshness_state("4h", source_ts) == "FRESH"


def test_dashboard_clock_defaults_to_real_current_utc() -> None:
    before = datetime.now(UTC)
    observed = dashboard.now_utc()
    after = datetime.now(UTC)

    assert before <= observed <= after
    assert observed.tzinfo is UTC


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
    chain_source = Path("scripts/run_chain_4h.sh").read_text(encoding="utf-8")
    assert chain_source.index("src.features.run_feat_candle") < chain_source.index(
        "src.market_data.run_canonical_fib_zone_map_v1"
    )


def test_failed_generation_rolls_back_without_replacing_prior_cohort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Connection:
        def __init__(self) -> None:
            self.rollbacks = 0
            self.commits = 0
            self.closed = False

        def rollback(self) -> None:
            self.rollbacks += 1

        def commit(self) -> None:
            self.commits += 1

        def close(self) -> None:
            self.closed = True

    connection = Connection()
    monkeypatch.setattr(runner, "get_connection", lambda: connection)
    monkeypatch.setattr(runner, "fetch_tracked_symbols", lambda *args, **kwargs: ["BTC"])
    monkeypatch.setattr(runner, "fetch_latest_production_rows", lambda *args, **kwargs: {})
    monkeypatch.setattr(runner, "fetch_recent_candles", lambda *args, **kwargs: {"BTC": candles()})
    monkeypatch.setattr(
        runner,
        "fetch_latest_trend_rows",
        lambda *args, **kwargs: {"BTC": trend_row(candles())},
    )
    monkeypatch.setattr(
        runner,
        "build_publication",
        lambda **kwargs: (_ for _ in ()).throw(CanonicalFibMapError("malformed cohort")),
    )
    publish_called = False

    def unexpected_publish(*args, **kwargs):
        nonlocal publish_called
        publish_called = True

    monkeypatch.setattr(runner, "publish", unexpected_publish)
    exit_code = runner.main(
        [
            "--lock-file",
            str(tmp_path / "writer.lock"),
            "--output",
            "summary",
        ]
    )
    assert exit_code == 1
    assert connection.rollbacks >= 2
    assert connection.commits == 0
    assert connection.closed
    assert not publish_called


def test_bullish_structure_builds_bullish_map_and_matching_leg() -> None:
    source_candles = candles()
    row = build_row(
        venue="bitvavo",
        symbol="BTC",
        interval_code="4h",
        candles=source_candles,
        trend_row=trend_row(source_candles, state="UP"),
        now_utc=NOW,
    )
    assert row["current_leg"] == "UP"
    assert row["provenance_payload"]["map_direction"] == DIRECTION_BULLISH
    assert row["invalidation_level"] == row["anchor_low_price"]
    assert row["anchor_high_price"] < row["target_t1"] < row["target_t2"]


def test_bearish_structure_builds_bearish_map_with_ordered_targets_and_invalidation() -> None:
    source_candles = bearish_candles()
    row = build_row(
        venue="bitvavo",
        symbol="ETH",
        interval_code="4h",
        candles=source_candles,
        trend_row=trend_row(source_candles, state="DOWN"),
        now_utc=NOW,
    )
    assert row["current_leg"] == "DOWN"
    assert row["provenance_payload"]["map_direction"] == DIRECTION_BEARISH
    assert row["invalidation_level"] == row["anchor_high_price"]
    assert (
        row["target_extension"]
        < row["target_t2"]
        < row["target_t1"]
        < row["anchor_low_price"]
    )
    assert row["anchor_high_ts_utc"] < row["anchor_low_ts_utc"]


def test_range_structure_is_persisted_honestly_without_directional_geometry() -> None:
    source_candles = range_candles()
    row = build_row(
        venue="bitvavo",
        symbol="XRP",
        interval_code="4h",
        candles=source_candles,
        trend_row=trend_row(source_candles, state="RANGE"),
        now_utc=NOW,
    )
    assert row["current_leg"] == "RANGE"
    assert row["map_status"] == MAP_STATE_NO_DATA
    assert row["target_t1"] is None
    assert row["invalidation_level"] is None
    assert row["provenance_payload"]["map_direction"] is None
    assert row["provenance_payload"]["reason"] == "RANGE_STRUCTURE_HAS_NO_DIRECTIONAL_FIB_MAP"


def test_dashboard_selects_targets_and_labels_by_persisted_direction() -> None:
    source_candles = bearish_candles()
    map_row = build_row(
        venue="bitvavo",
        symbol="ETH",
        interval_code="4h",
        candles=source_candles,
        trend_row=trend_row(source_candles, state="DOWN"),
        now_utc=NOW,
    )
    current = (map_row["target_t1"] + map_row["target_t2"]) / Decimal("2")
    rendered = build_dashboard_row(
        "ETH",
        interval="4h",
        price_row=PriceSnapshot(
            symbol="ETH",
            current_price=current,
            latest_candle_ts_utc=source_candles[-1].close_ts_utc,
            source="obs_market_candle",
        ),
        fib_row=map_row,
        regime_row=None,
    )
    assert rendered.current_leg == "DOWN"
    assert rendered.nearest_target_or_t1 == fmt_price(map_row["target_t2"])
    assert rendered.nearest_support_or_entry_zone.startswith("resistance/retracement=")
    assert rendered.invalidation_zone.startswith("ceiling=")
    assert rendered.distance_to_target_pct < 0


def test_dashboard_degrades_unknown_leg_without_reusing_directional_values() -> None:
    source_candles = range_candles()
    map_row = build_row(
        venue="bitvavo",
        symbol="XRP",
        interval_code="4h",
        candles=source_candles,
        trend_row=trend_row(source_candles, state="RANGE"),
        now_utc=NOW,
    )
    rendered = build_dashboard_row(
        "XRP",
        interval="4h",
        price_row=PriceSnapshot(
            symbol="XRP",
            current_price=source_candles[-1].close_price,
            latest_candle_ts_utc=source_candles[-1].close_ts_utc,
            source="obs_market_candle",
        ),
        fib_row=map_row,
        regime_row=None,
    )
    assert rendered.current_leg == "RANGE"
    assert rendered.nearest_target_or_t1 == "—"
    assert rendered.nearest_support_or_entry_zone == "UNKNOWN (non-directional map)"
    assert rendered.invalidation_zone == "UNKNOWN"
    assert rendered.strategy_candidate_state == "MAP_UNAVAILABLE"
