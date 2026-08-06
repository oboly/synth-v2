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


def test_missing_or_misaligned_trend_feature_reason_when_feat_candle_is_stale() -> None:
    """Regression for the causal-audit finding behind PR #190/#191: this
    reason fires when feat_candle's newest row for a symbol is not exactly
    aligned to obs_market_candle's newest row -- e.g. the off-by-one bug
    where run_feat_candle's --end was passed the closed candle's own
    identity timestamp (excluded by the half-open contract) instead of one
    interval past it. It is unrelated to structure_state, which this writer
    never queries."""
    source_candles = candles()
    stale_trend_row = trend_row(source_candles)
    stale_trend_row["close_ts_utc"] = source_candles[-2].close_ts_utc
    row = build_row(
        venue="bitvavo",
        symbol="BTC",
        interval_code="4h",
        candles=source_candles,
        trend_row=stale_trend_row,
        now_utc=NOW,
    )
    assert row["map_status"] == MAP_STATE_NO_DATA
    assert row["provenance_payload"]["reason"] == "MISSING_OR_MISALIGNED_TREND_FEATURE"


def test_aligned_feat_candle_and_obs_market_candle_timestamps_produce_available_map() -> None:
    """The corrected --end contract must make feat_candle's newest row for a
    symbol exactly equal to obs_market_candle's newest row -- proving the
    alignment canonical_fib_zone_map_v1 actually requires, with no
    structure_state involvement."""
    source_candles = candles()
    aligned_trend_row = trend_row(source_candles)
    assert aligned_trend_row["close_ts_utc"] == source_candles[-1].close_ts_utc
    row = build_row(
        venue="bitvavo",
        symbol="BTC",
        interval_code="4h",
        candles=source_candles,
        trend_row=aligned_trend_row,
        now_utc=NOW,
    )
    assert row["provenance_payload"].get("reason") != "MISSING_OR_MISALIGNED_TREND_FEATURE"
    assert row["map_status"] in subject.AVAILABLE_STATES


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


# ---------------------------------------------------------------------------
# Child-row identity for publication cohorts.
#
# Regression cover for the 2026-08-05T20:00Z publication failure: exactly one
# tracked symbol (NOT) had no 20:00 4h bar while it did have the 16:00 bar, so
# its child row carried asof_ts_utc=16:00 inside the 20:00 cohort and collided
# with its own row from the already-published 16:00 cohort under the old
# unique key (venue, symbol, interval_code, asof_ts_utc, map_version).
#
# Grain after db/migrations/20260806_canonical_fib_zone_map_publication_identity_v1.sql:
# one row per (publication_id, symbol).
# ---------------------------------------------------------------------------

IDENTITY_MIGRATION = Path(
    "db/migrations/20260806_canonical_fib_zone_map_publication_identity_v1.sql"
)
T_1600 = datetime(2026, 8, 5, 16, 0, tzinfo=UTC)
T_2000 = datetime(2026, 8, 5, 20, 0, tzinfo=UTC)
DB_1600 = T_1600.replace(tzinfo=None)
DB_2000 = T_2000.replace(tzinfo=None)


class _IdentityIntegrityError(Exception):
    """Stand-in for the MariaDB 1062 duplicate-key error."""


class _IdentityCursor:
    """Fake cursor enforcing the migrated uq_canonical_fib_zone_map_v1."""

    def __init__(self, script: dict) -> None:
        self._script = script
        self._result = None

    def __enter__(self) -> "_IdentityCursor":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def execute(self, sql: str, params=()) -> None:
        stripped = sql.strip()
        if stripped.startswith("SELECT") and "canonical_fib_zone_map_publication_v1" in sql:
            venue, quote, interval, asof = params[0], params[1], params[2], params[3]
            self._result = next(
                (
                    row
                    for row in self._script["publications"].values()
                    if row["venue"] == venue
                    and row["quote_currency"] == quote
                    and row["interval_code"] == interval
                    and row["asof_ts_utc"] == asof
                ),
                None,
            )
        elif stripped.startswith("INSERT INTO canonical_fib_zone_map_publication_v1"):
            self._script["publications"][params[0]] = {
                "publication_id": params[0],
                "venue": params[1],
                "quote_currency": params[2],
                "interval_code": params[3],
                "asof_ts_utc": params[4],
                "map_version": params[5],
                "content_digest": params[6],
                "row_count": params[7],
                "available_count": params[8],
            }
        elif stripped.startswith("INSERT INTO canonical_fib_zone_map_v1"):
            row = dict(params)
            key = (
                row["venue"],
                row["symbol"],
                row["interval_code"],
                row["publication_id"],
                row["map_version"],
            )
            if key in self._script["map_keys"]:
                raise _IdentityIntegrityError(
                    "Duplicate entry for key 'uq_canonical_fib_zone_map_v1'"
                )
            self._script["map_keys"].add(key)
            self._script["map_rows"].append(row)
        else:
            raise AssertionError(f"unexpected SQL in fake cursor: {sql[:120]}")

    def fetchone(self):
        return self._result

    def fetchall(self):
        return self._result or []


class _IdentityConn:
    def __init__(self) -> None:
        self.script: dict = {"publications": {}, "map_rows": [], "map_keys": set()}

    def cursor(self):
        return _IdentityCursor(self.script)

    def rows_for(self, symbol: str) -> list[dict]:
        return [row for row in self.script["map_rows"] if row["symbol"] == symbol]

    def latest_publication_rows(self) -> list[dict]:
        """Mirrors canonical_fib_zone_map_latest_v1: pick the cohort with the
        greatest publication asof, then return that cohort's rows."""
        latest = max(self.script["publications"].values(), key=lambda p: p["asof_ts_utc"])
        return [
            row
            for row in self.script["map_rows"]
            if row["publication_id"] == latest["publication_id"]
        ]


def _identity_authorization():
    from src.operations.writer_capability_authorization_v1 import (
        ExecutionMode,
        _mint_authorization,
    )

    return _mint_authorization(
        capability_id="native_short_4h_chain",
        execution_mode=ExecutionMode.PRODUCTION,
        validated_host="test-host",
        validated_commit="0" * 40,
        authorization_or_permit_id="test-authorization",
    )


def _cohort(symbol_latest: dict[str, datetime], *, now_utc: datetime):
    """Build a publication where each symbol's latest bar is given explicitly.

    NOT is given a 16:00 bar while other symbols get 20:00, reproducing the
    production shape (one tracked symbol missing the 20:00 bar).
    """
    by_symbol = {sym: candles(latest=latest) for sym, latest in symbol_latest.items()}
    return build_publication(
        venue="bitvavo",
        quote_currency="EUR",
        interval_code="4h",
        symbols=list(by_symbol),
        candles_by_symbol=by_symbol,
        trend_rows_by_symbol={s: trend_row(c) for s, c in by_symbol.items()},
        now_utc=now_utc,
    )


def test_identity_migration_keys_child_rows_on_publication() -> None:
    sql = IDENTITY_MIGRATION.read_text(encoding="utf-8")
    up = sql.split("-- UP", 1)[1]
    assert "DROP INDEX uq_canonical_fib_zone_map_v1" in up
    assert "venue, symbol, interval_code, publication_id, map_version" in up
    # The executable part is exactly one statement against exactly one table.
    executable = "\n".join(
        line for line in sql.splitlines() if not line.strip().startswith("--")
    ).strip()
    assert executable.count(";") == 1
    assert executable.startswith("ALTER TABLE canonical_fib_zone_map_v1")
    # The DOWN/rollback path must remain a commented reference, never executed:
    # the old asof_ts_utc-based key must not appear in the executable SQL.
    assert "asof_ts_utc" not in executable


def test_latest_view_selects_by_publication_asof_not_child_row_asof() -> None:
    """The shipped latest view must resolve "current" through the publication
    table, which is what makes a lagging child asof_ts_utc safe."""
    view_sql = Path(
        "db/migrations/20260730_canonical_fib_zone_map_production_v1.sql"
    ).read_text(encoding="utf-8")
    latest_block = view_sql.split("CREATE OR REPLACE VIEW canonical_fib_zone_map_latest_v1", 1)[1]
    assert "MAX(asof_ts_utc) AS max_asof_ts_utc" in latest_block
    assert "FROM canonical_fib_zone_map_publication_v1" in latest_block
    assert "latest.max_asof_ts_utc = p.asof_ts_utc" in latest_block


def test_1600_publication_contains_not_at_source_1600() -> None:
    build = _cohort({"NOT": T_1600}, now_utc=T_1600 + timedelta(minutes=5))
    assert build.asof_ts_utc == T_1600
    conn = _IdentityConn()
    assert subject.publish(conn, build, authorization=_identity_authorization()).status == "PUBLISHED"
    [row] = conn.rows_for("NOT")
    assert row["asof_ts_utc"] == DB_1600
    assert row["input_latest_candle_ts_utc"] == DB_1600


def test_2000_publication_may_contain_not_still_sourced_from_1600() -> None:
    build = _cohort({"NOT": T_1600, "BTC": T_2000}, now_utc=T_2000 + timedelta(minutes=5))
    assert build.asof_ts_utc == T_2000, "cohort asof is the max across symbols"
    conn = _IdentityConn()
    assert subject.publish(conn, build, authorization=_identity_authorization()).status == "PUBLISHED"
    [not_row] = conn.rows_for("NOT")
    assert not_row["asof_ts_utc"] == DB_1600
    assert not_row["input_latest_candle_ts_utc"] == DB_1600
    [btc_row] = conn.rows_for("BTC")
    assert btc_row["asof_ts_utc"] == DB_2000


def test_1600_and_2000_cohorts_coexist_without_collision() -> None:
    conn = _IdentityConn()
    first = _cohort({"NOT": T_1600}, now_utc=T_1600 + timedelta(minutes=5))
    subject.publish(conn, first, authorization=_identity_authorization())
    second = _cohort({"NOT": T_1600, "BTC": T_2000}, now_utc=T_2000 + timedelta(minutes=5))
    # This is the exact production case that raised IntegrityError 1062.
    assert subject.publish(conn, second, authorization=_identity_authorization()).status == "PUBLISHED"

    not_rows = conn.rows_for("NOT")
    assert len(not_rows) == 2
    assert {row["asof_ts_utc"] for row in not_rows} == {DB_1600}
    assert {row["publication_id"] for row in not_rows} == {
        f"fibnav-{first.content_digest[:32]}",
        f"fibnav-{second.content_digest[:32]}",
    }


def test_each_publication_has_exactly_one_row_per_symbol() -> None:
    conn = _IdentityConn()
    build = _cohort({"NOT": T_1600, "BTC": T_2000}, now_utc=T_2000 + timedelta(minutes=5))
    subject.publish(conn, build, authorization=_identity_authorization())
    publication_id = f"fibnav-{build.content_digest[:32]}"
    seen = [row["symbol"] for row in conn.script["map_rows"] if row["publication_id"] == publication_id]
    assert sorted(seen) == ["BTC", "NOT"]
    assert len(seen) == len(set(seen))


def test_duplicate_symbol_within_same_publication_still_fails() -> None:
    build = _cohort({"NOT": T_1600}, now_utc=T_1600 + timedelta(minutes=5))
    doubled = subject.PublicationBuild(
        venue=build.venue,
        quote_currency=build.quote_currency,
        interval_code=build.interval_code,
        asof_ts_utc=build.asof_ts_utc,
        rows=build.rows + build.rows,
        content_digest=build.content_digest,
        available_count=build.available_count,
    )
    conn = _IdentityConn()
    with conn.cursor() as cur:
        with pytest.raises(_IdentityIntegrityError, match="uq_canonical_fib_zone_map_v1"):
            subject.insert_publication_cohort(cur, doubled, "fibnav-duplicate-symbol-test")


def test_latest_consumers_select_the_2000_publication_and_keep_1600_freshness() -> None:
    conn = _IdentityConn()
    subject.publish(
        conn,
        _cohort({"NOT": T_1600}, now_utc=T_1600 + timedelta(minutes=5)),
        authorization=_identity_authorization(),
    )
    second = _cohort({"NOT": T_1600, "BTC": T_2000}, now_utc=T_2000 + timedelta(minutes=5))
    subject.publish(conn, second, authorization=_identity_authorization())

    current = conn.latest_publication_rows()
    assert {row["publication_id"] for row in current} == {f"fibnav-{second.content_digest[:32]}"}
    assert sorted(row["symbol"] for row in current) == ["BTC", "NOT"]
    # Source freshness for NOT still honestly reports 16:00 in the 20:00 cohort.
    not_row = next(row for row in current if row["symbol"] == "NOT")
    assert not_row["input_latest_candle_ts_utc"] == DB_1600
    assert not_row["source_freshness_state"] in {"FRESH", "STALE", "UNAVAILABLE"}


def test_same_publication_retry_remains_idempotent() -> None:
    conn = _IdentityConn()
    build = _cohort({"NOT": T_1600}, now_utc=T_1600 + timedelta(minutes=5))
    first = subject.publish(conn, build, authorization=_identity_authorization())
    second = subject.publish(conn, build, authorization=_identity_authorization())
    assert (first.status, second.status) == ("PUBLISHED", "UNCHANGED")
    assert second.publication_id == first.publication_id
    assert len(conn.rows_for("NOT")) == 1


def test_identity_change_touches_no_account_decision_planner_or_executor_layer() -> None:
    forbidden = (
        "src.account",
        "src.decision_gate",
        "src.execution_planner",
        "src.executor",
        "src.broker",
    )
    producer_source = Path("src/market_data/canonical_fib_zone_map_v1.py").read_text(
        encoding="utf-8"
    )
    migration_sql = IDENTITY_MIGRATION.read_text(encoding="utf-8")
    assert all(token not in producer_source for token in forbidden)
    # The migration touches exactly one market-only table and nothing else.
    assert migration_sql.split("-- UP", 1)[1].count("ALTER TABLE") == 1
    assert "canonical_fib_zone_map_v1" in migration_sql.split("-- UP", 1)[1]
    for table in ("account", "decision", "execution_plan", "order", "position", "broker"):
        assert table not in migration_sql.split("-- UP", 1)[1]
    assert subject.SAFETY_MARKERS["broker_writes"] == 0
    assert subject.SAFETY_MARKERS["order_submission"] == 0
    assert subject.SAFETY_MARKERS["decision_gate"] == "none"
    assert subject.SAFETY_MARKERS["execution_planner"] == "none"
    assert subject.SAFETY_MARKERS["executor"] == "none"


def test_asof_and_input_latest_are_equal_with_candles_but_diverge_without() -> None:
    """`asof_ts_utc` and `input_latest_candle_ts_utc` look redundant because
    they match for every row that has candles -- but they carry different
    signals and neither may be dropped.

    A symbol with no candles at all gets `asof_ts_utc` back-filled from the
    cohort asof (keeping it NOT NULL and indexable) while
    `input_latest_candle_ts_utc` stays NULL, which is the only unambiguous
    "no source data" marker.
    """
    have_candles = candles(latest=T_1600)
    build = build_publication(
        venue="bitvavo",
        quote_currency="EUR",
        interval_code="4h",
        symbols=["NOT", "GHOST"],
        candles_by_symbol={"NOT": have_candles},
        trend_rows_by_symbol={"NOT": trend_row(have_candles)},
        now_utc=T_1600 + timedelta(minutes=5),
    )
    assert build.asof_ts_utc == T_1600

    # Pre-insert: the no-data row has no timestamp of its own at all.
    ghost_built = next(row for row in build.rows if row["symbol"] == "GHOST")
    assert ghost_built["map_status"] == MAP_STATE_NO_DATA
    assert ghost_built["provenance_payload"]["reason"] == "MISSING_CANDLES"
    assert ghost_built["asof_ts_utc"] is None
    assert ghost_built["input_latest_candle_ts_utc"] is None

    conn = _IdentityConn()
    subject.publish(conn, build, authorization=_identity_authorization())

    # Post-insert: asof_ts_utc is back-filled from the cohort, input_latest is not.
    [ghost] = conn.rows_for("GHOST")
    assert ghost["asof_ts_utc"] == DB_1600, "must stay NOT NULL for the secondary indexes"
    assert ghost["input_latest_candle_ts_utc"] is None, "NULL is the no-source-data signal"

    # A row that does have candles keeps them equal.
    [not_row] = conn.rows_for("NOT")
    assert not_row["asof_ts_utc"] == not_row["input_latest_candle_ts_utc"] == DB_1600

    # Pin the fallback itself so it cannot be "simplified" away.
    producer_source = Path("src/market_data/canonical_fib_zone_map_v1.py").read_text(
        encoding="utf-8"
    )
    assert 'row["asof_ts_utc"] or build.asof_ts_utc' in producer_source
