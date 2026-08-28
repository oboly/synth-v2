from __future__ import annotations

"""Run preregistered Issue #533 Breathline harmonic-family falsification v1.

Consumes immutable #534/#417 research artifacts only. No DB, broker, account,
selection, permission, execution, order, schema, or runtime authority exists here.
"""

import argparse
import hashlib
import json
import math
import random
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable, Sequence

from src.research.breathline_harmonic_family_registry_v1 import (
    ALPHA,
    BASELINES,
    BINARY_OUTCOMES,
    CHECKPOINTS,
    DISCOVERY_FRACTION,
    DURATION_FAMILY_DAYS,
    EVENT_TIMING_OUTCOMES,
    MULTIPLE_COMPARISON_METHOD,
    NULL_PERMUTATIONS,
    PHASE_MARKERS,
    RANDOM_SEED,
    REGISTRY_NAME,
    REGISTRY_VERSION,
    SAFETY_MARKERS,
    WALK_FORWARD_MIN_PRIOR_ASSET_CYCLES,
    WALK_FORWARD_MIN_PRIOR_POOLED_CYCLES,
    registry_payload,
)


RUNNER_NAME = "breathline_harmonic_family_falsification_v1"
RUNNER_VERSION = "1.0.0"
EXPECTED_SOURCE_RUNNER = "bullish_breathline_canonical_4h_v1"
EXPECTED_SYMBOLS = ("RENDER", "TAO")
DEFAULT_OUT_ROOT = Path("data/research/breathline_harmonic_family_falsification_v1")

NODE_TS_FIELDS: dict[str, str] = {
    "first_high": "first_high_ts",
    "first_low": "first_low_ts",
    "second_high": "second_high_ts",
    "recognition": "recognition_ts",
    "ignition": "ignition_ts",
    "main_pulse": "main_pulse_ts",
    "extension": "extension_ts",
}

CHECKPOINT_CONFIRMATION_FIELDS: dict[str, str] = {
    "recognition": "recognition_confirmed_at_ts",
    "ignition": "ignition_confirmed_at_ts",
}

CHECKPOINT_PRICE_FIELDS: dict[str, str] = {
    "recognition": "recognition_price",
    "ignition": "ignition_price",
}


class InputProvenanceError(RuntimeError):
    pass


def emit(status: str, message: str, **fields: Any) -> None:
    suffix = " ".join(f"{key}={fields[key]}" for key in sorted(fields))
    print(f"{status} {message}{(' ' + suffix) if suffix else ''}", flush=True)


def utc_now() -> datetime:
    return datetime.now(UTC)


def fmt_ts(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_ts(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"invalid timestamp: {value!r}")
    dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def days_between(later: Any, earlier: Any) -> float:
    return (parse_ts(later) - parse_ts(earlier)).total_seconds() / 86400.0


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise InputProvenanceError(f"expected JSON object: {path}")
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise InputProvenanceError(f"expected object at {path}:{line_number}")
        rows.append(value)
    return rows


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def git_output(args: list[str], *, cwd: Path) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    output = completed.stdout.decode("utf-8", errors="replace").strip()
    if completed.returncode != 0 or not output:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(detail or f"git {' '.join(args)} failed")
    return output


def resolve_analysis_commit(root: Path) -> str:
    return git_output(["rev-parse", "HEAD"], cwd=root)


def _artifact_entry(asset: dict[str, Any], filename: str) -> dict[str, Any]:
    artifacts = asset.get("tracker_artifacts")
    if not isinstance(artifacts, dict):
        raise InputProvenanceError("source manifest missing tracker_artifacts")
    entry = artifacts.get(filename)
    if not isinstance(entry, dict) or entry.get("present") is not True:
        raise InputProvenanceError(f"source manifest requires present {filename}")
    expected_hash = entry.get("sha256")
    if not isinstance(expected_hash, str) or len(expected_hash) != 64:
        raise InputProvenanceError(f"source manifest invalid hash for {filename}")
    return entry


def validate_source_run(source_run_dir: Path) -> tuple[
    dict[str, Any],
    dict[str, list[dict[str, Any]]],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
]:
    manifest_path = source_run_dir / "run_manifest.json"
    if not manifest_path.is_file():
        raise InputProvenanceError(f"source run manifest missing: {manifest_path}")
    manifest = load_json(manifest_path)
    if manifest.get("runner_name") != EXPECTED_SOURCE_RUNNER:
        raise InputProvenanceError("unexpected source runner")
    if tuple(manifest.get("symbols") or ()) != EXPECTED_SYMBOLS:
        raise InputProvenanceError("source symbols do not match frozen #533 v1 scope")
    if manifest.get("research_only") is not True or manifest.get("market_only") is not True:
        raise InputProvenanceError("source run is not explicitly research-only/market-only")

    assets = manifest.get("assets")
    if not isinstance(assets, list) or len(assets) != len(EXPECTED_SYMBOLS):
        raise InputProvenanceError("source asset manifest set is invalid")
    asset_by_symbol = {
        str(asset.get("symbol") or "").upper(): asset
        for asset in assets
        if isinstance(asset, dict)
    }
    if set(asset_by_symbol) != set(EXPECTED_SYMBOLS):
        raise InputProvenanceError("source asset symbols do not match frozen scope")

    cycles_by_symbol: dict[str, list[dict[str, Any]]] = {}
    summary_by_symbol: dict[str, dict[str, Any]] = {}
    provenance_by_symbol: dict[str, dict[str, Any]] = {}
    model_versions: set[str] = set()

    for symbol in EXPECTED_SYMBOLS:
        asset = asset_by_symbol[symbol]
        tracker_dir = source_run_dir / symbol / "tracker"
        source_csv = source_run_dir / symbol / "source" / "canonical_candles.csv"
        ledger_path = tracker_dir / "cycle_ledger.jsonl"
        summary_path = tracker_dir / "summary.json"

        ledger_entry = _artifact_entry(asset, "cycle_ledger.jsonl")
        summary_entry = _artifact_entry(asset, "summary.json")

        for path, expected_hash, label in (
            (ledger_path, ledger_entry["sha256"], "cycle ledger"),
            (summary_path, summary_entry["sha256"], "tracker summary"),
            (source_csv, asset.get("source_sha256"), "source CSV"),
        ):
            if not path.is_file():
                raise InputProvenanceError(f"missing {label}: {path}")
            if sha256_file(path) != expected_hash:
                raise InputProvenanceError(f"hash mismatch for {label}: {symbol}")

        rows = load_jsonl(ledger_path)
        summary = load_json(summary_path)
        if int(summary.get("cycle_count") or -1) != len(rows):
            raise InputProvenanceError(f"cycle count mismatch: {symbol}")
        if int(asset.get("tracker_summary", {}).get("cycle_count") or -1) != len(rows):
            raise InputProvenanceError(f"manifest tracker cycle count mismatch: {symbol}")
        model_version = str(summary.get("model_version") or "")
        if not model_version:
            raise InputProvenanceError(f"tracker model version missing: {symbol}")
        model_versions.add(model_version)

        seen: set[str] = set()
        for row in rows:
            cid = str(row.get("cycle_id") or "")
            if not cid or cid in seen:
                raise InputProvenanceError(f"duplicate/missing cycle_id: {symbol}")
            seen.add(cid)
            if str(row.get("symbol") or "").upper() != symbol:
                raise InputProvenanceError(f"cycle symbol mismatch: {symbol}")
            duration = float(row.get("observed_cycle_length_days"))
            if not math.isfinite(duration) or duration <= 0:
                raise InputProvenanceError(f"invalid observed duration: {symbol}:{cid}")
            for required_ts in ("start_ts", "end_ts", "recognition_ts", "outcome_as_of_ts"):
                parse_ts(row.get(required_ts))

        cycles_by_symbol[symbol] = sorted(rows, key=lambda row: parse_ts(row["start_ts"]))
        summary_by_symbol[symbol] = summary
        provenance_by_symbol[symbol] = {
            "asset_id": asset.get("asset_id"),
            "source_csv": str(source_csv),
            "source_csv_sha256": sha256_file(source_csv),
            "cycle_ledger": str(ledger_path),
            "cycle_ledger_sha256": sha256_file(ledger_path),
            "summary": str(summary_path),
            "summary_sha256": sha256_file(summary_path),
            "source_row_count": asset.get("source_row_count"),
            "first_source_ts": asset.get("first_source_ts"),
            "last_source_ts": asset.get("last_source_ts"),
            "source_gap_count": asset.get("source_gap_count"),
            "tracker_model_version": model_version,
        }

    if len(model_versions) != 1:
        raise InputProvenanceError("source assets use different tracker model versions")
    return manifest, cycles_by_symbol, summary_by_symbol, provenance_by_symbol


def split_map(cycles_by_symbol: dict[str, list[dict[str, Any]]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for symbol in EXPECTED_SYMBOLS:
        rows = cycles_by_symbol[symbol]
        if len(rows) <= 1:
            split = len(rows)
        else:
            split = max(1, min(len(rows) - 1, int(len(rows) * DISCOVERY_FRACTION)))
        for index, row in enumerate(rows):
            result[str(row["cycle_id"])] = "discovery" if index < split else "holdout"
    return result


def all_cycles(cycles_by_symbol: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    rows = [row for symbol in EXPECTED_SYMBOLS for row in cycles_by_symbol[symbol]]
    return sorted(rows, key=lambda row: (parse_ts(row["start_ts"]), str(row["symbol"])))


def populations(rows: Sequence[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result = {symbol: [row for row in rows if row["symbol"] == symbol] for symbol in EXPECTED_SYMBOLS}
    result["POOLED"] = list(rows)
    return result


def _percentile(values: Sequence[float], q: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    fraction = position - low
    return ordered[low] + (ordered[high] - ordered[low]) * fraction


def distribution(values: Iterable[Any]) -> dict[str, Any]:
    finite = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    if not finite:
        return {
            "count": 0,
            "min": None,
            "p25": None,
            "median": None,
            "p75": None,
            "p90": None,
            "max": None,
            "mean": None,
        }
    return {
        "count": len(finite),
        "min": min(finite),
        "p25": _percentile(finite, 0.25),
        "median": _percentile(finite, 0.50),
        "p75": _percentile(finite, 0.75),
        "p90": _percentile(finite, 0.90),
        "max": max(finite),
        "mean": mean(finite),
    }


def holm_bonferroni(p_values: dict[str, float | None], *, alpha: float = ALPHA) -> dict[str, dict[str, Any]]:
    valid = [(key, float(value)) for key, value in p_values.items() if value is not None]
    valid.sort(key=lambda item: (item[1], item[0]))
    m = len(valid)
    adjusted: dict[str, float] = {}
    running = 0.0
    for index, (key, raw) in enumerate(valid):
        candidate = min(1.0, (m - index) * raw)
        running = max(running, candidate)
        adjusted[key] = running
    result: dict[str, dict[str, Any]] = {}
    for key in p_values:
        raw = p_values[key]
        adj = adjusted.get(key)
        result[key] = {
            "p_value_raw": raw,
            "p_value_adjusted": adj,
            "reject_at_alpha": bool(adj is not None and adj <= alpha),
            "method": MULTIPLE_COMPARISON_METHOD,
            "alpha": alpha,
        }
    return result


def tie_aware_auc(scores: Sequence[float], labels: Sequence[bool]) -> float | None:
    if len(scores) != len(labels):
        raise ValueError("scores/labels length mismatch")
    positives = [float(score) for score, label in zip(scores, labels) if label]
    negatives = [float(score) for score, label in zip(scores, labels) if not label]
    if not positives or not negatives:
        return None
    wins = 0.0
    for positive in positives:
        for negative in negatives:
            if positive > negative:
                wins += 1.0
            elif positive == negative:
                wins += 0.5
    return wins / (len(positives) * len(negatives))


def permutation_p_value(observed: float | None, null_values: Sequence[float], *, higher_is_better: bool) -> float | None:
    if observed is None or not null_values:
        return None
    if higher_is_better:
        favorable = sum(value >= observed for value in null_values)
    else:
        favorable = sum(value <= observed for value in null_values)
    return (1.0 + favorable) / (len(null_values) + 1.0)


def candidate_duration_residuals(observed_days: float) -> list[dict[str, float]]:
    result: list[dict[str, float]] = []
    for candidate in DURATION_FAMILY_DAYS:
        signed = observed_days - candidate
        result.append(
            {
                "candidate_duration_days": candidate,
                "duration_error_days": signed,
                "absolute_duration_error_days": abs(signed),
                "relative_duration_error": signed / candidate,
                "absolute_relative_duration_error": abs(signed) / candidate,
            }
        )
    return result


def build_lane_a_rows(
    cycles_by_symbol: dict[str, list[dict[str, Any]]],
    splits: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    duration_rows: list[dict[str, Any]] = []
    phase_rows: list[dict[str, Any]] = []
    for cycle in all_cycles(cycles_by_symbol):
        duration = float(cycle["observed_cycle_length_days"])
        residuals = candidate_duration_residuals(duration)
        nearest = min(residuals, key=lambda row: (row["absolute_duration_error_days"], row["candidate_duration_days"]))
        fixed21 = next(row for row in residuals if row["candidate_duration_days"] == 21.0)
        base = {
            "cycle_id": cycle["cycle_id"],
            "symbol": cycle["symbol"],
            "split": splits[str(cycle["cycle_id"])],
            "cycle_status": cycle.get("cycle_status"),
            "start_ts": cycle.get("start_ts"),
            "end_ts": cycle.get("end_ts"),
            "observed_cycle_length_days": duration,
            "reset_reason": cycle.get("reset_reason"),
            "phase_shift_reason": cycle.get("phase_shift_reason"),
        }
        duration_rows.append(
            {
                **base,
                "candidate_residuals": residuals,
                "nearest_candidate_duration_days": nearest["candidate_duration_days"],
                "nearest_candidate_absolute_error_days": nearest["absolute_duration_error_days"],
                "nearest_candidate_relative_error": nearest["relative_duration_error"],
                "nearest_candidate_absolute_relative_error": nearest["absolute_relative_duration_error"],
                "fixed_21d_absolute_error_days": fixed21["absolute_duration_error_days"],
                "fixed_21d_relative_error": fixed21["relative_duration_error"],
                "fixed_21d_absolute_relative_error": fixed21["absolute_relative_duration_error"],
            }
        )

        start_ts = parse_ts(cycle["start_ts"])
        for node, ratio in PHASE_MARKERS:
            field = NODE_TS_FIELDS[node]
            observed_ts_raw = cycle.get(field)
            phase_row: dict[str, Any] = {
                **base,
                "node": node,
                "ratio": ratio,
                "observed_node_ts": observed_ts_raw,
                "present": observed_ts_raw is not None,
                "expected_elapsed_days": duration * ratio,
                "observed_elapsed_days": None,
                "node_timing_residual_days": None,
                "observed_phase_position": None,
                "phase_position_residual": None,
            }
            if observed_ts_raw is not None:
                observed_elapsed = (parse_ts(observed_ts_raw) - start_ts).total_seconds() / 86400.0
                observed_phase = observed_elapsed / duration
                phase_row.update(
                    {
                        "observed_elapsed_days": observed_elapsed,
                        "node_timing_residual_days": observed_elapsed - duration * ratio,
                        "observed_phase_position": observed_phase,
                        "phase_position_residual": observed_phase - ratio,
                    }
                )
            phase_rows.append(phase_row)
    return duration_rows, phase_rows


def _phase_null_tests(
    phase_rows: list[dict[str, Any]],
    *,
    permutations: int,
) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for population, rows in populations(phase_rows).items():
        present = [row for row in rows if row["present"]]
        by_node = {node: [row for row in present if row["node"] == node] for node, _ in PHASE_MARKERS}
        actual: dict[str, float | None] = {
            node: (
                mean(abs(float(row["phase_position_residual"])) for row in node_rows)
                if node_rows
                else None
            )
            for node, node_rows in by_node.items()
        }
        null_by_node: dict[str, list[float]] = {node: [] for node, _ in PHASE_MARKERS}
        cycle_ids = sorted({str(row["cycle_id"]) for row in present})
        for permutation_index in range(permutations):
            rng = random.Random(f"{RANDOM_SEED}:{population}:lane_a_phase:{permutation_index}")
            shift_by_cycle = {cycle_id: rng.random() for cycle_id in cycle_ids}
            for node, ratio in PHASE_MARKERS:
                node_rows = by_node[node]
                if not node_rows:
                    continue
                null_error = mean(
                    abs(((float(row["observed_phase_position"]) + shift_by_cycle[str(row["cycle_id"])]) % 1.0) - ratio)
                    for row in node_rows
                )
                null_by_node[node].append(null_error)
        raw_p = {
            node: permutation_p_value(actual[node], null_by_node[node], higher_is_better=False)
            for node, _ in PHASE_MARKERS
        }
        corrected = holm_bonferroni(raw_p)
        output[population] = {
            node: {
                "present_count": len(by_node[node]),
                "mean_absolute_phase_position_residual": actual[node],
                **corrected[node],
            }
            for node, _ in PHASE_MARKERS
        }
    return output


def summarize_lane_a(
    duration_rows: list[dict[str, Any]],
    phase_rows: list[dict[str, Any]],
    *,
    permutations: int,
) -> dict[str, Any]:
    phase_tests = _phase_null_tests(phase_rows, permutations=permutations)
    result: dict[str, Any] = {
        "claim_type": "retrospective_descriptive_only",
        "registry_version": REGISTRY_VERSION,
        "permutations": permutations,
        "populations": {},
    }
    for population, rows in populations(duration_rows).items():
        phase_population_rows = populations(phase_rows)[population]
        candidate_summary: dict[str, Any] = {}
        for candidate in DURATION_FAMILY_DAYS:
            values: list[dict[str, float]] = []
            for row in rows:
                values.append(next(item for item in row["candidate_residuals"] if item["candidate_duration_days"] == candidate))
            candidate_summary[str(candidate)] = {
                "absolute_duration_error_days": distribution(item["absolute_duration_error_days"] for item in values),
                "absolute_relative_duration_error": distribution(item["absolute_relative_duration_error"] for item in values),
            }
        result["populations"][population] = {
            "sample_count": len(rows),
            "cycle_status_counts": dict(sorted(Counter(str(row.get("cycle_status")) for row in rows).items())),
            "observed_cycle_length_days": distribution(row["observed_cycle_length_days"] for row in rows),
            "nearest_candidate_counts": dict(sorted(Counter(str(row["nearest_candidate_duration_days"]) for row in rows).items(), key=lambda item: float(item[0]))),
            "nearest_candidate_absolute_error_days": distribution(row["nearest_candidate_absolute_error_days"] for row in rows),
            "nearest_candidate_absolute_relative_error": distribution(row["nearest_candidate_absolute_relative_error"] for row in rows),
            "fixed_21d_absolute_error_days": distribution(row["fixed_21d_absolute_error_days"] for row in rows),
            "fixed_21d_absolute_relative_error": distribution(row["fixed_21d_absolute_relative_error"] for row in rows),
            "candidate_duration_fit": candidate_summary,
            "reset_frequency": (sum(row.get("reset_reason") is not None for row in rows) / len(rows)) if rows else None,
            "phase_shift_frequency": (sum(row.get("phase_shift_reason") is not None for row in rows) / len(rows)) if rows else None,
            "phase_markers": {
                node: {
                    "timing_residual_days": distribution(
                        row["node_timing_residual_days"]
                        for row in phase_population_rows
                        if row["node"] == node
                    ),
                    "phase_position_residual": distribution(
                        row["phase_position_residual"]
                        for row in phase_population_rows
                        if row["node"] == node
                    ),
                    **phase_tests[population][node],
                }
                for node, _ in PHASE_MARKERS
            },
        }
    return result


def prior_completed_durations(
    all_rows: Sequence[dict[str, Any]],
    *,
    feature_as_of_ts: datetime,
    symbol: str | None,
) -> list[float]:
    values: list[float] = []
    for cycle in all_rows:
        if symbol is not None and cycle["symbol"] != symbol:
            continue
        if parse_ts(cycle["outcome_as_of_ts"]) < feature_as_of_ts:
            values.append(float(cycle["observed_cycle_length_days"]))
    return values


def _tracker_compatible_market_metrics(cycle: dict[str, Any], checkpoint: str) -> dict[str, Any]:
    checkpoint_price_raw = cycle.get(CHECKPOINT_PRICE_FIELDS[checkpoint])
    checkpoint_ts_raw = cycle.get(NODE_TS_FIELDS[checkpoint])
    if checkpoint_price_raw is None or checkpoint_ts_raw is None:
        return {
            "mfe_pct": None,
            "mae_pct": None,
            "time_to_main_pulse_days": None,
            "time_to_extension_days": None,
        }
    checkpoint_price = float(checkpoint_price_raw)
    future_prices = [
        float(value)
        for value in (cycle.get("main_pulse_price"), cycle.get("extension_price"))
        if value is not None
    ]
    mfe = None if not future_prices else (max(future_prices) / checkpoint_price - 1.0) * 100.0
    downside_prices = [
        float(value)
        for value in (cycle.get("recognition_price"), cycle.get("first_low_price"))
        if value is not None
    ]
    mae = None if not downside_prices else (min(downside_prices) / checkpoint_price - 1.0) * 100.0
    time_to_main = (
        None
        if cycle.get("main_pulse_ts") is None
        else days_between(cycle["main_pulse_ts"], checkpoint_ts_raw)
    )
    time_to_extension = (
        None
        if cycle.get("extension_ts") is None
        else days_between(cycle["extension_ts"], checkpoint_ts_raw)
    )
    return {
        "mfe_pct": mfe,
        "mae_pct": mae,
        "time_to_main_pulse_days": time_to_main,
        "time_to_extension_days": time_to_extension,
    }


def build_lane_b_rows(
    cycles_by_symbol: dict[str, list[dict[str, Any]]],
    splits: dict[str, str],
) -> list[dict[str, Any]]:
    source_rows = all_cycles(cycles_by_symbol)
    output: list[dict[str, Any]] = []
    checkpoint_ratio = dict(CHECKPOINTS)
    event_ratio = dict(EVENT_TIMING_OUTCOMES)

    for cycle in source_rows:
        start = parse_ts(cycle["start_ts"])
        observed_duration = float(cycle["observed_cycle_length_days"])
        symbol = str(cycle["symbol"])
        for checkpoint, ratio in CHECKPOINTS:
            checkpoint_ts_raw = cycle.get(NODE_TS_FIELDS[checkpoint])
            feature_ts_raw = cycle.get(CHECKPOINT_CONFIRMATION_FIELDS[checkpoint])
            if checkpoint_ts_raw is None or feature_ts_raw is None:
                continue
            checkpoint_ts = parse_ts(checkpoint_ts_raw)
            feature_ts = parse_ts(feature_ts_raw)
            elapsed = (checkpoint_ts - start).total_seconds() / 86400.0

            candidate_errors = {
                str(candidate): abs(elapsed - candidate * ratio)
                for candidate in DURATION_FAMILY_DAYS
            }
            selected = min(
                DURATION_FAMILY_DAYS,
                key=lambda candidate: (candidate_errors[str(candidate)], candidate),
            )
            asset_history = prior_completed_durations(
                source_rows,
                feature_as_of_ts=feature_ts,
                symbol=symbol,
            )
            pooled_history = prior_completed_durations(
                source_rows,
                feature_as_of_ts=feature_ts,
                symbol=None,
            )
            asset_median = (
                float(median(asset_history))
                if len(asset_history) >= WALK_FORWARD_MIN_PRIOR_ASSET_CYCLES
                else None
            )
            pooled_median = (
                float(median(pooled_history))
                if len(pooled_history) >= WALK_FORWARD_MIN_PRIOR_POOLED_CYCLES
                else None
            )
            predictors: dict[str, float | None] = {
                "family_checkpoint_selector": selected,
                "fixed_21d": 21.0,
                "asset_prior_median_completed_duration": asset_median,
                "pooled_prior_median_completed_duration": pooled_median,
            }

            duration_predictions: dict[str, Any] = {}
            event_timing_predictions: dict[str, Any] = {}
            for predictor, predicted_duration in predictors.items():
                duration_predictions[predictor] = {
                    "predicted_duration_days": predicted_duration,
                    "absolute_error_days": (
                        None if predicted_duration is None else abs(observed_duration - predicted_duration)
                    ),
                    "relative_error": (
                        None if predicted_duration is None else (observed_duration - predicted_duration) / predicted_duration
                    ),
                    "absolute_relative_error": (
                        None if predicted_duration is None else abs(observed_duration - predicted_duration) / predicted_duration
                    ),
                }
                event_timing_predictions[predictor] = {}
                for event, event_r in EVENT_TIMING_OUTCOMES:
                    actual_ts_raw = cycle.get(NODE_TS_FIELDS[event])
                    actual_elapsed = (
                        None
                        if actual_ts_raw is None
                        else (parse_ts(actual_ts_raw) - start).total_seconds() / 86400.0
                    )
                    predicted_elapsed = (
                        None if predicted_duration is None else predicted_duration * event_r
                    )
                    event_timing_predictions[predictor][event] = {
                        "actual_event_elapsed_days": actual_elapsed,
                        "predicted_event_elapsed_days": predicted_elapsed,
                        "absolute_error_days": (
                            None
                            if actual_elapsed is None or predicted_elapsed is None
                            else abs(actual_elapsed - predicted_elapsed)
                        ),
                    }

            baseline_alignment_errors = {
                predictor: (
                    None
                    if predicted_duration is None
                    else abs(elapsed - predicted_duration * checkpoint_ratio[checkpoint])
                )
                for predictor, predicted_duration in predictors.items()
            }
            market_metrics = _tracker_compatible_market_metrics(cycle, checkpoint)
            output.append(
                {
                    "cycle_id": cycle["cycle_id"],
                    "symbol": symbol,
                    "split": splits[str(cycle["cycle_id"])],
                    "cycle_status": cycle.get("cycle_status"),
                    "checkpoint": checkpoint,
                    "checkpoint_ratio": ratio,
                    "start_ts": cycle["start_ts"],
                    "checkpoint_ts": checkpoint_ts_raw,
                    "checkpoint_feature_as_of_ts": feature_ts_raw,
                    "checkpoint_elapsed_days": elapsed,
                    "candidate_alignment_absolute_error_days": candidate_errors,
                    "candidate_alignment_scores": {
                        key: -value for key, value in candidate_errors.items()
                    },
                    "family_selected_duration_days": selected,
                    "family_alignment_absolute_error_days": candidate_errors[str(selected)],
                    "family_alignment_score": -candidate_errors[str(selected)],
                    "asset_prior_completed_cycle_count": len(asset_history),
                    "pooled_prior_completed_cycle_count": len(pooled_history),
                    "predictor_durations_days": predictors,
                    "predictor_alignment_absolute_error_days": baseline_alignment_errors,
                    "duration_predictions": duration_predictions,
                    "event_timing_predictions": event_timing_predictions,
                    "observed_cycle_length_days": observed_duration,
                    "main_pulse_confirmed": bool(cycle.get("main_pulse_confirmed")),
                    "extension_confirmed": bool(cycle.get("extension_confirmed")),
                    "false_extension": (
                        cycle.get("extension_runner_state") == "BUILDING"
                        and not bool(cycle.get("extension_confirmed"))
                    ),
                    "reset_reason": cycle.get("reset_reason"),
                    "phase_shift_reason": cycle.get("phase_shift_reason"),
                    "walk_forward_baselines_available": (
                        asset_median is not None and pooled_median is not None
                    ),
                    **market_metrics,
                }
            )
    return output


def _auc_permutation_p(
    rows: Sequence[dict[str, Any]],
    *,
    score_getter: Any,
    outcome: str,
    population: str,
    checkpoint: str,
    key: str,
    permutations: int,
) -> tuple[float | None, float | None]:
    scores = [float(score_getter(row)) for row in rows]
    labels = [bool(row[outcome]) for row in rows]
    observed = tie_aware_auc(scores, labels)
    if observed is None:
        return None, None
    grouped_indices: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        grouped_indices[str(row["symbol"])].append(index)
    null_values: list[float] = []
    for permutation_index in range(permutations):
        rng = random.Random(
            f"{RANDOM_SEED}:{population}:{checkpoint}:{outcome}:{key}:{permutation_index}"
        )
        shuffled = list(labels)
        for indices in grouped_indices.values():
            values = [shuffled[index] for index in indices]
            rng.shuffle(values)
            for index, value in zip(indices, values):
                shuffled[index] = value
        null_auc = tie_aware_auc(scores, shuffled)
        if null_auc is not None:
            null_values.append(null_auc)
    return observed, permutation_p_value(observed, null_values, higher_is_better=True)


def build_candidate_tests(
    checkpoint_rows: list[dict[str, Any]],
    *,
    permutations: int,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    population_map = populations(checkpoint_rows)
    for population, population_rows in population_map.items():
        for checkpoint, _ in CHECKPOINTS:
            checkpoint_population = [row for row in population_rows if row["checkpoint"] == checkpoint]
            discovery = [row for row in checkpoint_population if row["split"] == "discovery"]
            holdout = [row for row in checkpoint_population if row["split"] == "holdout"]
            for outcome in BINARY_OUTCOMES:
                group_rows: list[dict[str, Any]] = []
                p_values: dict[str, float | None] = {}
                for candidate in DURATION_FAMILY_DAYS:
                    key = str(candidate)
                    discovery_auc = tie_aware_auc(
                        [-float(row["candidate_alignment_absolute_error_days"][key]) for row in discovery],
                        [bool(row[outcome]) for row in discovery],
                    )
                    holdout_auc, raw_p = _auc_permutation_p(
                        holdout,
                        score_getter=lambda row, candidate_key=key: -float(
                            row["candidate_alignment_absolute_error_days"][candidate_key]
                        ),
                        outcome=outcome,
                        population=population,
                        checkpoint=checkpoint,
                        key=f"candidate_{key}",
                        permutations=permutations,
                    ) if holdout else (None, None)
                    p_values[key] = raw_p
                    group_rows.append(
                        {
                            "population": population,
                            "checkpoint": checkpoint,
                            "future_outcome": outcome,
                            "candidate_duration_days": candidate,
                            "discovery_sample_count": len(discovery),
                            "holdout_sample_count": len(holdout),
                            "discovery_alignment_mae_days": (
                                mean(float(row["candidate_alignment_absolute_error_days"][key]) for row in discovery)
                                if discovery
                                else None
                            ),
                            "holdout_alignment_mae_days": (
                                mean(float(row["candidate_alignment_absolute_error_days"][key]) for row in holdout)
                                if holdout
                                else None
                            ),
                            "discovery_auc": discovery_auc,
                            "holdout_auc": holdout_auc,
                            "p_value_raw": raw_p,
                        }
                    )
                corrected = holm_bonferroni(p_values)
                for row in group_rows:
                    correction = corrected[str(row["candidate_duration_days"])]
                    row.update(
                        {
                            "p_value_adjusted": correction["p_value_adjusted"],
                            "reject_at_alpha": correction["reject_at_alpha"],
                            "multiple_comparison_method": MULTIPLE_COMPARISON_METHOD,
                            "alpha": ALPHA,
                        }
                    )
                    output.append(row)
    return output


def _duration_permutation_p(
    rows: Sequence[dict[str, Any]],
    *,
    predictor: str,
    population: str,
    checkpoint: str,
    permutations: int,
) -> float | None:
    usable = [
        row
        for row in rows
        if row["duration_predictions"][predictor]["predicted_duration_days"] is not None
    ]
    if len(usable) < 2:
        return None
    predictions = [float(row["duration_predictions"][predictor]["predicted_duration_days"]) for row in usable]
    actual = [float(row["observed_cycle_length_days"]) for row in usable]
    observed_mae = mean(abs(value - prediction) for value, prediction in zip(actual, predictions))
    grouped_indices: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(usable):
        grouped_indices[str(row["symbol"])].append(index)
    null_values: list[float] = []
    for permutation_index in range(permutations):
        rng = random.Random(
            f"{RANDOM_SEED}:{population}:{checkpoint}:{predictor}:duration:{permutation_index}"
        )
        shuffled = list(actual)
        for indices in grouped_indices.values():
            values = [shuffled[index] for index in indices]
            rng.shuffle(values)
            for index, value in zip(indices, values):
                shuffled[index] = value
        null_values.append(mean(abs(value - prediction) for value, prediction in zip(shuffled, predictions)))
    return permutation_p_value(observed_mae, null_values, higher_is_better=False)


def _summary_for_predictor(rows: Sequence[dict[str, Any]], predictor: str, *, population: str, checkpoint: str, permutations: int) -> dict[str, Any]:
    usable = [
        row
        for row in rows
        if row["duration_predictions"][predictor]["predicted_duration_days"] is not None
    ]
    return {
        "sample_count": len(usable),
        "predicted_duration_days": distribution(
            row["duration_predictions"][predictor]["predicted_duration_days"] for row in usable
        ),
        "duration_prediction_absolute_error_days": distribution(
            row["duration_predictions"][predictor]["absolute_error_days"] for row in usable
        ),
        "duration_prediction_absolute_relative_error": distribution(
            row["duration_predictions"][predictor]["absolute_relative_error"] for row in usable
        ),
        "duration_permutation_p_value": _duration_permutation_p(
            usable,
            predictor=predictor,
            population=population,
            checkpoint=checkpoint,
            permutations=permutations,
        ),
        "main_pulse_timing_absolute_error_days": distribution(
            row["event_timing_predictions"][predictor]["main_pulse"]["absolute_error_days"]
            for row in usable
        ),
        "extension_timing_absolute_error_days": distribution(
            row["event_timing_predictions"][predictor]["extension"]["absolute_error_days"]
            for row in usable
        ),
    }


def summarize_lane_b(
    checkpoint_rows: list[dict[str, Any]],
    candidate_tests: list[dict[str, Any]],
    *,
    permutations: int,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "claim_type": "point_in_time_predictive_validation",
        "registry_version": REGISTRY_VERSION,
        "permutations": permutations,
        "populations": {},
    }
    candidate_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in candidate_tests:
        candidate_groups[(row["population"], row["checkpoint"], row["future_outcome"])].append(row)

    for population, population_rows in populations(checkpoint_rows).items():
        result["populations"][population] = {}
        for checkpoint, _ in CHECKPOINTS:
            rows = [row for row in population_rows if row["checkpoint"] == checkpoint]
            discovery = [row for row in rows if row["split"] == "discovery"]
            holdout = [row for row in rows if row["split"] == "holdout"]
            walk_forward = [row for row in rows if row["walk_forward_baselines_available"]]

            binary_summary: dict[str, Any] = {}
            for outcome in BINARY_OUTCOMES:
                tests = candidate_groups[(population, checkpoint, outcome)]
                selectable = [row for row in tests if row["discovery_auc"] is not None]
                selected = (
                    max(
                        selectable,
                        key=lambda row: (
                            float(row["discovery_auc"]),
                            -float(row["candidate_duration_days"]),
                        ),
                    )
                    if selectable
                    else None
                )
                family_holdout_auc, family_p = _auc_permutation_p(
                    holdout,
                    score_getter=lambda row: float(row["family_alignment_score"]),
                    outcome=outcome,
                    population=population,
                    checkpoint=checkpoint,
                    key="family_min_alignment",
                    permutations=permutations,
                ) if holdout else (None, None)

                baseline_auc: dict[str, Any] = {}
                for predictor in ("fixed_21d", "asset_prior_median_completed_duration", "pooled_prior_median_completed_duration"):
                    usable = [
                        row
                        for row in holdout
                        if row["predictor_alignment_absolute_error_days"][predictor] is not None
                    ]
                    auc, p_value = _auc_permutation_p(
                        usable,
                        score_getter=lambda row, name=predictor: -float(
                            row["predictor_alignment_absolute_error_days"][name]
                        ),
                        outcome=outcome,
                        population=population,
                        checkpoint=checkpoint,
                        key=f"baseline_{predictor}",
                        permutations=permutations,
                    ) if usable else (None, None)
                    baseline_auc[predictor] = {
                        "sample_count": len(usable),
                        "holdout_auc": auc,
                        "permutation_p_value": p_value,
                    }
                binary_summary[outcome] = {
                    "discovery_selected_candidate_duration_days": (
                        None if selected is None else selected["candidate_duration_days"]
                    ),
                    "discovery_selected_candidate_auc": (
                        None if selected is None else selected["discovery_auc"]
                    ),
                    "selected_candidate_holdout_auc": (
                        None if selected is None else selected["holdout_auc"]
                    ),
                    "selected_candidate_holdout_p_value_raw": (
                        None if selected is None else selected["p_value_raw"]
                    ),
                    "selected_candidate_holdout_p_value_adjusted": (
                        None if selected is None else selected["p_value_adjusted"]
                    ),
                    "selected_candidate_reject_at_alpha": (
                        False if selected is None else selected["reject_at_alpha"]
                    ),
                    "family_min_alignment_holdout_auc": family_holdout_auc,
                    "family_min_alignment_permutation_p_value": family_p,
                    "baseline_holdout_auc": baseline_auc,
                }

            predictor_summary = {
                predictor: _summary_for_predictor(
                    holdout,
                    predictor,
                    population=population,
                    checkpoint=checkpoint,
                    permutations=permutations,
                )
                for predictor in (
                    "family_checkpoint_selector",
                    "fixed_21d",
                    "asset_prior_median_completed_duration",
                    "pooled_prior_median_completed_duration",
                )
            }

            result["populations"][population][checkpoint] = {
                "sample_count": len(rows),
                "discovery_sample_count": len(discovery),
                "holdout_sample_count": len(holdout),
                "walk_forward_sample_count": len(walk_forward),
                "family_alignment_absolute_error_days": distribution(
                    row["family_alignment_absolute_error_days"] for row in rows
                ),
                "fixed_21d_alignment_absolute_error_days": distribution(
                    row["predictor_alignment_absolute_error_days"]["fixed_21d"] for row in rows
                ),
                "main_pulse_confirmation_rate": (
                    sum(row["main_pulse_confirmed"] for row in rows) / len(rows) if rows else None
                ),
                "extension_confirmation_rate": (
                    sum(row["extension_confirmed"] for row in rows) / len(rows) if rows else None
                ),
                "false_extension_rate": (
                    sum(row["false_extension"] for row in rows) / len(rows) if rows else None
                ),
                "mfe_pct": distribution(row["mfe_pct"] for row in rows),
                "mae_pct": distribution(row["mae_pct"] for row in rows),
                "time_to_main_pulse_days": distribution(row["time_to_main_pulse_days"] for row in rows),
                "time_to_extension_days": distribution(row["time_to_extension_days"] for row in rows),
                "binary_outcome_tests": binary_summary,
                "holdout_duration_and_event_timing": predictor_summary,
            }
    return result


def artifact_hashes(out_dir: Path, filenames: Sequence[str]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for filename in filenames:
        path = out_dir / filename
        result[filename] = {
            "path": str(path),
            "sha256": sha256_file(path),
            "present": True,
        }
    return result


def analyze(
    *,
    source_run_dir: Path,
    out_dir: Path,
    permutations: int = NULL_PERMUTATIONS,
) -> dict[str, Any]:
    if permutations <= 0:
        raise ValueError("permutations must be positive")
    if out_dir.exists():
        raise FileExistsError(f"immutable output directory already exists: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=False)

    root = repo_root()
    analysis_commit = resolve_analysis_commit(root)
    registry_path = root / "src/research/breathline_harmonic_family_registry_v1.py"
    analyzer_path = Path(__file__).resolve()

    source_manifest, cycles_by_symbol, summaries, source_provenance = validate_source_run(source_run_dir)
    splits = split_map(cycles_by_symbol)

    registry = registry_payload()
    write_json(out_dir / "registry.json", registry)

    lane_a_duration_rows, lane_a_phase_rows = build_lane_a_rows(cycles_by_symbol, splits)
    lane_a_summary = summarize_lane_a(
        lane_a_duration_rows,
        lane_a_phase_rows,
        permutations=permutations,
    )
    write_jsonl(out_dir / "lane_a_cycle_residuals.jsonl", lane_a_duration_rows)
    write_jsonl(out_dir / "lane_a_phase_residuals.jsonl", lane_a_phase_rows)
    write_json(out_dir / "lane_a_summary.json", lane_a_summary)

    lane_b_rows = build_lane_b_rows(cycles_by_symbol, splits)
    candidate_tests = build_candidate_tests(lane_b_rows, permutations=permutations)
    lane_b_summary = summarize_lane_b(
        lane_b_rows,
        candidate_tests,
        permutations=permutations,
    )
    write_jsonl(out_dir / "lane_b_checkpoint_rows.jsonl", lane_b_rows)
    write_jsonl(out_dir / "lane_b_candidate_tests.jsonl", candidate_tests)
    write_json(out_dir / "lane_b_summary.json", lane_b_summary)

    artifact_names = (
        "registry.json",
        "lane_a_cycle_residuals.jsonl",
        "lane_a_phase_residuals.jsonl",
        "lane_a_summary.json",
        "lane_b_checkpoint_rows.jsonl",
        "lane_b_candidate_tests.jsonl",
        "lane_b_summary.json",
    )
    manifest = {
        "runner_name": RUNNER_NAME,
        "runner_version": RUNNER_VERSION,
        "run_ts_utc": fmt_ts(utc_now()),
        "analysis_commit_sha": analysis_commit,
        "analyzer_source_sha256": sha256_file(analyzer_path),
        "registry_name": REGISTRY_NAME,
        "registry_version": REGISTRY_VERSION,
        "registry_source_sha256": sha256_file(registry_path),
        "registry_snapshot_sha256": sha256_file(out_dir / "registry.json"),
        "source_run_dir": str(source_run_dir),
        "source_run_id": source_manifest.get("run_id"),
        "source_run_analysis_commit_sha": source_manifest.get("analysis_commit_sha"),
        "source_run_manifest_sha256": sha256_file(source_run_dir / "run_manifest.json"),
        "source_symbols": list(EXPECTED_SYMBOLS),
        "source_provenance": source_provenance,
        "tracker_model_versions": {
            symbol: summaries[symbol].get("model_version") for symbol in EXPECTED_SYMBOLS
        },
        "split_contract": registry["split"],
        "null_contract": registry["nulls"],
        "multiple_comparisons": registry["multiple_comparisons"],
        "permutations_executed": permutations,
        "safety": dict(SAFETY_MARKERS),
        "artifacts": artifact_hashes(out_dir, artifact_names),
    }
    write_json(out_dir / "run_manifest.json", manifest)
    emit(
        "CHECKPOINT",
        "run_manifest",
        path=str(out_dir / "run_manifest.json"),
        sha256=sha256_file(out_dir / "run_manifest.json"),
    )
    return manifest


def validate_run_id(value: str) -> str:
    text = value.strip()
    if not text or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-" for char in text):
        raise ValueError("run-id must contain only [A-Za-z0-9._-]")
    return text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-run-dir",
        required=True,
        type=Path,
        help="Immutable completed #534 empirical run directory",
    )
    parser.add_argument(
        "--out-root",
        type=Path,
        default=DEFAULT_OUT_ROOT,
        help="Generated research artifact root",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Immutable #533 run id; defaults to UTC timestamp",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    run_id = validate_run_id(args.run_id or utc_now().strftime("%Y%m%dT%H%M%SZ"))
    out_dir = args.out_root / run_id
    started = time.monotonic()
    emit(
        "STARTED",
        RUNNER_NAME,
        run_id=run_id,
        registry_version=REGISTRY_VERSION,
        permutations=NULL_PERMUTATIONS,
        research_only=True,
    )
    try:
        manifest = analyze(
            source_run_dir=args.source_run_dir,
            out_dir=out_dir,
            permutations=NULL_PERMUTATIONS,
        )
    except Exception as exc:
        shutil.rmtree(out_dir, ignore_errors=True)
        emit(
            "FAILED",
            RUNNER_NAME,
            run_id=run_id,
            elapsed_seconds=f"{time.monotonic() - started:.2f}",
            error_type=type(exc).__name__,
            error=str(exc),
            broker_private_calls=0,
            broker_writes=0,
            order_submission=0,
            live_orders=0,
            decision_gate="none",
            execution_planner="none",
            executor="none",
        )
        return 1
    emit(
        "FINISHED",
        RUNNER_NAME,
        run_id=run_id,
        elapsed_seconds=f"{time.monotonic() - started:.2f}",
        output_dir=str(out_dir),
        source_run_id=manifest.get("source_run_id"),
        broker_private_calls=0,
        broker_writes=0,
        order_submission=0,
        live_orders=0,
        decision_gate="none",
        execution_planner="none",
        executor="none",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
