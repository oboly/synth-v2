"""Tests for Issue #707 Phase B: the deterministic true point-in-time (PIT)
Fib exit-ladder replay engine, built against the frozen contract in
docs/research/fib_exit_ladder_v1_pit_replay_contract_v1.md.

Covers (per the Phase B task's required test groups):
    A. No future access
    B. Confirmation semantics (observable-after-close, entry-is-next-open)
    C. Determinism
    D. Selection/OOS separation (no retuning path)
    E. Candidate grid shape (3 families x 5 fractions, no FIB_STANDARD)
    F. Architecture imports (no decision_gate/execution_planner/executor/
       account/broker/order code)
    G. Representative synthetic replay (confirmed entry, no-anchor,
       insufficient-data, tie case)

Does not access the DB and does not run the real five-asset PIT outcome
replay — synthetic candle series only, per this phase's scope.
"""
from __future__ import annotations

import ast
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from src.research import fib_exit_ladder_v1_pit_replay_engine_v1 as engine
from src.research import run_fib_exit_ladder_backtest_v1 as ladder_bt

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATH = REPO_ROOT / "src/research/fib_exit_ladder_v1_pit_replay_engine_v1.py"

FORBIDDEN_IMPORT_PREFIXES = (
    "src.decision_gate",
    "src.execution_planner",
    "src.executor",
    "src.market_data",  # not account, but keep engine scope tight: not imported
)
FORBIDDEN_IMPORT_SUBSTRINGS = (
    "decision_gate",
    "execution_planner",
    "executor",
    "account",
    "broker",
    "order",
)


def _candle(days: int, open_price: str, high: str, low: str, close: str) -> ladder_bt.Candle:
    base = datetime(2020, 1, 1)
    return ladder_bt.Candle(
        open_ts_utc=base + timedelta(days=days),
        open_price=Decimal(open_price),
        high_price=Decimal(high),
        low_price=Decimal(low),
        close_price=Decimal(close),
    )


def _flat_run(start_day: int, end_day_exclusive: int, price: str) -> list[ladder_bt.Candle]:
    return [_candle(day, price, price, price, price) for day in range(start_day, end_day_exclusive)]


def _confirmed_series(confirmation_day: int = 25, tail_days: int = 40) -> list[ladder_bt.Candle]:
    """A deterministic synthetic series with exactly one PIT-confirmable
    anchor: anchor_low=1.00 (day0), wave1_high=2.50 (day14, gain=150% >=
    required 100%), wave2_low=1.50 (day17, retrace=(2.50-1.50)/1.50=0.667,
    within [0.236, 0.886]), confirmed when close first exceeds 2.50 at
    `confirmation_day` (close=2.60), observable/entry at confirmation_day+1
    (open=2.61). A long flat tail follows so the ladder has room to fill
    rungs and so truncation tests have plenty of "future" to discard."""
    candles = [_candle(0, "1.00", "1.05", "1.00", "1.00")]
    candles += _flat_run(1, 14, "1.20")
    candles.append(_candle(14, "1.30", "2.50", "1.25", "1.30"))  # wave1 high candle
    candles += _flat_run(15, 17, "1.60")
    candles.append(_candle(17, "1.55", "1.60", "1.50", "1.55"))  # wave2 low candle
    candles += _flat_run(18, confirmation_day, "2.00")
    candles.append(
        _candle(confirmation_day, "2.05", "2.65", "2.00", "2.60")
    )  # confirmation: close 2.60 > wave1_high 2.50
    candles.append(_candle(confirmation_day + 1, "2.61", "2.70", "2.55", "2.62"))  # entry/observable candle
    # Long rising tail so the ladder has real fill opportunity.
    for offset, day in enumerate(range(confirmation_day + 2, confirmation_day + 2 + tail_days)):
        price = Decimal("2.62") + Decimal(offset) * Decimal("0.30")
        price_text = str(price)
        candles.append(_candle(day, price_text, str(price + Decimal("0.05")), price_text, price_text))
    return candles


def _no_anchor_series(length: int = 60) -> list[ladder_bt.Candle]:
    """Flat/low-volatility series: no wave1 gain ever reaches the required
    threshold, so no candidate anchor is ever geometrically eligible."""
    return [_candle(day, "1.00", "1.02", "0.99", "1.00") for day in range(length)]


def _insufficient_data_series(length: int = 10) -> list[ladder_bt.Candle]:
    assert length < engine.MIN_CANDLES_REQUIRED
    return [_candle(day, "1.00", "1.05", "0.95", "1.00") for day in range(length)]


class _TripwireCandles:
    """A read-only candle sequence that raises if any index at or beyond
    `forbidden_from_idx` is ever accessed, used to structurally prove a
    detector call makes no future-index access at all (not merely that its
    *result* happens to be unaffected)."""

    def __init__(self, candles: list[ladder_bt.Candle], forbidden_from_idx: int) -> None:
        self._candles = candles
        self._forbidden_from_idx = forbidden_from_idx

    def __len__(self) -> int:
        return self._forbidden_from_idx

    def __getitem__(self, item):
        if isinstance(item, slice):
            indices = range(*item.indices(len(self._candles)))
            if any(idx >= self._forbidden_from_idx for idx in indices):
                raise AssertionError(f"forbidden slice access reaching index >= {self._forbidden_from_idx}: {item}")
            return self._candles[item]
        if item >= self._forbidden_from_idx or item < 0:
            raise AssertionError(f"forbidden index access: {item} >= {self._forbidden_from_idx}")
        return self._candles[item]


# ---------------------------------------------------------------------------
# A. No future access
# ---------------------------------------------------------------------------


def test_changing_candles_after_decision_timestamp_does_not_change_detector_result() -> None:
    full = _confirmed_series()
    anchor_full = engine.find_pit_anchor(full)
    assert anchor_full is not None

    truncated = full[: anchor_full.entry_idx + 1]
    anchor_truncated = engine.find_pit_anchor(truncated)
    assert anchor_truncated is not None
    assert anchor_truncated == anchor_full

    # Mutate every candle strictly after the entry candle into extreme noise;
    # the anchor already fixed above must not change.
    mutated = list(full[: anchor_full.entry_idx + 1]) + [
        _candle(1000 + i, "999.00", "1000.00", "0.01", "0.02") for i in range(20)
    ]
    anchor_mutated = engine.find_pit_anchor(mutated)
    assert anchor_mutated == anchor_full


def test_detector_never_requires_full_series_suffix_access() -> None:
    """Structural proof: find_pit_anchor never reads a candle at or beyond
    the entry candle's own index + 1, using a sequence that raises on any
    such access instead of merely comparing before/after results."""
    full = _confirmed_series()
    anchor_full = engine.find_pit_anchor(full)
    assert anchor_full is not None

    tripwire = _TripwireCandles(full, forbidden_from_idx=anchor_full.entry_idx + 1)
    anchor_via_tripwire = engine.find_pit_anchor(tripwire)  # type: ignore[arg-type]
    assert anchor_via_tripwire == anchor_full


def test_same_candle_ohlc_cannot_affect_entry_decision() -> None:
    """The entry candle's own high/low/close must never affect entry_price
    or entry_ts — only its open_price/open_ts_utc may be used."""
    full = _confirmed_series()
    anchor = engine.find_pit_anchor(full)
    assert anchor is not None

    tampered = list(full)
    entry_idx = anchor.entry_idx
    original = tampered[entry_idx]
    tampered[entry_idx] = ladder_bt.Candle(
        open_ts_utc=original.open_ts_utc,
        open_price=original.open_price,
        high_price=Decimal("99999.00"),
        low_price=Decimal("0.0001"),
        close_price=Decimal("0.0002"),
    )

    anchor_tampered = engine.find_pit_anchor(tampered)
    assert anchor_tampered is not None
    assert anchor_tampered.entry_price == anchor.entry_price
    assert anchor_tampered.entry_ts == anchor.entry_ts


# ---------------------------------------------------------------------------
# B. Confirmation semantics
# ---------------------------------------------------------------------------


def test_confirmation_not_observable_until_next_candle_closes() -> None:
    """If the series ends exactly at the confirmation candle, the candidate
    must not be treated as entered — no anchor is returned at all."""
    full = _confirmed_series()
    anchor = engine.find_pit_anchor(full)
    assert anchor is not None

    ends_at_confirmation = full[: anchor.confirmation_idx + 1]
    anchor_no_observable = engine.find_pit_anchor(ends_at_confirmation)
    assert anchor_no_observable is None


def test_entry_is_next_candle_open_not_confirmation_candle_itself() -> None:
    full = _confirmed_series()
    anchor = engine.find_pit_anchor(full)
    assert anchor is not None

    assert anchor.entry_idx == anchor.confirmation_idx + 1
    assert anchor.entry_ts == full[anchor.confirmation_idx + 1].open_ts_utc
    assert anchor.entry_price == full[anchor.confirmation_idx + 1].open_price
    assert anchor.entry_price != full[anchor.confirmation_idx].close_price


# ---------------------------------------------------------------------------
# C. Determinism
# ---------------------------------------------------------------------------


def test_repeated_runs_are_field_equivalent() -> None:
    full = _confirmed_series()
    result_a = engine.evaluate_pit_symbol_window_config(
        "LINK", "SELECTION_WINDOW", full, "PRO_3X4X", Decimal("0.80")
    )
    result_b = engine.evaluate_pit_symbol_window_config(
        "LINK", "SELECTION_WINDOW", full, "PRO_3X4X", Decimal("0.80")
    )
    assert result_a == result_b


def test_selection_ranking_is_stable_across_repeated_runs() -> None:
    full = _confirmed_series()
    selected_a, grid_a = engine.select_policy_on_selection_window("LINK", full)
    selected_b, grid_b = engine.select_policy_on_selection_window("LINK", full)
    assert selected_a == selected_b
    assert grid_a == grid_b


# ---------------------------------------------------------------------------
# D. Selection / OOS separation
# ---------------------------------------------------------------------------


def test_selection_only_touches_the_candles_it_is_given() -> None:
    """select_policy_on_selection_window has no parameter through which OOS
    candles could reach it; passing only SELECTION_WINDOW-filtered candles
    is structurally the only way to call it."""
    full = _confirmed_series()
    selected, grid_results = engine.select_policy_on_selection_window("LINK", full)
    assert selected is not None
    for result in grid_results.values():
        assert result.window == "SELECTION_WINDOW"


def test_oos_evaluator_accepts_only_a_frozen_selected_policy() -> None:
    import inspect

    params = inspect.signature(engine.evaluate_oos_window).parameters
    assert "selected" in params
    # No parameter exists that could carry a candidate grid or competing
    # configs into the OOS evaluator.
    assert "families" not in params
    assert "fractions" not in params
    assert "grid_results" not in params


def test_changing_competing_config_outcomes_cannot_alter_selected_config() -> None:
    """Once a policy is selected on SELECTION_WINDOW, evaluating OOS windows
    (even wildly different candle data) never feeds back into what was
    selected, because evaluate_oos_window's signature has no path to alter
    `selected`."""
    full = _confirmed_series()
    selected, _ = engine.select_policy_on_selection_window("LINK", full)
    assert selected is not None

    oos_candles_a = _no_anchor_series()
    oos_candles_b = _confirmed_series(confirmation_day=30)

    result_a = engine.evaluate_oos_window(selected, "OOS_WINDOW_1", oos_candles_a)
    result_b = engine.evaluate_oos_window(selected, "OOS_WINDOW_1", oos_candles_b)

    # Whatever the OOS outcome, the frozen policy identity is untouched.
    assert selected.target_family == selected.target_family
    assert result_a.target_family == selected.target_family
    assert result_b.target_family == selected.target_family
    assert result_a.max_ladder_sell_fraction == selected.max_ladder_sell_fraction
    assert result_b.max_ladder_sell_fraction == selected.max_ladder_sell_fraction


def test_run_pit_replay_for_symbol_does_not_retune_between_oos_windows() -> None:
    selection_candles = _confirmed_series()
    oos1_candles = _no_anchor_series()
    oos2_candles = _confirmed_series(confirmation_day=30)

    result = engine.run_pit_replay_for_symbol("LINK", selection_candles, oos1_candles, oos2_candles)
    assert result.selected_policy is not None
    assert result.oos_window_1_result is not None
    assert result.oos_window_2_result is not None
    assert result.oos_window_1_result.target_family == result.selected_policy.target_family
    assert result.oos_window_2_result.target_family == result.selected_policy.target_family
    assert result.oos_window_1_result.max_ladder_sell_fraction == result.selected_policy.max_ladder_sell_fraction
    assert result.oos_window_2_result.max_ladder_sell_fraction == result.selected_policy.max_ladder_sell_fraction


# ---------------------------------------------------------------------------
# E. Candidate grid
# ---------------------------------------------------------------------------


def test_candidate_grid_is_exactly_three_families_by_five_fractions() -> None:
    assert set(engine.CANDIDATE_FAMILIES) == {"PRO_3X4X", "SUPERCYCLE", "EXPLOSIVE_SUPERCYCLE"}
    assert "FIB_STANDARD" not in engine.CANDIDATE_FAMILIES
    assert len(engine.CANDIDATE_FAMILIES) == 3
    assert len(engine.SELL_FRACTION_GRID) == 5

    full = _confirmed_series()
    _, grid_results = engine.select_policy_on_selection_window("LINK", full)
    assert len(grid_results) == 15
    assert {family for family, _ in grid_results} == set(engine.CANDIDATE_FAMILIES)


def test_evaluate_rejects_unknown_target_family() -> None:
    full = _confirmed_series()
    with pytest.raises(ValueError):
        engine.evaluate_pit_symbol_window_config("LINK", "SELECTION_WINDOW", full, "NOT_A_FAMILY", Decimal("0.80"))


# ---------------------------------------------------------------------------
# F. Architecture imports
# ---------------------------------------------------------------------------


def test_engine_module_imports_no_forbidden_layers() -> None:
    tree = ast.parse(ENGINE_PATH.read_text(encoding="utf-8"))
    imported_names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.append(node.module)

    for name in imported_names:
        lowered = name.lower()
        for forbidden in FORBIDDEN_IMPORT_SUBSTRINGS:
            assert forbidden not in lowered, f"forbidden import found: {name!r} contains {forbidden!r}"


def test_engine_module_has_no_db_or_network_imports() -> None:
    text = ENGINE_PATH.read_text(encoding="utf-8")
    for forbidden in ("import pymysql", "import requests", "import socket", "import broker"):
        assert forbidden not in text


# ---------------------------------------------------------------------------
# G. Representative synthetic replay
# ---------------------------------------------------------------------------


def test_representative_confirmed_series_yields_ok_result_with_fills() -> None:
    full = _confirmed_series()
    result = engine.evaluate_pit_symbol_window_config(
        "LINK", "SELECTION_WINDOW", full, "PRO_3X4X", Decimal("0.80")
    )
    assert result.status == engine.STATUS_OK
    assert result.sample_count == 1
    assert result.entry_price is not None
    assert result.entry_price > 0
    assert result.total_return_pct_with_remaining is not None
    assert result.hold_return_pct is not None
    assert result.alpha_vs_hold_pct == result.total_return_pct_with_remaining - result.hold_return_pct
    assert result.filled_rung_count > 0  # rising tail gives the ladder real fill opportunity


def test_no_anchor_series_yields_no_anchor_status() -> None:
    series = _no_anchor_series()
    result = engine.evaluate_pit_symbol_window_config(
        "LINK", "SELECTION_WINDOW", series, "PRO_3X4X", Decimal("0.80")
    )
    assert result.status == engine.STATUS_NO_ANCHOR_SET_FOUND
    assert result.sample_count == 0
    assert result.entry_ts is None
    assert result.total_return_pct_with_remaining is None


def test_insufficient_data_series_yields_insufficient_candles_status() -> None:
    series = _insufficient_data_series()
    result = engine.evaluate_pit_symbol_window_config(
        "LINK", "SELECTION_WINDOW", series, "PRO_3X4X", Decimal("0.80")
    )
    assert result.status == engine.STATUS_INSUFFICIENT_CANDLES
    assert result.sample_count == 0


def test_selection_returns_insufficient_data_when_no_grid_combo_confirms() -> None:
    series = _no_anchor_series()
    selected, grid_results = engine.select_policy_on_selection_window("LINK", series)
    assert selected is None
    assert len(grid_results) == 15
    assert all(result.status != engine.STATUS_OK for result in grid_results.values())


def test_tie_case_breaks_by_lower_fraction_then_family_order() -> None:
    """Direct test of the ranking helper's fail-closed tie-break, using
    synthetic PitSymbolResult rows with a deliberately identical
    total_return_pct_with_remaining across two combinations, per contract
    § 7 tie handling: prefer the lower max_ladder_sell_fraction, then the
    family earlier in CANDIDATE_FAMILIES order."""

    def _ok(family: str, fraction: Decimal, total_return: Decimal) -> engine.PitSymbolResult:
        return engine.PitSymbolResult(
            symbol="LINK",
            window="SELECTION_WINDOW",
            target_family=family,
            max_ladder_sell_fraction=fraction,
            status=engine.STATUS_OK,
            anchor_low_ts=None,
            wave1_high_ts=None,
            wave2_low_ts=None,
            confirmation_ts=None,
            entry_ts=None,
            entry_price=Decimal("1.00"),
            total_return_pct_with_remaining=total_return,
            hold_return_pct=Decimal("0.00"),
            alpha_vs_hold_pct=total_return,
            filled_rung_count=0,
            sample_count=1,
            peak_oracle_return_pct=None,
            top_capture_ratio=None,
            fills=(),
        )

    tied_return = Decimal("42.00")
    grid_results = {
        ("SUPERCYCLE", Decimal("0.70")): _ok("SUPERCYCLE", Decimal("0.70"), tied_return),
        ("PRO_3X4X", Decimal("0.60")): _ok("PRO_3X4X", Decimal("0.60"), tied_return),
        ("PRO_3X4X", Decimal("0.70")): _ok("PRO_3X4X", Decimal("0.70"), tied_return),
        ("EXPLOSIVE_SUPERCYCLE", Decimal("0.50")): _ok("EXPLOSIVE_SUPERCYCLE", Decimal("0.50"), Decimal("10.00")),
    }

    ranked = engine._rank_grid_results(grid_results, engine.CANDIDATE_FAMILIES)  # noqa: SLF001
    best_key, best_result = ranked[0]
    # Lowest fraction among the tied-return rows wins first (0.60 beats 0.70).
    assert best_key == ("PRO_3X4X", Decimal("0.60"))
    assert best_result.total_return_pct_with_remaining == tied_return

    # Among the two 0.70-fraction tied rows, family order breaks the tie:
    # PRO_3X4X precedes SUPERCYCLE in CANDIDATE_FAMILIES.
    seventy_fraction_rows = [item for item in ranked if item[0][1] == Decimal("0.70")]
    assert seventy_fraction_rows[0][0] == ("PRO_3X4X", Decimal("0.70"))


def _wave2_confirmation_edge_series(
    *,
    first_confirmation_day: int | None,
    second_wave2_day: int | None = None,
    second_confirmation_day: int | None = None,
) -> list[ladder_bt.Candle]:
    """Series whose reclaim before day17 must not affect day17 wave2."""
    candles = [_candle(0, "1.00", "1.05", "1.00", "1.00")]
    candles += _flat_run(1, 14, "1.20")
    candles.append(_candle(14, "1.30", "2.50", "1.25", "1.30"))
    candles.append(_candle(15, "2.00", "2.05", "2.00", "2.00"))
    candles.append(_candle(16, "2.00", "2.65", "2.00", "2.60"))  # reclaim before wave2
    candles.append(_candle(17, "1.55", "1.60", "1.50", "1.55"))  # valid wave2
    for day in range(18, 31):
        if day == first_confirmation_day or day == second_confirmation_day:
            candles.append(_candle(day, "2.05", "2.65", "2.00", "2.60"))
        elif day == second_wave2_day:
            candles.append(_candle(day, "1.55", "1.60", "1.50", "1.55"))
        else:
            candles.append(_candle(day, "2.00", "2.05", "2.00", "2.00"))
    return candles


def test_reclaim_before_valid_wave2_does_not_block_later_confirmation() -> None:
    candles = _wave2_confirmation_edge_series(first_confirmation_day=20)
    anchor = engine.find_pit_anchor(candles)

    assert anchor is not None
    assert anchor.wave1_high_ts == candles[14].open_ts_utc
    assert anchor.wave2_low_ts == candles[17].open_ts_utc
    assert anchor.confirmation_idx == 20
    assert anchor.entry_idx == 21


def test_multiple_valid_wave2_candidates_have_independent_confirmation_searches() -> None:
    candles = _wave2_confirmation_edge_series(
        first_confirmation_day=18,
        second_wave2_day=20,
        second_confirmation_day=21,
    )

    assert engine.pit_contract.find_confirmation_index(candles, Decimal("2.50"), 17) == 18
    assert engine.pit_contract.find_confirmation_index(candles, Decimal("2.50"), 20) == 21
    anchor = engine.find_pit_anchor(candles)
    assert anchor is not None
    assert anchor.wave2_low_ts == candles[17].open_ts_utc
    assert anchor.confirmation_idx == 18
    assert anchor.entry_idx == 19


def test_valid_wave2_without_later_confirmation_is_not_an_anchor() -> None:
    candles = _wave2_confirmation_edge_series(first_confirmation_day=None)
    assert engine.find_pit_anchor(candles) is None


def test_rejects_fib_standard_and_invalid_frozen_fraction() -> None:
    full = _confirmed_series()
    with pytest.raises(ValueError, match="frozen target_family"):
        engine.evaluate_pit_symbol_window_config("LINK", "SELECTION_WINDOW", full, "FIB_STANDARD", Decimal("0.80"))
    with pytest.raises(ValueError, match="max_ladder_sell_fraction"):
        engine.evaluate_pit_symbol_window_config("LINK", "SELECTION_WINDOW", full, "PRO_3X4X", Decimal("0.90"))


def test_selection_has_no_caller_grid_override_path() -> None:
    import inspect

    params = inspect.signature(engine.select_policy_on_selection_window).parameters
    assert "families" not in params
    assert "fractions" not in params


def test_oos_rejects_forged_non_frozen_selected_policy() -> None:
    forged = engine.SelectedPolicy(
        symbol="LINK",
        target_family="FIB_STANDARD",
        max_ladder_sell_fraction=Decimal("0.80"),
        selection_metric_value=Decimal("0"),
        selection_sample_count=1,
    )
    with pytest.raises(ValueError, match="frozen target_family"):
        engine.evaluate_oos_window(forged, "OOS_WINDOW_1", _confirmed_series())
