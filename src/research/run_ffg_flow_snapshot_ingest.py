from __future__ import annotations

"""
FFG Flow Snapshot Ingest

Turns saved FFG Forecast HTML or plain text into:
  1. Preserved raw external research artifacts.
  2. Append-only structured flow snapshots per artifact and scope.
  3. Per-symbol flow observations.

Boundary:
  - Research-only. Market-only. No account rows, no orders, no broker calls.
  - FFG_LIST identity resolves only through exact source_symbol lookup against
    FFG_RESEARCH_UNIVERSE_V1.
  - OUTSIDE_FFG_RADAR remains external and unresolved by default.
  - Existing ffg_external_signal_snapshot_v1 remains unchanged.

Safety markers:
  broker_private_calls=0
  broker_writes=0
  order_submission=0
  live_orders=0
  decision_gate=none
  execution_planner=none
  executor=none

Usage:
  python -m src.research.run_ffg_flow_snapshot_ingest --artifact-file PATH --validate-only
  python -m src.research.run_ffg_flow_snapshot_ingest --artifact-file PATH --dry-run
  python -m src.research.run_ffg_flow_snapshot_ingest --artifact-file PATH --write-db
"""

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable

from src.common.db import get_connection

RUNNER_NAME = "run_ffg_flow_snapshot_ingest"
SOURCE_NAME = "FFG"
UNIVERSE_KEY = "FFG_RESEARCH_UNIVERSE_V1"
PARSER_VERSION = "ffg_flow_snapshot_ingest_v1"
ARTIFACT_KIND_HTML = "HTML"
ARTIFACT_KIND_TEXT = "TEXT"
LIST_SCOPE_FFG = "FFG_LIST"
LIST_SCOPE_OUTSIDE = "OUTSIDE_FFG_RADAR"
DIRECTION_INFLOW = "INFLOW"
DIRECTION_OUTFLOW = "OUTFLOW"
NORMALIZED_TIMEFRAME = "UNVERIFIED_BETA"
SOURCE_CONFIDENCE = "low"
SOURCE_STATUS = "BETA_UNVERIFIED"
PARSE_STATUS_OK = "PARSED_OK"
PARSE_STATUS_WARNINGS = "PARSED_WITH_WARNINGS"
EXIT_CODE_EXPECTED_FAILURE = 2
EXIT_CODE_UNEXPECTED_FAILURE = 1

INGEST_MIGRATION_PATH = "db/migrations/20260622_ffg_flow_snapshot_ingest.sql"
BASELINE_UNIVERSE_MIGRATION_PATH = "db/migrations/20260620_ffg_research_universe_v1.sql"
REQUIRED_INGEST_TABLES = (
    "external_research_artifact",
    "external_research_flow_snapshot",
    "external_research_flow_observation",
)
REQUIRED_SUPPORT_TABLES = ("ffg_research_universe_member_v1",)

SECTION_ALIASES = {
    "FFG LIST": LIST_SCOPE_FFG,
    "[FFG_LIST]": LIST_SCOPE_FFG,
    "OUTSIDE FFG RADAR": LIST_SCOPE_OUTSIDE,
    "[OUTSIDE_FFG_RADAR]": LIST_SCOPE_OUTSIDE,
}
FLOW_HEADER_RE = re.compile(r"^(Inflow|Outflow)\s*\((\d+)\)\s*$", re.IGNORECASE)
RANK_RE = re.compile(r"^(\d+)\.?\s*$")
SYMBOL_RE = re.compile(r"^[A-Z0-9._-]+$")


class FlowSnapshotIngestError(Exception):
    def __init__(
        self,
        reason: str,
        *,
        detail: str | None = None,
        missing_tables: Iterable[str] | None = None,
        migration: str | None = None,
    ) -> None:
        self.reason = reason
        self.detail = detail or ""
        self.missing_tables = tuple(missing_tables or ())
        self.migration = migration or INGEST_MIGRATION_PATH
        super().__init__(self.format_message())

    def format_message(self) -> str:
        parts = [f"reason={self.reason}"]
        if self.missing_tables:
            parts.append(f"missing_tables={','.join(self.missing_tables)}")
        if self.migration:
            parts.append(f"migration={self.migration}")
        if self.detail:
            parts.append(f"detail={self.detail}")
        return " ".join(parts)


@dataclass(frozen=True)
class ParsedObservation:
    list_scope: str
    direction: str
    source_symbol: str
    raw_display_name: str | None
    change_pct: Decimal | None
    reported_flow_usd: Decimal | None
    rank_in_section: int
    peak_flag: bool
    active_alert_flag: bool


@dataclass
class ParsedScope:
    list_scope: str
    reported_inflow_count: int | None = None
    reported_outflow_count: int | None = None
    observations: list[ParsedObservation] = field(default_factory=list)

    @property
    def parsed_inflow_count(self) -> int:
        return sum(1 for row in self.observations if row.direction == DIRECTION_INFLOW)

    @property
    def parsed_outflow_count(self) -> int:
        return sum(1 for row in self.observations if row.direction == DIRECTION_OUTFLOW)


@dataclass
class ParsedArtifact:
    artifact_kind: str
    raw_content: str
    content_sha256: str
    source_observed_label: str | None
    scopes: list[ParsedScope]
    warnings: list[dict[str, Any]]


@dataclass(frozen=True)
class ResolvedObservation:
    snapshot_scope: str
    source_symbol: str
    raw_display_name: str | None
    direction: str
    change_pct: Decimal | None
    reported_flow_usd: Decimal | None
    rank_in_section: int
    peak_flag: bool
    active_alert_flag: bool
    identity_status: str
    ffg_universe_member_id: int | None
    asset_id: int | None


@dataclass
class SnapshotPlan:
    list_scope: str
    universe_key: str | None
    reported_inflow_count: int | None
    parsed_inflow_count: int
    reported_outflow_count: int | None
    parsed_outflow_count: int
    observations: list[ResolvedObservation]


@dataclass
class IngestPlan:
    artifact_kind: str
    original_filename: str
    content_sha256: str
    raw_content: str
    source_observed_label: str | None
    source_observed_at_utc: str | None
    artifact_known: bool
    existing_artifact_id: int | None
    snapshot_plans: list[SnapshotPlan]
    warning_json: list[dict[str, Any]]
    parse_status: str

    @property
    def planned_snapshot_inserts(self) -> int:
        return 0 if self.artifact_known else len(self.snapshot_plans)

    @property
    def planned_observation_inserts(self) -> int:
        if self.artifact_known:
            return 0
        return sum(len(snapshot.observations) for snapshot in self.snapshot_plans)

    @property
    def unresolved_symbols(self) -> list[str]:
        symbols: list[str] = []
        for snapshot in self.snapshot_plans:
            for row in snapshot.observations:
                if row.identity_status != "FFG_UNIVERSE_RESOLVED":
                    symbols.append(f"{snapshot.list_scope}:{row.source_symbol}:{row.identity_status}")
        return symbols


class _BlockTextExtractor(HTMLParser):
    _BLOCK_TAGS = {
        "article",
        "aside",
        "br",
        "div",
        "h1",
        "h2",
        "h3",
        "h4",
        "header",
        "li",
        "p",
        "section",
        "table",
        "tbody",
        "td",
        "th",
        "tr",
        "ul",
    }

    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in self._BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if data:
            self._chunks.append(data)

    def get_text(self) -> str:
        return "".join(self._chunks)


def _detect_artifact_kind(path: Path, raw_content: str, override: str | None) -> str:
    if override:
        return override
    suffix = path.suffix.lower()
    if suffix in {".html", ".htm"}:
        return ARTIFACT_KIND_HTML
    if re.search(r"<(?:html|body|div|section|article|table|li)\b", raw_content, flags=re.IGNORECASE):
        return ARTIFACT_KIND_HTML
    return ARTIFACT_KIND_TEXT


def _read_artifact(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _sha256_text(raw_content: str) -> str:
    return hashlib.sha256(raw_content.encode("utf-8")).hexdigest()


def _normalize_text_for_parse(raw_content: str, artifact_kind: str) -> str:
    if artifact_kind == ARTIFACT_KIND_HTML:
        parser = _BlockTextExtractor()
        parser.feed(raw_content)
        return parser.get_text()
    return raw_content


def _normalize_lines(normalized_text: str) -> list[str]:
    lines: list[str] = []
    for raw_line in normalized_text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if line:
            lines.append(line)
    return lines


def _parse_decimal_pct(raw_value: str) -> Decimal | None:
    value = raw_value.strip()
    if not value:
        return None
    value = value.replace("%", "").replace("+", "")
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise FlowSnapshotIngestError("VALIDATION_FAILED", detail=f"Invalid change_pct: {raw_value}") from exc


def _parse_flow_usd(raw_value: str) -> Decimal | None:
    value = raw_value.strip()
    if not value:
        return None
    value = value.replace("$", "").replace(",", "").upper()
    multiplier = Decimal("1")
    if value.endswith("K"):
        multiplier = Decimal("1000")
        value = value[:-1]
    elif value.endswith("M"):
        multiplier = Decimal("1000000")
        value = value[:-1]
    elif value.endswith("B"):
        multiplier = Decimal("1000000000")
        value = value[:-1]
    try:
        return Decimal(value) * multiplier
    except InvalidOperation as exc:
        raise FlowSnapshotIngestError("VALIDATION_FAILED", detail=f"Invalid reported_flow_usd: {raw_value}") from exc


def _normalize_symbol(raw_symbol: str) -> str:
    symbol = raw_symbol.strip().upper()
    if not symbol or not SYMBOL_RE.match(symbol):
        raise FlowSnapshotIngestError("VALIDATION_FAILED", detail=f"Invalid source_symbol: {raw_symbol}")
    return symbol


def _parse_row(line: str, list_scope: str, direction: str) -> ParsedObservation | None:
    parts = [part.strip() for part in line.split("|")]
    if len(parts) < 5:
        return None
    rank_match = RANK_RE.match(parts[0])
    if not rank_match:
        return None
    rank_in_section = int(rank_match.group(1))
    source_symbol = _normalize_symbol(parts[1])
    raw_display_name = parts[2] or None
    change_pct = _parse_decimal_pct(parts[3])
    reported_flow_usd = _parse_flow_usd(parts[4])
    flags = {flag.strip().upper().replace(" ", "_") for flag in parts[5:] if flag.strip()}
    peak_flag = "PEAK" in flags or "PEAK_FLAG" in flags
    active_alert_flag = "ALERT" in flags or "ACTIVE_ALERT" in flags
    return ParsedObservation(
        list_scope=list_scope,
        direction=direction,
        source_symbol=source_symbol,
        raw_display_name=raw_display_name,
        change_pct=change_pct,
        reported_flow_usd=reported_flow_usd,
        rank_in_section=rank_in_section,
        peak_flag=peak_flag,
        active_alert_flag=active_alert_flag,
    )


def _section_key(line: str) -> str | None:
    normalized = line.strip().upper()
    return SECTION_ALIASES.get(normalized)


def parse_artifact(raw_content: str, artifact_kind: str) -> ParsedArtifact:
    normalized_text = _normalize_text_for_parse(raw_content, artifact_kind)
    lines = _normalize_lines(normalized_text)
    if not lines:
        raise FlowSnapshotIngestError("VALIDATION_FAILED", detail="Artifact is empty")

    observed_label: str | None = None
    scopes: dict[str, ParsedScope] = {}
    scope_order: list[str] = []
    scope_seen_symbols: dict[str, set[str]] = {}
    current_scope: str | None = None
    current_direction: str | None = None

    for line in lines:
        if line.upper().startswith("OBSERVED LABEL:"):
            observed_label = line.split(":", 1)[1].strip() or None
            continue

        section_key = _section_key(line)
        if section_key:
            current_scope = section_key
            current_direction = None
            if current_scope not in scopes:
                scopes[current_scope] = ParsedScope(list_scope=current_scope)
                scope_order.append(current_scope)
                scope_seen_symbols[current_scope] = set()
            continue

        header_match = FLOW_HEADER_RE.match(line)
        if header_match and current_scope is not None:
            label = header_match.group(1).upper()
            reported_count = int(header_match.group(2))
            current_direction = DIRECTION_INFLOW if label == "INFLOW" else DIRECTION_OUTFLOW
            scope = scopes[current_scope]
            if current_direction == DIRECTION_INFLOW:
                scope.reported_inflow_count = reported_count
            else:
                scope.reported_outflow_count = reported_count
            continue

        if current_scope is None or current_direction is None:
            continue

        row = _parse_row(line, current_scope, current_direction)
        if row is None:
            continue
        if row.source_symbol in scope_seen_symbols[current_scope]:
            raise FlowSnapshotIngestError(
                "DUPLICATE_SYMBOL",
                detail=f"Duplicate source_symbol within {current_scope}: {row.source_symbol}",
            )
        scope_seen_symbols[current_scope].add(row.source_symbol)
        scopes[current_scope].observations.append(row)

    ordered_scopes = [scopes[key] for key in scope_order if scopes[key].observations]
    if not ordered_scopes:
        raise FlowSnapshotIngestError("VALIDATION_FAILED", detail="No parseable flow rows found")

    warnings: list[dict[str, Any]] = []
    for scope in ordered_scopes:
        if scope.reported_inflow_count is not None and scope.reported_inflow_count != scope.parsed_inflow_count:
            warnings.append(
                {
                    "code": "REPORTED_COUNT_MISMATCH",
                    "list_scope": scope.list_scope,
                    "direction": DIRECTION_INFLOW,
                    "reported_count": scope.reported_inflow_count,
                    "parsed_count": scope.parsed_inflow_count,
                }
            )
        if scope.reported_outflow_count is not None and scope.reported_outflow_count != scope.parsed_outflow_count:
            warnings.append(
                {
                    "code": "REPORTED_COUNT_MISMATCH",
                    "list_scope": scope.list_scope,
                    "direction": DIRECTION_OUTFLOW,
                    "reported_count": scope.reported_outflow_count,
                    "parsed_count": scope.parsed_outflow_count,
                }
            )

    return ParsedArtifact(
        artifact_kind=artifact_kind,
        raw_content=raw_content,
        content_sha256=_sha256_text(raw_content),
        source_observed_label=observed_label,
        scopes=ordered_scopes,
        warnings=warnings,
    )


def _parse_source_observed_at(raw_value: str | None) -> str | None:
    if raw_value is None:
        return None
    normalized = raw_value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise FlowSnapshotIngestError("VALIDATION_FAILED", detail="Invalid --source-observed-at RFC3339") from exc
    if dt.tzinfo is None:
        raise FlowSnapshotIngestError("VALIDATION_FAILED", detail="--source-observed-at must include timezone")
    utc_dt = dt.astimezone(UTC)
    return utc_dt.strftime("%Y-%m-%d %H:%M:%S.%f")


def _required_table_map() -> dict[str, str]:
    table_to_migration = {table: INGEST_MIGRATION_PATH for table in REQUIRED_INGEST_TABLES}
    for table in REQUIRED_SUPPORT_TABLES:
        table_to_migration[table] = BASELINE_UNIVERSE_MIGRATION_PATH
    return table_to_migration


def assert_required_tables(conn) -> None:
    required_tables = tuple(_required_table_map().keys())
    placeholders = ", ".join(["%s"] * len(required_tables))
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = DATABASE()
              AND table_name IN ({placeholders})
            """,
            required_tables,
        )
        present = {str(row["table_name"]) for row in cur.fetchall()}

    missing_ingest = [table for table in REQUIRED_INGEST_TABLES if table not in present]
    if missing_ingest:
        raise FlowSnapshotIngestError(
            "MIGRATION_REQUIRED",
            missing_tables=missing_ingest,
            migration=INGEST_MIGRATION_PATH,
        )

    missing_support = [table for table in REQUIRED_SUPPORT_TABLES if table not in present]
    if missing_support:
        raise FlowSnapshotIngestError(
            "BASELINE_REQUIRED",
            missing_tables=missing_support,
            migration=BASELINE_UNIVERSE_MIGRATION_PATH,
        )


def fetch_existing_artifact(conn, content_sha256: str) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT artifact_id, source_name, content_sha256
            FROM external_research_artifact
            WHERE source_name = %s
              AND content_sha256 = %s
            """,
            (SOURCE_NAME, content_sha256),
        )
        return cur.fetchone()


def fetch_ffg_universe_members(conn, symbols: Iterable[str]) -> dict[str, dict[str, Any]]:
    normalized = sorted({_normalize_symbol(symbol) for symbol in symbols})
    if not normalized:
        return {}
    placeholders = ", ".join(["%s"] * len(normalized))
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT source_symbol, ffg_universe_member_id, asset_id
            FROM ffg_research_universe_member_v1
            WHERE universe_key = %s
              AND source_symbol IN ({placeholders})
            """,
            (UNIVERSE_KEY, *normalized),
        )
        rows = cur.fetchall()
    resolved: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = str(row["source_symbol"]).upper()
        if symbol in resolved:
            raise FlowSnapshotIngestError(
                "AMBIGUOUS_IDENTITY",
                detail=f"Multiple FFG universe rows found for {symbol}",
            )
        resolved[symbol] = row
    return resolved


def build_ingest_plan(
    conn,
    *,
    path: Path,
    parsed_artifact: ParsedArtifact,
    source_observed_at_utc: str | None,
    source_observed_label_override: str | None,
) -> IngestPlan:
    existing_artifact = fetch_existing_artifact(conn, parsed_artifact.content_sha256)
    ffg_symbols = [
        row.source_symbol
        for scope in parsed_artifact.scopes
        if scope.list_scope == LIST_SCOPE_FFG
        for row in scope.observations
    ]
    resolved_members = fetch_ffg_universe_members(conn, ffg_symbols)

    warnings = list(parsed_artifact.warnings)
    snapshot_plans: list[SnapshotPlan] = []

    for scope in parsed_artifact.scopes:
        resolved_rows: list[ResolvedObservation] = []
        for row in scope.observations:
            if scope.list_scope == LIST_SCOPE_FFG:
                member = resolved_members.get(row.source_symbol)
                if member is None:
                    warnings.append(
                        {
                            "code": "FFG_LIST_UNRESOLVED",
                            "list_scope": scope.list_scope,
                            "source_symbol": row.source_symbol,
                        }
                    )
                    identity_status = "UNRESOLVED"
                    member_id = None
                    asset_id = None
                else:
                    identity_status = "FFG_UNIVERSE_RESOLVED"
                    member_id = int(member["ffg_universe_member_id"])
                    asset_id = int(member["asset_id"]) if member["asset_id"] is not None else None
            else:
                warnings.append(
                    {
                        "code": "OUTSIDE_RADAR_UNRESOLVED",
                        "list_scope": scope.list_scope,
                        "source_symbol": row.source_symbol,
                    }
                )
                identity_status = "OUTSIDE_RADAR_UNRESOLVED"
                member_id = None
                asset_id = None

            resolved_rows.append(
                ResolvedObservation(
                    snapshot_scope=scope.list_scope,
                    source_symbol=row.source_symbol,
                    raw_display_name=row.raw_display_name,
                    direction=row.direction,
                    change_pct=row.change_pct,
                    reported_flow_usd=row.reported_flow_usd,
                    rank_in_section=row.rank_in_section,
                    peak_flag=row.peak_flag,
                    active_alert_flag=row.active_alert_flag,
                    identity_status=identity_status,
                    ffg_universe_member_id=member_id,
                    asset_id=asset_id,
                )
            )

        snapshot_plans.append(
            SnapshotPlan(
                list_scope=scope.list_scope,
                universe_key=UNIVERSE_KEY if scope.list_scope == LIST_SCOPE_FFG else None,
                reported_inflow_count=scope.reported_inflow_count,
                parsed_inflow_count=scope.parsed_inflow_count,
                reported_outflow_count=scope.reported_outflow_count,
                parsed_outflow_count=scope.parsed_outflow_count,
                observations=resolved_rows,
            )
        )

    parse_status = PARSE_STATUS_WARNINGS if warnings else PARSE_STATUS_OK
    source_observed_label = source_observed_label_override or parsed_artifact.source_observed_label

    return IngestPlan(
        artifact_kind=parsed_artifact.artifact_kind,
        original_filename=path.name,
        content_sha256=parsed_artifact.content_sha256,
        raw_content=parsed_artifact.raw_content,
        source_observed_label=source_observed_label,
        source_observed_at_utc=source_observed_at_utc,
        artifact_known=existing_artifact is not None,
        existing_artifact_id=None if existing_artifact is None else int(existing_artifact["artifact_id"]),
        snapshot_plans=snapshot_plans,
        warning_json=warnings,
        parse_status=parse_status,
    )


def insert_artifact(conn, plan: IngestPlan) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO external_research_artifact (
                source_name,
                artifact_kind,
                original_filename,
                content_sha256,
                raw_content,
                source_observed_label,
                source_observed_at_utc,
                parser_version,
                parse_status,
                parse_warning_json
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                SOURCE_NAME,
                plan.artifact_kind,
                plan.original_filename,
                plan.content_sha256,
                plan.raw_content,
                plan.source_observed_label,
                plan.source_observed_at_utc,
                PARSER_VERSION,
                plan.parse_status,
                None if not plan.warning_json else json.dumps(plan.warning_json),
            ),
        )
        return int(cur.lastrowid)


def insert_snapshot(conn, artifact_id: int, snapshot: SnapshotPlan) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO external_research_flow_snapshot (
                artifact_id,
                source_name,
                universe_key,
                list_scope,
                normalized_timeframe,
                source_confidence,
                source_status,
                reported_inflow_count,
                parsed_inflow_count,
                reported_outflow_count,
                parsed_outflow_count
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                artifact_id,
                SOURCE_NAME,
                snapshot.universe_key,
                snapshot.list_scope,
                NORMALIZED_TIMEFRAME,
                SOURCE_CONFIDENCE,
                SOURCE_STATUS,
                snapshot.reported_inflow_count,
                snapshot.parsed_inflow_count,
                snapshot.reported_outflow_count,
                snapshot.parsed_outflow_count,
            ),
        )
        return int(cur.lastrowid)


def insert_observation(conn, snapshot_id: int, observation: ResolvedObservation) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO external_research_flow_observation (
                snapshot_id,
                source_symbol,
                raw_display_name,
                direction,
                change_pct,
                reported_flow_usd,
                rank_in_section,
                peak_flag,
                active_alert_flag,
                identity_status,
                ffg_universe_member_id,
                asset_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                snapshot_id,
                observation.source_symbol,
                observation.raw_display_name,
                observation.direction,
                None if observation.change_pct is None else str(observation.change_pct),
                None if observation.reported_flow_usd is None else str(observation.reported_flow_usd),
                observation.rank_in_section,
                1 if observation.peak_flag else 0,
                1 if observation.active_alert_flag else 0,
                observation.identity_status,
                observation.ffg_universe_member_id,
                observation.asset_id,
            ),
        )


def apply_ingest_plan(conn, plan: IngestPlan) -> int | None:
    if plan.artifact_known:
        return plan.existing_artifact_id
    artifact_id = insert_artifact(conn, plan)
    for snapshot in plan.snapshot_plans:
        snapshot_id = insert_snapshot(conn, artifact_id, snapshot)
        for row in snapshot.observations:
            insert_observation(conn, snapshot_id, row)
    return artifact_id


def print_plan_summary(plan: IngestPlan, *, mode: str) -> None:
    print(f"  artifact_sha256: {plan.content_sha256}")
    print(f"  artifact_kind:   {plan.artifact_kind}")
    print(f"  artifact_state:  {'KNOWN' if plan.artifact_known else 'NEW'}")
    print(f"  parse_status:    {plan.parse_status}")
    print(f"  scopes_found:    {','.join(snapshot.list_scope for snapshot in plan.snapshot_plans)}")
    print(f"  planned_snapshots:    {plan.planned_snapshot_inserts}")
    print(f"  planned_observations: {plan.planned_observation_inserts}")
    if plan.source_observed_label:
        print(f"  source_observed_label: {plan.source_observed_label}")
    if plan.source_observed_at_utc:
        print(f"  source_observed_at_utc: {plan.source_observed_at_utc}")
    for snapshot in plan.snapshot_plans:
        print(
            "  snapshot "
            f"scope={snapshot.list_scope} "
            f"reported_inflow={snapshot.reported_inflow_count} parsed_inflow={snapshot.parsed_inflow_count} "
            f"reported_outflow={snapshot.reported_outflow_count} parsed_outflow={snapshot.parsed_outflow_count}"
        )
    if plan.unresolved_symbols:
        print(f"  unresolved_symbols: {','.join(plan.unresolved_symbols)}")
    if plan.warning_json:
        print(f"  warnings: {json.dumps(plan.warning_json, sort_keys=True)}")
    if mode == "dry-run" and plan.artifact_known:
        print("  dry_run_note: exact artifact already known; no new snapshots or observations planned")


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest append-only FFG flow snapshots from HTML or plain text.")
    parser.add_argument("--artifact-file", required=True, type=Path, help="Saved FFG HTML or plain text artifact")
    parser.add_argument("--artifact-kind", choices=[ARTIFACT_KIND_HTML, ARTIFACT_KIND_TEXT], help="Optional explicit artifact kind override")
    parser.add_argument("--source-observed-at", help="Optional RFC3339 timestamp from the source page")
    parser.add_argument("--source-observed-label", help="Optional source-side label to preserve as text")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--validate-only", action="store_true", help="Parse and validate only; never opens DB.")
    mode.add_argument("--dry-run", action="store_true", help="DB-backed plan only; no writes.")
    mode.add_argument("--write-db", action="store_true", help="Apply artifact, snapshot, and observation writes transactionally.")
    args = parser.parse_args()

    mode_label = "validate-only" if args.validate_only else "dry-run" if args.dry_run else "write-db"
    now_utc = datetime.now(UTC).isoformat()
    print(f"STARTED {RUNNER_NAME} at {now_utc}")
    print(f"  artifact_file: {args.artifact_file}")
    print(f"  mode:          {mode_label}")
    print("  broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0")

    conn = None
    try:
        raw_content = _read_artifact(args.artifact_file)
        artifact_kind = _detect_artifact_kind(args.artifact_file, raw_content, args.artifact_kind)
        parsed_artifact = parse_artifact(raw_content, artifact_kind)
        source_observed_at_utc = _parse_source_observed_at(args.source_observed_at)

        if args.validate_only:
            plan = IngestPlan(
                artifact_kind=parsed_artifact.artifact_kind,
                original_filename=args.artifact_file.name,
                content_sha256=parsed_artifact.content_sha256,
                raw_content=parsed_artifact.raw_content,
                source_observed_label=args.source_observed_label or parsed_artifact.source_observed_label,
                source_observed_at_utc=source_observed_at_utc,
                artifact_known=False,
                existing_artifact_id=None,
                snapshot_plans=[
                    SnapshotPlan(
                        list_scope=scope.list_scope,
                        universe_key=UNIVERSE_KEY if scope.list_scope == LIST_SCOPE_FFG else None,
                        reported_inflow_count=scope.reported_inflow_count,
                        parsed_inflow_count=scope.parsed_inflow_count,
                        reported_outflow_count=scope.reported_outflow_count,
                        parsed_outflow_count=scope.parsed_outflow_count,
                        observations=[],
                    )
                    for scope in parsed_artifact.scopes
                ],
                warning_json=list(parsed_artifact.warnings),
                parse_status=PARSE_STATUS_WARNINGS if parsed_artifact.warnings else PARSE_STATUS_OK,
            )
            print_plan_summary(plan, mode=mode_label)
            print("FINISHED run_ffg_flow_snapshot_ingest")
            return 0

        conn = get_connection()
        assert_required_tables(conn)
        plan = build_ingest_plan(
            conn,
            path=args.artifact_file,
            parsed_artifact=parsed_artifact,
            source_observed_at_utc=source_observed_at_utc,
            source_observed_label_override=args.source_observed_label,
        )
        print_plan_summary(plan, mode=mode_label)

        if args.write_db:
            artifact_id = apply_ingest_plan(conn, plan)
            conn.commit()
            print(f"  committed_artifact_id: {artifact_id}")
        else:
            print("  dry_run_note: no database writes executed")

    except FlowSnapshotIngestError as exc:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        print(f"FAILED {RUNNER_NAME} {exc}")
        return EXIT_CODE_EXPECTED_FAILURE
    except Exception as exc:
        if conn is not None and args.write_db:
            try:
                conn.rollback()
            except Exception:
                pass
        print(f"FAILED {RUNNER_NAME} reason=UNEXPECTED_ERROR detail={type(exc).__name__}")
        return EXIT_CODE_UNEXPECTED_FAILURE
    finally:
        if conn is not None:
            conn.close()

    print(f"FINISHED {RUNNER_NAME}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
