from src.reporting.chart_axis_v1 import (
    decimal_places_for_step,
    format_tick_label,
    nice_domain_and_ticks,
)


def test_spans_zero_produces_nice_symmetric_style_ticks() -> None:
    axis = nice_domain_and_ticks(-42.2, 62.2)
    assert axis.domain_min <= -42.2
    assert axis.domain_max >= 62.2
    assert 0.0 in axis.ticks
    assert list(axis.ticks) == sorted(axis.ticks)


def test_zero_tick_exactly_aligned_with_zero() -> None:
    axis = nice_domain_and_ticks(-18.0, 0.0)
    assert 0.0 in axis.ticks
    assert axis.domain_min <= -18.0
    assert axis.domain_max >= 0.0


def test_all_positive_viewport_domain_includes_visible_max_and_zero() -> None:
    # Caller folds zero into raw_min for an all-positive window before
    # calling this helper (see _rotation_history_html), so simulate that.
    axis = nice_domain_and_ticks(0.0, 5.0)
    assert axis.domain_min <= 0.0
    assert axis.domain_max >= 5.0
    assert 0.0 in axis.ticks


def test_all_negative_viewport_domain_includes_visible_min_and_zero() -> None:
    axis = nice_domain_and_ticks(-20.0, 0.0)
    assert axis.domain_min <= -20.0
    assert axis.domain_max >= 0.0
    assert 0.0 in axis.ticks


def test_single_point_degenerate_produces_nonzero_span() -> None:
    axis = nice_domain_and_ticks(0.0, 0.0)
    assert axis.domain_max > axis.domain_min
    assert len(axis.ticks) >= 2


def test_constant_nonzero_series_still_produces_nonzero_span() -> None:
    # A constant non-zero series folded with zero by the caller: raw_min=0,
    # raw_max=value already differs, so this exercises the non-degenerate
    # path, while an exact raw_min==raw_max==value simulates a caller that
    # does not fold in zero (defensive: must still not collapse to a point).
    axis = nice_domain_and_ticks(7.0, 7.0)
    assert axis.domain_max > axis.domain_min


def test_extremely_narrow_range_still_yields_readable_ticks() -> None:
    axis = nice_domain_and_ticks(0.0, 0.03)
    assert axis.domain_max >= 0.03
    assert len(axis.ticks) >= 2
    for tick in axis.ticks:
        label = format_tick_label(tick)
        # No more than 2 decimal places in any label.
        if "." in label:
            assert len(label.split(".")[1]) <= 2


def test_deterministic_identical_input_identical_output() -> None:
    first = nice_domain_and_ticks(-42.2, 62.2)
    second = nice_domain_and_ticks(-42.2, 62.2)
    assert first == second


def test_domain_always_contains_visible_min_and_max() -> None:
    for raw_min, raw_max in [(-1.0, 1.0), (0.0, 99.0), (-99.0, 0.0), (-3.3, 3.3), (0.0, 0.0)]:
        axis = nice_domain_and_ticks(raw_min, raw_max)
        assert axis.domain_min <= raw_min
        assert axis.domain_max >= raw_max


def test_format_tick_label_whole_numbers_have_no_decimal() -> None:
    assert format_tick_label(60.0) == "+60"
    assert format_tick_label(-40.0) == "-40"
    assert format_tick_label(0.0) == "0"


def test_format_tick_label_trims_trailing_decimal_zero() -> None:
    assert format_tick_label(2.5) == "+2.5"
    assert format_tick_label(-0.5) == "-0.5"


def test_format_tick_label_keeps_two_decimals_when_needed() -> None:
    assert format_tick_label(0.02) == "+0.02"


def test_sub_1e9_range_does_not_collapse_all_ticks_to_zero() -> None:
    # Second Codex review round on PR #515: round(value, 10) and a fixed
    # 1e-9 zero-snap silently zeroed every tick for a domain whose whole
    # span is smaller than 1e-9 (e.g. 0..1e-10), making the axis show one
    # overlapping "0" gridline instead of a real scale.
    axis = nice_domain_and_ticks(0.0, 1e-10)
    assert axis.domain_max >= 1e-10
    assert axis.step > 0.0
    nonzero_ticks = [tick for tick in axis.ticks if tick != 0.0]
    assert nonzero_ticks, "domain this small must still produce distinct nonzero ticks"
    decimals = decimal_places_for_step(axis.step)
    labels = [format_tick_label(tick, decimals=decimals) for tick in axis.ticks]
    assert len(labels) == len(set(labels))


def test_sub_cent_range_produces_distinct_non_colliding_labels() -> None:
    # Codex review on PR #515: a visible range narrower than 0.01 must not
    # collapse every distinct tick onto the same "+0.00"-style label.
    axis = nice_domain_and_ticks(0.0, 0.0001)
    decimals = decimal_places_for_step(axis.step)
    labels = [format_tick_label(tick, decimals=decimals) for tick in axis.ticks]
    assert len(labels) == len(set(labels))
    assert "0" in labels


def test_decimal_places_for_step_matches_nice_step_magnitude() -> None:
    assert decimal_places_for_step(20.0) == 0
    assert decimal_places_for_step(5.0) == 0
    assert decimal_places_for_step(0.5) == 1
    assert decimal_places_for_step(0.02) == 2
    assert decimal_places_for_step(0.00002) == 5


def test_format_tick_label_with_explicit_decimals_zero_pads_correctly() -> None:
    assert format_tick_label(0.00002, decimals=5) == "+0.00002"
    assert format_tick_label(20.0, decimals=0) == "+20"
    assert format_tick_label(0.0, decimals=5) == "0"
