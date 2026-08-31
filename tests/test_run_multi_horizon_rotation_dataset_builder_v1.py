from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from src.research.multi_horizon_rotation_dataset_builder_v1 import (
    RotationV1PitIndex,
    RotationV1Point,
)
from src.research.multi_horizon_rotation_replay_v1 import CANDIDATE_SPECS, Candle, CandidateResult
from src.research.run_multi_horizon_rotation_dataset_builder_v1 import (
    ALLOWED_PHASES,
    build_validation_row,
    chunk_asof_grid_by_utc_day,
    load_checkpoint,
    manifest_fingerprint,
    mark_checkpoint_terminal,
    parse_args,
    persist_or_reuse_manifest,
    reconcile_partial_to_checkpoint,
    replay_candles_at_asof,
    validate_resume_checkpoint,
    write_checkpoint,
)


BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _manifest(*, end: str = "2026-02-01T00:00:00Z") -> dict[str, object]:
    return {
        "manifest_version": "1.0.0",
        "venue": "bitvavo",
        "source_span_method": "test",
        "minimum_cohort": 20,
        "coverage_asset_count": 20,
        "source_coverage_sha256": "coverage",
        "source_span": {"start": "2026-01-01T00:00:00Z", "end": end},
        "rotation_v1_first_ts": "2026-01-01T00:00:00Z",
        "final_holdout_inspected": False,
        "splits": {
            "discovery": {"start": "2026-01-01T00:00:00Z", "end": "2026-01-20T00:00:00Z"},
            "validation": {"start": "2026-01-20T00:00:00Z", "end": "2026-01-26T00:00:00Z"},
            "final_holdout": {"start": "2026-01-26T00:00:00Z", "end": end},
        },
    }


def test_runner_exposes_only_discovery_and_validation_phases() -> None:
    assert ALLOWED_PHASES == ("discovery", "validation")
    args = parse_args(["--phase", "discovery", "--resume"])
    assert args.phase == "discovery"
    assert args.resume is True
    try:
        parse_args(["--phase", "final_holdout"])
    except SystemExit as exc:
        assert exc.code != 0
    else:
        raise AssertionError("final_holdout must not be a CLI phase")


def test_frozen_manifest_is_created_once_reused_unchanged_and_rejects_drift(tmp_path: Path) -> None:
    path = tmp_path / "split_manifest_v1.json"
    candidate = _manifest()
    first, first_state = persist_or_reuse_manifest(path, candidate)
    first_bytes = path.read_bytes()
    second, second_state = persist_or_reuse_manifest(path, dict(candidate))
    assert first_state == "CREATED"
    assert second_state == "REUSED"
    assert first == second
    assert path.read_bytes() == first_bytes

    drifted = _manifest(end="2026-02-02T00:00:00Z")
    try:
        persist_or_reuse_manifest(path, drifted)
    except ValueError as exc:
        assert "disagrees with frozen split manifest" in str(exc)
    else:
        raise AssertionError("later phase must not replace a changed frozen split manifest")
    assert path.read_bytes() == first_bytes


def test_concurrent_frozen_manifest_creation_has_one_winner_and_reuses_identical_manifest(tmp_path: Path) -> None:
    path = tmp_path / "split_manifest_v1.json"
    candidate = _manifest()

    def persist(_: int) -> tuple[dict[str, object], str]:
        return persist_or_reuse_manifest(path, dict(candidate))

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(persist, range(8)))

    states = [state for _, state in results]
    assert states.count("CREATED") == 1
    assert states.count("REUSED") == 7
    assert all(manifest_fingerprint(manifest) == manifest_fingerprint(candidate) for manifest, _ in results)
    assert manifest_fingerprint(_manifest()) == manifest_fingerprint(candidate)


def test_asof_grid_chunks_by_utc_day_without_reordering() -> None:
    grid = [
        BASE + timedelta(hours=23, minutes=45),
        BASE + timedelta(days=1),
        BASE + timedelta(days=1, minutes=15),
    ]
    chunks = chunk_asof_grid_by_utc_day(grid)
    assert chunks == [[grid[0]], [grid[1], grid[2]]]


def test_replay_slice_never_uses_future_chunk_candles_and_keeps_missing_asset() -> None:
    asof = BASE + timedelta(hours=40)
    candles = {
        1: [
            Candle(asof - timedelta(hours=36), Decimal("100"), Decimal("1")),
            Candle(asof, Decimal("101"), Decimal("1")),
            Candle(asof + timedelta(minutes=15), Decimal("102"), Decimal("1")),
        ],
        3: [Candle(asof, Decimal("50"), Decimal("2"))],
    }
    sliced = replay_candles_at_asof(
        chunk_candles=candles,
        observed_asset_ids=(1, 2),
        asof_ts=asof,
    )
    assert set(sliced) == {1, 2}
    assert [item.close_ts_utc for item in sliced[1]] == [asof - timedelta(hours=36), asof]
    assert sliced[2] == []
    assert 3 not in sliced


def test_interrupt_then_resume_trims_uncheckpointed_bytes_and_preserves_committed_state(tmp_path: Path) -> None:
    manifest = _manifest()
    fingerprint = manifest_fingerprint(manifest)
    committed = b'{"row":1}\n{"row":2}\n'
    uncheckpointed = b'{"row":3'
    partial = tmp_path / ".validation_rows_v1.jsonl.partial"
    partial.write_bytes(committed + uncheckpointed)
    checkpoint_path = tmp_path / ".validation_checkpoint_v1.json"
    completed_asof = BASE + timedelta(minutes=15)
    write_checkpoint(
        checkpoint_path,
        venue="bitvavo",
        phase="validation",
        manifest_sha256=fingerprint,
        last_completed_asof=completed_asof,
        asofs_completed=2,
        row_count=2,
        partial_bytes=len(committed),
        source_query_count=1,
        source_rows_read=100,
        terminal_state="RUNNING",
    )

    mark_checkpoint_terminal(checkpoint_path, terminal_state="INTERRUPTED")
    interrupted = load_checkpoint(checkpoint_path)
    assert interrupted["terminal_state"] == "INTERRUPTED"
    assert interrupted["row_count"] == 2
    assert interrupted["asofs_completed"] == 2
    assert interrupted["last_completed_asof"] == completed_asof.isoformat().replace("+00:00", "Z")

    validate_resume_checkpoint(
        interrupted,
        venue="bitvavo",
        phase="validation",
        expected_manifest_sha256=fingerprint,
    )
    reconcile_partial_to_checkpoint(partial, interrupted)
    assert partial.read_bytes() == committed

    with partial.open("ab") as handle:
        handle.write(b'{"row":3}\n')
    assert partial.read_bytes().count(b"\n") == 3


def test_resume_rejects_changed_split_or_source_manifest(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / ".discovery_checkpoint_v1.json"
    write_checkpoint(
        checkpoint_path,
        venue="bitvavo",
        phase="discovery",
        manifest_sha256="old",
        last_completed_asof=None,
        asofs_completed=0,
        row_count=0,
        partial_bytes=0,
        source_query_count=0,
        source_rows_read=0,
        terminal_state="INTERRUPTED",
    )
    checkpoint = load_checkpoint(checkpoint_path)
    try:
        validate_resume_checkpoint(
            checkpoint,
            venue="bitvavo",
            phase="discovery",
            expected_manifest_sha256="new",
        )
    except ValueError as exc:
        assert "manifest mismatch" in str(exc)
    else:
        raise AssertionError("resume must fail when source/split manifest changed")


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
