from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPORT_NAME = "aplus_canonical_table1_v1"
VERSION = "0.1"

EXPECTED_HEADER = (
    "TOKEN PHASE COHERENCE FIELD GEOMETRY STRUCTURAL_ROLE "
    "EXPANSION_QUALITY ANCHOR_STRENGTH STRATEGIC_BIAS NOTES"
)

ALLOWED = {
    "phase": {"early", "forming", "confirmed", "late", "exhaustion", "reset", "neutral"},
    "coherence": {"high", "moderate", "low"},
    "field": {"expansion", "compression", "transition", "neutral"},
    "geometry": {"clean", "mixed", "distorted", "unknown"},
    "structural_role": {"leader", "confirmer", "laggard", "speculative", "defensive", "unknown"},
    "expansion_quality": {"strong", "moderate", "weak", "none"},
    "anchor_strength": {"strong", "moderate", "weak", "none"},
    "strategic_bias": {"accumulation", "continuation", "caution", "avoid", "neutral"},
}


def parse_prediction_ts(text: str) -> str:
    match = re.search(r"prediction_ts_utc\s*=\s*([0-9T:\-]+Z)", text)
    if not match:
        raise ValueError("Could not find prediction_ts_utc in raw file")

    raw = match.group(1)
    dt = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def ts_slug(prediction_ts_utc: str) -> str:
    return prediction_ts_utc.replace("-", "").replace(":", "").replace("T", "T").replace("Z", "Z")


def find_table_lines(text: str) -> list[str]:
    lines = [line.rstrip() for line in text.splitlines()]
    try:
        header_idx = next(idx for idx, line in enumerate(lines) if line.strip() == EXPECTED_HEADER)
    except StopIteration as exc:
        raise ValueError("Expected canonical TABLE 1 header not found") from exc

    out: list[str] = []
    for line in lines[header_idx + 1 :]:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.lower().startswith("note:"):
            break
        if stripped.upper().startswith("TABLE "):
            break
        out.append(stripped)

    return out


def parse_row(line: str, prediction_ts_utc: str, source_path: Path) -> dict[str, Any]:
    parts = line.split(maxsplit=9)
    if len(parts) != 10:
        raise ValueError(f"Expected 10 parsed fields including notes, got {len(parts)}: {line}")

    row = {
        "prediction_ts_utc": prediction_ts_utc,
        "source_type": "external_symbolic_aplus_snapshot",
        "table_type": "canonical_breathline_table_1",
        "research_only": True,
        "token": parts[0].upper(),
        "phase": parts[1].lower(),
        "coherence": parts[2].lower(),
        "field": parts[3].lower(),
        "geometry": parts[4].lower(),
        "structural_role": parts[5].lower(),
        "expansion_quality": parts[6].lower(),
        "anchor_strength": parts[7].lower(),
        "strategic_bias": parts[8].lower(),
        "notes": parts[9].strip(),
        "source_path": str(source_path),
        "parser": REPORT_NAME,
        "parser_version": VERSION,
    }

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
        return

    fields = [
        "prediction_ts_utc",
        "source_type",
        "table_type",
        "research_only",
        "token",
        "phase",
        "coherence",
        "field",
        "geometry",
        "structural_role",
        "expansion_quality",
        "anchor_strength",
        "strategic_bias",
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse A+ canonical Breathline TABLE 1 snapshot.")
    parser.add_argument(
        "--input",
        default="data/aplus_raw/2026-05-13_1915_table1_canonical_breathline.txt",
    )
    parser.add_argument(
        "--out-dir",
        default="data/research/aplus_canonical_table1_v1",
    )
    parser.add_argument("--output", choices=["table", "none"], default="table")
    args = parser.parse_args()

    input_path = Path(args.input)
    rows = parse_file(input_path)

    prediction_ts = str(rows[0]["prediction_ts_utc"]) if rows else "unknown"
    slug = prediction_ts.replace("-", "").replace(":", "").replace("T", "T").replace("Z", "Z")

    out_dir = Path(args.out_dir)
    jsonl_path = out_dir / f"aplus_canonical_table1_{slug}.jsonl"
    csv_path = out_dir / f"aplus_canonical_table1_{slug}.csv"

    write_jsonl(jsonl_path, rows)
    write_csv(csv_path, rows)

    role_counts = Counter(str(row["structural_role"]) for row in rows)
    bias_counts = Counter(str(row["strategic_bias"]) for row in rows)
    phase_counts = Counter(str(row["phase"]) for row in rows)

    leaders = [
        row["token"]
        for row in rows
        if row["structural_role"] == "leader"
    ]

    canonical_core = [
        row["token"]
        for row in rows
        if row["structural_role"] == "leader"
        and row["coherence"] == "high"
        and row["geometry"] in {"clean", "mixed"}
        and row["expansion_quality"] in {"strong", "moderate"}
        and row["anchor_strength"] in {"strong", "moderate"}
        and row["strategic_bias"] in {"accumulation", "continuation"}
    ]

    avoid_tokens = [
        row["token"]
        for row in rows
        if row["strategic_bias"] == "avoid"
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
        print_counter("phase_counts", phase_counts)
        print("")
        print_counter("role_counts", role_counts)
        print("")
        print_counter("bias_counts", bias_counts)
        print("")
        print("leaders=" + ",".join(leaders))
        print("canonical_core=" + ",".join(canonical_core))
        print("avoid_tokens=" + ",".join(avoid_tokens))
        print("")
        print("[DONE] db_writes=0 broker_calls=0 broker_writes=0 order_submission=0")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
