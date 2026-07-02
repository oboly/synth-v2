"""
Breathline V1 Arm-A vs Arm-B.2a matched-control comparison/report runner.

Research-only, market-only, read-only. Verifies two immutable evidence
archives (Arm-A exact recovery and Arm-B.2a integer-day phase-null controls),
extracts each to an isolated scratch directory (never writing inside either
archive), cross-validates the exact preregistered cohort population, and
produces a matched-cell comparison report. This is matched phase-control
descriptive research: it is not independent hypothesis confirmation and not
trading authority. See
docs/research/breathline_three_cycle_chain_and_v1_recovery_contract_v1.md
section 10.2/10.3.

Safety markers:
  broker_private_calls=0
  broker_writes=0
  order_submission=0
  live_orders=0
  decision_gate=none
  execution_planner=none
  executor=none
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from src.market_context.breath_curve_core_v1 import parse_dt
from src.research.run_breathline_v1_recovery_orchestration_b2a_v1 import (
    NOT_INDEPENDENT_SAMPLES_NOTE,
    REGISTRY as B2A_REGISTRY,
    cluster_bootstrap_mean_ci,
)
from src.research.run_breathline_v1_recovery_orchestration_v1 import (
    find_repo_root,
    iso,
    resolve_git_commit,
    sha256_file,
    utc_now,
)


COMPARISON_ID = "ARM_A_B2A_MATCHED_CONTROL_COMPARISON"

DEFAULT_OUT_BASE = "data/research/breathline_v1_arm_a_b2a_comparison_v1"
DEFAULT_BOOTSTRAP_RESAMPLES = 2000
DEFAULT_BOOTSTRAP_SEED = 1337

# Preregistered exact cohort contract (contract section: "Cohort contract").
EXPECTED_SYMBOLS = frozenset({"BTC", "ETH", "FIL", "HBAR", "PEPE", "RENDER", "TAO", "XLM"})
EXPECTED_SYMBOL_COUNT = 8
EXPECTED_ANCHOR_COUNT = 28
EXPECTED_CHECKPOINTS = frozenset({0.618, 0.786})
EXPECTED_OFFSETS = frozenset({-10.5, -7.0, -5.0, -3.0, 0.0, 3.0, 5.0, 7.0, 10.5})
EXPECTED_ARM_A_ROW_COUNT = (
    EXPECTED_SYMBOL_COUNT * EXPECTED_ANCHOR_COUNT * len(EXPECTED_CHECKPOINTS) * len(EXPECTED_OFFSETS)
)  # 4,032
EXPECTED_SHIFT_SET = frozenset(B2A_REGISTRY)
EXPECTED_SHIFT_COUNT = len(EXPECTED_SHIFT_SET)  # 20
EXPECTED_B2A_ROW_COUNT = EXPECTED_ARM_A_ROW_COUNT * EXPECTED_SHIFT_COUNT  # 80,640

CONTRAST_METRICS = ("ranking_score", "partial_match_score", "structurally_eligible")

ARM_A_FLATTENED_REQUIRED_COLUMNS = {
    "symbol",
    "anchor_ts_utc",
    "checkpoint_ratio",
    "phase_offset_days",
    "availability_status",
    "ranking_score",
    "partial_match_score",
    "structurally_eligible",
    "selected_by_v1",
}

B2A_FLATTENED_REQUIRED_COLUMNS = {
    "symbol",
    "canonical_anchor_ts_utc",
    "shifted_anchor_ts_utc",
    "phase_class_mod_21_days",
    "anchor_displacement_days",
    "checkpoint_ratio",
    "phase_offset_days",
    "availability_status",
    "ranking_score",
    "partial_match_score",
    "structurally_eligible",
    "selected_by_v1",
}

B2A_CONTROL_METADATA_REQUIRED_COLUMNS = {
    "symbol",
    "canonical_anchor_ts_utc",
    "shifted_anchor_ts_utc",
    "phase_class_mod_21_days",
    "anchor_displacement_days",
    "availability_status",
}

MATCHED_CELL_FIELDNAMES = (
    "join_key_id",
    "symbol",
    "anchor_ts_utc",
    "checkpoint_ratio",
    "phase_offset_days",
    "row_kind",
    "phase_class_mod_21_days",
    "anchor_displacement_days",
    "ranking_score",
    "partial_match_score",
    "structurally_eligible",
    "selected_by_v1",
    "source_arm_id",
)

CONTRAST_FIELDNAMES = (
    "join_key_id",
    "symbol",
    "anchor_ts_utc",
    "checkpoint_ratio",
    "phase_offset_days",
    "metric",
    "canonical_value",
    "control_n",
    "control_mean",
    "control_median",
    "control_min",
    "control_max",
    "canonical_percentile_mid_rank",
    "canonical_minus_control_mean",
)

PER_SYMBOL_SUMMARY_FIELDNAMES = (
    "symbol",
    "metric",
    "join_key_count",
    "mean_canonical_value",
    "mean_control_mean",
    "mean_canonical_minus_control_mean",
)

ANCHOR_CLUSTER_FIELDNAMES = (
    "symbol",
    "metric",
    "cluster_count",
    "observation_count",
    "pooled_mean_contrast",
    "bootstrap_mean_contrast",
    "bootstrap_ci_low_90",
    "bootstrap_ci_high_90",
    "bootstrap_resamples",
    "bootstrap_seed",
    "note",
)

POOLED_FIELDNAMES = (
    "metric",
    "join_key_count",
    "pooled_canonical_mean",
    "pooled_control_mean",
    "pooled_canonical_minus_control_mean",
    "note",
)

POOLED_NOTE = (
    "Pooled descriptive-only summary across all symbols. Cross-asset returns are "
    "correlated and anchor-date cohorts are serially dependent; this is not an "
    "independent-sample statistic. Matched phase-control descriptive research "
    "only, not independent hypothesis confirmation and not trading authority."
)

SIDECAR_COMPARISON_DEFERRAL_NOTE = (
    "Sidecar-outcome comparison deferred: Arm-A recovery orchestration does not "
    "produce a sidecar metrics artifact, so Arm-A and B.2a sidecar schemas are not "
    "directly equivalent without adaptation. Per contract, adaptation is out of "
    "scope for this comparison."
)


class ComparisonValidationError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Archive verification (fail closed, read-only, never writes into an archive)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VerifiedArchive:
    archive_label: str
    archive_root: Path
    tar_gz_path: Path
    tar_gz_sha256: str
    extraction_root: Path
    verified_file_count: int


def find_single_file(root: Path, pattern: str, label: str) -> Path:
    matches = sorted(root.rglob(pattern))
    if len(matches) != 1:
        raise ComparisonValidationError(
            f"{label}: expected exactly one {pattern} file under {root}, found {len(matches)}"
        )
    return matches[0]


def verify_tar_gz_checksum(tar_gz_path: Path, label: str) -> str:
    sha256_path = tar_gz_path.with_name(tar_gz_path.name + ".sha256")
    if not sha256_path.is_file():
        raise ComparisonValidationError(f"{label}: missing checksum file {sha256_path}")
    recorded = sha256_path.read_text(encoding="utf-8").split()
    if not recorded:
        raise ComparisonValidationError(f"{label}: empty checksum file {sha256_path}")
    expected_hash = recorded[0].lower()
    actual_hash = sha256_file(tar_gz_path).lower()
    if actual_hash != expected_hash:
        raise ComparisonValidationError(
            f"{label}: tar.gz checksum mismatch expected={expected_hash} actual={actual_hash}"
        )
    return actual_hash


def safe_extract_tar_gz(tar_gz_path: Path, destination: Path, label: str) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    resolved_destination = destination.resolve()
    with tarfile.open(tar_gz_path, "r:gz") as archive:
        for member in archive.getmembers():
            member_path = (destination / member.name).resolve()
            if member_path != resolved_destination and not str(member_path).startswith(
                str(resolved_destination) + os.sep
            ):
                raise ComparisonValidationError(
                    f"{label}: unsafe archive member path {member.name!r}"
                )
        try:
            archive.extractall(destination, filter="data")
        except TypeError:
            archive.extractall(destination)  # pragma: no cover (pre-3.12 fallback)


def verify_sha256sums(extraction_root: Path, label: str) -> int:
    sha256sums_path = extraction_root / "SHA256SUMS"
    if not sha256sums_path.is_file():
        raise ComparisonValidationError(
            f"{label}: missing SHA256SUMS at extraction root {extraction_root}"
        )
    verified = 0
    with sha256sums_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            parts = stripped.split(None, 1)
            if len(parts) != 2:
                raise ComparisonValidationError(
                    f"{label}: malformed SHA256SUMS line {line_number}: {stripped!r}"
                )
            expected_hash, relative_path = parts
            relative_path = relative_path.lstrip("*")
            target = extraction_root / relative_path
            if not target.is_file():
                raise ComparisonValidationError(
                    f"{label}: SHA256SUMS references missing file {relative_path}"
                )
            actual_hash = sha256_file(target)
            if actual_hash.lower() != expected_hash.lower():
                raise ComparisonValidationError(
                    f"{label}: SHA256SUMS mismatch for {relative_path} "
                    f"expected={expected_hash} actual={actual_hash}"
                )
            verified += 1
    if verified == 0:
        raise ComparisonValidationError(f"{label}: SHA256SUMS contained no entries")
    return verified


def verify_and_extract_archive(archive_root: Path, work_dir: Path, label: str) -> VerifiedArchive:
    if not archive_root.is_dir():
        raise ComparisonValidationError(f"{label}: archive root is not a directory: {archive_root}")
    tar_gz_path = find_single_file(archive_root, "*.tar.gz", label)
    tar_gz_sha256 = verify_tar_gz_checksum(tar_gz_path, label)
    extraction_root = work_dir / label / "extracted"
    safe_extract_tar_gz(tar_gz_path, extraction_root, label)
    verified_file_count = verify_sha256sums(extraction_root, label)
    return VerifiedArchive(
        archive_label=label,
        archive_root=archive_root,
        tar_gz_path=tar_gz_path,
        tar_gz_sha256=tar_gz_sha256,
        extraction_root=extraction_root,
        verified_file_count=verified_file_count,
    )


# ---------------------------------------------------------------------------
# Arm-A discovery, parsing, and cohort validation
# ---------------------------------------------------------------------------


def parse_bool_column(value: str, *, column: str) -> bool:
    stripped = value.strip()
    if stripped == "True":
        return True
    if stripped == "False":
        return False
    raise ComparisonValidationError(f"schema mismatch: column {column} has non-boolean value {value!r}")


def require_columns(fieldnames: list[str] | None, required: set[str], *, label: str, path: Path) -> None:
    present = set(fieldnames or [])
    missing = required - present
    if missing:
        raise ComparisonValidationError(
            f"{label}: schema mismatch in {path}, missing columns {sorted(missing)}"
        )


@dataclass
class ArmAJoinRow:
    symbol: str
    anchor_ts_utc: str
    checkpoint_ratio: float
    phase_offset_days: float
    ranking_score: float
    partial_match_score: float
    structurally_eligible: bool
    selected_by_v1: bool


@dataclass
class ArmAEvidence:
    rows_by_join_key: dict[tuple[str, str, float, float], ArmAJoinRow]
    combo_run_ids: list[str]
    combo_source_commits: set[str]
    flattened_csv_paths: list[Path]
    manifest_paths: list[Path]


def discover_arm_a_flattened_csvs(extraction_root: Path) -> list[Path]:
    return sorted(extraction_root.rglob("breathline_v1_recovery_arm_a_flattened_*.csv"))


def discover_arm_a_manifests(extraction_root: Path) -> list[Path]:
    return sorted(extraction_root.rglob("breathline_v1_recovery_manifest_arm_a_*.json"))


def load_arm_a_evidence(extraction_root: Path) -> ArmAEvidence:
    label = "arm_a"
    flattened_csv_paths = discover_arm_a_flattened_csvs(extraction_root)
    manifest_paths = discover_arm_a_manifests(extraction_root)

    expected_combo_count = EXPECTED_SYMBOL_COUNT * EXPECTED_ANCHOR_COUNT
    if len(manifest_paths) != expected_combo_count:
        raise ComparisonValidationError(
            f"{label}: cohort mismatch, expected {expected_combo_count} combo manifests, "
            f"found {len(manifest_paths)}"
        )
    if len(flattened_csv_paths) != expected_combo_count:
        raise ComparisonValidationError(
            f"{label}: cohort mismatch, expected {expected_combo_count} flattened CSVs, "
            f"found {len(flattened_csv_paths)}"
        )

    combo_run_ids: list[str] = []
    combo_source_commits: set[str] = set()
    combo_keys_seen: set[tuple[str, str]] = set()
    symbols_seen: set[str] = set()
    anchors_seen: set[str] = set()

    for manifest_path in manifest_paths:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for required_key in ("run_id", "source_commit", "symbol", "anchor", "availability_summary"):
            if required_key not in manifest:
                raise ComparisonValidationError(
                    f"{label}: provenance mismatch, manifest {manifest_path} missing {required_key!r}"
                )
        if manifest.get("dependency_closure_integrity_status") != "PASS":
            raise ComparisonValidationError(
                f"{label}: provenance mismatch, manifest {manifest_path} does not report "
                f"dependency_closure_integrity_status=PASS"
            )
        availability_status = manifest["availability_summary"].get("availability_status")
        if availability_status != "OK":
            raise ComparisonValidationError(
                f"{label}: availability mismatch, manifest {manifest_path} reports "
                f"availability_status={availability_status!r}, expected OK"
            )
        combo_key = (manifest["symbol"], manifest["anchor"])
        if combo_key in combo_keys_seen:
            raise ComparisonValidationError(
                f"{label}: duplicate-key mismatch, combo {combo_key} appears in more than one manifest"
            )
        combo_keys_seen.add(combo_key)
        symbols_seen.add(manifest["symbol"])
        anchors_seen.add(manifest["anchor"])
        combo_run_ids.append(manifest["run_id"])
        combo_source_commits.add(manifest["source_commit"])

    if symbols_seen != EXPECTED_SYMBOLS:
        raise ComparisonValidationError(
            f"{label}: cohort mismatch, expected symbols {sorted(EXPECTED_SYMBOLS)}, "
            f"found {sorted(symbols_seen)}"
        )
    if len(anchors_seen) != EXPECTED_ANCHOR_COUNT:
        raise ComparisonValidationError(
            f"{label}: cohort mismatch, expected {EXPECTED_ANCHOR_COUNT} distinct anchors, "
            f"found {len(anchors_seen)}"
        )

    rows_by_join_key: dict[tuple[str, str, float, float], ArmAJoinRow] = {}
    total_row_count = 0

    for csv_path in flattened_csv_paths:
        with csv_path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            require_columns(
                reader.fieldnames, ARM_A_FLATTENED_REQUIRED_COLUMNS, label=label, path=csv_path
            )
            for row in reader:
                total_row_count += 1
                if row["availability_status"] != "OK":
                    raise ComparisonValidationError(
                        f"{label}: availability mismatch in {csv_path}, row has "
                        f"availability_status={row['availability_status']!r}"
                    )
                symbol = row["symbol"]
                anchor_ts_utc = row["anchor_ts_utc"]
                checkpoint_ratio = float(row["checkpoint_ratio"])
                phase_offset_days = float(row["phase_offset_days"])
                if checkpoint_ratio not in EXPECTED_CHECKPOINTS:
                    raise ComparisonValidationError(
                        f"{label}: schema mismatch in {csv_path}, unexpected checkpoint_ratio "
                        f"{checkpoint_ratio}"
                    )
                if phase_offset_days not in EXPECTED_OFFSETS:
                    raise ComparisonValidationError(
                        f"{label}: schema mismatch in {csv_path}, unexpected phase_offset_days "
                        f"{phase_offset_days}"
                    )
                join_key = (symbol, anchor_ts_utc, checkpoint_ratio, phase_offset_days)
                if join_key in rows_by_join_key:
                    raise ComparisonValidationError(
                        f"{label}: duplicate-key mismatch for join key {join_key} in {csv_path}"
                    )
                rows_by_join_key[join_key] = ArmAJoinRow(
                    symbol=symbol,
                    anchor_ts_utc=anchor_ts_utc,
                    checkpoint_ratio=checkpoint_ratio,
                    phase_offset_days=phase_offset_days,
                    ranking_score=float(row["ranking_score"]),
                    partial_match_score=float(row["partial_match_score"]),
                    structurally_eligible=parse_bool_column(
                        row["structurally_eligible"], column="structurally_eligible"
                    ),
                    selected_by_v1=parse_bool_column(row["selected_by_v1"], column="selected_by_v1"),
                )

    if total_row_count != EXPECTED_ARM_A_ROW_COUNT:
        raise ComparisonValidationError(
            f"{label}: cohort mismatch, expected {EXPECTED_ARM_A_ROW_COUNT} rows, "
            f"found {total_row_count}"
        )
    if len(rows_by_join_key) != EXPECTED_ARM_A_ROW_COUNT:
        raise ComparisonValidationError(
            f"{label}: duplicate-key mismatch, expected {EXPECTED_ARM_A_ROW_COUNT} distinct join "
            f"keys, found {len(rows_by_join_key)}"
        )

    return ArmAEvidence(
        rows_by_join_key=rows_by_join_key,
        combo_run_ids=combo_run_ids,
        combo_source_commits=combo_source_commits,
        flattened_csv_paths=flattened_csv_paths,
        manifest_paths=manifest_paths,
    )


# ---------------------------------------------------------------------------
# B.2a discovery, parsing, and cohort validation
# ---------------------------------------------------------------------------


@dataclass
class B2aJoinRow:
    ranking_score: float
    partial_match_score: float
    structurally_eligible: bool
    selected_by_v1: bool
    phase_class_mod_21_days: int
    anchor_displacement_days: int


@dataclass
class B2aEvidence:
    rows_by_join_key: dict[tuple[str, str, float, float], list[B2aJoinRow]]
    run_id: str
    source_commit: str
    flattened_csv_path: Path
    control_metadata_csv_path: Path
    manifest_path: Path


def discover_b2a_flattened_csv(extraction_root: Path) -> Path:
    return find_single_file(extraction_root, "breathline_v1_recovery_b2a_flattened_*.csv", "b2a")


def discover_b2a_control_metadata_csv(extraction_root: Path) -> Path:
    return find_single_file(
        extraction_root, "breathline_v1_recovery_b2a_control_metadata_*.csv", "b2a"
    )


def discover_b2a_manifest(extraction_root: Path) -> Path:
    return find_single_file(extraction_root, "breathline_v1_recovery_b2a_manifest_*.json", "b2a")


def validate_exact_shift_set(shifts: set[int], *, context: str) -> None:
    if shifts != EXPECTED_SHIFT_SET:
        missing = EXPECTED_SHIFT_SET - shifts
        extra = shifts - EXPECTED_SHIFT_SET
        raise ComparisonValidationError(
            f"missing/duplicate shift for {context}: missing={sorted(missing)} unexpected={sorted(extra)}"
        )


def validate_b2a_join_groups(rows_by_join_key: dict[tuple[str, str, float, float], list[B2aJoinRow]]) -> None:
    for join_key, group in rows_by_join_key.items():
        if len(group) != EXPECTED_SHIFT_COUNT:
            raise ComparisonValidationError(
                f"missing/duplicate shift for join key {join_key}, expected "
                f"{EXPECTED_SHIFT_COUNT} control rows, found {len(group)}"
            )
        shift_set = {row.phase_class_mod_21_days for row in group}
        validate_exact_shift_set(shift_set, context=f"join key {join_key}")


def validate_shift_mapping(
    *,
    canonical_anchor_ts_utc: str,
    shifted_anchor_ts_utc: str,
    anchor_displacement_days: int,
    context: str,
) -> None:
    expected_shifted = iso(parse_dt(canonical_anchor_ts_utc) + timedelta(days=anchor_displacement_days))
    if expected_shifted != shifted_anchor_ts_utc:
        raise ComparisonValidationError(
            f"incorrect anchor mapping for {context}: canonical_anchor_ts_utc="
            f"{canonical_anchor_ts_utc} anchor_displacement_days={anchor_displacement_days} "
            f"expected shifted_anchor_ts_utc={expected_shifted} but found {shifted_anchor_ts_utc}"
        )


def load_b2a_evidence(extraction_root: Path) -> B2aEvidence:
    label = "b2a"
    flattened_csv_path = discover_b2a_flattened_csv(extraction_root)
    control_metadata_csv_path = discover_b2a_control_metadata_csv(extraction_root)
    manifest_path = discover_b2a_manifest(extraction_root)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for required_key in ("run_id", "source_commit", "registry", "combo_count", "ok_combo_count",
                          "data_unavailable_combo_count"):
        if required_key not in manifest:
            raise ComparisonValidationError(
                f"{label}: provenance mismatch, manifest {manifest_path} missing {required_key!r}"
            )
    if manifest.get("dependency_closure_integrity_status") != "PASS":
        raise ComparisonValidationError(
            f"{label}: provenance mismatch, manifest does not report "
            f"dependency_closure_integrity_status=PASS"
        )
    if list(manifest["registry"]) != list(B2A_REGISTRY):
        raise ComparisonValidationError(
            f"{label}: cohort mismatch, manifest registry {manifest['registry']} does not match "
            f"the frozen B.2a registry {list(B2A_REGISTRY)}"
        )
    expected_combo_count = EXPECTED_SYMBOL_COUNT * EXPECTED_ANCHOR_COUNT * EXPECTED_SHIFT_COUNT
    if manifest["combo_count"] != expected_combo_count:
        raise ComparisonValidationError(
            f"{label}: cohort mismatch, manifest combo_count={manifest['combo_count']}, "
            f"expected {expected_combo_count}"
        )
    if manifest["data_unavailable_combo_count"] != 0 or manifest["ok_combo_count"] != expected_combo_count:
        raise ComparisonValidationError(
            f"{label}: availability mismatch, manifest reports "
            f"ok_combo_count={manifest['ok_combo_count']} "
            f"data_unavailable_combo_count={manifest['data_unavailable_combo_count']}, "
            f"expected all {expected_combo_count} combos OK"
        )

    symbols_seen: set[str] = set()
    canonical_anchor_keys_seen: set[tuple[str, str]] = set()
    shifts_by_combo: dict[tuple[str, str], set[int]] = {}
    control_row_count = 0

    with control_metadata_csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        require_columns(
            reader.fieldnames,
            B2A_CONTROL_METADATA_REQUIRED_COLUMNS,
            label=label,
            path=control_metadata_csv_path,
        )
        for row in reader:
            control_row_count += 1
            if row["availability_status"] != "OK":
                raise ComparisonValidationError(
                    f"{label}: availability mismatch in {control_metadata_csv_path}, row has "
                    f"availability_status={row['availability_status']!r}"
                )
            phase_class = int(row["phase_class_mod_21_days"])
            displacement = int(row["anchor_displacement_days"])
            if phase_class != displacement:
                raise ComparisonValidationError(
                    f"{label}: schema mismatch, phase_class_mod_21_days={phase_class} != "
                    f"anchor_displacement_days={displacement} in {control_metadata_csv_path}"
                )
            validate_shift_mapping(
                canonical_anchor_ts_utc=row["canonical_anchor_ts_utc"],
                shifted_anchor_ts_utc=row["shifted_anchor_ts_utc"],
                anchor_displacement_days=displacement,
                context=f"control metadata row symbol={row['symbol']} shift={displacement}",
            )
            combo_key = (row["symbol"], row["canonical_anchor_ts_utc"])
            symbols_seen.add(row["symbol"])
            canonical_anchor_keys_seen.add(combo_key)
            shifts_by_combo.setdefault(combo_key, set()).add(phase_class)

    if control_row_count != expected_combo_count:
        raise ComparisonValidationError(
            f"{label}: cohort mismatch, expected {expected_combo_count} control metadata rows, "
            f"found {control_row_count}"
        )
    if symbols_seen != EXPECTED_SYMBOLS:
        raise ComparisonValidationError(
            f"{label}: cohort mismatch, expected symbols {sorted(EXPECTED_SYMBOLS)}, "
            f"found {sorted(symbols_seen)}"
        )
    distinct_anchor_count = len({key[1] for key in canonical_anchor_keys_seen})
    if distinct_anchor_count != EXPECTED_ANCHOR_COUNT:
        raise ComparisonValidationError(
            f"{label}: cohort mismatch, expected {EXPECTED_ANCHOR_COUNT} distinct canonical "
            f"anchors, found {distinct_anchor_count}"
        )
    for combo_key, shifts in shifts_by_combo.items():
        validate_exact_shift_set(shifts, context=str(combo_key))

    rows_by_join_key: dict[tuple[str, str, float, float], list[B2aJoinRow]] = {}
    total_row_count = 0

    with flattened_csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        require_columns(
            reader.fieldnames, B2A_FLATTENED_REQUIRED_COLUMNS, label=label, path=flattened_csv_path
        )
        for row in reader:
            total_row_count += 1
            if row["availability_status"] != "OK":
                raise ComparisonValidationError(
                    f"{label}: availability mismatch in {flattened_csv_path}, row has "
                    f"availability_status={row['availability_status']!r}"
                )
            phase_class = int(row["phase_class_mod_21_days"])
            displacement = int(row["anchor_displacement_days"])
            if phase_class != displacement:
                raise ComparisonValidationError(
                    f"{label}: schema mismatch, phase_class_mod_21_days={phase_class} != "
                    f"anchor_displacement_days={displacement} in {flattened_csv_path}"
                )
            validate_shift_mapping(
                canonical_anchor_ts_utc=row["canonical_anchor_ts_utc"],
                shifted_anchor_ts_utc=row["shifted_anchor_ts_utc"],
                anchor_displacement_days=displacement,
                context=f"flattened row symbol={row['symbol']} shift={displacement}",
            )
            checkpoint_ratio = float(row["checkpoint_ratio"])
            phase_offset_days = float(row["phase_offset_days"])
            if checkpoint_ratio not in EXPECTED_CHECKPOINTS:
                raise ComparisonValidationError(
                    f"{label}: schema mismatch in {flattened_csv_path}, unexpected checkpoint_ratio "
                    f"{checkpoint_ratio}"
                )
            if phase_offset_days not in EXPECTED_OFFSETS:
                raise ComparisonValidationError(
                    f"{label}: schema mismatch in {flattened_csv_path}, unexpected phase_offset_days "
                    f"{phase_offset_days}"
                )
            join_key = (row["symbol"], row["canonical_anchor_ts_utc"], checkpoint_ratio, phase_offset_days)
            group = rows_by_join_key.setdefault(join_key, [])
            if any(existing.phase_class_mod_21_days == phase_class for existing in group):
                raise ComparisonValidationError(
                    f"{label}: duplicate-key mismatch, join key {join_key} has more than one row "
                    f"for shift {phase_class}"
                )
            group.append(
                B2aJoinRow(
                    ranking_score=float(row["ranking_score"]),
                    partial_match_score=float(row["partial_match_score"]),
                    structurally_eligible=parse_bool_column(
                        row["structurally_eligible"], column="structurally_eligible"
                    ),
                    selected_by_v1=parse_bool_column(row["selected_by_v1"], column="selected_by_v1"),
                    phase_class_mod_21_days=phase_class,
                    anchor_displacement_days=displacement,
                )
            )

    if total_row_count != EXPECTED_B2A_ROW_COUNT:
        raise ComparisonValidationError(
            f"{label}: cohort mismatch, expected {EXPECTED_B2A_ROW_COUNT} flattened rows, "
            f"found {total_row_count}"
        )
    if len(rows_by_join_key) != EXPECTED_ARM_A_ROW_COUNT:
        raise ComparisonValidationError(
            f"{label}: cohort mismatch, expected {EXPECTED_ARM_A_ROW_COUNT} distinct join keys, "
            f"found {len(rows_by_join_key)}"
        )
    validate_b2a_join_groups(rows_by_join_key)

    return B2aEvidence(
        rows_by_join_key=rows_by_join_key,
        run_id=manifest["run_id"],
        source_commit=manifest["source_commit"],
        flattened_csv_path=flattened_csv_path,
        control_metadata_csv_path=control_metadata_csv_path,
        manifest_path=manifest_path,
    )


# ---------------------------------------------------------------------------
# Cross-archive cohort validation (population equality, no orphans)
# ---------------------------------------------------------------------------


def validate_join_key_population_equality(
    arm_a_evidence: ArmAEvidence, b2a_evidence: B2aEvidence
) -> None:
    arm_a_keys = set(arm_a_evidence.rows_by_join_key)
    b2a_keys = set(b2a_evidence.rows_by_join_key)
    only_in_arm_a = arm_a_keys - b2a_keys
    only_in_b2a = b2a_keys - arm_a_keys
    if only_in_arm_a or only_in_b2a:
        raise ComparisonValidationError(
            "population mismatch: join keys do not match exactly between Arm-A and B.2a "
            f"(arm_a_only={len(only_in_arm_a)} b2a_only={len(only_in_b2a)})"
        )


# ---------------------------------------------------------------------------
# Matched-cell / contrast statistics
# ---------------------------------------------------------------------------


def metric_value(row: Any, metric: str) -> float:
    raw = getattr(row, metric)
    return 1.0 if raw is True else (0.0 if raw is False else float(raw))


def tie_aware_mid_rank_percentile(value: float, population: list[float]) -> float:
    n = len(population)
    below = sum(1 for item in population if item < value)
    equal = sum(1 for item in population if item == value)
    return round(((below + 0.5 * equal) / n) * 100.0, 4)


def join_key_id(join_key: tuple[str, str, float, float]) -> str:
    symbol, anchor_ts_utc, checkpoint_ratio, phase_offset_days = join_key
    return f"{symbol}|{anchor_ts_utc}|{checkpoint_ratio}|{phase_offset_days}"


def build_matched_cell_rows(
    arm_a_evidence: ArmAEvidence, b2a_evidence: B2aEvidence
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for join_key in sorted(arm_a_evidence.rows_by_join_key):
        symbol, anchor_ts_utc, checkpoint_ratio, phase_offset_days = join_key
        jid = join_key_id(join_key)
        canonical = arm_a_evidence.rows_by_join_key[join_key]
        rows.append(
            {
                "join_key_id": jid,
                "symbol": symbol,
                "anchor_ts_utc": anchor_ts_utc,
                "checkpoint_ratio": checkpoint_ratio,
                "phase_offset_days": phase_offset_days,
                "row_kind": "CANONICAL",
                "phase_class_mod_21_days": 0,
                "anchor_displacement_days": 0,
                "ranking_score": canonical.ranking_score,
                "partial_match_score": canonical.partial_match_score,
                "structurally_eligible": canonical.structurally_eligible,
                "selected_by_v1": canonical.selected_by_v1,
                "source_arm_id": "ARM_A",
            }
        )
        controls = sorted(
            b2a_evidence.rows_by_join_key[join_key], key=lambda item: item.phase_class_mod_21_days
        )
        for control in controls:
            rows.append(
                {
                    "join_key_id": jid,
                    "symbol": symbol,
                    "anchor_ts_utc": anchor_ts_utc,
                    "checkpoint_ratio": checkpoint_ratio,
                    "phase_offset_days": phase_offset_days,
                    "row_kind": "CONTROL",
                    "phase_class_mod_21_days": control.phase_class_mod_21_days,
                    "anchor_displacement_days": control.anchor_displacement_days,
                    "ranking_score": control.ranking_score,
                    "partial_match_score": control.partial_match_score,
                    "structurally_eligible": control.structurally_eligible,
                    "selected_by_v1": control.selected_by_v1,
                    "source_arm_id": "ARM_B2A",
                }
            )
    return rows


def build_contrast_rows(
    arm_a_evidence: ArmAEvidence, b2a_evidence: B2aEvidence
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for join_key in sorted(arm_a_evidence.rows_by_join_key):
        symbol, anchor_ts_utc, checkpoint_ratio, phase_offset_days = join_key
        jid = join_key_id(join_key)
        canonical = arm_a_evidence.rows_by_join_key[join_key]
        controls = b2a_evidence.rows_by_join_key[join_key]
        for metric in CONTRAST_METRICS:
            canonical_value = metric_value(canonical, metric)
            control_values = [metric_value(control, metric) for control in controls]
            control_mean = statistics.fmean(control_values)
            rows.append(
                {
                    "join_key_id": jid,
                    "symbol": symbol,
                    "anchor_ts_utc": anchor_ts_utc,
                    "checkpoint_ratio": checkpoint_ratio,
                    "phase_offset_days": phase_offset_days,
                    "metric": metric,
                    "canonical_value": canonical_value,
                    "control_n": len(control_values),
                    "control_mean": round(control_mean, 6),
                    "control_median": round(statistics.median(control_values), 6),
                    "control_min": round(min(control_values), 6),
                    "control_max": round(max(control_values), 6),
                    "canonical_percentile_mid_rank": tie_aware_mid_rank_percentile(
                        canonical_value, control_values
                    ),
                    "canonical_minus_control_mean": round(canonical_value - control_mean, 6),
                }
            )
    return rows


def build_per_symbol_summary(contrast_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    symbols = sorted({row["symbol"] for row in contrast_rows})
    out: list[dict[str, Any]] = []
    for symbol in symbols:
        for metric in CONTRAST_METRICS:
            cell_rows = [
                row for row in contrast_rows if row["symbol"] == symbol and row["metric"] == metric
            ]
            out.append(
                {
                    "symbol": symbol,
                    "metric": metric,
                    "join_key_count": len(cell_rows),
                    "mean_canonical_value": round(
                        statistics.fmean(row["canonical_value"] for row in cell_rows), 6
                    ),
                    "mean_control_mean": round(
                        statistics.fmean(row["control_mean"] for row in cell_rows), 6
                    ),
                    "mean_canonical_minus_control_mean": round(
                        statistics.fmean(row["canonical_minus_control_mean"] for row in cell_rows), 6
                    ),
                }
            )
    return out


def build_anchor_cluster_uncertainty(
    contrast_rows: list[dict[str, Any]], *, num_resamples: int, seed: int
) -> list[dict[str, Any]]:
    symbols = sorted({row["symbol"] for row in contrast_rows})
    out: list[dict[str, Any]] = []
    for symbol in symbols:
        for metric in CONTRAST_METRICS:
            cell_rows = [
                row for row in contrast_rows if row["symbol"] == symbol and row["metric"] == metric
            ]
            clusters: dict[str, list[float]] = {}
            for row in cell_rows:
                clusters.setdefault(row["anchor_ts_utc"], []).append(row["canonical_minus_control_mean"])
            pooled_values = [value for values in clusters.values() for value in values]
            if not pooled_values:
                out.append(
                    {
                        "symbol": symbol,
                        "metric": metric,
                        "cluster_count": 0,
                        "observation_count": 0,
                        "pooled_mean_contrast": None,
                        "bootstrap_mean_contrast": None,
                        "bootstrap_ci_low_90": None,
                        "bootstrap_ci_high_90": None,
                        "bootstrap_resamples": num_resamples,
                        "bootstrap_seed": seed,
                        "note": NOT_INDEPENDENT_SAMPLES_NOTE,
                    }
                )
                continue
            bootstrap_mean, ci_low, ci_high = cluster_bootstrap_mean_ci(
                clusters, num_resamples=num_resamples, seed=seed
            )
            out.append(
                {
                    "symbol": symbol,
                    "metric": metric,
                    "cluster_count": len(clusters),
                    "observation_count": len(pooled_values),
                    "pooled_mean_contrast": round(statistics.fmean(pooled_values), 6),
                    "bootstrap_mean_contrast": round(bootstrap_mean, 6),
                    "bootstrap_ci_low_90": round(ci_low, 6),
                    "bootstrap_ci_high_90": round(ci_high, 6),
                    "bootstrap_resamples": num_resamples,
                    "bootstrap_seed": seed,
                    "note": NOT_INDEPENDENT_SAMPLES_NOTE,
                }
            )
    return out


def build_pooled_descriptive_summary(contrast_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for metric in CONTRAST_METRICS:
        cell_rows = [row for row in contrast_rows if row["metric"] == metric]
        out.append(
            {
                "metric": metric,
                "join_key_count": len(cell_rows),
                "pooled_canonical_mean": round(
                    statistics.fmean(row["canonical_value"] for row in cell_rows), 6
                ),
                "pooled_control_mean": round(
                    statistics.fmean(row["control_mean"] for row in cell_rows), 6
                ),
                "pooled_canonical_minus_control_mean": round(
                    statistics.fmean(row["canonical_minus_control_mean"] for row in cell_rows), 6
                ),
                "note": POOLED_NOTE,
            }
        )
    return out


def write_csv_rows(path: Path, fieldnames: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compare Arm-A exact recovery evidence against Arm-B.2a matched integer-day "
            "phase-null controls (matched phase-control descriptive research only)."
        )
    )
    parser.add_argument("--arm-a-archive-root", required=True)
    parser.add_argument("--b2a-archive-root", required=True)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_BASE)
    parser.add_argument("--bootstrap-resamples", type=int, default=DEFAULT_BOOTSTRAP_RESAMPLES)
    parser.add_argument("--bootstrap-seed", type=int, default=DEFAULT_BOOTSTRAP_SEED)
    args = parser.parse_args()

    arm_a_archive_root = Path(args.arm_a_archive_root)
    b2a_archive_root = Path(args.b2a_archive_root)

    repo_root = find_repo_root()
    try:
        orchestration_runner_commit = resolve_git_commit(repo_root)
    except RuntimeError as exc:
        print(f"FAILED {exc}", flush=True)
        return 1

    print(
        f"STARTED runner=breathline_v1_arm_a_b2a_comparison_v1 "
        f"arm_a_archive_root={arm_a_archive_root} b2a_archive_root={b2a_archive_root}",
        flush=True,
    )

    try:
        with tempfile.TemporaryDirectory(prefix="breathline_arm_a_b2a_comparison_") as tmp:
            work_dir = Path(tmp)

            print("PHASE verify_arm_a_archive", flush=True)
            arm_a_archive = verify_and_extract_archive(arm_a_archive_root, work_dir, "arm_a")
            print(
                f"PHASE verify_arm_a_archive_done verified_files={arm_a_archive.verified_file_count}",
                flush=True,
            )

            print("PHASE verify_b2a_archive", flush=True)
            b2a_archive = verify_and_extract_archive(b2a_archive_root, work_dir, "b2a")
            print(
                f"PHASE verify_b2a_archive_done verified_files={b2a_archive.verified_file_count}",
                flush=True,
            )

            print("PHASE load_arm_a_evidence", flush=True)
            arm_a_evidence = load_arm_a_evidence(arm_a_archive.extraction_root)
            print(
                f"PHASE load_arm_a_evidence_done join_keys={len(arm_a_evidence.rows_by_join_key)}",
                flush=True,
            )

            print("PHASE load_b2a_evidence", flush=True)
            b2a_evidence = load_b2a_evidence(b2a_archive.extraction_root)
            print(
                f"PHASE load_b2a_evidence_done join_keys={len(b2a_evidence.rows_by_join_key)}",
                flush=True,
            )

            print("PHASE validate_population_equality", flush=True)
            validate_join_key_population_equality(arm_a_evidence, b2a_evidence)

            print("PHASE build_matched_cells", flush=True)
            matched_cell_rows = build_matched_cell_rows(arm_a_evidence, b2a_evidence)

            print("PHASE build_contrast_rows", flush=True)
            contrast_rows = build_contrast_rows(arm_a_evidence, b2a_evidence)

            per_symbol_rows = build_per_symbol_summary(contrast_rows)
            anchor_cluster_rows = build_anchor_cluster_uncertainty(
                contrast_rows,
                num_resamples=args.bootstrap_resamples,
                seed=args.bootstrap_seed,
            )
            pooled_rows = build_pooled_descriptive_summary(contrast_rows)

            started_at = utc_now()
            run_id = f"arm_a_b2a_comparison_{started_at.strftime('%Y%m%dT%H%M%SZ')}"
            run_dir = Path(args.out_dir) / run_id
            derived_dir = run_dir / "derived"
            manifest_dir = run_dir / "manifest"
            derived_dir.mkdir(parents=True, exist_ok=True)
            manifest_dir.mkdir(parents=True, exist_ok=True)

            matched_cell_csv_path = derived_dir / f"arm_a_b2a_matched_cell_{run_id}.csv"
            write_csv_rows(matched_cell_csv_path, MATCHED_CELL_FIELDNAMES, matched_cell_rows)

            contrast_csv_path = derived_dir / f"arm_a_b2a_contrast_{run_id}.csv"
            write_csv_rows(contrast_csv_path, CONTRAST_FIELDNAMES, contrast_rows)

            per_symbol_csv_path = derived_dir / f"arm_a_b2a_per_symbol_summary_{run_id}.csv"
            write_csv_rows(per_symbol_csv_path, PER_SYMBOL_SUMMARY_FIELDNAMES, per_symbol_rows)

            anchor_cluster_csv_path = derived_dir / f"arm_a_b2a_anchor_cluster_uncertainty_{run_id}.csv"
            write_csv_rows(anchor_cluster_csv_path, ANCHOR_CLUSTER_FIELDNAMES, anchor_cluster_rows)

            pooled_csv_path = derived_dir / f"arm_a_b2a_pooled_descriptive_{run_id}.csv"
            write_csv_rows(pooled_csv_path, POOLED_FIELDNAMES, pooled_rows)

            manifest = {
                "run_id": run_id,
                "comparison_id": COMPARISON_ID,
                "generated_at_utc": iso(utc_now()),
                "orchestration_runner_commit": orchestration_runner_commit,
                "input_archives": {
                    "arm_a": {
                        "archive_root": str(arm_a_archive_root),
                        "tar_gz_path": str(arm_a_archive.tar_gz_path),
                        "tar_gz_sha256": arm_a_archive.tar_gz_sha256,
                        "sha256sums_verified_file_count": arm_a_archive.verified_file_count,
                        "source_run_ids": sorted(arm_a_evidence.combo_run_ids),
                        "source_commits": sorted(arm_a_evidence.combo_source_commits),
                        "source_artifact_hashes": {
                            "flattened_csv_count": len(arm_a_evidence.flattened_csv_paths),
                            "manifest_count": len(arm_a_evidence.manifest_paths),
                        },
                    },
                    "b2a": {
                        "archive_root": str(b2a_archive_root),
                        "tar_gz_path": str(b2a_archive.tar_gz_path),
                        "tar_gz_sha256": b2a_archive.tar_gz_sha256,
                        "sha256sums_verified_file_count": b2a_archive.verified_file_count,
                        "source_run_id": b2a_evidence.run_id,
                        "source_commit": b2a_evidence.source_commit,
                        "source_artifact_hashes": {
                            "flattened_csv_sha256": sha256_file(b2a_evidence.flattened_csv_path),
                            "control_metadata_csv_sha256": sha256_file(
                                b2a_evidence.control_metadata_csv_path
                            ),
                            "manifest_sha256": sha256_file(b2a_evidence.manifest_path),
                        },
                    },
                },
                "registry": list(B2A_REGISTRY),
                "counts": {
                    "arm_a_row_count": EXPECTED_ARM_A_ROW_COUNT,
                    "b2a_row_count": EXPECTED_B2A_ROW_COUNT,
                    "join_key_count": len(arm_a_evidence.rows_by_join_key),
                    "matched_cell_row_count": len(matched_cell_rows),
                    "contrast_row_count": len(contrast_rows),
                },
                "bootstrap_resamples": args.bootstrap_resamples,
                "bootstrap_seed": args.bootstrap_seed,
                "output_artifacts": {
                    "matched_cell_csv": {
                        "path": str(matched_cell_csv_path),
                        "sha256": sha256_file(matched_cell_csv_path),
                        "rows": len(matched_cell_rows),
                    },
                    "contrast_csv": {
                        "path": str(contrast_csv_path),
                        "sha256": sha256_file(contrast_csv_path),
                        "rows": len(contrast_rows),
                    },
                    "per_symbol_summary_csv": {
                        "path": str(per_symbol_csv_path),
                        "sha256": sha256_file(per_symbol_csv_path),
                        "rows": len(per_symbol_rows),
                    },
                    "anchor_cluster_uncertainty_csv": {
                        "path": str(anchor_cluster_csv_path),
                        "sha256": sha256_file(anchor_cluster_csv_path),
                        "rows": len(anchor_cluster_rows),
                    },
                    "pooled_descriptive_csv": {
                        "path": str(pooled_csv_path),
                        "sha256": sha256_file(pooled_csv_path),
                        "rows": len(pooled_rows),
                    },
                },
                "sidecar_comparison_status": "DEFERRED_SCHEMA_NOT_EQUIVALENT",
                "sidecar_comparison_note": SIDECAR_COMPARISON_DEFERRAL_NOTE,
                "statistical_boundary_note": (
                    "Matched phase-control descriptive research only. No independent-row "
                    "p-values, no promotion threshold, no validated/predictive/trade/execution/"
                    "ranking conclusion. Not independent hypothesis confirmation and not "
                    "trading authority."
                ),
            }
            manifest_path = manifest_dir / f"arm_a_b2a_comparison_manifest_{run_id}.json"
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

            print(
                f"FINISHED run_id={run_id} join_keys={len(arm_a_evidence.rows_by_join_key)} "
                f"matched_cell_rows={len(matched_cell_rows)} contrast_rows={len(contrast_rows)}",
                flush=True,
            )
            return 0
    except ComparisonValidationError as exc:
        print(f"FAILED {exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
