from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from src.market_data.fib_navigation_map_v1 import (
    DIRECTION_BEARISH,
    DIRECTION_BULLISH,
    MAP_STATE_EMERGENCY_REBUILT,
    MAP_STATE_FALLBACK,
    MAP_STATE_FRESH,
    MAP_STATE_NO_DATA,
    MAP_STATE_STALE,
    TRIGGER_ALL_TARGETS_PASSED,
    TRIGGER_MAP_EXHAUSTED,
    TRIGGER_MAP_MISSING,
    TRIGGER_MAP_STALE,
    TRIGGER_NONE,
    FibNavCandle,
    FibNavigationMap,
    PriorMapMeta,
    _build_levels,
    build_fib_navigation_map,
)


# ---------------------------------------------------------------------------
# Candle factory helpers
# ---------------------------------------------------------------------------

def _ts(offset_minutes: int = 0) -> datetime:
    base = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    return base + timedelta(minutes=offset_minutes * 15)


def _candle(
    *,
    offset: int,
    low: str,
    high: str,
    open_: str | None = None,
    close: str | None = None,
    volume: str = "1000",
) -> FibNavCandle:
    l = Decimal(low)
    h = Decimal(high)
    o = Decimal(open_) if open_ else (l + h) / 2
    c = Decimal(close) if close else (l + h) / 2
    return FibNavCandle(
        close_ts_utc=_ts(offset),
        open_price=o,
        high_price=h,
        low_price=l,
        close_price=c,
        volume=Decimal(volume),
    )


def _sxt_candles() -> list[FibNavCandle]:
    """
    11 candles (15m) containing the SXT swing:
      pivot low  at index 3: low=0.006571
      pivot high at index 7: high=0.010127
      current close at index 10: ~0.009588

    With pivot_span=3:
      - c[3] is pivot low:  min of c[0..6].low = 0.006571
      - c[7] is pivot high: max of c[4..10].high = 0.010127
    """
    return [
        _candle(offset=0,  low="0.009000", high="0.010000"),
        _candle(offset=1,  low="0.008000", high="0.009000"),
        _candle(offset=2,  low="0.007000", high="0.008000"),
        _candle(offset=3,  low="0.006571", high="0.007000"),   # pivot low
        _candle(offset=4,  low="0.007000", high="0.008000"),
        _candle(offset=5,  low="0.008000", high="0.009000"),
        _candle(offset=6,  low="0.009000", high="0.009500"),
        _candle(offset=7,  low="0.009000", high="0.010127"),   # pivot high
        _candle(offset=8,  low="0.009000", high="0.009500"),
        _candle(offset=9,  low="0.008900", high="0.009500"),
        _candle(offset=10, low="0.009000", high="0.009600", close="0.009588"),
    ]


def _now_fresh() -> datetime:
    return _ts(10) + timedelta(minutes=1)


def _exhausted_prior(direction: str = DIRECTION_BULLISH) -> PriorMapMeta:
    from src.market_data.fib_navigation_map_v1 import MAP_STATE_EXHAUSTED
    return PriorMapMeta(
        map_state=MAP_STATE_EXHAUSTED,
        anchor_low=Decimal("0.005000"),
        anchor_high=Decimal("0.008000"),
        direction=direction,
        top_extension_price=Decimal("0.020000"),
        candle_ts_utc=_ts(0),
    )


# ---------------------------------------------------------------------------
# 1. SXT bullish emergency rebuild
# ---------------------------------------------------------------------------

_TOLERANCE = Decimal("0.000010")


def test_sxt_bullish_emergency_rebuild_state() -> None:
    candles = _sxt_candles()
    result = build_fib_navigation_map(
        candles=candles,
        current_price=Decimal("0.009588"),
        now_utc=_now_fresh(),
        prior=_exhausted_prior(),
        direction=DIRECTION_BULLISH,
    )
    assert result.map_state in {MAP_STATE_EMERGENCY_REBUILT, MAP_STATE_FALLBACK}, (
        f"Expected EMERGENCY_REBUILT or FALLBACK, got {result.map_state}"
    )
    assert result.rebuild_trigger in {TRIGGER_MAP_EXHAUSTED, TRIGGER_ALL_TARGETS_PASSED}
    assert len(result.retracement_levels) > 0, "Must not collapse to no levels"
    assert len(result.extension_levels) > 0, "Must not collapse to no levels"


def test_sxt_retracement_levels() -> None:
    candles = _sxt_candles()
    result = build_fib_navigation_map(
        candles=candles,
        current_price=Decimal("0.009588"),
        now_utc=_now_fresh(),
        prior=_exhausted_prior(),
        direction=DIRECTION_BULLISH,
    )
    by_label = {lvl.label: lvl.price for lvl in result.retracement_levels}

    # Expected: high - leg * level, leg = 0.010127 - 0.006571 = 0.003556
    expected = {
        "r_0236": Decimal("0.009288"),
        "r_0382": Decimal("0.008768"),
        "r_0500": Decimal("0.008349"),
        "r_0618": Decimal("0.007930"),
        "r_0786": Decimal("0.007332"),
        "r_1000": Decimal("0.006571"),
    }
    for label, exp_price in expected.items():
        assert label in by_label, f"Missing retracement level {label}"
        diff = abs(by_label[label] - exp_price)
        assert diff <= _TOLERANCE, (
            f"{label}: expected ~{exp_price}, got {by_label[label]} (diff={diff})"
        )


def test_sxt_extension_levels() -> None:
    candles = _sxt_candles()
    result = build_fib_navigation_map(
        candles=candles,
        current_price=Decimal("0.009588"),
        now_utc=_now_fresh(),
        prior=_exhausted_prior(),
        direction=DIRECTION_BULLISH,
    )
    by_label = {lvl.label: lvl.price for lvl in result.extension_levels}

    # Expected: low + leg * level, leg = 0.003556
    expected = {
        "ext_1272": Decimal("0.011094"),
        "ext_1414": Decimal("0.011599"),
        "ext_1618": Decimal("0.012325"),
        "ext_2000": Decimal("0.013683"),
        "ext_2272": Decimal("0.014650"),
        "ext_2414": Decimal("0.015155"),
        "ext_2618": Decimal("0.015881"),
        "ext_3000": Decimal("0.017239"),
        "ext_4236": Decimal("0.021635"),
    }
    for label, exp_price in expected.items():
        assert label in by_label, f"Missing extension level {label}"
        diff = abs(by_label[label] - exp_price)
        assert diff <= _TOLERANCE, (
            f"{label}: expected ~{exp_price}, got {by_label[label]} (diff={diff})"
        )


def test_sxt_anchor_detected_correctly() -> None:
    candles = _sxt_candles()
    result = build_fib_navigation_map(
        candles=candles,
        current_price=Decimal("0.009588"),
        now_utc=_now_fresh(),
        prior=_exhausted_prior(),
        direction=DIRECTION_BULLISH,
    )
    assert abs(result.anchor_low - Decimal("0.006571")) <= _TOLERANCE
    assert abs(result.anchor_high - Decimal("0.010127")) <= _TOLERANCE


# ---------------------------------------------------------------------------
# 2. All targets passed triggers rebuild attempt
# ---------------------------------------------------------------------------

def test_all_targets_passed_triggers_rebuild() -> None:
    candles = _sxt_candles()
    # Prior map is FRESH but current price has blown through all extensions
    prior = PriorMapMeta(
        map_state=MAP_STATE_FRESH,
        anchor_low=Decimal("0.006571"),
        anchor_high=Decimal("0.010127"),
        direction=DIRECTION_BULLISH,
        top_extension_price=Decimal("0.021635"),
        candle_ts_utc=_ts(9),
    )
    current_price_above_all = Decimal("0.025000")
    result = build_fib_navigation_map(
        candles=candles,
        current_price=current_price_above_all,
        now_utc=_now_fresh(),
        prior=prior,
        direction=DIRECTION_BULLISH,
    )
    assert result.rebuild_trigger == TRIGGER_ALL_TARGETS_PASSED
    assert result.map_state in {MAP_STATE_EMERGENCY_REBUILT, MAP_STATE_FALLBACK}
    assert len(result.retracement_levels) > 0
    assert len(result.extension_levels) > 0


# ---------------------------------------------------------------------------
# 3. No candles or stale candles → NO_DATA or STALE
# ---------------------------------------------------------------------------

def test_no_candles_returns_no_data() -> None:
    result = build_fib_navigation_map(
        candles=[],
        current_price=Decimal("0.009588"),
        now_utc=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert result.map_state == MAP_STATE_NO_DATA
    assert result.rebuild_trigger == TRIGGER_MAP_MISSING
    assert result.retracement_levels == ()
    assert result.extension_levels == ()


def test_insufficient_candles_returns_no_data() -> None:
    candles = _sxt_candles()[:5]
    result = build_fib_navigation_map(
        candles=candles,
        current_price=Decimal("0.009588"),
        now_utc=_now_fresh(),
    )
    assert result.map_state == MAP_STATE_NO_DATA


def test_stale_candles_returns_stale() -> None:
    candles = _sxt_candles()
    stale_now = _ts(10) + timedelta(hours=24)
    result = build_fib_navigation_map(
        candles=candles,
        current_price=Decimal("0.009588"),
        now_utc=stale_now,
    )
    assert result.map_state == MAP_STATE_STALE
    assert result.rebuild_trigger == TRIGGER_MAP_STALE


# ---------------------------------------------------------------------------
# 4. Bearish mirror calculation
# ---------------------------------------------------------------------------

def _bearish_candles() -> list[FibNavCandle]:
    """
    11 candles containing a bearish swing:
      pivot high at index 3: high=0.010127
      pivot low  at index 7: low=0.006571
    """
    return [
        _candle(offset=0,  low="0.007000", high="0.008000"),
        _candle(offset=1,  low="0.008000", high="0.009000"),
        _candle(offset=2,  low="0.009000", high="0.010000"),
        _candle(offset=3,  low="0.009500", high="0.010127"),  # pivot high
        _candle(offset=4,  low="0.009000", high="0.010000"),
        _candle(offset=5,  low="0.008000", high="0.009000"),
        _candle(offset=6,  low="0.007000", high="0.008000"),
        _candle(offset=7,  low="0.006571", high="0.007500"),  # pivot low
        _candle(offset=8,  low="0.006800", high="0.007500"),
        _candle(offset=9,  low="0.007000", high="0.007500"),
        _candle(offset=10, low="0.007000", high="0.007600", close="0.007200"),
    ]


def test_bearish_retrace_levels_go_up_from_low() -> None:
    """Bearish retracement levels should ascend from anchor_low toward anchor_high."""
    retrace, _ = _build_levels(Decimal("0.006571"), Decimal("0.010127"), DIRECTION_BEARISH)
    prices = [lvl.price for lvl in retrace]
    # For bearish: retrace price = anchor_low + leg * level → levels increase with fib_level
    for i in range(1, len(prices)):
        assert prices[i] > prices[i - 1], f"Expected ascending bearish retrace; got {prices}"


def test_bearish_extension_levels_go_below_low() -> None:
    """Bearish extension targets should all fall below anchor_low."""
    _, ext = _build_levels(Decimal("0.006571"), Decimal("0.010127"), DIRECTION_BEARISH)
    for lvl in ext:
        assert lvl.price < Decimal("0.006571"), (
            f"{lvl.label} price {lvl.price} should be below anchor_low 0.006571"
        )


def test_bearish_retrace_100_equals_anchor_high() -> None:
    """Bearish r_1000 (100% retrace) should equal anchor_high."""
    retrace, _ = _build_levels(Decimal("0.006571"), Decimal("0.010127"), DIRECTION_BEARISH)
    r1000 = next(lvl for lvl in retrace if lvl.label == "r_1000")
    assert abs(r1000.price - Decimal("0.010127")) <= _TOLERANCE


def test_bearish_emergency_rebuild_from_candles() -> None:
    candles = _bearish_candles()
    result = build_fib_navigation_map(
        candles=candles,
        current_price=Decimal("0.007200"),
        now_utc=_now_fresh(),
        prior=_exhausted_prior(direction=DIRECTION_BEARISH),
        direction=DIRECTION_BEARISH,
    )
    assert result.map_state in {MAP_STATE_EMERGENCY_REBUILT, MAP_STATE_FALLBACK}
    assert len(result.retracement_levels) > 0
    assert len(result.extension_levels) > 0
    # All bearish extensions should be below anchor_low
    for lvl in result.extension_levels:
        assert lvl.price < result.anchor_low, (
            f"{lvl.label} price {lvl.price} should be below anchor_low {result.anchor_low}"
        )


# ---------------------------------------------------------------------------
# 5. Fresh prior map with no trigger → FRESH state preserved
# ---------------------------------------------------------------------------

def test_valid_prior_no_trigger_returns_fresh() -> None:
    candles = _sxt_candles()
    prior = PriorMapMeta(
        map_state=MAP_STATE_FRESH,
        anchor_low=Decimal("0.006571"),
        anchor_high=Decimal("0.010127"),
        direction=DIRECTION_BULLISH,
        top_extension_price=Decimal("0.021635"),
        candle_ts_utc=_ts(9),
    )
    result = build_fib_navigation_map(
        candles=candles,
        current_price=Decimal("0.009000"),
        now_utc=_now_fresh(),
        prior=prior,
        direction=DIRECTION_BULLISH,
    )
    assert result.map_state == MAP_STATE_FRESH
    assert result.rebuild_trigger == TRIGGER_NONE


# ---------------------------------------------------------------------------
# 6. Architecture guard: no forbidden module imports
# ---------------------------------------------------------------------------

def test_no_forbidden_imports() -> None:
    source = Path("src/market_data/fib_navigation_map_v1.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    forbidden_terms = (
        "decision_gate",
        "execution_planner",
        "executor",
        "broker",
        "bitvavo_client",
        "account_position",
        "balance_snapshot",
        "order_snapshot",
        "agent",
        "dashboard",
    )

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    for module in imported:
        parts = module.split(".")
        for term in forbidden_terms:
            assert term not in parts, f"Forbidden import found: {module}"

    forbidden_refs = (
        "src.decision_gate",
        "src.execution_planner",
        "src.executor",
        "src.broker",
        "order_submission",
        "broker_write",
        "live_order",
    )
    for ref in forbidden_refs:
        assert ref not in source, f"Forbidden reference in source: {ref}"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main() -> None:
    tests = [
        test_sxt_bullish_emergency_rebuild_state,
        test_sxt_retracement_levels,
        test_sxt_extension_levels,
        test_sxt_anchor_detected_correctly,
        test_all_targets_passed_triggers_rebuild,
        test_no_candles_returns_no_data,
        test_insufficient_candles_returns_no_data,
        test_stale_candles_returns_stale,
        test_bearish_retrace_levels_go_up_from_low,
        test_bearish_extension_levels_go_below_low,
        test_bearish_retrace_100_equals_anchor_high,
        test_bearish_emergency_rebuild_from_candles,
        test_valid_prior_no_trigger_returns_fresh,
        test_no_forbidden_imports,
    ]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  PASS  {test.__name__}")
            passed += 1
        except AssertionError as exc:
            print(f"  FAIL  {test.__name__}: {exc}")
            failed += 1
        except Exception as exc:
            print(f"  ERROR {test.__name__}: {exc}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
