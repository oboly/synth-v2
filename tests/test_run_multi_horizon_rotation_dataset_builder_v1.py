from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from src.research.multi_horizon_rotation_dataset_builder_v1 import (
    RotationV1PitIndex,
    RotationV1Point,
)
from src.research.multi_horizon_rotation_replay_v1 import CANDIDATE_SPECS, CandidateResult
from src.research.run_multi_horizon_rotation_dataset_builder_v1 import (
    ALLOWED_PHASES,
    build_validation_row,
    parse_args,
)


BASE = datetime(2026, 1, 1, tzinfo=UTC)


def test_runner_exposes_only_discovery_and_validation_phases() -> None:
    assert ALLOWED_PHASES == ("discovery", "validation")
    args = parse_args(["--phase", "discovery"])
    assert args.phase == "discovery"
    try:
        parse_args(["--phase", "final_holdout"])
    except SystemExit as exc:
        assert exc.code != 0
    else:
        raise AssertionError("final_holdout must not be a CLI phase")


def test_build_validation_row_attaches_pit_b0_b1_and_purged_forwards() -> None:
    spec = CANDIDATE_SPECS[0]
    asof = BASE + timedelta(hours=4)
    result = CandidateResult(
        venue="bitvavo",
        asset_id=7,
        candidate_id=spec.candidate_id,
        model_id="multi_horizon_rotation_relative_flow",
        model_version=spec.model_version,
        input_interval="15m",
        lookback_horizon=spec.lookback_horizon,
        effective_horizon=spec.effective_horizon,
        observed_lifecycle="UNMEASURED",
        asof_ts=asof,
        freshness="FRESH",
        provenance="test",
        cohort_size=25,
        relative_return_unit=Decimal("0.1"),
        signed_flow_unit=Decimal("0.2"),
        relative_acceleration_unit=Decimal("0.3"),
        rotation_score=Decimal("20.000000"),
        data_quality="COMPLETE",
        reason="OK",
    )
    closes = {
        asof - timedelta(minutes=15): Decimal("100"),
        asof: Decimal("101"),
        asof + timedelta(minutes=15): Decimal("102"),
        asof + timedelta(hours=1): Decimal("103"),
    }
    pit = RotationV1PitIndex(
        {
            7: [
                RotationV1Point(asof - timedelta(hours=1), -40.0, "ROTATION_OUT"),
                RotationV1Point(asof + timedelta(hours=1), 50.0, "ROTATION_IN"),
            ]
        }
    )
    row = build_validation_row(
        result=result,
        close_by_ts=closes,
        spec_by_id={item.candidate_id: item for item in CANDIDATE_SPECS},
        pit_index=pit,
        phase_end=asof + timedelta(hours=1),
    )
    assert row["candidate_score"] == 20.0
    assert row["b0_score"] == -40.0
    assert row["b0_pressure_state"] == "ROTATION_OUT"
    assert row["b1_return"] is not None
    assert row["forward_15m"] is not None
    assert row["forward_1h"] is None
    assert row["forward_4h"] is None
    assert row["forward_24h"] is None
    assert row["b2_status"] == "UNAVAILABLE_NO_REPLAY_SAFE_CANONICAL_SOURCE"
