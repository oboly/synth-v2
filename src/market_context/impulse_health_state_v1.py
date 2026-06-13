from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Sequence

from src.market_context.contracts_v1 import ImpulseHealthState


DEFAULT_STALE_AFTER = timedelta(hours=4)
DEFAULT_EMA_SPAN = 9
DEFAULT_ATR_PERIOD = 14
DEFAULT_IMPULSE_LOOKBACK = 8
DEFAULT_ABSOLUTE_MIN_CANDLES = 3
DEFAULT_BLOW_OFF_ATR_MULTIPLE = Decimal("2.75")
DEFAULT_EXTENDED_ATR_MULTIPLE = Decimal("1.75")
DEFAULT_HEALTHY_ATR_MULTIPLE = Decimal("0.50")
DEFAULT_EARLY_ATR_MULTIPLE = Decimal("0.25")
DEFAULT_PULLBACK_MIN_ATR = Decimal("0.75")
DEFAULT_PULLBACK_MAX_ATR = Decimal("1.75")
DEFAULT_RECLAIM_FAIL_ATR = Decimal("0.25")


@dataclass(frozen=True)
class ImpulseHealthCandle:
    close_ts_utc: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal


@dataclass(frozen=True)
class ImpulseHealthStateResult:
    state: ImpulseHealthState
    ema_price: str | None
    atr: str | None
    swing_high_price: str | None
    distance_atr: str | None
    pullback_from_high_atr: str | None
    latest_close_ts_utc: str | None
    warnings: tuple[str, ...]


def _result(
    *,
    state: ImpulseHealthState,
    ema_price: Decimal | None,
    atr: Decimal | None,
    swing_high_price: Decimal | None,
    distance_atr: Decimal | None,
    pullback_from_high_atr: Decimal | None,
    latest_close_ts_utc: datetime | None,
    warnings: Sequence[str] = (),
) -> ImpulseHealthStateResult:
    return ImpulseHealthStateResult(
        state=state,
        ema_price=_decimal_to_json(ema_price),
        atr=_decimal_to_json(atr),
        swing_high_price=_decimal_to_json(swing_high_price),
        distance_atr=_decimal_to_json(distance_atr),
        pullback_from_high_atr=_decimal_to_json(pullback_from_high_atr),
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


def _compute_true_ranges(candles: Sequence[ImpulseHealthCandle]) -> list[Decimal]:
    ranges: list[Decimal] = []
    previous_close: Decimal | None = None
    for candle in candles:
        intrabar = candle.high_price - candle.low_price
        if previous_close is None:
            ranges.append(intrabar)
        else:
            ranges.append(
                max(
                    intrabar,
                    abs(candle.high_price - previous_close),
                    abs(candle.low_price - previous_close),
                )
            )
        previous_close = candle.close_price
    return ranges


def _compute_atr(candles: Sequence[ImpulseHealthCandle], period: int) -> Decimal:
    ranges = _compute_true_ranges(candles)
    window = ranges[-period:] if len(ranges) >= period else ranges
    if not window:
        return Decimal("0")
    return sum(window, Decimal("0")) / Decimal(len(window))


def _is_blow_off_candle(
    *,
    candle: ImpulseHealthCandle,
    ema_value: Decimal,
    atr: Decimal,
    blow_off_atr_multiple: Decimal,
) -> bool:
    if atr <= 0:
        return False
    body = abs(candle.close_price - candle.open_price)
    upper_wick = candle.high_price - max(candle.open_price, candle.close_price)
    candle_range = candle.high_price - candle.low_price
    return (
        candle.high_price >= ema_value + (atr * blow_off_atr_multiple)
        and candle_range >= atr * Decimal("1.50")
        and upper_wick >= max(body, atr * Decimal("0.50"))
        and candle.close_price <= candle.high_price - (atr * Decimal("0.75"))
    )


def build_impulse_health_state(
    *,
    candles: Sequence[ImpulseHealthCandle],
    now_utc: datetime,
    ema_span: int = DEFAULT_EMA_SPAN,
    atr_period: int = DEFAULT_ATR_PERIOD,
    impulse_lookback: int = DEFAULT_IMPULSE_LOOKBACK,
    absolute_min_candles: int = DEFAULT_ABSOLUTE_MIN_CANDLES,
    warmup_candles: int | None = None,
    stale_after: timedelta = DEFAULT_STALE_AFTER,
    blow_off_atr_multiple: Decimal = DEFAULT_BLOW_OFF_ATR_MULTIPLE,
    extended_atr_multiple: Decimal = DEFAULT_EXTENDED_ATR_MULTIPLE,
    healthy_atr_multiple: Decimal = DEFAULT_HEALTHY_ATR_MULTIPLE,
    early_atr_multiple: Decimal = DEFAULT_EARLY_ATR_MULTIPLE,
    pullback_min_atr: Decimal = DEFAULT_PULLBACK_MIN_ATR,
    pullback_max_atr: Decimal = DEFAULT_PULLBACK_MAX_ATR,
    reclaim_fail_atr: Decimal = DEFAULT_RECLAIM_FAIL_ATR,
) -> ImpulseHealthStateResult:
    if (
        not _valid_positive_int(ema_span)
        or not _valid_positive_int(atr_period)
        or not _valid_positive_int(impulse_lookback)
        or not _valid_positive_int(absolute_min_candles)
        or (warmup_candles is not None and not _valid_positive_int(warmup_candles))
        or stale_after <= timedelta(0)
        or not _valid_positive_decimal(blow_off_atr_multiple)
        or not _valid_positive_decimal(extended_atr_multiple)
        or not _valid_positive_decimal(healthy_atr_multiple)
        or not _valid_positive_decimal(early_atr_multiple)
        or not _valid_positive_decimal(pullback_min_atr)
        or not _valid_positive_decimal(pullback_max_atr)
        or not _valid_positive_decimal(reclaim_fail_atr)
        or pullback_max_atr <= pullback_min_atr
    ):
        return _result(
            state=ImpulseHealthState.NO_DATA,
            ema_price=None,
            atr=None,
            swing_high_price=None,
            distance_atr=None,
            pullback_from_high_atr=None,
            latest_close_ts_utc=None,
            warnings=("INVALID_PARAMETERS",),
        )

    if not candles:
        return _result(
            state=ImpulseHealthState.NO_DATA,
            ema_price=None,
            atr=None,
            swing_high_price=None,
            distance_atr=None,
            pullback_from_high_atr=None,
            latest_close_ts_utc=None,
            warnings=("INSUFFICIENT_CANDLES",),
        )

    # Validate required fields before any sort or max-timestamp operation.
    for candle in candles:
        if (
            candle.close_ts_utc is None
            or candle.open_price is None
            or candle.high_price is None
            or candle.low_price is None
            or candle.close_price is None
        ):
            return _result(
                state=ImpulseHealthState.NO_DATA,
                ema_price=None,
                atr=None,
                swing_high_price=None,
                distance_atr=None,
                pullback_from_high_atr=None,
                latest_close_ts_utc=None,
                warnings=("INVALID_CANDLE_DATA",),
            )

    if len(candles) < absolute_min_candles:
        latest_ts = max(candle.close_ts_utc for candle in candles)
        return _result(
            state=ImpulseHealthState.NO_DATA,
            ema_price=None,
            atr=None,
            swing_high_price=None,
            distance_atr=None,
            pullback_from_high_atr=None,
            latest_close_ts_utc=latest_ts,
            warnings=("INSUFFICIENT_CANDLES",),
        )

    sorted_candles = sorted(candles, key=lambda candle: candle.close_ts_utc)
    # Validate OHLC constraints; required fields are guaranteed non-None above.
    for candle in sorted_candles:
        if (
            candle.open_price <= 0
            or candle.high_price <= 0
            or candle.low_price <= 0
            or candle.close_price <= 0
            or candle.high_price < candle.low_price
            or candle.high_price < max(candle.open_price, candle.close_price)
            or candle.low_price > min(candle.open_price, candle.close_price)
        ):
            return _result(
                state=ImpulseHealthState.NO_DATA,
                ema_price=None,
                atr=None,
                swing_high_price=None,
                distance_atr=None,
                pullback_from_high_atr=None,
                latest_close_ts_utc=sorted_candles[-1].close_ts_utc,
                warnings=("INVALID_CANDLE_DATA",),
            )

    latest = sorted_candles[-1]
    if now_utc - latest.close_ts_utc > stale_after:
        return _result(
            state=ImpulseHealthState.STALE,
            ema_price=None,
            atr=None,
            swing_high_price=None,
            distance_atr=None,
            pullback_from_high_atr=None,
            latest_close_ts_utc=latest.close_ts_utc,
            warnings=("STALE_CANDLES",),
        )

    closes = [candle.close_price for candle in sorted_candles]
    ema_values = _compute_ema_series(closes, ema_span)
    ema_now = ema_values[-1]
    atr = _compute_atr(sorted_candles, atr_period)
    effective_warmup = warmup_candles or max(
        ema_span * 2,
        atr_period + 2,
        impulse_lookback + 2,
        absolute_min_candles,
    )

    lookback = min(len(sorted_candles), impulse_lookback)
    swing_window = sorted_candles[-lookback:]
    swing_high_price = max(candle.high_price for candle in swing_window)
    distance_atr = None if atr <= 0 else (latest.close_price - ema_now) / atr
    pullback_from_high_atr = None if atr <= 0 else (swing_high_price - latest.close_price) / atr

    if len(sorted_candles) < effective_warmup or atr <= 0 or ema_now <= 0:
        warning = "WARMUP_SHORT" if len(sorted_candles) < effective_warmup else "LOW_SIGNAL_QUALITY"
        return _result(
            state=ImpulseHealthState.LOW_CONFIDENCE,
            ema_price=ema_now,
            atr=atr,
            swing_high_price=swing_high_price,
            distance_atr=distance_atr,
            pullback_from_high_atr=pullback_from_high_atr,
            latest_close_ts_utc=latest.close_ts_utc,
            warnings=(warning,),
        )

    previous = sorted_candles[-2]
    prior = sorted_candles[-3]
    ema_prev = ema_values[-2]
    slope = ema_now - ema_prev
    latest_close = latest.close_price
    latest_high = latest.high_price
    latest_low = latest.low_price
    latest_open = latest.open_price
    upper_wick = latest_high - max(latest_open, latest_close)
    body = abs(latest_close - latest_open)
    candle_range = latest_high - latest_low
    made_recent_high = latest_high >= max(candle.high_price for candle in sorted_candles[-min(4, len(sorted_candles)):])
    near_high = swing_high_price - latest_close <= atr * Decimal("0.75")
    recent_blow_off = any(
        _is_blow_off_candle(
            candle=sorted_candles[index],
            ema_value=ema_values[index],
            atr=atr,
            blow_off_atr_multiple=blow_off_atr_multiple,
        )
        for index in range(max(0, len(sorted_candles) - 5), len(sorted_candles))
    )
    upper_wick_dominant_count = sum(
        1
        for candle in sorted_candles[-3:]
        if (candle.high_price - max(candle.open_price, candle.close_price))
        >= abs(candle.close_price - candle.open_price)
    )

    if _is_blow_off_candle(
        candle=latest,
        ema_value=ema_now,
        atr=atr,
        blow_off_atr_multiple=blow_off_atr_multiple,
    ):
        state = ImpulseHealthState.BLOW_OFF_SPIKE
    elif (
        recent_blow_off
        and upper_wick_dominant_count >= 2
        and latest_close <= previous.close_price
        and latest_close >= ema_now + (atr * Decimal("0.50"))
    ):
        state = ImpulseHealthState.DISTRIBUTION_RISK
    elif (
        previous.close_price <= ema_prev - (atr * reclaim_fail_atr)
        and latest_high >= ema_now
        and latest_close <= ema_now - (atr * reclaim_fail_atr)
    ):
        state = ImpulseHealthState.FAILED_RECLAIM
    elif (
        pullback_from_high_atr is not None
        and pullback_min_atr <= pullback_from_high_atr <= pullback_max_atr
        and latest_low >= ema_now - (atr * Decimal("0.25"))
        and latest_close >= ema_now + (atr * Decimal("0.10"))
        and latest_close > previous.close_price > prior.close_price
        and latest_high < swing_high_price
    ):
        state = ImpulseHealthState.SECOND_BUMP_POSSIBLE
    elif (
        pullback_from_high_atr is not None
        and pullback_min_atr <= pullback_from_high_atr <= pullback_max_atr
        and latest_close >= ema_now - (atr * Decimal("0.25"))
        and latest_close < swing_high_price
    ):
        state = ImpulseHealthState.COOLING_PULLBACK
    elif (
        latest_close >= ema_now + (atr * extended_atr_multiple)
        and slope > 0
        and upper_wick < body + (atr * Decimal("0.25"))
        and candle_range >= atr
    ):
        state = ImpulseHealthState.EXTENDED_IMPULSE
    elif (
        latest_close >= ema_now + (atr * early_atr_multiple)
        and latest_close < ema_now + (atr * healthy_atr_multiple)
        and slope >= 0
        and made_recent_high
        and latest_close > previous.close_price
    ):
        state = ImpulseHealthState.EARLY_IMPULSE
    else:
        state = ImpulseHealthState.HEALTHY_IMPULSE

    return _result(
        state=state,
        ema_price=ema_now,
        atr=atr,
        swing_high_price=swing_high_price,
        distance_atr=distance_atr,
        pullback_from_high_atr=pullback_from_high_atr,
        latest_close_ts_utc=latest.close_ts_utc,
        warnings=(),
    )
