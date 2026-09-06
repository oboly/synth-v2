import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.market_data.fib_navigation_map_v1 import DIRECTION_BULLISH
from src.research import run_target_capture_calibration_v1 as runner
from src.research.historical_fib_map_episode_substrate_v1 import (
    EpisodeFeaturePayload,
    EpisodeOutcomeLabels,
    EpisodeRecord,
    HistoricalCandle,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)

ARGV = [
    "--venue",
    "bitvavo",
    "--symbol",
    "PROM",
    "--timeframe",
    "4h",
    "--from-ts",
    "2026-01-01T00:00:00+00:00",
    "--to-ts",
    "2026-01-01T04:00:00+00:00",
    "--min-sample-threshold",
    "1",
]


def make_feature(*, episode_id: str, terminal_forward: bool = True) -> EpisodeFeaturePayload:
    return EpisodeFeaturePayload(
        episode_id=episode_id,
        symbol="PROM",
        venue="bitvavo",
        source_timeframe="4h",
        builder_name="historical_fib_map_episode_substrate_v1",
        builder_version="2.0.0",
        contract_version="1.1.0",
        projection_engine_module="src.market_data.canonical_fib_zone_map_v1",
        projection_engine_function="build_row",
        map_version="v1",
        map_creation_ts_utc=T0,
        source_candle_first_ts_utc=T0 - timedelta(hours=180 * 4),
        source_candle_last_ts_utc=T0,
        source_candle_count=180,
        direction=DIRECTION_BULLISH,
        anchor_low_price=Decimal("90"),
        anchor_low_ts_utc=T0 - timedelta(hours=40),
        anchor_high_price=Decimal("110"),
        anchor_high_ts_utc=T0 - timedelta(hours=4),
        anchor_span_candles=10,
        anchor_span_elapsed_seconds=36 * 3600,
        swing_amplitude_pct=Decimal("22.22"),
        reference_price=Decimal("100"),
        entry_zone_low=Decimal("98"),
        entry_zone_high=Decimal("102"),
        entry_zone_mid=Decimal("100"),
        target_t1=Decimal("112.72"),
        target_t2=Decimal("116.18"),
        target_extension=Decimal("120"),
        invalidation_level=Decimal("90"),
        atr_value=Decimal("2"),
        atr_period=14,
        target_t1_distance_pct=Decimal("12.72"),
        target_t2_distance_pct=Decimal("16.18"),
        invalidation_distance_pct=Decimal("10"),
        target_t1_distance_atr=Decimal("6.36"),
        target_t2_distance_atr=Decimal("8.09"),
        invalidation_distance_atr=Decimal("5"),
        map_state="ACTIVE",
        map_confidence="HIGH",
        rebuild_trigger="NONE",
        canonical_provenance_payload={},
    )


def make_labels(*, episode_id: str, terminal_forward: bool = True) -> EpisodeOutcomeLabels:
    terminal_ts_utc = T0 + timedelta(hours=8) if terminal_forward else T0
    reason = "TARGET2_REACHED" if terminal_forward else "SOURCE_DATA_EXHAUSTED"
    return EpisodeOutcomeLabels(
        episode_id=episode_id,
        first_entry_ts_utc=None,
        time_to_first_entry_seconds=None,
        target1_ts_utc=T0 + timedelta(hours=4) if terminal_forward else None,
        time_to_target1_seconds=4 * 3600 if terminal_forward else None,
        target2_ts_utc=T0 + timedelta(hours=8) if terminal_forward else None,
        time_to_target2_seconds=8 * 3600 if terminal_forward else None,
        invalidation_ts_utc=None,
        time_to_invalidation_seconds=None,
        ambiguous_ts_utc=None,
        terminal_ts_utc=terminal_ts_utc,
        map_lifetime_seconds=(terminal_ts_utc - T0).total_seconds(),
        lifecycle_transition_reason=reason,
        num_source_candles_until_terminal=2 if terminal_forward else 0,
        forward_candles_scanned=2 if terminal_forward else 0,
    )


def make_record(*, episode_id: str = "map-1", terminal_forward: bool = True) -> EpisodeRecord:
    return EpisodeRecord(
        feature=make_feature(episode_id=episode_id, terminal_forward=terminal_forward),
        labels=make_labels(episode_id=episode_id, terminal_forward=terminal_forward),
    )


def forward_candle(hours: int, *, high: str, low: str = "99") -> HistoricalCandle:
    close_ts = T0 + timedelta(hours=hours)
    return HistoricalCandle(
        symbol="PROM",
        venue="bitvavo",
        interval_code="4h",
        open_ts_utc=close_ts - timedelta(hours=4),
        close_ts_utc=close_ts,
        open_price=Decimal("100"),
        high_price=Decimal(high),
        low_price=Decimal(low),
        close_price=Decimal("100"),
    )


DEFAULT_FORWARD_CANDLES = [
    forward_candle(4, high="113"),
    forward_candle(8, high="117"),
]


def _install_fetch_mocks(
    monkeypatch,
    *,
    records,
    forward_candles=None,
    asset_id: int = 42,
):
    forward = list(DEFAULT_FORWARD_CANDLES if forward_candles is None else forward_candles)

    monkeypatch.setattr(runner, "fetch_asset_id", lambda **kwargs: asset_id)
    monkeypatch.setattr(
        runner, "fetch_ema_state_prehistory_candles", lambda **kwargs: []
    )
    monkeypatch.setattr(runner, "fetch_candles", lambda **kwargs: [])
    monkeypatch.setattr(
        runner, "fetch_forward_tail_candles", lambda **kwargs: forward
    )
    monkeypatch.setattr(runner, "build_episodes", lambda **kwargs: list(records))


def _read_json(path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _run(monkeypatch, tmp_path, *, records, forward_candles=None, extra_argv=None):
    _install_fetch_mocks(monkeypatch, records=records, forward_candles=forward_candles)
    argv = list(ARGV) + ["--output-dir", str(tmp_path)] + list(extra_argv or [])
    exit_code = runner.main(argv)
    return exit_code


def test_successful_run_publishes_report_and_manifest(monkeypatch, tmp_path, capsys) -> None:
    exit_code = _run(monkeypatch, tmp_path, records=[make_record()])
    assert exit_code == 0

    out = capsys.readouterr().out
    assert "STARTED runner=target_capture_calibration_runner_v1" in out
    assert out.strip().splitlines()[-1].startswith("FINISHED")

    run_dirs = list(tmp_path.glob("bitvavo/PROM/4h/*"))
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]

    report = _read_json(run_dir / "report_v1.json")
    manifest = _read_json(run_dir / "manifest_v1.json")

    assert report["version"] == "target_capture_calibration_analysis_v1"
    assert "report_fingerprint" in report

    assert manifest["mapped_target_episode_count"] == 2  # T1 + T2 for one record
    assert manifest["excluded_target_episode_count"] == 0
    assert manifest["exclusion_reason_counts"] == {}
    assert manifest["source_episode_count"] == 1
    assert manifest["report_fingerprint"] == report["report_fingerprint"]
    assert manifest["run_id"] == run_dir.name
    assert manifest["disposition"] == report["disposition"]
    assert manifest["safety_markers"]["db_writes"] == 0
    assert manifest["safety_markers"]["decision_gate"] == "none"


def test_rerun_with_identical_inputs_is_idempotent(monkeypatch, tmp_path) -> None:
    exit_code_1 = _run(monkeypatch, tmp_path, records=[make_record()])
    assert exit_code_1 == 0
    run_dirs = list(tmp_path.glob("bitvavo/PROM/4h/*"))
    report_before = (run_dirs[0] / "report_v1.json").read_text(encoding="utf-8")
    manifest_before = (run_dirs[0] / "manifest_v1.json").read_text(encoding="utf-8")

    exit_code_2 = _run(monkeypatch, tmp_path, records=[make_record()])
    assert exit_code_2 == 0
    run_dirs_after = list(tmp_path.glob("bitvavo/PROM/4h/*"))
    assert len(run_dirs_after) == 1
    assert (run_dirs_after[0] / "report_v1.json").read_text(encoding="utf-8") == report_before
    assert (run_dirs_after[0] / "manifest_v1.json").read_text(encoding="utf-8") == manifest_before


def test_conflicting_repeat_run_fails_closed_on_output_write(monkeypatch, tmp_path, capsys) -> None:
    exit_code_1 = _run(monkeypatch, tmp_path, records=[make_record()])
    assert exit_code_1 == 0

    # Same requested candle content (same source_input_sha256 / run_id) but
    # different build_episodes() output -> different report content at the
    # SAME immutable path. Must fail closed, never silently overwrite.
    exit_code_2 = _run(
        monkeypatch,
        tmp_path,
        records=[make_record(episode_id="map-2")],
    )
    assert exit_code_2 != 0
    out = capsys.readouterr().out
    assert "FAILED reason=output_write_failed" in out


def test_exclusions_are_counted_and_reported_not_dropped(monkeypatch, tmp_path) -> None:
    records = [
        make_record(episode_id="map-good", terminal_forward=True),
        make_record(episode_id="map-excluded", terminal_forward=False),
    ]
    exit_code = _run(monkeypatch, tmp_path, records=records)
    assert exit_code == 0

    run_dir = list(tmp_path.glob("bitvavo/PROM/4h/*"))[0]
    manifest = _read_json(run_dir / "manifest_v1.json")

    assert manifest["mapped_target_episode_count"] == 2
    assert manifest["excluded_target_episode_count"] == 2
    assert manifest["exclusion_reason_counts"] == {"VALIDITY_WINDOW_UNRESOLVED": 2}
    exclusion_source_ids = {e["source_map_id"] for e in manifest["exclusions"]}
    assert exclusion_source_ids == {"map-excluded"}


def test_all_excluded_fails_closed_with_no_calibration_inputs(monkeypatch, tmp_path, capsys) -> None:
    records = [make_record(episode_id="map-only", terminal_forward=False)]
    exit_code = _run(monkeypatch, tmp_path, records=records)
    assert exit_code != 0
    out = capsys.readouterr().out
    assert "FAILED reason=calibration_failed" in out
    assert not list(tmp_path.glob("bitvavo/PROM/4h/*"))


def test_invalid_arguments_fail_closed_before_any_fetch(monkeypatch, tmp_path, capsys) -> None:
    calls = []
    monkeypatch.setattr(runner, "fetch_asset_id", lambda **kwargs: calls.append(1) or 1)
    argv = list(ARGV) + ["--output-dir", str(tmp_path), "--max-episodes", "-1"]
    exit_code = runner.main(argv)
    assert exit_code == 2
    assert not calls
    out = capsys.readouterr().out
    assert "FAILED reason=invalid_arguments" in out


def test_invalid_target_roles_fail_closed(monkeypatch, tmp_path, capsys) -> None:
    argv = list(ARGV) + ["--output-dir", str(tmp_path), "--target-roles", "T1,T3"]
    exit_code = runner.main(argv)
    assert exit_code == 2
    out = capsys.readouterr().out
    assert "FAILED reason=invalid_arguments" in out


def test_asset_lookup_failure_fails_closed(monkeypatch, tmp_path, capsys) -> None:
    def _raise(**kwargs):
        raise ValueError("no asset found")

    monkeypatch.setattr(runner, "fetch_asset_id", _raise)
    argv = list(ARGV) + ["--output-dir", str(tmp_path)]
    exit_code = runner.main(argv)
    assert exit_code == 1
    out = capsys.readouterr().out
    assert "FAILED reason=asset_lookup_failed" in out


def test_build_failure_fails_closed(monkeypatch, tmp_path, capsys) -> None:
    _install_fetch_mocks(monkeypatch, records=[])

    def _raise(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(runner, "build_episodes", _raise)
    argv = list(ARGV) + ["--output-dir", str(tmp_path)]
    exit_code = runner.main(argv)
    assert exit_code == 1
    out = capsys.readouterr().out
    assert "FAILED reason=build_failed" in out


def test_zero_source_episodes_yields_no_calibration_inputs(monkeypatch, tmp_path, capsys) -> None:
    exit_code = _run(monkeypatch, tmp_path, records=[])
    assert exit_code != 0
    out = capsys.readouterr().out
    assert "FAILED reason=calibration_failed" in out


def test_deterministic_run_id_across_repeated_invocations(monkeypatch, tmp_path_factory) -> None:
    dir_a = tmp_path_factory.mktemp("run_a")
    dir_b = tmp_path_factory.mktemp("run_b")

    exit_a = _run(monkeypatch, dir_a, records=[make_record()])
    exit_b = _run(monkeypatch, dir_b, records=[make_record()])
    assert exit_a == 0 and exit_b == 0

    run_id_a = list(dir_a.glob("bitvavo/PROM/4h/*"))[0].name
    run_id_b = list(dir_b.glob("bitvavo/PROM/4h/*"))[0].name
    assert run_id_a == run_id_b
