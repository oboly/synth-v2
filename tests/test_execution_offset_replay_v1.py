from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.research.execution_offset_replay_v1 import (
    ExecutionOffsetEpisodeV1, ExecutionOffsetPolicyV1, ExecutionOffsetReplayError,
    POLICY_EXACT_LEVEL, POLICY_STATIC_BUFFER, POLICY_VOLATILITY_SCALED_BUFFER,
    ReplayCandle, SIDE_BUY, SIDE_SELL, execution_price_for_policy, replay_episode,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def episode(side: str = SIDE_SELL) -> ExecutionOffsetEpisodeV1:
    return ExecutionOffsetEpisodeV1(
        "ep-1", "PROM", "bitvavo", "4h", side, "F1.618", Decimal("100"),
        T0, T0 + timedelta(hours=4), Decimal("90") if side == SIDE_BUY else Decimal("110"),
        Decimal("4"), "RANGE", "map-1",
    )

def candle(hours: int, low: str, high: str, close: str = "100") -> ReplayCandle:
    return ReplayCandle(T0 + timedelta(hours=hours), Decimal(high), Decimal(low), Decimal(close))


def test_policy_sign_semantics() -> None:
    static = ExecutionOffsetPolicyV1(POLICY_STATIC_BUFFER, "v1", buffer_pct=Decimal("0.01"))
    assert execution_price_for_policy(episode(SIDE_BUY), static) == Decimal("101.00")
    assert execution_price_for_policy(episode(SIDE_SELL), static) == Decimal("99.00")


def test_exact_level_control() -> None:
    exact = ExecutionOffsetPolicyV1(POLICY_EXACT_LEVEL, "v1")
    assert execution_price_for_policy(episode(), exact) == Decimal("100")


def test_volatility_scaled_requires_atr() -> None:
    policy = ExecutionOffsetPolicyV1(POLICY_VOLATILITY_SCALED_BUFFER, "v1", atr_multiple=Decimal("0.25"))
    assert execution_price_for_policy(episode(), policy) == Decimal("99.00")

def test_sell_near_miss_exact_but_static_buffer_fills() -> None:
    candles = [candle(1, "97", "99.2"), candle(2, "96", "98")]
    exact = replay_episode(episode(), candles, ExecutionOffsetPolicyV1(POLICY_EXACT_LEVEL, "v1"))
    buffered = replay_episode(
        episode(), candles,
        ExecutionOffsetPolicyV1(POLICY_STATIC_BUFFER, "v1", buffer_pct=Decimal("0.01")),
    )
    assert exact.filled is False
    assert exact.touched is False
    assert exact.near_miss_distance_pct == Decimal("0.800")
    assert buffered.filled is True
    assert buffered.execution_price == Decimal("99.00")


def test_future_only_and_invalidated_before_fill() -> None:
    row = replay_episode(
        episode(), [candle(1, "95", "111")],
        ExecutionOffsetPolicyV1(POLICY_EXACT_LEVEL, "v1"),
    )
    assert row.invalidated_before_fill is True
    assert row.filled is False


def test_no_forward_candles_fails_closed() -> None:
    with pytest.raises(ExecutionOffsetReplayError, match="NO_FORWARD_CANDLES"):
        replay_episode(episode(), [candle(5, "90", "120")], ExecutionOffsetPolicyV1(POLICY_EXACT_LEVEL, "v1"))


def test_duplicate_forward_candle_timestamp_fails_closed_independent_of_input_order() -> None:
    duplicate_a = candle(1, "97", "99.2")
    duplicate_b = candle(1, "95", "111")
    policy = ExecutionOffsetPolicyV1(POLICY_EXACT_LEVEL, "v1")
    for rows in ([duplicate_a, duplicate_b], [duplicate_b, duplicate_a]):
        with pytest.raises(ExecutionOffsetReplayError, match="DUPLICATE_FORWARD_CANDLE_TIMESTAMP"):
            replay_episode(episode(), rows, policy)
