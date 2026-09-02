"""
Synth v2.6 research engine: FIB_EXIT_LADDER_V1_PIT_REPLAY_ENGINE_V1 (Issue
#707 Phase B).

Layer:
    research only. Pure functions operating on injected `Candle` sequences.
    No DB access, no I/O, no account/broker/order code.

Purpose:
    Implement the deterministic true point-in-time (PIT) Fib exit-ladder
    replay engine against the frozen contract in
    docs/research/fib_exit_ladder_v1_pit_replay_contract_v1.md (Issue #707
    Phase A). This module implements § 5 (PIT anchor/confirmation/entry),
    § 6 (candidate grid), § 7 (SELECTION_WINDOW selection), and § 8 (OOS
    evaluation). It does not run any real DB replay, does not read any new
    outcome metric from live data, and does not write anything.

Boundary:
    - No DB access, no network I/O.
    - No account/balance/position/order access.
    - No decision_gate, execution_planner, or executor imports.
    - No `automatic_exit_profile_v1` writes, no #657 promotion/binding.
    - Detection advances in timestamp order and returns at the earliest
      observable entry. It never reads a candle after that entry index.

Explicitly NOT reused from the future-aware `#270` detector:
    `find_anchor_set` in run_fib_exit_ladder_backtest_v1.py uses
    `future_high = max(candle.high for candle in candles[wave2_idx+1:])`
    and an `expansion` score derived from it to pick the *best* anchor. This
    module's `find_pit_anchor` never reads a suffix-max array, never scores
    by future expansion, and never admits a candidate on the basis of a
    future high. The only reused primitives are the pure Fib-ladder target/
    rung/fill mechanics (`build_targets`, `build_rungs`, `simulate_fills`,
    `weighted_avg_exit_price`, `return_pct`), which do not consult future
    data for eligibility or scoring — they only turn an already-fixed anchor
    into a price ladder and simulate forward fills, which the contract's
    § 5.2 explicitly permits ("downstream evaluation starts after the
    decision timestamp").
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional

from src.research import fib_exit_ladder_v1_pit_replay_contract_v1 as pit_contract
from src.research.run_fib_exit_ladder_backtest_v1 import (
    AnchorSet,
    Candle,
    Fill,
    Rung,
    build_rungs,
    build_targets,
    parse_datetime,
    return_pct,
    simulate_fills,
    weighted_avg_exit_price,
)

# Re-exported for callers; frozen per contract § 4 / § 3 / § 6.
SELECTION_WINDOW = pit_contract.SELECTION_WINDOW
OOS_WINDOW_1 = pit_contract.OOS_WINDOW_1
OOS_WINDOW_2 = pit_contract.OOS_WINDOW_2
REQUIRED_ASSET_UNIVERSE = pit_contract.REQUIRED_ASSET_UNIVERSE
CANDIDATE_FAMILIES = pit_contract.CANDIDATE_FAMILIES
SELL_FRACTION_GRID = pit_contract.SELL_FRACTION_GRID

# Frozen per contract § 5.1.
DEFAULT_PIVOT_THRESHOLD_PCT = Decimal("0.25")
DEFAULT_MIN_WAVE1_GAIN_PCT = Decimal("1.00")
DEFAULT_MIN_WAVE1_DAYS = 14
DEFAULT_MIN_WAVE2_DAYS_AFTER_HIGH = 3
DEFAULT_WAVE2_MIN_RETRACE = Decimal("0.236")
DEFAULT_WAVE2_MAX_RETRACE = Decimal("0.886")

# Frozen per contract § 6 (ladder construction parameters, unchanged from
# `#270`'s defaults).
DEFAULT_RUNGS_PER_TARGET = 5
DEFAULT_DISTRIBUTION = "front_loaded"
DEFAULT_TARGET_ZONE_LOW_PCT = Decimal("0.04")
DEFAULT_TARGET_ZONE_HIGH_PCT = Decimal("0.04")
DEFAULT_FRONT_RUN_PCT = Decimal("0.08")
DEFAULT_END_PCT_OF_ZONE_HIGH = Decimal("0.98")

MIN_CANDLES_REQUIRED = 20

STATUS_OK = "OK"
STATUS_INSUFFICIENT_CANDLES = "INSUFFICIENT_CANDLES"
STATUS_NO_ANCHOR_SET_FOUND = "NO_ANCHOR_SET_FOUND"
STATUS_NO_FUTURE_CANDLES = "NO_FUTURE_CANDLES"
STATUS_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


# ---------------------------------------------------------------------------
# § 5: point-in-time anchor detection, confirmation, and entry.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PitAnchor:
    anchor_low: Decimal
    anchor_low_ts: datetime
    wave1_high: Decimal
    wave1_high_ts: datetime
    wave2_low: Decimal
    wave2_low_ts: datetime
    wave1_range: Decimal
    confirmation_idx: int
    confirmation_ts: datetime
    entry_idx: int
    entry_ts: datetime
    entry_price: Decimal


@dataclass
class _PitPairState:
    """Incremental state for one `(low_idx, high_idx)` candidate pair.

    `find_pit_anchor` advances every pair only with the current chronological
    scan candle. No pair owns or rescans a future suffix.
    """

    low_idx: int
    high_idx: int
    anchor_low: Decimal
    wave1_high: Decimal
    wave1_range: Decimal
    high_ts: datetime
    pending_wave2_idx: Optional[int] = None


def _wave2_is_valid_for_pair(
    *,
    candle: Candle,
    state: _PitPairState,
    min_wave2_days_after_high: int,
    wave2_min_retrace: Decimal,
    wave2_max_retrace: Decimal,
) -> bool:
    wave2_days_after_high = (candle.open_ts_utc - state.high_ts).days
    if wave2_days_after_high < min_wave2_days_after_high:
        return False
    wave2_low = candle.low_price
    if wave2_low <= state.anchor_low or wave2_low >= state.wave1_high:
        return False
    retrace = (state.wave1_high - wave2_low) / state.wave1_range
    return wave2_min_retrace <= retrace <= wave2_max_retrace


def find_pit_anchor(
    candles: list[Candle],
    pivot_threshold_pct: Decimal = DEFAULT_PIVOT_THRESHOLD_PCT,
    min_wave1_gain_pct: Decimal = DEFAULT_MIN_WAVE1_GAIN_PCT,
    min_wave1_days: int = DEFAULT_MIN_WAVE1_DAYS,
    min_wave2_days_after_high: int = DEFAULT_MIN_WAVE2_DAYS_AFTER_HIGH,
    wave2_min_retrace: Decimal = DEFAULT_WAVE2_MIN_RETRACE,
    wave2_max_retrace: Decimal = DEFAULT_WAVE2_MAX_RETRACE,
) -> Optional[PitAnchor]:
    """Return the earliest observable PIT-confirmed anchor, or ``None``.

    Detection is chronological. For each closed candle `scan_idx`, every
    already-known `(low_idx, high_idx)` pair is advanced exactly once with
    that candle. Confirmation is checked before the candle may become a new
    wave2, so same-candle confirmation is impossible. Once any pair confirms,
    all confirmations at that same timestamp are tie-broken deterministically
    by `(low_idx, high_idx, wave2_idx)`, the next candle's open fixes entry,
    and the function returns immediately. Nothing after that entry index is
    inspected.
    """
    candle_count = len(candles)
    if candle_count < MIN_CANDLES_REQUIRED:
        return None

    active_pairs: list[_PitPairState] = []

    # `scan_idx` is the candle that has just become fully observable. The
    # range stops one candle before the end because confirmation needs the
    # next candle's open as the tradeable entry/observable timestamp.
    for scan_idx in range(0, candle_count - 1):
        scan_candle = candles[scan_idx]

        # First, let the just-closed candle confirm only wave2 candidates that
        # were already pending before this candle. This prevents a candle from
        # qualifying as wave2 and confirming itself.
        confirmed_states = [
            state
            for state in active_pairs
            if state.pending_wave2_idx is not None
            and scan_candle.close_price > state.wave1_high
        ]
        if confirmed_states:
            chosen = min(
                confirmed_states,
                key=lambda state: (
                    state.low_idx,
                    state.high_idx,
                    state.pending_wave2_idx,
                ),
            )
            assert chosen.pending_wave2_idx is not None
            wave2_idx = chosen.pending_wave2_idx
            entry_idx = scan_idx + 1
            entry_candle = candles[entry_idx]
            wave2_candle = candles[wave2_idx]
            return PitAnchor(
                anchor_low=chosen.anchor_low,
                anchor_low_ts=candles[chosen.low_idx].open_ts_utc,
                wave1_high=chosen.wave1_high,
                wave1_high_ts=candles[chosen.high_idx].open_ts_utc,
                wave2_low=wave2_candle.low_price,
                wave2_low_ts=wave2_candle.open_ts_utc,
                wave1_range=chosen.wave1_range,
                confirmation_idx=scan_idx,
                confirmation_ts=scan_candle.open_ts_utc,
                entry_idx=entry_idx,
                entry_ts=entry_candle.open_ts_utc,
                entry_price=entry_candle.open_price,
            )

        # No confirmation at this timestamp. Advance every existing pair once
        # with this candle, retaining the earliest valid pending wave2.
        for state in active_pairs:
            if state.pending_wave2_idx is not None:
                continue
            if _wave2_is_valid_for_pair(
                candle=scan_candle,
                state=state,
                min_wave2_days_after_high=min_wave2_days_after_high,
                wave2_min_retrace=wave2_min_retrace,
                wave2_max_retrace=wave2_max_retrace,
            ):
                state.pending_wave2_idx = scan_idx

        # Finally, the current closed candle may become a wave1 high for
        # future candles. Every candidate low used here is strictly historical
        # (`low_idx < scan_idx`); no future candle is consulted.
        if scan_idx == 0:
            continue
        wave1_high = scan_candle.high_price
        for low_idx in range(0, scan_idx):
            low_candle = candles[low_idx]
            anchor_low = low_candle.low_price
            if anchor_low <= 0:
                continue
            wave1_days = (scan_candle.open_ts_utc - low_candle.open_ts_utc).days
            if wave1_days < min_wave1_days:
                continue
            min_wave1_high = max(
                anchor_low * (Decimal("1") + pivot_threshold_pct),
                anchor_low * (Decimal("1") + min_wave1_gain_pct),
            )
            if wave1_high < min_wave1_high:
                continue
            wave1_range = wave1_high - anchor_low
            if wave1_range <= 0:
                continue
            active_pairs.append(
                _PitPairState(
                    low_idx=low_idx,
                    high_idx=scan_idx,
                    anchor_low=anchor_low,
                    wave1_high=wave1_high,
                    wave1_range=wave1_range,
                    high_ts=scan_candle.open_ts_utc,
                )
            )

    return None


# ---------------------------------------------------------------------------
# § 6 / § 7 / § 8: single (asset, window, family, fraction) evaluation.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PitSymbolResult:
    symbol: str
    window: str
    target_family: str
    max_ladder_sell_fraction: Decimal
    status: str
    anchor_low_ts: Optional[datetime]
    wave1_high_ts: Optional[datetime]
    wave2_low_ts: Optional[datetime]
    confirmation_ts: Optional[datetime]
    entry_ts: Optional[datetime]
    entry_price: Optional[Decimal]
    total_return_pct_with_remaining: Optional[Decimal]
    hold_return_pct: Optional[Decimal]
    alpha_vs_hold_pct: Optional[Decimal]
    filled_rung_count: int
    sample_count: int
    peak_oracle_return_pct: Optional[Decimal]
    top_capture_ratio: Optional[Decimal]
    fills: tuple[Fill, ...]


def _empty_pit_result(
    symbol: str, window: str, target_family: str, max_ladder_sell_fraction: Decimal, status: str
) -> PitSymbolResult:
    return PitSymbolResult(
        symbol=symbol,
        window=window,
        target_family=target_family,
        max_ladder_sell_fraction=max_ladder_sell_fraction,
        status=status,
        anchor_low_ts=None,
        wave1_high_ts=None,
        wave2_low_ts=None,
        confirmation_ts=None,
        entry_ts=None,
        entry_price=None,
        total_return_pct_with_remaining=None,
        hold_return_pct=None,
        alpha_vs_hold_pct=None,
        filled_rung_count=0,
        sample_count=0,
        peak_oracle_return_pct=None,
        top_capture_ratio=None,
        fills=(),
    )


def evaluate_pit_symbol_window_config(
    symbol: str,
    window: str,
    window_candles: list[Candle],
    target_family: str,
    max_ladder_sell_fraction: Decimal,
) -> PitSymbolResult:
    """Pure single (asset, window, target_family, max_ladder_sell_fraction)
    PIT replay, per contract § 6/§ 7/§ 8. `window_candles` must already be
    filtered to the caller's chosen window (§ 4: anchor detection/
    confirmation for a window uses only candles inside that window)."""
    if target_family not in CANDIDATE_FAMILIES:
        raise ValueError(
            f"Invalid frozen target_family {target_family!r}; expected one of {CANDIDATE_FAMILIES}."
        )
    if max_ladder_sell_fraction not in SELL_FRACTION_GRID:
        raise ValueError(
            "Invalid frozen max_ladder_sell_fraction "
            f"{max_ladder_sell_fraction!r}; expected one of {SELL_FRACTION_GRID}."
        )

    if len(window_candles) < MIN_CANDLES_REQUIRED:
        return _empty_pit_result(symbol, window, target_family, max_ladder_sell_fraction, STATUS_INSUFFICIENT_CANDLES)

    anchor = find_pit_anchor(
        window_candles,
    )
    if anchor is None:
        return _empty_pit_result(symbol, window, target_family, max_ladder_sell_fraction, STATUS_NO_ANCHOR_SET_FOUND)

    future_candles = window_candles[anchor.entry_idx :]
    if not future_candles:
        return _empty_pit_result(symbol, window, target_family, max_ladder_sell_fraction, STATUS_NO_FUTURE_CANDLES)

    entry_price = anchor.entry_price
    end_candle = future_candles[-1]
    peak_candle = max(future_candles, key=lambda candle: candle.high_price)

    anchor_set = AnchorSet(
        anchor_low_ts=anchor.anchor_low_ts,
        anchor_low=anchor.anchor_low,
        wave1_high_ts=anchor.wave1_high_ts,
        wave1_high=anchor.wave1_high,
        wave2_low_ts=anchor.wave2_low_ts,
        wave2_low=anchor.wave2_low,
        wave1_range=anchor.wave1_range,
        method="pit_confirmed_reclaim",
    )
    targets = build_targets(
        anchor=anchor_set,
        target_family=target_family,
        max_ladder_sell_fraction=max_ladder_sell_fraction,
        target_zone_low_pct=DEFAULT_TARGET_ZONE_LOW_PCT,
        target_zone_high_pct=DEFAULT_TARGET_ZONE_HIGH_PCT,
    )
    rungs: list[Rung] = build_rungs(
        targets=targets,
        rungs_per_target=DEFAULT_RUNGS_PER_TARGET,
        front_run_pct=DEFAULT_FRONT_RUN_PCT,
        end_pct_of_zone_high=DEFAULT_END_PCT_OF_ZONE_HIGH,
        distribution=DEFAULT_DISTRIBUTION,
    )
    fills = simulate_fills(candles=future_candles, start_ts=anchor.entry_ts, rungs=rungs)

    filled_fraction = sum((fill.sell_fraction for fill in fills), Decimal("0"))
    if filled_fraction > Decimal("1"):
        filled_fraction = Decimal("1")
    remaining_fraction = Decimal("1") - filled_fraction

    realized_return = None
    if fills:
        realized_return = sum(
            (fill.sell_fraction * return_pct(fill.limit_price, entry_price) for fill in fills), Decimal("0")
        )

    remaining_return = remaining_fraction * return_pct(end_candle.close_price, entry_price)
    total_return = (realized_return or Decimal("0")) + remaining_return
    hold_return = return_pct(end_candle.close_price, entry_price)
    alpha = total_return - hold_return

    peak_oracle_return = return_pct(peak_candle.high_price, entry_price)
    top_capture = total_return / peak_oracle_return if peak_oracle_return != 0 else None

    return PitSymbolResult(
        symbol=symbol,
        window=window,
        target_family=target_family,
        max_ladder_sell_fraction=max_ladder_sell_fraction,
        status=STATUS_OK,
        anchor_low_ts=anchor.anchor_low_ts,
        wave1_high_ts=anchor.wave1_high_ts,
        wave2_low_ts=anchor.wave2_low_ts,
        confirmation_ts=anchor.confirmation_ts,
        entry_ts=anchor.entry_ts,
        entry_price=entry_price,
        total_return_pct_with_remaining=total_return,
        hold_return_pct=hold_return,
        alpha_vs_hold_pct=alpha,
        filled_rung_count=len(fills),
        sample_count=1,
        peak_oracle_return_pct=peak_oracle_return,
        top_capture_ratio=top_capture,
        fills=tuple(fills),
    )


def filter_candles_to_window(candles: list[Candle], window: tuple[str, str]) -> list[Candle]:
    """Candles with `from_ts <= open_ts_utc < to_ts`, per contract § 4."""
    from_ts = parse_datetime(window[0])
    to_ts = parse_datetime(window[1])
    return [candle for candle in candles if from_ts <= candle.open_ts_utc < to_ts]


# ---------------------------------------------------------------------------
# § 7: SELECTION_WINDOW-only selection, with fail-closed tie handling.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SelectedPolicy:
    symbol: str
    target_family: str
    max_ladder_sell_fraction: Decimal
    selection_metric_value: Decimal
    selection_sample_count: int


def _rank_grid_results(
    grid_results: dict[tuple[str, Decimal], PitSymbolResult],
    families: tuple[str, ...],
) -> list[tuple[tuple[str, Decimal], PitSymbolResult]]:
    """Deterministic ranking of OK grid combinations per contract § 7: by
    highest `total_return_pct_with_remaining`, tie-broken by (1) lower
    `max_ladder_sell_fraction`, then (2) family position in the frozen
    `families` order. Never falls back to dict/iteration order for a tie."""
    eligible = [
        (key, result)
        for key, result in grid_results.items()
        if result.status == STATUS_OK and result.total_return_pct_with_remaining is not None
    ]

    def sort_key(item: tuple[tuple[str, Decimal], PitSymbolResult]) -> tuple[Decimal, Decimal, int]:
        (family, fraction), result = item
        assert result.total_return_pct_with_remaining is not None
        return (-result.total_return_pct_with_remaining, fraction, families.index(family))

    return sorted(eligible, key=sort_key)


def select_policy_on_selection_window(
    symbol: str,
    selection_window_candles: list[Candle],
) -> tuple[Optional[SelectedPolicy], dict[tuple[str, Decimal], PitSymbolResult]]:
    """§ 7 selection: evaluates the full frozen grid on SELECTION_WINDOW
    candles only (the caller passes already-window-filtered candles; this
    function never touches OOS data because it is never given any), ranks
    the OK combinations, and returns the single selected policy plus every
    grid row for provenance (§ 11). Returns `(None, grid_results)` —
    INSUFFICIENT_DATA — if no grid combination confirmed a PIT anchor in
    this window (§ 7 minimum sample requirement)."""
    grid_results: dict[tuple[str, Decimal], PitSymbolResult] = {}
    for family in CANDIDATE_FAMILIES:
        for fraction in SELL_FRACTION_GRID:
            grid_results[(family, fraction)] = evaluate_pit_symbol_window_config(
                symbol=symbol,
                window="SELECTION_WINDOW",
                window_candles=selection_window_candles,
                target_family=family,
                max_ladder_sell_fraction=fraction,
            )

    ranked = _rank_grid_results(grid_results, CANDIDATE_FAMILIES)
    if not ranked:
        return None, grid_results

    (best_family, best_fraction), best_result = ranked[0]
    assert best_result.total_return_pct_with_remaining is not None
    selected = SelectedPolicy(
        symbol=symbol,
        target_family=best_family,
        max_ladder_sell_fraction=best_fraction,
        selection_metric_value=best_result.total_return_pct_with_remaining,
        selection_sample_count=best_result.sample_count,
    )
    return selected, grid_results


# ---------------------------------------------------------------------------
# § 8: OOS evaluation. Structurally cannot retune: this function's signature
# accepts only one already-frozen `SelectedPolicy`, never the candidate grid
# or a set of competing configs, so there is no data path by which an OOS
# result could influence which config gets evaluated.
# ---------------------------------------------------------------------------


def evaluate_oos_window(
    selected: SelectedPolicy,
    oos_window_label: str,
    oos_window_candles: list[Candle],
) -> PitSymbolResult:
    """§ 8 OOS evaluation for one already-selected, frozen policy. Takes no
    `families`/`fractions` grid argument and no other symbol's or window's
    results — it cannot inspect or rank competing configs because none are
    reachable from this call."""
    return evaluate_pit_symbol_window_config(
        symbol=selected.symbol,
        window=oos_window_label,
        window_candles=oos_window_candles,
        target_family=selected.target_family,
        max_ladder_sell_fraction=selected.max_ladder_sell_fraction,
    )


@dataclass(frozen=True)
class PitSymbolReplayResult:
    symbol: str
    selected_policy: Optional[SelectedPolicy]
    selection_grid_results: dict[tuple[str, Decimal], PitSymbolResult]
    oos_window_1_result: Optional[PitSymbolResult]
    oos_window_2_result: Optional[PitSymbolResult]


def run_pit_replay_for_symbol(
    symbol: str,
    selection_window_candles: list[Candle],
    oos_window_1_candles: list[Candle],
    oos_window_2_candles: list[Candle],
) -> PitSymbolReplayResult:
    """Orchestrates § 7 selection followed by § 8 OOS evaluation for one
    symbol. Selection is computed exactly once, before either OOS window is
    evaluated (§ 4 no-retuning rule); each OOS window is evaluated only
    through `evaluate_oos_window`, which cannot retune (see above)."""
    selected, grid_results = select_policy_on_selection_window(
        symbol=symbol,
        selection_window_candles=selection_window_candles,
    )

    if selected is None:
        return PitSymbolReplayResult(
            symbol=symbol,
            selected_policy=None,
            selection_grid_results=grid_results,
            oos_window_1_result=None,
            oos_window_2_result=None,
        )

    oos1 = evaluate_oos_window(selected, "OOS_WINDOW_1", oos_window_1_candles)
    oos2 = evaluate_oos_window(selected, "OOS_WINDOW_2", oos_window_2_candles)

    return PitSymbolReplayResult(
        symbol=symbol,
        selected_policy=selected,
        selection_grid_results=grid_results,
        oos_window_1_result=oos1,
        oos_window_2_result=oos2,
    )