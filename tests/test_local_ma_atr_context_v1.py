from __future__ import annotations

import ast
import dataclasses
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from src.market_context.contracts_v1 import LocalMaAtrState
from src.market_context.local_ma_atr_context_v1 import (
    LocalMaAtrCandle,
    build_local_ma_atr_context,
)


ROOT = Path(__file__).parent.parent
MODULE_PATH = ROOT / "src" / "market_context" / "local_ma_atr_context_v1.py"
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
)


def _ts(index: int) -> datetime:
    return datetime(2026, 6, 1, 0, 0, tzinfo=UTC) + timedelta(minutes=index * 15)


def _candle(
    index: int,
    close: str,
    *,
    high: str | None = None,
    low: str | None = None,
) -> LocalMaAtrCandle:
    close_price = Decimal(close)
    high_price = Decimal(high) if high is not None else close_price + Decimal("0.20")
    low_price = Decimal(low) if low is not None else close_price - Decimal("0.20")
    return LocalMaAtrCandle(
        close_ts_utc=_ts(index),
        high_price=high_price,
        low_price=low_price,
        close_price=close_price,
    )


def _candles(closes: list[str]) -> list[LocalMaAtrCandle]:
    return [_candle(index, close) for index, close in enumerate(closes)]


def _candles_with_wick(closes: list[str], *, wick: str) -> list[LocalMaAtrCandle]:
    width = Decimal(wick)
    candles: list[LocalMaAtrCandle] = []
    for index, close_text in enumerate(closes):
        close_price = Decimal(close_text)
        candles.append(
            LocalMaAtrCandle(
                close_ts_utc=_ts(index),
                high_price=close_price + width,
                low_price=close_price - width,
                close_price=close_price,
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
    empty = build_local_ma_atr_context(candles=[], now_utc=now)
    short = build_local_ma_atr_context(candles=_candles(["10", "11"]), now_utc=now)
    assert empty.state is LocalMaAtrState.NO_DATA
    assert short.state is LocalMaAtrState.NO_DATA


def test_no_data_when_invalid_prices() -> None:
    now = _ts(10)
    candles = [
        _candle(0, "10"),
        _candle(1, "11"),
        _candle(2, "12", high="11", low="12"),
    ]
    result = build_local_ma_atr_context(candles=candles, now_utc=now)
    assert result.state is LocalMaAtrState.NO_DATA


def test_stale_when_latest_candle_too_old() -> None:
    candles = _candles(["10", "11", "12", "13", "14"])
    result = build_local_ma_atr_context(
        candles=candles,
        now_utc=_ts(30),
        stale_after=timedelta(hours=1),
    )
    assert result.state is LocalMaAtrState.STALE


def test_low_confidence_when_warmup_short() -> None:
    candles = _candles(["10", "11", "12", "13", "14"])
    result = build_local_ma_atr_context(
        candles=candles,
        now_utc=_ts(4),
        warmup_candles=10,
    )
    assert result.state is LocalMaAtrState.LOW_CONFIDENCE
    assert result.ma_price is not None
    assert result.atr is not None


def test_low_confidence_when_atr_zero() -> None:
    candles = [_candle(index, "10", high="10", low="10") for index in range(20)]
    result = build_local_ma_atr_context(
        candles=candles,
        now_utc=_ts(19),
        warmup_candles=5,
    )
    assert result.state is LocalMaAtrState.LOW_CONFIDENCE
    assert result.atr == "0"


def test_above_local_ma_when_close_clears_buffer() -> None:
    candles = _candles_with_wick(
        [
            "100", "100", "100", "100", "100", "100", "100", "100", "100", "100",
            "100", "100", "100", "100", "100", "100", "101", "102", "102.4", "102.6",
        ],
        wick="0.5",
    )
    result = build_local_ma_atr_context(
        candles=candles,
        now_utc=_ts(19),
        warmup_candles=10,
    )
    assert result.state is LocalMaAtrState.ABOVE_BREATHLINE
    assert result.distance_atr is not None and Decimal(result.distance_atr) > 0


def test_testing_local_ma_when_candle_overlaps_line() -> None:
    candles = _candles_with_wick(
        [
            "100", "100", "100", "100", "100", "100", "100", "100", "100", "100",
            "100", "100", "100", "100", "100", "100", "101", "102", "102.2",
        ],
        wick="0.5",
    )
    candles.append(_candle(19, "101.7", high="102.0", low="101.2"))
    result = build_local_ma_atr_context(
        candles=candles,
        now_utc=_ts(19),
        warmup_candles=10,
    )
    assert result.state is LocalMaAtrState.TESTING_BREATHLINE


def test_below_local_ma_when_close_breaks_below_buffer() -> None:
    candles = _candles(
        [
            "100", "100", "100", "100", "100", "100", "100", "100", "100", "100",
            "100", "100", "100", "100", "100", "100", "100", "100.5", "100.8",
        ]
    )
    candles.append(_candle(19, "99.8", high="100.0", low="99.5"))
    result = build_local_ma_atr_context(
        candles=candles,
        now_utc=_ts(19),
        warmup_candles=10,
    )
    assert result.state is LocalMaAtrState.BELOW_BREATHLINE


def test_reclaiming_local_ma_beats_testing() -> None:
    candles = _candles_with_wick(
        [
            "100", "100", "100", "100", "100", "100", "100", "100", "100", "100",
            "100", "100", "100", "100", "100", "100", "100.5", "101", "97.5",
        ],
        wick="0.5",
    )
    candles.append(_candle(19, "100.3", high="100.8", low="99.8"))
    result = build_local_ma_atr_context(
        candles=candles,
        now_utc=_ts(19),
        warmup_candles=10,
    )
    assert result.state is LocalMaAtrState.RECLAIMING_BREATHLINE


def test_extended_above_local_ma_beats_above() -> None:
    candles = _candles(
        [
            "100", "100", "100", "100", "100", "100", "100", "100", "100", "100",
            "100", "100", "100", "100", "100", "101", "102", "103", "104", "106",
        ]
    )
    result = build_local_ma_atr_context(
        candles=candles,
        now_utc=_ts(19),
        warmup_candles=10,
    )
    assert result.state is LocalMaAtrState.EXTENDED_ABOVE_BREATHLINE


def test_spike_cooling_beats_extended_when_fading() -> None:
    candles = _candles(
        [
            "100", "100", "100", "100", "100", "100", "100", "100", "100", "100",
            "100", "100", "100", "100", "100", "100", "101", "106", "105", "102",
        ]
    )
    result = build_local_ma_atr_context(
        candles=candles,
        now_utc=_ts(19),
        warmup_candles=10,
    )
    assert result.state is LocalMaAtrState.SPIKE_COOLING


def test_result_is_json_safe_using_enum_values() -> None:
    candles = _candles(["100", "100", "100", "100", "100"])
    result = build_local_ma_atr_context(
        candles=candles,
        now_utc=_ts(4),
        warmup_candles=10,
    )
    payload = dataclasses.asdict(result)
    json.dumps(payload)


def test_module_has_no_forbidden_imports() -> None:
    imports = _imports_for(MODULE_PATH)
    for imported in imports:
        for fragment in FORBIDDEN_IMPORT_FRAGMENTS:
            assert fragment not in imported, f"forbidden import fragment {fragment!r} found in {imported!r}"
