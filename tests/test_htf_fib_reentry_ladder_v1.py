from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path

from src.research.htf_fib_reentry_ladder_v1 import (
    RETRACE_LEVELS,
    FibRetraceLadder,
    HtfReentryInput,
    RetraceLevelRow,
    build_fib_retrace_ladder,
)


def _fet_input(recent_low: str | None = None) -> HtfReentryInput:
    return HtfReentryInput(
        symbol="FET",
        interval_code="1d",
        swing_low=Decimal("0.166"),
        swing_high=Decimal("0.244"),
        current_price=Decimal("0.230"),
        recent_low_price=Decimal(recent_low) if recent_low else None,
    )


def _ladder(recent_low: str | None = None) -> FibRetraceLadder:
    return build_fib_retrace_ladder(_fet_input(recent_low))


def _level(ladder: FibRetraceLadder, label: str) -> RetraceLevelRow:
    return next(r for r in ladder.levels if r.label == label)


def test_basic_ladder_has_four_levels() -> None:
    ladder = _ladder()
    assert len(ladder.levels) == 4


def test_level_labels_in_order() -> None:
    ladder = _ladder()
    labels = [r.label for r in ladder.levels]
    assert labels == ["retrace_0_382", "retrace_0_500", "retrace_0_618", "retrace_0_786"]


def test_level_roles() -> None:
    ladder = _ladder()
    roles = {r.label: r.role for r in ladder.levels}
    assert roles["retrace_0_382"] == "FIRST_TOUCH"
    assert roles["retrace_0_500"] == "MAIN_REBUY"
    assert roles["retrace_0_618"] == "DEEP_REBUY"
    assert roles["retrace_0_786"] == "PANIC_RESET"


def test_leg_size() -> None:
    ladder = _ladder()
    assert ladder.leg_size == Decimal("0.078")


def test_fet_retrace_0_382_price() -> None:
    ladder = _ladder()
    level = _level(ladder, "retrace_0_382")
    expected = Decimal("0.244") - Decimal("0.078") * Decimal("0.382")
    assert abs(level.price - expected) < Decimal("0.0000001")


def test_fet_retrace_0_500_price() -> None:
    ladder = _ladder()
    level = _level(ladder, "retrace_0_500")
    assert level.price == Decimal("0.205")


def test_fet_retrace_0_618_price() -> None:
    ladder = _ladder()
    level = _level(ladder, "retrace_0_618")
    expected = Decimal("0.244") - Decimal("0.078") * Decimal("0.618")
    assert abs(level.price - expected) < Decimal("0.0000001")


def test_fet_retrace_0_786_price() -> None:
    ladder = _ladder()
    level = _level(ladder, "retrace_0_786")
    expected = Decimal("0.244") - Decimal("0.078") * Decimal("0.786")
    assert abs(level.price - expected) < Decimal("0.0000001")


def test_levels_ordered_high_to_low_price() -> None:
    ladder = _ladder()
    prices = [r.price for r in ladder.levels]
    assert prices == sorted(prices, reverse=True)


def test_distance_to_current_pct_correct() -> None:
    ladder = _ladder()
    level = _level(ladder, "retrace_0_500")
    expected = (Decimal("0.205") - Decimal("0.230")) / Decimal("0.230") * Decimal("100")
    assert level.distance_to_current_pct is not None
    assert abs(level.distance_to_current_pct - expected) < Decimal("0.0001")


def test_distance_to_current_pct_negative_when_level_below_current() -> None:
    ladder = _ladder()
    level = _level(ladder, "retrace_0_500")
    assert level.distance_to_current_pct is not None
    assert level.distance_to_current_pct < Decimal("0")


def test_distance_to_current_pct_positive_when_level_above_current() -> None:
    inp = HtfReentryInput(
        symbol="X",
        interval_code="1d",
        swing_low=Decimal("0.1"),
        swing_high=Decimal("0.5"),
        current_price=Decimal("0.15"),
    )
    ladder = build_fib_retrace_ladder(inp)
    level = next(r for r in ladder.levels if r.label == "retrace_0_382")
    assert level.distance_to_current_pct is not None
    assert level.distance_to_current_pct > Decimal("0")


def test_distance_to_recent_low_pct_when_provided() -> None:
    ladder = _ladder("0.209")
    level = _level(ladder, "retrace_0_382")
    assert level.distance_to_recent_low_pct is not None
    r382_price = Decimal("0.244") - Decimal("0.078") * Decimal("0.382")
    expected = (r382_price - Decimal("0.209")) / Decimal("0.209") * Decimal("100")
    assert abs(level.distance_to_recent_low_pct - expected) < Decimal("0.0001")


def test_distance_to_recent_low_pct_none_when_no_recent_low() -> None:
    ladder = _ladder()
    for r in ladder.levels:
        assert r.distance_to_recent_low_pct is None


def test_recently_touched_true_when_recent_low_at_r382_zone() -> None:
    # FET: recent_low=0.209 < r382≈0.214204 → touched
    ladder = _ladder("0.209")
    assert _level(ladder, "retrace_0_382").recently_touched is True


def test_recently_touched_false_for_r500_when_above() -> None:
    # FET: recent_low=0.209 > r500=0.205 → NOT touched
    ladder = _ladder("0.209")
    assert _level(ladder, "retrace_0_500").recently_touched is False


def test_recently_touched_false_when_recent_low_just_above_r382() -> None:
    # recent_low=0.215 > r382≈0.214204 → NOT touched
    ladder = _ladder("0.215")
    assert _level(ladder, "retrace_0_382").recently_touched is False


def test_recently_touched_true_when_recent_low_exactly_at_level() -> None:
    r500_price = Decimal("0.205")
    ladder = _ladder(str(r500_price))
    assert _level(ladder, "retrace_0_500").recently_touched is True


def test_deepest_touched_label_r382_only() -> None:
    # recent_low=0.209 touches r382 but not r500/r618/r786
    ladder = _ladder("0.209")
    assert ladder.deepest_touched_label == "retrace_0_382"


def test_deepest_touched_label_r500() -> None:
    # recent_low=0.203 touches r382 and r500 but not r618
    ladder = _ladder("0.203")
    assert ladder.deepest_touched_label == "retrace_0_500"


def test_deepest_touched_label_none_when_no_touch() -> None:
    # recent_low=0.240 above all levels
    ladder = _ladder("0.240")
    assert ladder.deepest_touched_label is None


def test_missed_main_rebuy_by_pct_fet() -> None:
    # FET: recent_low=0.209, r500=0.205 → missed by ≈1.95%
    ladder = _ladder("0.209")
    assert ladder.missed_main_rebuy_by_pct is not None
    assert abs(ladder.missed_main_rebuy_by_pct - Decimal("1.95")) < Decimal("0.05")


def test_missed_main_rebuy_by_pct_none_when_touched() -> None:
    # recent_low=0.200 <= r500=0.205 → touched, no miss
    ladder = _ladder("0.200")
    assert ladder.missed_main_rebuy_by_pct is None


def test_missed_main_rebuy_by_pct_none_when_no_recent_low() -> None:
    ladder = _ladder()
    assert ladder.missed_main_rebuy_by_pct is None


def test_raises_on_swing_high_lte_swing_low() -> None:
    try:
        build_fib_retrace_ladder(
            HtfReentryInput(
                symbol="X",
                interval_code="1d",
                swing_low=Decimal("0.5"),
                swing_high=Decimal("0.5"),
                current_price=Decimal("0.6"),
            )
        )
        assert False, "Expected ValueError"
    except ValueError:
        pass


def test_raises_on_zero_current_price() -> None:
    try:
        build_fib_retrace_ladder(
            HtfReentryInput(
                symbol="X",
                interval_code="1d",
                swing_low=Decimal("0.1"),
                swing_high=Decimal("0.5"),
                current_price=Decimal("0"),
            )
        )
        assert False, "Expected ValueError"
    except ValueError:
        pass


def test_no_forbidden_imports_ast() -> None:
    src = Path("src/research/htf_fib_reentry_ladder_v1.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    forbidden = {"db", "bitvavo_client", "decision_gate", "execution_planner", "executor", "pymysql"}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module = ""
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module = alias.name or ""
                    for f in forbidden:
                        assert f not in module, f"forbidden import '{f}' found in pure module"
            else:
                module = node.module or ""
                for f in forbidden:
                    assert f not in module, f"forbidden import '{f}' found in pure module"


def main() -> None:
    test_basic_ladder_has_four_levels()
    test_level_labels_in_order()
    test_level_roles()
    test_leg_size()
    test_fet_retrace_0_382_price()
    test_fet_retrace_0_500_price()
    test_fet_retrace_0_618_price()
    test_fet_retrace_0_786_price()
    test_levels_ordered_high_to_low_price()
    test_distance_to_current_pct_correct()
    test_distance_to_current_pct_negative_when_level_below_current()
    test_distance_to_current_pct_positive_when_level_above_current()
    test_distance_to_recent_low_pct_when_provided()
    test_distance_to_recent_low_pct_none_when_no_recent_low()
    test_recently_touched_true_when_recent_low_at_r382_zone()
    test_recently_touched_false_for_r500_when_above()
    test_recently_touched_false_when_recent_low_just_above_r382()
    test_recently_touched_true_when_recent_low_exactly_at_level()
    test_deepest_touched_label_r382_only()
    test_deepest_touched_label_r500()
    test_deepest_touched_label_none_when_no_touch()
    test_missed_main_rebuy_by_pct_fet()
    test_missed_main_rebuy_by_pct_none_when_touched()
    test_missed_main_rebuy_by_pct_none_when_no_recent_low()
    test_raises_on_swing_high_lte_swing_low()
    test_raises_on_zero_current_price()
    test_no_forbidden_imports_ast()
    print("ok")


if __name__ == "__main__":
    main()
