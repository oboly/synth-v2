from __future__ import annotations

import json
import tempfile
import ast
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from src.market_data.native_short_fib_context_v1 import (
    STATUS_AVAILABLE,
    STATUS_INSUFFICIENT_1H,
    STATUS_INSUFFICIENT_4H,
    STATUS_STALE_OR_INVALID,
    Candle,
    build_native_short_context_row,
    load_native_short_context_rows,
    write_context_rows,
)
import src.market_data.run_native_short_fib_context_v1 as native_runner


def _candles(
    prices: list[str],
    *,
    start: datetime,
    step_hours: int,
    wiggle: str = "0.01",
) -> list[Candle]:
    out: list[Candle] = []
    delta = timedelta(hours=step_hours)
    width = Decimal(wiggle)
    for index, price_text in enumerate(prices):
        price = Decimal(price_text)
        out.append(
            Candle(
                close_ts_utc=start + delta * index,
                open_price=price,
                high_price=price + width,
                low_price=price - width,
                close_price=price,
            )
        )
    return out


def test_valid_4h_with_aligned_1h_is_native_short_available() -> None:
    now = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    primary = _candles(
        ["1.05", "1.00", "0.95", "1.00", "1.05", "1.15", "1.10", "1.08", "1.12", "1.14"],
        start=datetime(2026, 6, 3, 0, 0, tzinfo=UTC),
        step_hours=4,
    )
    support = _candles(
        ["1.10"] * 60,
        start=datetime(2026, 6, 3, 0, 0, tzinfo=UTC),
        step_hours=1,
        wiggle="0.005",
    )
    row = build_native_short_context_row(
        symbol="WLD",
        venue="bitvavo",
        primary_candles=primary,
        support_candles=support,
        now_utc=now,
    )
    assert row.context_status == STATUS_AVAILABLE
    assert row.primary_interval == "4h"
    assert row.supporting_interval == "1h"
    assert row.supporting_1h_state == "ALIGNED_WITH_4H"
    assert row.anchor_low_price is not None
    assert row.anchor_high_price is not None
    assert row.primary_4h_lifecycle_state in {"BREAKOUT_CONFIRMED", "TARGET_ACTIVE", "TARGET_REACHED_OR_PASSED"}


def test_valid_4h_with_conflicting_1h_keeps_4h_authoritative() -> None:
    now = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    primary = _candles(
        ["1.05", "1.00", "0.95", "1.00", "1.05", "1.15", "1.10", "1.08", "1.12", "1.14"],
        start=datetime(2026, 6, 3, 0, 0, tzinfo=UTC),
        step_hours=4,
    )
    support = _candles(
        ["0.92"] * 60,
        start=datetime(2026, 6, 3, 0, 0, tzinfo=UTC),
        step_hours=1,
        wiggle="0.005",
    )
    row = build_native_short_context_row(
        symbol="WLD",
        venue="bitvavo",
        primary_candles=primary,
        support_candles=support,
        now_utc=now,
    )
    assert row.context_status == STATUS_AVAILABLE
    assert row.supporting_1h_state == "CONFLICT_WITH_4H"
    assert row.breakout_gate_price == row.anchor_high_price


def test_valid_4h_with_missing_1h_is_not_native_available() -> None:
    now = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    primary = _candles(
        ["1.05", "1.00", "0.95", "1.00", "1.05", "1.15", "1.10", "1.08", "1.12", "1.14"],
        start=datetime(2026, 6, 3, 0, 0, tzinfo=UTC),
        step_hours=4,
    )
    row = build_native_short_context_row(
        symbol="WLD",
        venue="bitvavo",
        primary_candles=primary,
        support_candles=[],
        now_utc=now,
    )
    assert row.context_status == STATUS_INSUFFICIENT_1H
    assert row.supporting_1h_state == "UNKNOWN"


def test_completed_4h_map_remains_native_and_history_aware() -> None:
    now = datetime(2026, 6, 6, 12, 0, tzinfo=UTC)
    primary = _candles(
        ["1.05", "1.00", "0.95", "1.00", "1.05", "1.15", "1.10", "1.08", "1.32", "1.45"],
        start=datetime(2026, 6, 4, 0, 0, tzinfo=UTC),
        step_hours=4,
    )
    support = _candles(
        ["1.28"] * 60,
        start=datetime(2026, 6, 4, 0, 0, tzinfo=UTC),
        step_hours=1,
        wiggle="0.005",
    )
    row = build_native_short_context_row(
        symbol="WLD",
        venue="bitvavo",
        primary_candles=primary,
        support_candles=support,
        now_utc=now,
    )
    assert row.context_status == STATUS_AVAILABLE
    assert row.primary_4h_lifecycle_state == "MAP_COMPLETED"
    assert row.active_target_levels == ()
    assert row.previous_target_levels


def test_stale_primary_map_fails_closed() -> None:
    now = datetime(2026, 6, 8, 12, 0, tzinfo=UTC)
    primary = _candles(
        ["1.05", "1.00", "0.95", "1.00", "1.05", "1.15", "1.10", "1.08", "1.12", "1.14"],
        start=datetime(2026, 6, 3, 0, 0, tzinfo=UTC),
        step_hours=4,
    )
    support = _candles(
        ["1.10"] * 60,
        start=datetime(2026, 6, 3, 0, 0, tzinfo=UTC),
        step_hours=1,
        wiggle="0.005",
    )
    row = build_native_short_context_row(
        symbol="WLD",
        venue="bitvavo",
        primary_candles=primary,
        support_candles=support,
        now_utc=now,
    )
    assert row.context_status == STATUS_STALE_OR_INVALID


def test_insufficient_4h_history_fails_closed() -> None:
    now = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    primary = _candles(
        ["1.05", "1.00", "0.95", "1.00", "1.05"],
        start=datetime(2026, 6, 3, 0, 0, tzinfo=UTC),
        step_hours=4,
    )
    row = build_native_short_context_row(
        symbol="WLD",
        venue="bitvavo",
        primary_candles=primary,
        support_candles=[],
        now_utc=now,
    )
    assert row.context_status == STATUS_INSUFFICIENT_4H


def test_below_breakout_gate_state_is_available_without_forcing_support_conflict() -> None:
    now = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    primary = _candles(
        ["1.10", "1.00", "0.90", "1.00", "1.08", "1.20", "1.12", "1.09", "1.08", "1.07"],
        start=datetime(2026, 6, 3, 0, 0, tzinfo=UTC),
        step_hours=4,
    )
    support = _candles(
        ["1.05"] * 60,
        start=datetime(2026, 6, 3, 0, 0, tzinfo=UTC),
        step_hours=1,
        wiggle="0.005",
    )
    row = build_native_short_context_row(
        symbol="PLUME",
        venue="bitvavo",
        primary_candles=primary,
        support_candles=support,
        now_utc=now,
    )
    assert row.context_status == STATUS_AVAILABLE
    assert row.primary_4h_lifecycle_state == "BELOW_BREAKOUT_GATE"
    assert row.supporting_1h_state == "NEUTRAL_OR_NOT_CONFIRMING"


def test_pullback_retest_state_after_target_reach() -> None:
    now = datetime(2026, 6, 6, 12, 0, tzinfo=UTC)
    primary = _candles(
        ["1.05", "1.00", "0.95", "1.00", "1.05", "1.15", "1.10", "1.08", "1.26", "1.09"],
        start=datetime(2026, 6, 4, 0, 0, tzinfo=UTC),
        step_hours=4,
    )
    support = _candles(
        ["1.14"] * 60,
        start=datetime(2026, 6, 4, 0, 0, tzinfo=UTC),
        step_hours=1,
        wiggle="0.003",
    )
    row = build_native_short_context_row(
        symbol="WLD",
        venue="bitvavo",
        primary_candles=primary,
        support_candles=support,
        now_utc=now,
    )
    assert row.context_status == STATUS_AVAILABLE
    assert row.primary_4h_lifecycle_state in {"POST_BREAKOUT_PULLBACK", "TARGET_REACHED_OR_PASSED"}


def test_invalidation_is_not_reported_as_native_available() -> None:
    now = datetime(2026, 6, 6, 12, 0, tzinfo=UTC)
    primary = _candles(
        ["1.05", "1.00", "0.95", "1.00", "1.05", "1.15", "1.10", "1.08", "0.85", "0.82"],
        start=datetime(2026, 6, 4, 0, 0, tzinfo=UTC),
        step_hours=4,
    )
    support = _candles(
        ["0.84"] * 60,
        start=datetime(2026, 6, 4, 0, 0, tzinfo=UTC),
        step_hours=1,
        wiggle="0.003",
    )
    row = build_native_short_context_row(
        symbol="WLD",
        venue="bitvavo",
        primary_candles=primary,
        support_candles=support,
        now_utc=now,
    )
    assert row.context_status == STATUS_STALE_OR_INVALID
    assert row.primary_4h_lifecycle_state == "INVALIDATED"


def test_distribution_fixtures_are_non_degenerate() -> None:
    now = datetime(2026, 6, 6, 12, 0, tzinfo=UTC)
    fixtures = [
        (
            ["1.10", "1.00", "0.90", "1.00", "1.08", "1.20", "1.12", "1.09", "1.08", "1.07"],
            ["1.05"] * 60,
        ),
        (
            ["1.05", "1.00", "0.95", "1.00", "1.05", "1.15", "1.10", "1.08", "1.12", "1.14"],
            ["1.10"] * 60,
        ),
        (
            ["1.05", "1.00", "0.95", "1.00", "1.05", "1.15", "1.10", "1.08", "1.26", "1.09"],
            ["1.14"] * 60,
        ),
        (
            ["1.05", "1.00", "0.95", "1.00", "1.05", "1.15", "1.10", "1.08", "1.32", "1.45"],
            ["1.28"] * 60,
        ),
    ]
    lifecycle_states: set[str] = set()
    support_states: set[str] = set()
    for index, (primary_prices, support_prices) in enumerate(fixtures):
        row = build_native_short_context_row(
            symbol=f"S{index}",
            venue="bitvavo",
            primary_candles=_candles(primary_prices, start=datetime(2026, 6, 4, 0, 0, tzinfo=UTC), step_hours=4),
            support_candles=_candles(support_prices, start=datetime(2026, 6, 4, 0, 0, tzinfo=UTC), step_hours=1, wiggle="0.003"),
            now_utc=now,
        )
        lifecycle_states.add(row.primary_4h_lifecycle_state)
        support_states.add(row.supporting_1h_state)
    assert len(lifecycle_states) >= 3
    assert len(support_states) >= 2


def test_rows_round_trip_from_csv() -> None:
    now = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    primary = _candles(
        ["1.05", "1.00", "0.95", "1.00", "1.05", "1.15", "1.10", "1.08", "1.12", "1.14"],
        start=datetime(2026, 6, 3, 0, 0, tzinfo=UTC),
        step_hours=4,
    )
    support = _candles(
        ["1.10"] * 60,
        start=datetime(2026, 6, 3, 0, 0, tzinfo=UTC),
        step_hours=1,
        wiggle="0.005",
    )
    row = build_native_short_context_row(
        symbol="WLD",
        venue="bitvavo",
        primary_candles=primary,
        support_candles=support,
        now_utc=now,
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        paths = write_context_rows(rows=[row], output_dir=Path(tmpdir))
        loaded, missing = load_native_short_context_rows(paths["rows_csv"])
        assert missing is False
        assert loaded["WLD"].context_status == STATUS_AVAILABLE
        payload = json.loads(loaded["WLD"].to_csv_row()["active_target_levels_json"])
        assert isinstance(payload, list)


def test_native_short_bridge_has_no_broker_or_execution_imports() -> None:
    for path_text in (
        "src/market_data/native_short_fib_context_v1.py",
        "src/market_data/run_native_short_fib_context_v1.py",
    ):
        source = Path(path_text).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.add(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)
        for module_name in imported_modules:
            assert "bitvavo_client" not in module_name
            assert "decision_gate" not in module_name
            assert "execution_planner" not in module_name
            assert "executor" not in module_name


def test_explicit_symbol_scope_count_is_not_zero() -> None:
    symbols, markets = native_runner._select_symbols(
        explicit_symbols=["WLD", "PLUME"],
        account_profile="",
        venue="bitvavo",
    )
    assert symbols == ["PLUME", "WLD"]
    assert markets == []
