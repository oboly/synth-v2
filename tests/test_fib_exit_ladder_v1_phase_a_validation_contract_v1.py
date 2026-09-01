"""Tests for Issue #270 Phase A frozen validation contract.

Covers: frozen bucket/target-family definitions, deterministic and
repeatable core logic against synthetic (non-DB) candle input, no-look-ahead
in the anchor detector, no account-awareness, no production-layer imports,
and rejection of non-read SQL. Does not require DB access; the actual
Phase A run against real historical data is BLOCKED per
docs/research/fib_exit_ladder_v1_phase_a_validation_findings_v1.md.
"""
from __future__ import annotations

import ast
import re
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from src.research import run_fib_exit_ladder_backtest_v1 as ladder_bt
from src.research import run_fib_exit_ladder_scoreboard_v1 as ladder_sb

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKTEST_MODULE_PATH = REPO_ROOT / "src/research/run_fib_exit_ladder_backtest_v1.py"
SCOREBOARD_MODULE_PATH = REPO_ROOT / "src/research/run_fib_exit_ladder_scoreboard_v1.py"

FORBIDDEN_IMPORT_PREFIXES = (
    "src.decision_gate",
    "src.execution_planner",
    "src.executor",
    "src.selection",
    "src.exit_policy",
)


def _candle(days: int, open_price: str, high: str, low: str, close: str) -> ladder_bt.Candle:
    base = datetime(2020, 1, 1)
    return ladder_bt.Candle(
        open_ts_utc=base + timedelta(days=days),
        open_price=Decimal(open_price),
        high_price=Decimal(high),
        low_price=Decimal(low),
        close_price=Decimal(close),
    )


def _synthetic_candles() -> list[ladder_bt.Candle]:
    """Deterministic anchor_low -> wave1_high -> wave2_low -> breakout series."""
    candles = [_candle(0, "1.00", "1.00", "0.90", "0.95")]
    # Rally from anchor low (0.90) to wave1 high (>= 2x, so >= 1.80).
    for day in range(1, 20):
        price = Decimal("0.90") + (Decimal("1.00") * day / Decimal("19"))
        candles.append(_candle(day, str(price), str(price + Decimal("0.02")), str(price - Decimal("0.02")), str(price)))
    # wave1 high candle, well above 1.80, at day 20.
    candles.append(_candle(20, "1.90", "2.00", "1.85", "1.95"))
    # Pull back for wave2 low (retrace within 0.236-0.886 of wave1_range) a few days later.
    for day in range(21, 25):
        candles.append(_candle(day, "1.60", "1.65", "1.55", "1.58"))
    candles.append(_candle(25, "1.30", "1.35", "1.20", "1.25"))  # wave2 low candidate
    # Future expansion above wave1 high, giving a valid future_high.
    for day in range(26, 60):
        price = Decimal("1.25") + (Decimal("3.00") * (day - 25) / Decimal("34"))
        candles.append(_candle(day, str(price), str(price + Decimal("0.05")), str(price - Decimal("0.05")), str(price)))
    return candles


def test_target_families_are_frozen() -> None:
    assert set(ladder_bt.TARGET_FAMILIES) == {
        "FIB_STANDARD",
        "PRO_3X4X",
        "SUPERCYCLE",
        "EXPLOSIVE_SUPERCYCLE",
    }

    multipliers, fractions = ladder_bt.TARGET_FAMILIES["PRO_3X4X"]
    assert multipliers == [Decimal("2.000"), Decimal("2.618"), Decimal("3.000"), Decimal("4.000"), Decimal("4.236")]
    assert fractions == [Decimal("0.20"), Decimal("0.25"), Decimal("0.25"), Decimal("0.20"), Decimal("0.10")]

    multipliers, fractions = ladder_bt.TARGET_FAMILIES["SUPERCYCLE"]
    assert multipliers == [Decimal("2.618"), Decimal("4.236"), Decimal("6.854"), Decimal("11.090")]
    assert fractions == [Decimal("0.25"), Decimal("0.35"), Decimal("0.25"), Decimal("0.15")]

    multipliers, fractions = ladder_bt.TARGET_FAMILIES["EXPLOSIVE_SUPERCYCLE"]
    assert multipliers == [Decimal("4.236"), Decimal("6.854"), Decimal("11.090"), Decimal("17.944")]
    assert fractions == [Decimal("0.20"), Decimal("0.30"), Decimal("0.30"), Decimal("0.20")]


def test_original_asset_bucket_mapping_is_frozen() -> None:
    assert ladder_sb.exit_archetype_for_family("PRO_3X4X") == "EXIT_PROFILE_CONTROLLED_3X4X"
    assert ladder_sb.exit_archetype_for_family("SUPERCYCLE") == "EXIT_PROFILE_SUPERCYCLE_BALANCED"
    assert ladder_sb.exit_archetype_for_family("EXPLOSIVE_SUPERCYCLE") == "EXIT_PROFILE_EXPLOSIVE_MOONBAG"


def test_evaluate_symbol_is_deterministic_and_repeatable() -> None:
    candles = _synthetic_candles()
    kwargs = dict(
        symbol="SYNTH",
        candles=candles,
        target_family="PRO_3X4X",
        max_ladder_sell_fraction=Decimal("0.80"),
        pivot_threshold_pct=Decimal("0.25"),
        min_wave1_gain_pct=Decimal("1.00"),
        min_wave1_days=14,
        min_wave2_days_after_high=3,
        wave2_min_retrace=Decimal("0.236"),
        wave2_max_retrace=Decimal("0.886"),
        target_zone_low_pct=Decimal("0.04"),
        target_zone_high_pct=Decimal("0.04"),
        front_run_pct=Decimal("0.08"),
        end_pct_of_zone_high=Decimal("0.98"),
        rungs_per_target=5,
        distribution="front_loaded",
    )

    first = ladder_bt.evaluate_symbol(**kwargs)
    second = ladder_bt.evaluate_symbol(**kwargs)

    assert first.status == "OK"
    assert first.status == second.status
    assert first.anchor == second.anchor
    assert first.total_return_pct_with_remaining == second.total_return_pct_with_remaining
    assert first.hold_return_pct == second.hold_return_pct
    assert [f.limit_price for f in first.fills] == [f.limit_price for f in second.fills]


def test_anchor_detector_does_not_use_candles_before_its_own_window() -> None:
    """No-look-ahead: restricting the candle series to a window must not pull
    in an anchor whose defining candles fall outside that window."""
    full = _synthetic_candles()

    anchor_full = ladder_bt.find_anchor_set(
        candles=full,
        pivot_threshold_pct=Decimal("0.25"),
        min_wave1_gain_pct=Decimal("1.00"),
        min_wave1_days=14,
        min_wave2_days_after_high=3,
        wave2_min_retrace=Decimal("0.236"),
        wave2_max_retrace=Decimal("0.886"),
    )
    assert anchor_full is not None

    # A window that ends before the wave1 high must not find that same anchor.
    truncated = [c for c in full if c.open_ts_utc < anchor_full.wave1_high_ts]
    anchor_truncated = ladder_bt.find_anchor_set(
        candles=truncated,
        pivot_threshold_pct=Decimal("0.25"),
        min_wave1_gain_pct=Decimal("1.00"),
        min_wave1_days=14,
        min_wave2_days_after_high=3,
        wave2_min_retrace=Decimal("0.236"),
        wave2_max_retrace=Decimal("0.886"),
    )
    assert anchor_truncated is None or anchor_truncated.wave1_high_ts < anchor_full.wave1_high_ts


def test_read_only_guard_rejects_non_select_sql() -> None:
    for forbidden in ("INSERT INTO x VALUES (1)", "update x set y=1", "DELETE FROM x", "DROP TABLE x"):
        with pytest.raises(RuntimeError):
            ladder_bt.assert_read_only_sql(forbidden)

    ladder_bt.assert_read_only_sql("SELECT 1")  # must not raise


@pytest.mark.parametrize("module_path", [BACKTEST_MODULE_PATH, SCOREBOARD_MODULE_PATH])
def test_no_production_layer_or_account_aware_imports(module_path: Path) -> None:
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))

    imported_names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.append(node.module)

    for name in imported_names:
        assert not any(name.startswith(prefix) for prefix in FORBIDDEN_IMPORT_PREFIXES), (
            f"{module_path} imports forbidden module {name}"
        )

    source = module_path.read_text(encoding="utf-8")
    assert "trading_account_id" not in source
    assert not re.search(r"\baccount_balance\b|\bbalance\b(?!d)", source.lower())
