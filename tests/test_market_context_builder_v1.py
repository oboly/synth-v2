from __future__ import annotations

import ast
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from src.market_context.contracts_v1 import LocalMaAtrState, ImpulseHealthState
from src.market_context.impulse_health_state_v1 import ImpulseHealthStateResult
from src.market_context.local_ma_atr_context_v1 import LocalMaAtrContextResult
from src.market_context.market_context_builder_v1 import (
    EXTENSION_CONTEXT_ACTIVE,
    EXTENSION_CONTEXT_BUILDING,
    EXTENSION_CONTEXT_EXHAUSTED,
    EXTENSION_CONTEXT_NO_CHASE,
    EXTENSION_CONTEXT_NO_DATA,
    EXTENSION_CONTEXT_SETUP,
    PROFIT_PLAN_BIAS_AVOID_CHASE,
    PROFIT_PLAN_BIAS_NONE,
    PROFIT_PLAN_BIAS_PREPARE_SELLS,
    PROFIT_PLAN_BIAS_SELL_INTO_EXTENSION,
    PROFIT_PLAN_BIAS_WAIT_FOR_PULLBACK,
    MarketContextCandle,
    build_extension_context,
    build_market_context_by_symbol,
    build_market_context_for_symbol,
)

ROOT = Path(__file__).parent.parent
MODULE_PATH = ROOT / "src" / "market_context" / "market_context_builder_v1.py"

FORBIDDEN_IMPORT_FRAGMENTS = (
    "decision_gate",
    "execution_planner",
    "executor",
    "agents",
    "broker",
    "account",
    "balance",
    "reporting",
    "dashboard",
    "view",
    "fib_navigation",
)


def _ts(index: int) -> datetime:
    return datetime(2026, 6, 1, 0, 0, tzinfo=UTC) + timedelta(hours=index * 4)


def _candle(
    index: int,
    open_price: str,
    high_price: str,
    low_price: str,
    close_price: str,
) -> MarketContextCandle:
    return MarketContextCandle(
        close_ts_utc=_ts(index),
        open_price=Decimal(open_price),
        high_price=Decimal(high_price),
        low_price=Decimal(low_price),
        close_price=Decimal(close_price),
    )


def _flat_seed(length: int = 20, price: str = "100.0") -> list[MarketContextCandle]:
    p = Decimal(price)
    return [
        MarketContextCandle(
            close_ts_utc=_ts(i),
            open_price=p,
            high_price=p + Decimal("0.5"),
            low_price=p - Decimal("0.5"),
            close_price=p,
        )
        for i in range(length)
    ]


def _local_ma_atr_result(state: LocalMaAtrState) -> LocalMaAtrContextResult:
    return LocalMaAtrContextResult(
        state=state,
        ma_price=None,
        atr=None,
        distance_atr=None,
        latest_close_ts_utc=None,
        warnings=(),
    )


def _impulse_result(state: ImpulseHealthState) -> ImpulseHealthStateResult:
    return ImpulseHealthStateResult(
        state=state,
        ema_price=None,
        atr=None,
        swing_high_price=None,
        distance_atr=None,
        pullback_from_high_atr=None,
        latest_close_ts_utc=None,
        warnings=(),
    )


def _imports_for(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.append(node.module)
                for alias in node.names:
                    names.append(f"{node.module}.{alias.name}")
            for alias in node.names:
                names.append(alias.name)
    return names


# ---------------------------------------------------------------------------
# build_market_context_for_symbol — integration (no DB)
# ---------------------------------------------------------------------------

def test_json_safe_for_valid_candles() -> None:
    candles = _flat_seed(20)
    result = build_market_context_for_symbol(candles=candles, now_utc=_ts(19))
    json.dumps(result)


def test_output_has_all_three_keys() -> None:
    result = build_market_context_for_symbol(candles=_flat_seed(20), now_utc=_ts(19))
    assert "local_ma_atr_context" in result
    assert "impulse_health" in result
    assert "extension_context" in result


def test_state_values_are_strings() -> None:
    result = build_market_context_for_symbol(candles=_flat_seed(20), now_utc=_ts(19))
    assert isinstance(result["local_ma_atr_context"]["state"], str)
    assert isinstance(result["impulse_health"]["state"], str)
    assert isinstance(result["extension_context"]["state"], str)


def test_no_data_on_empty_candles() -> None:
    result = build_market_context_for_symbol(candles=[], now_utc=_ts(0))
    assert result["local_ma_atr_context"]["state"] == "NO_DATA"
    assert result["impulse_health"]["state"] == "NO_DATA"
    assert result["extension_context"]["state"] == EXTENSION_CONTEXT_NO_DATA


def test_no_data_on_insufficient_candles() -> None:
    result = build_market_context_for_symbol(candles=_flat_seed(1), now_utc=_ts(0))
    assert result["local_ma_atr_context"]["state"] == "NO_DATA"
    assert result["impulse_health"]["state"] == "NO_DATA"


def test_stale_on_old_candles() -> None:
    candles = _flat_seed(20)
    result = build_market_context_for_symbol(
        candles=candles,
        now_utc=_ts(19) + timedelta(days=10),
    )
    assert result["local_ma_atr_context"]["state"] == "STALE"
    assert result["extension_context"]["state"] == EXTENSION_CONTEXT_NO_DATA


def test_no_data_missing_close_ts() -> None:
    candles = _flat_seed()
    candles[5] = MarketContextCandle(
        close_ts_utc=None,  # type: ignore[arg-type]
        open_price=Decimal("100"),
        high_price=Decimal("100.5"),
        low_price=Decimal("99.5"),
        close_price=Decimal("100"),
    )
    result = build_market_context_for_symbol(candles=candles, now_utc=_ts(19))
    assert result["impulse_health"]["state"] == "NO_DATA"
    assert "INVALID_CANDLE_DATA" in result["impulse_health"]["warnings"]


def test_no_data_missing_price_field() -> None:
    candles = _flat_seed()
    candles[0] = MarketContextCandle(
        close_ts_utc=_ts(0),
        open_price=None,  # type: ignore[arg-type]
        high_price=Decimal("100.5"),
        low_price=Decimal("99.5"),
        close_price=Decimal("100"),
    )
    result = build_market_context_for_symbol(candles=candles, now_utc=_ts(19))
    assert result["impulse_health"]["state"] == "NO_DATA"


def test_no_data_non_positive_ohlc() -> None:
    candles = _flat_seed()
    candles[-1] = MarketContextCandle(
        close_ts_utc=_ts(19),
        open_price=Decimal("0"),
        high_price=Decimal("100.5"),
        low_price=Decimal("99.5"),
        close_price=Decimal("100"),
    )
    result = build_market_context_for_symbol(candles=candles, now_utc=_ts(19))
    assert result["impulse_health"]["state"] == "NO_DATA"


def test_no_data_invalid_ohlc_order() -> None:
    candles = _flat_seed()
    candles[-1] = _candle(19, "100", "99", "100", "100")
    result = build_market_context_for_symbol(candles=candles, now_utc=_ts(19))
    assert result["impulse_health"]["state"] == "NO_DATA"


def test_zero_atr_flat_candles() -> None:
    candles = [
        MarketContextCandle(
            close_ts_utc=_ts(i),
            open_price=Decimal("100"),
            high_price=Decimal("100"),
            low_price=Decimal("100"),
            close_price=Decimal("100"),
        )
        for i in range(20)
    ]
    result = build_market_context_for_symbol(candles=candles, now_utc=_ts(19))
    assert result["impulse_health"]["state"] == "LOW_CONFIDENCE"
    assert result["extension_context"]["state"] == EXTENSION_CONTEXT_NO_DATA


def test_warnings_are_sequences() -> None:
    # dataclasses.asdict() keeps string tuples as tuples; extension_context warnings
    # are built as a plain list. Both are JSON-safe — json.dumps handles tuple and list.
    result = build_market_context_for_symbol(candles=[], now_utc=_ts(0))
    assert hasattr(result["local_ma_atr_context"]["warnings"], "__iter__")
    assert hasattr(result["impulse_health"]["warnings"], "__iter__")
    assert isinstance(result["extension_context"]["warnings"], list)
    # JSON-safety covered by test_json_safe_for_valid_candles


# ---------------------------------------------------------------------------
# build_extension_context — unit tests using injected results
# ---------------------------------------------------------------------------

def test_extension_active_on_extended_states() -> None:
    b = _local_ma_atr_result(LocalMaAtrState.EXTENDED_ABOVE_BREATHLINE)
    i = _impulse_result(ImpulseHealthState.EXTENDED_IMPULSE)
    ec = build_extension_context(b, i)
    assert ec["state"] == EXTENSION_CONTEXT_ACTIVE
    assert ec["suggested_profit_plan_bias"] == PROFIT_PLAN_BIAS_SELL_INTO_EXTENSION


def test_extension_no_chase_on_blow_off() -> None:
    b = _local_ma_atr_result(LocalMaAtrState.ABOVE_BREATHLINE)
    i = _impulse_result(ImpulseHealthState.BLOW_OFF_SPIKE)
    ec = build_extension_context(b, i)
    assert ec["state"] == EXTENSION_CONTEXT_NO_CHASE
    assert ec["suggested_profit_plan_bias"] == PROFIT_PLAN_BIAS_AVOID_CHASE


def test_extension_exhausted_on_spike_cooling() -> None:
    b = _local_ma_atr_result(LocalMaAtrState.SPIKE_COOLING)
    i = _impulse_result(ImpulseHealthState.HEALTHY_IMPULSE)
    ec = build_extension_context(b, i)
    assert ec["state"] == EXTENSION_CONTEXT_EXHAUSTED
    assert ec["suggested_profit_plan_bias"] == PROFIT_PLAN_BIAS_AVOID_CHASE


def test_extension_exhausted_on_distribution_risk() -> None:
    b = _local_ma_atr_result(LocalMaAtrState.EXTENDED_ABOVE_BREATHLINE)
    i = _impulse_result(ImpulseHealthState.DISTRIBUTION_RISK)
    ec = build_extension_context(b, i)
    assert ec["state"] == EXTENSION_CONTEXT_EXHAUSTED


def test_extension_setup_on_extended_local_ma_other_impulse() -> None:
    b = _local_ma_atr_result(LocalMaAtrState.EXTENDED_ABOVE_BREATHLINE)
    i = _impulse_result(ImpulseHealthState.HEALTHY_IMPULSE)
    ec = build_extension_context(b, i)
    assert ec["state"] == EXTENSION_CONTEXT_SETUP
    assert ec["suggested_profit_plan_bias"] == PROFIT_PLAN_BIAS_SELL_INTO_EXTENSION


def test_extension_setup_on_above_extended_impulse() -> None:
    b = _local_ma_atr_result(LocalMaAtrState.ABOVE_BREATHLINE)
    i = _impulse_result(ImpulseHealthState.EXTENDED_IMPULSE)
    ec = build_extension_context(b, i)
    assert ec["state"] == EXTENSION_CONTEXT_SETUP


def test_extension_building_on_reclaiming_local_ma() -> None:
    b = _local_ma_atr_result(LocalMaAtrState.RECLAIMING_BREATHLINE)
    i = _impulse_result(ImpulseHealthState.HEALTHY_IMPULSE)
    ec = build_extension_context(b, i)
    assert ec["state"] == EXTENSION_CONTEXT_BUILDING
    assert ec["suggested_profit_plan_bias"] == PROFIT_PLAN_BIAS_PREPARE_SELLS


def test_extension_wait_for_pullback_on_below_local_ma() -> None:
    b = _local_ma_atr_result(LocalMaAtrState.BELOW_BREATHLINE)
    i = _impulse_result(ImpulseHealthState.HEALTHY_IMPULSE)
    ec = build_extension_context(b, i)
    assert ec["state"] == EXTENSION_CONTEXT_NO_DATA
    assert ec["suggested_profit_plan_bias"] == PROFIT_PLAN_BIAS_WAIT_FOR_PULLBACK


def test_extension_wait_for_pullback_on_failed_reclaim() -> None:
    b = _local_ma_atr_result(LocalMaAtrState.ABOVE_BREATHLINE)
    i = _impulse_result(ImpulseHealthState.FAILED_RECLAIM)
    ec = build_extension_context(b, i)
    assert ec["state"] == EXTENSION_CONTEXT_NO_DATA
    assert ec["suggested_profit_plan_bias"] == PROFIT_PLAN_BIAS_WAIT_FOR_PULLBACK


def test_extension_no_data_when_local_ma_stale() -> None:
    b = _local_ma_atr_result(LocalMaAtrState.STALE)
    i = _impulse_result(ImpulseHealthState.HEALTHY_IMPULSE)
    ec = build_extension_context(b, i)
    assert ec["state"] == EXTENSION_CONTEXT_NO_DATA
    assert ec["suggested_profit_plan_bias"] == PROFIT_PLAN_BIAS_NONE


def test_extension_no_data_when_impulse_stale() -> None:
    b = _local_ma_atr_result(LocalMaAtrState.ABOVE_BREATHLINE)
    i = _impulse_result(ImpulseHealthState.STALE)
    ec = build_extension_context(b, i)
    assert ec["state"] == EXTENSION_CONTEXT_NO_DATA


# ---------------------------------------------------------------------------
# build_market_context_by_symbol
# ---------------------------------------------------------------------------

def test_by_symbol_multiple() -> None:
    result = build_market_context_by_symbol(
        candles_by_symbol={"BTC": _flat_seed(20), "ETH": _flat_seed(20)},
        now_utc=_ts(19),
    )
    assert set(result.keys()) == {"BTC", "ETH"}
    for sym in result:
        assert "local_ma_atr_context" in result[sym]
        assert "impulse_health" in result[sym]
        assert "extension_context" in result[sym]


def test_by_symbol_empty_candle_list_returns_no_data_context() -> None:
    result = build_market_context_by_symbol(
        candles_by_symbol={"BTC": [], "ETH": _flat_seed(20)},
        now_utc=_ts(19),
    )
    assert set(result.keys()) == {"BTC", "ETH"}
    assert result["BTC"]["local_ma_atr_context"]["state"] == "NO_DATA"
    assert result["BTC"]["impulse_health"]["state"] == "NO_DATA"
    assert result["BTC"]["extension_context"]["state"] == EXTENSION_CONTEXT_NO_DATA


def test_market_context_does_not_expose_legacy_breathline_key() -> None:
    result = build_market_context_for_symbol(candles=_flat_seed(20), now_utc=_ts(19))
    assert "breathline" not in result


def test_by_symbol_empty_dict() -> None:
    result = build_market_context_by_symbol(candles_by_symbol={}, now_utc=_ts(0))
    assert result == {}


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

def test_constants_are_json_safe_strings() -> None:
    constants = [
        EXTENSION_CONTEXT_NO_DATA,
        EXTENSION_CONTEXT_BUILDING,
        EXTENSION_CONTEXT_SETUP,
        EXTENSION_CONTEXT_ACTIVE,
        EXTENSION_CONTEXT_EXHAUSTED,
        EXTENSION_CONTEXT_NO_CHASE,
        PROFIT_PLAN_BIAS_NONE,
        PROFIT_PLAN_BIAS_PREPARE_SELLS,
        PROFIT_PLAN_BIAS_SELL_INTO_EXTENSION,
        PROFIT_PLAN_BIAS_WAIT_FOR_PULLBACK,
        PROFIT_PLAN_BIAS_AVOID_CHASE,
    ]
    for c in constants:
        assert isinstance(c, str)
        json.dumps(c)


# ---------------------------------------------------------------------------
# Architecture guard
# ---------------------------------------------------------------------------

def test_module_has_no_forbidden_imports() -> None:
    imports = _imports_for(MODULE_PATH)
    for imported in imports:
        for fragment in FORBIDDEN_IMPORT_FRAGMENTS:
            assert fragment not in imported, (
                f"forbidden import fragment {fragment!r} found in {imported!r}"
            )
