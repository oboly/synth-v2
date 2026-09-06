from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.market_data.fib_navigation_map_v1 import DIRECTION_BEARISH, DIRECTION_BULLISH
from src.research.execution_offset_replay_v1 import ExecutionOffsetEpisodeV1, ReplayCandle, SIDE_BUY, SIDE_SELL
from src.research.target_capture_calibration_adapter_v1 import TargetEpisodeAnalysisContextV1
from src.research.target_capture_calibration_analysis_v1 import (
    CANDIDATE_BUFFER_PCTS,
    DISPOSITION_EXECUTION_PLANNER_CANDIDATE,
    DISPOSITION_REJECT,
    DISPOSITION_RESEARCH_ONLY,
    CalibrationInputV1,
    TargetCaptureCalibrationError,
    build_calibration_report,
    candidate_policies,
    render_calibration_report_json,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def make_input(i: int, *, peak: Decimal, direction: str = DIRECTION_BULLISH, fib: str = "F1.272", horizon: str = "4h") -> CalibrationInputV1:
    bullish = direction == DIRECTION_BULLISH
    canonical = Decimal("100")
    episode_id = f"ep-{i:03d}"
    episode = ExecutionOffsetEpisodeV1(
        episode_id=episode_id, symbol="PROM", venue="bitvavo", horizon=horizon,
        side=SIDE_SELL if bullish else SIDE_BUY, fib_level_id=fib,
        canonical_level=canonical, issued_ts_utc=T0,
        valid_until_ts_utc=T0 + timedelta(hours=8),
        invalidation_price=Decimal("90") if bullish else Decimal("110"),
        atr_at_issue=Decimal("2"), regime_state=None, source_map_id=f"map-{i:03d}",
    )
    context = TargetEpisodeAnalysisContextV1(
        episode_id=episode_id, source_map_id=f"map-{i:03d}", target_role="T1",
        reference_price=Decimal("90") if bullish else Decimal("110"), direction=direction,
    )
    if bullish:
        high, low = peak, Decimal("95")
        close = min(Decimal("98"), high)
    else:
        high, low = Decimal("105"), peak
        close = max(Decimal("102"), low)
    candle = ReplayCandle(T0, T0 + timedelta(hours=4), high, low, close)
    return CalibrationInputV1(episode, context, (candle,))


def test_candidate_set_is_frozen() -> None:
    policies = candidate_policies()
    assert tuple(p.buffer_pct for p in policies) == CANDIDATE_BUFFER_PCTS


def test_required_buffer_quantiles_use_exact_near_miss_pct_points() -> None:
    inputs = [make_input(i, peak=peak) for i, peak in enumerate((Decimal("100"), Decimal("99.5"), Decimal("99"), Decimal("98.5")))]
    report = build_calibration_report(inputs, min_sample_threshold=1)
    q = report["overall"]["required_buffer_quantiles_pct_points"]
    assert q["p50"] == Decimal("0.5")
    assert q["p75"] == Decimal("1")
    assert q["p90"] == Decimal("1.5")


def test_buffer_can_improve_capture_and_expected_return() -> None:
    inputs = [make_input(i, peak=Decimal("99")) for i in range(30)]
    report = build_calibration_report(inputs, min_sample_threshold=30)
    assert report["disposition"] == DISPOSITION_EXECUTION_PLANNER_CANDIDATE
    assert report["selected_buffer_pct_fraction"] == Decimal("0.01")
    one_pct = next(c for c in report["overall"]["candidates"] if c["buffer_pct_fraction"] == Decimal("0.01"))
    assert one_pct["capture_rate_pct"] == Decimal("100")
    assert one_pct["expected_return_delta_vs_exact_pct_points"] > 0


def test_no_positive_candidate_is_reject() -> None:
    inputs = [make_input(i, peak=Decimal("100")) for i in range(30)]
    report = build_calibration_report(inputs, min_sample_threshold=30)
    assert report["disposition"] == DISPOSITION_REJECT


def test_insufficient_sample_is_research_only() -> None:
    report = build_calibration_report([make_input(1, peak=Decimal("99"))], min_sample_threshold=30)
    assert report["disposition"] == DISPOSITION_RESEARCH_ONLY


def test_report_is_input_order_independent_and_byte_stable() -> None:
    inputs = [make_input(i, peak=Decimal("99")) for i in range(3)]
    a = render_calibration_report_json(build_calibration_report(inputs, min_sample_threshold=1))
    b = render_calibration_report_json(build_calibration_report(reversed(inputs), min_sample_threshold=1))
    assert a == b


def test_raw_and_executable_levels_are_both_preserved() -> None:
    report = build_calibration_report([make_input(1, peak=Decimal("99"))], min_sample_threshold=1)
    rows = report["evidence_rows"]
    assert all(row["raw_canonical_level"] == Decimal("100") for row in rows)
    assert any(row["executable_level"] != row["raw_canonical_level"] for row in rows)


@pytest.mark.parametrize("threshold", [0, -1, True, False, 0.5, Decimal("1"), "1", None])
def test_invalid_threshold_fails_closed(threshold) -> None:
    with pytest.raises(TargetCaptureCalibrationError):
        build_calibration_report([make_input(1, peak=Decimal("99"))], min_sample_threshold=threshold)


def test_duplicate_episode_identity_fails_closed() -> None:
    item = make_input(1, peak=Decimal("99"))
    with pytest.raises(TargetCaptureCalibrationError, match="DUPLICATE_EPISODE_IDENTITY"):
        build_calibration_report([item, item], min_sample_threshold=1)


def test_context_identity_conflict_fails_closed() -> None:
    item = make_input(1, peak=Decimal("99"))
    bad = CalibrationInputV1(item.episode, TargetEpisodeAnalysisContextV1("other", item.context.source_map_id, "T1", item.context.reference_price, item.context.direction), item.candles)
    with pytest.raises(TargetCaptureCalibrationError, match="EPISODE_CONTEXT_IDENTITY_CONFLICT"):
        build_calibration_report([bad], min_sample_threshold=1)


def test_candidate_crossing_invalidation_is_explicitly_excluded_not_report_fatal() -> None:
    item = make_input(1, peak=Decimal("99"))
    from dataclasses import replace
    tight = CalibrationInputV1(replace(item.episode, invalidation_price=Decimal("99.4")), item.context, item.candles)
    report = build_calibration_report([tight], min_sample_threshold=1)
    half = next(c for c in report["overall"]["candidates"] if c["buffer_pct_fraction"] == Decimal("0.005"))
    one = next(c for c in report["overall"]["candidates"] if c["buffer_pct_fraction"] == Decimal("0.01"))
    assert half["candidate_geometry_excluded_count"] == 0
    assert one["candidate_geometry_excluded_count"] == 1
    assert any(e["buffer_pct_fraction"] == Decimal("0.01") for e in report["candidate_geometry_exclusions"])
