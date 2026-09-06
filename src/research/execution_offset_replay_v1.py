from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Final, Iterable

VERSION: Final[str] = "execution_offset_replay_v1"
POLICY_EXACT_LEVEL: Final[str] = "EXACT_LEVEL"
POLICY_STATIC_BUFFER: Final[str] = "STATIC_BUFFER"
POLICY_VOLATILITY_SCALED_BUFFER: Final[str] = "VOLATILITY_SCALED_BUFFER"
SUPPORTED_POLICIES = frozenset({
    POLICY_EXACT_LEVEL,
    POLICY_STATIC_BUFFER,
    POLICY_VOLATILITY_SCALED_BUFFER,
})
SIDE_BUY: Final[str] = "BUY"
SIDE_SELL: Final[str] = "SELL"


class ExecutionOffsetReplayError(ValueError):
    pass


@dataclass(frozen=True)
class ReplayCandle:
    close_ts_utc: datetime
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal

@dataclass(frozen=True)
class ExecutionOffsetPolicyV1:
    policy_id: str
    version: str
    buffer_pct: Decimal = Decimal("0")
    atr_multiple: Decimal = Decimal("0")


@dataclass(frozen=True)
class ExecutionOffsetEpisodeV1:
    episode_id: str
    symbol: str
    venue: str
    horizon: str
    side: str
    fib_level_id: str
    canonical_level: Decimal
    issued_ts_utc: datetime
    valid_until_ts_utc: datetime
    invalidation_price: Decimal | None
    atr_at_issue: Decimal | None
    regime_state: str | None
    source_map_id: str


@dataclass(frozen=True)
class ExecutionOffsetReplayRowV1:
    episode_id: str
    policy_id: str
    policy_version: str
    canonical_level: Decimal
    execution_price: Decimal
    touched: bool
    filled: bool
    near_miss_distance_pct: Decimal | None
    time_to_fill_seconds: int | None
    max_favorable_excursion_pct: Decimal | None
    max_adverse_excursion_pct: Decimal | None
    invalidated_before_fill: bool

def validate_policy(policy: ExecutionOffsetPolicyV1) -> None:
    if policy.policy_id not in SUPPORTED_POLICIES:
        raise ExecutionOffsetReplayError("UNSUPPORTED_POLICY")
    if not policy.version.strip():
        raise ExecutionOffsetReplayError("POLICY_VERSION_REQUIRED")
    if policy.buffer_pct < 0 or policy.atr_multiple < 0:
        raise ExecutionOffsetReplayError("NEGATIVE_POLICY_PARAMETER")
    if policy.policy_id == POLICY_EXACT_LEVEL and (policy.buffer_pct != 0 or policy.atr_multiple != 0):
        raise ExecutionOffsetReplayError("EXACT_LEVEL_PARAMETERS_MUST_BE_ZERO")
    if policy.policy_id == POLICY_STATIC_BUFFER and policy.buffer_pct <= 0:
        raise ExecutionOffsetReplayError("STATIC_BUFFER_PCT_REQUIRED")
    if policy.policy_id == POLICY_VOLATILITY_SCALED_BUFFER and policy.atr_multiple <= 0:
        raise ExecutionOffsetReplayError("ATR_MULTIPLE_REQUIRED")


def execution_price_for_policy(
    episode: ExecutionOffsetEpisodeV1,
    policy: ExecutionOffsetPolicyV1,
) -> Decimal:
    validate_policy(policy)
    if episode.side not in {SIDE_BUY, SIDE_SELL}:
        raise ExecutionOffsetReplayError("UNSUPPORTED_SIDE")
    if episode.canonical_level <= 0:
        raise ExecutionOffsetReplayError("INVALID_CANONICAL_LEVEL")
    if policy.policy_id == POLICY_EXACT_LEVEL:
        return episode.canonical_level
    if policy.policy_id == POLICY_STATIC_BUFFER:
        delta = episode.canonical_level * policy.buffer_pct
    else:
        if episode.atr_at_issue is None or episode.atr_at_issue <= 0:
            raise ExecutionOffsetReplayError("ATR_REQUIRED_FOR_POLICY")
        delta = episode.atr_at_issue * policy.atr_multiple
    return episode.canonical_level + delta if episode.side == SIDE_BUY else episode.canonical_level - delta

def _validate_episode(episode: ExecutionOffsetEpisodeV1) -> None:
    if not episode.episode_id.strip() or not episode.source_map_id.strip():
        raise ExecutionOffsetReplayError("EPISODE_IDENTITY_REQUIRED")
    if episode.issued_ts_utc.tzinfo is None or episode.valid_until_ts_utc.tzinfo is None:
        raise ExecutionOffsetReplayError("AWARE_TIMESTAMPS_REQUIRED")
    if episode.valid_until_ts_utc <= episode.issued_ts_utc:
        raise ExecutionOffsetReplayError("INVALID_VALIDITY_WINDOW")
    if episode.side not in {SIDE_BUY, SIDE_SELL}:
        raise ExecutionOffsetReplayError("UNSUPPORTED_SIDE")
    if episode.canonical_level <= 0:
        raise ExecutionOffsetReplayError("INVALID_CANONICAL_LEVEL")


def replay_episode(
    episode: ExecutionOffsetEpisodeV1,
    candles: Iterable[ReplayCandle],
    policy: ExecutionOffsetPolicyV1,
) -> ExecutionOffsetReplayRowV1:
    _validate_episode(episode)
    execution_price = execution_price_for_policy(episode, policy)
    future = sorted(
        (c for c in candles if episode.issued_ts_utc < c.close_ts_utc <= episode.valid_until_ts_utc),
        key=lambda c: c.close_ts_utc,
    )
    if not future:
        raise ExecutionOffsetReplayError("NO_FORWARD_CANDLES")
    close_times = [c.close_ts_utc for c in future]
    if len(set(close_times)) != len(close_times):
        raise ExecutionOffsetReplayError("DUPLICATE_FORWARD_CANDLE_TIMESTAMP")

    fill_ts: datetime | None = None
    invalidated_before_fill = False
    touched = False
    closest = None
    post_fill: list[ReplayCandle] = []
    for candle in future:
        raw_touched = candle.low_price <= episode.canonical_level <= candle.high_price
        touched = touched or raw_touched
        if episode.side == SIDE_BUY:
            distance = max(Decimal("0"), candle.low_price - episode.canonical_level)
            fill = candle.low_price <= execution_price
            invalidated = episode.invalidation_price is not None and candle.low_price <= episode.invalidation_price
        else:
            distance = max(Decimal("0"), episode.canonical_level - candle.high_price)
            fill = candle.high_price >= execution_price
            invalidated = episode.invalidation_price is not None and candle.high_price >= episode.invalidation_price
        closest = distance if closest is None else min(closest, distance)
        if fill_ts is None and invalidated:
            invalidated_before_fill = True
            break
        if fill_ts is None and fill:
            fill_ts = candle.close_ts_utc
        if fill_ts is not None:
            post_fill.append(candle)

    near_miss = None if touched else (closest / episode.canonical_level * Decimal("100") if closest is not None else None)
    mfe = mae = None
    if fill_ts is not None and post_fill:
        if episode.side == SIDE_BUY:
            mfe = (max(c.high_price for c in post_fill) - execution_price) / execution_price * Decimal("100")
            mae = (execution_price - min(c.low_price for c in post_fill)) / execution_price * Decimal("100")
        else:
            mfe = (execution_price - min(c.low_price for c in post_fill)) / execution_price * Decimal("100")
            mae = (max(c.high_price for c in post_fill) - execution_price) / execution_price * Decimal("100")

    return ExecutionOffsetReplayRowV1(
        episode_id=episode.episode_id, policy_id=policy.policy_id, policy_version=policy.version,
        canonical_level=episode.canonical_level, execution_price=execution_price,
        touched=touched, filled=fill_ts is not None, near_miss_distance_pct=near_miss,
        time_to_fill_seconds=int((fill_ts - episode.issued_ts_utc).total_seconds()) if fill_ts else None,
        max_favorable_excursion_pct=mfe, max_adverse_excursion_pct=mae,
        invalidated_before_fill=invalidated_before_fill,
    )
