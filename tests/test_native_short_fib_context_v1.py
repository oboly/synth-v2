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
    PRIMARY_LIFECYCLE_COMPLETED,
    PRIMARY_LIFECYCLE_INVALIDATED,
    PRIMARY_LIFECYCLE_TARGET_ACTIVE,
    PRIMARY_LIFECYCLE_BREAKOUT_CONFIRMED,
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
        # End at 1.18: above breakout_gate (anchor_high=1.15) → BREAKOUT_CONFIRMED
        ["1.05", "1.00", "0.95", "1.00", "1.05", "1.15", "1.10", "1.08", "1.16", "1.18"],
        start=datetime(2026, 6, 3, 0, 0, tzinfo=UTC),
        step_hours=4,
    )
    support = _candles(
        # Support above breakout_gate (1.15) → ALIGNED_WITH_4H
        ["1.18"] * 60,
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
        min_primary_candles=8,
        primary_stale_after=timedelta(hours=48),
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
        min_primary_candles=8,
        primary_stale_after=timedelta(hours=48),
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
        min_primary_candles=8,
        primary_stale_after=timedelta(hours=48),
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
        min_primary_candles=8,
        primary_stale_after=timedelta(hours=48),
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
        min_primary_candles=8,
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
        min_primary_candles=8,
        primary_stale_after=timedelta(hours=48),
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
        min_primary_candles=8,
        primary_stale_after=timedelta(hours=48),
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
        min_primary_candles=8,
        primary_stale_after=timedelta(hours=48),
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
            min_primary_candles=8,
            primary_stale_after=timedelta(hours=48),
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
        min_primary_candles=8,
        primary_stale_after=timedelta(hours=48),
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
    assert set(symbols) == {"PLUME", "WLD"}
    assert markets == []


# ---------------------------------------------------------------------------
# Rollover regression tests
# ---------------------------------------------------------------------------

def _make_candle_sequence(prices: list[str], *, start: datetime, step_hours: int) -> list[Candle]:
    return _candles(prices, start=start, step_hours=step_hours)


def _support_flat(price: str, n: int = 60, *, start: datetime) -> list[Candle]:
    return _candles([price] * n, start=start, step_hours=1, wiggle="0.003")


def test_rollover_case_a_newer_active_beats_older_completed() -> None:
    """Case A: newer valid active swing must win over older completed swing."""
    now = datetime(2026, 6, 6, 20, 0, tzinfo=UTC)
    # 14 candles; pivots are detected in range(2, 12) i.e. indices 2-11.
    # Swing 1: pivot_low=idx2 (0.95), pivot_high=idx5 (1.15).
    #   max_high_since_anchor reaches 1.50 → all ext targets passed → MAP_COMPLETED.
    # Swing 2: pivot_low=idx7 (1.08), pivot_high=idx11 (1.50).
    #   current=1.44 < breakout_gate=1.50 → BELOW_BREAKOUT_GATE (active).
    primary = _candles(
        [
            "1.05", "1.00", "0.95", "1.00", "1.05",   # swing 1 low at idx 2
            "1.15",                                     # swing 1 pivot high at idx 5
            "1.10", "1.08",                             # dip → swing 2 low at idx 7
            "1.35", "1.30", "1.35",                    # bounce
            "1.50",                                     # swing 2 pivot high at idx 11
            "1.45", "1.44",                             # current: below swing 2 gate (1.50)
        ],
        start=datetime(2026, 6, 4, 0, 0, tzinfo=UTC),
        step_hours=4,
    )
    support = _support_flat("1.44", start=datetime(2026, 6, 4, 0, 0, tzinfo=UTC))
    row = build_native_short_context_row(
        symbol="WLD",
        venue="bitvavo",
        primary_candles=primary,
        support_candles=support,
        now_utc=now,
        min_primary_candles=8,
        primary_stale_after=timedelta(hours=48),
        support_stale_after=timedelta(hours=12),
    )
    # With the fix, the newer active map must be selected.
    assert row.context_status == STATUS_AVAILABLE
    assert row.primary_4h_lifecycle_state != PRIMARY_LIFECYCLE_COMPLETED, (
        "Case A violation: older completed map won over newer active map"
    )
    assert row.current_map_status == "CURRENT_ACTIVE_MAP"
    assert row.rollover_state == "CASE_A_NEWER_ACTIVE_SELECTED"
    assert row.previous_map_cycle_id != "", "previous_map_cycle_id must reference the completed map"
    assert row.previous_map_lifecycle_state == PRIMARY_LIFECYCLE_COMPLETED


def test_rollover_case_b_no_newer_map_shows_completed_as_fallback() -> None:
    """Case B: only one swing, and it is completed — must be returned as PREVIOUS_COMPLETED_MAP."""
    now = datetime(2026, 6, 6, 12, 0, tzinfo=UTC)
    primary = _candles(
        ["1.05", "1.00", "0.95", "1.00", "1.05", "1.15", "1.10", "1.08", "1.32", "1.45"],
        start=datetime(2026, 6, 4, 0, 0, tzinfo=UTC),
        step_hours=4,
    )
    support = _support_flat("1.28", start=datetime(2026, 6, 4, 0, 0, tzinfo=UTC))
    row = build_native_short_context_row(
        symbol="WLD",
        venue="bitvavo",
        primary_candles=primary,
        support_candles=support,
        now_utc=now,
        min_primary_candles=8,
        primary_stale_after=timedelta(hours=48),
    )
    assert row.context_status == STATUS_AVAILABLE
    assert row.primary_4h_lifecycle_state == PRIMARY_LIFECYCLE_COMPLETED
    assert row.current_map_status == "PREVIOUS_COMPLETED_MAP"
    assert row.rollover_state == "CASE_B_NO_NEW_MAP_WAIT"
    assert row.active_target_levels == ()


def test_rollover_case_c_invalidated_newest_falls_back_to_older_valid() -> None:
    """Case C: newest swing invalidated — must fall back to an older still-valid swing."""
    now = datetime(2026, 6, 6, 20, 0, tzinfo=UTC)
    # First swing: low at idx 2, high at idx 5, stays valid (price stays above low).
    # Second swing: low at idx 9, high at idx 13, then price crashes below low → INVALIDATED.
    primary = _candles(
        [
            "1.10", "1.00", "0.85", "0.95", "1.00",
            "1.25",
            "1.20", "1.18", "1.16",
            "1.10",
            "1.12", "1.14", "1.16",
            "1.30",
            "0.95",  # crash below swing 2 low → INVALIDATED for swing 2
        ],
        start=datetime(2026, 6, 4, 0, 0, tzinfo=UTC),
        step_hours=4,
    )
    support = _support_flat("0.98", start=datetime(2026, 6, 4, 0, 0, tzinfo=UTC))
    row = build_native_short_context_row(
        symbol="WLD",
        venue="bitvavo",
        primary_candles=primary,
        support_candles=support,
        now_utc=now,
        min_primary_candles=8,
        primary_stale_after=timedelta(hours=48),
    )
    assert row.primary_4h_lifecycle_state != PRIMARY_LIFECYCLE_INVALIDATED, (
        "Case C: should fall back to older valid swing, not return INVALIDATED"
    )
    assert row.rollover_state in {"CASE_C_INVALIDATED_FALLBACK", "CASE_A_NEWER_ACTIVE_SELECTED", "SINGLE_MAP"}


def test_rollover_completed_map_has_no_active_targets() -> None:
    """Completed maps must report empty active_target_levels regardless of selection."""
    now = datetime(2026, 6, 6, 12, 0, tzinfo=UTC)
    primary = _candles(
        ["1.05", "1.00", "0.95", "1.00", "1.05", "1.15", "1.10", "1.08", "1.32", "1.45"],
        start=datetime(2026, 6, 4, 0, 0, tzinfo=UTC),
        step_hours=4,
    )
    support = _support_flat("1.28", start=datetime(2026, 6, 4, 0, 0, tzinfo=UTC))
    row = build_native_short_context_row(
        symbol="WLD",
        venue="bitvavo",
        primary_candles=primary,
        support_candles=support,
        now_utc=now,
        min_primary_candles=8,
        primary_stale_after=timedelta(hours=48),
    )
    assert row.primary_4h_lifecycle_state == PRIMARY_LIFECYCLE_COMPLETED
    assert row.active_target_levels == ()
    assert row.previous_target_levels != ()


def test_rollover_fields_present_in_csv_round_trip() -> None:
    """Rollover fields must survive CSV write/read round-trip."""
    now = datetime(2026, 6, 6, 12, 0, tzinfo=UTC)
    primary = _candles(
        ["1.05", "1.00", "0.95", "1.00", "1.05", "1.15", "1.10", "1.08", "1.32", "1.45"],
        start=datetime(2026, 6, 4, 0, 0, tzinfo=UTC),
        step_hours=4,
    )
    support = _support_flat("1.28", start=datetime(2026, 6, 4, 0, 0, tzinfo=UTC))
    row = build_native_short_context_row(
        symbol="WLD",
        venue="bitvavo",
        primary_candles=primary,
        support_candles=support,
        now_utc=now,
        min_primary_candles=8,
        primary_stale_after=timedelta(hours=48),
    )
    assert row.current_map_status != ""
    assert row.rollover_state != ""
    with tempfile.TemporaryDirectory() as tmpdir:
        paths = write_context_rows(rows=[row], output_dir=Path(tmpdir))
        loaded, missing = load_native_short_context_rows(paths["rows_csv"])
        assert missing is False
        reloaded = loaded["WLD"]
        assert reloaded.current_map_status == row.current_map_status
        assert reloaded.rollover_state == row.rollover_state
        assert reloaded.selection_reason == row.selection_reason
        assert reloaded.previous_map_cycle_id == row.previous_map_cycle_id
        assert reloaded.previous_map_lifecycle_state == row.previous_map_lifecycle_state


def test_rollover_single_active_map_no_rollover() -> None:
    """Single swing in active state reports SINGLE_MAP rollover_state."""
    now = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    primary = _candles(
        ["1.05", "1.00", "0.95", "1.00", "1.05", "1.15", "1.10", "1.08", "1.12", "1.14"],
        start=datetime(2026, 6, 3, 0, 0, tzinfo=UTC),
        step_hours=4,
    )
    support = _support_flat("1.10", start=datetime(2026, 6, 3, 0, 0, tzinfo=UTC))
    row = build_native_short_context_row(
        symbol="WLD",
        venue="bitvavo",
        primary_candles=primary,
        support_candles=support,
        now_utc=now,
        min_primary_candles=8,
        primary_stale_after=timedelta(hours=48),
    )
    assert row.context_status == STATUS_AVAILABLE
    assert row.current_map_status == "CURRENT_ACTIVE_MAP"
    assert row.rollover_state in {"SINGLE_MAP", "NO_ROLLOVER"}
    assert row.previous_map_cycle_id == ""


def test_rollover_invalidated_only_never_reports_active_map() -> None:
    """When all swings are invalidated, current_map_status must not be CURRENT_ACTIVE_MAP."""
    now = datetime(2026, 6, 6, 12, 0, tzinfo=UTC)
    primary = _candles(
        ["1.05", "1.00", "0.95", "1.00", "1.05", "1.15", "1.10", "1.08", "0.85", "0.82"],
        start=datetime(2026, 6, 4, 0, 0, tzinfo=UTC),
        step_hours=4,
    )
    support = _support_flat("0.84", start=datetime(2026, 6, 4, 0, 0, tzinfo=UTC))
    row = build_native_short_context_row(
        symbol="WLD",
        venue="bitvavo",
        primary_candles=primary,
        support_candles=support,
        now_utc=now,
        min_primary_candles=8,
        primary_stale_after=timedelta(hours=48),
    )
    # Status should be STALE_OR_INVALID when invalidated
    assert row.context_status == STATUS_STALE_OR_INVALID
    assert row.current_map_status != "CURRENT_ACTIVE_MAP"
