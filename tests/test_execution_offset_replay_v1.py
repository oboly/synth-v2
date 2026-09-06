from dataclasses import replace
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

def candle(hours: int, low: str, high: str, close: str | None = None) -> ReplayCandle:
    close_ts = T0 + timedelta(hours=hours)
    low_price = Decimal(low)
    high_price = Decimal(high)
    close_price = Decimal(close) if close is not None else (low_price + high_price) / Decimal("2")
    return ReplayCandle(close_ts - timedelta(hours=1), close_ts, high_price, low_price, close_price)


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
    assert buffered.touched is True
    assert buffered.canonical_level_touched is False
    assert buffered.execution_price == Decimal("99.00")
    assert buffered.near_miss_distance_pct is None


def test_same_candle_sell_fill_and_invalidation_is_ambiguous() -> None:
    row = replay_episode(
        episode(), [candle(1, "95", "111")],
        ExecutionOffsetPolicyV1(POLICY_EXACT_LEVEL, "v1"),
    )
    assert row.same_candle_fill_invalidation_ambiguous is True
    assert row.invalidated_before_fill is False
    assert row.filled is False


def test_same_candle_buy_fill_and_invalidation_is_ambiguous() -> None:
    row = replay_episode(
        episode(SIDE_BUY), [candle(1, "89", "105")],
        ExecutionOffsetPolicyV1(POLICY_EXACT_LEVEL, "v1"),
    )
    assert row.same_candle_fill_invalidation_ambiguous is True
    assert row.invalidated_before_fill is False
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


def test_buffered_sell_near_miss_uses_execution_price() -> None:
    row = replay_episode(
        episode(), [candle(1, "97", "98.5")],
        ExecutionOffsetPolicyV1(POLICY_STATIC_BUFFER, "v1", buffer_pct=Decimal("0.01")),
    )
    assert row.filled is False
    assert row.near_miss_distance_pct == (Decimal("0.5") / Decimal("99") * Decimal("100"))


def test_buffered_buy_near_miss_uses_execution_price() -> None:
    row = replay_episode(
        episode(SIDE_BUY), [candle(1, "101.5", "103")],
        ExecutionOffsetPolicyV1(POLICY_STATIC_BUFFER, "v1", buffer_pct=Decimal("0.01")),
    )
    assert row.filled is False
    assert row.near_miss_distance_pct == (Decimal("0.5") / Decimal("101") * Decimal("100"))


def test_excursions_exclude_fill_candle() -> None:
    row = replay_episode(
        episode(), [candle(1, "90", "100"), candle(2, "99", "101")],
        ExecutionOffsetPolicyV1(POLICY_EXACT_LEVEL, "v1"),
    )
    assert row.filled is True
    assert row.max_favorable_excursion_pct == Decimal("1")
    assert row.max_adverse_excursion_pct == Decimal("1")


def test_sell_excursions_include_zero_baseline() -> None:
    row = replay_episode(
        episode(), [candle(1, "100", "100"), candle(2, "101", "102")],
        ExecutionOffsetPolicyV1(POLICY_EXACT_LEVEL, "v1"),
    )
    assert row.max_favorable_excursion_pct == Decimal("0")
    assert row.max_adverse_excursion_pct == Decimal("2")


def test_buy_excursions_include_zero_baseline() -> None:
    row = replay_episode(
        episode(SIDE_BUY), [candle(1, "100", "100"), candle(2, "98", "99")],
        ExecutionOffsetPolicyV1(POLICY_EXACT_LEVEL, "v1"),
    )
    assert row.max_favorable_excursion_pct == Decimal("0")
    assert row.max_adverse_excursion_pct == Decimal("2")


def test_static_sell_offset_rejects_non_positive_execution_price() -> None:
    with pytest.raises(ExecutionOffsetReplayError, match="NON_POSITIVE_EXECUTION_PRICE"):
        execution_price_for_policy(
            episode(),
            ExecutionOffsetPolicyV1(POLICY_STATIC_BUFFER, "v1", buffer_pct=Decimal("1")),
        )


def test_volatility_sell_offset_rejects_non_positive_execution_price() -> None:
    with pytest.raises(ExecutionOffsetReplayError, match="NON_POSITIVE_EXECUTION_PRICE"):
        execution_price_for_policy(
            episode(),
            ExecutionOffsetPolicyV1(POLICY_VOLATILITY_SCALED_BUFFER, "v1", atr_multiple=Decimal("25")),
        )


def test_mid_candle_issuance_excludes_preissuance_ohlc() -> None:
    ep = ExecutionOffsetEpisodeV1(
        "ep-mid", "PROM", "bitvavo", "4h", SIDE_SELL, "F1.618", Decimal("100"),
        T0 + timedelta(minutes=30), T0 + timedelta(hours=4), Decimal("110"),
        Decimal("4"), "RANGE", "map-mid",
    )
    row = replay_episode(
        ep,
        [candle(1, "95", "100"), candle(2, "95", "99")],
        ExecutionOffsetPolicyV1(POLICY_EXACT_LEVEL, "v1"),
    )
    assert row.filled is False
    assert row.near_miss_distance_pct == Decimal("1")


def test_overlapping_forward_candles_fail_closed() -> None:
    first = ReplayCandle(T0, T0 + timedelta(hours=2), Decimal("101"), Decimal("99"), Decimal("100"))
    second = ReplayCandle(T0 + timedelta(hours=1), T0 + timedelta(hours=3), Decimal("101"), Decimal("99"), Decimal("100"))
    with pytest.raises(ExecutionOffsetReplayError, match="OVERLAPPING_FORWARD_CANDLE_INTERVAL"):
        replay_episode(episode(), [first, second], ExecutionOffsetPolicyV1(POLICY_EXACT_LEVEL, "v1"))


def test_buy_invalidation_must_be_below_execution_price() -> None:
    bad = replace(episode(SIDE_BUY), invalidation_price=Decimal("100"))
    with pytest.raises(ExecutionOffsetReplayError, match="INVALID_INVALIDATION_DIRECTION"):
        replay_episode(bad, [candle(1, "99", "101")], ExecutionOffsetPolicyV1(POLICY_EXACT_LEVEL, "v1"))


def test_sell_invalidation_must_be_above_execution_price() -> None:
    bad = replace(episode(SIDE_SELL), invalidation_price=Decimal("100"))
    with pytest.raises(ExecutionOffsetReplayError, match="INVALID_INVALIDATION_DIRECTION"):
        replay_episode(bad, [candle(1, "99", "101")], ExecutionOffsetPolicyV1(POLICY_EXACT_LEVEL, "v1"))
