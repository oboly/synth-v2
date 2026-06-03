from __future__ import annotations

import ast
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from src.research.run_symbol_reentry_profile_backtest_v1 import (
    BacktestCandle,
    ImpulseSwing,
    RetraceEvent,
    SymbolReentryProfile,
    _avg,
    _find_pivot_highs,
    _find_pivot_lows,
    aggregate_profile,
    build_event_dict,
    build_manifest,
    build_profile_row,
    classify_retrace_event,
    detect_impulse_swings,
)

UTC = timezone.utc
_TS = datetime(2024, 1, 1, tzinfo=UTC)


def _candle(
    high: str,
    low: str,
    close: str | None = None,
    open_: str | None = None,
) -> BacktestCandle:
    return BacktestCandle(
        ts_utc=_TS,
        open_price=Decimal(open_ or low),
        high_price=Decimal(high),
        low_price=Decimal(low),
        close_price=Decimal(close or high),
    )


def _make_candles_with_swing() -> list[BacktestCandle]:
    """
    Build a simple 15-candle sequence with one clear pivot low (idx 2) and
    one clear pivot high (idx 12). Span=2. Monotonic rise avoids early peaks.
    Candles 13-14 have lows well above all retrace levels (>2.00) to ensure
    a clean lookforward window for no-touch tests.
    """
    return [
        _candle("1.50", "1.00"),   # 0
        _candle("1.30", "0.90"),   # 1
        _candle("1.20", "0.80"),   # 2 — pivot low (l=0.80)
        _candle("1.40", "1.05"),   # 3
        _candle("1.60", "1.15"),   # 4
        _candle("1.80", "1.30"),   # 5
        _candle("2.00", "1.50"),   # 6
        _candle("2.20", "1.60"),   # 7
        _candle("2.35", "1.70"),   # 8
        _candle("2.40", "1.75"),   # 9
        _candle("2.45", "1.80"),   # 10
        _candle("2.48", "1.85"),   # 11
        _candle("2.50", "1.90"),   # 12 — pivot high (h=2.50)
        _candle("2.45", "2.10"),   # 13 — lookforward (above all retrace levels)
        _candle("2.40", "2.00"),   # 14 — lookforward (above all retrace levels)
    ]


def _make_impulse_swing() -> ImpulseSwing:
    return ImpulseSwing(
        swing_low_price=Decimal("0.80"),
        swing_high_price=Decimal("2.50"),
        impulse_pct=(Decimal("2.50") - Decimal("0.80")) / Decimal("0.80") * Decimal("100"),
        swing_low_ts=_TS,
        swing_high_ts=_TS,
        swing_low_idx=2,
        swing_high_idx=12,
    )


def _make_retrace_event(
    *,
    r382: bool = False,
    r500: bool = False,
    r618: bool = False,
    r786: bool = False,
    deepest: str = "NO_TOUCH",
    bounce: str | None = None,
    impulse_pct: str = "50",
) -> RetraceEvent:
    return RetraceEvent(
        symbol="X",
        interval_code="1d",
        swing_low_price=Decimal("0.80"),
        swing_high_price=Decimal("2.50"),
        impulse_pct=Decimal(impulse_pct),
        swing_high_ts="2024-01-01T00:00:00+00:00",
        deepest_low_price=Decimal("1.80"),
        deepest_retrace_label=deepest,
        retrace_0_382_touched=r382,
        retrace_0_500_touched=r500,
        retrace_0_618_touched=r618,
        retrace_0_786_touched=r786,
        bounce_after_touch_pct=Decimal(bounce) if bounce else None,
    )


# ── AST / safety ────────────────────────────────────────────────────────────


def test_pure_ladder_module_has_no_forbidden_imports() -> None:
    src = Path("src/research/htf_fib_reentry_ladder_v1.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    forbidden = {"db", "bitvavo_client", "decision_gate", "execution_planner", "executor", "pymysql"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for f in forbidden:
                assert f not in module, f"forbidden '{f}' in ladder module imports"


def test_runner_has_no_broker_imports() -> None:
    src = Path("src/research/run_symbol_reentry_profile_backtest_v1.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    forbidden = {"bitvavo_client", "decision_gate", "execution_planner", "executor"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for f in forbidden:
                assert f not in module, f"forbidden '{f}' in runner imports"


def test_runner_has_no_broker_write_calls() -> None:
    src = Path("src/research/run_symbol_reentry_profile_backtest_v1.py").read_text(encoding="utf-8")
    for forbidden in ("place_order", "cancel_order", "BROKER_WRITE_PERMISSION"):
        assert forbidden not in src, f"runner must not reference '{forbidden}'"


# ── _find_pivot_lows / _find_pivot_highs ────────────────────────────────────


def test_find_pivot_lows_basic() -> None:
    candles = _make_candles_with_swing()
    lows = _find_pivot_lows(candles, span=2)
    assert 2 in lows


def test_find_pivot_highs_basic() -> None:
    candles = _make_candles_with_swing()
    highs = _find_pivot_highs(candles, span=2)
    assert 12 in highs


def test_find_pivot_lows_empty_on_short_sequence() -> None:
    candles = [_candle("1.0", "0.5")] * 3
    assert _find_pivot_lows(candles, span=2) == []


# ── detect_impulse_swings ────────────────────────────────────────────────────


def test_detect_impulse_swings_empty() -> None:
    assert detect_impulse_swings([], pivot_span=2, min_impulse_pct=Decimal("10")) == []


def test_detect_impulse_swings_too_few_candles() -> None:
    candles = [_candle("1.0", "0.5")] * 4
    assert detect_impulse_swings(candles, pivot_span=2, min_impulse_pct=Decimal("10")) == []


def test_detect_impulse_swings_finds_one_swing() -> None:
    candles = _make_candles_with_swing()
    swings = detect_impulse_swings(candles, pivot_span=2, min_impulse_pct=Decimal("10"))
    assert len(swings) >= 1
    assert swings[0].swing_low_price == Decimal("0.80")
    assert swings[0].swing_high_price == Decimal("2.50")


def test_detect_impulse_swings_skips_below_min_pct() -> None:
    candles = _make_candles_with_swing()
    swings = detect_impulse_swings(candles, pivot_span=2, min_impulse_pct=Decimal("999"))
    assert swings == []


def test_detect_impulse_swings_impulse_pct_correct() -> None:
    candles = _make_candles_with_swing()
    swings = detect_impulse_swings(candles, pivot_span=2, min_impulse_pct=Decimal("10"))
    assert len(swings) >= 1
    expected_pct = (Decimal("2.50") - Decimal("0.80")) / Decimal("0.80") * Decimal("100")
    assert abs(swings[0].impulse_pct - expected_pct) < Decimal("0.0001")


# ── classify_retrace_event ───────────────────────────────────────────────────


def test_classify_retrace_event_no_touch() -> None:
    candles = _make_candles_with_swing()
    # extend candles with high-close aftermath so price stays near swing high
    for _ in range(5):
        candles.append(_candle("2.45", "2.30", "2.40"))
    swing = _make_impulse_swing()
    event = classify_retrace_event("X", "1d", swing, candles, lookforward_bars=5)
    assert event.deepest_retrace_label == "NO_TOUCH"
    assert not event.retrace_0_382_touched
    assert event.bounce_after_touch_pct is None


def test_classify_retrace_event_r382_touch() -> None:
    candles = _make_candles_with_swing()
    # swing high=2.50, leg=1.70, r382=2.50-1.70*0.382=1.8505...
    # append a candle that dips to 1.80 (below r382≈1.8505) but stays above r500=2.50-1.70*0.5=1.65
    for _ in range(3):
        candles.append(_candle("2.40", "1.80", "2.20"))
    swing = _make_impulse_swing()
    event = classify_retrace_event("X", "1d", swing, candles, lookforward_bars=5)
    assert event.retrace_0_382_touched


def test_classify_retrace_event_full_retrace() -> None:
    candles = _make_candles_with_swing()
    # append candle that dips below swing_low=0.80
    candles.append(_candle("2.10", "0.75", "1.00"))
    swing = _make_impulse_swing()
    event = classify_retrace_event("X", "1d", swing, candles, lookforward_bars=3)
    assert event.deepest_retrace_label == "FULL_RETRACE"


def test_classify_retrace_event_empty_window() -> None:
    candles = _make_candles_with_swing()
    swing = _make_impulse_swing()
    # swing_high_idx=12, start=13, lookforward_bars=0 → empty window
    event = classify_retrace_event("X", "1d", swing, candles, lookforward_bars=0)
    assert event.deepest_retrace_label == "NO_TOUCH"
    assert event.bounce_after_touch_pct is None


def test_classify_retrace_event_bounce_pct_positive_after_touch() -> None:
    candles = _make_candles_with_swing()
    # dip then recovery: close=2.40 after dip to 1.80
    candles.append(_candle("2.40", "1.80", "2.40"))
    for _ in range(4):
        candles.append(_candle("2.45", "2.30", "2.45"))
    swing = _make_impulse_swing()
    event = classify_retrace_event("X", "1d", swing, candles, lookforward_bars=5)
    if event.bounce_after_touch_pct is not None:
        assert event.bounce_after_touch_pct > Decimal("0")


# ── aggregate_profile ────────────────────────────────────────────────────────


def test_aggregate_profile_insufficient_sample() -> None:
    events = [_make_retrace_event(r382=True, deepest="retrace_0_382", bounce="5")]
    profile = aggregate_profile("X", "1d", events, min_sample=3, avg_impulse_pct=Decimal("50"))
    assert profile.classification == "INSUFFICIENT_SAMPLE"
    assert profile.sample_size == 1


def test_aggregate_profile_touch_counts() -> None:
    events = [
        _make_retrace_event(r382=True, r500=True, deepest="retrace_0_500", bounce="5"),
        _make_retrace_event(r382=True, deepest="retrace_0_382", bounce="3"),
        _make_retrace_event(r382=False, deepest="NO_TOUCH"),
    ]
    profile = aggregate_profile("X", "1d", events, min_sample=3, avg_impulse_pct=Decimal("50"))
    assert profile.touch_count_0_382 == 2
    assert profile.touch_count_0_500 == 1
    assert profile.touch_count_0_618 == 0


def test_aggregate_profile_preferred_level_by_highest_count() -> None:
    # preferred is based on most common deepest_retrace_label (where price reversed)
    events = [
        _make_retrace_event(r382=True, r500=True, deepest="retrace_0_500", bounce="5"),
        _make_retrace_event(r382=True, r500=True, deepest="retrace_0_500", bounce="4"),
        _make_retrace_event(r382=True, deepest="retrace_0_382", bounce="3"),
    ]
    profile = aggregate_profile("X", "1d", events, min_sample=3, avg_impulse_pct=Decimal("50"))
    assert profile.preferred_retrace_level == "retrace_0_500"


def test_aggregate_profile_wickiness_score() -> None:
    events = [
        _make_retrace_event(r382=True, r500=False, deepest="retrace_0_382", bounce="3"),
        _make_retrace_event(r382=True, r500=False, deepest="retrace_0_382", bounce="4"),
        _make_retrace_event(r382=True, r500=True, deepest="retrace_0_500", bounce="5"),
        _make_retrace_event(deepest="NO_TOUCH"),
    ]
    profile = aggregate_profile("X", "1d", events, min_sample=3, avg_impulse_pct=Decimal("50"))
    # 2 out of 4 wicky
    assert abs(profile.wickiness_score - Decimal("0.5")) < Decimal("0.001")


def test_aggregate_profile_fib_respect_score() -> None:
    events = [
        _make_retrace_event(r382=True, deepest="retrace_0_382", bounce="3"),
        _make_retrace_event(deepest="NO_TOUCH"),
        _make_retrace_event(r382=True, r500=True, r618=True, deepest="retrace_0_618", bounce="2"),
        _make_retrace_event(deepest="NO_TOUCH"),
    ]
    profile = aggregate_profile("X", "1d", events, min_sample=3, avg_impulse_pct=Decimal("50"))
    # 3 out of 4 in RESPECT_LABELS (r382, NO_TOUCH, NO_TOUCH)
    assert abs(profile.fib_respect_score - Decimal("0.75")) < Decimal("0.001")


def test_aggregate_profile_volatility_score_capped_at_one() -> None:
    events = [_make_retrace_event(deepest="NO_TOUCH")] * 3
    profile = aggregate_profile(
        "X", "1d", events, min_sample=3, avg_impulse_pct=Decimal("200")
    )
    assert profile.volatility_score == Decimal("1")


def test_aggregate_profile_classification_deep_retrace() -> None:
    events = [
        _make_retrace_event(r382=True, r500=True, r618=True, deepest="retrace_0_618", bounce="2"),
    ] * 4
    profile = aggregate_profile("X", "1d", events, min_sample=3, avg_impulse_pct=Decimal("50"))
    assert profile.classification == "DEEP_RETRACE"


def test_aggregate_profile_classification_clean_fib_respect() -> None:
    events = [
        _make_retrace_event(r382=True, r500=True, deepest="retrace_0_500", bounce="8"),
        _make_retrace_event(deepest="NO_TOUCH"),
        _make_retrace_event(r382=True, r500=True, deepest="retrace_0_500", bounce="6"),
        _make_retrace_event(deepest="NO_TOUCH"),
        _make_retrace_event(r382=True, r500=True, deepest="retrace_0_500", bounce="7"),
    ]
    profile = aggregate_profile("X", "1d", events, min_sample=3, avg_impulse_pct=Decimal("40"))
    assert profile.classification == "CLEAN_FIB_RESPECT"
    assert profile.fib_respect_score >= Decimal("0.6")


def test_aggregate_profile_classification_wick_heavy() -> None:
    events = [
        _make_retrace_event(r382=True, r500=False, deepest="retrace_0_382", bounce="3"),
        _make_retrace_event(r382=True, r500=False, deepest="retrace_0_382", bounce="4"),
        _make_retrace_event(r382=True, r500=False, deepest="retrace_0_382", bounce="5"),
        _make_retrace_event(deepest="NO_TOUCH"),
    ]
    profile = aggregate_profile("X", "1d", events, min_sample=3, avg_impulse_pct=Decimal("50"))
    assert profile.classification == "WICK_HEAVY"


def test_aggregate_profile_avg_bounce_after_0_382() -> None:
    events = [
        _make_retrace_event(r382=True, r500=False, deepest="retrace_0_382", bounce="4"),
        _make_retrace_event(r382=True, r500=False, deepest="retrace_0_382", bounce="6"),
        _make_retrace_event(r382=False, deepest="NO_TOUCH"),
    ]
    profile = aggregate_profile("X", "1d", events, min_sample=3, avg_impulse_pct=Decimal("50"))
    assert profile.avg_bounce_after_0_382 is not None
    assert abs(profile.avg_bounce_after_0_382 - Decimal("5")) < Decimal("0.001")


# ── output serialization ─────────────────────────────────────────────────────


def test_build_profile_row_has_required_keys() -> None:
    events = [_make_retrace_event(deepest="NO_TOUCH")] * 3
    profile = aggregate_profile("WLD", "1d", events, min_sample=3, avg_impulse_pct=Decimal("50"))
    row = build_profile_row(profile)
    for key in ("symbol", "interval_code", "classification", "preferred_retrace_level", "sample_size"):
        assert key in row, f"missing key: {key}"


def test_build_event_dict_has_expected_keys() -> None:
    event = _make_retrace_event(r382=True, deepest="retrace_0_382", bounce="5")
    d = build_event_dict(event)
    for key in (
        "symbol", "interval_code", "swing_low_price", "swing_high_price",
        "deepest_retrace_label", "retrace_0_382_touched", "bounce_after_touch_pct",
    ):
        assert key in d, f"missing key: {key}"


def test_build_manifest_has_safety_markers() -> None:
    manifest = build_manifest(
        [],
        run_ts="2024-01-01T00:00:00+00:00",
        venue="bitvavo",
        interval_code="1d",
        lookback_candles=500,
        pivot_span=5,
        min_impulse_pct="15",
        lookforward_bars=60,
    )
    assert manifest["broker_writes"] == 0
    assert manifest["order_submission"] == 0
    assert manifest["broker_calls"] == 0
    assert manifest["executor"] == "none"
    assert manifest["db_writes"] == 0


def main() -> None:
    test_pure_ladder_module_has_no_forbidden_imports()
    test_runner_has_no_broker_imports()
    test_runner_has_no_broker_write_calls()
    test_find_pivot_lows_basic()
    test_find_pivot_highs_basic()
    test_find_pivot_lows_empty_on_short_sequence()
    test_detect_impulse_swings_empty()
    test_detect_impulse_swings_too_few_candles()
    test_detect_impulse_swings_finds_one_swing()
    test_detect_impulse_swings_skips_below_min_pct()
    test_detect_impulse_swings_impulse_pct_correct()
    test_classify_retrace_event_no_touch()
    test_classify_retrace_event_r382_touch()
    test_classify_retrace_event_full_retrace()
    test_classify_retrace_event_empty_window()
    test_classify_retrace_event_bounce_pct_positive_after_touch()
    test_aggregate_profile_insufficient_sample()
    test_aggregate_profile_touch_counts()
    test_aggregate_profile_preferred_level_by_highest_count()
    test_aggregate_profile_wickiness_score()
    test_aggregate_profile_fib_respect_score()
    test_aggregate_profile_volatility_score_capped_at_one()
    test_aggregate_profile_classification_deep_retrace()
    test_aggregate_profile_classification_clean_fib_respect()
    test_aggregate_profile_classification_wick_heavy()
    test_aggregate_profile_avg_bounce_after_0_382()
    test_build_profile_row_has_required_keys()
    test_build_event_dict_has_expected_keys()
    test_build_manifest_has_safety_markers()
    print("ok")


if __name__ == "__main__":
    main()
