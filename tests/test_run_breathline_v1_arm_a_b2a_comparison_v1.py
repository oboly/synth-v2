from __future__ import annotations

import csv
import hashlib
import io
import json
import sys
import tarfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.research.run_breathline_v1_recovery_orchestration_v1 import (
    FLATTENED_FIELDNAMES as ARM_A_FLATTENED_FIELDNAMES,
)
from src.research.run_breathline_v1_recovery_orchestration_b2a_v1 import (
    CONTROL_METADATA_FIELDNAMES as B2A_CONTROL_METADATA_FIELDNAMES,
    FLATTENED_FIELDNAMES_B2A,
    REGISTRY as B2A_REGISTRY,
)
from src.research.run_breathline_v1_arm_a_b2a_comparison_v1 import (
    ArmAEvidence,
    ArmAJoinRow,
    B2aEvidence,
    B2aJoinRow,
    CONTRAST_METRICS,
    ComparisonValidationError,
    EXPECTED_ANCHOR_COUNT,
    EXPECTED_SYMBOLS,
    build_anchor_cluster_uncertainty,
    build_contrast_rows,
    build_matched_cell_rows,
    build_pooled_descriptive_summary,
    discover_arm_a_manifests,
    load_arm_a_evidence,
    load_b2a_evidence,
    main,
    tie_aware_mid_rank_percentile,
    validate_b2a_join_groups,
    validate_shift_mapping,
    verify_and_extract_archive,
)


CHECKPOINTS = (0.618, 0.786)
OFFSETS = (-10.5, -7.0, -5.0, -3.0, 0.0, 3.0, 5.0, 7.0, 10.5)
SOURCE_COMMIT = "a" * 40


def anchor_dates_ts_utc(n: int) -> list[str]:
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    return [(base + timedelta(days=21 * i)).strftime("%Y-%m-%dT%H:%M:%SZ") for i in range(n)]


def rows_to_csv_bytes(fieldnames: tuple[str, ...], rows: list[dict]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(fieldnames))
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def build_arm_a_flattened_row(symbol, anchor_ts_utc, checkpoint_ratio, phase_offset_days, run_id) -> dict:
    return {
        "run_id": run_id,
        "arm_id": "ARM_A",
        "source_jsonl_path": "raw/x.jsonl",
        "source_jsonl_row_number": 1,
        "source_jsonl_sha256": "0" * 64,
        "source_code_recovery_status": "PASS",
        "source_data_recovery_status": "UNAVAILABLE",
        "result_recovery_status": "UNAVAILABLE",
        "availability_status": "OK",
        "symbol": symbol,
        "anchor_ts_utc": anchor_ts_utc,
        "checkpoint_ratio": checkpoint_ratio,
        "selected_partial_offset_days": OFFSETS[0],
        "as_of_ts_utc": anchor_ts_utc,
        "phase_offset_days": phase_offset_days,
        "future_target_is_future": True,
        "partial_match_score": 0.5,
        "ranking_score": 0.5,
        "required_ratio": checkpoint_ratio,
        "required_marker_due": True,
        "required_marker_matched": True,
        "due_marker_count": 5,
        "observed_marker_count": 5,
        "min_due_markers_met": True,
        "structurally_eligible": True,
        "score_zero_reason": "[]",
        "notes_json": "[]",
        "selected_by_v1": phase_offset_days == OFFSETS[0],
    }


def build_arm_a_manifest(symbol: str, anchor_date: str, run_id: str) -> dict:
    return {
        "run_id": run_id,
        "source_commit": SOURCE_COMMIT,
        "symbol": symbol,
        "anchor": anchor_date,
        "availability_summary": {"availability_status": "OK"},
        "dependency_closure_integrity_status": "PASS",
    }


def build_arm_a_content(
    symbols: list[str], anchors_ts_utc: list[str], *, run_id_prefix: str = "arm_a_test"
) -> dict[str, bytes]:
    content: dict[str, bytes] = {}
    for symbol in symbols:
        for anchor_ts_utc in anchors_ts_utc:
            anchor_date = anchor_ts_utc[:10]
            run_id = f"{run_id_prefix}_{symbol.lower()}_{anchor_date}"
            rows = [
                build_arm_a_flattened_row(symbol, anchor_ts_utc, checkpoint, offset, run_id)
                for checkpoint in CHECKPOINTS
                for offset in OFFSETS
            ]
            combo_dir = f"raw-runset/{anchor_date}/{symbol}/{run_id}"
            content[f"{combo_dir}/derived/breathline_v1_recovery_arm_a_flattened_{run_id}.csv"] = (
                rows_to_csv_bytes(ARM_A_FLATTENED_FIELDNAMES, rows)
            )
            manifest = build_arm_a_manifest(symbol, anchor_date, run_id)
            # Real Arm-A runner template (run_breathline_v1_recovery_orchestration_v1.py):
            # breathline_v1_recovery_manifest_{run_id}.json -- no fixed "arm_a" segment;
            # only run_id's own content happens to start with "arm_a_" in production.
            content[f"{combo_dir}/manifest/breathline_v1_recovery_manifest_{run_id}.json"] = (
                json.dumps(manifest).encode("utf-8")
            )
    return content


def build_b2a_content(symbols: list[str], anchors_ts_utc: list[str], run_id: str = "b2a_test_run") -> dict[str, bytes]:
    control_rows = []
    flattened_rows = []
    for symbol in symbols:
        for anchor_ts_utc in anchors_ts_utc:
            canonical_dt = datetime.fromisoformat(anchor_ts_utc.replace("Z", "+00:00"))
            for shift in B2A_REGISTRY:
                shifted_ts_utc = (canonical_dt + timedelta(days=shift)).strftime("%Y-%m-%dT%H:%M:%SZ")
                control_rows.append(
                    {
                        "run_id": run_id,
                        "arm_id": "ARM_B2A",
                        "control_taxonomy": "INTEGER_DAY_PHASE_NULL_CONTROL",
                        "symbol": symbol,
                        "canonical_anchor_ts_utc": anchor_ts_utc,
                        "shifted_anchor_ts_utc": shifted_ts_utc,
                        "phase_class_mod_21_days": shift,
                        "anchor_displacement_days": shift,
                        "availability_status": "OK",
                        "source_commit": SOURCE_COMMIT,
                        "raw_csv_path": "raw/x.csv",
                        "raw_jsonl_path": "raw/x.jsonl",
                        "raw_jsonl_sha256": "0" * 64,
                        "ok_row_count": 2,
                        "data_unavailable_row_count": 0,
                    }
                )
                for checkpoint in CHECKPOINTS:
                    for offset in OFFSETS:
                        flattened_rows.append(
                            {
                                "run_id": run_id,
                                "arm_id": "ARM_B2A",
                                "control_taxonomy": "INTEGER_DAY_PHASE_NULL_CONTROL",
                                "symbol": symbol,
                                "canonical_anchor_ts_utc": anchor_ts_utc,
                                "shifted_anchor_ts_utc": shifted_ts_utc,
                                "phase_class_mod_21_days": shift,
                                "anchor_displacement_days": shift,
                                "availability_status": "OK",
                                "source_jsonl_path": "raw/x.jsonl",
                                "source_jsonl_row_number": 1,
                                "source_jsonl_sha256": "0" * 64,
                                "checkpoint_ratio": checkpoint,
                                "selected_partial_offset_days": OFFSETS[0],
                                "as_of_ts_utc": shifted_ts_utc,
                                "phase_offset_days": offset,
                                "future_target_is_future": True,
                                "partial_match_score": 0.5,
                                "ranking_score": 0.5,
                                "required_ratio": checkpoint,
                                "required_marker_due": True,
                                "required_marker_matched": True,
                                "due_marker_count": 5,
                                "observed_marker_count": 5,
                                "min_due_markers_met": True,
                                "structurally_eligible": True,
                                "score_zero_reason": "[]",
                                "notes_json": "[]",
                                "selected_by_v1": offset == OFFSETS[0],
                            }
                        )
    manifest = {
        "run_id": run_id,
        "source_commit": SOURCE_COMMIT,
        "registry": list(B2A_REGISTRY),
        "combo_count": len(symbols) * len(anchors_ts_utc) * len(B2A_REGISTRY),
        "ok_combo_count": len(symbols) * len(anchors_ts_utc) * len(B2A_REGISTRY),
        "data_unavailable_combo_count": 0,
        "dependency_closure_integrity_status": "PASS",
    }
    return {
        f"runset/control_metadata/breathline_v1_recovery_b2a_control_metadata_{run_id}.csv": (
            rows_to_csv_bytes(B2A_CONTROL_METADATA_FIELDNAMES, control_rows)
        ),
        f"runset/derived/breathline_v1_recovery_b2a_flattened_{run_id}.csv": (
            rows_to_csv_bytes(FLATTENED_FIELDNAMES_B2A, flattened_rows)
        ),
        f"runset/manifest/breathline_v1_recovery_b2a_manifest_{run_id}.json": (
            json.dumps(manifest).encode("utf-8")
        ),
    }


def build_archive(
    parent_dir: Path,
    archive_name: str,
    content_files: dict[str, bytes],
    *,
    corrupt_sha256sums_path: str | None = None,
) -> Path:
    archive_root = parent_dir / archive_name
    archive_root.mkdir(parents=True, exist_ok=True)
    build_dir = parent_dir / f"_{archive_name}_build"
    build_dir.mkdir(parents=True, exist_ok=True)

    sha_lines = []
    for rel_path, content in sorted(content_files.items()):
        target = build_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        if rel_path == corrupt_sha256sums_path:
            digest = "0" * 64
        sha_lines.append(f"{digest}  {rel_path}")

    sha256sums_path = build_dir / "SHA256SUMS"
    sha256sums_path.write_text("\n".join(sha_lines) + "\n", encoding="utf-8")

    tar_path = archive_root / f"{archive_name}.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(sha256sums_path, arcname="SHA256SUMS")
        for rel_path in sorted(content_files):
            tar.add(build_dir / rel_path, arcname=rel_path)

    tar_hash = hashlib.sha256(tar_path.read_bytes()).hexdigest()
    (archive_root / f"{archive_name}.tar.gz.sha256").write_text(
        f"{tar_hash}  {archive_name}.tar.gz\n", encoding="utf-8"
    )
    return archive_root


def make_arm_a_row(**overrides) -> ArmAJoinRow:
    defaults = dict(
        symbol="BTC",
        anchor_ts_utc="2025-01-01T00:00:00Z",
        checkpoint_ratio=0.618,
        phase_offset_days=0.0,
        ranking_score=0.7,
        partial_match_score=0.6,
        structurally_eligible=True,
        selected_by_v1=True,
    )
    defaults.update(overrides)
    return ArmAJoinRow(**defaults)


def make_b2a_row(phase_class: int, **overrides) -> B2aJoinRow:
    defaults = dict(
        ranking_score=0.5,
        partial_match_score=0.4,
        structurally_eligible=False,
        selected_by_v1=False,
        phase_class_mod_21_days=phase_class,
        anchor_displacement_days=phase_class,
    )
    defaults.update(overrides)
    return B2aJoinRow(**defaults)


# ---------------------------------------------------------------------------
# Full-cohort fixture (module-scoped: built once, reused by happy-path tests)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def full_cohort_roots(tmp_path_factory) -> tuple[Path, Path]:
    base = tmp_path_factory.mktemp("archives")
    symbols = sorted(EXPECTED_SYMBOLS)
    anchors = anchor_dates_ts_utc(EXPECTED_ANCHOR_COUNT)
    arm_a_content = build_arm_a_content(symbols, anchors)
    b2a_content = build_b2a_content(symbols, anchors)
    arm_a_root = build_archive(base, "arm_a_full", arm_a_content)
    b2a_root = build_archive(base, "b2a_full", b2a_content)
    return arm_a_root, b2a_root


# ---------------------------------------------------------------------------
# Archive verification: hash failure / SHA256SUMS failure
# ---------------------------------------------------------------------------


def test_archive_hash_failure_rejected(tmp_path: Path) -> None:
    content = build_arm_a_content(["BTC"], anchor_dates_ts_utc(1))
    archive_root = build_archive(tmp_path, "tiny_arm_a", content)
    (archive_root / "tiny_arm_a.tar.gz.sha256").write_text(
        f"{'0' * 64}  tiny_arm_a.tar.gz\n", encoding="utf-8"
    )
    with pytest.raises(ComparisonValidationError, match="checksum mismatch"):
        verify_and_extract_archive(archive_root, tmp_path / "work", "arm_a")


def test_internal_sha256sums_failure_rejected(tmp_path: Path) -> None:
    content = build_arm_a_content(["BTC"], anchor_dates_ts_utc(1))
    corrupt_path = next(iter(content))
    archive_root = build_archive(
        tmp_path, "tiny_arm_a_corrupt", content, corrupt_sha256sums_path=corrupt_path
    )
    with pytest.raises(ComparisonValidationError, match="SHA256SUMS mismatch"):
        verify_and_extract_archive(archive_root, tmp_path / "work", "arm_a")


# ---------------------------------------------------------------------------
# Cohort mismatch
# ---------------------------------------------------------------------------


def test_cohort_mismatch_rejected(tmp_path: Path) -> None:
    content = build_arm_a_content(["BTC"], anchor_dates_ts_utc(1))
    archive_root = build_archive(tmp_path, "tiny_arm_a_cohort", content)
    verified = verify_and_extract_archive(archive_root, tmp_path / "work", "arm_a")
    with pytest.raises(ComparisonValidationError, match="cohort mismatch"):
        load_arm_a_evidence(verified.extraction_root)


# ---------------------------------------------------------------------------
# Arm-A manifest discovery: real runner naming, not an invented "_arm_a_" pattern
# ---------------------------------------------------------------------------


def test_arm_a_manifest_discovery_matches_real_runner_naming(tmp_path: Path) -> None:
    # The real Arm-A runner (run_breathline_v1_recovery_orchestration_v1.py) writes
    # breathline_v1_recovery_manifest_{run_id}.json -- there is no fixed "_arm_a_"
    # segment in the filename template itself. Use a run_id prefix that does NOT
    # contain "arm_a" at all to prove discovery no longer depends on that invented
    # assumption.
    content = build_arm_a_content(["BTC"], anchor_dates_ts_utc(1), run_id_prefix="customrun")
    manifest_rel_paths = [path for path in content if "/manifest/" in path]
    assert len(manifest_rel_paths) == 1
    manifest_filename = Path(manifest_rel_paths[0]).name

    # The fixture must match the real runner's naming convention exactly.
    assert manifest_filename.startswith("breathline_v1_recovery_manifest_")
    assert not manifest_filename.startswith("breathline_v1_recovery_manifest_arm_a_")
    # The old invented pattern required a literal "_arm_a_" segment; this run_id has none.
    assert "_arm_a_" not in manifest_filename

    archive_root = build_archive(tmp_path, "arm_a_custom_run_id", content)
    verified = verify_and_extract_archive(archive_root, tmp_path / "work", "arm_a")

    discovered = discover_arm_a_manifests(verified.extraction_root)
    assert len(discovered) == 1
    assert discovered[0].name == manifest_filename


# ---------------------------------------------------------------------------
# Missing / duplicate shift
# ---------------------------------------------------------------------------


def test_missing_shift_rejected() -> None:
    shifts = [s for s in B2A_REGISTRY if s != -10]
    group = [make_b2a_row(s) for s in shifts]
    join_key = ("BTC", "2025-01-01T00:00:00Z", 0.618, 0.0)
    with pytest.raises(ComparisonValidationError, match="missing/duplicate shift"):
        validate_b2a_join_groups({join_key: group})


def test_duplicate_shift_rejected() -> None:
    group = [make_b2a_row(s) for s in B2A_REGISTRY] + [make_b2a_row(1)]
    join_key = ("BTC", "2025-01-01T00:00:00Z", 0.618, 0.0)
    with pytest.raises(ComparisonValidationError, match="missing/duplicate shift"):
        validate_b2a_join_groups({join_key: group})


def test_exact_registry_shift_group_accepted() -> None:
    group = [make_b2a_row(s) for s in B2A_REGISTRY]
    join_key = ("BTC", "2025-01-01T00:00:00Z", 0.618, 0.0)
    validate_b2a_join_groups({join_key: group})  # must not raise


# ---------------------------------------------------------------------------
# Incorrect canonical/shifted-anchor mapping
# ---------------------------------------------------------------------------


def test_incorrect_anchor_mapping_rejected() -> None:
    with pytest.raises(ComparisonValidationError, match="incorrect anchor mapping"):
        validate_shift_mapping(
            canonical_anchor_ts_utc="2025-01-01T00:00:00Z",
            shifted_anchor_ts_utc="2025-01-01T00:00:00Z",
            anchor_displacement_days=3,
            context="test",
        )


def test_correct_anchor_mapping_accepted() -> None:
    validate_shift_mapping(
        canonical_anchor_ts_utc="2025-01-01T00:00:00Z",
        shifted_anchor_ts_utc="2025-01-04T00:00:00Z",
        anchor_displacement_days=3,
        context="test",
    )
    validate_shift_mapping(
        canonical_anchor_ts_utc="2025-01-15T00:00:00Z",
        shifted_anchor_ts_utc="2025-01-05T00:00:00Z",
        anchor_displacement_days=-10,
        context="test",
    )


# ---------------------------------------------------------------------------
# Exact 20-control match (matched-cell construction)
# ---------------------------------------------------------------------------


def test_build_matched_cell_rows_has_one_canonical_and_20_controls() -> None:
    join_key = ("BTC", "2025-01-01T00:00:00Z", 0.618, 0.0)
    arm_a_evidence = ArmAEvidence(
        rows_by_join_key={join_key: make_arm_a_row()},
        combo_run_ids=["run1"],
        combo_source_commits={"abc"},
        flattened_csv_paths=[],
        manifest_paths=[],
    )
    b2a_evidence = B2aEvidence(
        rows_by_join_key={join_key: [make_b2a_row(s) for s in B2A_REGISTRY]},
        run_id="b2a_run",
        source_commit="abc",
        flattened_csv_path=Path("x"),
        control_metadata_csv_path=Path("y"),
        manifest_path=Path("z"),
    )
    rows = build_matched_cell_rows(arm_a_evidence, b2a_evidence)
    assert len(rows) == 21
    canonical = [row for row in rows if row["row_kind"] == "CANONICAL"]
    controls = [row for row in rows if row["row_kind"] == "CONTROL"]
    assert len(canonical) == 1
    assert len(controls) == 20
    assert {control["phase_class_mod_21_days"] for control in controls} == set(B2A_REGISTRY)
    assert canonical[0]["phase_class_mod_21_days"] == 0
    assert canonical[0]["anchor_displacement_days"] == 0
    assert canonical[0]["source_arm_id"] == "ARM_A"
    assert all(control["source_arm_id"] == "ARM_B2A" for control in controls)


# ---------------------------------------------------------------------------
# Contrast statistics
# ---------------------------------------------------------------------------


def test_build_contrast_rows_computes_expected_stats() -> None:
    join_key = ("BTC", "2025-01-01T00:00:00Z", 0.618, 0.0)
    arm_a_evidence = ArmAEvidence(
        rows_by_join_key={
            join_key: make_arm_a_row(ranking_score=0.8, partial_match_score=0.7, structurally_eligible=True)
        },
        combo_run_ids=[],
        combo_source_commits=set(),
        flattened_csv_paths=[],
        manifest_paths=[],
    )
    control_scores = [round(0.05 * (i + 1), 4) for i in range(20)]
    controls = [
        make_b2a_row(shift, ranking_score=score)
        for shift, score in zip(B2A_REGISTRY, control_scores)
    ]
    b2a_evidence = B2aEvidence(
        rows_by_join_key={join_key: controls},
        run_id="r",
        source_commit="c",
        flattened_csv_path=Path("x"),
        control_metadata_csv_path=Path("y"),
        manifest_path=Path("z"),
    )
    contrast_rows = build_contrast_rows(arm_a_evidence, b2a_evidence)
    assert len(contrast_rows) == len(CONTRAST_METRICS)
    ranking_row = next(row for row in contrast_rows if row["metric"] == "ranking_score")
    expected_mean = sum(control_scores) / 20
    assert ranking_row["canonical_value"] == 0.8
    assert ranking_row["control_n"] == 20
    assert ranking_row["control_mean"] == pytest.approx(expected_mean, abs=1e-6)
    assert ranking_row["canonical_minus_control_mean"] == pytest.approx(0.8 - expected_mean, abs=1e-6)


# ---------------------------------------------------------------------------
# Tie-aware mid-rank percentile
# ---------------------------------------------------------------------------


def test_tie_aware_mid_rank_percentile_no_ties() -> None:
    population = [1.0, 2.0, 3.0, 4.0]
    assert tie_aware_mid_rank_percentile(2.5, population) == 50.0


def test_tie_aware_mid_rank_percentile_with_ties() -> None:
    population = [1.0, 2.0, 2.0, 3.0]
    # value 2.0: 1 strictly below, 2 equal -> (1 + 0.5*2) / 4 * 100 = 50.0
    assert tie_aware_mid_rank_percentile(2.0, population) == 50.0


def test_tie_aware_mid_rank_percentile_all_equal() -> None:
    population = [5.0] * 20
    assert tie_aware_mid_rank_percentile(5.0, population) == 50.0


def test_tie_aware_mid_rank_percentile_extremes() -> None:
    population = [1.0, 2.0, 3.0, 4.0]
    assert tie_aware_mid_rank_percentile(0.0, population) == 0.0
    assert tie_aware_mid_rank_percentile(5.0, population) == 100.0


# ---------------------------------------------------------------------------
# Deterministic canonical-anchor cluster bootstrap
# ---------------------------------------------------------------------------


def _sample_contrast_rows() -> list[dict]:
    return [
        {
            "symbol": "BTC",
            "metric": "ranking_score",
            "anchor_ts_utc": "2025-01-01T00:00:00Z",
            "canonical_minus_control_mean": 0.10,
        },
        {
            "symbol": "BTC",
            "metric": "ranking_score",
            "anchor_ts_utc": "2025-01-01T00:00:00Z",
            "canonical_minus_control_mean": 0.20,
        },
        {
            "symbol": "BTC",
            "metric": "ranking_score",
            "anchor_ts_utc": "2025-02-01T00:00:00Z",
            "canonical_minus_control_mean": -0.10,
        },
    ]


def test_build_anchor_cluster_uncertainty_deterministic_for_fixed_seed() -> None:
    contrast_rows = _sample_contrast_rows()
    first = build_anchor_cluster_uncertainty(contrast_rows, num_resamples=200, seed=1337)
    second = build_anchor_cluster_uncertainty(contrast_rows, num_resamples=200, seed=1337)
    assert first == second
    ranking_row = next(row for row in first if row["symbol"] == "BTC" and row["metric"] == "ranking_score")
    assert ranking_row["cluster_count"] == 2
    assert ranking_row["observation_count"] == 3
    assert "not independent samples" in ranking_row["note"]


def test_build_anchor_cluster_uncertainty_varies_with_seed() -> None:
    contrast_rows = _sample_contrast_rows()
    first = build_anchor_cluster_uncertainty(contrast_rows, num_resamples=200, seed=1)
    second = build_anchor_cluster_uncertainty(contrast_rows, num_resamples=200, seed=2)
    # Bootstrap draws differ across seeds (extremely unlikely to coincide by chance).
    assert first != second


# ---------------------------------------------------------------------------
# Pooled descriptive-only labeling
# ---------------------------------------------------------------------------


def test_build_pooled_descriptive_summary_labels_non_independent() -> None:
    contrast_rows = []
    for metric in CONTRAST_METRICS:
        contrast_rows.append(
            {"metric": metric, "canonical_value": 0.5, "control_mean": 0.4, "canonical_minus_control_mean": 0.1}
        )
        contrast_rows.append(
            {"metric": metric, "canonical_value": 0.6, "control_mean": 0.5, "canonical_minus_control_mean": 0.1}
        )
    pooled = build_pooled_descriptive_summary(contrast_rows)
    assert len(pooled) == len(CONTRAST_METRICS)
    for row in pooled:
        assert "descriptive" in row["note"].lower()
        assert "cross-asset" in row["note"].lower()
        assert "correlated" in row["note"].lower()
        assert row["pooled_canonical_minus_control_mean"] == pytest.approx(0.1)


# ---------------------------------------------------------------------------
# Full happy-path integration: exact preregistered cohort, exact 20-control match
# ---------------------------------------------------------------------------


def test_main_happy_path_full_cohort(full_cohort_roots: tuple[Path, Path], tmp_path: Path) -> None:
    arm_a_root, b2a_root = full_cohort_roots
    out_dir = tmp_path / "out"

    argv = [
        "runner",
        "--arm-a-archive-root",
        str(arm_a_root),
        "--b2a-archive-root",
        str(b2a_root),
        "--out-dir",
        str(out_dir),
        "--bootstrap-resamples",
        "50",
        "--bootstrap-seed",
        "1337",
    ]
    old_argv = sys.argv
    sys.argv = argv
    try:
        exit_code = main()
    finally:
        sys.argv = old_argv

    assert exit_code == 0

    run_dirs = list(out_dir.iterdir())
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    assert sorted(path.name for path in run_dir.iterdir()) == ["derived", "manifest"]

    matched_cell_csv = next((run_dir / "derived").glob("*matched_cell*.csv"))
    contrast_csv = next((run_dir / "derived").glob("*contrast*.csv"))
    per_symbol_csv = next((run_dir / "derived").glob("*per_symbol_summary*.csv"))
    anchor_cluster_csv = next((run_dir / "derived").glob("*anchor_cluster_uncertainty*.csv"))
    pooled_csv = next((run_dir / "derived").glob("*pooled_descriptive*.csv"))
    manifest_path = next((run_dir / "manifest").glob("*.json"))

    with matched_cell_csv.open(newline="", encoding="utf-8") as handle:
        matched_cell_rows = list(csv.DictReader(handle))
    assert len(matched_cell_rows) == 4032 * 21

    counts_per_join_key: dict[str, int] = {}
    canonical_counts: dict[str, int] = {}
    for row in matched_cell_rows:
        counts_per_join_key[row["join_key_id"]] = counts_per_join_key.get(row["join_key_id"], 0) + 1
        if row["row_kind"] == "CANONICAL":
            canonical_counts[row["join_key_id"]] = canonical_counts.get(row["join_key_id"], 0) + 1
    assert len(counts_per_join_key) == 4032
    assert all(count == 21 for count in counts_per_join_key.values())
    assert all(count == 1 for count in canonical_counts.values())

    with contrast_csv.open(newline="", encoding="utf-8") as handle:
        contrast_rows = list(csv.DictReader(handle))
    assert len(contrast_rows) == 4032 * len(CONTRAST_METRICS)

    with per_symbol_csv.open(newline="", encoding="utf-8") as handle:
        per_symbol_rows = list(csv.DictReader(handle))
    assert len(per_symbol_rows) == len(EXPECTED_SYMBOLS) * len(CONTRAST_METRICS)

    with anchor_cluster_csv.open(newline="", encoding="utf-8") as handle:
        anchor_cluster_rows = list(csv.DictReader(handle))
    assert len(anchor_cluster_rows) == len(EXPECTED_SYMBOLS) * len(CONTRAST_METRICS)
    assert all("not independent samples" in row["note"] for row in anchor_cluster_rows)

    with pooled_csv.open(newline="", encoding="utf-8") as handle:
        pooled_rows = list(csv.DictReader(handle))
    assert len(pooled_rows) == len(CONTRAST_METRICS)
    assert all("descriptive" in row["note"].lower() for row in pooled_rows)
    assert all("cross-asset" in row["note"].lower() for row in pooled_rows)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["counts"]["arm_a_row_count"] == 4032
    assert manifest["counts"]["b2a_row_count"] == 80640
    assert manifest["counts"]["join_key_count"] == 4032
    assert manifest["registry"] == list(B2A_REGISTRY)
    assert manifest["sidecar_comparison_status"] == "DEFERRED_SCHEMA_NOT_EQUIVALENT"
    boundary_note_lower = manifest["statistical_boundary_note"].lower()
    assert "not independent hypothesis confirmation" in boundary_note_lower
    assert "not trading authority" in boundary_note_lower


def test_main_fails_when_archive_checksum_is_wrong(tmp_path: Path) -> None:
    content = build_arm_a_content(["BTC"], anchor_dates_ts_utc(1))
    arm_a_root = build_archive(tmp_path, "bad_arm_a", content)
    (arm_a_root / "bad_arm_a.tar.gz.sha256").write_text(f"{'0' * 64}  bad_arm_a.tar.gz\n", encoding="utf-8")
    b2a_content = build_b2a_content(["BTC"], anchor_dates_ts_utc(1))
    b2a_root = build_archive(tmp_path, "ok_b2a", b2a_content)

    argv = [
        "runner",
        "--arm-a-archive-root",
        str(arm_a_root),
        "--b2a-archive-root",
        str(b2a_root),
        "--out-dir",
        str(tmp_path / "out"),
    ]
    old_argv = sys.argv
    sys.argv = argv
    try:
        exit_code = main()
    finally:
        sys.argv = old_argv

    assert exit_code == 1
    assert not (tmp_path / "out").exists()
