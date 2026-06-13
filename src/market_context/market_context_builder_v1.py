from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Sequence

from src.market_context.breathline_state_v1 import (
    BreathlineCandle,
    BreathlineStateResult,
    build_breathline_state,
)
from src.market_context.contracts_v1 import BreathlineState, ImpulseHealthState
from src.market_context.impulse_health_state_v1 import (
    ImpulseHealthCandle,
    ImpulseHealthStateResult,
    build_impulse_health_state,
)

# ---------------------------------------------------------------------------
# Extension context state constants (display artifact — not core contracts)
# ---------------------------------------------------------------------------

EXTENSION_CONTEXT_NO_DATA = "NO_DATA"
EXTENSION_CONTEXT_BUILDING = "BUILDING"
EXTENSION_CONTEXT_SETUP = "EXTENSION_SETUP"
EXTENSION_CONTEXT_ACTIVE = "EXTENSION_ACTIVE"
EXTENSION_CONTEXT_EXHAUSTED = "EXTENSION_EXHAUSTED"
EXTENSION_CONTEXT_NO_CHASE = "NO_CHASE"

# Suggested profit plan bias constants
# Read-only display hint — NOT execution intent, NOT order advice, NOT account-aware.
PROFIT_PLAN_BIAS_NONE = "NONE"
PROFIT_PLAN_BIAS_PREPARE_SELLS = "PREPARE_SELLS"
PROFIT_PLAN_BIAS_SELL_INTO_EXTENSION = "SELL_INTO_EXTENSION"
PROFIT_PLAN_BIAS_WAIT_FOR_PULLBACK = "WAIT_FOR_PULLBACK"
PROFIT_PLAN_BIAS_AVOID_CHASE = "AVOID_CHASE"

_SENTINEL_STATES: frozenset[str] = frozenset({"NO_DATA", "STALE", "LOW_CONFIDENCE"})

_WAIT_BREATHLINE_STATES: frozenset[str] = frozenset({
    BreathlineState.TESTING_BREATHLINE,
    BreathlineState.BELOW_BREATHLINE,
})

_BUILDING_IMPULSE_STATES: frozenset[str] = frozenset({
    ImpulseHealthState.EARLY_IMPULSE,
    ImpulseHealthState.HEALTHY_IMPULSE,
    ImpulseHealthState.COOLING_PULLBACK,
    ImpulseHealthState.SECOND_BUMP_POSSIBLE,
})


@dataclass(frozen=True)
class MarketContextCandle:
    close_ts_utc: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal


def build_extension_context(
    breathline_result: BreathlineStateResult,
    impulse_result: ImpulseHealthStateResult,
) -> dict[str, Any]:
    """
    Combine breathline + impulse health into a read-only display context.

    Read-only market/reporting context.
    Not execution intent. Not order advice. Not account-aware.
    suggested_profit_plan_bias is a display hint only and must never reach
    decision_gate, execution_planner, or executor.
    """
    b_state = str(breathline_result.state)
    i_state = str(impulse_result.state)

    # Degrade gracefully when either builder lacks reliable data.
    if b_state in _SENTINEL_STATES or i_state in _SENTINEL_STATES:
        return {
            "state": EXTENSION_CONTEXT_NO_DATA,
            "label": "Insufficient data",
            "suggested_profit_plan_bias": PROFIT_PLAN_BIAS_NONE,
            "warnings": [],
        }

    # Blow-off — highest priority caution signal regardless of breathline.
    if i_state == ImpulseHealthState.BLOW_OFF_SPIKE:
        return {
            "state": EXTENSION_CONTEXT_NO_CHASE,
            "label": "Blow-off — no chase",
            "suggested_profit_plan_bias": PROFIT_PLAN_BIAS_AVOID_CHASE,
            "warnings": [],
        }

    # Spike cooling — breathline-level exhaustion signal.
    if b_state == BreathlineState.SPIKE_COOLING:
        return {
            "state": EXTENSION_CONTEXT_EXHAUSTED,
            "label": "Spike cooling — avoid chase",
            "suggested_profit_plan_bias": PROFIT_PLAN_BIAS_AVOID_CHASE,
            "warnings": [],
        }

    # Distribution risk while extended — extension topped out.
    if (
        b_state == BreathlineState.EXTENDED_ABOVE_BREATHLINE
        and i_state == ImpulseHealthState.DISTRIBUTION_RISK
    ):
        return {
            "state": EXTENSION_CONTEXT_EXHAUSTED,
            "label": "Extension exhausted — avoid chase",
            "suggested_profit_plan_bias": PROFIT_PLAN_BIAS_AVOID_CHASE,
            "warnings": [],
        }

    # Both extended — active extension, consider selling into strength.
    if (
        b_state == BreathlineState.EXTENDED_ABOVE_BREATHLINE
        and i_state == ImpulseHealthState.EXTENDED_IMPULSE
    ):
        return {
            "state": EXTENSION_CONTEXT_ACTIVE,
            "label": "Extension active — sell into strength",
            "suggested_profit_plan_bias": PROFIT_PLAN_BIAS_SELL_INTO_EXTENSION,
            "warnings": [],
        }

    # Breathline extended with any other healthy impulse — setup phase.
    if b_state == BreathlineState.EXTENDED_ABOVE_BREATHLINE:
        return {
            "state": EXTENSION_CONTEXT_SETUP,
            "label": "Extension setup — prepare sell targets",
            "suggested_profit_plan_bias": PROFIT_PLAN_BIAS_SELL_INTO_EXTENSION,
            "warnings": [],
        }

    # Above breathline with extended impulse — extension forming.
    if (
        b_state == BreathlineState.ABOVE_BREATHLINE
        and i_state == ImpulseHealthState.EXTENDED_IMPULSE
    ):
        return {
            "state": EXTENSION_CONTEXT_SETUP,
            "label": "Extended impulse above breathline",
            "suggested_profit_plan_bias": PROFIT_PLAN_BIAS_SELL_INTO_EXTENSION,
            "warnings": [],
        }

    # Reclaiming or above breathline with building impulse — prepare sell side.
    if b_state in {BreathlineState.RECLAIMING_BREATHLINE, BreathlineState.ABOVE_BREATHLINE}:
        if i_state in _BUILDING_IMPULSE_STATES:
            return {
                "state": EXTENSION_CONTEXT_BUILDING,
                "label": "Building impulse — prepare sell targets",
                "suggested_profit_plan_bias": PROFIT_PLAN_BIAS_PREPARE_SELLS,
                "warnings": [],
            }

    # Wait states — breathline breakdown or failed impulse reclaim.
    if b_state in _WAIT_BREATHLINE_STATES or i_state == ImpulseHealthState.FAILED_RECLAIM:
        return {
            "state": EXTENSION_CONTEXT_NO_DATA,
            "label": "Wait for pullback to breathline",
            "suggested_profit_plan_bias": PROFIT_PLAN_BIAS_WAIT_FOR_PULLBACK,
            "warnings": [],
        }

    return {
        "state": EXTENSION_CONTEXT_BUILDING,
        "label": "Context building",
        "suggested_profit_plan_bias": PROFIT_PLAN_BIAS_NONE,
        "warnings": [],
    }


def build_market_context_for_symbol(
    *,
    candles: Sequence[MarketContextCandle],
    now_utc: datetime,
) -> dict[str, Any]:
    breathline_candles = [
        BreathlineCandle(
            close_ts_utc=c.close_ts_utc,
            high_price=c.high_price,
            low_price=c.low_price,
            close_price=c.close_price,
        )
        for c in candles
    ]
    impulse_candles = [
        ImpulseHealthCandle(
            close_ts_utc=c.close_ts_utc,
            open_price=c.open_price,
            high_price=c.high_price,
            low_price=c.low_price,
            close_price=c.close_price,
        )
        for c in candles
    ]
    breathline_result = build_breathline_state(candles=breathline_candles, now_utc=now_utc)
    impulse_result = build_impulse_health_state(candles=impulse_candles, now_utc=now_utc)
    return {
        "breathline": dataclasses.asdict(breathline_result),
        "impulse_health": dataclasses.asdict(impulse_result),
        "extension_context": build_extension_context(breathline_result, impulse_result),
    }


def build_market_context_by_symbol(
    *,
    candles_by_symbol: dict[str, Sequence[MarketContextCandle]],
    now_utc: datetime,
) -> dict[str, dict[str, Any]]:
    return {
        symbol: build_market_context_for_symbol(candles=candles, now_utc=now_utc)
        for symbol, candles in candles_by_symbol.items()
    }
