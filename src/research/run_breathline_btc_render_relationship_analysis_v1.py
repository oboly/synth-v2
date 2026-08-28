from __future__ import annotations

"""Offline falsification analysis for Issue #418 BTC↔RENDER Breathline relations.

Consumes an immutable independent-ledger run produced by
``run_bullish_breathline_btc_render_canonical_4h_v1``. The existing #417
single-symbol tracker is never invoked or modified here.

Lane A is retrospective structural description. Lane B is point-in-time
predictive validation. All statistics, nulls, minimum support and verdict rules
come from the frozen relationship registry.
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
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable, Sequence

from src.research.breathline_btc_alt_relationship_registry_v1 import (
    ALPHA,
    ALT_SYMBOL,
    DISCOVERY_FRACTION,
    EVENTS,
    INTERVAL_CODE,
    MIN_BINARY_CLASS_COUNT,
    MIN_BINARY_ROWS_PER_SPLIT,
    MIN_EVENT_COMPARISONS_PER_SPLIT,
    MIN_PAIRED_CYCLES_PER_SPLIT,
    MIN_PRIOR_RENDER_OUTCOMES,
    MIN_SEQUENCE_CYCLES_PER_SPLIT,
    MIN_SIGNIFICANT_LAG_EVENTS,
    MULTIPLE_COMPARISON_METHOD,
    NULL_PERMUTATIONS,
    PHASE_CHECKPOINTS,
    PREDICTIVE_ALT_CHECKPOINTS,
    PREDICTIVE_OUTCOMES,
    RANDOM_SEED,
    REFERENCE_SYMBOL,
    REGISTRY_NAME,
    REGISTRY_VERSION,
    ROTATION_FEATURES,
    SAFETY_MARKERS,
    VENUE,
    registry_payload,
)


RUNNER_NAME = "breathline_btc_render_relationship_analysis_v1"
RUNNER_VERSION = "1.0.0"
SOURCE_RUNNER_NAME = "bullish_breathline_btc_render_canonical_4h_v1"
DEFAULT_OUT_ROOT = Path("data/research/breathline_btc_render_relationship_analysis_v1")
SOURCE_REGISTRY_PATH = Path("src/research/breathline_btc_alt_relationship_registry_v1.py")
ANALYZER_SOURCE_PATH = Path(__file__).resolve()

EVENT_TS_FIELDS = {
    "start": "start_ts",
    "recognition": "recognition_ts",
    "ignition": "ignition_ts",
    "main_pulse": "main_pulse_ts",
    "extension": "extension_ts",
    "end": "end_ts",
}

CONFIRMED_AT_FIELDS = {
    "recognition": "recognition_confirmed_at_ts",
    "ignition": "ignition_confirmed_at_ts",
    "main_pulse": "main_pulse_confirmed_at_ts",
    "extension": "extension_confirmed_at_ts",
}


class AnalysisError(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(UTC)


def fmt_ts(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_ts(value: Any, *, field: str, required: bool = True) -> datetime | None:
    if value in (None, ""):
        if required:
            raise AnalysisError(f"missing timestamp field: {field}")
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise AnalysisError(f"invalid timestamp field: {field}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def days_between(later: datetime, earlier: datetime) -> float:
    return (later - earlier).total_seconds() / 86400.0


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def git_output(args: list[str]) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo_root(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    value = completed.stdout.decode("utf-8", errors="replace").strip()
    if completed.returncode != 0 or not value:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise AnalysisError(detail or f"git {' '.join(args)} failed")
    return value


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise AnalysisError(f"invalid JSONL {path}:{line_number}") from exc
            if not isinstance(row, dict):
                raise AnalysisError(f"non-object JSONL row {path}:{line_number}")
            rows.append(row)
    return rows


def event_ts(cycle: dict[str, Any], event: str) -> datetime | None:
    return parse_ts(cycle.get(EVENT_TS_FIELDS[event]), field=EVENT_TS_FIELDS[event], required=False)


def confirmed_at_ts(cycle: dict[str, Any], event: str) -> datetime | None:
    return parse_ts(cycle.get(CONFIRMED_AT_FIELDS[event]), field=CONFIRMED_AT_FIELDS[event], required=False)


def cycle_start(cycle: dict[str, Any]) -> datetime:
    value = parse_ts(cycle.get("start_ts"), field="start_ts")
    assert value is not None
    return value


def cycle_end(cycle: dict[str, Any]) -> datetime:
    value = parse_ts(cycle.get("end_ts"), field="end_ts")
    assert value is not None
    return value


def validate_cycle(cycle: dict[str, Any], *, symbol: str) -> None:
    if str(cycle.get("symbol") or "").upper() != symbol:
        raise AnalysisError(f"cycle symbol mismatch expected={symbol}")
    if not cycle.get("cycle_id"):
        raise AnalysisError(f"cycle_id missing for {symbol}")
    start = cycle_start(cycle)
    end = cycle_end(cycle)
    if end < start:
        raise AnalysisError(f"cycle end before start: {cycle['cycle_id']}")
    parse_ts(cycle.get("outcome_as_of_ts"), field="outcome_as_of_ts")


def validate_source_run(source_run_dir: Path) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]], dict[str, str]]:
    manifest_path = source_run_dir / "run_manifest.json"
    if not manifest_path.is_file():
        raise AnalysisError(f"source run manifest missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("runner_name") != SOURCE_RUNNER_NAME:
        raise AnalysisError("unexpected source runner")
    if manifest.get("symbols") != [REFERENCE_SYMBOL, ALT_SYMBOL]:
        raise AnalysisError("source symbol order/scope mismatch")
    if manifest.get("venue") != VENUE or manifest.get("interval_code") != INTERVAL_CODE:
        raise AnalysisError("source venue/interval mismatch")
    if manifest.get("relationship_analysis_performed") is not False:
        raise AnalysisError("source run must contain independent ledgers only")
    if manifest.get("research_only") is not True or manifest.get("market_only") is not True:
        raise AnalysisError("source run safety contract mismatch")

    assets = manifest.get("assets")
    if not isinstance(assets, list) or len(assets) != 2:
        raise AnalysisError("source manifest asset set invalid")
    by_symbol = {str(row.get("symbol") or "").upper(): row for row in assets if isinstance(row, dict)}
    if set(by_symbol) != {REFERENCE_SYMBOL, ALT_SYMBOL}:
        raise AnalysisError("source manifest asset symbols invalid")

    cycles_by_symbol: dict[str, list[dict[str, Any]]] = {}
    ledger_hashes: dict[str, str] = {}
    for symbol in (REFERENCE_SYMBOL, ALT_SYMBOL):
        ledger_path = source_run_dir / symbol / "tracker" / "cycle_ledger.jsonl"
        if not ledger_path.is_file():
            raise AnalysisError(f"source ledger missing: {ledger_path}")
        actual_hash = sha256_file(ledger_path)
        expected_hash = (
            by_symbol[symbol]
            .get("tracker_artifacts", {})
            .get("cycle_ledger.jsonl", {})
            .get("sha256")
        )
        if actual_hash != expected_hash:
            raise AnalysisError(f"source ledger hash mismatch: {symbol}")
        rows = load_jsonl(ledger_path)
        for row in rows:
            validate_cycle(row, symbol=symbol)
        rows.sort(key=lambda row: (cycle_start(row), str(row["cycle_id"])))
        cycles_by_symbol[symbol] = rows
        ledger_hashes[symbol] = actual_hash

    return manifest, cycles_by_symbol, ledger_hashes


def split_render_cycles(render_cycles: Sequence[dict[str, Any]]) -> dict[str, str]:
    ordered = sorted(render_cycles, key=lambda row: (cycle_start(row), str(row["cycle_id"])))
    discovery_count = int(math.floor(len(ordered) * DISCOVERY_FRACTION))
    return {
        str(row["cycle_id"]): ("discovery" if idx < discovery_count else "holdout")
        for idx, row in enumerate(ordered)
    }


def overlap_seconds(a: dict[str, Any], b: dict[str, Any]) -> float:
    start = max(cycle_start(a), cycle_start(b))
    end = min(cycle_end(a), cycle_end(b))
    return max(0.0, (end - start).total_seconds())


def realized_phase(cycle: dict[str, Any], at_ts: datetime) -> float | None:
    start = cycle_start(cycle)
    end = cycle_end(cycle)
    duration = (end - start).total_seconds()
    if duration <= 0 or at_ts < start or at_ts > end:
        return None
    return (at_ts - start).total_seconds() / duration


def best_btc_pair(render: dict[str, Any], btc_cycles: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    candidates: list[tuple[float, float, datetime, str, dict[str, Any]]] = []
    render_start = cycle_start(render)
    for btc in btc_cycles:
        overlap = overlap_seconds(render, btc)
        if overlap <= 0:
            continue
        start_lag_abs = abs(days_between(render_start, cycle_start(btc)))
        candidates.append(
            (
                -overlap,
                start_lag_abs,
                cycle_start(btc),
                str(btc["cycle_id"]),
                btc,
            )
        )
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1], item[2], item[3]))
    return candidates[0][4]


def build_pair_rows(
    btc_cycles: Sequence[dict[str, Any]],
    render_cycles: Sequence[dict[str, Any]],
    split_by_cycle_id: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    pair_rows: list[dict[str, Any]] = []
    phase_rows: list[dict[str, Any]] = []
    lag_rows: list[dict[str, Any]] = []
    sequence_rows: list[dict[str, Any]] = []

    for render in sorted(render_cycles, key=lambda row: (cycle_start(row), str(row["cycle_id"]))):
        render_id = str(render["cycle_id"])
        split = split_by_cycle_id[render_id]
        btc = best_btc_pair(render, btc_cycles)
        if btc is None:
            pair_rows.append(
                {
                    "render_cycle_id": render_id,
                    "split": split,
                    "paired": False,
                    "relationship_state": "UNPAIRED",
                    "render_start_ts": fmt_ts(cycle_start(render)),
                    "render_end_ts": fmt_ts(cycle_end(render)),
                }
            )
            continue

        btc_id = str(btc["cycle_id"])
        overlap = overlap_seconds(render, btc)
        render_phase_vector: dict[str, float] = {}
        btc_phase_vector: dict[str, float] = {}

        for checkpoint in PHASE_CHECKPOINTS:
            render_event = event_ts(render, checkpoint)
            if render_event is None:
                continue
            render_phase = realized_phase(render, render_event)
            btc_phase = realized_phase(btc, render_event)
            if render_phase is None or btc_phase is None:
                continue
            render_phase_vector[checkpoint] = render_phase
            btc_phase_vector[checkpoint] = btc_phase
            phase_rows.append(
                {
                    "split": split,
                    "render_cycle_id": render_id,
                    "btc_cycle_id": btc_id,
                    "checkpoint": checkpoint,
                    "sample_ts": fmt_ts(render_event),
                    "render_realized_phase": render_phase,
                    "btc_realized_phase": btc_phase,
                    "signed_phase_delta": render_phase - btc_phase,
                    "absolute_phase_delta": abs(render_phase - btc_phase),
                }
            )

        event_lags: dict[str, float] = {}
        for event in EVENTS:
            render_event = event_ts(render, event)
            btc_event = event_ts(btc, event)
            if render_event is None or btc_event is None:
                continue
            lag = days_between(render_event, btc_event)
            event_lags[event] = lag
            lag_rows.append(
                {
                    "split": split,
                    "render_cycle_id": render_id,
                    "btc_cycle_id": btc_id,
                    "event": event,
                    "render_event_ts": fmt_ts(render_event),
                    "btc_event_ts": fmt_ts(btc_event),
                    "event_lag_days": lag,
                }
            )

        ordered_points = [
            (checkpoint, abs(render_phase_vector[checkpoint] - btc_phase_vector[checkpoint]))
            for checkpoint in PHASE_CHECKPOINTS
            if checkpoint in render_phase_vector and checkpoint in btc_phase_vector
        ]
        changes = [
            ordered_points[idx][1] - ordered_points[idx - 1][1]
            for idx in range(1, len(ordered_points))
        ]
        net_change = None
        detached = False
        relock = False
        if len(ordered_points) >= 2:
            net_change = ordered_points[-1][1] - ordered_points[0][1]
            detached_at: int | None = None
            for idx in range(1, len(changes)):
                if changes[idx - 1] > 0 and changes[idx] > 0:
                    detached = True
                    detached_at = idx
                    break
            if detached_at is not None:
                relock = any(change < 0 for change in changes[detached_at + 1 :])
            sequence_rows.append(
                {
                    "split": split,
                    "render_cycle_id": render_id,
                    "btc_cycle_id": btc_id,
                    "checkpoints": [item[0] for item in ordered_points],
                    "absolute_phase_deltas": [item[1] for item in ordered_points],
                    "delta_abs_phase_errors": changes,
                    "net_abs_phase_delta_change": net_change,
                    "detached_sequence": detached,
                    "relock_sequence": relock,
                }
            )

        pair_rows.append(
            {
                "render_cycle_id": render_id,
                "btc_cycle_id": btc_id,
                "split": split,
                "paired": True,
                "relationship_state": "PAIRED_UNCLASSIFIED",
                "render_start_ts": fmt_ts(cycle_start(render)),
                "render_end_ts": fmt_ts(cycle_end(render)),
                "btc_start_ts": fmt_ts(cycle_start(btc)),
                "btc_end_ts": fmt_ts(cycle_end(btc)),
                "overlap_days": overlap / 86400.0,
                "start_lag_days": days_between(cycle_start(render), cycle_start(btc)),
                "end_lag_days": days_between(cycle_end(render), cycle_end(btc)),
                "render_extension_confirmed": bool(render.get("extension_confirmed")),
                "btc_extension_confirmed": bool(btc.get("extension_confirmed")),
                "render_phase_vector": render_phase_vector,
                "btc_phase_vector": btc_phase_vector,
                "phase_support_pattern": [
                    checkpoint
                    for checkpoint in PHASE_CHECKPOINTS
                    if checkpoint in render_phase_vector and checkpoint in btc_phase_vector
                ],
                "event_lags_days": event_lags,
            }
        )

    return pair_rows, phase_rows, lag_rows, sequence_rows


def mean_or_none(values: Sequence[float]) -> float | None:
    return None if not values else float(mean(values))


def median_or_none(values: Sequence[float]) -> float | None:
    return None if not values else float(median(values))


def rate_or_none(values: Sequence[bool]) -> float | None:
    return None if not values else sum(1 for value in values if value) / len(values)


def roc_auc(scores: Sequence[float], labels: Sequence[bool]) -> float | None:
    if len(scores) != len(labels):
        raise ValueError("score/label length mismatch")
    positives = [score for score, label in zip(scores, labels, strict=True) if label]
    negatives = [score for score, label in zip(scores, labels, strict=True) if not label]
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


def holm_adjust(raw: dict[str, float | None]) -> dict[str, float | None]:
    valid = sorted((value, key) for key, value in raw.items() if value is not None)
    adjusted: dict[str, float | None] = {key: None for key in raw}
    running = 0.0
    count = len(valid)
    for rank, (value, key) in enumerate(valid):
        candidate = min(1.0, value * (count - rank))
        running = max(running, candidate)
        adjusted[key] = running
    return adjusted


def seed_for(label: str) -> int:
    suffix = int(hashlib.sha256(label.encode("utf-8")).hexdigest()[:8], 16)
    return RANDOM_SEED + suffix


def permutation_p(observed: float, null_values: Sequence[float], *, favorable: str) -> float:
    if len(null_values) != NULL_PERMUTATIONS:
        raise AnalysisError("permutation count mismatch")
    if favorable == "lower":
        extreme = sum(1 for value in null_values if value <= observed)
    elif favorable == "higher":
        extreme = sum(1 for value in null_values if value >= observed)
    else:
        raise ValueError(f"invalid favorable direction: {favorable}")
    return (1 + extreme) / (NULL_PERMUTATIONS + 1)


def phase_stat_from_vectors(rows: Sequence[dict[str, Any]]) -> float | None:
    values: list[float] = []
    for row in rows:
        render_vector = row["render_phase_vector"]
        btc_vector = row["btc_phase_vector"]
        for checkpoint in row["phase_support_pattern"]:
            values.append(abs(float(render_vector[checkpoint]) - float(btc_vector[checkpoint])))
    return mean_or_none(values)


def sequence_stats_from_vectors(rows: Sequence[dict[str, Any]]) -> tuple[float | None, float | None, float | None, int]:
    net_changes: list[float] = []
    detached_values: list[bool] = []
    relock_values: list[bool] = []
    for row in rows:
        checkpoints = list(row["phase_support_pattern"])
        if len(checkpoints) < 2:
            continue
        render_vector = row["render_phase_vector"]
        btc_vector = row["btc_phase_vector"]
        deltas = [abs(float(render_vector[key]) - float(btc_vector[key])) for key in checkpoints]
        changes = [deltas[idx] - deltas[idx - 1] for idx in range(1, len(deltas))]
        net_changes.append(deltas[-1] - deltas[0])
        detached_at: int | None = None
        for idx in range(1, len(changes)):
            if changes[idx - 1] > 0 and changes[idx] > 0:
                detached_at = idx
                break
        detached = detached_at is not None
        relock = False if detached_at is None else any(change < 0 for change in changes[detached_at + 1 :])
        detached_values.append(detached)
        relock_values.append(relock)
    return mean_or_none(net_changes), rate_or_none(detached_values), rate_or_none(relock_values), len(net_changes)


def permute_btc_vectors(rows: Sequence[dict[str, Any]], rng: random.Random) -> list[dict[str, Any]]:
    copied = [dict(row) for row in rows]
    groups: dict[tuple[str, ...], list[int]] = {}
    for idx, row in enumerate(copied):
        pattern = tuple(row["phase_support_pattern"])
        if not pattern:
            continue
        groups.setdefault(pattern, []).append(idx)
    for indices in groups.values():
        vectors = [copied[idx]["btc_phase_vector"] for idx in indices]
        shuffled = list(vectors)
        rng.shuffle(shuffled)
        for idx, vector in zip(indices, shuffled, strict=True):
            copied[idx]["btc_phase_vector"] = vector
    return copied


def pair_null_distributions(rows: Sequence[dict[str, Any]], *, split: str) -> dict[str, list[float]]:
    rng = random.Random(seed_for(f"pair-null:{split}"))
    result = {"phase_lock": [], "net_change": [], "detached_rate": [], "relock_rate": []}
    for _ in range(NULL_PERMUTATIONS):
        permuted = permute_btc_vectors(rows, rng)
        phase = phase_stat_from_vectors(permuted)
        net, detached, relock, _ = sequence_stats_from_vectors(permuted)
        if phase is None or net is None or detached is None or relock is None:
            raise AnalysisError(f"pair null lacks required support in {split}")
        result["phase_lock"].append(phase)
        result["net_change"].append(net)
        result["detached_rate"].append(detached)
        result["relock_rate"].append(relock)
    return result


def lag_null_distribution(rows: Sequence[dict[str, Any]], *, split: str, event: str) -> list[float]:
    eligible = [row for row in rows if row["split"] == split and row["event"] == event]
    render_times = [parse_ts(row["render_event_ts"], field="render_event_ts") for row in eligible]
    btc_times = [parse_ts(row["btc_event_ts"], field="btc_event_ts") for row in eligible]
    assert all(value is not None for value in render_times)
    assert all(value is not None for value in btc_times)
    render_values = [value for value in render_times if value is not None]
    btc_values = [value for value in btc_times if value is not None]
    rng = random.Random(seed_for(f"lag-null:{split}:{event}"))
    nulls: list[float] = []
    for _ in range(NULL_PERMUTATIONS):
        shuffled = list(btc_values)
        rng.shuffle(shuffled)
        nulls.append(mean(days_between(render, btc) for render, btc in zip(render_values, shuffled, strict=True)))
    return nulls


def conditional_extension_difference(rows: Sequence[dict[str, Any]]) -> float | None:
    yes = [bool(row["render_extension_confirmed"]) for row in rows if bool(row["btc_extension_confirmed"])]
    no = [bool(row["render_extension_confirmed"]) for row in rows if not bool(row["btc_extension_confirmed"])]
    if not yes or not no:
        return None
    return (sum(yes) / len(yes)) - (sum(no) / len(no))


def extension_null_distribution(rows: Sequence[dict[str, Any]], *, split: str) -> list[float]:
    labels = [bool(row["btc_extension_confirmed"]) for row in rows]
    rng = random.Random(seed_for(f"extension-null:{split}"))
    nulls: list[float] = []
    for _ in range(NULL_PERMUTATIONS):
        shuffled = list(labels)
        rng.shuffle(shuffled)
        permuted = [dict(row, btc_extension_confirmed=label) for row, label in zip(rows, shuffled, strict=True)]
        value = conditional_extension_difference(permuted)
        if value is None:
            raise AnalysisError("extension permutation lost binary support")
        nulls.append(value)
    return nulls


def binary_support(labels: Sequence[bool]) -> bool:
    if len(labels) < MIN_BINARY_ROWS_PER_SPLIT:
        return False
    positives = sum(1 for value in labels if value)
    negatives = len(labels) - positives
    return positives >= MIN_BINARY_CLASS_COUNT and negatives >= MIN_BINARY_CLASS_COUNT


def build_lane_b_rows(
    btc_cycles: Sequence[dict[str, Any]],
    render_cycles: Sequence[dict[str, Any]],
    split_by_cycle_id: dict[str, str],
) -> list[dict[str, Any]]:
    btc_events: dict[str, list[datetime]] = {"main_pulse": [], "extension": []}
    for cycle in btc_cycles:
        for event in btc_events:
            confirmed = confirmed_at_ts(cycle, event)
            if confirmed is not None:
                btc_events[event].append(confirmed)
    for event in btc_events:
        btc_events[event] = sorted(set(btc_events[event]))

    render_ordered = sorted(render_cycles, key=lambda row: (cycle_start(row), str(row["cycle_id"])))
    rows: list[dict[str, Any]] = []
    for render in render_ordered:
        cycle_id = str(render["cycle_id"])
        outcome_as_of = parse_ts(render.get("outcome_as_of_ts"), field="outcome_as_of_ts")
        assert outcome_as_of is not None
        for checkpoint in PREDICTIVE_ALT_CHECKPOINTS:
            feature_as_of = confirmed_at_ts(render, checkpoint)
            if feature_as_of is None:
                continue

            latest_main = max((value for value in btc_events["main_pulse"] if value <= feature_as_of), default=None)
            latest_extension = max((value for value in btc_events["extension"] if value <= feature_as_of), default=None)

            row: dict[str, Any] = {
                "render_cycle_id": cycle_id,
                "split": split_by_cycle_id[cycle_id],
                "checkpoint": checkpoint,
                "feature_as_of_ts": fmt_ts(feature_as_of),
                "outcome_as_of_ts": fmt_ts(outcome_as_of),
                "main_pulse_confirmed": bool(render.get("main_pulse_confirmed")),
                "extension_confirmed": bool(render.get("extension_confirmed")),
                "latest_btc_main_pulse_confirmed_at_ts": None if latest_main is None else fmt_ts(latest_main),
                "latest_btc_extension_confirmed_at_ts": None if latest_extension is None else fmt_ts(latest_extension),
                "btc_main_pulse_recency_score": None if latest_main is None else -days_between(feature_as_of, latest_main),
                "btc_extension_recency_score": None if latest_extension is None else -days_between(feature_as_of, latest_extension),
            }

            prior = [
                previous
                for previous in render_ordered
                if str(previous["cycle_id"]) != cycle_id
                and (parse_ts(previous.get("outcome_as_of_ts"), field="outcome_as_of_ts") or feature_as_of) < feature_as_of
            ]
            for outcome in PREDICTIVE_OUTCOMES:
                prior_values = [bool(previous.get(outcome)) for previous in prior]
                row[f"no_btc_prior_{outcome}"] = (
                    None
                    if len(prior_values) < MIN_PRIOR_RENDER_OUTCOMES
                    else sum(prior_values) / len(prior_values)
                )
                row[f"no_btc_prior_{outcome}_count"] = len(prior_values)
            rows.append(row)
    return rows


def rotation_null_auc(scores: Sequence[float], labels: Sequence[bool], *, label: str) -> list[float]:
    rng = random.Random(seed_for(f"rotation-null:{label}"))
    nulls: list[float] = []
    for _ in range(NULL_PERMUTATIONS):
        shuffled = list(scores)
        rng.shuffle(shuffled)
        auc = roc_auc(shuffled, labels)
        if auc is None:
            raise AnalysisError("rotation null lost binary support")
        nulls.append(auc)
    return nulls


def summarize_lane_a(
    pair_rows: Sequence[dict[str, Any]],
    phase_rows: Sequence[dict[str, Any]],
    lag_rows: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    paired = [row for row in pair_rows if row.get("paired")]
    result: dict[str, Any] = {
        "pairing": {
            "render_cycle_count": len(pair_rows),
            "paired_count": len(paired),
            "unpaired_count": len(pair_rows) - len(paired),
        },
        "splits": {},
        "hypotheses": {},
    }

    split_cache: dict[str, dict[str, Any]] = {}
    for split in ("discovery", "holdout"):
        split_pairs = [row for row in paired if row["split"] == split]
        split_phase = [row for row in phase_rows if row["split"] == split]
        split_lags = [row for row in lag_rows if row["split"] == split]
        phase_stat = phase_stat_from_vectors(split_pairs)
        net, detached, relock, sequence_count = sequence_stats_from_vectors(split_pairs)
        nulls = None
        if len(split_pairs) >= MIN_PAIRED_CYCLES_PER_SPLIT and sequence_count >= MIN_SEQUENCE_CYCLES_PER_SPLIT and phase_stat is not None:
            nulls = pair_null_distributions(split_pairs, split=split)
        split_cache[split] = {
            "pairs": split_pairs,
            "phase": split_phase,
            "lags": split_lags,
            "phase_stat": phase_stat,
            "net_change": net,
            "detached_rate": detached,
            "relock_rate": relock,
            "sequence_count": sequence_count,
            "pair_nulls": nulls,
        }
        result["splits"][split] = {
            "paired_count": len(split_pairs),
            "phase_value_count": len(split_phase),
            "sequence_count": sequence_count,
            "mean_absolute_phase_delta": phase_stat,
            "mean_net_abs_phase_delta_change": net,
            "detached_sequence_rate": detached,
            "relock_sequence_rate": relock,
        }

    # PHASE_LOCK
    phase_sufficient = all(
        len(split_cache[split]["pairs"]) >= MIN_PAIRED_CYCLES_PER_SPLIT
        and len(split_cache[split]["phase"]) >= MIN_EVENT_COMPARISONS_PER_SPLIT
        and split_cache[split]["pair_nulls"] is not None
        for split in ("discovery", "holdout")
    )
    if not phase_sufficient:
        phase_hypothesis = {"status": "INSUFFICIENT_EVIDENCE"}
    else:
        discovery = split_cache["discovery"]
        holdout = split_cache["holdout"]
        discovery_null = discovery["pair_nulls"]["phase_lock"]
        holdout_null = holdout["pair_nulls"]["phase_lock"]
        holdout_p = permutation_p(holdout["phase_stat"], holdout_null, favorable="lower")
        supported = (
            discovery["phase_stat"] < median(discovery_null)
            and holdout["phase_stat"] < median(holdout_null)
            and holdout_p < ALPHA
        )
        phase_hypothesis = {
            "status": "SUPPORTED_STRUCTURAL" if supported else "NOT_SUPPORTED",
            "discovery_mean_absolute_phase_delta": discovery["phase_stat"],
            "discovery_null_median": median(discovery_null),
            "holdout_mean_absolute_phase_delta": holdout["phase_stat"],
            "holdout_null_median": median(holdout_null),
            "holdout_p_value": holdout_p,
        }
    result["hypotheses"]["PHASE_LOCK"] = phase_hypothesis

    # LEADING / LAGGING
    lag_tests: dict[str, dict[str, Any]] = {}
    raw_holdout_p: dict[str, float | None] = {}
    sufficient_event_count = 0
    for event in PHASE_CHECKPOINTS:
        discovery_rows = [row for row in lag_rows if row["split"] == "discovery" and row["event"] == event]
        holdout_rows = [row for row in lag_rows if row["split"] == "holdout" and row["event"] == event]
        if len(discovery_rows) < MIN_EVENT_COMPARISONS_PER_SPLIT or len(holdout_rows) < MIN_EVENT_COMPARISONS_PER_SPLIT:
            lag_tests[event] = {"status": "INSUFFICIENT_EVIDENCE", "discovery_n": len(discovery_rows), "holdout_n": len(holdout_rows)}
            raw_holdout_p[event] = None
            continue
        sufficient_event_count += 1
        discovery_mean = mean(float(row["event_lag_days"]) for row in discovery_rows)
        holdout_mean = mean(float(row["event_lag_days"]) for row in holdout_rows)
        if discovery_mean == 0:
            raw_p = 1.0
            direction = "NONE"
        else:
            direction = "LAGGING" if discovery_mean > 0 else "LEADING"
            nulls = lag_null_distribution(lag_rows, split="holdout", event=event)
            raw_p = permutation_p(holdout_mean, nulls, favorable="higher" if direction == "LAGGING" else "lower")
        raw_holdout_p[event] = raw_p
        lag_tests[event] = {
            "status": "TESTED",
            "direction_from_discovery": direction,
            "discovery_n": len(discovery_rows),
            "holdout_n": len(holdout_rows),
            "discovery_mean_lag_days": discovery_mean,
            "holdout_mean_lag_days": holdout_mean,
            "holdout_p_value_raw": raw_p,
        }
    adjusted = holm_adjust(raw_holdout_p)
    significant_directions: list[str] = []
    for event, test in lag_tests.items():
        test["holdout_p_value_adjusted"] = adjusted[event]
        if test.get("status") != "TESTED":
            continue
        direction = test["direction_from_discovery"]
        same_sign = (
            direction == "LAGGING" and test["holdout_mean_lag_days"] > 0
        ) or (
            direction == "LEADING" and test["holdout_mean_lag_days"] < 0
        )
        test["same_direction_holdout"] = same_sign
        test["reject_at_alpha"] = bool(same_sign and adjusted[event] is not None and adjusted[event] < ALPHA)
        if test["reject_at_alpha"]:
            significant_directions.append(direction)
    if sufficient_event_count < MIN_SIGNIFICANT_LAG_EVENTS:
        lag_status = "INSUFFICIENT_EVIDENCE"
    elif len(significant_directions) >= MIN_SIGNIFICANT_LAG_EVENTS and len(set(significant_directions)) == 1:
        lag_status = significant_directions[0]
    else:
        lag_status = "NOT_SUPPORTED"
    result["hypotheses"]["LEADING_LAGGING"] = {"status": lag_status, "events": lag_tests}

    # CONVERGING / DIVERGING
    sequence_sufficient = all(
        split_cache[split]["sequence_count"] >= MIN_SEQUENCE_CYCLES_PER_SPLIT
        and split_cache[split]["pair_nulls"] is not None
        for split in ("discovery", "holdout")
    )
    if not sequence_sufficient:
        convergence = {"status": "INSUFFICIENT_EVIDENCE"}
    else:
        discovery = split_cache["discovery"]
        holdout = split_cache["holdout"]
        discovery_mean = discovery["net_change"]
        holdout_mean = holdout["net_change"]
        if discovery_mean is None or holdout_mean is None or discovery_mean == 0:
            convergence = {"status": "NOT_SUPPORTED", "discovery_mean": discovery_mean, "holdout_mean": holdout_mean}
        else:
            direction = "CONVERGING" if discovery_mean < 0 else "DIVERGING"
            holdout_null = holdout["pair_nulls"]["net_change"]
            p_value = permutation_p(holdout_mean, holdout_null, favorable="lower" if direction == "CONVERGING" else "higher")
            same_sign = (direction == "CONVERGING" and holdout_mean < 0) or (direction == "DIVERGING" and holdout_mean > 0)
            convergence = {
                "status": direction if same_sign and p_value < ALPHA else "NOT_SUPPORTED",
                "discovery_mean_net_change": discovery_mean,
                "holdout_mean_net_change": holdout_mean,
                "holdout_p_value": p_value,
            }
    result["hypotheses"]["CONVERGING_DIVERGING"] = convergence

    # DETACHED / RELOCK
    det_raw: dict[str, float | None] = {"DETACHED": None, "RELOCK": None}
    det_tests: dict[str, dict[str, Any]] = {}
    if not sequence_sufficient:
        det_tests = {"DETACHED": {"status": "INSUFFICIENT_EVIDENCE"}, "RELOCK": {"status": "INSUFFICIENT_EVIDENCE"}}
    else:
        for name, field, null_key in (
            ("DETACHED", "detached_rate", "detached_rate"),
            ("RELOCK", "relock_rate", "relock_rate"),
        ):
            discovery = split_cache["discovery"]
            holdout = split_cache["holdout"]
            holdout_p = permutation_p(holdout[field], holdout["pair_nulls"][null_key], favorable="higher")
            det_raw[name] = holdout_p
            det_tests[name] = {
                "status": "TESTED",
                "discovery_rate": discovery[field],
                "discovery_null_median": median(discovery["pair_nulls"][null_key]),
                "holdout_rate": holdout[field],
                "holdout_null_median": median(holdout["pair_nulls"][null_key]),
                "holdout_p_value_raw": holdout_p,
            }
        det_adjusted = holm_adjust(det_raw)
        for name, test in det_tests.items():
            test["holdout_p_value_adjusted"] = det_adjusted[name]
            supported = (
                test["discovery_rate"] > test["discovery_null_median"]
                and test["holdout_rate"] > test["holdout_null_median"]
                and det_adjusted[name] is not None
                and det_adjusted[name] < ALPHA
            )
            test["status"] = "SUPPORTED_STRUCTURAL" if supported else "NOT_SUPPORTED"
    result["hypotheses"]["DETACHED_RELOCK"] = det_tests

    # SHARED_EXTENSION
    extension_split: dict[str, dict[str, Any]] = {}
    extension_sufficient = True
    for split in ("discovery", "holdout"):
        rows = [row for row in paired if row["split"] == split]
        btc_labels = [bool(row["btc_extension_confirmed"]) for row in rows]
        render_labels = [bool(row["render_extension_confirmed"]) for row in rows]
        sufficient = binary_support(btc_labels) and binary_support(render_labels)
        extension_sufficient = extension_sufficient and sufficient
        extension_split[split] = {
            "n": len(rows),
            "btc_extension_count": sum(btc_labels),
            "render_extension_count": sum(render_labels),
            "difference": conditional_extension_difference(rows),
            "sufficient": sufficient,
            "rows": rows,
        }
    if not extension_sufficient:
        extension_hypothesis = {"status": "INSUFFICIENT_EVIDENCE", "splits": {key: {k: v for k, v in value.items() if k != "rows"} for key, value in extension_split.items()}}
    else:
        discovery_diff = extension_split["discovery"]["difference"]
        holdout_diff = extension_split["holdout"]["difference"]
        nulls = extension_null_distribution(extension_split["holdout"]["rows"], split="holdout")
        p_value = permutation_p(holdout_diff, nulls, favorable="higher")
        supported = discovery_diff > 0 and holdout_diff > 0 and p_value < ALPHA
        extension_hypothesis = {
            "status": "SUPPORTED_PREDICTIVE" if supported else "NOT_SUPPORTED",
            "discovery_difference": discovery_diff,
            "holdout_difference": holdout_diff,
            "holdout_p_value": p_value,
            "splits": {key: {k: v for k, v in value.items() if k != "rows"} for key, value in extension_split.items()},
        }
    result["hypotheses"]["SHARED_EXTENSION"] = extension_hypothesis
    return result


def summarize_lane_b(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    tests: dict[str, dict[str, Any]] = {}
    raw_holdout: dict[str, float | None] = {}

    for checkpoint in PREDICTIVE_ALT_CHECKPOINTS:
        for feature in ROTATION_FEATURES:
            for outcome in PREDICTIVE_OUTCOMES:
                key = f"{checkpoint}|{feature}|{outcome}"
                by_split: dict[str, list[dict[str, Any]]] = {}
                for split in ("discovery", "holdout"):
                    eligible = [
                        row
                        for row in rows
                        if row["split"] == split
                        and row["checkpoint"] == checkpoint
                        and row.get(feature) is not None
                        and row.get(f"no_btc_prior_{outcome}") is not None
                    ]
                    by_split[split] = eligible

                support = True
                split_metrics: dict[str, Any] = {}
                for split in ("discovery", "holdout"):
                    eligible = by_split[split]
                    labels = [bool(row[outcome]) for row in eligible]
                    scores = [float(row[feature]) for row in eligible]
                    baselines = [float(row[f"no_btc_prior_{outcome}"]) for row in eligible]
                    sufficient = binary_support(labels)
                    support = support and sufficient
                    split_metrics[split] = {
                        "n": len(eligible),
                        "positive_count": sum(labels),
                        "negative_count": len(labels) - sum(labels),
                        "btc_auc": roc_auc(scores, labels) if sufficient else None,
                        "no_btc_prior_auc": roc_auc(baselines, labels) if sufficient else None,
                        "sufficient": sufficient,
                    }

                if not support:
                    tests[key] = {
                        "checkpoint": checkpoint,
                        "feature": feature,
                        "outcome": outcome,
                        "status": "INSUFFICIENT_EVIDENCE",
                        "splits": split_metrics,
                    }
                    raw_holdout[key] = None
                    continue

                discovery_rows = by_split["discovery"]
                holdout_rows = by_split["holdout"]
                discovery_scores = [float(row[feature]) for row in discovery_rows]
                discovery_labels = [bool(row[outcome]) for row in discovery_rows]
                holdout_scores = [float(row[feature]) for row in holdout_rows]
                holdout_labels = [bool(row[outcome]) for row in holdout_rows]
                discovery_auc = roc_auc(discovery_scores, discovery_labels)
                holdout_auc = roc_auc(holdout_scores, holdout_labels)
                assert discovery_auc is not None and holdout_auc is not None
                nulls = rotation_null_auc(holdout_scores, holdout_labels, label=key)
                raw_p = permutation_p(holdout_auc, nulls, favorable="higher")
                raw_holdout[key] = raw_p
                tests[key] = {
                    "checkpoint": checkpoint,
                    "feature": feature,
                    "outcome": outcome,
                    "status": "TESTED",
                    "splits": split_metrics,
                    "discovery_auc": discovery_auc,
                    "holdout_auc": holdout_auc,
                    "holdout_no_btc_prior_auc": split_metrics["holdout"]["no_btc_prior_auc"],
                    "holdout_p_value_raw": raw_p,
                }

    adjusted = holm_adjust(raw_holdout)
    supported_keys: list[str] = []
    sufficient_count = 0
    for key, test in tests.items():
        test["holdout_p_value_adjusted"] = adjusted[key]
        if test["status"] != "TESTED":
            continue
        sufficient_count += 1
        baseline_auc = test["holdout_no_btc_prior_auc"]
        supported = (
            test["discovery_auc"] > 0.5
            and test["holdout_auc"] > 0.5
            and baseline_auc is not None
            and test["holdout_auc"] > baseline_auc
            and adjusted[key] is not None
            and adjusted[key] < ALPHA
        )
        test["reject_at_alpha"] = supported
        test["status"] = "SUPPORTED" if supported else "NOT_SUPPORTED"
        if supported:
            supported_keys.append(key)

    if supported_keys:
        verdict = "ROTATION_CANDIDATE"
    elif sufficient_count == 0:
        verdict = "INSUFFICIENT_EVIDENCE"
    else:
        verdict = "NOT_SUPPORTED"
    return {
        "walk_forward_definition": "expanding prior RENDER outcomes and prior-confirmed BTC events at each checkpoint",
        "row_count": len(rows),
        "tests": tests,
        "verdict": verdict,
        "supported_tests": supported_keys,
    }


def derive_overall_verdict(lane_a: dict[str, Any], lane_b: dict[str, Any]) -> dict[str, Any]:
    hypotheses = lane_a["hypotheses"]
    predictive_supported = (
        hypotheses["SHARED_EXTENSION"].get("status") == "SUPPORTED_PREDICTIVE"
        or lane_b.get("verdict") == "ROTATION_CANDIDATE"
    )
    structural_supported = (
        hypotheses["PHASE_LOCK"].get("status") == "SUPPORTED_STRUCTURAL"
        or hypotheses["LEADING_LAGGING"].get("status") in {"LEADING", "LAGGING"}
        or hypotheses["CONVERGING_DIVERGING"].get("status") in {"CONVERGING", "DIVERGING"}
        or any(test.get("status") == "SUPPORTED_STRUCTURAL" for test in hypotheses["DETACHED_RELOCK"].values())
    )
    if predictive_supported:
        overall = "POSITIVE_RESEARCH_EVIDENCE"
    elif structural_supported:
        overall = "STRUCTURAL_EVIDENCE_ONLY"
    else:
        overall = "UNRELATED"
    return {
        "overall_verdict": overall,
        "runtime_promotion": False,
        "selection_engine_authority": False,
        "decision_gate_authority": False,
        "execution_authority": False,
    }


def run_analysis(source_run_dir: Path) -> dict[str, Any]:
    source_manifest, cycles, ledger_hashes = validate_source_run(source_run_dir)
    btc_cycles = cycles[REFERENCE_SYMBOL]
    render_cycles = cycles[ALT_SYMBOL]
    split_by_id = split_render_cycles(render_cycles)
    pair_rows, phase_rows, lag_rows, sequence_rows = build_pair_rows(btc_cycles, render_cycles, split_by_id)
    lane_a = summarize_lane_a(pair_rows, phase_rows, lag_rows)
    lane_b_rows = build_lane_b_rows(btc_cycles, render_cycles, split_by_id)
    lane_b = summarize_lane_b(lane_b_rows)
    verdict = derive_overall_verdict(lane_a, lane_b)
    return {
        "source_manifest": source_manifest,
        "ledger_hashes": ledger_hashes,
        "pair_rows": pair_rows,
        "phase_rows": phase_rows,
        "lag_rows": lag_rows,
        "sequence_rows": sequence_rows,
        "lane_a": lane_a,
        "lane_b_rows": lane_b_rows,
        "lane_b": lane_b,
        "verdict": verdict,
    }


def persist_analysis(
    *,
    analysis: dict[str, Any],
    source_run_dir: Path,
    out_root: Path,
    run_id: str,
    cli_args: list[str],
) -> Path:
    run_dir = out_root / run_id
    if run_dir.exists():
        raise FileExistsError(f"immutable analysis run already exists: {run_dir}")

    root = repo_root()
    analysis_commit = git_output(["rev-parse", "HEAD"])
    registry_path = root / SOURCE_REGISTRY_PATH
    analyzer_path = ANALYZER_SOURCE_PATH
    source_manifest_path = source_run_dir / "run_manifest.json"

    run_dir.mkdir(parents=True, exist_ok=False)
    try:
        write_json(run_dir / "registry.json", registry_payload())
        write_jsonl(run_dir / "pair_rows.jsonl", analysis["pair_rows"])
        write_jsonl(run_dir / "lane_a_phase_rows.jsonl", analysis["phase_rows"])
        write_jsonl(run_dir / "lane_a_event_lag_rows.jsonl", analysis["lag_rows"])
        write_jsonl(run_dir / "lane_a_sequence_rows.jsonl", analysis["sequence_rows"])
        write_json(run_dir / "lane_a_summary.json", analysis["lane_a"])
        write_jsonl(run_dir / "lane_b_checkpoint_rows.jsonl", analysis["lane_b_rows"])
        write_json(run_dir / "lane_b_summary.json", analysis["lane_b"])
        write_json(run_dir / "summary.json", analysis["verdict"])

        artifacts: dict[str, str] = {}
        for path in sorted(run_dir.iterdir()):
            if path.is_file() and path.name != "run_manifest.json":
                artifacts[path.name] = sha256_file(path)

        source_manifest = analysis["source_manifest"]
        manifest = {
            "runner_name": RUNNER_NAME,
            "runner_version": RUNNER_VERSION,
            "run_id": run_id,
            "run_ts_utc": fmt_ts(utc_now()),
            "research_only": True,
            "market_only": True,
            "account_awareness": 0,
            "relationship_analysis_performed": True,
            "reference_symbol": REFERENCE_SYMBOL,
            "alt_symbol": ALT_SYMBOL,
            "venue": VENUE,
            "interval_code": INTERVAL_CODE,
            "analysis_commit_sha": analysis_commit,
            "analyzer_source_sha256": sha256_file(analyzer_path),
            "registry_name": REGISTRY_NAME,
            "registry_version": REGISTRY_VERSION,
            "registry_source_sha256": sha256_file(registry_path),
            "source_run_dir": str(source_run_dir),
            "source_run_id": source_manifest.get("run_id"),
            "source_run_analysis_commit_sha": source_manifest.get("analysis_commit_sha"),
            "source_run_manifest_sha256": sha256_file(source_manifest_path),
            "source_tracker_model_version": source_manifest.get("tracker_model_version"),
            "source_tracker_source_commit_sha": source_manifest.get("tracker_source_commit_sha"),
            "source_tracker_source_sha256": source_manifest.get("tracker_source_sha256"),
            "source_ledger_sha256": analysis["ledger_hashes"],
            "discovery_fraction": DISCOVERY_FRACTION,
            "null_permutations": NULL_PERMUTATIONS,
            "random_seed": RANDOM_SEED,
            "multiple_comparison_method": MULTIPLE_COMPARISON_METHOD,
            "alpha": ALPHA,
            "cli": [sys.executable, "-m", "src.research.run_breathline_btc_render_relationship_analysis_v1", *cli_args],
            "output_artifact_sha256": artifacts,
            "safety": dict(SAFETY_MARKERS),
            "verdict": analysis["verdict"],
        }
        write_json(run_dir / "run_manifest.json", manifest)
        return run_dir
    except Exception:
        shutil.rmtree(run_dir, ignore_errors=True)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(raw_args)
    started = time.monotonic()
    print(
        "STARTED",
        RUNNER_NAME,
        f"run_id={args.run_id}",
        f"registry_version={REGISTRY_VERSION}",
        f"permutations={NULL_PERMUTATIONS}",
        "research_only=True",
        flush=True,
    )
    try:
        analysis = run_analysis(args.source_run_dir)
        run_dir = persist_analysis(
            analysis=analysis,
            source_run_dir=args.source_run_dir,
            out_root=args.out_root,
            run_id=args.run_id,
            cli_args=raw_args,
        )
        print(
            "FINISHED",
            RUNNER_NAME,
            f"elapsed_seconds={time.monotonic() - started:.2f}",
            f"output_dir={run_dir}",
            f"overall_verdict={analysis['verdict']['overall_verdict']}",
            "broker_writes=0",
            "order_submission=0",
            "decision_gate=none",
            "execution_planner=none",
            "executor=none",
            flush=True,
        )
        return 0
    except Exception as exc:
        print(
            "FAILED",
            RUNNER_NAME,
            f"elapsed_seconds={time.monotonic() - started:.2f}",
            f"error_type={type(exc).__name__}",
            f"error={exc}",
            flush=True,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
