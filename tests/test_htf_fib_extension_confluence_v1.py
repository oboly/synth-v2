from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path

from src.research.htf_fib_extension_confluence_v1 import (
    DEFAULT_GATE_RETEST_PROXIMITY_PCT,
    DEFAULT_RESISTANCE_PROXIMITY_PCT,
    DEFAULT_ROUND_STEP,
    DEFAULT_ROUND_THRESHOLD_FRAC,
    HtfSwingInput,
    build_htf_extension_map,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _wld_like_anchor(**overrides: object) -> HtfSwingInput:
    """HTF swing resembling a low-cap asset at ~0.65 ATH breakout."""
    kwargs: dict[str, object] = {
        "symbol": "GENERIC",
        "interval_code": "1d",
        "swing_low": Decimal("0.30"),
        "swing_high": Decimal("0.65"),
        "current_price": Decimal("0.68"),
        "prior_high_price": None,
    }
    kwargs.update(overrides)
    return HtfSwingInput(**kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Fib extension math
# ---------------------------------------------------------------------------

def test_extension_prices_match_anchored_swing_formula() -> None:
    """ext = swing_low + leg * fib_level, never current_price * fib."""
    anchor = _wld_like_anchor()
    leg = Decimal("0.65") - Decimal("0.30")  # 0.35

    result = build_htf_extension_map(anchor)
    by_label = {t.label: t for t in result.targets}

    ext_1_272_expected = Decimal("0.30") + leg * Decimal("1.272")
    ext_1_618_expected = Decimal("0.30") + leg * Decimal("1.618")
    ext_2_000_expected = Decimal("0.30") + leg * Decimal("2.000")

    assert abs(by_label["ext_1_272"].price - ext_1_272_expected) < Decimal("0.0000001")
    assert abs(by_label["ext_1_618"].price - ext_1_618_expected) < Decimal("0.0000001")
    assert abs(by_label["ext_2_000"].price - ext_2_000_expected) < Decimal("0.0000001")


def test_breakout_gate_equals_swing_high() -> None:
    anchor = _wld_like_anchor()
    result = build_htf_extension_map(anchor)
    assert result.breakout_gate == anchor.swing_high


def test_leg_size_is_swing_high_minus_low() -> None:
    anchor = _wld_like_anchor()
    result = build_htf_extension_map(anchor)
    assert result.leg_size == (anchor.swing_high - anchor.swing_low).quantize(Decimal("0.0000000001"))


def test_ext_order_is_ascending() -> None:
    result = build_htf_extension_map(_wld_like_anchor())
    prices = [t.price for t in result.targets]
    assert prices == sorted(prices)


def test_all_extensions_above_swing_high() -> None:
    result = build_htf_extension_map(_wld_like_anchor())
    for target in result.targets:
        assert target.price > result.swing_high, f"{target.label} should exceed swing_high"


def test_pct_above_swing_high_is_positive() -> None:
    result = build_htf_extension_map(_wld_like_anchor())
    for target in result.targets:
        assert target.pct_above_swing_high > 0


# ---------------------------------------------------------------------------
# WLD-like acceptance example
# ---------------------------------------------------------------------------

def test_wld_like_example_values() -> None:
    """
    Canonical acceptance check:
      swing_low=0.30, swing_high=0.65, leg=0.35
      ext_1_272 ≈ 0.7452   first extension target
      ext_1_618 ≈ 0.8663   stronger spike target
      ext_2_000 = 1.0000   → round_number_confluence with step=1.0
      breakout_gate ≈ previous high = 0.65
    """
    anchor = _wld_like_anchor()
    result = build_htf_extension_map(anchor, round_step=Decimal("1"))
    by_label = {t.label: t for t in result.targets}

    assert result.breakout_gate == Decimal("0.65")

    assert by_label["ext_1_272"].price == Decimal("0.7452").quantize(Decimal("0.0000000001")) or (
        abs(by_label["ext_1_272"].price - Decimal("0.7452")) < Decimal("0.0001")
    )
    assert by_label["ext_1_618"].price > Decimal("0.86")
    assert by_label["ext_2_000"].price == Decimal("1.0000").quantize(Decimal("0.0000000001")) or (
        abs(by_label["ext_2_000"].price - Decimal("1.0000")) < Decimal("0.0001")
    )

    # 1.0000 is a whole number → round_number_confluence with step=1
    assert by_label["ext_2_000"].round_number_confluence is True


# ---------------------------------------------------------------------------
# Round number confluence
# ---------------------------------------------------------------------------

def test_round_number_confluence_whole_number() -> None:
    """ext_2_000 = 1.0000 with step=1.0 must be flagged."""
    result = build_htf_extension_map(_wld_like_anchor(), round_step=Decimal("1"))
    by_label = {t.label: t for t in result.targets}
    assert by_label["ext_2_000"].round_number_confluence is True


def test_round_number_confluence_near_half_step() -> None:
    """
    swing_low=0.05, swing_high=0.40, leg=0.35
    ext_1_272 = 0.05 + 0.35*1.272 = 0.4952  → near 0.50 with step=0.50
    """
    anchor = HtfSwingInput(
        symbol="GENERIC",
        interval_code="1d",
        swing_low=Decimal("0.05"),
        swing_high=Decimal("0.40"),
        current_price=Decimal("0.42"),
    )
    result = build_htf_extension_map(anchor, round_step=Decimal("0.5"))
    by_label = {t.label: t for t in result.targets}

    # 0.4952 % 0.50 = 0.4952, fraction = 0.4952/0.50 = 0.9904 → ≥ 0.98 threshold
    assert by_label["ext_1_272"].round_number_confluence is True


def test_round_number_confluence_far_from_step() -> None:
    """A target landing at 25% of step should not be flagged."""
    anchor = HtfSwingInput(
        symbol="GENERIC",
        interval_code="1d",
        swing_low=Decimal("1.00"),
        swing_high=Decimal("2.00"),
        current_price=Decimal("2.10"),
    )
    result = build_htf_extension_map(anchor, round_step=Decimal("1"))
    by_label = {t.label: t for t in result.targets}

    # ext_1_272 = 1.00 + 1.00*1.272 = 2.272 → 0.272 above 2.0 → not near 0 or 1
    assert by_label["ext_1_272"].round_number_confluence is False


# ---------------------------------------------------------------------------
# Prior high / resistance confluence
# ---------------------------------------------------------------------------

def test_prior_high_confluence_flagged_when_near() -> None:
    """ext_1_272 ≈ 0.7452; prior_high at 0.75 is within 2% → flagged."""
    anchor = _wld_like_anchor(prior_high_price=Decimal("0.75"))
    result = build_htf_extension_map(anchor)
    by_label = {t.label: t for t in result.targets}
    assert by_label["ext_1_272"].prior_high_confluence is True


def test_prior_high_confluence_not_flagged_when_far() -> None:
    """prior_high at 0.90 is far from ext_1_272 ≈ 0.7452 → not flagged."""
    anchor = _wld_like_anchor(prior_high_price=Decimal("0.90"))
    result = build_htf_extension_map(anchor)
    by_label = {t.label: t for t in result.targets}
    assert by_label["ext_1_272"].prior_high_confluence is False


def test_prior_high_confluence_none_when_no_prior_high() -> None:
    anchor = _wld_like_anchor(prior_high_price=None)
    result = build_htf_extension_map(anchor)
    for target in result.targets:
        assert target.prior_high_confluence is False


# ---------------------------------------------------------------------------
# ext_1_272_touched_and_rejected
# ---------------------------------------------------------------------------

def test_ext_1_272_touched_and_rejected_true() -> None:
    """prior_high exceeded ext_1.272, current is back below it."""
    # ext_1.272 ≈ 0.7452
    anchor = _wld_like_anchor(
        prior_high_price=Decimal("0.80"),  # prior high was above 0.7452
        current_price=Decimal("0.70"),     # now below 0.7452
    )
    result = build_htf_extension_map(anchor)
    assert result.ext_1_272_touched_and_rejected is True


def test_ext_1_272_touched_and_rejected_false_when_still_above() -> None:
    """current is above ext_1.272 → not rejected."""
    anchor = _wld_like_anchor(
        prior_high_price=Decimal("0.80"),
        current_price=Decimal("0.78"),  # still above 0.7452
    )
    result = build_htf_extension_map(anchor)
    assert result.ext_1_272_touched_and_rejected is False


def test_ext_1_272_touched_and_rejected_false_without_prior_high() -> None:
    anchor = _wld_like_anchor(
        prior_high_price=None,
        current_price=Decimal("0.70"),
    )
    result = build_htf_extension_map(anchor)
    assert result.ext_1_272_touched_and_rejected is False


def test_ext_1_272_touched_and_rejected_false_when_prior_below_ext() -> None:
    """prior_high never reached ext_1.272 → cannot be rejection."""
    anchor = _wld_like_anchor(
        prior_high_price=Decimal("0.72"),  # below 0.7452
        current_price=Decimal("0.70"),
    )
    result = build_htf_extension_map(anchor)
    assert result.ext_1_272_touched_and_rejected is False


# ---------------------------------------------------------------------------
# retesting_breakout_gate
# ---------------------------------------------------------------------------

def test_retesting_breakout_gate_true() -> None:
    """
    Price near swing_high (within 2%) and prior_high reached ext_1.272:
    typical retest scenario.
    """
    anchor = _wld_like_anchor(
        prior_high_price=Decimal("0.80"),
        current_price=Decimal("0.655"),  # within 2% of 0.65
    )
    result = build_htf_extension_map(anchor)
    assert result.retesting_breakout_gate is True


def test_retesting_breakout_gate_false_far_from_gate() -> None:
    anchor = _wld_like_anchor(
        prior_high_price=Decimal("0.80"),
        current_price=Decimal("0.68"),  # >2% above swing_high 0.65
    )
    result = build_htf_extension_map(anchor)
    assert result.retesting_breakout_gate is False


def test_retesting_breakout_gate_false_no_extension_touch() -> None:
    """Near gate but extension was never touched → not a retest."""
    anchor = _wld_like_anchor(
        prior_high_price=Decimal("0.66"),  # never reached 0.7452
        current_price=Decimal("0.655"),
    )
    result = build_htf_extension_map(anchor)
    assert result.retesting_breakout_gate is False


# ---------------------------------------------------------------------------
# Price band labels
# ---------------------------------------------------------------------------

def test_price_band_below_gate() -> None:
    result = build_htf_extension_map(_wld_like_anchor(current_price=Decimal("0.60")))
    assert result.price_band == "BELOW_BREAKOUT_GATE"


def test_price_band_approaching_1272() -> None:
    result = build_htf_extension_map(_wld_like_anchor(current_price=Decimal("0.68")))
    assert result.price_band == "ABOVE_GATE_APPROACHING_1272"


def test_price_band_between_1272_1618() -> None:
    # ext_1_272 ≈ 0.7452, ext_1_618 ≈ 0.8663 → price at 0.80
    result = build_htf_extension_map(_wld_like_anchor(current_price=Decimal("0.80")))
    assert result.price_band == "BETWEEN_1272_1618"


def test_price_band_between_1618_2000() -> None:
    result = build_htf_extension_map(_wld_like_anchor(current_price=Decimal("0.90")))
    assert result.price_band == "BETWEEN_1618_2000"


def test_price_band_above_2000() -> None:
    result = build_htf_extension_map(_wld_like_anchor(current_price=Decimal("1.10")))
    assert result.price_band == "ABOVE_2000"


# ---------------------------------------------------------------------------
# Distance metrics
# ---------------------------------------------------------------------------

def test_distance_to_current_positive_when_target_above() -> None:
    """All targets are above current_price=0.68 → positive distance."""
    result = build_htf_extension_map(_wld_like_anchor(current_price=Decimal("0.68")))
    for target in result.targets:
        assert target.distance_to_current_pct > 0, f"{target.label} should be above current"


def test_distance_to_current_negative_when_target_below_current() -> None:
    """With current_price above all targets, distances are negative."""
    result = build_htf_extension_map(_wld_like_anchor(current_price=Decimal("1.50")))
    for target in result.targets:
        assert target.distance_to_current_pct < 0


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def test_rejects_inverted_swing() -> None:
    try:
        build_htf_extension_map(
            HtfSwingInput(
                symbol="X",
                interval_code="1d",
                swing_low=Decimal("0.70"),
                swing_high=Decimal("0.50"),
                current_price=Decimal("0.60"),
            )
        )
    except ValueError as exc:
        assert "swing_low" in str(exc)
        return
    raise AssertionError("Expected ValueError for inverted swing")


def test_rejects_zero_current_price() -> None:
    try:
        build_htf_extension_map(
            HtfSwingInput(
                symbol="X",
                interval_code="1d",
                swing_low=Decimal("0.30"),
                swing_high=Decimal("0.65"),
                current_price=Decimal("0"),
            )
        )
    except ValueError as exc:
        assert "current_price" in str(exc)
        return
    raise AssertionError("Expected ValueError for zero current_price")


def test_rejects_zero_swing_low() -> None:
    try:
        build_htf_extension_map(
            HtfSwingInput(
                symbol="X",
                interval_code="1d",
                swing_low=Decimal("0"),
                swing_high=Decimal("0.65"),
                current_price=Decimal("0.50"),
            )
        )
    except ValueError as exc:
        assert "swing_low" in str(exc)
        return
    raise AssertionError("Expected ValueError for zero swing_low")


# ---------------------------------------------------------------------------
# Boundary: no forbidden imports
# ---------------------------------------------------------------------------

def test_module_has_no_forbidden_imports() -> None:
    source = Path("src/research/htf_fib_extension_confluence_v1.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden_terms = (
        "decision_gate",
        "execution_planner",
        "executor",
        "broker",
        "bitvavo_client",
        "account_position",
        "balance_snapshot",
        "order_snapshot",
        "db",
        "common.db",
    )
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    for module_name in imported_modules:
        parts = tuple(part for part in module_name.split(".") if part)
        for term in forbidden_terms:
            assert term not in parts, f"Forbidden module import found: {module_name}"

    forbidden_dotted_refs = (
        "src.decision_gate",
        "src.execution_planner",
        "src.executor",
        "src.broker",
        "src.common.db",
        "order_submission",
        "broker_write",
    )
    for ref in forbidden_dotted_refs:
        assert ref not in source, f"Forbidden reference found: {ref}"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main() -> None:
    tests = [
        test_extension_prices_match_anchored_swing_formula,
        test_breakout_gate_equals_swing_high,
        test_leg_size_is_swing_high_minus_low,
        test_ext_order_is_ascending,
        test_all_extensions_above_swing_high,
        test_pct_above_swing_high_is_positive,
        test_wld_like_example_values,
        test_round_number_confluence_whole_number,
        test_round_number_confluence_near_half_step,
        test_round_number_confluence_far_from_step,
        test_prior_high_confluence_flagged_when_near,
        test_prior_high_confluence_not_flagged_when_far,
        test_prior_high_confluence_none_when_no_prior_high,
        test_ext_1_272_touched_and_rejected_true,
        test_ext_1_272_touched_and_rejected_false_when_still_above,
        test_ext_1_272_touched_and_rejected_false_without_prior_high,
        test_ext_1_272_touched_and_rejected_false_when_prior_below_ext,
        test_retesting_breakout_gate_true,
        test_retesting_breakout_gate_false_far_from_gate,
        test_retesting_breakout_gate_false_no_extension_touch,
        test_price_band_below_gate,
        test_price_band_approaching_1272,
        test_price_band_between_1272_1618,
        test_price_band_between_1618_2000,
        test_price_band_above_2000,
        test_distance_to_current_positive_when_target_above,
        test_distance_to_current_negative_when_target_below_current,
        test_rejects_inverted_swing,
        test_rejects_zero_current_price,
        test_rejects_zero_swing_low,
        test_module_has_no_forbidden_imports,
    ]
    for test in tests:
        test()
    print("ok")


if __name__ == "__main__":
    main()
