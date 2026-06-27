from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any


RUNNER_NAME = "run_breathline_marker_timing_report_v1"
VERSION = "1.0"

MARKER_TIMING_OBSERVATIONS_CSV = "marker_timing_observations.csv"
MARKER_SEGMENT_OBSERVATIONS_CSV = "marker_segment_observations.csv"
MARKER_TIMING_SUMMARY_CSV = "marker_timing_summary.csv"
MARKER_SEGMENT_SUMMARY_CSV = "marker_segment_summary.csv"
BTC_RELATIVE_MARKER_TIMING_SUMMARY_CSV = "btc_relative_marker_timing_summary.csv"
BTC_RELATIVE_SEGMENT_TIMING_SUMMARY_CSV = "btc_relative_segment_timing_summary.csv"
MANIFEST_TXT = "manifest.txt"

MARKER_TIMING_OBSERVATION_FIELDS = [
    "symbol",
    "anchor_ts_utc",
    "checkpoint_ratio",
    "selected_partial_offset_days",
    "marker_code",
    "expected_ts_utc",
    "observed_ts_utc",
    "matched",
    "timing_error_hours",
]

MARKER_SEGMENT_OBSERVATION_FIELDS = [
    "symbol",
    "anchor_ts_utc",
    "checkpoint_ratio",
    "from_marker_code",
    "to_marker_code",
    "expected_duration_hours",
    "observed_duration_hours",
    "observed_minus_expected_hours",
    "both_markers_matched",
]

MARKER_TIMING_SUMMARY_FIELDS = [
    "checkpoint_ratio",
    "symbol",
    "marker_code",
    "total_rows",
    "matched_rows",
    "match_rate",
    "median_timing_error_hours",
    "min_timing_error_hours",
    "max_timing_error_hours",
]

MARKER_SEGMENT_SUMMARY_FIELDS = [
    "checkpoint_ratio",
    "symbol",
    "from_marker_code",
    "to_marker_code",
    "total_rows",
    "matched_segment_rows",
    "match_rate",
    "median_expected_duration_hours",
    "median_observed_duration_hours",
    "median_observed_minus_expected_hours",
]

BTC_RELATIVE_MARKER_TIMING_SUMMARY_FIELDS = [
    "checkpoint_ratio",
    "symbol",
    "marker_code",
    "paired_rows",
    "median_relative_marker_lag_hours",
    "min_relative_marker_lag_hours",
    "max_relative_marker_lag_hours",
]

BTC_RELATIVE_SEGMENT_TIMING_SUMMARY_FIELDS = [
    "checkpoint_ratio",
    "symbol",
    "from_marker_code",
    "to_marker_code",
    "paired_rows",
    "median_relative_segment_duration_delta_hours",
    "min_relative_segment_duration_delta_hours",
    "max_relative_segment_duration_delta_hours",
]


@dataclass(frozen=True)
class ParsedMarker:
    code: str
    expected_ts_utc: str
    expected_ts: datetime
    matched: bool
    observed_ts_utc: str
    observed_ts: datetime | None
    timing_error_hours: float | None
    order_index: int


@dataclass(frozen=True)
class AcceptedRecord:
    symbol: str
    anchor_ts_utc: str
    checkpoint_ratio: str
    selected_partial_offset_days: float
    markers: tuple[ParsedMarker, ...]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="File-only research report for historical Breathline marker timing."
    )
    parser.add_argument("--input-jsonl", required=True)
    parser.add_argument("--out-dir", required=True)
    return parser.parse_args(argv)


def parse_iso_utc(raw: str, *, context: str) -> datetime:
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Invalid {context}: {raw}") from exc
    return value.astimezone(UTC)


def iso_utc(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_float(value: Any, *, context: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {context}: {value}") from exc


def maybe_float(value: Any) -> float | None:
    if value in ("", None):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def format_metric(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.6f}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def current_git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return "unavailable"
    commit = result.stdout.strip()
    if not commit:
        return "unavailable"
    return commit


def ensure_empty_output_dir(path: Path) -> None:
    if path.exists():
        if any(path.iterdir()):
            raise ValueError(f"Output directory must be empty: {path}")
    else:
        path.mkdir(parents=True, exist_ok=True)


def load_accepted_records(path: Path) -> tuple[int, list[AcceptedRecord]]:
    input_rows = 0
    accepted: list[AcceptedRecord] = []
    accepted_identities: set[tuple[str, str, str]] = set()

    with path.open(encoding="utf-8") as handle:
        for line in handle:
            input_rows += 1
            raw_row = json.loads(line)
            if raw_row.get("status") != "OK":
                continue

            symbol = str(raw_row.get("symbol") or "").strip()
            anchor_ts_utc = str(raw_row.get("anchor_ts_utc") or "").strip()
            checkpoint_ratio = str(raw_row.get("checkpoint_ratio") or "").strip()
            if not symbol:
                raise ValueError("Accepted row missing symbol")
            if not anchor_ts_utc:
                raise ValueError(f"Accepted row missing anchor_ts_utc for symbol={symbol}")
            if not checkpoint_ratio:
                raise ValueError(
                    f"Accepted row missing checkpoint_ratio for symbol={symbol} anchor={anchor_ts_utc}"
                )
            identity_key = (symbol, anchor_ts_utc, checkpoint_ratio)
            if identity_key in accepted_identities:
                raise ValueError(
                    "Duplicate accepted record identity "
                    f"for symbol={symbol} anchor={anchor_ts_utc} checkpoint={checkpoint_ratio}"
                )

            selected_partial_offset_days = to_float(
                raw_row.get("selected_partial_offset_days"),
                context=(
                    "selected_partial_offset_days "
                    f"for symbol={symbol} anchor={anchor_ts_utc} checkpoint={checkpoint_ratio}"
                ),
            )

            selected_full = raw_row.get("selected_full_same_offset")
            if not isinstance(selected_full, dict):
                raise ValueError(
                    f"Accepted row missing selected_full_same_offset for symbol={symbol} anchor={anchor_ts_utc}"
                )

            raw_markers = selected_full.get("markers")
            if not isinstance(raw_markers, list):
                raise ValueError(
                    f"Accepted row missing marker list for symbol={symbol} anchor={anchor_ts_utc}"
                )

            markers: list[ParsedMarker] = []
            seen_codes: set[str] = set()
            previous_expected: datetime | None = None

            for index, raw_marker in enumerate(raw_markers):
                if not isinstance(raw_marker, dict):
                    raise ValueError(
                        f"Invalid marker payload for symbol={symbol} anchor={anchor_ts_utc} index={index}"
                    )

                code = str(raw_marker.get("code") or "").strip()
                if not code:
                    raise ValueError(
                        f"Accepted row missing marker code for symbol={symbol} anchor={anchor_ts_utc}"
                    )
                if code in seen_codes:
                    raise ValueError(
                        f"Duplicate marker code {code} for symbol={symbol} anchor={anchor_ts_utc} checkpoint={checkpoint_ratio}"
                    )
                seen_codes.add(code)

                expected_raw = str(raw_marker.get("expected_ts_utc") or "").strip()
                if not expected_raw:
                    raise ValueError(
                        f"Accepted row missing expected_ts_utc for symbol={symbol} marker={code}"
                    )
                expected_ts = parse_iso_utc(
                    expected_raw,
                    context=f"expected_ts_utc for symbol={symbol} marker={code}",
                )

                if previous_expected is not None and expected_ts <= previous_expected:
                    raise ValueError(
                        "Marker expected timestamps must be strictly ascending "
                        f"for symbol={symbol} anchor={anchor_ts_utc} checkpoint={checkpoint_ratio}"
                    )
                previous_expected = expected_ts

                matched_value = raw_marker.get("matched")
                if matched_value not in (True, False):
                    raise ValueError(
                        f"Invalid matched flag for symbol={symbol} marker={code}: {matched_value}"
                    )
                matched = bool(matched_value)

                observed_raw = str(raw_marker.get("observed_ts_utc") or "").strip()
                observed_ts: datetime | None = None
                if matched:
                    if not observed_raw:
                        raise ValueError(
                            f"Matched marker missing observed_ts_utc for symbol={symbol} marker={code}"
                        )
                    observed_ts = parse_iso_utc(
                        observed_raw,
                        context=f"observed_ts_utc for symbol={symbol} marker={code}",
                    )
                elif observed_raw:
                    observed_ts = parse_iso_utc(
                        observed_raw,
                        context=f"observed_ts_utc for symbol={symbol} marker={code}",
                    )

                markers.append(
                    ParsedMarker(
                        code=code,
                        expected_ts_utc=expected_raw,
                        expected_ts=expected_ts,
                        matched=matched,
                        observed_ts_utc=observed_raw,
                        observed_ts=observed_ts,
                        timing_error_hours=maybe_float(raw_marker.get("timing_error_hours")),
                        order_index=index,
                    )
                )

            accepted.append(
                AcceptedRecord(
                    symbol=symbol,
                    anchor_ts_utc=anchor_ts_utc,
                    checkpoint_ratio=checkpoint_ratio,
                    selected_partial_offset_days=selected_partial_offset_days,
                    markers=tuple(markers),
                )
            )
            accepted_identities.add(identity_key)

    return input_rows, accepted


def build_marker_timing_observations(records: list[AcceptedRecord]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in sorted(records, key=record_sort_key):
        for marker in record.markers:
            rows.append(
                {
                    "symbol": record.symbol,
                    "anchor_ts_utc": record.anchor_ts_utc,
                    "checkpoint_ratio": record.checkpoint_ratio,
                    "selected_partial_offset_days": record.selected_partial_offset_days,
                    "marker_code": marker.code,
                    "expected_ts_utc": marker.expected_ts_utc,
                    "observed_ts_utc": marker.observed_ts_utc,
                    "matched": marker.matched,
                    "timing_error_hours": format_metric(marker.timing_error_hours),
                }
            )
    return rows


def build_marker_segment_observations(records: list[AcceptedRecord]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in sorted(records, key=record_sort_key):
        for left, right in zip(record.markers, record.markers[1:]):
            expected_duration = (right.expected_ts - left.expected_ts).total_seconds() / 3600.0
            if left.matched and right.matched and left.observed_ts and right.observed_ts:
                observed_duration = (right.observed_ts - left.observed_ts).total_seconds() / 3600.0
                observed_minus_expected = observed_duration - expected_duration
                both_matched = True
            else:
                observed_duration = None
                observed_minus_expected = None
                both_matched = False

            rows.append(
                {
                    "symbol": record.symbol,
                    "anchor_ts_utc": record.anchor_ts_utc,
                    "checkpoint_ratio": record.checkpoint_ratio,
                    "from_marker_code": left.code,
                    "to_marker_code": right.code,
                    "expected_duration_hours": format_metric(expected_duration),
                    "observed_duration_hours": format_metric(observed_duration),
                    "observed_minus_expected_hours": format_metric(observed_minus_expected),
                    "both_markers_matched": both_matched,
                }
            )
    return rows


def build_marker_timing_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["checkpoint_ratio"]), str(row["symbol"]), str(row["marker_code"]))].append(row)

    summary: list[dict[str, Any]] = []
    for key in sorted(grouped, key=summary_marker_key_sort):
        group_rows = grouped[key]
        errors = [
            maybe_float(row.get("timing_error_hours"))
            for row in group_rows
            if row.get("matched") is True
        ]
        numeric_errors = [value for value in errors if value is not None]
        matched_rows = sum(1 for row in group_rows if row.get("matched") is True)
        summary.append(
            {
                "checkpoint_ratio": key[0],
                "symbol": key[1],
                "marker_code": key[2],
                "total_rows": len(group_rows),
                "matched_rows": matched_rows,
                "match_rate": format_metric(matched_rows / len(group_rows) if group_rows else None),
                "median_timing_error_hours": format_metric(median(numeric_errors) if numeric_errors else None),
                "min_timing_error_hours": format_metric(min(numeric_errors) if numeric_errors else None),
                "max_timing_error_hours": format_metric(max(numeric_errors) if numeric_errors else None),
            }
        )
    return summary


def build_marker_segment_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[
            (
                str(row["checkpoint_ratio"]),
                str(row["symbol"]),
                str(row["from_marker_code"]),
                str(row["to_marker_code"]),
            )
        ].append(row)

    summary: list[dict[str, Any]] = []
    for key in sorted(grouped, key=summary_segment_key_sort):
        group_rows = grouped[key]
        expected = [to_float(row["expected_duration_hours"], context="expected_duration_hours") for row in group_rows]
        observed = [
            maybe_float(row.get("observed_duration_hours"))
            for row in group_rows
            if row.get("both_markers_matched") is True
        ]
        observed_delta = [
            maybe_float(row.get("observed_minus_expected_hours"))
            for row in group_rows
            if row.get("both_markers_matched") is True
        ]
        observed_clean = [value for value in observed if value is not None]
        observed_delta_clean = [value for value in observed_delta if value is not None]
        matched_rows = sum(1 for row in group_rows if row.get("both_markers_matched") is True)
        summary.append(
            {
                "checkpoint_ratio": key[0],
                "symbol": key[1],
                "from_marker_code": key[2],
                "to_marker_code": key[3],
                "total_rows": len(group_rows),
                "matched_segment_rows": matched_rows,
                "match_rate": format_metric(matched_rows / len(group_rows) if group_rows else None),
                "median_expected_duration_hours": format_metric(median(expected) if expected else None),
                "median_observed_duration_hours": format_metric(
                    median(observed_clean) if observed_clean else None
                ),
                "median_observed_minus_expected_hours": format_metric(
                    median(observed_delta_clean) if observed_delta_clean else None
                ),
            }
        )
    return summary


def build_btc_relative_marker_timing_summary(records: list[AcceptedRecord]) -> tuple[list[dict[str, Any]], int]:
    grouped: dict[tuple[str, str], dict[str, AcceptedRecord]] = defaultdict(dict)
    for record in records:
        grouped[(record.anchor_ts_utc, record.checkpoint_ratio)][record.symbol] = record

    relative_values: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    pair_count = 0

    for (anchor_ts_utc, checkpoint_ratio), cohort in sorted(grouped.items()):
        btc = cohort.get("BTC")
        if btc is None:
            continue
        btc_markers = {marker.code: marker for marker in btc.markers}

        for symbol, coin in sorted(cohort.items()):
            if symbol == "BTC":
                continue
            for marker in coin.markers:
                btc_marker = btc_markers.get(marker.code)
                if (
                    btc_marker is None
                    or not marker.matched
                    or not btc_marker.matched
                    or marker.observed_ts is None
                    or btc_marker.observed_ts is None
                ):
                    continue
                relative_lag_hours = (
                    marker.observed_ts - btc_marker.observed_ts
                ).total_seconds() / 3600.0
                relative_values[(checkpoint_ratio, symbol, marker.code)].append(relative_lag_hours)
                pair_count += 1

    rows: list[dict[str, Any]] = []
    for key in sorted(relative_values, key=summary_marker_key_sort):
        values = relative_values[key]
        rows.append(
            {
                "checkpoint_ratio": key[0],
                "symbol": key[1],
                "marker_code": key[2],
                "paired_rows": len(values),
                "median_relative_marker_lag_hours": format_metric(median(values)),
                "min_relative_marker_lag_hours": format_metric(min(values)),
                "max_relative_marker_lag_hours": format_metric(max(values)),
            }
        )
    return rows, pair_count


def build_btc_relative_segment_timing_summary(records: list[AcceptedRecord]) -> tuple[list[dict[str, Any]], int]:
    grouped: dict[tuple[str, str], dict[str, AcceptedRecord]] = defaultdict(dict)
    for record in records:
        grouped[(record.anchor_ts_utc, record.checkpoint_ratio)][record.symbol] = record

    relative_values: dict[tuple[str, str, str, str], list[float]] = defaultdict(list)
    pair_count = 0

    for (anchor_ts_utc, checkpoint_ratio), cohort in sorted(grouped.items()):
        btc = cohort.get("BTC")
        if btc is None:
            continue
        btc_pairs = segment_pair_map(btc)

        for symbol, coin in sorted(cohort.items()):
            if symbol == "BTC":
                continue
            coin_pairs = segment_pair_map(coin)
            for pair_key, coin_pair in coin_pairs.items():
                btc_pair = btc_pairs.get(pair_key)
                if btc_pair is None:
                    continue
                if (
                    coin_pair["left"].matched
                    and coin_pair["right"].matched
                    and btc_pair["left"].matched
                    and btc_pair["right"].matched
                    and coin_pair["left"].observed_ts is not None
                    and coin_pair["right"].observed_ts is not None
                    and btc_pair["left"].observed_ts is not None
                    and btc_pair["right"].observed_ts is not None
                ):
                    coin_duration = (
                        coin_pair["right"].observed_ts - coin_pair["left"].observed_ts
                    ).total_seconds() / 3600.0
                    btc_duration = (
                        btc_pair["right"].observed_ts - btc_pair["left"].observed_ts
                    ).total_seconds() / 3600.0
                    delta_hours = coin_duration - btc_duration
                    relative_values[(checkpoint_ratio, symbol, pair_key[0], pair_key[1])].append(delta_hours)
                    pair_count += 1

    rows: list[dict[str, Any]] = []
    for key in sorted(relative_values, key=summary_segment_key_sort):
        values = relative_values[key]
        rows.append(
            {
                "checkpoint_ratio": key[0],
                "symbol": key[1],
                "from_marker_code": key[2],
                "to_marker_code": key[3],
                "paired_rows": len(values),
                "median_relative_segment_duration_delta_hours": format_metric(median(values)),
                "min_relative_segment_duration_delta_hours": format_metric(min(values)),
                "max_relative_segment_duration_delta_hours": format_metric(max(values)),
            }
        )
    return rows, pair_count


def segment_pair_map(record: AcceptedRecord) -> dict[tuple[str, str], dict[str, ParsedMarker]]:
    pairs: dict[tuple[str, str], dict[str, ParsedMarker]] = {}
    for left, right in zip(record.markers, record.markers[1:]):
        pairs[(left.code, right.code)] = {"left": left, "right": right}
    return pairs


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def write_manifest(path: Path, *, input_jsonl: Path, source_git_commit: str) -> None:
    generated_at_utc = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        f"generated_at_utc={generated_at_utc}",
        f"input_jsonl={input_jsonl}",
        f"input_sha256={sha256_file(input_jsonl)}",
        f"source_git_commit={source_git_commit}",
        "terminology=marker_timing_not_phase_duration",
        "scope=research_only_market_only_account_agnostic",
        "db_reads=0",
        "db_writes=0",
        "broker_calls=0",
        "broker_writes=0",
        "order_submission=0",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def record_sort_key(record: AcceptedRecord) -> tuple[float, str, str, float]:
    return (
        float(record.checkpoint_ratio),
        record.symbol,
        record.anchor_ts_utc,
        record.selected_partial_offset_days,
    )


def summary_marker_key_sort(key: tuple[str, str, str]) -> tuple[float, str, str]:
    return (float(key[0]), key[1], key[2])


def summary_segment_key_sort(key: tuple[str, str, str, str]) -> tuple[float, str, str, str]:
    return (float(key[0]), key[1], key[2], key[3])


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    input_jsonl = Path(args.input_jsonl)
    out_dir = Path(args.out_dir)

    ensure_empty_output_dir(out_dir)

    print(f"STARTED {RUNNER_NAME} version={VERSION}")
    print("scope=research-only market-only account-agnostic")
    print("db_reads=0 db_writes=0 broker_calls=0 broker_writes=0 order_submission=0")

    input_rows, accepted_records = load_accepted_records(input_jsonl)
    source_git_commit = current_git_commit()
    marker_timing_observations = build_marker_timing_observations(accepted_records)
    marker_segment_observations = build_marker_segment_observations(accepted_records)
    marker_timing_summary = build_marker_timing_summary(marker_timing_observations)
    marker_segment_summary = build_marker_segment_summary(marker_segment_observations)
    btc_relative_marker_summary, btc_relative_marker_pairs = build_btc_relative_marker_timing_summary(
        accepted_records
    )
    btc_relative_segment_summary, btc_relative_segment_pairs = build_btc_relative_segment_timing_summary(
        accepted_records
    )

    write_csv(out_dir / MARKER_TIMING_OBSERVATIONS_CSV, marker_timing_observations, MARKER_TIMING_OBSERVATION_FIELDS)
    write_csv(
        out_dir / MARKER_SEGMENT_OBSERVATIONS_CSV,
        marker_segment_observations,
        MARKER_SEGMENT_OBSERVATION_FIELDS,
    )
    write_csv(out_dir / MARKER_TIMING_SUMMARY_CSV, marker_timing_summary, MARKER_TIMING_SUMMARY_FIELDS)
    write_csv(out_dir / MARKER_SEGMENT_SUMMARY_CSV, marker_segment_summary, MARKER_SEGMENT_SUMMARY_FIELDS)
    write_csv(
        out_dir / BTC_RELATIVE_MARKER_TIMING_SUMMARY_CSV,
        btc_relative_marker_summary,
        BTC_RELATIVE_MARKER_TIMING_SUMMARY_FIELDS,
    )
    write_csv(
        out_dir / BTC_RELATIVE_SEGMENT_TIMING_SUMMARY_CSV,
        btc_relative_segment_summary,
        BTC_RELATIVE_SEGMENT_TIMING_SUMMARY_FIELDS,
    )
    write_manifest(out_dir / MANIFEST_TXT, input_jsonl=input_jsonl, source_git_commit=source_git_commit)

    print(f"input_rows={input_rows}")
    print(f"accepted_rows={len(accepted_records)}")
    print(f"marker_observations={len(marker_timing_observations)}")
    print(f"marker_segments={len(marker_segment_observations)}")
    print(f"btc_relative_marker_pairs={btc_relative_marker_pairs}")
    print(f"btc_relative_segment_pairs={btc_relative_segment_pairs}")
    print(f"output_dir={out_dir}")
    print(f"FINISHED {RUNNER_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
