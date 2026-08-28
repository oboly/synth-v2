from __future__ import annotations

"""Offline falsification analysis for Issue #418 BTC↔RENDER Breathline relations.

Consumes immutable independent #417 ledgers. Lane A is retrospective structural/
association evidence. Lane B is point-in-time predictive validation. Only Lane B
ROTATION_CANDIDATE may create predictive research evidence.
"""

import argparse
import hashlib
import json
import math
import random
import re
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
RUNNER_VERSION = "1.0.5"
SOURCE_RUNNER_NAME = "bullish_breathline_btc_render_canonical_4h_v1"
DEFAULT_OUT_ROOT = Path("data/research/breathline_btc_render_relationship_analysis_v1")
REGISTRY_PATH = Path("src/research/breathline_btc_alt_relationship_registry_v1.py")
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")

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


def fmt_ts(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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
    output = completed.stdout.decode("utf-8", errors="replace").strip()
    if completed.returncode != 0 or not output:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise AnalysisError(detail or f"git {' '.join(args)} failed")
    return output


def validate_run_id(value: str) -> str:
    run_id = str(value).strip()
    if not run_id or RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise ValueError("run_id must match [A-Za-z0-9._-]+")
    return run_id


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
    if cycle_end(cycle) < cycle_start(cycle):
        raise AnalysisError(f"cycle end before start: {cycle['cycle_id']}")
    parse_ts(cycle.get("outcome_as_of_ts"), field="outcome_as_of_ts")


def validate_source_run(
    source_run_dir: Path,
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]], dict[str, str]]:
    manifest_path = source_run_dir / "run_manifest.json"
    if not manifest_path.is_file():
        raise AnalysisError(f"source run manifest missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("runner_name") != SOURCE_RUNNER_NAME:
        raise AnalysisError("unexpected source runner")
    if manifest.get("symbols") != [REFERENCE_SYMBOL, ALT_SYMBOL]:
        raise AnalysisError("source symbol scope mismatch")
    if manifest.get("venue") != VENUE or manifest.get("interval_code") != INTERVAL_CODE:
        raise AnalysisError("source venue/interval mismatch")
    if manifest.get("relationship_analysis_performed") is not False:
        raise AnalysisError("source run must contain independent ledgers only")
    if manifest.get("research_only") is not True or manifest.get("market_only") is not True:
        raise AnalysisError("source run safety contract mismatch")

    assets = manifest.get("assets")
    if not isinstance(assets, list) or len(assets) != 2:
        raise AnalysisError("source manifest asset set invalid")
    by_symbol = {
        str(row.get("symbol") or "").upper(): row
        for row in assets
        if isinstance(row, dict)
    }
    if set(by_symbol) != {REFERENCE_SYMBOL, ALT_SYMBOL}:
        raise AnalysisError("source manifest symbols invalid")

    cycles: dict[str, list[dict[str, Any]]] = {}
    hashes: dict[str, str] = {}
    for symbol in (REFERENCE_SYMBOL, ALT_SYMBOL):
        ledger = source_run_dir / symbol / "tracker" / "cycle_ledger.jsonl"
        if not ledger.is_file():
            raise AnalysisError(f"source ledger missing: {ledger}")
        observed_hash = sha256_file(ledger)
        expected_hash = (
            by_symbol[symbol]
            .get("tracker_artifacts", {})
            .get("cycle_ledger.jsonl", {})
            .get("sha256")
        )
        if observed_hash != expected_hash:
            raise AnalysisError(f"source ledger hash mismatch: {symbol}")
        rows = load_jsonl(ledger)
        for row in rows:
            validate_cycle(row, symbol=symbol)
        rows.sort(key=lambda row: (cycle_start(row), str(row["cycle_id"])))
        cycles[symbol] = rows
        hashes[symbol] = observed_hash
    return manifest, cycles, hashes


def split_render_cycles(render_cycles: Sequence[dict[str, Any]]) -> dict[str, str]:
    ordered = sorted(
        render_cycles,
        key=lambda row: (cycle_start(row), str(row["cycle_id"])),
    )
    discovery_count = int(math.floor(len(ordered) * DISCOVERY_FRACTION))
    return {
        str(row["cycle_id"]): ("discovery" if idx < discovery_count else "holdout")
        for idx, row in enumerate(ordered)
    }


def overlap_seconds(a: dict[str, Any], b: dict[str, Any]) -> float:
    return max(
        0.0,
        (min(cycle_end(a), cycle_end(b)) - max(cycle_start(a), cycle_start(b))).total_seconds(),
    )


def realized_phase(cycle: dict[str, Any], at_ts: datetime) -> float | None:
    start = cycle_start(cycle)
    end = cycle_end(cycle)
    duration = (end - start).total_seconds()
    if duration <= 0 or at_ts < start or at_ts > end:
        return None
    return (at_ts - start).total_seconds() / duration


def best_btc_pair(
    render: dict[str, Any],
    btc_cycles: Sequence[dict[str, Any]],
) -> dict[str, Any] | None:
    candidates: list[tuple[float, float, datetime, str, dict[str, Any]]] = []
    for btc in btc_cycles:
        overlap = overlap_seconds(render, btc)
        if overlap <= 0:
            continue
        candidates.append(
            (
                -overlap,
                abs(days_between(cycle_start(render), cycle_start(btc))),
                cycle_start(btc),
                str(btc["cycle_id"]),
                btc,
            )
        )
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[:4])
    return candidates[0][4]


def build_pair_rows(
    btc_cycles: Sequence[dict[str, Any]],
    render_cycles: Sequence[dict[str, Any]],
    split_by_cycle_id: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    pairs: list[dict[str, Any]] = []
    phases: list[dict[str, Any]] = []
    lags: list[dict[str, Any]] = []
    sequences: list[dict[str, Any]] = []

    for render in sorted(
        render_cycles,
        key=lambda row: (cycle_start(row), str(row["cycle_id"])),
    ):
        render_id = str(render["cycle_id"])
        split = split_by_cycle_id[render_id]
        btc = best_btc_pair(render, btc_cycles)
        if btc is None:
            pairs.append(
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
        render_vector: dict[str, float] = {}
        btc_vector: dict[str, float] = {}
        for checkpoint in PHASE_CHECKPOINTS:
            sample = event_ts(render, checkpoint)
            if sample is None:
                continue
            render_phase = realized_phase(render, sample)
            btc_phase = realized_phase(btc, sample)
            if render_phase is None or btc_phase is None:
                continue
            render_vector[checkpoint] = render_phase
            btc_vector[checkpoint] = btc_phase
            phases.append(
                {
                    "split": split,
                    "render_cycle_id": render_id,
                    "btc_cycle_id": btc_id,
                    "checkpoint": checkpoint,
                    "sample_ts": fmt_ts(sample),
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
            lags.append(
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

        support = [
            key
            for key in PHASE_CHECKPOINTS
            if key in render_vector and key in btc_vector
        ]
        if len(support) >= 2:
            deltas = [abs(render_vector[key] - btc_vector[key]) for key in support]
            changes = [
                deltas[idx] - deltas[idx - 1]
                for idx in range(1, len(deltas))
            ]
            detached_at: int | None = None
            for idx in range(1, len(changes)):
                if changes[idx - 1] > 0 and changes[idx] > 0:
                    detached_at = idx
                    break
            detached = detached_at is not None
            relock = (
                False
                if detached_at is None
                else any(change < 0 for change in changes[detached_at + 1 :])
            )
            sequences.append(
                {
                    "split": split,
                    "render_cycle_id": render_id,
                    "btc_cycle_id": btc_id,
                    "checkpoints": support,
                    "absolute_phase_deltas": deltas,
                    "delta_abs_phase_errors": changes,
                    "net_abs_phase_delta_change": deltas[-1] - deltas[0],
                    "detached_sequence": detached,
                    "relock_sequence": relock,
                }
            )

        pairs.append(
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
                "overlap_days": overlap_seconds(render, btc) / 86400.0,
                "start_lag_days": days_between(cycle_start(render), cycle_start(btc)),
                "end_lag_days": days_between(cycle_end(render), cycle_end(btc)),
                "render_extension_confirmed": bool(render.get("extension_confirmed")),
                "btc_extension_confirmed": bool(btc.get("extension_confirmed")),
                "render_phase_vector": render_vector,
                "btc_phase_vector": btc_vector,
                "phase_support_pattern": support,
                "event_lags_days": event_lags,
            }
        )
    return pairs, phases, lags, sequences


def mean_or_none(values: Sequence[float]) -> float | None:
    return None if not values else float(mean(values))


def rate_or_none(values: Sequence[bool]) -> float | None:
    return None if not values else sum(values) / len(values)


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
            wins += 1.0 if positive > negative else 0.5 if positive == negative else 0.0
    return wins / (len(positives) * len(negatives))


def holm_adjust(raw: dict[str, float | None]) -> dict[str, float | None]:
    valid = sorted((value, key) for key, value in raw.items() if value is not None)
    result: dict[str, float | None] = {key: None for key in raw}
    running = 0.0
    total = len(valid)
    for rank, (value, key) in enumerate(valid):
        running = max(running, min(1.0, value * (total - rank)))
        result[key] = running
    return result


def seed_for(label: str) -> int:
    return RANDOM_SEED + int(hashlib.sha256(label.encode("utf-8")).hexdigest()[:8], 16)


def permutation_p(observed: float, nulls: Sequence[float], *, favorable: str) -> float:
    if len(nulls) != NULL_PERMUTATIONS:
        raise AnalysisError("permutation count mismatch")
    if favorable == "lower":
        extreme = sum(value <= observed for value in nulls)
    elif favorable == "higher":
        extreme = sum(value >= observed for value in nulls)
    else:
        raise ValueError("invalid favorable direction")
    return (1 + extreme) / (NULL_PERMUTATIONS + 1)


def phase_stat_from_vectors(rows: Sequence[dict[str, Any]]) -> float | None:
    values = [
        abs(float(row["render_phase_vector"][key]) - float(row["btc_phase_vector"][key]))
        for row in rows
        for key in row["phase_support_pattern"]
    ]
    return mean_or_none(values)


def sequence_stats_from_vectors(
    rows: Sequence[dict[str, Any]],
) -> tuple[float | None, float | None, float | None, int]:
    nets: list[float] = []
    detached_flags: list[bool] = []
    relock_flags: list[bool] = []
    for row in rows:
        support = list(row["phase_support_pattern"])
        if len(support) < 2:
            continue
        deltas = [
            abs(float(row["render_phase_vector"][key]) - float(row["btc_phase_vector"][key]))
            for key in support
        ]
        changes = [deltas[idx] - deltas[idx - 1] for idx in range(1, len(deltas))]
        detached_at: int | None = None
        for idx in range(1, len(changes)):
            if changes[idx - 1] > 0 and changes[idx] > 0:
                detached_at = idx
                break
        detached = detached_at is not None
        relock = (
            False
            if detached_at is None
            else any(change < 0 for change in changes[detached_at + 1 :])
        )
        nets.append(deltas[-1] - deltas[0])
        detached_flags.append(detached)
        relock_flags.append(relock)
    return mean_or_none(nets), rate_or_none(detached_flags), rate_or_none(relock_flags), len(nets)


def permute_btc_vectors(rows: Sequence[dict[str, Any]], rng: random.Random) -> list[dict[str, Any]]:
    copied = [dict(row) for row in rows]
    groups: dict[tuple[str, ...], list[int]] = {}
    for idx, row in enumerate(copied):
        pattern = tuple(row["phase_support_pattern"])
        if pattern:
            groups.setdefault(pattern, []).append(idx)
    for indices in groups.values():
        vectors = [copied[idx]["btc_phase_vector"] for idx in indices]
        shuffled = list(vectors)
        rng.shuffle(shuffled)
        for idx, vector in zip(indices, shuffled, strict=True):
            copied[idx]["btc_phase_vector"] = vector
    return copied


def phase_null_distribution(rows: Sequence[dict[str, Any]], *, split: str) -> list[float]:
    rng = random.Random(seed_for(f"phase-null:{split}"))
    result: list[float] = []
    for _ in range(NULL_PERMUTATIONS):
        value = phase_stat_from_vectors(permute_btc_vectors(rows, rng))
        if value is None:
            raise AnalysisError(f"phase null lacks support in {split}")
        result.append(value)
    return result


def sequence_null_distributions(rows: Sequence[dict[str, Any]], *, split: str) -> dict[str, list[float]]:
    rng = random.Random(seed_for(f"sequence-null:{split}"))
    result = {"net_change": [], "detached_rate": [], "relock_rate": []}
    for _ in range(NULL_PERMUTATIONS):
        net, detached, relock, _ = sequence_stats_from_vectors(
            permute_btc_vectors(rows, rng)
        )
        if net is None or detached is None or relock is None:
            raise AnalysisError(f"sequence null lacks support in {split}")
        result["net_change"].append(net)
        result["detached_rate"].append(detached)
        result["relock_rate"].append(relock)
    return result


def lag_null_distribution(rows: Sequence[dict[str, Any]], *, split: str, event: str) -> list[float]:
    eligible = [
        row for row in rows if row["split"] == split and row["event"] == event
    ]
    render_times = [
        parse_ts(row["render_event_ts"], field="render_event_ts")
        for row in eligible
    ]
    btc_times = [
        parse_ts(row["btc_event_ts"], field="btc_event_ts")
        for row in eligible
    ]
    assert all(value is not None for value in render_times + btc_times)
    render_values = [value for value in render_times if value is not None]
    btc_values = [value for value in btc_times if value is not None]
    rng = random.Random(seed_for(f"lag-null:{split}:{event}"))
    result: list[float] = []
    for _ in range(NULL_PERMUTATIONS):
        shuffled = list(btc_values)
        rng.shuffle(shuffled)
        lags = [
            days_between(render, btc)
            for render, btc in zip(render_values, shuffled, strict=True)
        ]
        result.append(float(median(lags)))
    return result


def binary_support(labels: Sequence[bool]) -> bool:
    if len(labels) < MIN_BINARY_ROWS_PER_SPLIT:
        return False
    positives = sum(labels)
    return positives >= MIN_BINARY_CLASS_COUNT and len(labels) - positives >= MIN_BINARY_CLASS_COUNT


def conditional_extension_difference(rows: Sequence[dict[str, Any]]) -> float | None:
    yes = [
        bool(row["render_extension_confirmed"])
        for row in rows
        if bool(row["btc_extension_confirmed"])
    ]
    no = [
        bool(row["render_extension_confirmed"])
        for row in rows
        if not bool(row["btc_extension_confirmed"])
    ]
    if not yes or not no:
        return None
    return sum(yes) / len(yes) - sum(no) / len(no)


def extension_null_distribution(rows: Sequence[dict[str, Any]], *, split: str) -> list[float]:
    labels = [bool(row["btc_extension_confirmed"]) for row in rows]
    rng = random.Random(seed_for(f"extension-null:{split}"))
    result: list[float] = []
    for _ in range(NULL_PERMUTATIONS):
        shuffled = list(labels)
        rng.shuffle(shuffled)
        value = conditional_extension_difference(
            [
                dict(row, btc_extension_confirmed=label)
                for row, label in zip(rows, shuffled, strict=True)
            ]
        )
        if value is None:
            raise AnalysisError("extension permutation lost support")
        result.append(value)
    return result


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

    render_ordered = sorted(
        render_cycles,
        key=lambda row: (cycle_start(row), str(row["cycle_id"])),
    )
    rows: list[dict[str, Any]] = []
    for render in render_ordered:
        cycle_id = str(render["cycle_id"])
        outcome_as_of = parse_ts(render.get("outcome_as_of_ts"), field="outcome_as_of_ts")
        assert outcome_as_of is not None
        for checkpoint in PREDICTIVE_ALT_CHECKPOINTS:
            feature_as_of = confirmed_at_ts(render, checkpoint)
            if feature_as_of is None:
                continue
            if outcome_as_of <= feature_as_of:
                continue

            main_pulse_value = bool(render.get("main_pulse_confirmed"))
            extension_value = bool(render.get("extension_confirmed"))
            main_pulse_confirmed_at = confirmed_at_ts(render, "main_pulse")
            extension_confirmed_at = confirmed_at_ts(render, "extension")
            if main_pulse_value and main_pulse_confirmed_at is None:
                raise AnalysisError(
                    f"positive main_pulse_confirmed lacks confirmation timestamp: {cycle_id}"
                )
            if extension_value and extension_confirmed_at is None:
                raise AnalysisError(
                    f"positive extension_confirmed lacks confirmation timestamp: {cycle_id}"
                )

            main_pulse_label_available_at = (
                main_pulse_confirmed_at if main_pulse_value else outcome_as_of
            )
            extension_label_available_at = (
                extension_confirmed_at if extension_value else outcome_as_of
            )
            assert main_pulse_label_available_at is not None
            assert extension_label_available_at is not None
            main_pulse_label_eligible = main_pulse_label_available_at > feature_as_of
            extension_label_eligible = extension_label_available_at > feature_as_of
            if not main_pulse_label_eligible and not extension_label_eligible:
                continue

            latest_main = max(
                (ts for ts in btc_events["main_pulse"] if ts <= feature_as_of),
                default=None,
            )
            latest_extension = max(
                (ts for ts in btc_events["extension"] if ts <= feature_as_of),
                default=None,
            )
            row: dict[str, Any] = {
                "render_cycle_id": cycle_id,
                "split": split_by_cycle_id[cycle_id],
                "checkpoint": checkpoint,
                "feature_as_of_ts": fmt_ts(feature_as_of),
                "outcome_as_of_ts": fmt_ts(outcome_as_of),
                "main_pulse_confirmed": main_pulse_value,
                "extension_confirmed": extension_value,
                "main_pulse_confirmed_label_eligible": main_pulse_label_eligible,
                "extension_confirmed_label_eligible": extension_label_eligible,
                "main_pulse_confirmed_label_available_at_ts": fmt_ts(main_pulse_label_available_at),
                "extension_confirmed_label_available_at_ts": fmt_ts(extension_label_available_at),
                "latest_btc_main_pulse_confirmed_at_ts": None if latest_main is None else fmt_ts(latest_main),
                "latest_btc_extension_confirmed_at_ts": None if latest_extension is None else fmt_ts(latest_extension),
                "btc_main_pulse_recency_score": None if latest_main is None else -days_between(feature_as_of, latest_main),
                "btc_extension_recency_score": None if latest_extension is None else -days_between(feature_as_of, latest_extension),
            }
            prior: list[dict[str, Any]] = []
            for previous in render_ordered:
                if str(previous["cycle_id"]) == cycle_id:
                    continue
                previous_outcome = parse_ts(
                    previous.get("outcome_as_of_ts"),
                    field="outcome_as_of_ts",
                )
                assert previous_outcome is not None
                if previous_outcome < feature_as_of:
                    prior.append(previous)
            for outcome in PREDICTIVE_OUTCOMES:
                values = [bool(previous.get(outcome)) for previous in prior]
                row[f"no_btc_prior_{outcome}"] = (
                    None
                    if len(values) < MIN_PRIOR_RENDER_OUTCOMES
                    else sum(values) / len(values)
                )
                row[f"no_btc_prior_{outcome}_count"] = len(values)
            rows.append(row)
    return rows


def rotation_null_auc(scores: Sequence[float], labels: Sequence[bool], *, label: str) -> list[float]:
    rng = random.Random(seed_for(f"rotation-null:{label}"))
    result: list[float] = []
    for _ in range(NULL_PERMUTATIONS):
        shuffled = list(scores)
        rng.shuffle(shuffled)
        auc = roc_auc(shuffled, labels)
        if auc is None:
            raise AnalysisError("rotation null lost support")
        result.append(auc)
    return result


def summarize_lane_a(
    pair_rows: Sequence[dict[str, Any]],
    phase_rows: Sequence[dict[str, Any]],
    lag_rows: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    paired = [row for row in pair_rows if row.get("paired")]
    cache: dict[str, dict[str, Any]] = {}
    result: dict[str, Any] = {
        "pairing": {
            "render_cycle_count": len(pair_rows),
            "paired_count": len(paired),
            "unpaired_count": len(pair_rows) - len(paired),
        },
        "splits": {},
        "hypotheses": {},
    }

    for split in ("discovery", "holdout"):
        pairs = [row for row in paired if row["split"] == split]
        phases = [row for row in phase_rows if row["split"] == split]
        phase_stat = phase_stat_from_vectors(pairs)
        net, detached, relock, sequence_count = sequence_stats_from_vectors(pairs)
        phase_nulls = (
            phase_null_distribution(pairs, split=split)
            if len(pairs) >= MIN_PAIRED_CYCLES_PER_SPLIT
            and len(phases) >= MIN_EVENT_COMPARISONS_PER_SPLIT
            and phase_stat is not None
            else None
        )
        sequence_nulls = (
            sequence_null_distributions(pairs, split=split)
            if sequence_count >= MIN_SEQUENCE_CYCLES_PER_SPLIT
            else None
        )
        cache[split] = {
            "pairs": pairs,
            "phases": phases,
            "phase_stat": phase_stat,
            "phase_nulls": phase_nulls,
            "net": net,
            "detached": detached,
            "relock": relock,
            "sequence_count": sequence_count,
            "sequence_nulls": sequence_nulls,
        }
        result["splits"][split] = {
            "paired_count": len(pairs),
            "phase_value_count": len(phases),
            "sequence_count": sequence_count,
            "mean_absolute_phase_delta": phase_stat,
            "mean_net_abs_phase_delta_change": net,
            "detached_sequence_rate": detached,
            "relock_sequence_rate": relock,
        }

    if any(cache[split]["phase_nulls"] is None for split in ("discovery", "holdout")):
        result["hypotheses"]["PHASE_LOCK"] = {"status": "INSUFFICIENT_EVIDENCE"}
    else:
        discovery = cache["discovery"]
        holdout = cache["holdout"]
        p_value = permutation_p(
            holdout["phase_stat"],
            holdout["phase_nulls"],
            favorable="lower",
        )
        supported = (
            discovery["phase_stat"] < median(discovery["phase_nulls"])
            and holdout["phase_stat"] < median(holdout["phase_nulls"])
            and p_value < ALPHA
        )
        result["hypotheses"]["PHASE_LOCK"] = {
            "status": "SUPPORTED_STRUCTURAL" if supported else "NOT_SUPPORTED",
            "discovery_mean_absolute_phase_delta": discovery["phase_stat"],
            "discovery_null_median": median(discovery["phase_nulls"]),
            "holdout_mean_absolute_phase_delta": holdout["phase_stat"],
            "holdout_null_median": median(holdout["phase_nulls"]),
            "holdout_p_value": p_value,
        }

    lag_tests: dict[str, dict[str, Any]] = {}
    raw_lag: dict[str, float | None] = {}
    sufficient_events = 0
    for event in PHASE_CHECKPOINTS:
        discovery_rows = [
            row
            for row in lag_rows
            if row["split"] == "discovery" and row["event"] == event
        ]
        holdout_rows = [
            row
            for row in lag_rows
            if row["split"] == "holdout" and row["event"] == event
        ]
        if (
            len(discovery_rows) < MIN_EVENT_COMPARISONS_PER_SPLIT
            or len(holdout_rows) < MIN_EVENT_COMPARISONS_PER_SPLIT
        ):
            lag_tests[event] = {
                "status": "INSUFFICIENT_EVIDENCE",
                "discovery_n": len(discovery_rows),
                "holdout_n": len(holdout_rows),
            }
            raw_lag[event] = None
            continue

        sufficient_events += 1
        discovery_median = float(median(float(row["event_lag_days"]) for row in discovery_rows))
        holdout_median = float(median(float(row["event_lag_days"]) for row in holdout_rows))
        direction = (
            "NONE"
            if discovery_median == 0
            else "LAGGING"
            if discovery_median > 0
            else "LEADING"
        )
        raw_p = (
            1.0
            if direction == "NONE"
            else permutation_p(
                holdout_median,
                lag_null_distribution(lag_rows, split="holdout", event=event),
                favorable="higher" if direction == "LAGGING" else "lower",
            )
        )
        raw_lag[event] = raw_p
        lag_tests[event] = {
            "status": "TESTED",
            "direction_from_discovery": direction,
            "discovery_n": len(discovery_rows),
            "holdout_n": len(holdout_rows),
            "discovery_median_lag_days": discovery_median,
            "holdout_median_lag_days": holdout_median,
            "holdout_p_value_raw": raw_p,
        }

    adjusted_lag = holm_adjust(raw_lag)
    significant_directions: list[str] = []
    for event, test in lag_tests.items():
        test["holdout_p_value_adjusted"] = adjusted_lag[event]
        if test["status"] != "TESTED":
            continue
        direction = test["direction_from_discovery"]
        holdout_median = test["holdout_median_lag_days"]
        same_direction = (
            (direction == "LAGGING" and holdout_median > 0)
            or (direction == "LEADING" and holdout_median < 0)
        )
        rejected = bool(
            same_direction
            and adjusted_lag[event] is not None
            and adjusted_lag[event] < ALPHA
        )
        test["same_direction_holdout"] = same_direction
        test["reject_at_alpha"] = rejected
        if rejected:
            significant_directions.append(direction)

    lag_status = (
        "INSUFFICIENT_EVIDENCE"
        if sufficient_events < MIN_SIGNIFICANT_LAG_EVENTS
        else significant_directions[0]
        if len(significant_directions) >= MIN_SIGNIFICANT_LAG_EVENTS
        and len(set(significant_directions)) == 1
        else "NOT_SUPPORTED"
    )
    result["hypotheses"]["LEADING_LAGGING"] = {
        "status": lag_status,
        "statistic": "median_signed_same_event_lag_days",
        "events": lag_tests,
    }

    sequence_sufficient = all(
        cache[split]["sequence_nulls"] is not None
        for split in ("discovery", "holdout")
    )
    if not sequence_sufficient:
        result["hypotheses"]["CONVERGING_DIVERGING"] = {
            "status": "INSUFFICIENT_EVIDENCE"
        }
        result["hypotheses"]["DETACHED_RELOCK"] = {
            "DETACHED": {"status": "INSUFFICIENT_EVIDENCE"},
            "RELOCK": {"status": "INSUFFICIENT_EVIDENCE"},
        }
    else:
        discovery = cache["discovery"]
        holdout = cache["holdout"]
        discovery_net = discovery["net"]
        holdout_net = holdout["net"]
        assert discovery_net is not None and holdout_net is not None
        direction = (
            "NONE"
            if discovery_net == 0
            else "CONVERGING"
            if discovery_net < 0
            else "DIVERGING"
        )
        if direction == "NONE":
            convergence = {
                "status": "NOT_SUPPORTED",
                "discovery_mean_net_change": discovery_net,
                "holdout_mean_net_change": holdout_net,
            }
        else:
            p_value = permutation_p(
                holdout_net,
                holdout["sequence_nulls"]["net_change"],
                favorable="lower" if direction == "CONVERGING" else "higher",
            )
            same = (
                (direction == "CONVERGING" and holdout_net < 0)
                or (direction == "DIVERGING" and holdout_net > 0)
            )
            convergence = {
                "status": direction if same and p_value < ALPHA else "NOT_SUPPORTED",
                "discovery_mean_net_change": discovery_net,
                "holdout_mean_net_change": holdout_net,
                "holdout_p_value": p_value,
            }
        result["hypotheses"]["CONVERGING_DIVERGING"] = convergence

        raw_seq: dict[str, float | None] = {}
        seq_tests: dict[str, dict[str, Any]] = {}
        for name, field, null_key in (
            ("DETACHED", "detached", "detached_rate"),
            ("RELOCK", "relock", "relock_rate"),
        ):
            raw_p = permutation_p(
                holdout[field],
                holdout["sequence_nulls"][null_key],
                favorable="higher",
            )
            raw_seq[name] = raw_p
            seq_tests[name] = {
                "status": "TESTED",
                "discovery_rate": discovery[field],
                "discovery_null_median": median(discovery["sequence_nulls"][null_key]),
                "holdout_rate": holdout[field],
                "holdout_null_median": median(holdout["sequence_nulls"][null_key]),
                "holdout_p_value_raw": raw_p,
            }
        adjusted_seq = holm_adjust(raw_seq)
        for name, test in seq_tests.items():
            test["holdout_p_value_adjusted"] = adjusted_seq[name]
            supported = (
                test["discovery_rate"] > test["discovery_null_median"]
                and test["holdout_rate"] > test["holdout_null_median"]
                and adjusted_seq[name] is not None
                and adjusted_seq[name] < ALPHA
            )
            test["status"] = "SUPPORTED_STRUCTURAL" if supported else "NOT_SUPPORTED"
        result["hypotheses"]["DETACHED_RELOCK"] = seq_tests

    extension_data: dict[str, dict[str, Any]] = {}
    extension_sufficient = True
    for split in ("discovery", "holdout"):
        rows = [row for row in paired if row["split"] == split]
        btc_labels = [bool(row["btc_extension_confirmed"]) for row in rows]
        render_labels = [bool(row["render_extension_confirmed"]) for row in rows]
        sufficient = binary_support(btc_labels) and binary_support(render_labels)
        extension_sufficient = extension_sufficient and sufficient
        extension_data[split] = {
            "rows": rows,
            "n": len(rows),
            "btc_extension_count": sum(btc_labels),
            "render_extension_count": sum(render_labels),
            "difference": conditional_extension_difference(rows),
            "sufficient": sufficient,
        }
    public_extension = {
        split: {key: value for key, value in data.items() if key != "rows"}
        for split, data in extension_data.items()
    }
    if not extension_sufficient:
        extension_test = {
            "status": "INSUFFICIENT_EVIDENCE",
            "splits": public_extension,
            "authority": "LANE_A_ASSOCIATION_ONLY",
        }
    else:
        discovery_diff = extension_data["discovery"]["difference"]
        holdout_diff = extension_data["holdout"]["difference"]
        assert discovery_diff is not None and holdout_diff is not None
        p_value = permutation_p(
            holdout_diff,
            extension_null_distribution(extension_data["holdout"]["rows"], split="holdout"),
            favorable="higher",
        )
        supported = discovery_diff > 0 and holdout_diff > 0 and p_value < ALPHA
        extension_test = {
            "status": "SUPPORTED_ASSOCIATION" if supported else "NOT_SUPPORTED",
            "authority": "LANE_A_ASSOCIATION_ONLY",
            "discovery_difference": discovery_diff,
            "holdout_difference": holdout_diff,
            "holdout_p_value": p_value,
            "splits": public_extension,
        }
    result["hypotheses"]["SHARED_EXTENSION"] = extension_test
    return result


def summarize_lane_b(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    tests: dict[str, dict[str, Any]] = {}
    raw_p: dict[str, float | None] = {}
    for checkpoint in PREDICTIVE_ALT_CHECKPOINTS:
        for feature in ROTATION_FEATURES:
            for outcome in PREDICTIVE_OUTCOMES:
                key = f"{checkpoint}|{feature}|{outcome}"
                by_split: dict[str, list[dict[str, Any]]] = {}
                metrics: dict[str, dict[str, Any]] = {}
                sufficient = True
                for split in ("discovery", "holdout"):
                    eligible = [
                        row
                        for row in rows
                        if row["split"] == split
                        and row["checkpoint"] == checkpoint
                        and row.get(f"{outcome}_label_eligible") is True
                        and row.get(feature) is not None
                        and row.get(f"no_btc_prior_{outcome}") is not None
                    ]
                    by_split[split] = eligible
                    labels = [bool(row[outcome]) for row in eligible]
                    support = binary_support(labels)
                    sufficient = sufficient and support
                    scores = [float(row[feature]) for row in eligible]
                    baselines = [
                        float(row[f"no_btc_prior_{outcome}"])
                        for row in eligible
                    ]
                    metrics[split] = {
                        "n": len(eligible),
                        "positive_count": sum(labels),
                        "negative_count": len(labels) - sum(labels),
                        "btc_auc": roc_auc(scores, labels) if support else None,
                        "no_btc_prior_auc": roc_auc(baselines, labels) if support else None,
                        "sufficient": support,
                    }
                if not sufficient:
                    tests[key] = {
                        "checkpoint": checkpoint,
                        "feature": feature,
                        "outcome": outcome,
                        "status": "INSUFFICIENT_EVIDENCE",
                        "splits": metrics,
                    }
                    raw_p[key] = None
                    continue

                discovery_scores = [float(row[feature]) for row in by_split["discovery"]]
                discovery_labels = [bool(row[outcome]) for row in by_split["discovery"]]
                holdout_scores = [float(row[feature]) for row in by_split["holdout"]]
                holdout_labels = [bool(row[outcome]) for row in by_split["holdout"]]
                discovery_auc = roc_auc(discovery_scores, discovery_labels)
                holdout_auc = roc_auc(holdout_scores, holdout_labels)
                assert discovery_auc is not None and holdout_auc is not None
                p_value = permutation_p(
                    holdout_auc,
                    rotation_null_auc(holdout_scores, holdout_labels, label=key),
                    favorable="higher",
                )
                raw_p[key] = p_value
                tests[key] = {
                    "checkpoint": checkpoint,
                    "feature": feature,
                    "outcome": outcome,
                    "status": "TESTED",
                    "splits": metrics,
                    "discovery_auc": discovery_auc,
                    "holdout_auc": holdout_auc,
                    "holdout_no_btc_prior_auc": metrics["holdout"]["no_btc_prior_auc"],
                    "holdout_p_value_raw": p_value,
                }

    adjusted = holm_adjust(raw_p)
    supported: list[str] = []
    sufficient_count = 0
    for key, test in tests.items():
        test["holdout_p_value_adjusted"] = adjusted[key]
        if test["status"] != "TESTED":
            continue
        sufficient_count += 1
        baseline = test["holdout_no_btc_prior_auc"]
        passes = (
            test["discovery_auc"] > 0.5
            and test["holdout_auc"] > 0.5
            and baseline is not None
            and test["holdout_auc"] > baseline
            and adjusted[key] is not None
            and adjusted[key] < ALPHA
        )
        test["reject_at_alpha"] = passes
        test["status"] = "SUPPORTED" if passes else "NOT_SUPPORTED"
        if passes:
            supported.append(key)

    verdict = (
        "ROTATION_CANDIDATE"
        if supported
        else "INSUFFICIENT_EVIDENCE"
        if sufficient_count == 0
        else "NOT_SUPPORTED"
    )
    return {
        "walk_forward_definition": "expanding prior RENDER outcomes and prior-confirmed BTC events at each checkpoint",
        "row_count": len(rows),
        "tests": tests,
        "verdict": verdict,
        "supported_tests": supported,
        "authority": "LANE_B_PIT_PREDICTIVE_TEST",
    }


def derive_overall_verdict(lane_a: dict[str, Any], lane_b: dict[str, Any]) -> dict[str, Any]:
    hypotheses = lane_a["hypotheses"]
    predictive = lane_b.get("verdict") == "ROTATION_CANDIDATE"
    structural = (
        hypotheses["PHASE_LOCK"].get("status") == "SUPPORTED_STRUCTURAL"
        or hypotheses["LEADING_LAGGING"].get("status") in {"LEADING", "LAGGING"}
        or hypotheses["CONVERGING_DIVERGING"].get("status") in {"CONVERGING", "DIVERGING"}
        or any(
            test.get("status") == "SUPPORTED_STRUCTURAL"
            for test in hypotheses["DETACHED_RELOCK"].values()
        )
        or hypotheses["SHARED_EXTENSION"].get("status") == "SUPPORTED_ASSOCIATION"
    )
    overall = (
        "POSITIVE_RESEARCH_EVIDENCE"
        if predictive
        else "STRUCTURAL_EVIDENCE_ONLY"
        if structural
        else "UNRELATED"
    )
    return {
        "overall_verdict": overall,
        "predictive_evidence_source": "ROTATION_CANDIDATE" if predictive else None,
        "runtime_promotion": False,
        "selection_engine_authority": False,
        "decision_gate_authority": False,
        "execution_authority": False,
    }


def run_analysis(source_run_dir: Path) -> dict[str, Any]:
    source_manifest, cycles, ledger_hashes = validate_source_run(source_run_dir)
    split = split_render_cycles(cycles[ALT_SYMBOL])
    pair_rows, phase_rows, lag_rows, sequence_rows = build_pair_rows(
        cycles[REFERENCE_SYMBOL],
        cycles[ALT_SYMBOL],
        split,
    )
    lane_a = summarize_lane_a(pair_rows, phase_rows, lag_rows)
    lane_b_rows = build_lane_b_rows(cycles[REFERENCE_SYMBOL], cycles[ALT_SYMBOL], split)
    lane_b = summarize_lane_b(lane_b_rows)
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
        "verdict": derive_overall_verdict(lane_a, lane_b),
    }


def persist_analysis(
    *,
    analysis: dict[str, Any],
    source_run_dir: Path,
    out_root: Path,
    run_id: str,
    cli_args: list[str],
) -> Path:
    frozen_run_id = validate_run_id(run_id)
    run_dir = out_root / frozen_run_id
    if run_dir.exists():
        raise FileExistsError(f"immutable analysis run already exists: {run_dir}")
    root = repo_root()
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
        write_jsonl(
            run_dir / "lane_b_tests.jsonl",
            [
                dict(test_id=key, **value)
                for key, value in analysis["lane_b"]["tests"].items()
            ],
        )
        write_json(run_dir / "lane_b_summary.json", analysis["lane_b"])
        write_json(run_dir / "summary.json", analysis["verdict"])
        artifact_hashes = {
            path.name: sha256_file(path)
            for path in sorted(run_dir.iterdir())
            if path.is_file() and path.name != "run_manifest.json"
        }
        source_manifest = analysis["source_manifest"]
        manifest = {
            "runner_name": RUNNER_NAME,
            "runner_version": RUNNER_VERSION,
            "run_id": frozen_run_id,
            "run_ts_utc": fmt_ts(datetime.now(UTC)),
            "research_only": True,
            "market_only": True,
            "account_awareness": 0,
            "relationship_analysis_performed": True,
            "reference_symbol": REFERENCE_SYMBOL,
            "alt_symbol": ALT_SYMBOL,
            "venue": VENUE,
            "interval_code": INTERVAL_CODE,
            "analysis_commit_sha": git_output(["rev-parse", "HEAD"]),
            "analyzer_source_sha256": sha256_file(Path(__file__).resolve()),
            "registry_name": REGISTRY_NAME,
            "registry_version": REGISTRY_VERSION,
            "registry_source_sha256": sha256_file(root / REGISTRY_PATH),
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
            "cli": [
                sys.executable,
                "-m",
                "src.research.run_breathline_btc_render_relationship_analysis_v1",
                *cli_args,
            ],
            "output_artifact_sha256": artifact_hashes,
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
    run_id = validate_run_id(args.run_id)
    started = time.monotonic()
    print(
        "STARTED",
        RUNNER_NAME,
        f"run_id={run_id}",
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
            run_id=run_id,
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
