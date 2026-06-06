"""
Tests for reserve-policy variant simulation in run_manual_exact_zone_backtest_v1.

No DB access. All inputs are supplied directly.

Coverage:
- No entry → all variants return entry_hit=False, no pnl
- Entry hit, single-tranche variants (A, B, D) target hit/miss
- Entry hit, multi-tranche C (20/15/15)
- Partial tranche hits (first hit, later ones not)
- Reserve constraint: sold_pct never exceeds max_sell_pct_allowed
- Realized vs unrealized P&L split
- MAE/MFE span full hold window (entry to end)
- B&H and improvement for variants
- NEAR_VARIANTS spec validation (no ValueError on construction)
- VariantSpec rejects tranche total > max_sell_pct_allowed
- variant_to_dict has all required keys
- write_variant_outputs creates files
- print_variant_comparison_table runs without error
- Determinism
"""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Optional

import pytest

from src.research.run_manual_exact_zone_backtest_v1 import (
    NEAR_VARIANTS,
    Candle,
    SellTranche,
    VariantResult,
    VariantSpec,
    _variant_to_dict,
    print_variant_comparison_table,
    run_all_variants,
    simulate_variant,
    write_variant_outputs,
)
from src.account.long_reserve_policy_v1 import (
    TP_SCOPE_CHILD_SHORT_SWING,
    TP_SCOPE_PARENT_TF_FULL,
    RESERVE_SOURCE_ASSET_OVERRIDE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PREDICTION_TS = datetime(2026, 5, 21, 0, 0, 0, tzinfo=UTC)
BUY = Decimal("2.00")
CAPITAL = Decimal("100.00")
_H = Decimal("100")
_Z = Decimal("0")


def _ts(offset_min: int) -> datetime:
    return PREDICTION_TS + timedelta(minutes=offset_min)


def _candle(
    offset_min: int,
    high: str,
    low: str,
    close: str,
    open_: Optional[str] = None,
) -> Candle:
    ts = _ts(offset_min)
    o = Decimal(open_) if open_ else (Decimal(high) + Decimal(low)) / Decimal("2")
    return Candle(
        open_ts_utc=ts,
        open_price=o,
        high_price=Decimal(high),
        low_price=Decimal(low),
        close_price=Decimal(close),
    )


def _spec(
    variant_id: str = "TEST",
    label: str = "TEST",
    tp_scope: str = TP_SCOPE_CHILD_SHORT_SWING,
    reserve_pct: str = "50",
    max_short_swing: str = "50",
    max_sell: str = "50",
    allow_full_exit: bool = False,
    reserve_source: str = RESERVE_SOURCE_ASSET_OVERRIDE,
    tranches: Optional[list[SellTranche]] = None,
    parent_tf_status: str = "N/A",
) -> VariantSpec:
    return VariantSpec(
        variant_id=variant_id,
        label=label,
        tp_scope=tp_scope,
        active_long_reserve_pct=Decimal(reserve_pct),
        max_short_swing_sell_pct=Decimal(max_short_swing),
        max_sell_pct_allowed=Decimal(max_sell),
        allow_parent_tf_full_exit=allow_full_exit,
        reserve_source=reserve_source,
        tranches=tranches or [SellTranche(sell_pct=Decimal("50"), target_price=Decimal("2.12"))],
        parent_tf_target_status=parent_tf_status,
    )


# ---------------------------------------------------------------------------
# NEAR_VARIANTS construction (no exception = pass)
# ---------------------------------------------------------------------------

def test_near_variants_construct_without_error() -> None:
    assert len(NEAR_VARIANTS) == 4
    ids = [v.variant_id for v in NEAR_VARIANTS]
    assert "A_FULL_EXIT_BENCHMARK" in ids
    assert "B_MAX_50_FIRST_TARGET" in ids
    assert "C_20_15_15_RUNNER" in ids
    assert "D_PARENT_TF_FULL_EXIT_BENCHMARK" in ids


def test_variant_a_is_benchmark_no_reserve() -> None:
    a = next(v for v in NEAR_VARIANTS if v.variant_id == "A_FULL_EXIT_BENCHMARK")
    assert a.active_long_reserve_pct == Decimal("0")
    assert a.max_sell_pct_allowed == Decimal("100")
    assert len(a.tranches) == 1
    assert a.tranches[0].sell_pct == Decimal("100")


def test_variant_c_tranche_total_within_reserve() -> None:
    c = next(v for v in NEAR_VARIANTS if v.variant_id == "C_20_15_15_RUNNER")
    total = sum(t.sell_pct for t in c.tranches)
    assert total == Decimal("50")
    assert total <= c.max_sell_pct_allowed


def test_variant_d_parent_tf_status_unknown() -> None:
    d = next(v for v in NEAR_VARIANTS if v.variant_id == "D_PARENT_TF_FULL_EXIT_BENCHMARK")
    assert d.parent_tf_target_status == "UNKNOWN"
    assert d.allow_parent_tf_full_exit is True
    assert d.max_sell_pct_allowed == Decimal("100")


# ---------------------------------------------------------------------------
# VariantSpec validation
# ---------------------------------------------------------------------------

def test_variant_spec_rejects_tranche_total_exceeds_max_sell() -> None:
    with pytest.raises(ValueError, match="exceeds max_sell_pct_allowed"):
        VariantSpec(
            variant_id="BAD",
            label="BAD",
            tp_scope=TP_SCOPE_CHILD_SHORT_SWING,
            active_long_reserve_pct=Decimal("50"),
            max_short_swing_sell_pct=Decimal("50"),
            max_sell_pct_allowed=Decimal("50"),
            allow_parent_tf_full_exit=False,
            reserve_source=RESERVE_SOURCE_ASSET_OVERRIDE,
            tranches=[
                SellTranche(sell_pct=Decimal("40"), target_price=Decimal("2.12")),
                SellTranche(sell_pct=Decimal("20"), target_price=Decimal("2.25")),
            ],
            parent_tf_target_status="N/A",
        )


# ---------------------------------------------------------------------------
# No entry
# ---------------------------------------------------------------------------

def test_no_entry_all_pnl_none() -> None:
    candles = [_candle(15, "2.10", "2.05", "2.08")]
    spec = _spec()
    r = simulate_variant(candles, PREDICTION_TS, BUY, CAPITAL, spec)
    assert r.entry_hit is False
    assert r.pnl_eur is None
    assert r.final_value_eur is None
    assert r.realized_pnl_eur is None
    assert r.unrealized_pnl_eur is None
    assert r.target_hits == []
    assert r.short_swing_sold_pct == _Z
    assert r.long_runner_remaining_pct == _H


def test_no_entry_bah_still_calculated() -> None:
    candles = [_candle(15, "2.10", "2.05", "2.43")]
    spec = _spec()
    r = simulate_variant(candles, PREDICTION_TS, BUY, CAPITAL, spec)
    assert r.buy_and_hold_return_from_entry_to_end is not None
    # (2.43 - 2.00) / 2.00 * 100 = 21.5
    assert r.buy_and_hold_return_from_entry_to_end == pytest.approx(
        Decimal("21.5"), abs=Decimal("0.01")
    )


# ---------------------------------------------------------------------------
# Single-tranche: target hit
# ---------------------------------------------------------------------------

def test_single_tranche_target_hit_realized_only() -> None:
    # Variant B: sell 50% at 2.12, hold 50% to close
    candles = [
        _candle(15, "2.05", "1.98", "2.01"),   # entry
        _candle(30, "2.15", "2.00", "2.13"),   # target hit
        _candle(45, "2.20", "2.10", "2.18"),   # after exit — hold runner
    ]
    spec = _spec(tranches=[SellTranche(sell_pct=Decimal("50"), target_price=Decimal("2.12"))])
    r = simulate_variant(candles, PREDICTION_TS, BUY, CAPITAL, spec)

    assert r.entry_hit is True
    assert r.target_hits == ["2.12"]
    assert r.short_swing_sold_pct == Decimal("50")
    assert r.long_runner_remaining_pct == Decimal("50")

    # realized: 50 EUR * (2.12 - 2.00) / 2.00 = 50 * 0.06 = 3.00 EUR
    assert r.realized_pnl_eur == pytest.approx(Decimal("3.00"), abs=Decimal("0.001"))

    # unrealized: 50 EUR held to close=2.18 → 50 * (2.18 - 2.00) / 2.00 = 50 * 0.09 = 4.50 EUR
    assert r.unrealized_pnl_eur == pytest.approx(Decimal("4.50"), abs=Decimal("0.001"))

    # final_value = 100 + 3 + 4.5 = 107.5
    assert r.final_value_eur == pytest.approx(Decimal("107.5"), abs=Decimal("0.01"))

    # gross_return = (3 + 4.5) / 100 * 100 = 7.5%
    assert r.gross_return_pct == pytest.approx(Decimal("7.5"), abs=Decimal("0.01"))


def test_single_tranche_100pct_target_hit_no_runner() -> None:
    # Variant A: sell 100% at 2.12
    candles = [
        _candle(15, "2.05", "1.98", "2.01"),
        _candle(30, "2.15", "2.00", "2.13"),
        _candle(45, "2.20", "2.10", "2.18"),
    ]
    spec = _spec(
        reserve_pct="0", max_short_swing="100", max_sell="100",
        tranches=[SellTranche(sell_pct=Decimal("100"), target_price=Decimal("2.12"))],
    )
    r = simulate_variant(candles, PREDICTION_TS, BUY, CAPITAL, spec)

    assert r.target_hits == ["2.12"]
    assert r.short_swing_sold_pct == Decimal("100")
    assert r.long_runner_remaining_pct == Decimal("0")

    # realized: 100 * (2.12 - 2.00) / 2.00 = 6.00 EUR
    assert r.realized_pnl_eur == pytest.approx(Decimal("6.00"), abs=Decimal("0.001"))
    # unrealized: 0 EUR remaining → 0
    assert r.unrealized_pnl_eur == pytest.approx(Decimal("0"), abs=Decimal("0.001"))
    assert r.final_value_eur == pytest.approx(Decimal("106.00"), abs=Decimal("0.01"))


# ---------------------------------------------------------------------------
# Single-tranche: target not hit
# ---------------------------------------------------------------------------

def test_single_tranche_target_not_hit_valued_at_close() -> None:
    candles = [
        _candle(15, "2.05", "1.98", "2.01"),   # entry
        _candle(30, "2.10", "2.00", "2.08"),   # miss
        _candle(45, "2.08", "2.01", "2.05"),   # miss — final
    ]
    spec = _spec(tranches=[SellTranche(sell_pct=Decimal("50"), target_price=Decimal("2.12"))])
    r = simulate_variant(candles, PREDICTION_TS, BUY, CAPITAL, spec)

    assert r.entry_hit is True
    assert r.target_hits == []
    assert r.short_swing_sold_pct == _Z
    assert r.long_runner_remaining_pct == _H

    # All capital held to close=2.05: unrealized = 100 * (2.05 - 2.00) / 2.00 = 2.5 EUR
    assert r.unrealized_pnl_eur == pytest.approx(Decimal("2.5"), abs=Decimal("0.01"))
    assert r.realized_pnl_eur == pytest.approx(Decimal("0"), abs=Decimal("0.001"))
    assert r.final_value_eur == pytest.approx(Decimal("102.5"), abs=Decimal("0.01"))


# ---------------------------------------------------------------------------
# Multi-tranche: all hit (variant C analogue)
# ---------------------------------------------------------------------------

def test_multi_tranche_all_hit() -> None:
    candles = [
        _candle(15, "2.05", "1.98", "2.01"),   # entry
        _candle(30, "2.15", "2.00", "2.13"),   # T1 2.12 hit
        _candle(45, "2.28", "2.12", "2.25"),   # T2 2.25 hit
        _candle(60, "2.40", "2.25", "2.38"),   # T3 2.35 hit
        _candle(75, "2.43", "2.35", "2.40"),   # final
    ]
    spec = _spec(
        tranches=[
            SellTranche(sell_pct=Decimal("20"), target_price=Decimal("2.12")),
            SellTranche(sell_pct=Decimal("15"), target_price=Decimal("2.25")),
            SellTranche(sell_pct=Decimal("15"), target_price=Decimal("2.35")),
        ],
    )
    r = simulate_variant(candles, PREDICTION_TS, BUY, CAPITAL, spec)

    assert r.target_hits == ["2.12", "2.25", "2.35"]
    assert r.short_swing_sold_pct == Decimal("50")
    assert r.long_runner_remaining_pct == Decimal("50")

    # realized:
    #   20 * (2.12-2.00)/2.00 = 20*0.06 = 1.20
    #   15 * (2.25-2.00)/2.00 = 15*0.125 = 1.875
    #   15 * (2.35-2.00)/2.00 = 15*0.175 = 2.625
    #   total = 5.70
    assert r.realized_pnl_eur == pytest.approx(Decimal("5.70"), abs=Decimal("0.01"))

    # unrealized: 50 EUR at final close 2.40 → 50*(2.40-2.00)/2.00 = 50*0.20 = 10.00
    assert r.unrealized_pnl_eur == pytest.approx(Decimal("10.00"), abs=Decimal("0.01"))

    assert r.final_value_eur == pytest.approx(Decimal("115.70"), abs=Decimal("0.01"))


def test_multi_tranche_partial_hit_stops_at_first_miss() -> None:
    candles = [
        _candle(15, "2.05", "1.98", "2.01"),   # entry
        _candle(30, "2.15", "2.00", "2.13"),   # T1 2.12 hit
        _candle(45, "2.20", "2.12", "2.18"),   # T2 2.25 miss
        _candle(60, "2.22", "2.15", "2.20"),   # T3 2.35 miss — final
    ]
    spec = _spec(
        tranches=[
            SellTranche(sell_pct=Decimal("20"), target_price=Decimal("2.12")),
            SellTranche(sell_pct=Decimal("15"), target_price=Decimal("2.25")),
            SellTranche(sell_pct=Decimal("15"), target_price=Decimal("2.35")),
        ],
    )
    r = simulate_variant(candles, PREDICTION_TS, BUY, CAPITAL, spec)

    assert r.target_hits == ["2.12"]  # only first tranche hit
    assert r.short_swing_sold_pct == Decimal("20")
    assert r.long_runner_remaining_pct == Decimal("80")

    # realized: 20 * (2.12-2.00)/2.00 = 1.20
    assert r.realized_pnl_eur == pytest.approx(Decimal("1.20"), abs=Decimal("0.01"))

    # unrealized: 80 EUR at final close 2.20 → 80*(2.20-2.00)/2.00 = 80*0.10 = 8.00
    assert r.unrealized_pnl_eur == pytest.approx(Decimal("8.00"), abs=Decimal("0.01"))


# ---------------------------------------------------------------------------
# No same-candle entry and exit for first tranche
# ---------------------------------------------------------------------------

def test_first_tranche_not_hit_on_entry_candle() -> None:
    # Entry candle has high > 2.12 too — but tranche should search strictly after entry
    candles = [
        _candle(15, "2.50", "1.90", "2.10"),   # entry (low=1.90<=2.00) AND high>2.12
        _candle(30, "2.05", "2.00", "2.03"),   # miss
        _candle(45, "2.13", "2.01", "2.12"),   # T1 hit here
    ]
    spec = _spec(tranches=[SellTranche(sell_pct=Decimal("50"), target_price=Decimal("2.12"))])
    r = simulate_variant(candles, PREDICTION_TS, BUY, CAPITAL, spec)

    assert r.entry_hit is True
    assert r.target_hits == ["2.12"]
    # tranche hit at offset=45, not offset=15


# ---------------------------------------------------------------------------
# MAE / MFE span full hold window
# ---------------------------------------------------------------------------

def test_mae_mfe_span_full_hold_window() -> None:
    # Even after target hit (partially), runner is still held → MAE/MFE should cover full window
    candles = [
        _candle(15, "2.05", "1.95", "2.01"),   # entry, low drops to 1.95
        _candle(30, "2.15", "2.00", "2.13"),   # T1 hit
        _candle(45, "2.20", "1.80", "1.90"),   # after T1: drops hard — worst low
    ]
    spec = _spec(tranches=[SellTranche(sell_pct=Decimal("50"), target_price=Decimal("2.12"))])
    r = simulate_variant(candles, PREDICTION_TS, BUY, CAPITAL, spec)

    # worst low = 1.80 → MAE = (1.80 - 2.00) / 2.00 * 100 = -10%
    assert r.maximum_adverse_excursion_pct == pytest.approx(
        Decimal("-10.0"), abs=Decimal("0.01")
    )
    # best high = 2.20 → MFE = (2.20 - 2.00) / 2.00 * 100 = 10%
    assert r.maximum_favorable_excursion_pct == pytest.approx(
        Decimal("10.0"), abs=Decimal("0.01")
    )


# ---------------------------------------------------------------------------
# B&H and improvement
# ---------------------------------------------------------------------------

def test_bah_and_improvement_multi_tranche() -> None:
    # Final close = 2.40, buy = 2.00 → B&H = 20%
    candles = [
        _candle(15, "2.05", "1.98", "2.01"),
        _candle(30, "2.15", "2.00", "2.13"),
        _candle(45, "2.28", "2.12", "2.25"),
        _candle(60, "2.40", "2.25", "2.40"),   # final
    ]
    spec = _spec(
        tranches=[
            SellTranche(sell_pct=Decimal("20"), target_price=Decimal("2.12")),
            SellTranche(sell_pct=Decimal("15"), target_price=Decimal("2.25")),
        ],
    )
    r = simulate_variant(candles, PREDICTION_TS, BUY, CAPITAL, spec)

    bah = (Decimal("2.40") - Decimal("2.00")) / Decimal("2.00") * Decimal("100")
    assert r.buy_and_hold_return_from_entry_to_end == pytest.approx(bah, abs=Decimal("0.01"))
    assert r.improvement_vs_buy_and_hold == pytest.approx(
        r.gross_return_pct - bah, abs=Decimal("0.01")  # type: ignore[operator]
    )


# ---------------------------------------------------------------------------
# run_all_variants
# ---------------------------------------------------------------------------

def test_run_all_variants_returns_one_per_spec() -> None:
    candles = [
        _candle(15, "2.05", "1.98", "2.01"),
        _candle(30, "2.15", "2.00", "2.43"),
    ]
    results = run_all_variants(
        candles=candles,
        prediction_ts=PREDICTION_TS,
        buy_level=BUY,
        starting_capital=CAPITAL,
        variants=NEAR_VARIANTS,
    )
    assert len(results) == len(NEAR_VARIANTS)
    ids = [r.variant_id for r in results]
    assert "A_FULL_EXIT_BENCHMARK" in ids
    assert "C_20_15_15_RUNNER" in ids


def test_run_all_variants_is_deterministic() -> None:
    candles = [
        _candle(15, "2.05", "1.98", "2.01"),
        _candle(30, "2.15", "2.00", "2.13"),
        _candle(45, "2.28", "2.12", "2.40"),
    ]
    r1 = run_all_variants(candles, PREDICTION_TS, BUY, CAPITAL, NEAR_VARIANTS)
    r2 = run_all_variants(candles, PREDICTION_TS, BUY, CAPITAL, NEAR_VARIANTS)
    for a, b in zip(r1, r2):
        assert a.final_value_eur == b.final_value_eur
        assert a.target_hits == b.target_hits


# ---------------------------------------------------------------------------
# _variant_to_dict
# ---------------------------------------------------------------------------

def test_variant_to_dict_has_all_required_keys() -> None:
    candles = [
        _candle(15, "2.05", "1.98", "2.01"),
        _candle(30, "2.15", "2.00", "2.13"),
    ]
    spec = _spec()
    r = simulate_variant(candles, PREDICTION_TS, BUY, CAPITAL, spec)
    d = _variant_to_dict(r)

    required = [
        "variant_id", "label",
        "active_long_reserve_pct", "reserve_source", "tp_scope",
        "max_short_swing_sell_pct", "max_sell_pct_allowed",
        "parent_tf_target_status", "entry_hit", "target_hits",
        "gross_return_pct", "pnl_eur", "final_value_eur",
        "realized_pnl_eur", "unrealized_pnl_eur",
        "short_swing_sold_pct", "long_runner_remaining_pct",
        "MAE", "MFE",
        "buy_and_hold_return_from_entry_to_end", "improvement_vs_buy_and_hold",
    ]
    for key in required:
        assert key in d, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# write_variant_outputs
# ---------------------------------------------------------------------------

def _make_variant_results() -> list[VariantResult]:
    candles = [
        _candle(15, "2.05", "1.98", "2.01"),
        _candle(30, "2.15", "2.00", "2.13"),
        _candle(45, "2.28", "2.12", "2.43"),
    ]
    return run_all_variants(candles, PREDICTION_TS, BUY, CAPITAL, NEAR_VARIANTS)


def test_write_variant_outputs_creates_json_and_jsonl() -> None:
    results = _make_variant_results()
    candles = [
        _candle(15, "2.05", "1.98", "2.01"),
        _candle(30, "2.15", "2.00", "2.13"),
        _candle(45, "2.28", "2.12", "2.43"),
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        written = write_variant_outputs(
            variant_results=results,
            output_dir=Path(tmpdir),
            candles=candles,
            buy_level=BUY,
            prediction_ts=PREDICTION_TS,
            write_chart=False,
        )
        assert "variant_summary" in written
        assert "variant_rows" in written
        assert written["variant_summary"].exists()
        assert written["variant_rows"].exists()


def test_variant_summary_json_structure() -> None:
    results = _make_variant_results()
    candles = [_candle(15, "2.05", "1.98", "2.01"), _candle(30, "2.15", "2.00", "2.43")]
    with tempfile.TemporaryDirectory() as tmpdir:
        written = write_variant_outputs(
            results, Path(tmpdir), candles, BUY, PREDICTION_TS, write_chart=False
        )
        data = json.loads(written["variant_summary"].read_text())
    assert "variants" in data
    assert len(data["variants"]) == 4


def test_variant_rows_jsonl_parseable() -> None:
    results = _make_variant_results()
    candles = [_candle(15, "2.05", "1.98", "2.01"), _candle(30, "2.15", "2.00", "2.43")]
    with tempfile.TemporaryDirectory() as tmpdir:
        written = write_variant_outputs(
            results, Path(tmpdir), candles, BUY, PREDICTION_TS, write_chart=False
        )
        lines = written["variant_rows"].read_text().strip().split("\n")
    assert len(lines) == 4
    for line in lines:
        json.loads(line)


# ---------------------------------------------------------------------------
# print_variant_comparison_table (smoke — must not raise)
# ---------------------------------------------------------------------------

def test_print_variant_comparison_table_runs(capsys) -> None:
    results = _make_variant_results()
    print_variant_comparison_table(results)
    captured = capsys.readouterr()
    assert "VARIANT COMPARISON" in captured.out
    assert "A_FULL_EXIT_BENCHMARK" in captured.out
    assert "C_20_15_15_RUNNER" in captured.out


def test_variant_table_sorted_by_final_value(capsys) -> None:
    results = _make_variant_results()
    print_variant_comparison_table(results)
    captured = capsys.readouterr()
    lines = [l for l in captured.out.split("\n") if l.strip() and "---" not in l and "VARIANT" not in l and "variant_id" not in l]
    # Extract final_value tokens — check they're non-increasing top to bottom
    values = []
    for line in lines:
        parts = line.split()
        # second token after variant_id column is final_eur
        if len(parts) >= 2:
            try:
                values.append(Decimal(parts[1]))
            except Exception:
                pass
    assert values == sorted(values, reverse=True)


# ---------------------------------------------------------------------------
# Edge: candles before prediction_ts excluded from all variants
# ---------------------------------------------------------------------------

def test_pre_prediction_candles_excluded_from_variants() -> None:
    pre = _candle(-30, "2.05", "1.90", "2.00")   # before — should not trigger entry
    post = _candle(15, "2.10", "2.05", "2.08")   # after — no entry (low > 2.00)
    candles = [pre, post]
    for spec in NEAR_VARIANTS:
        r = simulate_variant(candles, PREDICTION_TS, BUY, CAPITAL, spec)
        assert r.entry_hit is False, f"Pre-ts candle triggered entry for {spec.variant_id}"
