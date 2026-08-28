from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.research.entry_quality_forward_validation_v1 import (
    Candle,
    HorizonSpec,
    evaluate_horizon,
    pct_change,
    validate_candles,
)


def ts(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, 28, hour, minute, tzinfo=UTC)


def candle(hour: int, minute: int, close: str, high: str, low: str) -> Candle:
    return Candle(
        close_ts_utc=ts(hour, minute),
        close_price=Decimal(close),
        high_price=Decimal(high),
        low_price=Decimal(low),
    )


def test_forward_outcome_uses_last_close_at_or_before_asof_and_strict_future() -> None:
    observation_asof = ts(10, 7)
    rows = [
        candle(10, 0, "100", "101", "99"),
        candle(10, 15, "102", "103", "100"),
        candle(10, 30, "104", "105", "101"),
        candle(11, 0, "108", "110", "103"),
        candle(11, 15, "200", "205", "190"),
    ]

    result = evaluate_horizon(
        observation_asof=observation_asof,
        candles=rows,
        horizon=HorizonSpec("1h", timedelta(hours=1)),
    )

    assert result.status == "COMPLETE"
    assert result.base_price == Decimal("100")
    assert result.future_close_price == Decimal("108")
    assert result.future_candle_count == 3
    assert result.forward_return_pct == Decimal("8.000000")
    assert result.mfe_pct == Decimal("10.000000")
    assert result.mae_pct == Decimal("0.000000")


def test_candle_exactly_at_observation_asof_is_base_not_future_label() -> None:
    rows = [
        candle(10, 0, "100", "101", "99"),
        candle(10, 15, "101", "102", "100"),
        candle(10, 30, "103", "104", "101"),
    ]
    result = evaluate_horizon(
        observation_asof=ts(10, 15),
        candles=rows,
        horizon=HorizonSpec("1h", timedelta(hours=1)),
    )

    assert result.base_price == Decimal("101")
    assert result.future_candle_count == 1
    assert result.future_close_price == Decimal("103")


def test_horizon_end_is_inclusive_but_candles_after_horizon_are_excluded() -> None:
    rows = [
        candle(10, 0, "100", "101", "99"),
        candle(10, 30, "101", "102", "98"),
        candle(11, 0, "103", "105", "97"),
        candle(11, 15, "150", "160", "140"),
    ]
    result = evaluate_horizon(
        observation_asof=ts(10, 0),
        candles=rows,
        horizon=HorizonSpec("1h", timedelta(hours=1)),
    )

    assert result.future_candle_count == 2
    assert result.future_close_price == Decimal("103")
    assert result.mfe_pct == Decimal("5.000000")
    assert result.mae_pct == Decimal("-3.000000")


def test_missing_base_price_fails_closed() -> None:
    result = evaluate_horizon(
        observation_asof=ts(10, 0),
        candles=[candle(10, 15, "101", "102", "100")],
        horizon=HorizonSpec("1h", timedelta(hours=1)),
    )

    assert result.status == "INSUFFICIENT_BASE_PRICE"
    assert result.forward_return_pct is None
    assert result.mfe_pct is None
    assert result.mae_pct is None


def test_missing_future_candles_fails_closed() -> None:
    result = evaluate_horizon(
        observation_asof=ts(10, 0),
        candles=[candle(10, 0, "100", "101", "99")],
        horizon=HorizonSpec("1h", timedelta(hours=1)),
    )

    assert result.status == "INSUFFICIENT_FUTURE_CANDLES"
    assert result.base_price == Decimal("100")
    assert result.future_close_price is None


def test_validate_candles_rejects_duplicate_timestamps() -> None:
    rows = [
        candle(10, 0, "100", "101", "99"),
        candle(10, 0, "100", "101", "99"),
    ]
    with pytest.raises(ValueError, match="strictly increasing and unique"):
        validate_candles(rows)


def test_pct_change_is_deterministic_decimal_math() -> None:
    assert pct_change(Decimal("100"), Decimal("101.25")) == Decimal("1.250000")
