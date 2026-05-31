from __future__ import annotations

import argparse
import csv
import json
import os
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.common.db import get_connection


REPORT_NAME = "canonical_fib_map_source_audit_v1"
REPORT_VERSION = "0.1"
DEFAULT_OUTPUT_DIR = Path("data/research/canonical_fib_map_source_audit_v1")
DEFAULT_FIB_MAP_ROWS = Path("data/research/fibo_target_map_v1/fibo_target_map_rows_v1.csv")
SEARCH_ROOTS = [
    Path("data/research"),
    Path("data/external"),
    Path("docs/research"),
    Path("src/research"),
    Path("src/reporting"),
]
SEARCH_TERMS = (
    "fib",
    "fibo",
    "fibonacci",
    "zone",
    "target",
    "tp",
    "entry",
    "support",
    "resistance",
    "invalidation",
    "leg",
    "direction",
    "swing",
    "reload",
    "rebuy",
    "reaction",
    "regime",
)
REQUIRED_CANONICAL_FIELDS = {
    "Entry Zone": ("entry_zone_low", "entry_zone_high"),
    "Target": (
        "local_reaction_price",
        "next_extension_target_price",
        "main_extension_target_price",
        "stretch_target_price",
        "bull_target_price",
        "moonbag_target_price",
        "fib_1272_price",
        "fib_1618_price",
        "fib_2618_price",
        "fib_3618_price",
        "fib_4236_price",
    ),
    "Invalidation Level": ("invalidation_price", "fib_invalidation_price", "fib_invalidation"),
    "Current Leg": ("leg_direction",),
    "Support / Reaction Zone": (
        "local_reaction_price",
        "next_fibo_support_price",
        "secondary_fibo_support_price",
    ),
    "Anchor / Swing context": (
        "anchor_start_ts",
        "anchor_end_ts",
        "swing_low_price",
        "swing_high_price",
    ),
    "Source timestamp": ("close_ts_utc", "anchor_end_ts", "anchor_start_ts"),
    "Regime Context": ("global_regime", "asset_class_regime", "global_class_regime", "asof_ts_utc"),
}


@dataclass(frozen=True)
class CandidateColumn:
    table_schema: str
    table_name: str
    column_name: str
    data_type: str
    candidate_role_guess: str
    confidence_guess: str
    reason: str


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only audit of existing fib/zone/target/invalidation source candidates."
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--write-files", action="store_true")
    parser.add_argument("--output", choices=("summary", "json"), default="summary")
    return parser.parse_args(argv)


def fmt_ts(value: Any) -> str:
    if not isinstance(value, datetime):
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    else:
        value = value.astimezone(UTC)
    return value.isoformat().replace("+00:00", "Z")


def fetch_all_dicts(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    try:
        cursor = conn.cursor(dictionary=True)
    except TypeError:
        cursor = conn.cursor()
    try:
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        if not rows:
            return []
        if isinstance(rows[0], dict):
            return [dict(row) for row in rows]
        columns = [str(desc[0]) for desc in cursor.description or []]
        return [dict(zip(columns, row)) for row in rows]
    finally:
        try:
            cursor.close()
        except Exception:
            pass


def try_query(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    try:
        return fetch_all_dicts(conn, sql, params)
    except Exception:
        return []


def quote_ident(value: str) -> str:
    return "`" + str(value).replace("`", "``") + "`"


def guess_role(column_name: str, table_name: str) -> tuple[str, str, str]:
    text = f"{table_name} {column_name}".lower()
    if "regime" in text:
        return ("REGIME_CONTEXT_SOURCE", "HIGH", "Contains regime naming and likely visible market context.")
    if "invalidation" in text:
        return ("INVALIDATION_SOURCE", "HIGH", "Column explicitly mentions invalidation.")
    if "entry_zone" in text or ("entry" in text and "zone" in text):
        return ("ENTRY_ZONE_SOURCE", "HIGH", "Column explicitly mentions entry zone.")
    if "target" in text or text.endswith(" tp") or "_tp" in text or "extension" in text:
        return ("TARGET_SOURCE", "HIGH", "Column explicitly mentions target/TP/extension context.")
    if "support" in text or "resistance" in text or "reaction" in text or "zone" in text:
        return ("SUPPORT_REACTION_SOURCE", "MEDIUM", "Column mentions support/resistance/reaction/zone context.")
    if "leg" in text or "direction" in text:
        return ("LEG_DIRECTION_SOURCE", "MEDIUM", "Column mentions leg or directional context.")
    if "swing" in text or "anchor" in text:
        return ("SWING_ANCHOR_SOURCE", "MEDIUM", "Column mentions swing or anchor context.")
    if "reload" in text or "rebuy" in text:
        return ("ENTRY_ZONE_SOURCE", "MEDIUM", "Column mentions reload/rebuy and may map to entry context.")
    return ("UNKNOWN", "LOW", "Keyword match is broad but candidate use is unclear.")


def discover_candidate_columns(conn: Any) -> list[CandidateColumn]:
    where = " OR ".join(["LOWER(column_name) LIKE %s" for _ in SEARCH_TERMS])
    params = tuple(f"%{term}%" for term in SEARCH_TERMS)
    rows = try_query(
        conn,
        f"""
        SELECT table_schema, table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = DATABASE()
          AND ({where})
        ORDER BY table_name, ordinal_position
        """,
        params,
    )
    out: list[CandidateColumn] = []
    for row in rows:
        role, confidence, reason = guess_role(str(row["column_name"]), str(row["table_name"]))
        out.append(
            CandidateColumn(
                table_schema=str(row["table_schema"]),
                table_name=str(row["table_name"]),
                column_name=str(row["column_name"]),
                data_type=str(row["data_type"]),
                candidate_role_guess=role,
                confidence_guess=confidence,
                reason=reason,
            )
        )
    return out


def table_columns_by_table(candidates: list[CandidateColumn]) -> dict[str, list[CandidateColumn]]:
    grouped: dict[str, list[CandidateColumn]] = defaultdict(list)
    for candidate in candidates:
        grouped[candidate.table_name].append(candidate)
    return dict(grouped)


def discover_all_table_columns(conn: Any) -> dict[str, list[str]]:
    rows = try_query(
        conn,
        """
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = DATABASE()
        ORDER BY table_name, ordinal_position
        """,
    )
    grouped: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        grouped[str(row["table_name"])].append(str(row["column_name"]))
    return dict(grouped)


def find_first(columns: list[str], names: tuple[str, ...]) -> str | None:
    lower_map = {column.lower(): column for column in columns}
    for name in names:
        if name.lower() in lower_map:
            return lower_map[name.lower()]
    return None


def find_like(columns: list[str], needles: tuple[str, ...]) -> str | None:
    for column in columns:
        lowered = column.lower()
        if any(needle in lowered for needle in needles):
            return column
    return None


def table_summary(conn: Any, table_name: str, columns: list[str], venue: str, interval: str) -> dict[str, Any]:
    q_table = quote_ident(table_name)
    row_count_rows = try_query(conn, f"SELECT COUNT(*) AS row_count FROM {q_table}")
    row_count = int(row_count_rows[0]["row_count"]) if row_count_rows else None

    symbol_col = find_first(columns, ("symbol", "asset_symbol", "base_symbol")) or find_like(columns, ("symbol",))
    asset_id_col = find_first(columns, ("asset_id",))
    asof_col = find_first(columns, ("asof_ts_utc", "asof_ts", "observed_ts_utc", "created_at_utc")) or find_like(
        columns, ("asof", "observed_ts", "created_at")
    )
    close_col = find_first(columns, ("close_ts_utc", "close_ts", "source_candle_ts_utc")) or find_like(
        columns, ("close_ts", "source_candle")
    )
    interval_col = find_first(columns, ("interval_code", "interval"))
    venue_col = find_first(columns, ("venue",))

    distinct_symbols = None
    if symbol_col:
        rows = try_query(
            conn,
            f"SELECT COUNT(DISTINCT {quote_ident(symbol_col)}) AS distinct_symbols FROM {q_table}",
        )
        distinct_symbols = int(rows[0]["distinct_symbols"]) if rows else None
    elif asset_id_col:
        rows = try_query(
            conn,
            f"SELECT COUNT(DISTINCT {quote_ident(asset_id_col)}) AS distinct_symbols FROM {q_table}",
        )
        distinct_symbols = int(rows[0]["distinct_symbols"]) if rows else None

    latest_asof = ""
    if asof_col:
        rows = try_query(conn, f"SELECT MAX({quote_ident(asof_col)}) AS latest_asof_ts_utc FROM {q_table}")
        latest_asof = fmt_ts(rows[0]["latest_asof_ts_utc"]) if rows else ""

    latest_close = ""
    if close_col:
        rows = try_query(conn, f"SELECT MAX({quote_ident(close_col)}) AS latest_close_ts_utc FROM {q_table}")
        latest_close = fmt_ts(rows[0]["latest_close_ts_utc"]) if rows else ""

    interval_coverage = ""
    if interval_col:
        rows = try_query(
            conn,
            f"SELECT GROUP_CONCAT(DISTINCT {quote_ident(interval_col)} ORDER BY {quote_ident(interval_col)} SEPARATOR ',') AS interval_coverage FROM {q_table}",
        )
        interval_coverage = str(rows[0]["interval_coverage"] or "") if rows else ""

    venue_coverage = ""
    if venue_col:
        rows = try_query(
            conn,
            f"SELECT GROUP_CONCAT(DISTINCT {quote_ident(venue_col)} ORDER BY {quote_ident(venue_col)} SEPARATOR ',') AS venue_coverage FROM {q_table}",
        )
        venue_coverage = str(rows[0]["venue_coverage"] or "") if rows else ""

    role_counter = Counter(candidate.candidate_role_guess for candidate in table_columns_by_table_candidates[table_name])
    top_role = role_counter.most_common(1)[0][0] if role_counter else "UNKNOWN"
    contamination_risk = table_name in {"paper_advice_observation", "execution_zone_context", "selection_state"}

    return {
        "table_name": table_name,
        "candidate_role_guess": top_role,
        "row_count": row_count,
        "distinct_symbols": distinct_symbols,
        "latest_asof_ts_utc": latest_asof,
        "latest_close_ts_utc": latest_close,
        "interval_coverage": interval_coverage,
        "venue_coverage": venue_coverage,
        "symbol_column": symbol_col or asset_id_col or "",
        "asof_column": asof_col or "",
        "close_ts_column": close_col or "",
        "interval_column": interval_col or "",
        "venue_column": venue_col or "",
        "freshness_status": "UNKNOWN" if not (latest_asof or latest_close) else "VISIBLE",
        "contamination_risk": "YES" if contamination_risk else "NO",
        "reason": (
            "Operational/advice table: visible for audit only, not canonical strategy map."
            if contamination_risk
            else "Candidate table discovered via schema keyword scan."
        ),
    }


def safe_first_line(path: Path) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return handle.readline().strip()[:400]
    except Exception:
        return ""


def guess_file_role(path: Path, first_line: str) -> tuple[str, str]:
    text = f"{path.name.lower()} {first_line.lower()}"
    if "active_regime_observation" in text or "global_regime" in text:
        return ("REGIME_CONTEXT_SOURCE", "Contains explicit regime context.")
    if "fibo_target_map" in text or "fib_" in text:
        return ("TARGET_SOURCE", "Contains explicit fib map naming.")
    if "invalidation" in text:
        return ("INVALIDATION_SOURCE", "Contains invalidation naming.")
    if "entry_zone" in text or ("entry" in text and "zone" in text):
        return ("ENTRY_ZONE_SOURCE", "Contains explicit entry-zone naming.")
    if "target" in text or "tp" in text:
        return ("TARGET_SOURCE", "Contains target/TP naming.")
    if "support" in text or "resistance" in text or "reaction" in text or "zone" in text:
        return ("SUPPORT_REACTION_SOURCE", "Contains support/reaction/zone naming.")
    if "leg" in text or "direction" in text or "swing" in text or "anchor" in text:
        return ("SWING_ANCHOR_SOURCE", "Contains leg/swing/anchor naming.")
    return ("UNKNOWN", "Name/header match is broad.")


def discover_files() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for root in SEARCH_ROOTS:
        if not root.exists():
            out.append(
                {
                    "path": str(root),
                    "file_type": "directory",
                    "size_bytes": 0,
                    "candidate_role_guess": "UNKNOWN",
                    "first_header_or_line": "",
                    "status": "MISSING",
                }
            )
            continue
        for dirpath, _, filenames in os.walk(root):
            for filename in filenames:
                lowered = filename.lower()
                if not any(term in lowered for term in SEARCH_TERMS):
                    continue
                path = Path(dirpath) / filename
                first_line = safe_first_line(path)
                role, _ = guess_file_role(path, first_line)
                try:
                    size = path.stat().st_size
                    status = "FOUND"
                except Exception:
                    size = 0
                    status = "UNREADABLE"
                out.append(
                    {
                        "path": str(path),
                        "file_type": path.suffix.lstrip(".") or "unknown",
                        "size_bytes": size,
                        "candidate_role_guess": role,
                        "first_header_or_line": first_line,
                        "status": status,
                    }
                )
    out.sort(key=lambda row: row["path"])
    return out


def audit_fib_map_csv(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "exists": "no",
            "row_count": 0,
            "distinct_symbols": 0,
            "columns": [],
            "required_fields_present": {},
            "required_fields_missing": {},
            "coverage_reason": "CSV file is missing.",
        }
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        columns = list(reader.fieldnames or [])
    symbols = sorted({str(row.get("symbol") or "").strip().upper() for row in rows if row.get("symbol")})
    present: dict[str, list[str]] = {}
    missing: dict[str, list[str]] = {}
    for label, fields in REQUIRED_CANONICAL_FIELDS.items():
        has = [field for field in fields if field in columns]
        miss = [field for field in fields if field not in columns]
        present[label] = has
        missing[label] = miss
    coverage_reason = (
        "CSV exists but symbol coverage is low relative to dashboard asset universe."
        if len(symbols) < 10
        else "CSV exists with partial but broader symbol coverage."
    )
    return {
        "exists": "yes",
        "row_count": len(rows),
        "distinct_symbols": len(symbols),
        "columns": columns,
        "required_fields_present": present,
        "required_fields_missing": missing,
        "coverage_reason": coverage_reason,
    }


def build_recommendations(
    *,
    table_summaries: list[dict[str, Any]],
    fib_csv_audit: dict[str, Any],
    candidate_tables: set[str],
) -> list[dict[str, Any]]:
    summary_by_table = {row["table_name"]: row for row in table_summaries}
    fib_has_rows = fib_csv_audit.get("row_count", 0) > 0
    fib_symbols = int(fib_csv_audit.get("distinct_symbols", 0) or 0)
    fib_present = fib_csv_audit.get("required_fields_present", {})
    recommendations: list[dict[str, Any]] = []

    def add(field_name: str, status: str, source: str, next_action: str, reason: str) -> None:
        recommendations.append(
            {
                "canonical_field": field_name,
                "source_status": status,
                "current_source": source,
                "next_action": next_action,
                "reason": reason,
            }
        )

    for field_name in ("Entry Zone", "Target", "Invalidation Level", "Current Leg", "Support / Reaction Zone", "Anchor / Swing context", "Source timestamp"):
        present_fields = fib_present.get(field_name, [])
        if fib_has_rows and present_fields and fib_symbols >= 10:
            add(
                field_name,
                "PARTIAL_SOURCE_EXISTS",
                "data/research/fibo_target_map_v1/fibo_target_map_rows_v1.csv",
                "promote existing research CSV to DB-backed canonical source",
                "Required columns exist in research CSV, but symbol coverage is still too low for dashboard-wide use.",
            )
        elif fib_has_rows and present_fields:
            add(
                field_name,
                "PARTIAL_SOURCE_EXISTS",
                "data/research/fibo_target_map_v1/fibo_target_map_rows_v1.csv",
                "build new canonical fib_zone_map_v1 table",
                "Research CSV has relevant fields but current dashboard coverage is sparse.",
            )
        elif "paper_advice_observation" in candidate_tables:
            add(
                field_name,
                "LEGACY_ONLY",
                "paper_advice_observation",
                "ignore legacy source",
                "Legacy paper/advice context mentions related fields but is blackbox advice and not canonical strategy-map source.",
            )
        else:
            add(
                field_name,
                "MISSING",
                "UNKNOWN",
                "build new canonical fib_zone_map_v1 table",
                "No acceptable canonical source with required provenance was discovered.",
            )

    if "active_regime_observation" in summary_by_table:
        add(
            "Regime Context",
            "VISIBLE_CONTEXT_ONLY",
            "active_regime_observation",
            "keep active_regime_observation as visible context only",
            "Canonical market context exists and is appropriate for display, but must not become hidden veto or execution permission.",
        )
    else:
        add(
            "Regime Context",
            "MISSING",
            "UNKNOWN",
            "needs validation before use",
            "No regime observation source was discovered in the current DB.",
        )
    return recommendations


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


def print_summary(summary: dict[str, Any]) -> None:
    print(f"report={REPORT_NAME}")
    print(f"version={REPORT_VERSION}")
    for key in (
        "candidate_tables",
        "candidate_columns",
        "candidate_files",
        "canonical_ready_fields",
        "partial_fields",
        "missing_fields",
        "contamination_risk_fields",
        "visible_context_only_fields",
    ):
        print(f"{key}={summary[key]}")
    print("db_writes=0")
    print("broker_private_calls=0")
    print("broker_writes=0")
    print("order_submission=0")
    print("decision_gate_changes=0")
    print("execution_planner_changes=0")
    print("executor=none")
    print("account_awareness=0")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = Path(args.output_dir)

    global table_columns_by_table_candidates
    conn = get_connection()
    try:
        candidate_columns = discover_candidate_columns(conn)
        table_columns_by_table_candidates = table_columns_by_table(candidate_columns)
        all_columns_by_table = discover_all_table_columns(conn)
        candidate_tables = sorted(table_columns_by_table_candidates)
        table_summaries = [
            table_summary(conn, table_name, all_columns_by_table.get(table_name, []), args.venue, args.interval)
            for table_name in candidate_tables
        ]
        active_regime_summary = next((row for row in table_summaries if row["table_name"] == "active_regime_observation"), None)
    finally:
        conn.close()

    file_candidates = discover_files()
    fib_csv_audit = audit_fib_map_csv(DEFAULT_FIB_MAP_ROWS)
    recommendations = build_recommendations(
        table_summaries=table_summaries,
        fib_csv_audit=fib_csv_audit,
        candidate_tables=set(candidate_tables),
    )

    if active_regime_summary:
        active_regime_summary["candidate_role_guess"] = "REGIME_CONTEXT_SOURCE"
        active_regime_summary["reason"] = "Allowed for visible dashboard context only, never hidden veto/final advice/execution permission."
        active_regime_summary["recommendation"] = "KEEP_AS_VISIBLE_CONTEXT_ONLY"

    recommendation_counts = Counter(row["source_status"] for row in recommendations)
    contamination_risk_fields = sum(1 for row in recommendations if row["source_status"] == "CONTAMINATION_RISK")
    summary = {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "candidate_tables": len(candidate_tables),
        "candidate_columns": len(candidate_columns),
        "candidate_files": len(file_candidates),
        "canonical_ready_fields": int(recommendation_counts.get("CANONICAL_READY", 0)),
        "partial_fields": int(recommendation_counts.get("PARTIAL_SOURCE_EXISTS", 0)),
        "missing_fields": int(recommendation_counts.get("MISSING", 0) + recommendation_counts.get("LEGACY_ONLY", 0)),
        "contamination_risk_fields": contamination_risk_fields,
        "visible_context_only_fields": int(recommendation_counts.get("VISIBLE_CONTEXT_ONLY", 0)),
        "fib_csv_audit": fib_csv_audit,
        "active_regime_observation": active_regime_summary or {
            "table_name": "active_regime_observation",
            "candidate_role_guess": "REGIME_CONTEXT_SOURCE",
            "reason": "Table not discovered.",
            "recommendation": "KEEP_AS_VISIBLE_CONTEXT_ONLY",
            "freshness_status": "UNKNOWN",
        },
    }

    if args.write_files:
        output_dir.mkdir(parents=True, exist_ok=True)
        write_csv(output_dir / "table_column_candidates.csv", [candidate.__dict__ for candidate in candidate_columns])
        write_csv(output_dir / "table_freshness_summary.csv", table_summaries)
        write_csv(output_dir / "file_candidates.csv", file_candidates)
        write_csv(output_dir / "canonical_field_recommendations.csv", recommendations)
        write_json(output_dir / "summary.json", summary)

    if args.output == "summary":
        print_summary(summary)
    else:
        print(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=True))
    return 0


table_columns_by_table_candidates: dict[str, list[CandidateColumn]] = {}


if __name__ == "__main__":
    raise SystemExit(main())
