from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

from src.breathline.parse_aplus_table1_canonical_v1 import parse_table1_raw
from src.breathline.parse_aplus_table2_harmonic_overlay_v1 import parse_table2_raw


REPORT_NAME = "aplus_table1_table2_normalized_load_v1"
VERSION = "0.1"

DEFAULT_TABLE1_RAW = "data/aplus_raw/2026-05-14_1315_table1_canonical_breathline.txt"
DEFAULT_TABLE2_RAW = "data/aplus_raw/2026-05-14_1256_table2_harmonic_phase_overlay.txt"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build research-only normalized A+ Table 1 + Table 2 records."
    )
    parser.add_argument("--table1-raw", default=DEFAULT_TABLE1_RAW)
    parser.add_argument("--table2-raw", default=DEFAULT_TABLE2_RAW)
    parser.add_argument("--out-file", default="")
    parser.add_argument("--output", choices=["table", "jsonl", "none"], default="table")
    parser.add_argument(
        "--write-db",
        action="store_true",
        help="Reserved for future use. Not implemented in v1.",
    )
    return parser.parse_args()


def classify_table1(row: dict[str, Any]) -> str:
    if row["strategic_bias"] == "avoid":
        return "APLUS_T1_AVOID"

    if row["strategic_bias"] == "caution":
        return "APLUS_T1_CAUTION"

    if (
        row["structural_role"] == "leader"
        and row["coherence"] == "high"
        and row["geometry"] == "clean"
        and row["expansion_quality"] in {"strong", "moderate"}
        and row["anchor_strength"] in {"strong", "moderate"}
        and row["strategic_bias"] in {"accumulation", "continuation"}
    ):
        return "APLUS_T1_CORE"

    if (
        row["structural_role"] in {"confirmer", "defensive"}
        and row["anchor_strength"] in {"strong", "moderate"}
        and row["strategic_bias"] in {"accumulation", "continuation", "neutral"}
    ):
        return "APLUS_T1_ANCHOR_CONTEXT"

    return "APLUS_T1_OTHER"


def classify_table2(row: dict[str, Any]) -> str:
    if row["quality"] == "dirty" and row["extension_risk"] == "high":
        return "APLUS_T2_DIRTY_HIGH_RISK"

    if row["harmonic_phase"] in {"extension_1272", "late_extension"} and row["extension_risk"] == "high":
        return "APLUS_T2_EXTENSION_HIGH_RISK"

    if (
        row["harmonic_phase"] == "confirmed_0618"
        and row["phase_state"] == "confirmed"
        and row["quality"] == "clean"
        and row["extension_risk"] == "low"
    ):
        return "APLUS_T2_CLEAN_0618_CONFIRMED"

    if row["harmonic_phase"] == "confirmed_1000" and row["quality"] == "clean":
        return "APLUS_T2_CLEAN_1000"

    if row["harmonic_phase"] == "reset":
        return "APLUS_T2_RESET"

    if row["harmonic_phase"].startswith("forming_"):
        return "APLUS_T2_FORMING"

    if row["harmonic_phase"] == "pre_0618":
        return "APLUS_T2_PRE_0618"

    return "APLUS_T2_OTHER"


def combined_read(table1_bucket: str, table2_bucket: str, table2: dict[str, Any]) -> str:
    t1_supportive = table1_bucket in {"APLUS_T1_CORE", "APLUS_T1_ANCHOR_CONTEXT"}
    t1_risk = table1_bucket in {"APLUS_T1_CAUTION", "APLUS_T1_AVOID"}
    t2_clean = table2_bucket in {"APLUS_T2_CLEAN_0618_CONFIRMED", "APLUS_T2_CLEAN_1000"}
    t2_risk = (
        table2_bucket in {"APLUS_T2_DIRTY_HIGH_RISK", "APLUS_T2_EXTENSION_HIGH_RISK"}
        or table2["extension_risk"] == "high"
        or table2["quality"] == "dirty"
    )

    if t1_supportive and t2_clean:
        return "ALIGNED_CORE_CLEAN"

    if t1_risk and t2_risk:
        return "ALIGNED_RISK"

    if t1_supportive and t2_risk:
        return "CONFLICT_T1_SUPPORT_T2_RISK"

    if t1_risk and t2_clean:
        return "CONFLICT_T1_RISK_T2_CLEAN"

    return "NEUTRAL_OR_MIXED"


def load_table1(path: Path) -> dict[str, dict[str, Any]]:
    raw = path.read_text(encoding="utf-8")
    records = [asdict(record) for record in parse_table1_raw(raw)]
    return {str(record["token"]): record for record in records}


def load_table2(path: Path) -> dict[str, dict[str, Any]]:
    raw = path.read_text(encoding="utf-8")
    records = [asdict(record) for record in parse_table2_raw(raw)]
    return {str(record["token"]): record for record in records}


def build_normalized(table1: dict[str, dict[str, Any]], table2: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    table1_tokens = set(table1.keys())
    table2_tokens = set(table2.keys())

    if table1_tokens != table2_tokens:
        missing_table1 = sorted(table2_tokens - table1_tokens)
        missing_table2 = sorted(table1_tokens - table2_tokens)
        raise ValueError(
            "Table token sets differ: "
            f"missing_table1={missing_table1} missing_table2={missing_table2}"
        )

    rows: list[dict[str, Any]] = []

    for token in sorted(table1_tokens):
        t1 = table1[token]
        t2 = table2[token]

        t1_bucket = classify_table1(t1)
        t2_bucket = classify_table2(t2)
        read = combined_read(t1_bucket, t2_bucket, t2)

        rows.append(
            {
                "schema_version": "aplus_table1_table2_normalized_v1",
                "source_type": "external_symbolic_aplus_snapshot",
                "research_only": True,
                "token": token,

                "table1_schema_version": t1["schema_version"],
                "table1_prediction_ts_utc": t1["prediction_ts_utc"],
                "table1_phase": t1["phase"],
                "table1_coherence": t1["coherence"],
                "table1_field": t1["field"],
                "table1_geometry": t1["geometry"],
                "table1_structural_role": t1["structural_role"],
                "table1_expansion_quality": t1["expansion_quality"],
                "table1_anchor_strength": t1["anchor_strength"],
                "table1_strategic_bias": t1["strategic_bias"],
                "table1_notes": t1["notes"],
                "table1_bucket": t1_bucket,

                "table2_schema_version": t2["schema_version"],
                "table2_prediction_ts_utc": t2["prediction_ts_utc"],
                "table2_harmonic_phase": t2["harmonic_phase"],
                "table2_phase_state": t2["phase_state"],
                "table2_offset_band": t2["offset_band"],
                "table2_drift_direction": t2["drift_direction"],
                "table2_quality": t2["quality"],
                "table2_extension_risk": t2["extension_risk"],
                "table2_notes": t2["notes"],
                "table2_bucket": t2_bucket,

                "combined_read": read,
                "loader": REPORT_NAME,
                "loader_version": VERSION,
            }
        )

    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")


def print_counter(title: str, rows: list[dict[str, Any]], field: str) -> None:
    counts = Counter(str(row[field]) for row in rows)
    print(title)
    for key in sorted(counts):
        print(f"  {key}: {counts[key]}")


def print_table(rows: list[dict[str, Any]]) -> None:
    print(f"report={REPORT_NAME} version={VERSION}")
    print("scope=research-only market-only account-agnostic")
    print("db_writes=0 broker_calls=0 broker_writes=0 order_submission=0")
    print("selection_engine=none decision_gate=none execution_planner=none executor=none")
    print("write_db=false")
    print(f"rows={len(rows)}")
    print("")

    print_counter("table1_bucket", rows, "table1_bucket")
    print("")
    print_counter("table2_bucket", rows, "table2_bucket")
    print("")
    print_counter("combined_read", rows, "combined_read")
    print("")

    columns = [
        "token",
        "table1_bucket",
        "table2_bucket",
        "combined_read",
        "table1_strategic_bias",
        "table2_harmonic_phase",
        "table2_offset_band",
        "table2_quality",
        "table2_extension_risk",
    ]

    print("\t".join(columns))
    for row in rows:
        print("\t".join(str(row[column]) for column in columns))

    print("")
    print("[DONE] db_writes=0 broker_calls=0 broker_writes=0 order_submission=0")


def main() -> int:
    args = parse_args()

    if args.write_db:
        raise SystemExit("DB writes are not implemented in v1. Use dry-run JSONL output first.")

    table1_path = Path(args.table1_raw)
    table2_path = Path(args.table2_raw)

    table1 = load_table1(table1_path)
    table2 = load_table2(table2_path)
    rows = build_normalized(table1, table2)

    if args.out_file:
        write_jsonl(Path(args.out_file), rows)

    if args.output == "jsonl":
        for row in rows:
            print(json.dumps(row, sort_keys=True, ensure_ascii=False))
    elif args.output == "table":
        print_table(rows)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
