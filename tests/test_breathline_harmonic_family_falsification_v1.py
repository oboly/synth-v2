from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import src.research.run_breathline_harmonic_family_falsification_v1 as runner
from src.research.breathline_harmonic_family_registry_v1 import (
    DURATION_FAMILY_DAYS,
    HALF_PHASE_SPLIT_CANDIDATE_DAYS,
    NULL_PERMUTATIONS,
    PHASE_MARKERS,
    RANDOM_SEED,
    REGISTRY_VERSION,
)


BASE = datetime(2025, 1, 1, tzinfo=UTC)


def iso(day: float) -> str:
    return (BASE + timedelta(days=day)).isoformat().replace("+00:00", "Z")


def cycle(
    symbol: str,
    index: int,
    *,
    start_day: float,
    duration_days: float,
    main: bool = True,
    extension: bool = False,
) -> dict[str, object]:
    recognition_day = start_day + 2.0
    ignition_day = start_day + 2.5
    main_day = start_day + 3.5 if main else None
    extension_day = start_day + 4.0 if extension else None
    end_day = start_day + duration_days
    return {
        "cycle_id": f"{symbol.lower()}-{index:02d}",
        "symbol": symbol,
        "previous_cycle_id": None,
        "start_ts": iso(start_day),
        "end_ts": iso(end_day),
        "cycle_status": "OBSERVED" if main else "FAILED",
        "observed_cycle_length_days": duration_days,
        "phase_offset_days": -9.0,
        "previous_phase_offset_days": -9.0 if index else None,
        "phase_drift_days": 0.0 if index else None,
        "first_high_ts": iso(start_day + 0.5),
        "first_high_price": 105.0,
        "first_low_ts": iso(start_day + 1.0),
        "first_low_price": 101.0,
        "second_high_ts": iso(start_day + 1.5),
        "second_high_price": 108.0,
        "recognition_ts": iso(recognition_day),
        "recognition_price": 104.0,
        "ignition_ts": iso(ignition_day),
        "ignition_price": 106.0,
        "main_pulse_ts": None if main_day is None else iso(main_day),
        "main_pulse_price": None if main_day is None else 112.0,
        "extension_ts": None if extension_day is None else iso(extension_day),
        "extension_price": None if extension_day is None else 118.0,
        "recognition_confirmed_at_ts": iso(recognition_day + 0.25),
        "ignition_confirmed_at_ts": iso(ignition_day + 0.25),
        "main_pulse_confirmed_at_ts": None if main_day is None else iso(main_day + 0.25),
        "extension_confirmed_at_ts": None if extension_day is None else iso(extension_day + 0.25),
        "recognition_progress_ratio": 2.0 / 21.0,
        "ignition_progress_ratio": 2.5 / 21.0,
        "recognition_ratio_used": 0.55,
        "ignition_ratio_used": 0.72,
        "recognition_state": "CONFIRMED",
        "ignition_state": "ACTIVE",
        "extension_runner_state": "ACTIVE" if extension else "BUILDING",
        "higher_low_confirmed": True,
        "main_pulse_confirmed": main,
        "extension_confirmed": extension,
        "expected_node_ts": {},
        "timing_error_days": {},
        "recognition_volume_snapshot": {},
        "ignition_volume_snapshot": {},
        "main_pulse_volume_snapshot": {},
        "reset_reason": None if main else "NO_MAIN_PULSE_CONFIRMATION",
        "phase_shift_reason": None,
        "feature_as_of_ts": iso(ignition_day + 0.25),
        "outcome_as_of_ts": iso(end_day + 0.25),
        "research_only": True,
    }


def fixture_cycles() -> dict[str, list[dict[str, object]]]:
    result: dict[str, list[dict[str, object]]] = {"RENDER": [], "TAO": []}
    for symbol, shift in (("RENDER", 0.0), ("TAO", 1.0)):
        for index in range(12):
            result[symbol].append(
                cycle(
                    symbol,
                    index,
                    start_day=shift + index * 8.0,
                    duration_days=3.0 + (index % 4),
                    main=index % 3 != 0,
                    extension=index % 4 == 0,
                )
            )
    return result


def write_source_run(tmp_path: Path) -> Path:
    run_dir = tmp_path / "source-run"
    assets = []
    cycles = fixture_cycles()
    for asset_id, symbol in ((38, "RENDER"), (69, "TAO")):
        source_dir = run_dir / symbol / "source"
        tracker_dir = run_dir / symbol / "tracker"
        source_dir.mkdir(parents=True)
        tracker_dir.mkdir(parents=True)
        source_csv = source_dir / "canonical_candles.csv"
        source_csv.write_text("ts,open,high,low,close,volume\n", encoding="utf-8")
        ledger = tracker_dir / "cycle_ledger.jsonl"
        with ledger.open("w", encoding="utf-8") as handle:
            for row in cycles[symbol]:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
        summary = tracker_dir / "summary.json"
        summary.write_text(
            json.dumps(
                {
                    "model_version": "bullish-breathline-tracker-v1.0.0",
                    "symbol": symbol,
                    "cycle_count": len(cycles[symbol]),
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        assets.append(
            {
                "asset_id": asset_id,
                "symbol": symbol,
                "source_sha256": runner.sha256_file(source_csv),
                "source_row_count": 1,
                "first_source_ts": iso(0),
                "last_source_ts": iso(100),
                "source_gap_count": 0,
                "tracker_artifacts": {
                    "cycle_ledger.jsonl": {
                        "present": True,
                        "sha256": runner.sha256_file(ledger),
                    },
                    "summary.json": {
                        "present": True,
                        "sha256": runner.sha256_file(summary),
                    },
                },
                "tracker_summary": {"cycle_count": len(cycles[symbol])},
            }
        )
    (run_dir / "run_manifest.json").write_text(
        json.dumps(
            {
                "runner_name": runner.EXPECTED_SOURCE_RUNNER,
                "run_id": "synthetic-mechanics-only",
                "analysis_commit_sha": "source-commit",
                "symbols": ["RENDER", "TAO"],
                "research_only": True,
                "market_only": True,
                "assets": assets,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return run_dir


def test_registry_is_exactly_frozen() -> None:
    assert REGISTRY_VERSION == "1.0.1"
    assert DURATION_FAMILY_DAYS == (3.0, 6.0, 9.0, 12.0, 21.0, 42.0, 63.0, 105.0, 126.0, 147.0)
    assert tuple(ratio for _, ratio in PHASE_MARKERS) == (0.236, 0.382, 0.5, 0.618, 0.786, 1.0, 1.272)
    assert HALF_PHASE_SPLIT_CANDIDATE_DAYS == 10.5
    assert HALF_PHASE_SPLIT_CANDIDATE_DAYS not in DURATION_FAMILY_DAYS
    assert NULL_PERMUTATIONS == 2000
    assert RANDOM_SEED == 533001


def test_holm_bonferroni_is_monotone_and_familywise() -> None:
    corrected = runner.holm_bonferroni({"a": 0.01, "b": 0.03, "c": 0.04})
    assert corrected["a"]["p_value_adjusted"] == pytest.approx(0.03)
    assert corrected["b"]["p_value_adjusted"] == pytest.approx(0.06)
    assert corrected["c"]["p_value_adjusted"] == pytest.approx(0.06)
    assert corrected["a"]["reject_at_alpha"] is True
    assert corrected["b"]["reject_at_alpha"] is False


def test_tie_aware_auc() -> None:
    assert runner.tie_aware_auc([1.0, 1.0, 0.0], [True, False, False]) == pytest.approx(0.75)
    assert runner.tie_aware_auc([1.0, 2.0], [True, True]) is None


def test_extension_phase_null_uses_one_circular_representation() -> None:
    assert runner.circular_phase_distance(1.0, 1.272) == pytest.approx(0.272)
    assert runner.circular_phase_distance(0.0, 0.272) == pytest.approx(0.272)
    assert runner.circular_phase_distance(1.272, 1.272) == pytest.approx(0.0)

    rows = [
        {
            "cycle_id": "render-extension",
            "symbol": "RENDER",
            "node": "extension",
            "present": True,
            "observed_phase_position": 1.0,
            "phase_position_residual": -0.272,
        }
    ]
    result = runner.phase_null_tests(rows, permutations=20)
    extension = result["RENDER"]["extension"]
    assert extension["phase_null_metric"] == "shortest_unit_circle_distance"
    assert extension["mean_circular_phase_distance"] == pytest.approx(0.272)
    assert 0.0 < extension["p_value_raw"] <= 1.0


def test_split_is_chronological_per_asset() -> None:
    cycles = fixture_cycles()
    splits = runner.split_map(cycles)  # type: ignore[arg-type]
    for symbol in ("RENDER", "TAO"):
        labels = [splits[str(row["cycle_id"])] for row in cycles[symbol]]
        assert labels[:8] == ["discovery"] * 8
        assert labels[8:] == ["holdout"] * 4


def test_lane_a_retains_every_duration_candidate_and_missing_node() -> None:
    cycles = fixture_cycles()
    cycles["RENDER"][0]["extension_ts"] = None
    splits = runner.split_map(cycles)  # type: ignore[arg-type]
    durations, phases = runner.build_lane_a_rows(cycles, splits)  # type: ignore[arg-type]
    render_first = next(row for row in durations if row["cycle_id"] == "render-00")
    assert len(render_first["candidate_residuals"]) == len(DURATION_FAMILY_DAYS)
    assert render_first["nearest_candidate_duration_days"] == 3.0
    missing_extension = next(
        row for row in phases if row["cycle_id"] == "render-00" and row["node"] == "extension"
    )
    assert missing_extension["present"] is False
    assert missing_extension["phase_position_residual"] is None


def test_prior_completed_history_is_strictly_point_in_time() -> None:
    rows = [
        cycle("RENDER", 0, start_day=0, duration_days=4),
        cycle("RENDER", 1, start_day=10, duration_days=6),
        cycle("RENDER", 2, start_day=20, duration_days=100),
    ]
    feature = runner.parse_ts(iso(18))
    values = runner.prior_completed_durations(rows, feature_as_of_ts=feature, symbol="RENDER")
    assert values == [4.0, 6.0]
    assert 100.0 not in values


def test_future_cycle_mutation_cannot_change_earlier_predictor_fields() -> None:
    cycles = fixture_cycles()
    splits = runner.split_map(cycles)  # type: ignore[arg-type]
    before = runner.build_lane_b_rows(cycles, splits)  # type: ignore[arg-type]
    target_before = next(
        row for row in before if row["cycle_id"] == "render-08" and row["checkpoint"] == "recognition"
    )

    cycles["RENDER"][11]["observed_cycle_length_days"] = 140.0
    cycles["RENDER"][11]["main_pulse_confirmed"] = not bool(cycles["RENDER"][11]["main_pulse_confirmed"])
    cycles["RENDER"][11]["extension_confirmed"] = not bool(cycles["RENDER"][11]["extension_confirmed"])
    after = runner.build_lane_b_rows(cycles, splits)  # type: ignore[arg-type]
    target_after = next(
        row for row in after if row["cycle_id"] == "render-08" and row["checkpoint"] == "recognition"
    )

    assert target_before["candidate_alignment_absolute_error_days"] == target_after["candidate_alignment_absolute_error_days"]
    assert target_before["family_selected_duration_days"] == target_after["family_selected_duration_days"]
    assert target_before["predictor_durations_days"] == target_after["predictor_durations_days"]
    assert target_before["asset_prior_completed_cycle_count"] == target_after["asset_prior_completed_cycle_count"]
    assert target_before["pooled_prior_completed_cycle_count"] == target_after["pooled_prior_completed_cycle_count"]


def test_source_provenance_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    source_run = write_source_run(tmp_path)
    ledger = source_run / "RENDER" / "tracker" / "cycle_ledger.jsonl"
    ledger.write_text(ledger.read_text(encoding="utf-8") + "{}\n", encoding="utf-8")
    with pytest.raises(runner.InputProvenanceError, match="hash mismatch"):
        runner.validate_source_run(source_run)


def test_full_synthetic_mechanics_flow_writes_research_artifacts(tmp_path: Path) -> None:
    source_run = write_source_run(tmp_path)
    out_dir = tmp_path / "out"
    manifest = runner.analyze(source_run_dir=source_run, out_dir=out_dir, permutations=20)

    assert manifest["runner_name"] == runner.RUNNER_NAME
    assert manifest["registry_version"] == REGISTRY_VERSION
    assert manifest["permutations_executed"] == 20
    assert manifest["safety"]["research_only"] is True
    assert manifest["safety"]["account_awareness"] == 0
    assert manifest["safety"]["broker_writes"] == 0
    assert manifest["safety"]["decision_gate"] == "none"
    assert (out_dir / "lane_a_cycle_residuals.jsonl").is_file()
    assert (out_dir / "lane_a_phase_residuals.jsonl").is_file()
    assert (out_dir / "lane_a_summary.json").is_file()
    assert (out_dir / "lane_b_checkpoint_rows.jsonl").is_file()
    assert (out_dir / "lane_b_candidate_tests.jsonl").is_file()
    assert (out_dir / "lane_b_summary.json").is_file()
    assert (out_dir / "run_manifest.json").is_file()

    lane_a = json.loads((out_dir / "lane_a_summary.json").read_text(encoding="utf-8"))
    assert lane_a["registry_version"] == "1.0.1"
    assert (
        lane_a["populations"]["RENDER"]["phase_markers"]["extension"]["phase_null_metric"]
        == "shortest_unit_circle_distance"
    )

    lane_b = json.loads((out_dir / "lane_b_summary.json").read_text(encoding="utf-8"))
    assert set(lane_b["populations"]) == {"RENDER", "TAO", "POOLED"}
    assert lane_b["populations"]["RENDER"]["recognition"]["holdout_sample_count"] == 4


def test_main_never_deletes_preexisting_immutable_run_directory(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    out_root = tmp_path / "out-root"
    out_dir = out_root / "already-complete"
    out_dir.mkdir(parents=True)
    sentinel = out_dir / "sentinel.txt"
    sentinel.write_text("immutable-evidence\n", encoding="utf-8")

    rc = runner.main(
        [
            "--source-run-dir",
            str(tmp_path / "missing-source-is-not-reached"),
            "--out-root",
            str(out_root),
            "--run-id",
            "already-complete",
        ]
    )
    output = capsys.readouterr().out

    assert rc == 1
    assert out_dir.is_dir()
    assert sentinel.read_text(encoding="utf-8") == "immutable-evidence\n"
    assert "FAILED breathline_harmonic_family_falsification_v1" in output
    assert "immutable output directory already exists" in output
