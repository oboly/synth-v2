from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPORT_NAME = "aplus_table2_harmonic_overlay_v1"
VERSION = "0.1"

EXPECTED_COLUMNS = [
    "TOKEN",
    "HARMONIC_PHASE",
    "PHASE_STATE",
    "OFFSET_BAND",
    "DRIFT_DIRECTION",
    "QUALITY",
    "EXTENSION_RISK",
    "NOTES",
]

ALLOWED = {
    "harmonic_phase": {
        "pre_0618",
        "forming_0618",
        "confirmed_0618",
        "forming_0786",
        "confirmed_0786",
        "forming_1000",
        "confirmed_1000",
        "extension_1272",
        "late_extension",
        "reset",
        "unclear",
    },
    "phase_state": {
        "early",
        "forming",
        "confirmed",
        "late",
        "exhausted",
        "unclear",
    },
    "offset_band": {
        "-10.5",
        "-9",
        "-8",
        "-7",
        "-5",
        "-3",
        "0",
        "+3",
        "+5",
        "+7",
        "+9",
        "+10.5",
        "unknown",
    },
    "drift_direction": {
        "converging",
        "forward_drift",
        "backward_drift",
        "flat",
        "unstable",
        "unknown",
    },
    "quality": {
        "clean",
        "mixed",
        "dirty",
        "unknown",
    },
    "extension_risk": {
        "low",
        "moderate",
        "high",
        "unknown",
    },
}


def parse_prediction_ts(text: str) -> str:
    match = re.search(r"prediction_ts_utc\s*=\s*([0-9T:\-]+Z)", text)
    if not match:
        raise ValueError("Could not find prediction_ts_utc in raw file")

    raw = match.group(1)
    dt = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def slug_from_ts(prediction_ts_utc: str) -> str:
    return (
        prediction_ts_utc
        .replace("-", "")
        .replace(":", "")
        .replace("T", "T")
        .replace("Z", "Z")
    )


def normalize_header(line: str) -> list[str]:
    stripped = line.strip().strip("|").strip()

    if "|" in stripped:
        cells = [cell.strip().upper() for cell in stripped.split("|")]
        return [cell for cell in cells if cell]

    return [part.strip().upper() for part in stripped.split() if part.strip()]


def is_header(line: str) -> bool:
    return normalize_header(line) == EXPECTED_COLUMNS


def is_separator(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if set(stripped.replace("|", "").replace(" ", "")) <= {"-"}:
        return True
    return False


def find_table_lines(text: str) -> list[str]:
    lines = [line.rstrip() for line in text.splitlines()]

    try:
        header_idx = next(idx for idx, line in enumerate(lines) if is_header(line))
    except StopIteration as exc:
        raise ValueError("Expected canonical TABLE 2 header not found") from exc

    out: list[str] = []

    for line in lines[header_idx + 1:]:
        stripped = line.strip()

        if not stripped:
            continue
        if is_separator(stripped):
            continue
        if stripped.lower().startswith("note:"):
            break
        if stripped.upper().startswith("TABLE "):
            break
        if stripped.startswith("#"):
            continue

        out.append(stripped)

    return out


def split_row(line: str) -> list[str]:
    if "|" in line:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        return [cell for cell in cells]

    return line.split(maxsplit=7)


def parse_row(line: str, prediction_ts_utc: str, source_path: Path) -> dict[str, Any]:
    parts = split_row(line)

    if len(parts) != 8:
        raise ValueError(f"Expected 8 parsed fields including notes, got {len(parts)}: {line}")

    row = {
        "prediction_ts_utc": prediction_ts_utc,
        "source_type": "external_symbolic_aplus_snapshot",
        "table_type": "canonical_harmonic_phase_overlay_table_2",
        "research_only": True,
        "token": parts[0].strip().upper(),
        "harmonic_phase": parts[1].strip().lower(),
        "phase_state": parts[2].strip().lower(),
        "offset_band": parts[3].strip(),
        "drift_direction": parts[4].strip().lower(),
        "quality": parts[5].strip().lower(),
        "extension_risk": parts[6].strip().lower(),
        "notes": parts[7].strip(),
        "source_path": str(source_path),
        "parser": REPORT_NAME,
        "parser_version": VERSION,
    }

    if not row["token"]:
        raise ValueError(f"Empty token in line: {line}")

    for key, allowed_values in ALLOWED.items():
        value = str(row[key])
        if value not in allowed_values:
            raise ValueError(f"Invalid {key}={value!r} for token={row['token']}")

    return row


def parse_file(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    prediction_ts_utc = parse_prediction_ts(text)
    table_lines = find_table_lines(text)
    rows = [parse_row(line, prediction_ts_utc, path) for line in table_lines]

    tokens = [row["token"] for row in rows]
    duplicate_tokens = sorted(token for token, count in Counter(tokens).items() if count > 1)

    if duplicate_tokens:
        raise ValueError(f"Duplicate token rows found: {duplicate_tokens}")

    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    if not rows:
        path.write_text("", encoding="utf-8")
        return

    fields = [
        "prediction_ts_utc",
        "source_type",
        "table_type",
        "research_only",
        "token",
        "harmonic_phase",
        "phase_state",
        "offset_band",
        "drift_direction",
        "quality",
        "extension_risk",
        "notes",
        "source_path",
        "parser",
        "parser_version",
    ]

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def print_counter(title: str, counter: Counter[str]) -> None:
    print(title)
    for key in sorted(counter):
        print(f"{key}={counter[key]}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse A+ canonical Harmonic Phase Overlay TABLE 2 snapshot.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--out-dir", default="data/research/aplus_table2_harmonic_overlay_v1")
    parser.add_argument("--output", choices=["table", "none"], default="table")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    input_path = Path(args.input)
    rows = parse_file(input_path)

    prediction_ts = str(rows[0]["prediction_ts_utc"]) if rows else "unknown"
    slug = slug_from_ts(prediction_ts)

    out_dir = Path(args.out_dir)
    jsonl_path = out_dir / f"aplus_table2_harmonic_overlay_{slug}.jsonl"
    csv_path = out_dir / f"aplus_table2_harmonic_overlay_{slug}.csv"

    write_jsonl(jsonl_path, rows)
    write_csv(csv_path, rows)

    harmonic_phase_counts = Counter(str(row["harmonic_phase"]) for row in rows)
    phase_state_counts = Counter(str(row["phase_state"]) for row in rows)
    offset_band_counts = Counter(str(row["offset_band"]) for row in rows)
    drift_direction_counts = Counter(str(row["drift_direction"]) for row in rows)
    quality_counts = Counter(str(row["quality"]) for row in rows)
    extension_risk_counts = Counter(str(row["extension_risk"]) for row in rows)

    clean_tokens = [row["token"] for row in rows if row["quality"] == "clean"]
    dirty_tokens = [row["token"] for row in rows if row["quality"] == "dirty"]
    high_extension_risk_tokens = [row["token"] for row in rows if row["extension_risk"] == "high"]
    unstable_tokens = [
        row["token"]
        for row in rows
        if row["drift_direction"] == "unstable" or row["offset_band"] in {"+9", "+10.5", "-9", "-10.5"}
    ]

    if args.output == "table":
        print(f"report={REPORT_NAME} version={VERSION}")
        print("scope=research-only market-only account-agnostic")
        print("db_writes=0 broker_calls=0 broker_writes=0 order_submission=0")
        print("selection_engine=none decision_gate=none execution_planner=none executor=none")
        print(f"input={input_path}")
        print(f"prediction_ts_utc={prediction_ts}")
        print(f"rows={len(rows)}")
        print(f"wrote_jsonl={jsonl_path}")
        print(f"wrote_csv={csv_path}")
        print("")

        print_counter("harmonic_phase_counts", harmonic_phase_counts)
        print("")
        print_counter("phase_state_counts", phase_state_counts)
        print("")
        print_counter("offset_band_counts", offset_band_counts)
        print("")
        print_counter("drift_direction_counts", drift_direction_counts)
        print("")
        print_counter("quality_counts", quality_counts)
        print("")
        print_counter("extension_risk_counts", extension_risk_counts)
        print("")

        print("clean_tokens=" + ",".join(clean_tokens))
        print("dirty_tokens=" + ",".join(dirty_tokens))
        print("high_extension_risk_tokens=" + ",".join(high_extension_risk_tokens))
        print("unstable_tokens=" + ",".join(unstable_tokens))
        print("")
        print("[DONE] db_writes=0 broker_calls=0 broker_writes=0 order_submission=0")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
