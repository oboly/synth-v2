from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from src.market_data.fib_navigation_map_v1 import (
    ACTIVE_RECOMPUTED_MAP,
    DIRECTION_BULLISH,
    MAP_COMPLETED_FROZEN,
    MAP_STATE_EMERGENCY_REBUILT,
    MAP_STATE_FALLBACK,
    NEW_MAP_AVAILABLE,
    PriorMapMeta,
    RECOMPUTE_NEEDED,
    TRIGGER_ALL_TARGETS_PASSED,
    TRIGGER_MAP_EXHAUSTED,
    FibNavCandle,
    build_fib_navigation_map,
)

_TOL = Decimal("0.0002")


def _ts(index: int) -> datetime:
    return datetime(2026, 6, 14, 0, 0, tzinfo=UTC) + timedelta(hours=index)


def _candle(
    index: int,
    *,
    low: str,
    high: str,
    close: str | None = None,
    open_: str | None = None,
    volume: str = "1000",
) -> FibNavCandle:
    low_d = Decimal(low)
    high_d = Decimal(high)
    close_d = Decimal(close) if close is not None else (low_d + high_d) / 2
    open_d = Decimal(open_) if open_ is not None else close_d
    return FibNavCandle(
        close_ts_utc=_ts(index),
        open_price=open_d,
        high_price=high_d,
        low_price=low_d,
        close_price=close_d,
        volume=Decimal(volume),
    )


def _completed_prior(*, low: str, high: str, top: str) -> PriorMapMeta:
    return PriorMapMeta(
        map_state="MAP_COMPLETED",
        anchor_low=Decimal(low),
        anchor_high=Decimal(high),
        direction=DIRECTION_BULLISH,
        top_extension_price=Decimal(top),
        candle_ts_utc=_ts(5),
    )


def _price_by_label(result) -> dict[str, Decimal]:
    return {level.label: level.price for level in result.retracement_levels + result.extension_levels}


def _assert_level_close(actual: Decimal, expected: Decimal, *, tol: Decimal = _TOL) -> None:
    assert abs(actual - expected) <= tol, f"expected ~{expected}, got {actual}"


def _sxt_case_candles() -> list[FibNavCandle]:
    return [
        _candle(0, low="0.0089", high="0.0094"),
        _candle(1, low="0.0082", high="0.0089"),
        _candle(2, low="0.0071", high="0.0081"),
        _candle(3, low="0.006571", high="0.00695"),
        _candle(4, low="0.0071", high="0.0077"),
        _candle(5, low="0.0078", high="0.0086"),
        _candle(6, low="0.0085", high="0.0092"),
        _candle(7, low="0.0089", high="0.0097"),
        _candle(8, low="0.0091", high="0.00995"),
        _candle(9, low="0.0092", high="0.01005", close="0.00982"),
        _candle(10, low="0.00931", high="0.010127", close="0.009588"),
    ]


def _xpl_case_candles() -> list[FibNavCandle]:
    return [
        _candle(0, low="0.0610", high="0.0630"),
        _candle(1, low="0.0580", high="0.0615"),
        _candle(2, low="0.0545", high="0.0575"),
        _candle(3, low="0.05213", high="0.0532"),
        _candle(4, low="0.0540", high="0.0580"),
        _candle(5, low="0.0575", high="0.0625"),
        _candle(6, low="0.0610", high="0.0670"),
        _candle(7, low="0.0645", high="0.0705"),
        _candle(8, low="0.0672", high="0.0724"),
        _candle(9, low="0.0699", high="0.07420", close="0.0734"),
        _candle(10, low="0.0708", high="0.07468", close="0.074067"),
    ]


def _render_case_candles() -> list[FibNavCandle]:
    return [
        _candle(0, low="1.3200", high="1.3600"),
        _candle(1, low="1.3080", high="1.3440"),
        _candle(2, low="1.2920", high="1.3220"),
        _candle(3, low="1.2840", high="1.3020"),
        _candle(4, low="1.3000", high="1.3360"),
        _candle(5, low="1.3260", high="1.3720"),
        _candle(6, low="1.3520", high="1.3980"),
        _candle(7, low="1.3740", high="1.4180"),
        _candle(8, low="1.3920", high="1.4300"),
        _candle(9, low="1.4010", high="1.4350", close="1.4280"),
        _candle(10, low="1.4090", high="1.4369", close="1.4369"),
    ]


def test_sxt_exhausted_map_rebuild_has_navigation_levels() -> None:
    result = build_fib_navigation_map(
        candles=_sxt_case_candles(),
        current_price=Decimal("0.009588"),
        now_utc=_ts(10) + timedelta(minutes=1),
        prior=_completed_prior(low="0.0050", high="0.0080", top="0.0090"),
        direction=DIRECTION_BULLISH,
    )
    assert result.map_state in {MAP_STATE_EMERGENCY_REBUILT, MAP_STATE_FALLBACK}
    assert result.rebuild_trigger in {TRIGGER_MAP_EXHAUSTED, TRIGGER_ALL_TARGETS_PASSED}
    assert result.extension_levels
    assert result.retracement_levels
    assert result.historical_reference_state == MAP_COMPLETED_FROZEN
    assert result.active_map_state == ACTIVE_RECOMPUTED_MAP
    assert result.recompute_status == NEW_MAP_AVAILABLE


def test_xpl_exhausted_map_rebuild_levels_match_golden_case() -> None:
    result = build_fib_navigation_map(
        candles=_xpl_case_candles(),
        current_price=Decimal("0.074067"),
        now_utc=_ts(10) + timedelta(minutes=1),
        prior=_completed_prior(low="0.0490", high="0.0630", top="0.069942"),
        direction=DIRECTION_BULLISH,
    )
    by_label = _price_by_label(result)
    for label, expected in {
        "r_0236": Decimal("0.06936"),
        "r_0382": Decimal("0.06606"),
        "r_0500": Decimal("0.06340"),
        "r_0618": Decimal("0.06074"),
        "r_0786": Decimal("0.05696"),
        "ext_1272": Decimal("0.08081"),
        "ext_1414": Decimal("0.08401"),
        "ext_1618": Decimal("0.08862"),
        "ext_2000": Decimal("0.09723"),
    }.items():
        _assert_level_close(by_label[label], expected)
    assert result.historical_reference_state == MAP_COMPLETED_FROZEN
    assert result.active_map_state == ACTIVE_RECOMPUTED_MAP
    assert result.recompute_status == NEW_MAP_AVAILABLE


def test_render_exhausted_map_rebuild_levels_match_golden_case() -> None:
    result = build_fib_navigation_map(
        candles=_render_case_candles(),
        current_price=Decimal("1.4369"),
        now_utc=_ts(10) + timedelta(minutes=1),
        prior=_completed_prior(low="1.2400", high="1.3858", top="1.4126"),
        direction=DIRECTION_BULLISH,
    )
    by_label = _price_by_label(result)
    for label, expected in {
        "r_0236": Decimal("1.4008"),
        "r_0382": Decimal("1.3785"),
        "r_0500": Decimal("1.3605"),
        "r_0618": Decimal("1.3424"),
        "r_0786": Decimal("1.3167"),
        "r_1000": Decimal("1.2840"),
        "ext_1272": Decimal("1.4785"),
        "ext_1414": Decimal("1.5002"),
        "ext_1618": Decimal("1.5314"),
        "ext_2000": Decimal("1.5898"),
    }.items():
        _assert_level_close(by_label[label], expected, tol=Decimal("0.0003"))
    assert result.extension_levels


def test_tao_completed_map_reference_stays_frozen_when_new_map_available() -> None:
    prior = _completed_prior(low="250", high="300", top="330")
    result = build_fib_navigation_map(
        candles=[
            _candle(0, low="260", high="275"),
            _candle(1, low="255", high="268"),
            _candle(2, low="248", high="258"),
            _candle(3, low="240", high="246"),
            _candle(4, low="246", high="258"),
            _candle(5, low="254", high="274"),
            _candle(6, low="270", high="298"),
            _candle(7, low="290", high="320"),
            _candle(8, low="308", high="338"),
            _candle(9, low="320", high="352"),
            _candle(10, low="334", high="365", close="360"),
        ],
        current_price=Decimal("360"),
        now_utc=_ts(10) + timedelta(minutes=1),
        prior=prior,
        direction=DIRECTION_BULLISH,
    )
    assert result.historical_reference_state == MAP_COMPLETED_FROZEN
    assert result.historical_reference_top_extension_price == Decimal("330")
    assert result.active_map_state == ACTIVE_RECOMPUTED_MAP
    assert result.recompute_status == NEW_MAP_AVAILABLE
    assert result.historical_reference_top_extension_price != result.extension_levels[-1].price


def test_completed_reference_without_fresh_rebuild_marks_recompute_needed() -> None:
    prior = _completed_prior(low="0.0050", high="0.0080", top="0.0090")
    result = build_fib_navigation_map(
        candles=_sxt_case_candles()[:5],
        current_price=Decimal("0.009588"),
        now_utc=_ts(4) + timedelta(minutes=1),
        prior=prior,
        direction=DIRECTION_BULLISH,
    )
    assert result.map_state == "NO_DATA"
    assert result.historical_reference_state == MAP_COMPLETED_FROZEN
    assert result.recompute_status == RECOMPUTE_NEEDED
