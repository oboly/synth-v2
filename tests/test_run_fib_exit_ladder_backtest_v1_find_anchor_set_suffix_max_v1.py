"""Equivalence tests for Issue #691: find_anchor_set() suffix-max optimization.

run_fib_exit_ladder_backtest_v1.find_anchor_set() replaced its repeated
    max(candle.high_price for candle in candles[wave2_idx + 1:])
suffix scan (O(n) per wave2_idx, O(n) times per (low_idx, high_idx) pair,
so O(n) work repeated inside a triple-nested loop) with a single O(n)
precomputed suffix-maximum array and O(1) lookups.

This module keeps a test-local reference implementation that reproduces the
*original* suffix-scan behavior verbatim (same iteration order, same
eligibility checks, same expansion/score math, same first-winner tie
behavior) and proves it returns identical results to the optimized
production implementation across representative cases, including no
candidate, one candidate, multiple candidates, and an exact score tie.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from src.research import run_fib_exit_ladder_backtest_v1 as ladder_bt

Candle = ladder_bt.Candle
AnchorSet = ladder_bt.AnchorSet


def _candle(days: int, open_price: str, high: str, low: str, close: str) -> Candle:
    base = datetime(2020, 1, 1)
    return Candle(
        open_ts_utc=base + timedelta(days=days),
        open_price=Decimal(open_price),
        high_price=Decimal(high),
        low_price=Decimal(low),
        close_price=Decimal(close),
    )


def reference_find_anchor_set(
    candles: list[Candle],
    pivot_threshold_pct: Decimal,
    min_wave1_gain_pct: Decimal,
    min_wave1_days: int,
    min_wave2_days_after_high: int,
    wave2_min_retrace: Decimal,
    wave2_max_retrace: Decimal,
) -> Optional[AnchorSet]:
    """Verbatim pre-optimization reference: repeated suffix max() scan."""
    if len(candles) < 20:
        return None

    best: Optional[AnchorSet] = None
    best_score: Optional[Decimal] = None

    for low_idx in range(0, max(1, len(candles) - 10)):
        anchor_low = candles[low_idx].low_price
        if anchor_low <= 0:
            continue

        min_wave1_high = max(
            anchor_low * (Decimal("1") + pivot_threshold_pct),
            anchor_low * (Decimal("1") + min_wave1_gain_pct),
        )

        for high_idx in range(low_idx + 1, len(candles) - 5):
            wave1_days = (candles[high_idx].open_ts_utc - candles[low_idx].open_ts_utc).days
            if wave1_days < min_wave1_days:
                continue

            wave1_high = candles[high_idx].high_price
            if wave1_high < min_wave1_high:
                continue

            wave1_range = wave1_high - anchor_low
            if wave1_range <= 0:
                continue

            for wave2_idx in range(high_idx + 1, len(candles) - 1):
                wave2_days_after_high = (candles[wave2_idx].open_ts_utc - candles[high_idx].open_ts_utc).days
                if wave2_days_after_high < min_wave2_days_after_high:
                    continue

                wave2_low = candles[wave2_idx].low_price

                if wave2_low <= anchor_low:
                    continue
                if wave2_low >= wave1_high:
                    continue

                retrace = (wave1_high - wave2_low) / wave1_range
                if retrace < wave2_min_retrace or retrace > wave2_max_retrace:
                    continue

                future_high = max(candle.high_price for candle in candles[wave2_idx + 1 :])
                if future_high <= wave1_high:
                    continue

                expansion = (future_high - wave2_low) / wave1_range
                score = expansion

                if best is None or best_score is None or score > best_score:
                    best = AnchorSet(
                        anchor_low_ts=candles[low_idx].open_ts_utc,
                        anchor_low=anchor_low,
                        wave1_high_ts=candles[high_idx].open_ts_utc,
                        wave1_high=wave1_high,
                        wave2_low_ts=candles[wave2_idx].open_ts_utc,
                        wave2_low=wave2_low,
                        wave1_range=wave1_range,
                        method="deterministic_low_high_retrace_expansion",
                    )
                    best_score = score

    return best


DEFAULT_KWARGS = dict(
    pivot_threshold_pct=Decimal("0.25"),
    min_wave1_gain_pct=Decimal("1.00"),
    min_wave1_days=14,
    min_wave2_days_after_high=3,
    wave2_min_retrace=Decimal("0.236"),
    wave2_max_retrace=Decimal("0.886"),
)


def _assert_equivalent(candles: list[Candle], **overrides: object) -> Optional[AnchorSet]:
    kwargs = dict(DEFAULT_KWARGS, **overrides)
    expected = reference_find_anchor_set(candles, **kwargs)
    actual = ladder_bt.find_anchor_set(candles, **kwargs)
    assert actual == expected
    return actual


def _synthetic_candles_with_two_candidates() -> list[Candle]:
    """Rally -> wave1 -> two separate wave2 retrace/expansion candidates.

    The second (later) wave2 low gets a larger future expansion, so it
    should win on score even though it is found later in iteration order.
    """
    candles = [_candle(0, "1.00", "1.00", "0.90", "0.95")]
    for day in range(1, 20):
        price = Decimal("0.90") + (Decimal("1.00") * day / Decimal("19"))
        candles.append(_candle(day, str(price), str(price + Decimal("0.02")), str(price - Decimal("0.02")), str(price)))
    candles.append(_candle(20, "1.90", "2.00", "1.85", "1.95"))  # wave1 high

    # First wave2 retrace candidate, days 21-25.
    for day in range(21, 25):
        candles.append(_candle(day, "1.60", "1.65", "1.55", "1.58"))
    candles.append(_candle(25, "1.30", "1.35", "1.20", "1.25"))  # wave2 low candidate #1

    # Partial recovery, then a second deeper wave2 retrace candidate.
    for day in range(26, 40):
        candles.append(_candle(day, "1.70", "1.75", "1.65", "1.72"))
    for day in range(40, 44):
        candles.append(_candle(day, "1.55", "1.60", "1.50", "1.52"))
    candles.append(_candle(44, "1.28", "1.33", "1.15", "1.20"))  # wave2 low candidate #2

    # Strong future expansion after candidate #2, well above candidate #1's expansion.
    for day in range(45, 90):
        price = Decimal("1.20") + (Decimal("6.00") * (day - 44) / Decimal("45"))
        candles.append(_candle(day, str(price), str(price + Decimal("0.05")), str(price - Decimal("0.05")), str(price)))
    return candles


def _synthetic_candles_no_anchor() -> list[Candle]:
    """Flat/choppy series with no wave1 gain large enough to ever qualify."""
    candles = []
    for day in range(0, 40):
        candles.append(_candle(day, "1.00", "1.02", "0.98", "1.00"))
    return candles


def _synthetic_candles_score_tie() -> list[Candle]:
    """Two distinct wave2 low candidates that produce an exact tied score.

    Because both wave1_range and post-wave2 max are shared (single flat
    future_high applies to both, since they are computed over overlapping
    suffixes), we instead construct two low/high/wave2 anchor triples that
    are independent of each other but happen to produce identical
    expansion scores, to exercise first-winner tie behavior.
    """
    candles = [_candle(0, "1.00", "1.00", "0.90", "0.95")]
    for day in range(1, 20):
        price = Decimal("0.90") + (Decimal("1.00") * day / Decimal("19"))
        candles.append(_candle(day, str(price), str(price + Decimal("0.02")), str(price - Decimal("0.02")), str(price)))
    candles.append(_candle(20, "1.90", "2.00", "1.85", "1.95"))  # wave1 high

    # Two adjacent wave2 low candidates with identical low_price -> identical
    # retrace, expansion, and score (since future_high suffix is the same
    # or later for the second one, but we equalize by giving both an
    # identical low and letting the shared tail dominate future_high).
    for day in range(21, 24):
        candles.append(_candle(day, "1.60", "1.65", "1.55", "1.58"))
    candles.append(_candle(24, "1.30", "1.35", "1.20", "1.25"))  # wave2 candidate A
    candles.append(_candle(25, "1.45", "1.50", "1.20", "1.40"))  # low equal to A, candidate B

    for day in range(26, 60):
        price = Decimal("1.25") + (Decimal("3.00") * (day - 25) / Decimal("34"))
        candles.append(_candle(day, str(price), str(price + Decimal("0.05")), str(price - Decimal("0.05")), str(price)))
    return candles


def test_no_anchor_candidate_reference_matches_optimized() -> None:
    candles = _synthetic_candles_no_anchor()
    result = _assert_equivalent(candles)
    assert result is None


def test_one_valid_candidate_reference_matches_optimized() -> None:
    candles = [_candle(0, "1.00", "1.00", "0.90", "0.95")]
    for day in range(1, 20):
        price = Decimal("0.90") + (Decimal("1.00") * day / Decimal("19"))
        candles.append(_candle(day, str(price), str(price + Decimal("0.02")), str(price - Decimal("0.02")), str(price)))
    candles.append(_candle(20, "1.90", "2.00", "1.85", "1.95"))
    for day in range(21, 25):
        candles.append(_candle(day, "1.60", "1.65", "1.55", "1.58"))
    candles.append(_candle(25, "1.30", "1.35", "1.20", "1.25"))
    for day in range(26, 60):
        price = Decimal("1.25") + (Decimal("3.00") * (day - 25) / Decimal("34"))
        candles.append(_candle(day, str(price), str(price + Decimal("0.05")), str(price - Decimal("0.05")), str(price)))

    result = _assert_equivalent(candles)
    assert result is not None
    assert result.wave2_low_ts == datetime(2020, 1, 1) + timedelta(days=25)


def test_multiple_candidates_reference_matches_optimized_and_picks_higher_score() -> None:
    candles = _synthetic_candles_with_two_candidates()
    result = _assert_equivalent(candles)
    assert result is not None
    # Candidate #2 (day 44) has the larger future expansion and should win.
    assert result.wave2_low_ts == datetime(2020, 1, 1) + timedelta(days=44)


def test_score_tie_reference_matches_optimized_first_winner_semantics() -> None:
    candles = _synthetic_candles_score_tie()

    expected = reference_find_anchor_set(candles, **DEFAULT_KWARGS)
    actual = ladder_bt.find_anchor_set(candles, **DEFAULT_KWARGS)

    assert actual == expected
    # Whatever the tie/near-tie outcome, both implementations must agree
    # exactly, including which anchor (found first in iteration order)
    # wins when scores are equal (score > best_score is strict, so an
    # exact tie keeps the earlier winner).
    if expected is not None:
        assert actual.wave2_low_ts == expected.wave2_low_ts
        assert actual.wave1_high_ts == expected.wave1_high_ts
        assert actual.anchor_low_ts == expected.anchor_low_ts


def test_representative_deterministic_series_reference_matches_optimized() -> None:
    candles = _synthetic_candles_with_two_candidates()
    result = _assert_equivalent(
        candles,
        pivot_threshold_pct=Decimal("0.30"),
        min_wave1_gain_pct=Decimal("0.80"),
        min_wave1_days=10,
        min_wave2_days_after_high=2,
        wave2_min_retrace=Decimal("0.20"),
        wave2_max_retrace=Decimal("0.90"),
    )
    assert result is not None


def test_short_candle_series_below_minimum_returns_none_both_implementations() -> None:
    candles = [_candle(day, "1.00", "1.05", "0.95", "1.00") for day in range(5)]
    result = _assert_equivalent(candles)
    assert result is None
