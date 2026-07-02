from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.market_context.breath_curve_core_v1 import Candle, parse_dt
from src.research.backtest_breath_curve_partial_to_full_v1 import write_csv as v1_write_csv
from src.research.run_breathline_v1_recovery_orchestration_b2a_v1 import (
    ARM_ID,
    REGISTRY,
    ControlMetadataRow,
    build_anchor_cluster_uncertainty,
    build_combos,
    build_per_symbol_summary,
    build_shift_combo,
    build_sidecar_rows,
    cluster_bootstrap_mean_ci,
    combo_availability,
    combo_id,
    compute_sidecar_metrics,
    flatten_combo_rows,
    main,
    validate_registry,
)
from src.research.run_breathline_v1_recovery_orchestration_v1 import (
    DEPENDENCY_CLOSURE_FILES,
    V1_MODULE,
)


OFFSETS = [-10.5, -7.0, -5.0, -3.0, 0.0, 3.0, 5.0, 7.0, 10.5]
FAKE_GIT_COMMIT = "abc123def456"


def make_ok_row(
    *,
    symbol: str = "BTC",
    anchor_ts_utc: str = "2025-01-01T00:00:00Z",
    checkpoint_ratio: float = 0.618,
    as_of_ts_utc: str = "2025-01-14T00:00:00Z",
    selected_offset: float = 0.0,
    target_ts_utc: str = "2025-01-22T00:00:00Z",
) -> dict[str, object]:
    partials = []
    for offset in OFFSETS:
        marker_matched = offset == selected_offset
        future_target_is_future = True
        partials.append(
            {
                "ranking_score": 0.75 if offset == selected_offset else 0.25,
                "future_target_expected_ts_utc": target_ts_utc,
                "future_target_is_future": future_target_is_future,
                "result": {
                    "symbol": symbol,
                    "anchor_ts_utc": anchor_ts_utc,
                    "as_of_ts_utc": as_of_ts_utc,
                    "phase_offset_days": offset,
                    "partial_match_score": 0.75 if offset == selected_offset else 0.25,
                    "required_ratio": checkpoint_ratio,
                    "due_marker_count": 4,
                    "observed_marker_count": 3,
                    "notes": [],
                    "markers": [
                        {"ratio": checkpoint_ratio, "matched": marker_matched},
                    ],
                },
            }
        )
    return {
        "status": "OK",
        "symbol": symbol,
        "anchor_ts_utc": anchor_ts_utc,
        "checkpoint_ratio": checkpoint_ratio,
        "selected_partial_offset_days": selected_offset,
        "all_partial_offsets": partials,
    }


def make_error_row(
    *,
    symbol: str = "BTC",
    anchor_ts_utc: str = "2025-01-01T00:00:00Z",
    checkpoint_ratio: float = 0.786,
    error: str = "Not enough full-cycle candles loaded: 2",
) -> dict[str, object]:
    return {
        "status": "ERROR",
        "symbol": symbol,
        "anchor_ts_utc": anchor_ts_utc,
        "checkpoint_ratio": checkpoint_ratio,
        "error": error,
    }


def make_v1_summary_row(
    *,
    symbol: str = "BTC",
    anchor_ts_utc: str = "2025-01-01T00:00:00Z",
    checkpoint_ratio: float = 0.618,
    as_of_close: float = 100.0,
) -> dict[str, object]:
    return {
        "status": "OK",
        "symbol": symbol,
        "anchor_ts_utc": anchor_ts_utc,
        "checkpoint_ratio": checkpoint_ratio,
        "as_of_ts_utc": "2025-01-14T00:00:00Z",
        "selected_partial_offset_days": 0.0,
        "selected_partial_score": 0.75,
        "as_of_close": as_of_close,
        "return_to_1000_pct": 1.5,
        "venue": "bitvavo",
        "interval_code": "1d",
        "cycle_days": 21.0,
        "tolerance_hours": 36.0,
        "error": "",
    }


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def write_v1_outputs(
    raw_dir: Path,
    jsonl_rows: list[dict[str, object]],
    csv_rows: list[dict[str, object]] | None = None,
) -> tuple[Path, Path]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    csv_path = raw_dir / "breath_curve_partial_to_full_v1_20250101T000000Z.csv"
    jsonl_path = raw_dir / "breath_curve_partial_to_full_v1_20250101T000000Z.jsonl"
    v1_write_csv(csv_path, csv_rows if csv_rows is not None else [make_v1_summary_row()])
    write_jsonl(jsonl_path, jsonl_rows)
    return csv_path, jsonl_path


def make_dependency_head_bytes() -> dict[str, bytes]:
    return {
        relative_path: f"# frozen bytes for {relative_path}\n".encode("utf-8")
        for relative_path in DEPENDENCY_CLOSURE_FILES
    }


def write_dependency_worktree(repo_root: Path, head_bytes: dict[str, bytes]) -> None:
    for relative_path, data in head_bytes.items():
        path = repo_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def make_git_runner(head_bytes: dict[str, bytes], *, v1_handler: callable):
    def fake_run(cmd: list[str], **kwargs: object):
        if cmd == ["git", "rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout=f"{FAKE_GIT_COMMIT}\n".encode("utf-8"), stderr=b""
            )
        if cmd[:2] == ["git", "show"]:
            relative_path = cmd[2].split("HEAD:", 1)[1]
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout=head_bytes[relative_path], stderr=b""
            )
        return v1_handler(cmd, **kwargs)

    return fake_run


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------


def test_registry_equals_exact_twenty_shifts() -> None:
    assert REGISTRY == (
        -10, -9, -8, -7, -6, -5, -4, -3, -2, -1,
        1, 2, 3, 4, 5, 6, 7, 8, 9, 10,
    )


def test_registry_zero_is_rejected() -> None:
    with pytest.raises(ValueError, match="0d shift"):
        validate_registry((0,) + REGISTRY[1:])


def test_registry_rejects_duplicate_phase_class_modulo_21d() -> None:
    # 1 and 22 alias to the same phase class modulo 21d.
    bad_registry = REGISTRY[:-1] + (22,)
    with pytest.raises(ValueError, match="duplicate phase classes modulo 21d"):
        validate_registry(bad_registry)


def test_registry_has_no_duplicate_phase_classes_modulo_21d() -> None:
    phase_classes = [shift % 21 for shift in REGISTRY]
    assert len(set(phase_classes)) == len(phase_classes) == 20


# ---------------------------------------------------------------------------
# Control metadata: canonical vs shifted anchor
# ---------------------------------------------------------------------------


def test_build_shift_combo_records_canonical_and_shifted_anchor_correctly() -> None:
    canonical = parse_dt("2025-01-15T00:00:00Z")

    positive = build_shift_combo("BTC", canonical, 3)
    assert positive["canonical_anchor_ts_utc"] == "2025-01-15T00:00:00Z"
    assert positive["shifted_anchor_ts_utc"] == "2025-01-18T00:00:00Z"
    assert positive["phase_class_mod_21_days"] == 3
    assert positive["anchor_displacement_days"] == 3

    negative = build_shift_combo("BTC", canonical, -10)
    assert negative["canonical_anchor_ts_utc"] == "2025-01-15T00:00:00Z"
    assert negative["shifted_anchor_ts_utc"] == "2025-01-05T00:00:00Z"
    assert negative["phase_class_mod_21_days"] == -10
    assert negative["anchor_displacement_days"] == -10


def test_build_combos_preserves_canonical_anchor_cohort_across_all_shifts() -> None:
    anchors = [parse_dt("2025-01-01T00:00:00Z"), parse_dt("2025-02-01T00:00:00Z")]
    combos = build_combos(["BTC", "ETH"], anchors)

    assert len(combos) == 2 * 2 * 20
    for symbol in ("BTC", "ETH"):
        for anchor in anchors:
            shifts_seen = {
                combo["shift"]
                for combo in combos
                if combo["symbol"] == symbol
                and combo["canonical_anchor_ts_utc"] == anchor.isoformat().replace("+00:00", "Z")
            }
            assert shifts_seen == set(REGISTRY)


# ---------------------------------------------------------------------------
# Availability / DATA_UNAVAILABLE explicitness
# ---------------------------------------------------------------------------


def test_combo_availability_ok_when_all_rows_ok() -> None:
    rows = [make_ok_row(checkpoint_ratio=0.618), make_ok_row(checkpoint_ratio=0.786)]
    status, ok_count, unavailable_count = combo_availability(rows)
    assert status == "OK"
    assert ok_count == 2
    assert unavailable_count == 0


def test_combo_availability_data_unavailable_when_any_row_errors() -> None:
    rows = [make_ok_row(checkpoint_ratio=0.618), make_error_row(checkpoint_ratio=0.786)]
    status, ok_count, unavailable_count = combo_availability(rows)
    assert status == "DATA_UNAVAILABLE"
    assert ok_count == 1
    assert unavailable_count == 1


def test_flatten_combo_rows_excludes_error_rows_without_substitution() -> None:
    combo = build_shift_combo("BTC", parse_dt("2025-01-01T00:00:00Z"), 3)
    rows = [make_ok_row(checkpoint_ratio=0.618), make_error_row(checkpoint_ratio=0.786)]
    flattened = flatten_combo_rows(
        rows,
        run_id="run123",
        combo=combo,
        source_jsonl_path="/tmp/raw.jsonl",
        source_jsonl_sha256="abc123",
    )
    # Only the OK checkpoint contributes rows (9 offsets); the ERROR checkpoint
    # contributes nothing -- no fabricated or substituted values.
    assert len(flattened) == 9
    assert all(row["checkpoint_ratio"] == 0.618 for row in flattened)
    assert all(row["arm_id"] == ARM_ID for row in flattened)
    assert all(row["availability_status"] == "OK" for row in flattened)


# ---------------------------------------------------------------------------
# Sidecar metrics: pure function, deterministic
# ---------------------------------------------------------------------------


def test_compute_sidecar_metrics_no_as_of_close_is_explicit() -> None:
    metrics = compute_sidecar_metrics(
        [], as_of_ts=parse_dt("2025-01-01T00:00:00Z"), target_ts=parse_dt("2025-01-02T00:00:00Z"),
        as_of_close=None,
    )
    assert metrics["sidecar_status"] == "NO_AS_OF_CLOSE"
    assert metrics["mfe_from_high_pct"] is None


def test_compute_sidecar_metrics_no_window_candles_is_explicit() -> None:
    as_of = parse_dt("2025-01-01T00:00:00Z")
    target = parse_dt("2025-01-05T00:00:00Z")
    candles = [Candle(ts=parse_dt("2025-02-01T00:00:00Z"), open=1, high=1, low=1, close=1)]
    metrics = compute_sidecar_metrics(candles, as_of_ts=as_of, target_ts=target, as_of_close=100.0)
    assert metrics["sidecar_status"] == "NO_CANDLE_WINDOW_DATA"


def test_compute_sidecar_metrics_deterministic_values() -> None:
    as_of = parse_dt("2025-01-01T00:00:00Z")
    target = parse_dt("2025-01-04T00:00:00Z")
    candles = [
        Candle(ts=parse_dt("2025-01-01T00:00:00Z"), open=100, high=105, low=95, close=100),
        Candle(ts=parse_dt("2025-01-02T00:00:00Z"), open=100, high=120, low=90, close=110),
        Candle(ts=parse_dt("2025-01-03T00:00:00Z"), open=110, high=115, low=108, close=112),
        Candle(ts=parse_dt("2025-01-04T00:00:00Z"), open=112, high=118, low=111, close=115),
    ]
    metrics = compute_sidecar_metrics(candles, as_of_ts=as_of, target_ts=target, as_of_close=100.0)
    assert metrics["sidecar_status"] == "OK"
    assert metrics["mfe_from_high_pct"] == pytest.approx(20.0)  # (120/100 - 1) * 100
    assert metrics["mae_from_low_pct"] == pytest.approx(-10.0)  # (90/100 - 1) * 100
    assert metrics["close_to_close_1000_pct"] == pytest.approx(15.0)  # (115/100 - 1) * 100
    assert metrics["time_to_window_high_bars"] == 1  # index of the 120-high candle


def test_build_sidecar_rows_no_candle_source_is_explicit_not_fabricated() -> None:
    combo = build_shift_combo("BTC", parse_dt("2025-01-01T00:00:00Z"), 3)
    rows = [make_ok_row(checkpoint_ratio=0.618)]
    raw_dir = Path("/tmp")  # unused path placeholder, replaced below in real test
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        raw_csv_path = Path(tmp) / "raw.csv"
        v1_write_csv(raw_csv_path, [make_v1_summary_row(checkpoint_ratio=0.618)])
        sidecar = build_sidecar_rows(
            rows, run_id="run123", combo=combo, raw_csv_path=raw_csv_path, candles=None
        )
    assert len(sidecar) == 1
    assert sidecar[0]["sidecar_status"] == "NO_CANDLE_SOURCE_CONFIGURED"
    assert sidecar[0]["mfe_from_high_pct"] is None
    assert sidecar[0]["as_of_close"] == 100.0


# ---------------------------------------------------------------------------
# Cluster bootstrap determinism
# ---------------------------------------------------------------------------


def test_cluster_bootstrap_mean_ci_is_deterministic_for_fixed_seed() -> None:
    clusters = {"a": [1.0, 2.0], "b": [3.0], "c": [-1.0, 0.0, 1.0]}
    first = cluster_bootstrap_mean_ci(clusters, num_resamples=500, seed=1337)
    second = cluster_bootstrap_mean_ci(clusters, num_resamples=500, seed=1337)
    assert first == second


def test_cluster_bootstrap_mean_ci_empty_is_zero() -> None:
    assert cluster_bootstrap_mean_ci({}, num_resamples=100, seed=1) == (0.0, 0.0, 0.0)


def test_build_anchor_cluster_uncertainty_notes_not_independent_samples() -> None:
    flattened_rows = [
        {
            "symbol": "BTC",
            "shifted_anchor_ts_utc": "2025-01-04T00:00:00Z",
            "checkpoint_ratio": 0.618,
            "selected_by_v1": True,
        }
    ]
    sidecar_rows = [
        {
            "symbol": "BTC",
            "shifted_anchor_ts_utc": "2025-01-04T00:00:00Z",
            "canonical_anchor_ts_utc": "2025-01-01T00:00:00Z",
            "checkpoint_ratio": 0.618,
            "close_to_close_1000_pct": 5.0,
        }
    ]
    rows = build_anchor_cluster_uncertainty(
        run_id="run123",
        symbols=["BTC"],
        flattened_rows=flattened_rows,
        sidecar_rows=sidecar_rows,
        num_resamples=200,
        seed=1337,
    )
    assert len(rows) == 1
    assert rows[0]["cluster_count"] == 1
    assert rows[0]["observation_count"] == 1
    assert "not independent samples" in rows[0]["note"]


def test_build_per_symbol_summary_counts_unavailable_combos() -> None:
    control_rows = [
        ControlMetadataRow(
            run_id="run123",
            arm_id=ARM_ID,
            control_taxonomy="INTEGER_DAY_PHASE_NULL_CONTROL",
            symbol="BTC",
            canonical_anchor_ts_utc="2025-01-01T00:00:00Z",
            shifted_anchor_ts_utc="2025-01-04T00:00:00Z",
            phase_class_mod_21_days=3,
            anchor_displacement_days=3,
            availability_status="OK",
            source_commit=FAKE_GIT_COMMIT,
            raw_csv_path="raw.csv",
            raw_jsonl_path="raw.jsonl",
            raw_jsonl_sha256="abc",
            ok_row_count=2,
            data_unavailable_row_count=0,
        ),
        ControlMetadataRow(
            run_id="run123",
            arm_id=ARM_ID,
            control_taxonomy="INTEGER_DAY_PHASE_NULL_CONTROL",
            symbol="BTC",
            canonical_anchor_ts_utc="2025-01-01T00:00:00Z",
            shifted_anchor_ts_utc="2025-01-06T00:00:00Z",
            phase_class_mod_21_days=5,
            anchor_displacement_days=5,
            availability_status="DATA_UNAVAILABLE",
            source_commit=FAKE_GIT_COMMIT,
            raw_csv_path="raw.csv",
            raw_jsonl_path="raw.jsonl",
            raw_jsonl_sha256="abc",
            ok_row_count=0,
            data_unavailable_row_count=2,
        ),
    ]
    summary = build_per_symbol_summary(
        run_id="run123",
        symbols=["BTC"],
        control_rows=control_rows,
        flattened_rows=[],
        sidecar_rows=[],
    )
    assert summary[0]["combo_count"] == 2
    assert summary[0]["ok_combo_count"] == 1
    assert summary[0]["data_unavailable_combo_count"] == 1


# ---------------------------------------------------------------------------
# Smoke: frozen V1 artifacts remain separate/unmodified; full main() flow
# ---------------------------------------------------------------------------


def test_main_smoke_single_anchor_single_symbol_preserves_raw_v1_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = tmp_path / "repo"
    out_dir = tmp_path / "research"
    head_bytes = make_dependency_head_bytes()
    write_dependency_worktree(repo_root, head_bytes)

    calls: list[list[str]] = []

    def v1_handler(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert cmd[:3] == [sys.executable, "-m", V1_MODULE]
        calls.append(cmd)
        anchor_arg = cmd[cmd.index("--anchors") + 1]
        raw_dir = Path(cmd[cmd.index("--out-dir") + 1])
        raw_dir.mkdir(parents=True, exist_ok=True)
        write_v1_outputs(
            raw_dir,
            [
                make_ok_row(anchor_ts_utc=anchor_arg, checkpoint_ratio=0.618),
                make_ok_row(anchor_ts_utc=anchor_arg, checkpoint_ratio=0.786),
            ],
            [
                make_v1_summary_row(anchor_ts_utc=anchor_arg, checkpoint_ratio=0.618),
                make_v1_summary_row(anchor_ts_utc=anchor_arg, checkpoint_ratio=0.786),
            ],
        )
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    monkeypatch.setattr("subprocess.run", make_git_runner(head_bytes, v1_handler=v1_handler))
    monkeypatch.setattr(
        "src.research.run_breathline_v1_recovery_orchestration_b2a_v1.find_repo_root",
        lambda: repo_root,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "runner",
            "--symbols",
            "BTC",
            "--canonical-anchors",
            "2025-01-01T00:00:00Z",
            "--out-dir",
            str(out_dir),
            "--skip-sidecar-candles",
        ],
    )

    assert main() == 0
    # Exactly 20 frozen V1 invocations: one per registered shift.
    assert len(calls) == 20

    run_dirs = list(out_dir.iterdir())
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    top_level = sorted(path.name for path in run_dir.iterdir())
    assert top_level == ["control_metadata", "derived", "logs", "manifest", "raw"]

    raw_combo_dirs = sorted((run_dir / "raw").iterdir())
    assert len(raw_combo_dirs) == 20
    for combo_dir in raw_combo_dirs:
        csv_paths = list(combo_dir.glob("*.csv"))
        jsonl_paths = list(combo_dir.glob("*.jsonl"))
        assert len(csv_paths) == 1
        assert len(jsonl_paths) == 1

    # Derived/control/manifest artifacts are separate from the raw V1 output tree.
    derived_files = sorted(path.name for path in (run_dir / "derived").iterdir())
    assert len(derived_files) == 4
    control_files = list((run_dir / "control_metadata").glob("*.csv"))
    assert len(control_files) == 1
    manifest_files = list((run_dir / "manifest").glob("*.json"))
    assert len(manifest_files) == 1

    with control_files[0].open(newline="", encoding="utf-8") as handle:
        control_rows = list(csv.DictReader(handle))
    assert len(control_rows) == 20
    assert {row["availability_status"] for row in control_rows} == {"OK"}
    assert {int(row["phase_class_mod_21_days"]) for row in control_rows} == set(REGISTRY)
    assert all(row["arm_id"] == ARM_ID for row in control_rows)
    assert all(row["canonical_anchor_ts_utc"] == "2025-01-01T00:00:00Z" for row in control_rows)

    manifest = json.loads(manifest_files[0].read_text(encoding="utf-8"))
    assert manifest["registry"] == list(REGISTRY)
    assert manifest["ok_combo_count"] == 20
    assert manifest["data_unavailable_combo_count"] == 0
    assert manifest["dependency_closure_integrity_status"] == "PASS"
    assert "not independent samples" in manifest["not_independent_samples_note"]


def test_main_smoke_data_unavailable_combo_excluded_from_population_not_substituted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = tmp_path / "repo"
    out_dir = tmp_path / "research"
    head_bytes = make_dependency_head_bytes()
    write_dependency_worktree(repo_root, head_bytes)

    def v1_handler(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        anchor_arg = cmd[cmd.index("--anchors") + 1]
        raw_dir = Path(cmd[cmd.index("--out-dir") + 1])
        raw_dir.mkdir(parents=True, exist_ok=True)
        # 2025-01-01 shifted by -10d is 2024-12-22: force that single combo unavailable.
        if anchor_arg.startswith("2024-12-22"):
            write_v1_outputs(
                raw_dir,
                [
                    make_error_row(anchor_ts_utc=anchor_arg, checkpoint_ratio=0.618),
                    make_error_row(anchor_ts_utc=anchor_arg, checkpoint_ratio=0.786),
                ],
                [],
            )
        else:
            write_v1_outputs(
                raw_dir,
                [
                    make_ok_row(anchor_ts_utc=anchor_arg, checkpoint_ratio=0.618),
                    make_ok_row(anchor_ts_utc=anchor_arg, checkpoint_ratio=0.786),
                ],
                [
                    make_v1_summary_row(anchor_ts_utc=anchor_arg, checkpoint_ratio=0.618),
                    make_v1_summary_row(anchor_ts_utc=anchor_arg, checkpoint_ratio=0.786),
                ],
            )
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    monkeypatch.setattr("subprocess.run", make_git_runner(head_bytes, v1_handler=v1_handler))
    monkeypatch.setattr(
        "src.research.run_breathline_v1_recovery_orchestration_b2a_v1.find_repo_root",
        lambda: repo_root,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "runner",
            "--symbols",
            "BTC",
            "--canonical-anchors",
            "2025-01-01T00:00:00Z",
            "--out-dir",
            str(out_dir),
            "--skip-sidecar-candles",
        ],
    )

    assert main() == 0

    run_dir = next(out_dir.iterdir())
    control_csv = next((run_dir / "control_metadata").glob("*.csv"))
    with control_csv.open(newline="", encoding="utf-8") as handle:
        control_rows = list(csv.DictReader(handle))

    unavailable_rows = [row for row in control_rows if row["availability_status"] == "DATA_UNAVAILABLE"]
    assert len(unavailable_rows) == 1
    assert unavailable_rows[0]["phase_class_mod_21_days"] == "-10"

    flattened_csv = next((run_dir / "derived").glob("*flattened*.csv"))
    with flattened_csv.open(newline="", encoding="utf-8") as handle:
        flattened_rows = list(csv.DictReader(handle))
    # The DATA_UNAVAILABLE combo contributes zero flattened rows -- excluded,
    # not substituted or fabricated.
    assert all(row["phase_class_mod_21_days"] != "-10" for row in flattened_rows)

    manifest_json = json.loads(
        next((run_dir / "manifest").glob("*.json")).read_text(encoding="utf-8")
    )
    assert manifest_json["ok_combo_count"] == 19
    assert manifest_json["data_unavailable_combo_count"] == 1


def test_main_fails_before_v1_subprocess_when_frozen_dependency_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo_root = tmp_path / "repo"
    out_dir = tmp_path / "research"
    head_bytes = make_dependency_head_bytes()
    write_dependency_worktree(repo_root, head_bytes)
    (repo_root / DEPENDENCY_CLOSURE_FILES[0]).unlink()

    def v1_handler(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise AssertionError(f"v1 subprocess should not run: {cmd}")

    monkeypatch.setattr("subprocess.run", make_git_runner(head_bytes, v1_handler=v1_handler))
    monkeypatch.setattr(
        "src.research.run_breathline_v1_recovery_orchestration_b2a_v1.find_repo_root",
        lambda: repo_root,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "runner",
            "--symbols",
            "BTC",
            "--canonical-anchors",
            "2025-01-01T00:00:00Z",
            "--out-dir",
            str(out_dir),
        ],
    )

    assert main() == 1
    assert not out_dir.exists()
    captured = capsys.readouterr()
    assert "frozen dependency missing" in captured.out
