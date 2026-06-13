from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Sequence

from src.market_context.contracts_v1 import BreathlineState


DEFAULT_STALE_AFTER = timedelta(hours=4)
DEFAULT_EMA_SPAN = 9
DEFAULT_ATR_PERIOD = 14
DEFAULT_ABSOLUTE_MIN_CANDLES = 3
DEFAULT_TEST_ATR_BUFFER = Decimal("0.25")
DEFAULT_RECLAIM_ATR_BUFFER = Decimal("0.10")
DEFAULT_EXTENDED_ATR_MULTIPLE = Decimal("1.50")
DEFAULT_SPIKE_ATR_MULTIPLE = Decimal("2.50")


@dataclass(frozen=True)
class BreathlineCandle:
    close_ts_utc: datetime
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal


@dataclass(frozen=True)
class BreathlineStateResult:
    state: BreathlineState
    breathline_price: str | None
    atr: str | None
    distance_atr: str | None
    latest_close_ts_utc: str | None
    warnings: tuple[str, ...]


def _result(
    *,
    state: BreathlineState,
    breathline_price: Decimal | None,
    atr: Decimal | None,
    distance_atr: Decimal | None,
    latest_close_ts_utc: datetime | None,
    warnings: Sequence[str] = (),
) -> BreathlineStateResult:
    return BreathlineStateResult(
        state=state,
        breathline_price=_decimal_to_json(breathline_price),
        atr=_decimal_to_json(atr),
        distance_atr=_decimal_to_json(distance_atr),
        latest_close_ts_utc=_datetime_to_json(latest_close_ts_utc),
        warnings=tuple(warnings),
    )


def _decimal_to_json(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _datetime_to_json(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


def _valid_positive_int(value: int) -> bool:
    return isinstance(value, int) and value > 0


def _valid_positive_decimal(value: Decimal) -> bool:
    return isinstance(value, Decimal) and value > 0


def _compute_ema_series(closes: Sequence[Decimal], span: int) -> list[Decimal]:
    alpha = Decimal("2") / Decimal(span + 1)
    ema_values: list[Decimal] = [closes[0]]
    for close in closes[1:]:
        ema_values.append((close * alpha) + (ema_values[-1] * (Decimal("1") - alpha)))
    return ema_values


def _compute_atr(candles: Sequence[BreathlineCandle], period: int) -> Decimal:
    ranges = [candle.high_price - candle.low_price for candle in candles]
    window = ranges[-period:] if len(ranges) >= period else ranges
    if not window:
        return Decimal("0")
    return sum(window, Decimal("0")) / Decimal(len(window))


def build_breathline_state(
    *,
    candles: Sequence[BreathlineCandle],
    now_utc: datetime,
    ema_span: int = DEFAULT_EMA_SPAN,
    atr_period: int = DEFAULT_ATR_PERIOD,
    absolute_min_candles: int = DEFAULT_ABSOLUTE_MIN_CANDLES,
    warmup_candles: int | None = None,
    stale_after: timedelta = DEFAULT_STALE_AFTER,
    test_atr_buffer: Decimal = DEFAULT_TEST_ATR_BUFFER,
    reclaim_atr_buffer: Decimal = DEFAULT_RECLAIM_ATR_BUFFER,
    extended_atr_multiple: Decimal = DEFAULT_EXTENDED_ATR_MULTIPLE,
    spike_atr_multiple: Decimal = DEFAULT_SPIKE_ATR_MULTIPLE,
) -> BreathlineStateResult:
    if (
        not _valid_positive_int(ema_span)
        or not _valid_positive_int(atr_period)
        or not _valid_positive_int(absolute_min_candles)
        or (warmup_candles is not None and not _valid_positive_int(warmup_candles))
        or stale_after <= timedelta(0)
        or not _valid_positive_decimal(test_atr_buffer)
        or not _valid_positive_decimal(reclaim_atr_buffer)
        or not _valid_positive_decimal(extended_atr_multiple)
        or not _valid_positive_decimal(spike_atr_multiple)
    ):
        return _result(
            state=BreathlineState.NO_DATA,
            breathline_price=None,
            atr=None,
            distance_atr=None,
            latest_close_ts_utc=None,
            warnings=("INVALID_PARAMETERS",),
        )

    if not candles:
        return _result(
            state=BreathlineState.NO_DATA,
            breathline_price=None,
            atr=None,
            distance_atr=None,
            latest_close_ts_utc=None,
            warnings=("INSUFFICIENT_CANDLES",),
        )

    # Validate required fields before any sort or max-timestamp operation.
    for candle in candles:
        if (
            candle.close_ts_utc is None
            or candle.high_price is None
            or candle.low_price is None
            or candle.close_price is None
        ):
            return _result(
                state=BreathlineState.NO_DATA,
                breathline_price=None,
                atr=None,
                distance_atr=None,
                latest_close_ts_utc=None,
                warnings=("INVALID_CANDLE_DATA",),
            )

    if len(candles) < absolute_min_candles:
        latest_ts = max(candle.close_ts_utc for candle in candles)
        return _result(
            state=BreathlineState.NO_DATA,
            breathline_price=None,
            atr=None,
            distance_atr=None,
            latest_close_ts_utc=latest_ts,
            warnings=("INSUFFICIENT_CANDLES",),
        )

    sorted_candles = sorted(candles, key=lambda candle: candle.close_ts_utc)
    # Validate OHLC constraints; required fields are guaranteed non-None above.
    for candle in sorted_candles:
        if (
            candle.high_price <= 0
            or candle.low_price <= 0
            or candle.close_price <= 0
            or candle.high_price < candle.low_price
        ):
            return _result(
                state=BreathlineState.NO_DATA,
                breathline_price=None,
                atr=None,
                distance_atr=None,
                latest_close_ts_utc=sorted_candles[-1].close_ts_utc,
                warnings=("INVALID_CANDLE_DATA",),
            )

    latest = sorted_candles[-1]
    if now_utc - latest.close_ts_utc > stale_after:
        return _result(
            state=BreathlineState.STALE,
            breathline_price=None,
            atr=None,
            distance_atr=None,
            latest_close_ts_utc=latest.close_ts_utc,
            warnings=("STALE_CANDLES",),
        )

    closes = [candle.close_price for candle in sorted_candles]
    ema_values = _compute_ema_series(closes, ema_span)
    breathline_now = ema_values[-1]
    atr = _compute_atr(sorted_candles, atr_period)
    effective_warmup = warmup_candles or max(ema_span * 2, atr_period + 2, absolute_min_candles)

    if atr > 0 and breathline_now > 0:
        distance_atr = (latest.close_price - breathline_now) / atr
    else:
        distance_atr = None

    if len(sorted_candles) < effective_warmup or atr <= 0 or breathline_now <= 0:
        warning = "WARMUP_SHORT" if len(sorted_candles) < effective_warmup else "LOW_SIGNAL_QUALITY"
        return _result(
            state=BreathlineState.LOW_CONFIDENCE,
            breathline_price=breathline_now,
            atr=atr,
            distance_atr=distance_atr,
            latest_close_ts_utc=latest.close_ts_utc,
            warnings=(warning,),
        )

    previous = sorted_candles[-2]
    breathline_prev = ema_values[-2]
    slope = breathline_now - breathline_prev
    test_buffer = atr * test_atr_buffer
    reclaim_buffer = atr * reclaim_atr_buffer
    latest_close = latest.close_price

    recent_start = max(0, len(sorted_candles) - 3)
    recent_extended = False
    for index in range(recent_start, len(sorted_candles)):
        prior_distance = sorted_candles[index].close_price - ema_values[index]
        if prior_distance >= atr * spike_atr_multiple:
            recent_extended = True
            break

    if recent_extended and latest_close < previous.close_price and (
        latest_close <= breathline_now + test_buffer or slope <= 0
    ):
        state = BreathlineState.SPIKE_COOLING
    elif latest_close >= breathline_now + (atr * extended_atr_multiple) and slope >= 0:
        state = BreathlineState.EXTENDED_ABOVE_BREATHLINE
    elif (
        previous.close_price <= breathline_prev - reclaim_buffer
        and latest.low_price <= breathline_now
        and latest.high_price >= breathline_now
        and latest_close >= breathline_now + reclaim_buffer
    ):
        state = BreathlineState.RECLAIMING_BREATHLINE
    elif latest.low_price <= breathline_now + test_buffer and latest.high_price >= breathline_now - test_buffer:
        state = BreathlineState.TESTING_BREATHLINE
    elif latest_close > breathline_now + test_buffer:
        state = BreathlineState.ABOVE_BREATHLINE
    else:
        state = BreathlineState.BELOW_BREATHLINE

    return _result(
        state=state,
        breathline_price=breathline_now,
        atr=atr,
        distance_atr=distance_atr,
        latest_close_ts_utc=latest.close_ts_utc,
        warnings=(),
    )
