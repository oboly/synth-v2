"""Continuous bullish Breathline tracker v1.

Research-only, market-only, account-agnostic. The tracker discovers observed bullish
breaths from point-in-time confirmed pivots, keeps cycle boundaries event-driven rather
than forcing 21-day resets, and evaluates preregistered recognition/ignition phase grids
without using future outcomes as checkpoint-time inputs.

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

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Iterable, Sequence

MODEL_VERSION = "bullish-breathline-tracker-v1.0.0"
NOMINAL_CYCLE_DAYS = 21.0

RECOGNITION_RATIO_GRID: tuple[float, ...] = (
    0.55,
    0.58,
    0.60,
    0.618,
    0.64,
    0.66,
    0.68,
    0.70,
    0.72,
)
IGNITION_RATIO_GRID: tuple[float, ...] = (0.72, 0.74, 0.76, 0.786, 0.80, 0.82)
NORMAL_PHASE_OFFSETS_DAYS: tuple[float, ...] = (-9, -7, -5, -3, 0, 3, 5, 7, 9)
HALF_PHASE_SPLIT_CANDIDATE_DAYS = 10.5
BASELINE_RATIOS: dict[str, float] = {
    "first_high": 0.236,
    "first_low": 0.382,
    "second_high": 0.500,
    "recognition": 0.618,
    "ignition": 0.786,
    "main_pulse": 1.000,
    "extension": 1.272,
}


@dataclass(frozen=True)
class CandleObservation:
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None


@dataclass(frozen=True)
class ConfirmedPivot:
    kind: str
    pivot_ts: datetime
    confirmed_at_ts: datetime
    price: float
    source_index: int


@dataclass(frozen=True)
class VolumeSnapshot:
    as_of_ts: datetime
    latest_volume: float | None
    trailing_mean_volume: float | None
    volume_ratio: float | None


@dataclass(frozen=True)
class CycleRecord:
    cycle_id: str
    symbol: str
    previous_cycle_id: str | None
    start_ts: datetime
    end_ts: datetime
    cycle_status: str
    observed_cycle_length_days: float
    phase_offset_days: float
    previous_phase_offset_days: float | None
    phase_drift_days: float | None
    first_high_ts: datetime
    first_high_price: float
    first_low_ts: datetime
    first_low_price: float
    second_high_ts: datetime
    second_high_price: float
    recognition_ts: datetime
    recognition_price: float
    ignition_ts: datetime | None
    ignition_price: float | None
    main_pulse_ts: datetime | None
    main_pulse_price: float | None
    extension_ts: datetime | None
    extension_price: float | None
    recognition_confirmed_at_ts: datetime
    ignition_confirmed_at_ts: datetime | None
    main_pulse_confirmed_at_ts: datetime | None
    extension_confirmed_at_ts: datetime | None
    recognition_progress_ratio: float
    ignition_progress_ratio: float | None
    recognition_ratio_used: float
    ignition_ratio_used: float | None
    recognition_state: str
    ignition_state: str
    extension_runner_state: str
    higher_low_confirmed: bool
    main_pulse_confirmed: bool
    extension_confirmed: bool
    expected_node_ts: dict[str, str]
    timing_error_days: dict[str, float | None]
    recognition_volume_snapshot: VolumeSnapshot
    ignition_volume_snapshot: VolumeSnapshot | None
    main_pulse_volume_snapshot: VolumeSnapshot | None
    reset_reason: str | None
    phase_shift_reason: str | None
    feature_as_of_ts: datetime
    outcome_as_of_ts: datetime
    research_only: bool = True


@dataclass(frozen=True)
class CandidateEvidence:
    ratio: float
    matched_count: int
    continuation_count: int
    extension_count: int
    false_extension_count: int
    continuation_probability: float | None
    extension_probability: float | None
    false_extension_rate: float | None
    mean_mfe_pct: float | None
    mean_mae_pct: float | None
    mean_time_to_main_pulse_days: float | None
    mean_time_to_extension_days: float | None


@dataclass(frozen=True)
class CalibrationResult:
    checkpoint: str
    frozen_grid: tuple[float, ...]
    discovery_cycle_ids: tuple[str, ...]
    holdout_cycle_ids: tuple[str, ...]
    evidence: tuple[CandidateEvidence, ...]
    selected_ratio: float | None
    holdout_continuation_probability: float | None
    holdout_extension_probability: float | None


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _iso(dt: datetime) -> str:
    return _utc(dt).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _days(delta: timedelta) -> float:
    return delta.total_seconds() / 86400.0


def validate_frozen_contract() -> None:
    if HALF_PHASE_SPLIT_CANDIDATE_DAYS in NORMAL_PHASE_OFFSETS_DAYS:
        raise ValueError("±10.5 must not appear in the normal phase-offset grid")
    if -HALF_PHASE_SPLIT_CANDIDATE_DAYS in NORMAL_PHASE_OFFSETS_DAYS:
        raise ValueError("±10.5 must not appear in the normal phase-offset grid")
    if tuple(sorted(RECOGNITION_RATIO_GRID)) != RECOGNITION_RATIO_GRID:
        raise ValueError("recognition ratio grid must be ordered and frozen")
    if tuple(sorted(IGNITION_RATIO_GRID)) != IGNITION_RATIO_GRID:
        raise ValueError("ignition ratio grid must be ordered and frozen")


validate_frozen_contract()


def detect_confirmed_pivots(
    candles: Sequence[CandleObservation], *, left_bars: int = 2, right_bars: int = 2
) -> list[ConfirmedPivot]:
    """Detect local extrema only when their right-side confirmation bars exist.

    `confirmed_at_ts` is deliberately later than (or equal to) the pivot timestamp.
    A replay that consumes pivots by confirmed_at_ts therefore cannot backdate a pivot.
    """
    if left_bars < 1 or right_bars < 1:
        raise ValueError("pivot confirmation requires at least one bar on each side")
    ordered = sorted(candles, key=lambda row: row.ts)
    pivots: list[ConfirmedPivot] = []
    for idx in range(left_bars, len(ordered) - right_bars):
        row = ordered[idx]
        left = ordered[idx - left_bars : idx]
        right = ordered[idx + 1 : idx + 1 + right_bars]
        high_is_pivot = all(row.high > other.high for other in (*left, *right))
        low_is_pivot = all(row.low < other.low for other in (*left, *right))
        confirmed_at = _utc(ordered[idx + right_bars].ts)
        if high_is_pivot:
            pivots.append(
                ConfirmedPivot("HIGH", _utc(row.ts), confirmed_at, float(row.high), idx)
            )
        if low_is_pivot:
            pivots.append(
                ConfirmedPivot("LOW", _utc(row.ts), confirmed_at, float(row.low), idx)
            )
    return sorted(pivots, key=lambda pivot: (pivot.pivot_ts, pivot.kind))


def _volume_snapshot(
    candles: Sequence[CandleObservation], as_of_ts: datetime, *, lookback: int = 5
) -> VolumeSnapshot:
    available = [row for row in candles if _utc(row.ts) <= _utc(as_of_ts)]
    volumes = [float(row.volume) for row in available[-lookback:] if row.volume is not None]
    latest = None if not available or available[-1].volume is None else float(available[-1].volume)
    trailing = mean(volumes) if volumes else None
    ratio = None if latest is None or not trailing else latest / trailing
    return VolumeSnapshot(_utc(as_of_ts), latest, trailing, ratio)


def _closest_offset_days(start_ts: datetime, recognition_ts: datetime) -> float:
    observed = _days(_utc(recognition_ts) - _utc(start_ts))
    baseline = NOMINAL_CYCLE_DAYS * BASELINE_RATIOS["recognition"]
    residual = observed - baseline
    return min(NORMAL_PHASE_OFFSETS_DAYS, key=lambda candidate: abs(candidate - residual))


def _closest_ratio(progress_ratio: float, grid: Sequence[float]) -> float:
    return min(grid, key=lambda candidate: abs(candidate - progress_ratio))


def _expected_nodes(start_ts: datetime) -> dict[str, str]:
    return {
        name: _iso(_utc(start_ts) + timedelta(days=NOMINAL_CYCLE_DAYS * ratio))
        for name, ratio in BASELINE_RATIOS.items()
    }


def _timing_errors(
    start_ts: datetime,
    nodes: dict[str, datetime | None],
) -> dict[str, float | None]:
    errors: dict[str, float | None] = {}
    for name, ratio in BASELINE_RATIOS.items():
        observed = nodes.get(name)
        if observed is None:
            errors[name] = None
            continue
        expected = _utc(start_ts) + timedelta(days=NOMINAL_CYCLE_DAYS * ratio)
        errors[name] = round(_days(_utc(observed) - expected), 6)
    return errors


def _cycle_id(symbol: str, start_ts: datetime, recognition_ts: datetime) -> str:
    raw = f"{MODEL_VERSION}|{symbol}|{_iso(start_ts)}|{_iso(recognition_ts)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def extract_bullish_cycles(
    symbol: str,
    candles: Sequence[CandleObservation],
    pivots: Sequence[ConfirmedPivot] | None = None,
) -> list[CycleRecord]:
    """Extract non-overlapping bullish breaths from observed pivot transitions.

    Pattern: start low -> first high -> first low -> second high -> higher low.
    The next confirmed high is ignition evidence. A later higher confirmed high is the
    main pulse; a subsequent higher confirmed high is extension evidence. Cycle end is
    the last evidence timestamp consumed before the next observed start candidate.
    There is no `start + 21d` reset.
    """
    ordered_pivots = list(pivots or detect_confirmed_pivots(candles))
    ordered_pivots.sort(key=lambda pivot: (pivot.pivot_ts, pivot.kind))
    cycles: list[CycleRecord] = []
    cursor = 0
    previous_cycle_id: str | None = None
    previous_offset: float | None = None

    while cursor + 4 < len(ordered_pivots):
        found: tuple[int, list[ConfirmedPivot]] | None = None
        for idx in range(cursor, len(ordered_pivots) - 4):
            seq = ordered_pivots[idx : idx + 5]
            if [pivot.kind for pivot in seq] != ["LOW", "HIGH", "LOW", "HIGH", "LOW"]:
                continue
            start, first_high, first_low, second_high, recognition = seq
            if not (
                first_high.price > start.price
                and first_low.price > start.price
                and second_high.price > first_low.price
                and recognition.price > first_low.price
                and recognition.price < second_high.price
            ):
                continue
            found = (idx, seq)
            break
        if found is None:
            break

        idx, seq = found
        start, first_high, first_low, second_high, recognition = seq
        ignition: ConfirmedPivot | None = None
        main_pulse: ConfirmedPivot | None = None
        extension: ConfirmedPivot | None = None
        next_start_idx: int | None = None

        for look in range(idx + 5, len(ordered_pivots)):
            pivot = ordered_pivots[look]
            if ignition is None and pivot.kind == "HIGH":
                ignition = pivot
                continue
            if ignition is not None and main_pulse is None and pivot.kind == "HIGH" and pivot.price > second_high.price:
                main_pulse = pivot
                continue
            if main_pulse is not None and extension is None and pivot.kind == "HIGH" and pivot.price > main_pulse.price:
                extension = pivot
                continue
            if look + 4 < len(ordered_pivots):
                candidate = ordered_pivots[look : look + 5]
                if [item.kind for item in candidate] == ["LOW", "HIGH", "LOW", "HIGH", "LOW"]:
                    a, b, c, d, e = candidate
                    if b.price > a.price and c.price > a.price and d.price > c.price and e.price > c.price and e.price < d.price:
                        next_start_idx = look
                        break

        end_pivot = extension or main_pulse or ignition or recognition
        if next_start_idx is not None:
            next_start_ts = ordered_pivots[next_start_idx].pivot_ts
            evidence = [item for item in (extension, main_pulse, ignition, recognition) if item is not None and item.pivot_ts < next_start_ts]
            end_pivot = max(evidence, key=lambda item: item.confirmed_at_ts) if evidence else recognition

        recognition_progress = _days(recognition.pivot_ts - start.pivot_ts) / NOMINAL_CYCLE_DAYS
        ignition_progress = (
            None
            if ignition is None
            else _days(ignition.pivot_ts - start.pivot_ts) / NOMINAL_CYCLE_DAYS
        )
        recognition_ratio = _closest_ratio(recognition_progress, RECOGNITION_RATIO_GRID)
        ignition_ratio = None if ignition_progress is None else _closest_ratio(ignition_progress, IGNITION_RATIO_GRID)
        offset = float(_closest_offset_days(start.pivot_ts, recognition.pivot_ts))
        drift = None if previous_offset is None else round(offset - previous_offset, 6)
        phase_shift_reason = None
        if drift is not None and abs(drift) >= 6:
            phase_shift_reason = "NORMAL_OFFSET_GRID_DRIFT_GE_6D"

        main_confirmed = main_pulse is not None
        extension_confirmed = extension is not None
        if extension_confirmed:
            extension_state = "ACTIVE"
        elif main_confirmed:
            extension_state = "BUILDING"
        elif ignition is not None:
            extension_state = "BUILDING"
        else:
            extension_state = "NONE"

        status = "OBSERVED"
        reset_reason = None
        if ignition is None:
            status = "UNCLEAR"
            reset_reason = "NO_IGNITION_BEFORE_NEXT_TRANSITION_OR_DATA_END"
        elif not main_confirmed:
            status = "FAILED"
            reset_reason = "NO_MAIN_PULSE_CONFIRMATION"

        nodes: dict[str, datetime | None] = {
            "first_high": first_high.pivot_ts,
            "first_low": first_low.pivot_ts,
            "second_high": second_high.pivot_ts,
            "recognition": recognition.pivot_ts,
            "ignition": None if ignition is None else ignition.pivot_ts,
            "main_pulse": None if main_pulse is None else main_pulse.pivot_ts,
            "extension": None if extension is None else extension.pivot_ts,
        }
        cid = _cycle_id(symbol, start.pivot_ts, recognition.pivot_ts)
        feature_as_of = ignition.confirmed_at_ts if ignition is not None else recognition.confirmed_at_ts
        outcome_as_of = end_pivot.confirmed_at_ts

        record = CycleRecord(
            cycle_id=cid,
            symbol=symbol,
            previous_cycle_id=previous_cycle_id,
            start_ts=start.pivot_ts,
            end_ts=end_pivot.pivot_ts,
            cycle_status=status,
            observed_cycle_length_days=round(_days(end_pivot.pivot_ts - start.pivot_ts), 6),
            phase_offset_days=offset,
            previous_phase_offset_days=previous_offset,
            phase_drift_days=drift,
            first_high_ts=first_high.pivot_ts,
            first_high_price=first_high.price,
            first_low_ts=first_low.pivot_ts,
            first_low_price=first_low.price,
            second_high_ts=second_high.pivot_ts,
            second_high_price=second_high.price,
            recognition_ts=recognition.pivot_ts,
            recognition_price=recognition.price,
            ignition_ts=None if ignition is None else ignition.pivot_ts,
            ignition_price=None if ignition is None else ignition.price,
            main_pulse_ts=None if main_pulse is None else main_pulse.pivot_ts,
            main_pulse_price=None if main_pulse is None else main_pulse.price,
            extension_ts=None if extension is None else extension.pivot_ts,
            extension_price=None if extension is None else extension.price,
            recognition_confirmed_at_ts=recognition.confirmed_at_ts,
            ignition_confirmed_at_ts=None if ignition is None else ignition.confirmed_at_ts,
            main_pulse_confirmed_at_ts=None if main_pulse is None else main_pulse.confirmed_at_ts,
            extension_confirmed_at_ts=None if extension is None else extension.confirmed_at_ts,
            recognition_progress_ratio=round(recognition_progress, 6),
            ignition_progress_ratio=None if ignition_progress is None else round(ignition_progress, 6),
            recognition_ratio_used=recognition_ratio,
            ignition_ratio_used=ignition_ratio,
            recognition_state="CONFIRMED",
            ignition_state="ACTIVE" if ignition is not None else "NOT_OBSERVED",
            extension_runner_state=extension_state,
            higher_low_confirmed=True,
            main_pulse_confirmed=main_confirmed,
            extension_confirmed=extension_confirmed,
            expected_node_ts=_expected_nodes(start.pivot_ts),
            timing_error_days=_timing_errors(start.pivot_ts, nodes),
            recognition_volume_snapshot=_volume_snapshot(candles, recognition.confirmed_at_ts),
            ignition_volume_snapshot=None if ignition is None else _volume_snapshot(candles, ignition.confirmed_at_ts),
            main_pulse_volume_snapshot=None if main_pulse is None else _volume_snapshot(candles, main_pulse.confirmed_at_ts),
            reset_reason=reset_reason,
            phase_shift_reason=phase_shift_reason,
            feature_as_of_ts=feature_as_of,
            outcome_as_of_ts=outcome_as_of,
        )
        if record.feature_as_of_ts > record.outcome_as_of_ts:
            raise AssertionError("checkpoint feature timestamp cannot exceed outcome timestamp")
        cycles.append(record)
        previous_cycle_id = cid
        previous_offset = offset
        cursor = next_start_idx if next_start_idx is not None else idx + 5

    return cycles


def _checkpoint_progress(cycle: CycleRecord, checkpoint: str) -> float | None:
    if checkpoint == "recognition":
        return cycle.recognition_progress_ratio
    if checkpoint == "ignition":
        return cycle.ignition_progress_ratio
    raise ValueError(f"unsupported checkpoint: {checkpoint}")


def _future_metrics(cycle: CycleRecord, checkpoint: str) -> tuple[float | None, float | None, float | None, float | None]:
    checkpoint_price = cycle.recognition_price if checkpoint == "recognition" else cycle.ignition_price
    checkpoint_ts = cycle.recognition_ts if checkpoint == "recognition" else cycle.ignition_ts
    if checkpoint_price is None or checkpoint_ts is None:
        return None, None, None, None
    future_prices = [value for value in (cycle.main_pulse_price, cycle.extension_price) if value is not None]
    mfe = None if not future_prices else (max(future_prices) / checkpoint_price - 1.0) * 100.0
    downside_prices = [value for value in (cycle.recognition_price, cycle.first_low_price) if value is not None]
    mae = None if not downside_prices else (min(downside_prices) / checkpoint_price - 1.0) * 100.0
    time_to_main = None if cycle.main_pulse_ts is None else _days(cycle.main_pulse_ts - checkpoint_ts)
    time_to_extension = None if cycle.extension_ts is None else _days(cycle.extension_ts - checkpoint_ts)
    return mfe, mae, time_to_main, time_to_extension


def _evidence_for_ratio(
    cycles: Sequence[CycleRecord], checkpoint: str, ratio: float, *, tolerance_ratio: float
) -> CandidateEvidence:
    matched = [
        cycle
        for cycle in cycles
        if (progress := _checkpoint_progress(cycle, checkpoint)) is not None
        and abs(progress - ratio) <= tolerance_ratio
    ]
    continuation = [cycle for cycle in matched if cycle.main_pulse_confirmed]
    extensions = [cycle for cycle in matched if cycle.extension_confirmed]
    false_extensions = [cycle for cycle in matched if cycle.extension_runner_state == "BUILDING" and not cycle.extension_confirmed]
    metrics = [_future_metrics(cycle, checkpoint) for cycle in matched]

    def avg(index: int) -> float | None:
        values = [item[index] for item in metrics if item[index] is not None]
        return None if not values else round(mean(values), 6)

    count = len(matched)
    return CandidateEvidence(
        ratio=ratio,
        matched_count=count,
        continuation_count=len(continuation),
        extension_count=len(extensions),
        false_extension_count=len(false_extensions),
        continuation_probability=None if count == 0 else round(len(continuation) / count, 6),
        extension_probability=None if count == 0 else round(len(extensions) / count, 6),
        false_extension_rate=None if count == 0 else round(len(false_extensions) / count, 6),
        mean_mfe_pct=avg(0),
        mean_mae_pct=avg(1),
        mean_time_to_main_pulse_days=avg(2),
        mean_time_to_extension_days=avg(3),
    )


def calibrate_checkpoint_grid(
    cycles: Sequence[CycleRecord],
    checkpoint: str,
    *,
    discovery_fraction: float = 0.7,
    tolerance_days: float = 2.0,
    min_discovery_matches: int = 2,
) -> CalibrationResult:
    """Select a ratio on chronological discovery data, then score it on holdout.

    The candidate grid is frozen at module import. Selection sees only discovery-cycle
    outcomes; holdout cycles are never used to choose the ratio.
    """
    if not 0.0 < discovery_fraction < 1.0:
        raise ValueError("discovery_fraction must be between 0 and 1")
    ordered = sorted(cycles, key=lambda cycle: cycle.start_ts)
    split = max(1, min(len(ordered) - 1, int(len(ordered) * discovery_fraction))) if len(ordered) > 1 else len(ordered)
    discovery = ordered[:split]
    holdout = ordered[split:]
    grid = RECOGNITION_RATIO_GRID if checkpoint == "recognition" else IGNITION_RATIO_GRID
    tolerance_ratio = tolerance_days / NOMINAL_CYCLE_DAYS
    evidence = tuple(_evidence_for_ratio(discovery, checkpoint, ratio, tolerance_ratio=tolerance_ratio) for ratio in grid)
    eligible = [item for item in evidence if item.matched_count >= min_discovery_matches]
    selected = None
    if eligible:
        selected = max(
            eligible,
            key=lambda item: (
                item.continuation_probability or 0.0,
                item.extension_probability or 0.0,
                -(item.false_extension_rate or 0.0),
                item.matched_count,
                -abs(item.ratio - BASELINE_RATIOS[checkpoint]),
            ),
        ).ratio

    holdout_cont = None
    holdout_ext = None
    if selected is not None and holdout:
        holdout_evidence = _evidence_for_ratio(holdout, checkpoint, selected, tolerance_ratio=tolerance_ratio)
        holdout_cont = holdout_evidence.continuation_probability
        holdout_ext = holdout_evidence.extension_probability

    return CalibrationResult(
        checkpoint=checkpoint,
        frozen_grid=tuple(grid),
        discovery_cycle_ids=tuple(cycle.cycle_id for cycle in discovery),
        holdout_cycle_ids=tuple(cycle.cycle_id for cycle in holdout),
        evidence=evidence,
        selected_ratio=selected,
        holdout_continuation_probability=holdout_cont,
        holdout_extension_probability=holdout_ext,
    )


def walk_forward_checkpoint_evidence(
    cycles: Sequence[CycleRecord], checkpoint: str, *, min_train_cycles: int = 3
) -> list[dict[str, object]]:
    ordered = sorted(cycles, key=lambda cycle: cycle.start_ts)
    rows: list[dict[str, object]] = []
    for test_index in range(min_train_cycles, len(ordered)):
        train = ordered[:test_index]
        test = ordered[test_index]
        calibration = calibrate_checkpoint_grid(
            train,
            checkpoint,
            discovery_fraction=max(0.5, (len(train) - 1) / len(train)),
            min_discovery_matches=1,
        )
        selected = calibration.selected_ratio
        matched = False
        if selected is not None:
            progress = _checkpoint_progress(test, checkpoint)
            matched = progress is not None and abs(progress - selected) <= (2.0 / NOMINAL_CYCLE_DAYS)
        rows.append(
            {
                "checkpoint": checkpoint,
                "train_cycle_ids": [cycle.cycle_id for cycle in train],
                "test_cycle_id": test.cycle_id,
                "selected_ratio": selected,
                "test_checkpoint_match": matched,
                "test_main_pulse_confirmed": test.main_pulse_confirmed,
                "test_extension_confirmed": test.extension_confirmed,
            }
        )
    return rows


def cycle_to_jsonable(cycle: CycleRecord) -> dict[str, object]:
    payload = asdict(cycle)
    for key, value in list(payload.items()):
        if isinstance(value, datetime):
            payload[key] = _iso(value)
    for snapshot_key in (
        "recognition_volume_snapshot",
        "ignition_volume_snapshot",
        "main_pulse_volume_snapshot",
    ):
        snapshot = payload.get(snapshot_key)
        if isinstance(snapshot, dict) and isinstance(snapshot.get("as_of_ts"), datetime):
            snapshot["as_of_ts"] = _iso(snapshot["as_of_ts"])
    return payload


def append_cycle_ledger(path: Path, cycles: Iterable[CycleRecord]) -> int:
    """Append unseen cycle records without rewriting historical rows.

    An existing cycle id with different content is a hard error. Identical replays are
    idempotent and append zero duplicate rows.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, dict[str, object]] = {}
    if path.exists():
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            if not raw_line.strip():
                continue
            row = json.loads(raw_line)
            existing[str(row["cycle_id"])] = row

    new_rows: list[dict[str, object]] = []
    for cycle in cycles:
        row = cycle_to_jsonable(cycle)
        cid = str(row["cycle_id"])
        if cid in existing:
            if existing[cid] != row:
                raise ValueError(f"append-only ledger conflict for cycle_id={cid}")
            continue
        existing[cid] = row
        new_rows.append(row)

    if new_rows:
        with path.open("a", encoding="utf-8") as handle:
            for row in new_rows:
                handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    return len(new_rows)
