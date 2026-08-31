from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from src.research.multi_horizon_rotation_dataset_builder_v1 import (
    AssetCoverage,
    RotationV1PitIndex,
    RotationV1Point,
    comparable_horizon_return,
    derive_common_source_span,
    forward_response,
    split_manifest_payload,
)
from src.research.multi_horizon_rotation_replay_v1 import CANDIDATE_SPECS


BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _coverage(asset_id: int, *, first_hours: int = 0, last_days: int = 100) -> AssetCoverage:
    return AssetCoverage(
        asset_id=asset_id,
        first_close_ts=BASE + timedelta(hours=first_hours),
        last_close_ts=BASE + timedelta(days=last_days),
    )


def test_common_source_span_uses_twentieth_asset_coverage_and_rotation_floor() -> None:
    coverage = [_coverage(index, first_hours=index) for index in range(1, 26)]
    rotation_first = BASE + timedelta(days=3)
    span = derive_common_source_span(
        coverage=coverage,
        rotation_v1_first_ts=rotation_first,
        minimum_cohort=20,
    )
    assert span.start == BASE + timedelta(days=3)
    assert span.end == BASE + timedelta(days=100)
    assert span.minimum_cohort == 20
    assert span.coverage_asset_count == 25


def test_common_source_span_fails_when_fewer_than_minimum_cohort_assets() -> None:
    coverage = [_coverage(index) for index in range(1, 20)]
    try:
        derive_common_source_span(
            coverage=coverage,
            rotation_v1_first_ts=BASE,
            minimum_cohort=20,
        )
    except ValueError as exc:
        assert "insufficient assets" in str(exc)
    else:
        raise AssertionError("minimum cohort coverage must fail closed")


def test_split_manifest_is_frozen_sixty_twenty_twenty() -> None:
    coverage = [_coverage(index) for index in range(1, 21)]
    span = derive_common_source_span(
        coverage=coverage,
        rotation_v1_first_ts=BASE + timedelta(hours=36),
        minimum_cohort=20,
    )
    manifest = split_manifest_payload(span)
    discovery = manifest["splits"]["discovery"]
    validation = manifest["splits"]["validation"]
    holdout = manifest["splits"]["final_holdout"]
    start = datetime.fromisoformat(discovery["start"].replace("Z", "+00:00"))
    discovery_end = datetime.fromisoformat(discovery["end"].replace("Z", "+00:00"))
    validation_end = datetime.fromisoformat(validation["end"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(holdout["end"].replace("Z", "+00:00"))
    total_steps = int((end - start).total_seconds() // 900)
    discovery_steps = int((discovery_end - start).total_seconds() // 900)
    validation_steps = int((validation_end - discovery_end).total_seconds() // 900)
    assert discovery_steps == int(total_steps * 0.60)
    assert validation_steps == int(total_steps * 0.20)
    assert manifest["final_holdout_inspected"] is False


def test_rotation_v1_pit_index_never_uses_future_row() -> None:
    index = RotationV1PitIndex(
        {
            1: [
                RotationV1Point(BASE, -20.0, "ROTATION_OUT"),
                RotationV1Point(BASE + timedelta(hours=1), 10.0, "MIXED"),
            ]
        }
    )
    before = index.latest_at_or_before(asset_id=1, asof_ts=BASE - timedelta(minutes=15))
    middle = index.latest_at_or_before(asset_id=1, asof_ts=BASE + timedelta(minutes=45))
    after = index.latest_at_or_before(asset_id=1, asof_ts=BASE + timedelta(hours=2))
    assert before is None
    assert middle is not None and middle.score_total == -20.0
    assert after is not None and after.score_total == 10.0


def test_comparable_horizon_return_requires_exact_boundary() -> None:
    spec = CANDIDATE_SPECS[1]
    asof = BASE + timedelta(hours=2)
    closes = {
        asof - timedelta(hours=1): Decimal("100"),
        asof: Decimal("110"),
    }
    value = comparable_horizon_return(close_by_ts=closes, asof_ts=asof, spec=spec)
    assert value is not None and value > 0
    missing = comparable_horizon_return(
        close_by_ts={asof: Decimal("110")},
        asof_ts=asof,
        spec=spec,
    )
    assert missing is None


def test_forward_response_is_purged_at_phase_boundary() -> None:
    asof = BASE + timedelta(hours=1)
    phase_end = BASE + timedelta(hours=2)
    closes = {
        asof: Decimal("100"),
        asof + timedelta(minutes=15): Decimal("101"),
        phase_end: Decimal("105"),
    }
    allowed = forward_response(
        close_by_ts=closes,
        asof_ts=asof,
        horizon=timedelta(minutes=15),
        phase_end=phase_end,
    )
    purged = forward_response(
        close_by_ts=closes,
        asof_ts=asof,
        horizon=timedelta(hours=1),
        phase_end=phase_end,
    )
    assert allowed is not None
    assert purged is None
