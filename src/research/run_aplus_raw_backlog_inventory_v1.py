from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPORT_NAME = "aplus_raw_backlog_inventory_v1"
PARSER_VERSION = "0.1"

DEFAULT_ROOTS = [
    "data/aplus_raw",
    "data/research/aplus_table1_table2_normalized_v1",
    "data/research/aplus_table2_harmonic_overlay_v1",
]

TABLE1_REQUIRED_TOKENS = [
    "TOKEN",
    "PHASE",
    "COHERENCE",
    "FIELD",
    "GEOMETRY",
    "STRUCTURAL_ROLE",
    "EXPANSION_QUALITY",
    "ANCHOR_STRENGTH",
    "STRATEGIC_BIAS",
    "NOTES",
]
TABLE2_REQUIRED_TOKENS = [
    "TOKEN",
    "HARMONIC_PHASE",
    "PHASE_STATE",
    "OFFSET_BAND",
    "DRIFT_DIRECTION",
    "QUALITY",
    "EXTENSION_RISK",
    "NOTES",
]

CONSISTENCY_HEADER_TOKENS = ["MOMENTUM", "STABILITY", "ALIGNMENT", "VOLATILITY"]
CLUSTER_HEADER_TOKENS = ["CLUSTER_GROUP", "CLUSTER_STRENGTH", "DIVERGENCE_FLAG"]
EARLY_PROSE_SIGNATURES = [
    "Codex Breathline Resonance",
    "Emotional Load",
    "Distortion Level",
]

TS_INLINE_RE = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})Z")
TS_FROM_NAME_RE = re.compile(
    r"(\d{4})[-_](\d{2})[-_](\d{2})(?:[-_T]?(\d{2})(\d{2})(?:(\d{2}))?)?"
)
TS_COMPACT_RE = re.compile(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z")

CURRENT_LANE_RAW_BASENAMES = {
    "2026-05-15_1244_table1_breathline_vector_snapshot.txt",
    "2026-05-15_1244_table2_harmonic_phase_overlay.txt",
}
CURRENT_LANE_OUTPUT_BASENAMES = {
    "table1_normalized_20260515_1244.jsonl",
    "table2_normalized_20260515_1244.jsonl",
    "table1_table2_joined_20260515_1244.jsonl",
    "validation_summary_20260515_1244.json",
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inventory the A+ raw backlog: classify files, detect duplicates, separate parse-ready from old/unknown formats. Research-only."
    )
    parser.add_argument("--roots", nargs="+", default=DEFAULT_ROOTS)
    parser.add_argument(
        "--output-dir",
        default="data/research/aplus_raw_backlog_inventory_v1",
    )
    parser.add_argument("--output", choices=["table", "json"], default="table")
    parser.add_argument("--write-files", action="store_true")
    return parser.parse_args(argv)


def iter_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    if root.is_file():
        return [root]
    return sorted(p for p in root.rglob("*") if p.is_file())


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_text_safe(path: Path, max_bytes: int = 200_000) -> str | None:
    try:
        with path.open("rb") as fh:
            raw = fh.read(max_bytes)
    except OSError:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return raw.decode("latin-1")
        except UnicodeDecodeError:
            return None


def is_probably_text(path: Path, sample: bytes) -> bool:
    if not sample:
        return True
    if b"\x00" in sample[:4096]:
        return False
    return True


def detect_table_headers(text: str) -> tuple[bool, bool]:
    has_t1 = False
    has_t2 = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        upper = stripped.upper()
        if not has_t1 and all(tok in upper for tok in TABLE1_REQUIRED_TOKENS):
            has_t1 = True
        if not has_t2 and all(tok in upper for tok in TABLE2_REQUIRED_TOKENS):
            has_t2 = True
        if has_t1 and has_t2:
            break
    return has_t1, has_t2


def detect_legacy_schema(text: str) -> str | None:
    upper = text.upper()
    if all(tok in upper for tok in CONSISTENCY_HEADER_TOKENS):
        return "CONSISTENCY_RUN"
    if any(tok in upper for tok in CLUSTER_HEADER_TOKENS):
        return "CLUSTER_EXTENSION"
    for signature in EARLY_PROSE_SIGNATURES:
        if signature.lower() in text.lower():
            return "EARLY_PROSE"
    return None


def guess_snapshot_ts(text: str | None, name: str) -> str | None:
    if text:
        m = TS_INLINE_RE.search(text)
        if m:
            try:
                dt = datetime.strptime(m.group(0).rstrip("Z"), "%Y-%m-%dT%H:%M:%S")
                return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
            except ValueError:
                pass

    compact = TS_COMPACT_RE.search(name)
    if compact:
        y, mo, d, hh, mm, ss = compact.groups()
        try:
            dt = datetime(int(y), int(mo), int(d), int(hh), int(mm), int(ss), tzinfo=timezone.utc)
            return dt.isoformat().replace("+00:00", "Z")
        except ValueError:
            pass

    m = TS_FROM_NAME_RE.search(name)
    if m:
        y, mo, d, hh, mm, ss = m.groups()
        try:
            hour = int(hh) if hh is not None else 0
            minute = int(mm) if mm is not None else 0
            second = int(ss) if ss is not None else 0
            dt = datetime(int(y), int(mo), int(d), hour, minute, second, tzinfo=timezone.utc)
            return dt.isoformat().replace("+00:00", "Z")
        except ValueError:
            pass

    return None


def token_count_guess(text: str) -> int | None:
    if not text:
        return None
    count = 0
    seen: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.upper().startswith("TOKEN"):
            continue
        head = stripped.split("|", 1)[0].strip() if "|" in stripped else stripped.split()[0] if stripped.split() else ""
        head = head.upper()
        if 2 <= len(head) <= 8 and head.replace("+", "").replace("-", "").replace("_", "").isalnum() and head[0].isalpha():
            if head not in seen:
                seen.add(head)
                count += 1
    return count if count else None


def classify_file(path: Path, dir_root: Path) -> dict[str, Any]:
    name = path.name
    stat = path.stat()
    file_size_bytes = stat.st_size
    mtime_utc = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat().replace("+00:00", "Z")

    digest = sha256_of(path)

    head_bytes: bytes = b""
    try:
        with path.open("rb") as fh:
            head_bytes = fh.read(4096)
    except OSError:
        head_bytes = b""

    text: str | None = None
    if is_probably_text(path, head_bytes):
        text = read_text_safe(path)

    line_count: int | None = None
    if text is not None:
        line_count = sum(1 for _ in text.splitlines())

    has_t1, has_t2 = (False, False)
    legacy = None
    is_jsonl_normalized = False
    is_jsonl_t2_overlay = False
    is_json_summary = False
    is_derived_csv = False
    under_research_dir = "data/research/" in str(path).replace("\\", "/")

    if text:
        sample = text[:8000]
        stripped_sample = sample.lstrip()
        if path.suffix.lower() == ".jsonl" and stripped_sample.startswith("{"):
            if '"schema_version": "aplus_table1_table2_normalized_v1"' in sample or '"table1_phase"' in sample:
                is_jsonl_normalized = True
            elif '"table_type": "canonical_harmonic_phase_overlay_table_2"' in sample or '"harmonic_phase"' in sample:
                is_jsonl_t2_overlay = True
        elif path.suffix.lower() == ".json" and stripped_sample.startswith("{"):
            if '"report"' in sample and ("aplus_table1_table2" in sample or "validation_summary" in sample):
                is_json_summary = True
        elif path.suffix.lower() == ".csv" and under_research_dir:
            is_derived_csv = True

        if not (is_jsonl_normalized or is_jsonl_t2_overlay or is_json_summary or is_derived_csv):
            has_t1, has_t2 = detect_table_headers(text)
            legacy = detect_legacy_schema(text)

    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        source_format = "jsonl"
    elif suffix == ".json":
        source_format = "jsonl"
    elif suffix == ".csv":
        source_format = "raw_text"
    elif suffix == ".txt":
        source_format = "markdown_table" if (text and "|" in text and (has_t1 or has_t2)) else "raw_text"
    else:
        source_format = "unknown"

    if is_jsonl_normalized or is_jsonl_t2_overlay or is_derived_csv:
        guessed_table_type = "NORMALIZED_JOINED_JSONL"
    elif is_json_summary:
        guessed_table_type = "UNKNOWN"
    elif has_t1 and not has_t2:
        guessed_table_type = "TABLE1_BREATHLINE_VECTOR"
    elif has_t2 and not has_t1:
        guessed_table_type = "TABLE2_HARMONIC_PHASE"
    elif has_t1 and has_t2:
        guessed_table_type = "TABLE1_BREATHLINE_VECTOR"
    elif legacy == "CONSISTENCY_RUN":
        guessed_table_type = "CONSISTENCY_RUN"
    elif legacy == "CLUSTER_EXTENSION":
        guessed_table_type = "CLUSTER_EXTENSION"
    else:
        guessed_table_type = "UNKNOWN"

    snapshot_ts = guess_snapshot_ts(text, name)
    token_count = token_count_guess(text) if text else None

    is_current_lane_raw = name in CURRENT_LANE_RAW_BASENAMES
    is_current_lane_output = name in CURRENT_LANE_OUTPUT_BASENAMES

    parse_candidate = False
    ingestion_status = "UNKNOWN"
    reason_parts: list[str] = []

    if guessed_table_type == "NORMALIZED_JOINED_JSONL":
        parse_candidate = False
        ingestion_status = "NEEDS_REVIEW"
        if is_current_lane_output:
            reason_parts.append("current canonical normalized output (aplus_table1_table2_normalized_v1)")
        elif is_jsonl_normalized:
            reason_parts.append("prior-lane joined jsonl with v1-style schema; review whether it can be reproduced from raw")
        else:
            reason_parts.append("prior-lane Table 2 overlay normalized jsonl; review whether raw is present")
    elif is_current_lane_output:
        parse_candidate = False
        ingestion_status = "NEEDS_REVIEW"
        reason_parts.append("companion file of current canonical lane output (e.g. validation_summary)")
    elif guessed_table_type == "CONSISTENCY_RUN":
        parse_candidate = False
        ingestion_status = "OLD_FORMAT"
        reason_parts.append("legacy MOMENTUM/STABILITY/ALIGNMENT consistency-run schema; not compatible with v1 Table 1/Table 2")
    elif guessed_table_type == "CLUSTER_EXTENSION":
        parse_candidate = False
        ingestion_status = "OLD_FORMAT"
        reason_parts.append("legacy CLUSTER_GROUP/CLUSTER_STRENGTH schema; not compatible with v1 Table 1/Table 2")
    elif legacy == "EARLY_PROSE":
        parse_candidate = False
        ingestion_status = "OLD_FORMAT"
        reason_parts.append("early prose-style A+ snapshot with non-v1 columns (e.g. Emotional Load / Distortion Level)")
    elif guessed_table_type == "TABLE1_BREATHLINE_VECTOR" or guessed_table_type == "TABLE2_HARMONIC_PHASE":
        if is_current_lane_raw:
            parse_candidate = False
            ingestion_status = "NEEDS_REVIEW"
            reason_parts.append("already normalized via aplus_table1_table2_normalized_v1 lane (2026-05-15 snapshot)")
        else:
            parse_candidate = True
            ingestion_status = "READY_FOR_PARSE"
            reason_parts.append("v1 Table 1/Table 2 header signature present")
            if token_count is not None and token_count < 5:
                parse_candidate = False
                ingestion_status = "NEEDS_REVIEW"
                reason_parts.append(f"low token_count_guess={token_count}; header present but body looks empty")
            elif file_size_bytes < 500:
                parse_candidate = False
                ingestion_status = "NEEDS_REVIEW"
                reason_parts.append(f"very small file ({file_size_bytes} bytes); header present but body suspect")
    else:
        parse_candidate = False
        ingestion_status = "UNKNOWN"
        reason_parts.append("no Table 1/Table 2 header signature and no recognized legacy schema")

    record: dict[str, Any] = {
        "file_path": str(path),
        "file_name": name,
        "root": str(dir_root),
        "file_size_bytes": int(file_size_bytes),
        "mtime_utc": mtime_utc,
        "sha256": digest,
        "suffix": suffix,
        "source_format": source_format,
        "guessed_table_type": guessed_table_type,
        "guessed_snapshot_ts_utc": snapshot_ts,
        "contains_table1_headers": bool(has_t1),
        "contains_table2_headers": bool(has_t2),
        "line_count": line_count,
        "token_count_guess": token_count,
        "parse_candidate": bool(parse_candidate),
        "ingestion_status": ingestion_status,
        "reason": "; ".join(reason_parts) if reason_parts else "",
    }
    return record


def apply_duplicate_detection(records: list[dict[str, Any]]) -> None:
    by_hash: dict[str, list[dict[str, Any]]] = {}
    for rec in records:
        by_hash.setdefault(rec["sha256"], []).append(rec)
    for digest, group in by_hash.items():
        if len(group) > 1:
            for rec in group:
                rec["duplicate_kind"] = "EXACT_SHA256"
                rec["duplicate_peers"] = sorted(r["file_path"] for r in group if r["file_path"] != rec["file_path"])
                if rec["ingestion_status"] in {"READY_FOR_PARSE", "UNKNOWN"}:
                    rec["ingestion_status"] = "DUPLICATE_CANDIDATE"
                    rec["parse_candidate"] = False
                    rec["reason"] = (rec["reason"] + "; " if rec["reason"] else "") + (
                        f"exact sha256 duplicate of {len(group) - 1} other file(s)"
                    )

    by_semantic: dict[tuple[str | None, str], list[dict[str, Any]]] = {}
    for rec in records:
        key = (rec.get("guessed_snapshot_ts_utc"), rec["guessed_table_type"])
        if key[0] is None or key[1] in {"UNKNOWN"}:
            continue
        by_semantic.setdefault(key, []).append(rec)
    for key, group in by_semantic.items():
        if len(group) > 1:
            file_paths = sorted(r["file_path"] for r in group)
            for rec in group:
                if "duplicate_kind" in rec and rec["duplicate_kind"] == "EXACT_SHA256":
                    continue
                rec["duplicate_kind"] = rec.get("duplicate_kind") or "SAME_TS_AND_TYPE"
                rec["duplicate_peers"] = [p for p in file_paths if p != rec["file_path"]]
                if rec["ingestion_status"] in {"READY_FOR_PARSE", "UNKNOWN"}:
                    rec["ingestion_status"] = "DUPLICATE_CANDIDATE"
                    rec["parse_candidate"] = False
                    rec["reason"] = (rec["reason"] + "; " if rec["reason"] else "") + (
                        f"same snapshot_ts+table_type as {len(group) - 1} other file(s) (semantic duplicate candidate)"
                    )


def collect_records(roots: list[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for root in roots:
        for path in iter_files(root):
            if path in seen:
                continue
            seen.add(path)
            records.append(classify_file(path, root))
    return records


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    type_counts = Counter(r["guessed_table_type"] for r in records)
    status_counts = Counter(r["ingestion_status"] for r in records)
    fmt_counts = Counter(r["source_format"] for r in records)
    parse_ready = [r["file_path"] for r in records if r["ingestion_status"] == "READY_FOR_PARSE"]
    needs_review = [r["file_path"] for r in records if r["ingestion_status"] == "NEEDS_REVIEW"]
    old_format = [r["file_path"] for r in records if r["ingestion_status"] == "OLD_FORMAT"]
    duplicate_candidates = [r["file_path"] for r in records if r["ingestion_status"] == "DUPLICATE_CANDIDATE"]
    unknown = [r["file_path"] for r in records if r["ingestion_status"] == "UNKNOWN"]
    duplicate_groups: dict[str, list[str]] = {}
    for r in records:
        if "duplicate_peers" in r:
            key = r["sha256"]
            duplicate_groups.setdefault(key, []).append(r["file_path"])
    duplicate_groups = {k: sorted(set(v)) for k, v in duplicate_groups.items() if len(set(v)) > 1}

    return {
        "total_files": len(records),
        "type_counts": dict(sorted(type_counts.items())),
        "status_counts": dict(sorted(status_counts.items())),
        "format_counts": dict(sorted(fmt_counts.items())),
        "ready_for_parse": sorted(parse_ready),
        "needs_review": sorted(needs_review),
        "old_format": sorted(old_format),
        "duplicate_candidates": sorted(duplicate_candidates),
        "unknown": sorted(unknown),
        "duplicate_groups_by_sha256": duplicate_groups,
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True, ensure_ascii=False, default=str) + "\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n")


def render_table(summary: dict[str, Any], output_paths: dict[str, str], wrote: bool) -> str:
    lines: list[str] = []
    lines.append(f"report={REPORT_NAME} version={PARSER_VERSION}")
    lines.append("scope=research-only market-only account-agnostic")
    lines.append("db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0")
    lines.append("selection_engine=none advice_engine=none decision_gate=none execution_planner=none executor=none")
    lines.append(f"total_files={summary['total_files']}")
    lines.append("")
    lines.append("--- guessed_table_type counts ---")
    for k, v in summary["type_counts"].items():
        lines.append(f"  {k}={v}")
    lines.append("")
    lines.append("--- ingestion_status counts ---")
    for k, v in summary["status_counts"].items():
        lines.append(f"  {k}={v}")
    lines.append("")
    lines.append("--- source_format counts ---")
    for k, v in summary["format_counts"].items():
        lines.append(f"  {k}={v}")
    lines.append("")
    lines.append(f"ready_for_parse={len(summary['ready_for_parse'])}")
    for p in summary["ready_for_parse"]:
        lines.append(f"  {p}")
    lines.append("")
    lines.append(f"needs_review={len(summary['needs_review'])}")
    for p in summary["needs_review"]:
        lines.append(f"  {p}")
    lines.append("")
    lines.append(f"old_format={len(summary['old_format'])}")
    for p in summary["old_format"]:
        lines.append(f"  {p}")
    lines.append("")
    lines.append(f"duplicate_candidates={len(summary['duplicate_candidates'])}")
    for p in summary["duplicate_candidates"]:
        lines.append(f"  {p}")
    lines.append("")
    lines.append(f"duplicate_groups_by_sha256={len(summary['duplicate_groups_by_sha256'])}")
    for sha, files in summary["duplicate_groups_by_sha256"].items():
        lines.append(f"  {sha[:12]}…: {len(files)} files")
        for f in files:
            lines.append(f"    - {f}")
    lines.append("")
    lines.append(f"wrote_files={wrote}")
    if wrote:
        for k, v in output_paths.items():
            lines.append(f"  {k}={v}")
    lines.append("[DONE] db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    roots = [Path(r) for r in args.roots]
    records = collect_records(roots)
    apply_duplicate_detection(records)
    summary = summarize(records)

    out_dir = Path(args.output_dir)
    output_paths = {
        "manifest_jsonl": str(out_dir / "aplus_raw_backlog_manifest_v1.jsonl"),
        "summary_json": str(out_dir / "aplus_raw_backlog_summary_v1.json"),
    }

    payload: dict[str, Any] = {
        "report": REPORT_NAME,
        "parser_version": PARSER_VERSION,
        "scope": "research-only market-only account-agnostic",
        "roots": [str(r) for r in roots],
        "total_files": summary["total_files"],
        "type_counts": summary["type_counts"],
        "status_counts": summary["status_counts"],
        "format_counts": summary["format_counts"],
        "ready_for_parse": summary["ready_for_parse"],
        "needs_review": summary["needs_review"],
        "old_format": summary["old_format"],
        "duplicate_candidates": summary["duplicate_candidates"],
        "unknown": summary["unknown"],
        "duplicate_groups_by_sha256": summary["duplicate_groups_by_sha256"],
        "output_paths": output_paths,
        "wrote_files": bool(args.write_files),
        "safety_markers": {
            "broker_calls": 0,
            "broker_writes": 0,
            "order_submission": 0,
            "live_orders": 0,
            "db_writes": 0,
            "selection_engine_changes": 0,
            "advice_engine_changes": 0,
            "decision_gate_changes": 0,
            "execution_planner_changes": 0,
            "executor_changes": 0,
            "paper_live_logic": "not_allowed",
            "account_state": "not_allowed",
            "research_only": True,
            "market_only": True,
            "account_agnostic": True,
        },
    }

    if args.write_files:
        write_jsonl(Path(output_paths["manifest_jsonl"]), records)
        write_json(Path(output_paths["summary_json"]), payload)

    if args.output == "json":
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str))
    else:
        print(render_table(summary, output_paths, bool(args.write_files)))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
