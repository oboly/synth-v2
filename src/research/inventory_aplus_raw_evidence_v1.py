"""
A+ raw evidence inventory (Phase 1 of the A+ / Breathline V1 alignment study).

Research-only, read-only. Recursively inspects data/aplus_raw/ (or an explicit
--root) and produces a hashed, schema-classified, timestamp-provenance-tagged
inventory of candidate A+ source files. This is a survey tool: it does not
select an anchor, does not compute a Breathline state, does not join to
market data, and does not draw any conclusion. See
docs/research/aplus_breathline_alignment_contract_v1.md.

data/aplus_raw is external local research evidence. This script never writes,
renames, moves, or edits anything under the scanned root; it only reads.
Generated inventory artifacts are written under
data/research/aplus_breathline_alignment_v1/<run_id>/ and are not meant to be
committed to git.

Safety markers:
  broker_private_calls=0
  broker_writes=0
  order_submission=0
  live_orders=0
  decision_gate=none
  execution_planner=none
  executor=none
  selection_engine=none
  db_writes=0
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPORT_NAME = "aplus_breathline_alignment_inventory_v1"
VERSION = "0.1"

DEFAULT_ROOT = "data/aplus_raw"
DEFAULT_OUT_BASE = "data/research/aplus_breathline_alignment_v1"

TABLE_TYPE_TABLE1 = "TABLE1_CANONICAL_BREATHLINE"
TABLE_TYPE_TABLE2 = "TABLE2_HARMONIC_OVERLAY"
TABLE_TYPE_UNSUPPORTED = "UNSUPPORTED_SCHEMA"

TABLE1_HEADER_TOKENS = (
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
)
TABLE2_HEADER_TOKENS = (
    "TOKEN",
    "HARMONIC_PHASE",
    "PHASE_STATE",
    "OFFSET_BAND",
    "DRIFT_DIRECTION",
    "QUALITY",
    "EXTENSION_RISK",
    "NOTES",
)
FIELD_NAMES_BY_TABLE_TYPE = {
    TABLE_TYPE_TABLE1: [
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
    ],
    TABLE_TYPE_TABLE2: [
        "token",
        "harmonic_phase",
        "phase_state",
        "offset_band",
        "drift_direction",
        "quality",
        "extension_risk",
        "notes",
    ],
}

TS_PROVENANCE_EXPLICIT = "EXPLICIT_SOURCE_TIMESTAMP"
TS_PROVENANCE_FILENAME = "FILENAME_INFERRED_TIMESTAMP"
TS_PROVENANCE_UNKNOWN = "UNKNOWN"

TIMESTAMP_ROLE_OBSERVATION = "OBSERVATION_TIME"
TIMESTAMP_ROLE_PREDICTION_TARGET = "PREDICTION_TARGET_TIME"
TIMESTAMP_ROLE_FILENAME_INFERRED = "FILENAME_INFERRED"
# An explicit timestamp with no named field to establish its semantic role
# (e.g. a bare "(2026-05-15T12:44:48Z)" in a title line). Never coerced into
# OBSERVATION_TIME or PREDICTION_TARGET_TIME without a named field as evidence.
TIMESTAMP_ROLE_UNLABELED_EXPLICIT = "UNLABELED_EXPLICIT"

# Named explicit-timestamp field patterns and the role each field name
# establishes. Add new named fields here only when a source explicitly labels
# them; never infer a role for an unlabeled bare timestamp.
NAMED_TIMESTAMP_FIELD_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "prediction_ts_utc",
        re.compile(r"prediction_ts_utc\s*=\s*([0-9T:\-]+Z)", re.IGNORECASE),
        TIMESTAMP_ROLE_PREDICTION_TARGET,
    ),
    (
        "observation_ts_utc",
        re.compile(r"observation_ts_utc\s*=\s*([0-9T:\-]+Z)", re.IGNORECASE),
        TIMESTAMP_ROLE_OBSERVATION,
    ),
)
BARE_ISO_TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
FILENAME_TS_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:_(\d{2})(\d{2}))?")
DECLARED_METADATA_LINE_RE = re.compile(r"^([a-z_][a-z0-9_]*)\s*=\s*(.+)$", re.IGNORECASE)
MARKDOWN_SEPARATOR_CELL_RE = re.compile(r"^:?-+:?$")


class InventoryIntegrityError(RuntimeError):
    """Raised for run-level fail-closed conditions (never partially resolved)."""


@dataclass
class ExplicitTimestamp:
    field_name: str | None
    raw: str
    iso: str
    role: str | None


@dataclass
class FileRecord:
    file_path: str
    file_name: str
    sha256: str
    file_size_bytes: int
    detected_table_type: str
    header_tokens: list[str] | None
    delimiter_style: str | None
    declared_metadata: dict[str, str]
    token_count: int | None
    explicit_timestamps: list[dict[str, Any]]
    filename_inferred_timestamp: str | None
    timestamp_provenance: str
    primary_timestamp_iso: str | None
    primary_timestamp_role: str | None
    assets: list[str]
    duplicate_assets_within_file: list[str]
    unparsed_row_count: int
    status: str
    status_notes: list[str] = field(default_factory=list)
    eligible_for_primary_analysis: bool = False


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    if root.is_file():
        return [root]
    return sorted(p for p in root.rglob("*") if p.is_file())


def read_text_safe(path: Path, max_bytes: int = 2_000_000) -> str | None:
    try:
        with path.open("rb") as handle:
            raw = handle.read(max_bytes)
    except OSError:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return raw.decode("latin-1")
        except UnicodeDecodeError:
            return None


def split_pipe_line(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [part.strip() for part in stripped.split("|")]


def tokenize_line(line: str) -> tuple[list[str], str]:
    if "|" in line:
        return split_pipe_line(line), "pipe"
    return line.split(), "space"


def is_markdown_separator_row(fields: list[str]) -> bool:
    non_empty = [f for f in fields if f]
    if not non_empty:
        return False
    return all(MARKDOWN_SEPARATOR_CELL_RE.match(f) for f in non_empty)


def detect_table_type(tokens: list[str]) -> str:
    token_set = {tok.upper() for tok in tokens if tok}
    if set(TABLE1_HEADER_TOKENS).issubset(token_set):
        return TABLE_TYPE_TABLE1
    if set(TABLE2_HEADER_TOKENS).issubset(token_set):
        return TABLE_TYPE_TABLE2
    return TABLE_TYPE_UNSUPPORTED


@dataclass
class HeaderMatch:
    line_index: int
    header_tokens: list[str]
    delimiter_style: str
    table_type: str


def find_header(lines: list[str]) -> HeaderMatch | None:
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        tokens, delimiter_style = tokenize_line(stripped)
        if is_markdown_separator_row(tokens):
            continue
        table_type = detect_table_type(tokens)
        if table_type != TABLE_TYPE_UNSUPPORTED:
            return HeaderMatch(
                line_index=idx,
                header_tokens=[tok.upper() for tok in tokens if tok],
                delimiter_style=delimiter_style,
                table_type=table_type,
            )
    return None


def split_data_row(line: str, delimiter_style: str, table_type: str) -> list[str] | None:
    field_names = FIELD_NAMES_BY_TABLE_TYPE[table_type]
    expected_count = len(field_names)
    if delimiter_style == "pipe":
        parts = split_pipe_line(line)
    else:
        parts = line.split(maxsplit=expected_count - 1)
    if len(parts) != expected_count:
        return None
    return parts


def parse_table_rows(
    lines: list[str], header: HeaderMatch
) -> tuple[list[dict[str, Any]], int]:
    field_names = FIELD_NAMES_BY_TABLE_TYPE[header.table_type]
    rows: list[dict[str, Any]] = []
    unparsed_row_count = 0
    for line in lines[header.line_index + 1 :]:
        stripped = line.strip()
        if not stripped:
            continue
        raw_tokens, delimiter_style = tokenize_line(stripped)
        if is_markdown_separator_row(raw_tokens):
            continue
        parts = split_data_row(stripped, header.delimiter_style, header.table_type)
        if parts is None:
            unparsed_row_count += 1
            continue
        row = {name: value for name, value in zip(field_names, parts)}
        row["token"] = row["token"].upper()
        rows.append(row)
    return rows, unparsed_row_count


def extract_declared_metadata(text: str) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = DECLARED_METADATA_LINE_RE.match(stripped)
        if match:
            key = match.group(1).lower()
            metadata.setdefault(key, match.group(2).strip())
    return metadata


def normalize_iso(raw: str) -> str | None:
    candidate = raw.strip()
    if not candidate.endswith("Z"):
        candidate = candidate + "Z"
    try:
        dt = datetime.strptime(candidate, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def extract_explicit_timestamps(text: str) -> list[ExplicitTimestamp]:
    found: list[ExplicitTimestamp] = []
    seen: set[tuple[str | None, str]] = set()
    consumed_spans: list[tuple[int, int]] = []

    for field_name, pattern, role in NAMED_TIMESTAMP_FIELD_PATTERNS:
        for match in pattern.finditer(text):
            raw = match.group(1)
            iso = normalize_iso(raw)
            if iso is None:
                continue
            consumed_spans.append(match.span(1))
            key = (field_name, iso)
            if key in seen:
                continue
            seen.add(key)
            found.append(ExplicitTimestamp(field_name=field_name, raw=raw, iso=iso, role=role))

    for match in BARE_ISO_TS_RE.finditer(text):
        span = match.span()
        if any(span[0] >= start and span[1] <= end for start, end in consumed_spans):
            continue
        raw = match.group(0)
        iso = normalize_iso(raw)
        if iso is None:
            continue
        key = (None, iso)
        if key in seen:
            continue
        seen.add(key)
        found.append(
            ExplicitTimestamp(field_name=None, raw=raw, iso=iso, role=TIMESTAMP_ROLE_UNLABELED_EXPLICIT)
        )

    return found


def infer_filename_timestamp(name: str) -> str | None:
    match = FILENAME_TS_RE.match(name)
    if not match:
        return None
    year, month, day, hour, minute = match.groups()
    try:
        dt = datetime(
            int(year),
            int(month),
            int(day),
            int(hour) if hour is not None else 0,
            int(minute) if minute is not None else 0,
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None
    return dt.isoformat().replace("+00:00", "Z")


def resolve_timestamp_provenance(
    explicit_timestamps: list[ExplicitTimestamp], filename_ts: str | None
) -> tuple[str, str | None, str | None, list[str]]:
    notes: list[str] = []
    distinct_isos = {ts.iso for ts in explicit_timestamps}

    if len(distinct_isos) == 1:
        chosen = explicit_timestamps[0]
        return TS_PROVENANCE_EXPLICIT, chosen.iso, chosen.role, notes

    if len(distinct_isos) > 1:
        notes.append(
            "ambiguous: multiple conflicting explicit timestamps found "
            f"({sorted(distinct_isos)}); none selected"
        )
        return TS_PROVENANCE_UNKNOWN, None, None, notes

    if filename_ts is not None:
        return TS_PROVENANCE_FILENAME, filename_ts, TIMESTAMP_ROLE_FILENAME_INFERRED, notes

    return TS_PROVENANCE_UNKNOWN, None, None, notes


def find_duplicate_assets(rows: list[dict[str, Any]]) -> list[str]:
    seen: dict[str, int] = {}
    for row in rows:
        token = row["token"]
        seen[token] = seen.get(token, 0) + 1
    return sorted(token for token, count in seen.items() if count > 1)


def classify_file(path: Path, root: Path) -> tuple[FileRecord, list[dict[str, Any]]]:
    stat = path.stat()
    digest = sha256_file(path)
    text = read_text_safe(path)

    header_tokens: list[str] | None = None
    delimiter_style: str | None = None
    table_type = TABLE_TYPE_UNSUPPORTED
    declared_metadata: dict[str, str] = {}
    rows: list[dict[str, Any]] = []
    unparsed_row_count = 0
    duplicate_assets: list[str] = []
    status = "OK"
    status_notes: list[str] = []

    explicit_timestamps: list[ExplicitTimestamp] = []
    filename_ts = infer_filename_timestamp(path.name)

    if text is None:
        status = "UNREADABLE"
        status_notes.append("could not decode file as utf-8 or latin-1")
    else:
        declared_metadata = extract_declared_metadata(text)
        explicit_timestamps = extract_explicit_timestamps(text)
        lines = text.splitlines()
        header = find_header(lines)
        if header is None:
            status = "UNSUPPORTED_SCHEMA"
            status_notes.append("no Table 1 / Table 2 header signature found")
        else:
            table_type = header.table_type
            header_tokens = header.header_tokens
            delimiter_style = header.delimiter_style
            rows, unparsed_row_count = parse_table_rows(lines, header)
            if not rows:
                status = "EMPTY_TABLE_BODY"
                status_notes.append("header matched but no parseable data rows were found")
            else:
                duplicate_assets = find_duplicate_assets(rows)
                if duplicate_assets:
                    status = "DUPLICATE_ASSET_ALIAS_WITHIN_FILE"
                    status_notes.append(
                        f"duplicate asset token(s) within one file: {', '.join(duplicate_assets)}"
                    )
            if unparsed_row_count:
                status_notes.append(f"unparsed_row_count={unparsed_row_count} (skipped, not fabricated)")

    provenance, primary_iso, primary_role, ts_notes = resolve_timestamp_provenance(
        explicit_timestamps, filename_ts
    )
    if ts_notes:
        status = "AMBIGUOUS_TIMESTAMP" if status == "OK" else status
        status_notes.extend(ts_notes)

    eligible = (
        provenance == TS_PROVENANCE_EXPLICIT
        and primary_role == TIMESTAMP_ROLE_OBSERVATION
        and status == "OK"
    )

    record = FileRecord(
        file_path=str(path),
        file_name=path.name,
        sha256=digest,
        file_size_bytes=int(stat.st_size),
        detected_table_type=table_type,
        header_tokens=header_tokens,
        delimiter_style=delimiter_style,
        declared_metadata=declared_metadata,
        token_count=len(rows) if rows else (0 if status == "EMPTY_TABLE_BODY" else None),
        explicit_timestamps=[
            {"field_name": ts.field_name, "raw": ts.raw, "iso": ts.iso, "role": ts.role}
            for ts in explicit_timestamps
        ],
        filename_inferred_timestamp=filename_ts,
        timestamp_provenance=provenance,
        primary_timestamp_iso=primary_iso,
        primary_timestamp_role=primary_role,
        assets=sorted({row["token"] for row in rows}),
        duplicate_assets_within_file=duplicate_assets,
        unparsed_row_count=unparsed_row_count,
        status=status,
        status_notes=status_notes,
        eligible_for_primary_analysis=eligible,
    )

    row_records: list[dict[str, Any]] = []
    if table_type != TABLE_TYPE_UNSUPPORTED and status not in {"UNREADABLE"}:
        for index, row in enumerate(rows):
            row_records.append(
                {
                    "source_file_hash": digest,
                    "source_file_path": str(path),
                    "source_file_name": path.name,
                    "detected_table_type": table_type,
                    "row_index_in_file": index,
                    "primary_timestamp_iso": primary_iso,
                    "timestamp_provenance": provenance,
                    "primary_timestamp_role": primary_role,
                    **row,
                }
            )

    return record, row_records


def check_duplicate_source_identity(records: list[FileRecord]) -> None:
    by_hash: dict[str, list[str]] = {}
    for record in records:
        by_hash.setdefault(record.sha256, []).append(record.file_path)
    duplicates = {digest: paths for digest, paths in by_hash.items() if len(paths) > 1}
    if duplicates:
        details = "; ".join(
            f"{digest[:12]}...: {sorted(paths)}" for digest, paths in sorted(duplicates.items())
        )
        raise InventoryIntegrityError(
            f"duplicate source identity: identical sha256 content found at multiple paths ({details})"
        )


def run_inventory(root: Path) -> tuple[list[FileRecord], list[dict[str, Any]]]:
    file_records: list[FileRecord] = []
    row_records: list[dict[str, Any]] = []
    for path in iter_files(root):
        record, rows = classify_file(path, root)
        file_records.append(record)
        row_records.extend(rows)
    check_duplicate_source_identity(file_records)
    return file_records, row_records


def build_summary(records: list[FileRecord], root: Path) -> dict[str, Any]:
    table_type_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    provenance_counts: dict[str, int] = {}
    role_counts: dict[str, int] = {}

    for record in records:
        table_type_counts[record.detected_table_type] = table_type_counts.get(record.detected_table_type, 0) + 1
        status_counts[record.status] = status_counts.get(record.status, 0) + 1
        provenance_counts[record.timestamp_provenance] = provenance_counts.get(record.timestamp_provenance, 0) + 1
        role_key = record.primary_timestamp_role or "NONE"
        role_counts[role_key] = role_counts.get(role_key, 0) + 1

    eligible = [r.file_path for r in records if r.eligible_for_primary_analysis]

    return {
        "report": REPORT_NAME,
        "version": VERSION,
        "root": str(root),
        "total_files": len(records),
        "table_type_counts": dict(sorted(table_type_counts.items())),
        "status_counts": dict(sorted(status_counts.items())),
        "timestamp_provenance_counts": dict(sorted(provenance_counts.items())),
        "timestamp_role_counts": dict(sorted(role_counts.items())),
        "primary_analysis_eligible_count": len(eligible),
        "primary_analysis_eligible_files": sorted(eligible),
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False, default=str) + "\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n")


def file_record_to_dict(record: FileRecord) -> dict[str, Any]:
    return {
        "file_path": record.file_path,
        "file_name": record.file_name,
        "sha256": record.sha256,
        "file_size_bytes": record.file_size_bytes,
        "detected_table_type": record.detected_table_type,
        "header_tokens": record.header_tokens,
        "delimiter_style": record.delimiter_style,
        "declared_metadata": record.declared_metadata,
        "token_count": record.token_count,
        "explicit_timestamps": record.explicit_timestamps,
        "filename_inferred_timestamp": record.filename_inferred_timestamp,
        "timestamp_provenance": record.timestamp_provenance,
        "primary_timestamp_iso": record.primary_timestamp_iso,
        "primary_timestamp_role": record.primary_timestamp_role,
        "assets": record.assets,
        "duplicate_assets_within_file": record.duplicate_assets_within_file,
        "unparsed_row_count": record.unparsed_row_count,
        "status": record.status,
        "status_notes": record.status_notes,
        "eligible_for_primary_analysis": record.eligible_for_primary_analysis,
    }


def render_table_summary(summary: dict[str, Any], output_paths: dict[str, str], wrote: bool) -> str:
    lines: list[str] = []
    lines.append(f"report={REPORT_NAME} version={VERSION}")
    lines.append("scope=research-only market-only account-agnostic read-only")
    lines.append(
        "db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0 "
        "selection_engine=none decision_gate=none execution_planner=none executor=none"
    )
    lines.append(f"root={summary['root']}")
    lines.append(f"total_files={summary['total_files']}")
    lines.append("")
    lines.append("--- detected_table_type counts ---")
    for key, value in summary["table_type_counts"].items():
        lines.append(f"  {key}={value}")
    lines.append("")
    lines.append("--- status counts ---")
    for key, value in summary["status_counts"].items():
        lines.append(f"  {key}={value}")
    lines.append("")
    lines.append("--- timestamp_provenance counts ---")
    for key, value in summary["timestamp_provenance_counts"].items():
        lines.append(f"  {key}={value}")
    lines.append("")
    lines.append("--- timestamp_role counts ---")
    for key, value in summary["timestamp_role_counts"].items():
        lines.append(f"  {key}={value}")
    lines.append("")
    lines.append(f"primary_analysis_eligible_count={summary['primary_analysis_eligible_count']}")
    for path in summary["primary_analysis_eligible_files"]:
        lines.append(f"  {path}")
    lines.append("")
    lines.append(f"wrote_files={wrote}")
    if wrote:
        for key, value in output_paths.items():
            lines.append(f"  {key}={value}")
    lines.append(
        "[DONE] db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0"
    )
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Phase 1 read-only inventory of A+ raw evidence for the A+/Breathline V1 "
            "alignment study. Research-only; never writes into the scanned root."
        )
    )
    parser.add_argument("--root", default=DEFAULT_ROOT)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_BASE)
    parser.add_argument("--output", choices=["table", "json"], default="table")
    parser.add_argument("--write-files", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = Path(args.root)

    try:
        records, row_records = run_inventory(root)
    except InventoryIntegrityError as exc:
        print(f"FAILED {exc}", flush=True)
        return 1

    summary = build_summary(records, root)

    started_at = datetime.now(timezone.utc)
    run_id = f"aplus_inventory_{started_at.strftime('%Y%m%dT%H%M%SZ')}"
    out_dir = Path(args.out_dir) / run_id
    output_paths = {
        "file_manifest_jsonl": str(out_dir / "evidence" / f"aplus_evidence_file_manifest_{run_id}.jsonl"),
        "rows_jsonl": str(out_dir / "evidence" / f"aplus_evidence_rows_{run_id}.jsonl"),
        "summary_json": str(out_dir / "manifest" / f"aplus_evidence_inventory_manifest_{run_id}.json"),
    }

    payload: dict[str, Any] = {
        **summary,
        "run_id": run_id,
        "generated_at_utc": started_at.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "output_paths": output_paths,
        "wrote_files": bool(args.write_files),
        "row_count": len(row_records),
        "safety_markers": {
            "broker_calls": 0,
            "broker_writes": 0,
            "order_submission": 0,
            "live_orders": 0,
            "db_writes": 0,
            "selection_engine_changes": 0,
            "decision_gate_changes": 0,
            "execution_planner_changes": 0,
            "executor_changes": 0,
            "research_only": True,
            "market_only": True,
            "account_agnostic": True,
        },
    }

    if args.write_files:
        write_jsonl(Path(output_paths["file_manifest_jsonl"]), [file_record_to_dict(r) for r in records])
        write_jsonl(Path(output_paths["rows_jsonl"]), row_records)
        write_json(Path(output_paths["summary_json"]), payload)

    if args.output == "json":
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str))
    else:
        print(render_table_summary(summary, output_paths, bool(args.write_files)))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
