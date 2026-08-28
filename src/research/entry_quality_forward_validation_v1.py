from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Iterable


@dataclass(frozen=True)
class Candle:
    close_ts_utc: datetime
    close_price: Decimal
    high_price: Decimal
    low_price: Decimal


@dataclass(frozen=True)
class HorizonSpec:
    label: str
    delta: timedelta


@dataclass(frozen=True)
class HorizonOutcome:
    horizon: str
    horizon_end_ts_utc: datetime
    base_price: Decimal | None
    future_close_price: Decimal | None
    future_candle_count: int
    forward_return_pct: Decimal | None
    mfe_pct: Decimal | None
    mae_pct: Decimal | None
    status: str


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def pct_change(base: Decimal, value: Decimal) -> Decimal:
    return (((value / base) - Decimal("1")) * Decimal("100")).quantize(
        Decimal("0.000001")
    )


def validate_candles(candles: Iterable[Candle]) -> list[Candle]:
    ordered = sorted(candles, key=lambda candle: ensure_utc(candle.close_ts_utc))
    previous_ts: datetime | None = None
    for candle in ordered:
        ts = ensure_utc(candle.close_ts_utc)
        if previous_ts is not None and ts <= previous_ts:
            raise ValueError("Candle timestamps must be strictly increasing and unique")
        if candle.close_price <= 0 or candle.high_price <= 0 or candle.low_price <= 0:
            raise ValueError("Candle prices must be positive")
        if candle.high_price < candle.low_price:
            raise ValueError("Candle high must be >= low")
        if candle.high_price < candle.close_price or candle.low_price > candle.close_price:
            raise ValueError("Candle close must lie within high/low range")
        previous_ts = ts
    return ordered


def evaluate_horizon(
    *,
    observation_asof: datetime,
    candles: Iterable[Candle],
    horizon: HorizonSpec,
) -> HorizonOutcome:
    observation_asof = ensure_utc(observation_asof)
    horizon_end = observation_asof + horizon.delta
    ordered = validate_candles(candles)

    base_candidates = [
        candle
        for candle in ordered
        if ensure_utc(candle.close_ts_utc) <= observation_asof
    ]
    if not base_candidates:
        return HorizonOutcome(
            horizon=horizon.label,
            horizon_end_ts_utc=horizon_end,
            base_price=None,
            future_close_price=None,
            future_candle_count=0,
            forward_return_pct=None,
            mfe_pct=None,
            mae_pct=None,
            status="INSUFFICIENT_BASE_PRICE",
        )

    base = base_candidates[-1].close_price
    future = [
        candle
        for candle in ordered
        if observation_asof < ensure_utc(candle.close_ts_utc) <= horizon_end
    ]
    if not future:
        return HorizonOutcome(
            horizon=horizon.label,
            horizon_end_ts_utc=horizon_end,
            base_price=base,
            future_close_price=None,
            future_candle_count=0,
            forward_return_pct=None,
            mfe_pct=None,
            mae_pct=None,
            status="INSUFFICIENT_FUTURE_CANDLES",
        )

    future_close = future[-1].close_price
    max_high = max(candle.high_price for candle in future)
    min_low = min(candle.low_price for candle in future)
    return HorizonOutcome(
        horizon=horizon.label,
        horizon_end_ts_utc=horizon_end,
        base_price=base,
        future_close_price=future_close,
        future_candle_count=len(future),
        forward_return_pct=pct_change(base, future_close),
        mfe_pct=pct_change(base, max_high),
        mae_pct=pct_change(base, min_low),
        status="COMPLETE",
    )


def evaluate_all_horizons(
    *,
    observation_asof: datetime,
    candles: Iterable[Candle],
    horizons: Iterable[HorizonSpec],
) -> list[HorizonOutcome]:
    candle_rows = list(candles)
    return [
        evaluate_horizon(
            observation_asof=observation_asof,
            candles=candle_rows,
            horizon=horizon,
        )
        for horizon in horizons
    ]
