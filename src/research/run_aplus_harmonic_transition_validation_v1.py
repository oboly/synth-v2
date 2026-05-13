from __future__ import annotations

import argparse
import csv
import glob
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any


REPORT_NAME = "aplus_harmonic_transition_validation_v1"
VERSION = "0.1"


PHASE_SCORE = {
    "0.236": 1,
    "0.382": 2,
    "0.500": 3,
    "0.618": 4,
    "0.786": 5,
    "1.000": 6,
    "1.272": 7,
}

OFFSET_SCORE = {
    "-10.5": -10.5,
    "-9": -9.0,
    "-7": -7.0,
    "-5": -5.0,
    "-3": -3.0,
    "0": 0.0,
    "+3": 3.0,
    "+5": 5.0,
    "+7": 7.0,
    "+9": 9.0,
    "+10.5": 10.5,
}


@dataclass(frozen=True)
class SnapshotRow:
    snapshot_id: str
    snapshot_ts_local: str
    token: str
    phase_marker: str
    phase_offset_band: str
    phase_stability: str
    recognition_0618: str
    overflow_0786: str
    extension_1272: str
    regime_fit: str
    clean_or_dirty: str


def fmt(value: Any, places: int = 4) -> str:
    if value is None:
        return ""

    dec = value if isinstance(value, Decimal) else Decimal(str(value))
    q = Decimal("1").scaleb(-places)
    text = format(dec.quantize(q), "f")

    if "." in text:
        text = text.rstrip("0").rstrip(".")

    return text or "0"


def print_table(headers: list[str], rows: list[list[str]]) -> None:
    if not rows:
        print("(no rows)")
        return

    widths = [len(header) for header in headers]

    for row in rows:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(value))

    print(" | ".join(headers[idx].ljust(widths[idx]) for idx in range(len(headers))))
    print("-+-".join("-" * width for width in widths))

    for row in rows:
        print(" | ".join(row[idx].ljust(widths[idx]) for idx in range(len(headers))))


def load_snapshot_rows(pattern: str) -> list[SnapshotRow]:
    rows: list[SnapshotRow] = []

    for raw_path in sorted(glob.glob(pattern)):
        path = Path(raw_path)

        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue

            row = json.loads(line)

            rows.append(
                SnapshotRow(
                    snapshot_id=str(row.get("snapshot_id", path.stem)),
                    snapshot_ts_local=str(row.get("snapshot_ts_local", "")),
                    token=str(row["token"]),
                    phase_marker=str(row.get("phase_marker", "unclear")),
                    phase_offset_band=str(row.get("phase_offset_band", "unclear")),
                    phase_stability=str(row.get("phase_stability", "unclear")),
                    recognition_0618=str(row.get("recognition_0618", "unclear")),
                    overflow_0786=str(row.get("overflow_0786", "unclear")),
                    extension_1272=str(row.get("extension_1272", "unclear")),
                    regime_fit=str(row.get("regime_fit", "unclear")),
                    clean_or_dirty=str(row.get("clean_or_dirty", "unclear")),
                )
            )

    return rows


def phase_stage(row: SnapshotRow) -> str:
    if row.phase_marker == "0.236":
        return "EARLY_SEED_0236"

    if row.phase_marker in {"0.382", "0.500"}:
        if row.recognition_0618 == "forming":
            return "FORMING_PRE_0618"
        return "PRE_RECOGNITION"

    if row.phase_marker == "0.618":
        if row.recognition_0618 == "confirmed":
            return "RECOGNITION_0618_CONFIRMED"
        if row.recognition_0618 == "forming":
            return "RECOGNITION_0618_FORMING"
        return "RECOGNITION_0618_UNCLEAR"

    if row.phase_marker == "0.786":
        if row.overflow_0786 in {"building", "active"}:
            return "OVERFLOW_0786_PRESSURE"
        if row.overflow_0786 == "exhausted":
            return "OVERFLOW_0786_EXHAUSTED"
        return "OVERFLOW_0786_UNCLEAR"

    if row.phase_marker == "1.000":
        return "MAIN_PULSE_1000"

    if row.phase_marker == "1.272":
        return "EXTENSION_1272"

    return "UNCLEAR"


def quality_bucket(row: SnapshotRow) -> str:
    if row.phase_marker == "0.618" and row.recognition_0618 == "confirmed" and row.regime_fit == "high" and row.clean_or_dirty == "clean":
        return "CLEAN_0618_CONFIRMED"

    if row.phase_marker in {"1.000", "1.272"} and row.extension_1272 == "exceeded":
        if row.clean_or_dirty == "clean":
            return "CLEAN_LATE_EXTENSION"
        return "DIRTY_LATE_OVERFLOW"

    if row.phase_marker in {"0.236", "0.382", "0.500"} and row.recognition_0618 == "forming":
        return "FORMING_EARLY"

    if row.phase_marker == "0.786":
        return "0786_OVERFLOW_PRESSURE"

    if row.clean_or_dirty == "dirty":
        return "DIRTY_OTHER"

    if row.phase_marker == "unclear":
        return "UNCLEAR"

    return "OTHER"


def classify_transition(prev: SnapshotRow, curr: SnapshotRow) -> str:
    prev_score = PHASE_SCORE.get(prev.phase_marker)
    curr_score = PHASE_SCORE.get(curr.phase_marker)

    prev_stage = phase_stage(prev)
    curr_stage = phase_stage(curr)

    if prev.phase_marker == "unclear" or curr.phase_marker == "unclear":
        return "UNCLEAR_TRANSITION"

    if prev.clean_or_dirty == "clean" and curr.clean_or_dirty == "dirty":
        return "CLEAN_TO_DIRTY"

    if prev.clean_or_dirty == "dirty" and curr.clean_or_dirty == "clean":
        return "DIRTY_TO_CLEAN"

    if curr.phase_marker in {"1.000", "1.272"} and curr.extension_1272 == "exceeded":
        if curr.clean_or_dirty == "clean":
            return "CLEAN_LATE_EXTENSION"
        return "DIRTY_LATE_OVERFLOW"

    if prev_score is not None and curr_score is not None:
        if prev_score < 4 and curr.phase_marker == "0.618" and curr.recognition_0618 == "confirmed":
            return "FORMING_TO_RECOGNITION"

        if prev.phase_marker == "0.618" and curr.phase_marker == "0.786":
            return "RECOGNITION_TO_OVERFLOW"

        if prev.phase_marker == "0.786" and curr.phase_marker in {"1.000", "1.272"}:
            return "OVERFLOW_TO_EXTENSION"

        if curr_score > prev_score:
            return "FORWARD_PHASE_PROGRESS"

        if curr_score < prev_score:
            return "PHASE_REGRESSION"

    if prev_stage == curr_stage:
        return "STABLE_STAGE"

    return "OTHER_TRANSITION"


def offset_transition(prev: SnapshotRow, curr: SnapshotRow) -> str:
    prev_offset = OFFSET_SCORE.get(prev.phase_offset_band)
    curr_offset = OFFSET_SCORE.get(curr.phase_offset_band)

    if prev.phase_offset_band in {"drift", "unclear"} or curr.phase_offset_band in {"drift", "unclear"}:
        if curr.phase_offset_band == "drift":
            return "OFFSET_DRIFTED"
        return "OFFSET_UNCLEAR"

    if prev_offset is None or curr_offset is None:
        return "OFFSET_UNCLEAR"

    if abs(curr_offset) < abs(prev_offset):
        return "OFFSET_CONVERGED"

    if abs(curr_offset) > abs(prev_offset):
        return "OFFSET_DIVERGED"

    if curr_offset == prev_offset:
        return "OFFSET_STABLE"

    return "OFFSET_SHIFTED_SAME_DISTANCE"


def rows_by_token_and_snapshot(rows: list[SnapshotRow]) -> dict[str, list[SnapshotRow]]:
    grouped: dict[str, list[SnapshotRow]] = defaultdict(list)

    for row in rows:
        grouped[row.token].append(row)

    for token in grouped:
        grouped[token].sort(key=lambda row: (row.snapshot_ts_local, row.snapshot_id))

    return grouped


def build_current_state_rows(rows: list[SnapshotRow]) -> list[dict[str, Any]]:
    latest_by_token: dict[str, SnapshotRow] = {}

    for row in rows:
        current = latest_by_token.get(row.token)

        if current is None or (row.snapshot_ts_local, row.snapshot_id) > (current.snapshot_ts_local, current.snapshot_id):
            latest_by_token[row.token] = row

    out: list[dict[str, Any]] = []

    for token, row in sorted(latest_by_token.items()):
        out.append(
            {
                "token": token,
                "snapshot_id": row.snapshot_id,
                "snapshot_ts_local": row.snapshot_ts_local,
                "phase_marker": row.phase_marker,
                "phase_offset_band": row.phase_offset_band,
                "phase_stage": phase_stage(row),
                "quality_bucket": quality_bucket(row),
                "phase_stability": row.phase_stability,
                "recognition_0618": row.recognition_0618,
                "overflow_0786": row.overflow_0786,
                "extension_1272": row.extension_1272,
                "regime_fit": row.regime_fit,
                "clean_or_dirty": row.clean_or_dirty,
            }
        )

    return out


def build_transition_rows(rows: list[SnapshotRow]) -> list[dict[str, Any]]:
    grouped = rows_by_token_and_snapshot(rows)
    out: list[dict[str, Any]] = []

    for token, token_rows in grouped.items():
        if len(token_rows) < 2:
            continue

        for prev, curr in zip(token_rows, token_rows[1:]):
            prev_score = PHASE_SCORE.get(prev.phase_marker)
            curr_score = PHASE_SCORE.get(curr.phase_marker)

            out.append(
                {
                    "token": token,
                    "prev_snapshot_id": prev.snapshot_id,
                    "curr_snapshot_id": curr.snapshot_id,
                    "prev_snapshot_ts_local": prev.snapshot_ts_local,
                    "curr_snapshot_ts_local": curr.snapshot_ts_local,
                    "prev_phase_marker": prev.phase_marker,
                    "curr_phase_marker": curr.phase_marker,
                    "prev_phase_offset_band": prev.phase_offset_band,
                    "curr_phase_offset_band": curr.phase_offset_band,
                    "prev_stage": phase_stage(prev),
                    "curr_stage": phase_stage(curr),
                    "prev_quality_bucket": quality_bucket(prev),
                    "curr_quality_bucket": quality_bucket(curr),
                    "transition_type": classify_transition(prev, curr),
                    "offset_transition": offset_transition(prev, curr),
                    "phase_delta": (curr_score - prev_score) if prev_score is not None and curr_score is not None else None,
                    "prev_clean_or_dirty": prev.clean_or_dirty,
                    "curr_clean_or_dirty": curr.clean_or_dirty,
                    "prev_regime_fit": prev.regime_fit,
                    "curr_regime_fit": curr.regime_fit,
                }
            )

    return out


def summarize_counter(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    counts = Counter(str(row[key]) for row in rows)
    total = sum(counts.values())

    return [
        {
            key: label,
            "rows": count,
            "pct": round(count / total * 100.0, 4) if total else None,
        }
        for label, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    if not rows:
        path.write_text("", encoding="utf-8")
        return

    fields = sorted({key for row in rows for key in row.keys()})

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> int:
    parser = argparse.ArgumentParser(description="Research-only A+ harmonic transition validation.")
    parser.add_argument("--snapshot-glob", default="data/external/aplus_harmonic_phase_overlay/*.jsonl")
    parser.add_argument("--out-dir", default="data/research/aplus_harmonic_transition_validation_v1")
    parser.add_argument("--output", choices=["table", "none"], default="table")
    args = parser.parse_args()

    rows = load_snapshot_rows(args.snapshot_glob)
    current_rows = build_current_state_rows(rows)
    transition_rows = build_transition_rows(rows)

    current_stage_summary = summarize_counter(current_rows, "phase_stage")
    quality_summary = summarize_counter(current_rows, "quality_bucket")
    transition_summary = summarize_counter(transition_rows, "transition_type") if transition_rows else []
    offset_transition_summary = summarize_counter(transition_rows, "offset_transition") if transition_rows else []

    out_dir = Path(args.out_dir)
    write_csv(out_dir / "aplus_harmonic_transition_current_state.csv", current_rows)
    write_csv(out_dir / "aplus_harmonic_transition_rows.csv", transition_rows)
    write_csv(out_dir / "aplus_harmonic_transition_current_stage_summary.csv", current_stage_summary)
    write_csv(out_dir / "aplus_harmonic_transition_quality_summary.csv", quality_summary)
    write_csv(out_dir / "aplus_harmonic_transition_type_summary.csv", transition_summary)
    write_csv(out_dir / "aplus_harmonic_transition_offset_summary.csv", offset_transition_summary)

    snapshot_ids = sorted({row.snapshot_id for row in rows})

    if args.output == "table":
        print(f"report={REPORT_NAME} version={VERSION}")
        print("scope=research-only market-only account-agnostic")
        print("db_writes=0 broker_calls=0 broker_writes=0 order_submission=0")
        print("runtime_layer_touch=none")
        print(f"snapshot_glob={args.snapshot_glob}")
        print(f"snapshot_count={len(snapshot_ids)}")
        print(f"snapshot_ids={','.join(snapshot_ids)}")
        print(f"token_rows={len(rows)}")
        print(f"current_tokens={len(current_rows)}")
        print(f"transition_count={len(transition_rows)}")
        print(f"ready_for_next_snapshot={str(len(snapshot_ids) < 2).lower()}")
        print("")

        print("--- current phase-stage summary ---")
        print_table(
            ["phase_stage", "rows", "pct"],
            [
                [str(row["phase_stage"]), str(row["rows"]), fmt(row["pct"], 2)]
                for row in current_stage_summary
            ],
        )

        print("")
        print("--- current quality-bucket summary ---")
        print_table(
            ["quality_bucket", "rows", "pct"],
            [
                [str(row["quality_bucket"]), str(row["rows"]), fmt(row["pct"], 2)]
                for row in quality_summary
            ],
        )

        print("")
        print("--- transition summary ---")
        if transition_rows:
            print_table(
                ["transition_type", "rows", "pct"],
                [
                    [str(row["transition_type"]), str(row["rows"]), fmt(row["pct"], 2)]
                    for row in transition_summary
                ],
            )
        else:
            print("NO_TRANSITIONS_YET_NEED_AT_LEAST_2_SNAPSHOTS")

        print("")
        print("[DONE] db_writes=0 broker_calls=0 broker_writes=0 order_submission=0")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
