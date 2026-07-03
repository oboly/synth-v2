"""
A+ raw evidence inventory (Phase 1 of the A+ / Breathline V1 alignment study).

Research-only, read-only. Recursively inspects data/aplus_raw/ (or an explicit
--root) and produces a hashed, schema-classified, timestamp-lane-tagged
inventory of candidate A+ source files. This is a survey tool: it does not
select an anchor, does not compute a Breathline state, does not join to
market data, and does not draw any conclusion. See
docs/research/aplus_breathline_alignment_contract_v1.md.

data/aplus_raw is external local research evidence. This script never writes,
renames, moves, or edits anything under the scanned root; it only reads.
Generated inventory artifacts are written under
data/research/aplus_breathline_alignment_v1/<run_id>/ and are not meant to be
committed to git.

Content identity is canonical by sha256: identical bytes discovered at
multiple paths are one canonical source with multiple alias_paths, never
multiple ledger populations. This never aborts an inventory run; only a
genuine internal inconsistency (the same hash producing different parsed
content) does.

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
VERSION = "0.2"

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

# Maximum consecutive trailing non-blank lines (footer prose, a second
# unsupported table, etc.) recorded as UNPARSED_NON_TABLE_LINE diagnostics
# after the table body has ended. Bounded to avoid pathological blow-up; the
# observed anomalies (a one-paragraph footer note) are 1-2 lines.
MAX_TRAILING_DIAGNOSTIC_LINES = 50
MAX_DIAGNOSTIC_LINE_TEXT_CHARS = 500

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

# Timestamp lanes (contract section 3.1 / 4.1). PRIMARY_TARGET_ALIGNMENT is
# the only lane this study actively analyzes; FUTURE_OBSERVATION_ASOF is
# detected structurally but not implemented in this PR; everything else is
# exploratory only and excluded from Phase 2 eligibility.
LANE_PRIMARY_TARGET_ALIGNMENT = "PRIMARY_TARGET_ALIGNMENT"
LANE_FUTURE_OBSERVATION_ASOF = "FUTURE_OBSERVATION_ASOF"
LANE_EXPLORATORY_ONLY = "EXPLORATORY_ONLY"

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

# Explicit, documented market-symbol alias registry. Never inferred from
# source text -- extend only with a specific, reviewed entry citing where the
# alias was observed. Resolution against this registry is the only path from
# a raw source token to a canonical_market_symbol.
MARKET_SYMBOL_ALIAS_REGISTRY: dict[str, str] = {
    # Observed in data/aplus_raw/2026-05-27_2149_june_reflection_subset_8_note.txt:
    # the TOKEN column literally reads "Canton (CC)" for the CC token.
    "CANTON (CC)": "CC",
}
CANONICAL_MARKET_SYMBOLS: frozenset[str] = frozenset(
    {
        "AAVE", "ADA", "ALGO", "BTC", "CC", "CRV", "DEEP", "DOT", "ETH", "FET",
        "FIL", "FLOKI", "HBAR", "HNT", "HOT", "HYPE", "ICP", "INJ", "IOST",
        "LDO", "LINK", "LTC", "MOG", "NEAR", "NOT", "ONDO", "PEPE", "POL",
        "QNT", "RED", "RENDER", "RLC", "SOL", "SUI", "TAO", "VET", "WAL",
        "WLD", "XLM", "XPL", "XRP",
    }
)

ASSET_RESOLUTION_RESOLVED = "RESOLVED"
ASSET_RESOLUTION_UNRESOLVED = "UNRESOLVED"

ROW_PARSE_STATUS_OK = "OK"
ROW_PARSE_STATUS_MALFORMED = "MALFORMED_TABLE_BODY"
ROW_PARSE_STATUS_UNPARSED_NON_TABLE = "UNPARSED_NON_TABLE_LINE"


class InventoryIntegrityError(RuntimeError):
    """Raised only for a genuine internal inconsistency, never for a benign
    duplicate. See check_content_group_consistency."""


@dataclass
class ExplicitTimestamp:
    field_name: str | None
    raw: str
    iso: str
    role: str | None


@dataclass
class ParsedRow:
    fields: dict[str, str]
    raw_source_token: str


@dataclass
class RowDiagnostic:
    line_index: int
    line_text: str
    row_parse_status: str


@dataclass
class ParsedContent:
    """Everything derivable from file bytes alone -- independent of which
    alias path the bytes were read from."""

    sha256: str
    file_size_bytes: int
    detected_table_type: str
    header_tokens: list[str] | None
    delimiter_style: str | None
    declared_metadata: dict[str, str]
    rows: list[ParsedRow]
    row_diagnostics: list[RowDiagnostic]
    explicit_timestamps: list[ExplicitTimestamp]
    status: str
    status_notes: list[str]


@dataclass
class CanonicalSourceRecord:
    canonical_source_hash: str
    canonical_source_path: str
    alias_paths: list[str]
    alias_count: int
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
    timestamp_lane: str
    assets: list[str]
    duplicate_assets_within_file: list[str]
    unparsed_row_count: int
    status: str
    status_notes: list[str] = field(default_factory=list)


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
) -> tuple[list[ParsedRow], list[RowDiagnostic]]:
    """Parse the contiguous table body immediately following the header.

    Table rows in this corpus are always contiguous: once at least one row
    has been parsed, the first blank line ends the table body. Anything
    after that boundary (a footer note, stray prose, a second unsupported
    table) is never a candidate asset row -- it is recorded only as an
    UNPARSED_NON_TABLE_LINE diagnostic, bounded by
    MAX_TRAILING_DIAGNOSTIC_LINES. A non-blank line inside the contiguous
    body that fails to match the expected column shape is recorded as
    MALFORMED_TABLE_BODY. Neither diagnostic ever becomes an asset row.
    """
    field_names = FIELD_NAMES_BY_TABLE_TYPE[header.table_type]
    rows: list[ParsedRow] = []
    diagnostics: list[RowDiagnostic] = []
    table_body_ended = False
    trailing_diagnostic_count = 0

    for offset, line in enumerate(lines[header.line_index + 1 :]):
        line_index = header.line_index + 1 + offset
        stripped = line.strip()
        if not stripped:
            if rows:
                table_body_ended = True
            continue

        if table_body_ended:
            if trailing_diagnostic_count < MAX_TRAILING_DIAGNOSTIC_LINES:
                diagnostics.append(
                    RowDiagnostic(
                        line_index=line_index,
                        line_text=stripped[:MAX_DIAGNOSTIC_LINE_TEXT_CHARS],
                        row_parse_status=ROW_PARSE_STATUS_UNPARSED_NON_TABLE,
                    )
                )
                trailing_diagnostic_count += 1
            continue

        raw_tokens, _ = tokenize_line(stripped)
        if is_markdown_separator_row(raw_tokens):
            continue

        parts = split_data_row(stripped, header.delimiter_style, header.table_type)
        if parts is None:
            diagnostics.append(
                RowDiagnostic(
                    line_index=line_index,
                    line_text=stripped[:MAX_DIAGNOSTIC_LINE_TEXT_CHARS],
                    row_parse_status=ROW_PARSE_STATUS_MALFORMED,
                )
            )
            continue

        row_fields = {name: value for name, value in zip(field_names, parts)}
        raw_source_token = row_fields["token"].upper()
        row_fields["token"] = raw_source_token
        rows.append(ParsedRow(fields=row_fields, raw_source_token=raw_source_token))

    return rows, diagnostics


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


def resolve_timestamp_lane(primary_role: str | None) -> str:
    if primary_role == TIMESTAMP_ROLE_PREDICTION_TARGET:
        return LANE_PRIMARY_TARGET_ALIGNMENT
    if primary_role == TIMESTAMP_ROLE_OBSERVATION:
        return LANE_FUTURE_OBSERVATION_ASOF
    return LANE_EXPLORATORY_ONLY


def resolve_market_symbol(raw_source_token: str) -> tuple[str | None, str]:
    """Resolve a raw source token against the explicit alias registry only.

    Never infers an alias from the source text. Returns
    (canonical_market_symbol_or_None, asset_resolution_status).
    """
    if raw_source_token in CANONICAL_MARKET_SYMBOLS:
        return raw_source_token, ASSET_RESOLUTION_RESOLVED
    alias_target = MARKET_SYMBOL_ALIAS_REGISTRY.get(raw_source_token)
    if alias_target is not None:
        return alias_target, ASSET_RESOLUTION_RESOLVED
    return None, ASSET_RESOLUTION_UNRESOLVED


def find_duplicate_assets(rows: list[ParsedRow]) -> list[str]:
    seen: dict[str, int] = {}
    for row in rows:
        seen[row.raw_source_token] = seen.get(row.raw_source_token, 0) + 1
    return sorted(token for token, count in seen.items() if count > 1)


def parse_content(path: Path) -> ParsedContent:
    stat = path.stat()
    digest = sha256_file(path)
    text = read_text_safe(path)

    header_tokens: list[str] | None = None
    delimiter_style: str | None = None
    table_type = TABLE_TYPE_UNSUPPORTED
    declared_metadata: dict[str, str] = {}
    rows: list[ParsedRow] = []
    row_diagnostics: list[RowDiagnostic] = []
    status = "OK"
    status_notes: list[str] = []
    explicit_timestamps: list[ExplicitTimestamp] = []

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
            rows, row_diagnostics = parse_table_rows(lines, header)
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
            malformed_count = sum(
                1 for d in row_diagnostics if d.row_parse_status == ROW_PARSE_STATUS_MALFORMED
            )
            trailing_count = sum(
                1 for d in row_diagnostics if d.row_parse_status == ROW_PARSE_STATUS_UNPARSED_NON_TABLE
            )
            if malformed_count:
                status_notes.append(f"malformed_table_body_count={malformed_count} (skipped, not fabricated)")
            if trailing_count:
                status_notes.append(
                    f"unparsed_non_table_line_count={trailing_count} (footer/trailing content, not fabricated as rows)"
                )

    return ParsedContent(
        sha256=digest,
        file_size_bytes=int(stat.st_size),
        detected_table_type=table_type,
        header_tokens=header_tokens,
        delimiter_style=delimiter_style,
        declared_metadata=declared_metadata,
        rows=rows,
        row_diagnostics=row_diagnostics,
        explicit_timestamps=explicit_timestamps,
        status=status,
        status_notes=status_notes,
    )


def content_identity_key(parsed: ParsedContent) -> tuple[Any, ...]:
    """Fields that must be identical for byte-identical content. Excludes
    anything derived from a path (e.g. filename-inferred timestamps)."""
    return (
        parsed.detected_table_type,
        tuple(parsed.header_tokens) if parsed.header_tokens else None,
        parsed.delimiter_style,
        tuple(sorted(parsed.declared_metadata.items())),
        tuple((r.raw_source_token, tuple(sorted(r.fields.items()))) for r in parsed.rows),
        tuple((ts.field_name, ts.iso, ts.role) for ts in parsed.explicit_timestamps),
        parsed.status,
    )


def check_content_group_consistency(digest: str, group: list[tuple[Path, ParsedContent]]) -> None:
    if len(group) < 2:
        return
    keys = {content_identity_key(parsed) for _, parsed in group}
    if len(keys) > 1:
        paths = sorted(str(path) for path, _ in group)
        raise InventoryIntegrityError(
            f"internal inconsistency: sha256 {digest[:16]}... produced non-identical parsed "
            f"content across paths (this should be impossible for byte-identical content): {paths}"
        )


def build_canonical_record(
    digest: str, alias_paths: list[str], parsed: ParsedContent
) -> CanonicalSourceRecord:
    canonical_source_path = alias_paths[0]
    filename_ts = infer_filename_timestamp(Path(canonical_source_path).name)

    provenance, primary_iso, primary_role, ts_notes = resolve_timestamp_provenance(
        parsed.explicit_timestamps, filename_ts
    )
    status = parsed.status
    status_notes = list(parsed.status_notes)
    if ts_notes:
        status = "AMBIGUOUS_TIMESTAMP" if status == "OK" else status
        status_notes.extend(ts_notes)

    timestamp_lane = resolve_timestamp_lane(primary_role)
    duplicate_assets = find_duplicate_assets(parsed.rows)
    unparsed_row_count = len(parsed.row_diagnostics)

    return CanonicalSourceRecord(
        canonical_source_hash=digest,
        canonical_source_path=canonical_source_path,
        alias_paths=alias_paths,
        alias_count=len(alias_paths),
        file_size_bytes=parsed.file_size_bytes,
        detected_table_type=parsed.detected_table_type,
        header_tokens=parsed.header_tokens,
        delimiter_style=parsed.delimiter_style,
        declared_metadata=parsed.declared_metadata,
        token_count=len(parsed.rows) if parsed.rows else (0 if status == "EMPTY_TABLE_BODY" else None),
        explicit_timestamps=[
            {"field_name": ts.field_name, "raw": ts.raw, "iso": ts.iso, "role": ts.role}
            for ts in parsed.explicit_timestamps
        ],
        filename_inferred_timestamp=filename_ts,
        timestamp_provenance=provenance,
        primary_timestamp_iso=primary_iso,
        primary_timestamp_role=primary_role,
        timestamp_lane=timestamp_lane,
        assets=sorted({row.raw_source_token for row in parsed.rows}),
        duplicate_assets_within_file=duplicate_assets,
        unparsed_row_count=unparsed_row_count,
        status=status,
        status_notes=status_notes,
    )


def build_row_records(record: CanonicalSourceRecord, parsed: ParsedContent) -> list[dict[str, Any]]:
    if record.detected_table_type == TABLE_TYPE_UNSUPPORTED or record.status == "UNREADABLE":
        return []
    row_records: list[dict[str, Any]] = []
    for index, row in enumerate(parsed.rows):
        canonical_symbol, resolution_status = resolve_market_symbol(row.raw_source_token)
        row_records.append(
            {
                "canonical_source_hash": record.canonical_source_hash,
                "canonical_source_path": record.canonical_source_path,
                "detected_table_type": record.detected_table_type,
                "row_index_in_file": index,
                "primary_timestamp_iso": record.primary_timestamp_iso,
                "timestamp_provenance": record.timestamp_provenance,
                "primary_timestamp_role": record.primary_timestamp_role,
                "timestamp_lane": record.timestamp_lane,
                "raw_source_token": row.raw_source_token,
                "canonical_market_symbol": canonical_symbol,
                "asset_resolution_status": resolution_status,
                "row_parse_status": ROW_PARSE_STATUS_OK,
                **row.fields,
            }
        )
    for diagnostic in parsed.row_diagnostics:
        row_records.append(
            {
                "canonical_source_hash": record.canonical_source_hash,
                "canonical_source_path": record.canonical_source_path,
                "detected_table_type": record.detected_table_type,
                "row_index_in_file": None,
                "primary_timestamp_iso": record.primary_timestamp_iso,
                "timestamp_provenance": record.timestamp_provenance,
                "primary_timestamp_role": record.primary_timestamp_role,
                "timestamp_lane": record.timestamp_lane,
                "raw_source_token": None,
                "canonical_market_symbol": None,
                "asset_resolution_status": None,
                "row_parse_status": diagnostic.row_parse_status,
                "line_index": diagnostic.line_index,
                "line_text": diagnostic.line_text,
            }
        )
    return row_records


def run_inventory(root: Path) -> tuple[list[CanonicalSourceRecord], list[dict[str, Any]]]:
    by_hash: dict[str, list[tuple[Path, ParsedContent]]] = {}
    for path in iter_files(root):
        parsed = parse_content(path)
        by_hash.setdefault(parsed.sha256, []).append((path, parsed))

    canonical_records: list[CanonicalSourceRecord] = []
    all_row_records: list[dict[str, Any]] = []

    for digest in sorted(by_hash):
        group = by_hash[digest]
        check_content_group_consistency(digest, group)
        alias_paths = sorted(str(path) for path, _ in group)
        _, representative_parsed = group[0]
        record = build_canonical_record(digest, alias_paths, representative_parsed)
        canonical_records.append(record)
        all_row_records.extend(build_row_records(record, representative_parsed))

    return canonical_records, all_row_records


def build_summary(records: list[CanonicalSourceRecord], row_records: list[dict[str, Any]], root: Path) -> dict[str, Any]:
    table_type_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    provenance_counts: dict[str, int] = {}
    role_counts: dict[str, int] = {}
    lane_counts: dict[str, int] = {}

    for record in records:
        table_type_counts[record.detected_table_type] = table_type_counts.get(record.detected_table_type, 0) + 1
        status_counts[record.status] = status_counts.get(record.status, 0) + 1
        provenance_counts[record.timestamp_provenance] = provenance_counts.get(record.timestamp_provenance, 0) + 1
        role_key = record.primary_timestamp_role or "NONE"
        role_counts[role_key] = role_counts.get(role_key, 0) + 1
        lane_counts[record.timestamp_lane] = lane_counts.get(record.timestamp_lane, 0) + 1

    valid_primary_target_alignment_events = [
        record.canonical_source_path
        for record in records
        if record.timestamp_lane == LANE_PRIMARY_TARGET_ALIGNMENT and record.status == "OK"
    ]

    resolution_counts: dict[str, int] = {}
    row_parse_status_counts: dict[str, int] = {}
    for row in row_records:
        row_parse_status_counts[row["row_parse_status"]] = row_parse_status_counts.get(row["row_parse_status"], 0) + 1
        resolution_status = row.get("asset_resolution_status")
        if resolution_status is not None:
            resolution_counts[resolution_status] = resolution_counts.get(resolution_status, 0) + 1

    alias_groups = [
        {"canonical_source_hash": r.canonical_source_hash, "alias_paths": r.alias_paths}
        for r in records
        if r.alias_count > 1
    ]

    return {
        "report": REPORT_NAME,
        "version": VERSION,
        "root": str(root),
        "total_canonical_sources": len(records),
        "total_discovered_paths": sum(r.alias_count for r in records),
        "alias_group_count": len(alias_groups),
        "alias_groups": alias_groups,
        "table_type_counts": dict(sorted(table_type_counts.items())),
        "status_counts": dict(sorted(status_counts.items())),
        "timestamp_provenance_counts": dict(sorted(provenance_counts.items())),
        "timestamp_role_counts": dict(sorted(role_counts.items())),
        "timestamp_lane_counts": dict(sorted(lane_counts.items())),
        "valid_primary_target_alignment_event_count": len(valid_primary_target_alignment_events),
        "valid_primary_target_alignment_sources": sorted(valid_primary_target_alignment_events),
        "row_parse_status_counts": dict(sorted(row_parse_status_counts.items())),
        "asset_resolution_counts": dict(sorted(resolution_counts.items())),
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


def canonical_record_to_dict(record: CanonicalSourceRecord) -> dict[str, Any]:
    return {
        "canonical_source_hash": record.canonical_source_hash,
        "canonical_source_path": record.canonical_source_path,
        "alias_paths": record.alias_paths,
        "alias_count": record.alias_count,
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
        "timestamp_lane": record.timestamp_lane,
        "assets": record.assets,
        "duplicate_assets_within_file": record.duplicate_assets_within_file,
        "unparsed_row_count": record.unparsed_row_count,
        "status": record.status,
        "status_notes": record.status_notes,
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
    lines.append(f"total_canonical_sources={summary['total_canonical_sources']}")
    lines.append(f"total_discovered_paths={summary['total_discovered_paths']}")
    lines.append(f"alias_group_count={summary['alias_group_count']}")
    for group in summary["alias_groups"]:
        lines.append(f"  {group['canonical_source_hash'][:12]}...: {len(group['alias_paths'])} paths")
        for p in group["alias_paths"]:
            lines.append(f"    - {p}")
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
    lines.append("--- timestamp_lane counts ---")
    for key, value in summary["timestamp_lane_counts"].items():
        lines.append(f"  {key}={value}")
    lines.append("")
    lines.append("--- row_parse_status counts ---")
    for key, value in summary["row_parse_status_counts"].items():
        lines.append(f"  {key}={value}")
    lines.append("")
    lines.append("--- asset_resolution counts ---")
    for key, value in summary["asset_resolution_counts"].items():
        lines.append(f"  {key}={value}")
    lines.append("")
    lines.append(
        f"valid_primary_target_alignment_event_count={summary['valid_primary_target_alignment_event_count']}"
    )
    for path in summary["valid_primary_target_alignment_sources"]:
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

    summary = build_summary(records, row_records, root)

    started_at = datetime.now(timezone.utc)
    run_id = f"aplus_inventory_{started_at.strftime('%Y%m%dT%H%M%SZ')}"
    out_dir = Path(args.out_dir) / run_id
    output_paths = {
        "canonical_source_manifest_jsonl": str(
            out_dir / "evidence" / f"aplus_evidence_canonical_source_manifest_{run_id}.jsonl"
        ),
        "rows_jsonl": str(out_dir / "evidence" / f"aplus_evidence_rows_{run_id}.jsonl"),
        "summary_json": str(out_dir / "manifest" / f"aplus_evidence_inventory_manifest_{run_id}.json"),
    }

    payload: dict[str, Any] = {
        **summary,
        "run_id": run_id,
        "generated_at_utc": started_at.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "output_paths": output_paths,
        "wrote_files": bool(args.write_files),
        "row_record_count": len(row_records),
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
        write_jsonl(
            Path(output_paths["canonical_source_manifest_jsonl"]),
            [canonical_record_to_dict(r) for r in records],
        )
        write_jsonl(Path(output_paths["rows_jsonl"]), row_records)
        write_json(Path(output_paths["summary_json"]), payload)

    if args.output == "json":
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str))
    else:
        print(render_table_summary(summary, output_paths, bool(args.write_files)))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
