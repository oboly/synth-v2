from __future__ import annotations

import ast
import dataclasses
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from src.market_context.contracts_v1 import ImpulseHealthState
from src.market_context.impulse_health_state_v1 import (
    ImpulseHealthCandle,
    build_impulse_health_state,
)


ROOT = Path(__file__).parent.parent
MODULE_PATH = ROOT / "src" / "market_context" / "impulse_health_state_v1.py"
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
    "breathline_state_v1",
    "fib_navigation",
)


def _ts(index: int) -> datetime:
    return datetime(2026, 6, 1, 0, 0, tzinfo=UTC) + timedelta(minutes=index * 15)


def _candle(
    index: int,
    open_price: str,
    high_price: str,
    low_price: str,
    close_price: str,
) -> ImpulseHealthCandle:
    return ImpulseHealthCandle(
        close_ts_utc=_ts(index),
        open_price=Decimal(open_price),
        high_price=Decimal(high_price),
        low_price=Decimal(low_price),
        close_price=Decimal(close_price),
    )


def _flat_seed(length: int = 16, price: str = "100.0") -> list[ImpulseHealthCandle]:
    price_decimal = Decimal(price)
    candles: list[ImpulseHealthCandle] = []
    for index in range(length):
        candles.append(
            ImpulseHealthCandle(
                close_ts_utc=_ts(index),
                open_price=price_decimal,
                high_price=price_decimal + Decimal("0.5"),
                low_price=price_decimal - Decimal("0.5"),
                close_price=price_decimal,
            )
        )
    return candles


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


def test_no_data_when_empty_or_too_short() -> None:
    now = _ts(10)
    empty = build_impulse_health_state(candles=[], now_utc=now)
    short = build_impulse_health_state(candles=_flat_seed(2), now_utc=now)
    assert empty.state is ImpulseHealthState.NO_DATA
    assert short.state is ImpulseHealthState.NO_DATA


def test_no_data_when_invalid_parameters() -> None:
    result = build_impulse_health_state(
        candles=_flat_seed(),
        now_utc=_ts(15),
        ema_span=0,
    )
    assert result.state is ImpulseHealthState.NO_DATA
    assert result.warnings == ("INVALID_PARAMETERS",)


def test_no_data_when_invalid_ohlc_shapes() -> None:
    invalid_high_low = _flat_seed()
    invalid_high_low[-1] = _candle(15, "100", "99", "100", "100")
    result_high_low = build_impulse_health_state(candles=invalid_high_low, now_utc=_ts(15))
    assert result_high_low.state is ImpulseHealthState.NO_DATA

    invalid_high_body = _flat_seed()
    invalid_high_body[-1] = _candle(15, "100", "100.1", "99.5", "100.2")
    result_high_body = build_impulse_health_state(candles=invalid_high_body, now_utc=_ts(15))
    assert result_high_body.state is ImpulseHealthState.NO_DATA

    invalid_low_body = _flat_seed()
    invalid_low_body[-1] = _candle(15, "100", "100.5", "100.1", "99.8")
    result_low_body = build_impulse_health_state(candles=invalid_low_body, now_utc=_ts(15))
    assert result_low_body.state is ImpulseHealthState.NO_DATA


def test_stale_when_latest_candle_too_old() -> None:
    candles = _flat_seed()
    result = build_impulse_health_state(
        candles=candles,
        now_utc=_ts(40),
        stale_after=timedelta(hours=1),
    )
    assert result.state is ImpulseHealthState.STALE


def test_low_confidence_when_warmup_short() -> None:
    candles = _flat_seed(6)
    result = build_impulse_health_state(
        candles=candles,
        now_utc=_ts(5),
        warmup_candles=10,
    )
    assert result.state is ImpulseHealthState.LOW_CONFIDENCE
    assert result.warnings == ("WARMUP_SHORT",)
    assert result.ema_price is not None


def test_low_confidence_when_atr_zero() -> None:
    candles = [
        ImpulseHealthCandle(
            close_ts_utc=_ts(index),
            open_price=Decimal("100"),
            high_price=Decimal("100"),
            low_price=Decimal("100"),
            close_price=Decimal("100"),
        )
        for index in range(20)
    ]
    result = build_impulse_health_state(
        candles=candles,
        now_utc=_ts(19),
        warmup_candles=5,
    )
    assert result.state is ImpulseHealthState.LOW_CONFIDENCE
    assert result.atr == "0"


def test_blow_off_spike_beats_extended() -> None:
    candles = _flat_seed()
    candles.extend(
        [
            _candle(16, "100.5", "102.0", "100.3", "101.8"),
            _candle(17, "101.8", "103.5", "101.2", "103.0"),
            _candle(18, "103.0", "107.5", "102.8", "104.2"),
        ]
    )
    result = build_impulse_health_state(
        candles=candles,
        now_utc=_ts(18),
        warmup_candles=10,
    )
    assert result.state is ImpulseHealthState.BLOW_OFF_SPIKE


def test_distribution_risk_after_recent_blow_off() -> None:
    candles = _flat_seed()
    candles.extend(
        [
            _candle(16, "100.5", "102.0", "100.3", "101.8"),
            _candle(17, "101.8", "103.5", "101.2", "103.0"),
            _candle(18, "103.0", "107.5", "102.8", "104.2"),
            _candle(19, "104.2", "105.7", "103.6", "104.0"),
            _candle(20, "104.0", "105.5", "103.3", "103.7"),
        ]
    )
    result = build_impulse_health_state(
        candles=candles,
        now_utc=_ts(20),
        warmup_candles=10,
    )
    assert result.state is ImpulseHealthState.DISTRIBUTION_RISK


def test_failed_reclaim_beats_healthy() -> None:
    candles = _flat_seed()
    candles.extend(
        [
            _candle(16, "100.0", "100.3", "98.4", "98.8"),
            _candle(17, "98.9", "100.4", "98.7", "99.0"),
        ]
    )
    result = build_impulse_health_state(
        candles=candles,
        now_utc=_ts(17),
        warmup_candles=10,
    )
    assert result.state is ImpulseHealthState.FAILED_RECLAIM


def test_second_bump_possible_beats_cooling_pullback() -> None:
    candles = _flat_seed()
    candles.extend(
        [
            _candle(16, "100.2", "102.1", "100.0", "101.8"),
            _candle(17, "101.8", "103.9", "101.5", "103.5"),
            _candle(18, "103.4", "105.4", "103.1", "104.8"),
            _candle(19, "104.7", "105.0", "103.1", "103.4"),
            _candle(20, "103.4", "104.0", "102.7", "103.0"),
            _candle(21, "103.0", "104.1", "102.9", "103.6"),
            _candle(22, "103.6", "104.6", "103.3", "104.2"),
        ]
    )
    result = build_impulse_health_state(
        candles=candles,
        now_utc=_ts(22),
        warmup_candles=10,
    )
    assert result.state is ImpulseHealthState.SECOND_BUMP_POSSIBLE


def test_cooling_pullback_path() -> None:
    candles = _flat_seed()
    candles.extend(
        [
            _candle(16, "100.2", "102.0", "100.0", "101.7"),
            _candle(17, "101.7", "103.6", "101.4", "103.2"),
            _candle(18, "103.2", "104.9", "102.9", "104.6"),
            _candle(19, "104.5", "104.8", "103.0", "103.5"),
            _candle(20, "103.5", "103.8", "102.9", "103.2"),
        ]
    )
    result = build_impulse_health_state(
        candles=candles,
        now_utc=_ts(20),
        warmup_candles=10,
    )
    assert result.state is ImpulseHealthState.COOLING_PULLBACK


def test_extended_impulse_path() -> None:
    candles = _flat_seed()
    candles.extend(
        [
            _candle(16, "100.5", "102.0", "100.3", "101.8"),
            _candle(17, "101.8", "103.8", "101.6", "103.4"),
            _candle(18, "103.4", "105.9", "103.1", "105.6"),
        ]
    )
    result = build_impulse_health_state(
        candles=candles,
        now_utc=_ts(18),
        warmup_candles=10,
    )
    assert result.state is ImpulseHealthState.EXTENDED_IMPULSE


def test_early_impulse_path() -> None:
    candles = _flat_seed()
    candles.extend(
        [
            _candle(16, "100.1", "100.7", "99.9", "100.5"),
            _candle(17, "100.5", "100.85", "100.3", "100.65"),
        ]
    )
    result = build_impulse_health_state(
        candles=candles,
        now_utc=_ts(17),
        warmup_candles=10,
    )
    assert result.state is ImpulseHealthState.EARLY_IMPULSE


def test_healthy_impulse_default_path() -> None:
    candles = _flat_seed()
    candles.extend(
        [
            _candle(16, "100.2", "101.2", "100.0", "100.9"),
            _candle(17, "100.9", "102.1", "100.7", "101.7"),
            _candle(18, "101.7", "103.0", "101.5", "102.6"),
        ]
    )
    result = build_impulse_health_state(
        candles=candles,
        now_utc=_ts(18),
        warmup_candles=10,
    )
    assert result.state is ImpulseHealthState.HEALTHY_IMPULSE


def test_result_is_json_safe_using_enum_values() -> None:
    result = build_impulse_health_state(
        candles=_flat_seed(6),
        now_utc=_ts(5),
        warmup_candles=10,
    )
    payload = dataclasses.asdict(result)
    json.dumps(payload)


def test_no_data_when_missing_close_ts() -> None:
    # Without fix: sorted() raises TypeError on None close_ts_utc.
    candles = _flat_seed()
    candles[5] = ImpulseHealthCandle(
        close_ts_utc=None,  # type: ignore[arg-type]
        open_price=Decimal("100"),
        high_price=Decimal("100.5"),
        low_price=Decimal("99.5"),
        close_price=Decimal("100"),
    )
    result = build_impulse_health_state(candles=candles, now_utc=_ts(15))
    assert result.state is ImpulseHealthState.NO_DATA
    assert "INVALID_CANDLE_DATA" in result.warnings


def test_no_data_when_missing_price_field() -> None:
    # 2 candles (< absolute_min_candles=3) with open_price=None.
    # Without fix: max() on close_ts_utc succeeds and INSUFFICIENT_CANDLES is
    # returned before the price-field check fires.
    # With fix: field presence check fires first → INVALID_CANDLE_DATA.
    bad = ImpulseHealthCandle(
        close_ts_utc=_ts(0),
        open_price=None,  # type: ignore[arg-type]
        high_price=Decimal("100.5"),
        low_price=Decimal("99.5"),
        close_price=Decimal("100"),
    )
    result = build_impulse_health_state(
        candles=[bad, _candle(1, "100", "100.5", "99.5", "100")],
        now_utc=_ts(5),
    )
    assert result.state is ImpulseHealthState.NO_DATA
    assert "INVALID_CANDLE_DATA" in result.warnings


def test_no_data_when_non_positive_ohlc_prices() -> None:
    candles = _flat_seed()
    candles[-1] = ImpulseHealthCandle(
        close_ts_utc=_ts(15),
        open_price=Decimal("0"),
        high_price=Decimal("100.5"),
        low_price=Decimal("99.5"),
        close_price=Decimal("100"),
    )
    result = build_impulse_health_state(candles=candles, now_utc=_ts(15))
    assert result.state is ImpulseHealthState.NO_DATA
    assert "INVALID_CANDLE_DATA" in result.warnings


def test_module_has_no_forbidden_imports() -> None:
    imports = _imports_for(MODULE_PATH)
    for imported in imports:
        for fragment in FORBIDDEN_IMPORT_FRAGMENTS:
            assert fragment not in imported, f"forbidden import fragment {fragment!r} found in {imported!r}"
