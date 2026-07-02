"""
Breathline V1 recovery orchestration Arm B.2a: legacy V1 integer-day phase-null controls.

Research-only, market-only, read-only. Invokes the frozen V1 partial/full breath-curve
backtest once per (symbol, canonical anchor, shift) combination across a fixed registry
of 20 non-zero integer-day physical anchor displacements. B.2a is matched phase-control
research, not independent samples and not trading authority. See
docs/research/breathline_three_cycle_chain_and_v1_recovery_contract_v1.md section 10.2.

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
import random
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from src.market_context.breath_curve_core_v1 import Candle, iso, parse_dt
from src.research.breath_curve_template_matcher_v1 import (
    load_csv as load_candle_csv,
    load_db as load_candle_db,
)
from src.research.run_breathline_v1_recovery_orchestration_v1 import (
    V1_MODULE,
    find_repo_root,
    locate_v1_artifacts,
    parse_jsonl,
    required_marker_due,
    required_marker_matched,
    resolve_git_commit,
    score_zero_reason,
    sha256_file,
    structurally_eligible,
    utc_now,
    verify_dependency_closure_integrity,
)


ARM_ID = "ARM_B2A"
CONTROL_TAXONOMY = "INTEGER_DAY_PHASE_NULL_CONTROL"
NOT_INDEPENDENT_SAMPLES_NOTE = (
    "B.2a is matched phase-control research, not independent samples and not "
    "trading authority."
)

# Preregistered, fixed, ordered. No 0d shift. No dynamic/random/inferred/filtered/
# result-dependent shifts. Each value is used unchanged as both
# phase_class_mod_21_days and anchor_displacement_days (contract section 10.2).
REGISTRY: tuple[int, ...] = (
    -10, -9, -8, -7, -6, -5, -4, -3, -2, -1,
    1, 2, 3, 4, 5, 6, 7, 8, 9, 10,
)

DEFAULT_OUT_BASE = "data/research/breathline_v1_recovery_orchestration_b2a_v1"
DEFAULT_VENUE = "bitvavo"
DEFAULT_INTERVAL_CODE = "1d"
DEFAULT_BOOTSTRAP_RESAMPLES = 2000
DEFAULT_BOOTSTRAP_SEED = 1337

CONTROL_METADATA_FIELDNAMES = (
    "run_id",
    "arm_id",
    "control_taxonomy",
    "symbol",
    "canonical_anchor_ts_utc",
    "shifted_anchor_ts_utc",
    "phase_class_mod_21_days",
    "anchor_displacement_days",
    "availability_status",
    "source_commit",
    "raw_csv_path",
    "raw_jsonl_path",
    "raw_jsonl_sha256",
    "ok_row_count",
    "data_unavailable_row_count",
)

FLATTENED_FIELDNAMES_B2A = (
    "run_id",
    "arm_id",
    "control_taxonomy",
    "symbol",
    "canonical_anchor_ts_utc",
    "shifted_anchor_ts_utc",
    "phase_class_mod_21_days",
    "anchor_displacement_days",
    "availability_status",
    "source_jsonl_path",
    "source_jsonl_row_number",
    "source_jsonl_sha256",
    "checkpoint_ratio",
    "selected_partial_offset_days",
    "as_of_ts_utc",
    "phase_offset_days",
    "future_target_is_future",
    "partial_match_score",
    "ranking_score",
    "required_ratio",
    "required_marker_due",
    "required_marker_matched",
    "due_marker_count",
    "observed_marker_count",
    "min_due_markers_met",
    "structurally_eligible",
    "score_zero_reason",
    "notes_json",
    "selected_by_v1",
)

SIDECAR_FIELDNAMES = (
    "run_id",
    "arm_id",
    "symbol",
    "canonical_anchor_ts_utc",
    "shifted_anchor_ts_utc",
    "phase_class_mod_21_days",
    "anchor_displacement_days",
    "checkpoint_ratio",
    "as_of_ts_utc",
    "target_ts_utc",
    "as_of_close",
    "mfe_from_high_pct",
    "mae_from_low_pct",
    "close_to_close_1000_pct",
    "time_to_window_high_bars",
    "sidecar_status",
)

PER_SYMBOL_SUMMARY_FIELDNAMES = (
    "run_id",
    "symbol",
    "combo_count",
    "ok_combo_count",
    "data_unavailable_combo_count",
    "flattened_row_count",
    "selected_row_count",
    "mean_selected_partial_match_score",
    "mean_selected_close_to_close_1000_pct",
)

ANCHOR_CLUSTER_FIELDNAMES = (
    "run_id",
    "symbol",
    "metric",
    "cluster_count",
    "observation_count",
    "pooled_mean",
    "bootstrap_mean",
    "bootstrap_ci_low_90",
    "bootstrap_ci_high_90",
    "bootstrap_resamples",
    "bootstrap_seed",
    "note",
)


def validate_registry(registry: tuple[int, ...]) -> None:
    if len(registry) != 20:
        raise ValueError(f"registry must contain exactly 20 shifts, got {len(registry)}")
    if 0 in registry:
        raise ValueError("registry must not contain a 0d shift")
    if len(set(registry)) != len(registry):
        raise ValueError("registry must not contain duplicate shifts")
    phase_classes = [shift % 21 for shift in registry]
    if len(set(phase_classes)) != len(phase_classes):
        raise ValueError("registry must not contain duplicate phase classes modulo 21d")


validate_registry(REGISTRY)


@dataclass(frozen=True)
class ControlMetadataRow:
    run_id: str
    arm_id: str
    control_taxonomy: str
    symbol: str
    canonical_anchor_ts_utc: str
    shifted_anchor_ts_utc: str
    phase_class_mod_21_days: int
    anchor_displacement_days: int
    availability_status: str
    source_commit: str
    raw_csv_path: str
    raw_jsonl_path: str
    raw_jsonl_sha256: str
    ok_row_count: int
    data_unavailable_row_count: int


def build_shift_combo(symbol: str, canonical_anchor: datetime, shift: int) -> dict[str, Any]:
    shifted_anchor = canonical_anchor + timedelta(days=shift)
    return {
        "symbol": symbol,
        "canonical_anchor": canonical_anchor,
        "canonical_anchor_ts_utc": iso(canonical_anchor),
        "shift": shift,
        "shifted_anchor": shifted_anchor,
        "shifted_anchor_ts_utc": iso(shifted_anchor),
        "phase_class_mod_21_days": shift,
        "anchor_displacement_days": shift,
    }


def build_combos(symbols: list[str], canonical_anchors: list[datetime]) -> list[dict[str, Any]]:
    combos: list[dict[str, Any]] = []
    for symbol in symbols:
        for canonical_anchor in canonical_anchors:
            for shift in REGISTRY:
                combos.append(build_shift_combo(symbol, canonical_anchor, shift))
    return combos


def combo_id(combo: dict[str, Any]) -> str:
    anchor_stamp = combo["canonical_anchor"].strftime("%Y%m%dT%H%M%SZ")
    return f"{combo['symbol']}_{combo['shift']:+03d}d_{anchor_stamp}"


def combo_availability(rows: list[dict[str, Any]]) -> tuple[str, int, int]:
    ok_row_count = sum(1 for row in rows if row.get("status") == "OK")
    unavailable_row_count = sum(1 for row in rows if row.get("status") != "OK")
    availability_status = "DATA_UNAVAILABLE" if unavailable_row_count > 0 else "OK"
    return availability_status, ok_row_count, unavailable_row_count


def flatten_combo_rows(
    rows: list[dict[str, Any]],
    *,
    run_id: str,
    combo: dict[str, Any],
    source_jsonl_path: str,
    source_jsonl_sha256: str,
) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for fallback_row_number, row in enumerate(rows, start=1):
        if row.get("status") != "OK":
            continue
        source_row_number = int(row.get("_source_jsonl_row_number", fallback_row_number))
        selected_offset = row.get("selected_partial_offset_days")
        for item in row["all_partial_offsets"]:
            result = item["result"]
            notes = list(result.get("notes") or [])
            phase_offset = result.get("phase_offset_days")
            future_target = item.get("future_target_is_future")
            required_due = required_marker_due(notes)
            required_matched = required_marker_matched(result)
            min_due_met = "INSUFFICIENT_DUE_MARKERS" not in notes
            selected_by_v1 = (
                selected_offset is not None
                and phase_offset is not None
                and abs(float(selected_offset) - float(phase_offset)) < 1e-9
            )
            flattened.append(
                {
                    "run_id": run_id,
                    "arm_id": ARM_ID,
                    "control_taxonomy": CONTROL_TAXONOMY,
                    "symbol": combo["symbol"],
                    "canonical_anchor_ts_utc": combo["canonical_anchor_ts_utc"],
                    "shifted_anchor_ts_utc": combo["shifted_anchor_ts_utc"],
                    "phase_class_mod_21_days": combo["phase_class_mod_21_days"],
                    "anchor_displacement_days": combo["anchor_displacement_days"],
                    "availability_status": "OK",
                    "source_jsonl_path": source_jsonl_path,
                    "source_jsonl_row_number": source_row_number,
                    "source_jsonl_sha256": source_jsonl_sha256,
                    "checkpoint_ratio": row.get("checkpoint_ratio"),
                    "selected_partial_offset_days": selected_offset,
                    "as_of_ts_utc": result.get("as_of_ts_utc"),
                    "phase_offset_days": phase_offset,
                    "future_target_is_future": future_target,
                    "partial_match_score": result.get("partial_match_score"),
                    "ranking_score": item.get("ranking_score"),
                    "required_ratio": result.get("required_ratio"),
                    "required_marker_due": required_due,
                    "required_marker_matched": required_matched,
                    "due_marker_count": result.get("due_marker_count"),
                    "observed_marker_count": result.get("observed_marker_count"),
                    "min_due_markers_met": min_due_met,
                    "structurally_eligible": structurally_eligible(
                        future_target_is_future=future_target,
                        required_due=required_due,
                        required_matched=required_matched,
                        min_due_met=min_due_met,
                    ),
                    "score_zero_reason": json.dumps(
                        score_zero_reason(notes, required_matched=required_matched),
                        separators=(",", ":"),
                    ),
                    "notes_json": json.dumps(notes, separators=(",", ":")),
                    "selected_by_v1": selected_by_v1,
                }
            )
    return flattened


def raw_csv_as_of_close(raw_csv_path: Path) -> dict[float, float | None]:
    result: dict[float, float | None] = {}
    with raw_csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("status") != "OK":
                continue
            checkpoint_raw = row.get("checkpoint_ratio")
            if checkpoint_raw in (None, ""):
                continue
            as_of_close_raw = row.get("as_of_close", "")
            result[float(checkpoint_raw)] = (
                float(as_of_close_raw) if as_of_close_raw not in ("", None) else None
            )
    return result


def selected_target_ts(row: dict[str, Any]) -> datetime | None:
    selected_offset = row.get("selected_partial_offset_days")
    if selected_offset is None:
        return None
    for item in row.get("all_partial_offsets", []):
        result = item.get("result", {})
        phase_offset = result.get("phase_offset_days")
        if phase_offset is not None and abs(float(phase_offset) - float(selected_offset)) < 1e-9:
            target_raw = item.get("future_target_expected_ts_utc")
            return parse_dt(target_raw) if target_raw else None
    return None


def compute_sidecar_metrics(
    candles: list[Candle],
    *,
    as_of_ts: datetime,
    target_ts: datetime,
    as_of_close: float | None,
) -> dict[str, Any]:
    if as_of_close is None or as_of_close == 0:
        return {
            "mfe_from_high_pct": None,
            "mae_from_low_pct": None,
            "close_to_close_1000_pct": None,
            "time_to_window_high_bars": None,
            "sidecar_status": "NO_AS_OF_CLOSE",
        }
    window = sorted(
        (candle for candle in candles if as_of_ts <= candle.ts <= target_ts),
        key=lambda candle: candle.ts,
    )
    if not window:
        return {
            "mfe_from_high_pct": None,
            "mae_from_low_pct": None,
            "close_to_close_1000_pct": None,
            "time_to_window_high_bars": None,
            "sidecar_status": "NO_CANDLE_WINDOW_DATA",
        }
    high_index, high_candle = max(enumerate(window), key=lambda pair: pair[1].high)
    low_candle = min(window, key=lambda candle: candle.low)
    target_close_candle = window[-1]
    return {
        "mfe_from_high_pct": round(((high_candle.high / as_of_close) - 1.0) * 100.0, 4),
        "mae_from_low_pct": round(((low_candle.low / as_of_close) - 1.0) * 100.0, 4),
        "close_to_close_1000_pct": round(
            ((target_close_candle.close / as_of_close) - 1.0) * 100.0, 4
        ),
        "time_to_window_high_bars": high_index,
        "sidecar_status": "OK",
    }


def load_bounded_candles(
    *,
    symbol: str,
    venue: str,
    interval_code: str,
    start: datetime,
    end: datetime,
    candle_csv: str | None,
) -> list[Candle]:
    if candle_csv:
        return [candle for candle in load_candle_csv(candle_csv) if start <= candle.ts <= end]
    return load_candle_db(symbol, None, venue, interval_code, start, end)


def build_sidecar_rows(
    rows: list[dict[str, Any]],
    *,
    run_id: str,
    combo: dict[str, Any],
    raw_csv_path: Path,
    candles: list[Candle] | None,
) -> list[dict[str, Any]]:
    as_of_close_by_checkpoint = raw_csv_as_of_close(raw_csv_path)
    out: list[dict[str, Any]] = []
    for row in rows:
        if row.get("status") != "OK":
            continue
        checkpoint = row.get("checkpoint_ratio")
        as_of_ts = (
            parse_dt(row["all_partial_offsets"][0]["result"]["as_of_ts_utc"])
            if row.get("all_partial_offsets")
            else None
        )
        target_ts = selected_target_ts(row)
        as_of_close = (
            as_of_close_by_checkpoint.get(float(checkpoint)) if checkpoint is not None else None
        )

        if candles is None:
            metrics = {
                "mfe_from_high_pct": None,
                "mae_from_low_pct": None,
                "close_to_close_1000_pct": None,
                "time_to_window_high_bars": None,
                "sidecar_status": "NO_CANDLE_SOURCE_CONFIGURED",
            }
        elif as_of_ts is None or target_ts is None:
            metrics = {
                "mfe_from_high_pct": None,
                "mae_from_low_pct": None,
                "close_to_close_1000_pct": None,
                "time_to_window_high_bars": None,
                "sidecar_status": "NO_TARGET_WINDOW",
            }
        else:
            metrics = compute_sidecar_metrics(
                candles, as_of_ts=as_of_ts, target_ts=target_ts, as_of_close=as_of_close
            )

        out.append(
            {
                "run_id": run_id,
                "arm_id": ARM_ID,
                "symbol": combo["symbol"],
                "canonical_anchor_ts_utc": combo["canonical_anchor_ts_utc"],
                "shifted_anchor_ts_utc": combo["shifted_anchor_ts_utc"],
                "phase_class_mod_21_days": combo["phase_class_mod_21_days"],
                "anchor_displacement_days": combo["anchor_displacement_days"],
                "checkpoint_ratio": checkpoint,
                "as_of_ts_utc": iso(as_of_ts) if as_of_ts else "",
                "target_ts_utc": iso(target_ts) if target_ts else "",
                "as_of_close": as_of_close,
                **metrics,
            }
        )
    return out


def build_per_symbol_summary(
    *,
    run_id: str,
    symbols: list[str],
    control_rows: list[ControlMetadataRow],
    flattened_rows: list[dict[str, Any]],
    sidecar_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for symbol in symbols:
        symbol_controls = [row for row in control_rows if row.symbol == symbol]
        ok_controls = [row for row in symbol_controls if row.availability_status == "OK"]
        symbol_flattened = [row for row in flattened_rows if row["symbol"] == symbol]
        selected_flattened = [row for row in symbol_flattened if row["selected_by_v1"]]
        selected_keys = {
            (row["shifted_anchor_ts_utc"], row["checkpoint_ratio"]) for row in selected_flattened
        }
        symbol_sidecar_selected = [
            row
            for row in sidecar_rows
            if row["symbol"] == symbol
            and (row["shifted_anchor_ts_utc"], row["checkpoint_ratio"]) in selected_keys
            and row["close_to_close_1000_pct"] is not None
        ]
        scores = [
            row["partial_match_score"]
            for row in selected_flattened
            if row["partial_match_score"] is not None
        ]
        close_to_close_values = [row["close_to_close_1000_pct"] for row in symbol_sidecar_selected]
        out.append(
            {
                "run_id": run_id,
                "symbol": symbol,
                "combo_count": len(symbol_controls),
                "ok_combo_count": len(ok_controls),
                "data_unavailable_combo_count": len(symbol_controls) - len(ok_controls),
                "flattened_row_count": len(symbol_flattened),
                "selected_row_count": len(selected_flattened),
                "mean_selected_partial_match_score": (
                    round(sum(scores) / len(scores), 6) if scores else None
                ),
                "mean_selected_close_to_close_1000_pct": (
                    round(sum(close_to_close_values) / len(close_to_close_values), 6)
                    if close_to_close_values
                    else None
                ),
            }
        )
    return out


def cluster_bootstrap_mean_ci(
    values_by_cluster: dict[str, list[float]],
    *,
    num_resamples: int,
    seed: int,
) -> tuple[float, float, float]:
    cluster_means = [
        sum(values) / len(values) for values in values_by_cluster.values() if values
    ]
    if not cluster_means:
        return 0.0, 0.0, 0.0
    rng = random.Random(seed)
    resample_means = []
    for _ in range(num_resamples):
        sample = [rng.choice(cluster_means) for _ in cluster_means]
        resample_means.append(sum(sample) / len(sample))
    resample_means.sort()
    n = len(resample_means)
    low_index = max(0, int(round(0.05 * (n - 1))))
    high_index = min(n - 1, int(round(0.95 * (n - 1))))
    return sum(resample_means) / n, resample_means[low_index], resample_means[high_index]


def build_anchor_cluster_uncertainty(
    *,
    run_id: str,
    symbols: list[str],
    flattened_rows: list[dict[str, Any]],
    sidecar_rows: list[dict[str, Any]],
    num_resamples: int,
    seed: int,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    selected_lookup = {
        (row["symbol"], row["shifted_anchor_ts_utc"], row["checkpoint_ratio"])
        for row in flattened_rows
        if row["selected_by_v1"]
    }
    for symbol in symbols:
        clusters: dict[str, list[float]] = {}
        for row in sidecar_rows:
            if row["symbol"] != symbol:
                continue
            key = (row["symbol"], row["shifted_anchor_ts_utc"], row["checkpoint_ratio"])
            if key not in selected_lookup or row["close_to_close_1000_pct"] is None:
                continue
            clusters.setdefault(row["canonical_anchor_ts_utc"], []).append(
                row["close_to_close_1000_pct"]
            )

        if not clusters:
            out.append(
                {
                    "run_id": run_id,
                    "symbol": symbol,
                    "metric": "close_to_close_1000_pct",
                    "cluster_count": 0,
                    "observation_count": 0,
                    "pooled_mean": None,
                    "bootstrap_mean": None,
                    "bootstrap_ci_low_90": None,
                    "bootstrap_ci_high_90": None,
                    "bootstrap_resamples": num_resamples,
                    "bootstrap_seed": seed,
                    "note": NOT_INDEPENDENT_SAMPLES_NOTE,
                }
            )
            continue

        pooled_values = [value for values in clusters.values() for value in values]
        bootstrap_mean, ci_low, ci_high = cluster_bootstrap_mean_ci(
            clusters, num_resamples=num_resamples, seed=seed
        )
        out.append(
            {
                "run_id": run_id,
                "symbol": symbol,
                "metric": "close_to_close_1000_pct",
                "cluster_count": len(clusters),
                "observation_count": len(pooled_values),
                "pooled_mean": round(sum(pooled_values) / len(pooled_values), 6),
                "bootstrap_mean": round(bootstrap_mean, 6),
                "bootstrap_ci_low_90": round(ci_low, 6),
                "bootstrap_ci_high_90": round(ci_high, 6),
                "bootstrap_resamples": num_resamples,
                "bootstrap_seed": seed,
                "note": NOT_INDEPENDENT_SAMPLES_NOTE,
            }
        )
    return out


def write_csv_rows(path: Path, fieldnames: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
        writer.writeheader()
        writer.writerows(rows)


def write_control_metadata_csv(path: Path, rows: list[ControlMetadataRow]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(CONTROL_METADATA_FIELDNAMES))
        writer.writeheader()
        for row in rows:
            writer.writerow({field: getattr(row, field) for field in CONTROL_METADATA_FIELDNAMES})


def run_v1_for_combo(
    *,
    repo_root: Path,
    raw_dir: Path,
    logs_dir: Path,
    symbol: str,
    shifted_anchor_ts_utc: str,
) -> tuple[list[str], int]:
    command_line = [
        sys.executable,
        "-m",
        V1_MODULE,
        "--symbols",
        symbol,
        "--anchors",
        shifted_anchor_ts_utc,
        "--out-dir",
        str(raw_dir),
    ]
    stdout_path = logs_dir / "v1_stdout.txt"
    stderr_path = logs_dir / "v1_stderr.txt"
    with stdout_path.open("w", encoding="utf-8") as stdout_handle, stderr_path.open(
        "w", encoding="utf-8"
    ) as stderr_handle:
        completed = subprocess.run(
            command_line,
            cwd=str(repo_root),
            stdout=stdout_handle,
            stderr=stderr_handle,
            check=False,
        )
    return command_line, completed.returncode


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run Arm B.2a: legacy V1 integer-day phase-null controls "
            "(matched phase-control research, not independent samples)."
        )
    )
    parser.add_argument("--symbols", required=True, help="Comma-separated symbols.")
    parser.add_argument(
        "--canonical-anchors",
        required=True,
        help="Comma-separated canonical anchor timestamps.",
    )
    parser.add_argument(
        "--candle-csv",
        default=None,
        help=(
            "Optional bounded candle CSV for deterministic sidecar metrics. "
            "When omitted, sidecar metrics use a bounded read-only DB query."
        ),
    )
    parser.add_argument("--out-dir", default=DEFAULT_OUT_BASE)
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--interval", dest="interval_code", default=DEFAULT_INTERVAL_CODE)
    parser.add_argument("--bootstrap-resamples", type=int, default=DEFAULT_BOOTSTRAP_RESAMPLES)
    parser.add_argument("--bootstrap-seed", type=int, default=DEFAULT_BOOTSTRAP_SEED)
    parser.add_argument(
        "--skip-sidecar-candles",
        action="store_true",
        help=(
            "Skip bounded candle queries for sidecar metrics. Control metadata and "
            "flattened output are unaffected."
        ),
    )
    args = parser.parse_args()

    try:
        validate_registry(REGISTRY)
        symbols = [value.strip() for value in args.symbols.split(",") if value.strip()]
        if not symbols:
            raise ValueError("--symbols must contain at least one symbol")
        canonical_anchor_strings = [
            value.strip() for value in args.canonical_anchors.split(",") if value.strip()
        ]
        if not canonical_anchor_strings:
            raise ValueError("--canonical-anchors must contain at least one anchor")
        canonical_anchors = [parse_dt(value) for value in canonical_anchor_strings]
    except ValueError as exc:
        print(f"FAILED {exc}", flush=True)
        return 1

    repo_root = find_repo_root()
    try:
        orchestration_runner_commit = resolve_git_commit(repo_root)
        dependency_hashes = verify_dependency_closure_integrity(repo_root)
    except RuntimeError as exc:
        print(f"FAILED {exc}", flush=True)
        return 1

    source_commit = orchestration_runner_commit
    started_at = utc_now()
    run_id = f"b2a_{started_at.strftime('%Y%m%dT%H%M%SZ')}"
    run_dir = Path(args.out_dir) / run_id
    raw_base_dir = run_dir / "raw"
    derived_dir = run_dir / "derived"
    control_dir = run_dir / "control_metadata"
    manifest_dir = run_dir / "manifest"
    logs_base_dir = run_dir / "logs"
    for path in (raw_base_dir, derived_dir, control_dir, manifest_dir, logs_base_dir):
        path.mkdir(parents=True, exist_ok=True)

    combos = build_combos(symbols, canonical_anchors)
    print(
        f"STARTED runner=breathline_v1_recovery_orchestration_b2a_v1 arm_id={ARM_ID} "
        f"symbols={len(symbols)} canonical_anchors={len(canonical_anchors)} "
        f"shifts={len(REGISTRY)} combos={len(combos)}",
        flush=True,
    )

    control_rows: list[ControlMetadataRow] = []
    flattened_rows: list[dict[str, Any]] = []
    sidecar_rows: list[dict[str, Any]] = []
    combo_manifest_entries: list[dict[str, Any]] = []

    for index, combo in enumerate(combos, start=1):
        cid = combo_id(combo)
        raw_dir = raw_base_dir / cid
        logs_dir = logs_base_dir / cid
        raw_dir.mkdir(parents=True, exist_ok=True)
        logs_dir.mkdir(parents=True, exist_ok=True)

        print(
            f"PHASE combo_start index={index}/{len(combos)} symbol={combo['symbol']} "
            f"shift={combo['shift']:+d} canonical_anchor={combo['canonical_anchor_ts_utc']} "
            f"shifted_anchor={combo['shifted_anchor_ts_utc']}",
            flush=True,
        )

        command_line, exit_code = run_v1_for_combo(
            repo_root=repo_root,
            raw_dir=raw_dir,
            logs_dir=logs_dir,
            symbol=combo["symbol"],
            shifted_anchor_ts_utc=combo["shifted_anchor_ts_utc"],
        )

        if exit_code != 0:
            print(f"FAILED combo={cid} subprocess_exit_code={exit_code}", flush=True)
            return 1

        try:
            raw_csv_path, raw_jsonl_path = locate_v1_artifacts(raw_dir)
            raw_jsonl_sha256 = sha256_file(raw_jsonl_path)
            rows = parse_jsonl(raw_jsonl_path)
        except RuntimeError as exc:
            print(f"FAILED combo={cid} {exc}", flush=True)
            return 1

        availability_status, ok_row_count, unavailable_row_count = combo_availability(rows)

        control_rows.append(
            ControlMetadataRow(
                run_id=run_id,
                arm_id=ARM_ID,
                control_taxonomy=CONTROL_TAXONOMY,
                symbol=combo["symbol"],
                canonical_anchor_ts_utc=combo["canonical_anchor_ts_utc"],
                shifted_anchor_ts_utc=combo["shifted_anchor_ts_utc"],
                phase_class_mod_21_days=combo["phase_class_mod_21_days"],
                anchor_displacement_days=combo["anchor_displacement_days"],
                availability_status=availability_status,
                source_commit=source_commit,
                raw_csv_path=str(raw_csv_path),
                raw_jsonl_path=str(raw_jsonl_path),
                raw_jsonl_sha256=raw_jsonl_sha256,
                ok_row_count=ok_row_count,
                data_unavailable_row_count=unavailable_row_count,
            )
        )

        combo_manifest_entries.append(
            {
                "combo_id": cid,
                "symbol": combo["symbol"],
                "shift": combo["shift"],
                "canonical_anchor_ts_utc": combo["canonical_anchor_ts_utc"],
                "shifted_anchor_ts_utc": combo["shifted_anchor_ts_utc"],
                "availability_status": availability_status,
                "command_line": command_line,
                "raw_csv_path": str(raw_csv_path),
                "raw_csv_sha256": sha256_file(raw_csv_path),
                "raw_jsonl_path": str(raw_jsonl_path),
                "raw_jsonl_sha256": raw_jsonl_sha256,
                "subprocess_exit_code": exit_code,
            }
        )

        if availability_status != "OK":
            print(
                f"DATA_UNAVAILABLE combo={cid} unavailable_rows={unavailable_row_count}",
                flush=True,
            )
            continue

        combo_flattened = flatten_combo_rows(
            rows,
            run_id=run_id,
            combo=combo,
            source_jsonl_path=str(raw_jsonl_path),
            source_jsonl_sha256=raw_jsonl_sha256,
        )
        flattened_rows.extend(combo_flattened)

        candles: list[Candle] | None = None
        if not args.skip_sidecar_candles:
            as_of_targets: list[datetime] = []
            for row in rows:
                if row.get("status") != "OK":
                    continue
                if row.get("all_partial_offsets"):
                    as_of_targets.append(
                        parse_dt(row["all_partial_offsets"][0]["result"]["as_of_ts_utc"])
                    )
                target = selected_target_ts(row)
                if target is not None:
                    as_of_targets.append(target)
            if as_of_targets:
                try:
                    candles = load_bounded_candles(
                        symbol=combo["symbol"],
                        venue=args.venue,
                        interval_code=args.interval_code,
                        start=min(as_of_targets),
                        end=max(as_of_targets),
                        candle_csv=args.candle_csv,
                    )
                except Exception as exc:
                    print(f"SIDECAR_CANDLE_QUERY_FAILED combo={cid} error={exc}", flush=True)
                    candles = None

        combo_sidecar = build_sidecar_rows(
            rows,
            run_id=run_id,
            combo=combo,
            raw_csv_path=raw_csv_path,
            candles=candles,
        )
        sidecar_rows.extend(combo_sidecar)

        print(f"PHASE combo_end index={index}/{len(combos)} combo={cid}", flush=True)

    flattened_csv_path = derived_dir / f"breathline_v1_recovery_b2a_flattened_{run_id}.csv"
    write_csv_rows(flattened_csv_path, FLATTENED_FIELDNAMES_B2A, flattened_rows)

    sidecar_csv_path = derived_dir / f"breathline_v1_recovery_b2a_sidecar_metrics_{run_id}.csv"
    write_csv_rows(sidecar_csv_path, SIDECAR_FIELDNAMES, sidecar_rows)

    per_symbol_rows = build_per_symbol_summary(
        run_id=run_id,
        symbols=symbols,
        control_rows=control_rows,
        flattened_rows=flattened_rows,
        sidecar_rows=sidecar_rows,
    )
    per_symbol_csv_path = (
        derived_dir / f"breathline_v1_recovery_b2a_per_symbol_summary_{run_id}.csv"
    )
    write_csv_rows(per_symbol_csv_path, PER_SYMBOL_SUMMARY_FIELDNAMES, per_symbol_rows)

    anchor_cluster_rows = build_anchor_cluster_uncertainty(
        run_id=run_id,
        symbols=symbols,
        flattened_rows=flattened_rows,
        sidecar_rows=sidecar_rows,
        num_resamples=args.bootstrap_resamples,
        seed=args.bootstrap_seed,
    )
    anchor_cluster_csv_path = (
        derived_dir / f"breathline_v1_recovery_b2a_anchor_cluster_uncertainty_{run_id}.csv"
    )
    write_csv_rows(anchor_cluster_csv_path, ANCHOR_CLUSTER_FIELDNAMES, anchor_cluster_rows)

    control_csv_path = control_dir / f"breathline_v1_recovery_b2a_control_metadata_{run_id}.csv"
    write_control_metadata_csv(control_csv_path, control_rows)

    ok_combo_count = sum(1 for row in control_rows if row.availability_status == "OK")
    data_unavailable_combo_count = len(control_rows) - ok_combo_count

    manifest = {
        "run_id": run_id,
        "arm_id": ARM_ID,
        "control_taxonomy": CONTROL_TAXONOMY,
        "generated_at_utc": iso(utc_now()),
        "source_commit": source_commit,
        "orchestration_runner_commit": orchestration_runner_commit,
        "registry": list(REGISTRY),
        "symbols": symbols,
        "canonical_anchors_ts_utc": [iso(anchor) for anchor in canonical_anchors],
        "combo_count": len(combos),
        "ok_combo_count": ok_combo_count,
        "data_unavailable_combo_count": data_unavailable_combo_count,
        "combos": combo_manifest_entries,
        "dependency_closure_hashes": dependency_hashes,
        "dependency_closure_integrity_status": "PASS",
        "artifacts": {
            "flattened_csv": {
                "path": str(flattened_csv_path),
                "sha256": sha256_file(flattened_csv_path),
                "rows": len(flattened_rows),
            },
            "sidecar_metrics_csv": {
                "path": str(sidecar_csv_path),
                "sha256": sha256_file(sidecar_csv_path),
                "rows": len(sidecar_rows),
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
            "control_metadata_csv": {
                "path": str(control_csv_path),
                "sha256": sha256_file(control_csv_path),
                "rows": len(control_rows),
            },
        },
        "python_version": sys.version,
        "not_independent_samples_note": NOT_INDEPENDENT_SAMPLES_NOTE,
    }
    manifest_path = manifest_dir / f"breathline_v1_recovery_b2a_manifest_{run_id}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    print(
        f"FINISHED run_id={run_id} combos={len(combos)} ok_combos={ok_combo_count} "
        f"data_unavailable_combos={data_unavailable_combo_count} "
        f"flattened_rows={len(flattened_rows)}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
