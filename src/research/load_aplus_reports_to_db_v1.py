from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from src.common.db import get_db_connection


REPORT_NAME = "load_aplus_reports_to_db_v1"
PARSER_VERSION = "1.0"

EXPECTED_TOKENS = [
    "BTC", "ETH", "SOL", "ADA", "DEEP", "FIL", "HBAR", "HOT", "NEAR", "PEPE",
    "POL", "QNT", "SUI", "VET", "WAL", "XLM", "AAVE", "CC", "CRV", "FLOKI",
    "HYPE", "LDO", "LTC", "ONDO", "RLC", "WLD", "XRP", "ALGO", "DOT", "FET",
    "HNT", "ICP", "INJ", "IOST", "MOG", "NOT", "RED", "RENDER", "XPL", "TAO",
    "LINK",
]
EXPECTED_TOKEN_SET = set(EXPECTED_TOKENS)

TABLE1_FIELDS = [
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
]
TABLE2_FIELDS = [
    "token",
    "harmonic_phase",
    "phase_state",
    "offset_band",
    "drift_direction",
    "quality",
    "extension_risk",
    "notes",
]


@dataclass(frozen=True)
class ParsedReport:
    report_type: str
    prediction_ts_utc: datetime
    source_file_path: str
    rows: list[dict[str, Any]]
    parser_version: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load A+ raw reports and parsed Table 1 / Table 2 rows into DB.")
    parser.add_argument("--raw-dir", default="data/aplus_raw")
    parser.add_argument(
        "--normalized-dir",
        action="append",
        default=[
            "data/research/aplus_table1_table2_normalized_v1",
            "data/research/aplus_table1_only_normalized_v1",
            "data/research/aplus_table2_harmonic_overlay_v1",
        ],
    )
    parser.add_argument("--write-db", action="store_true")
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args()


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def db_ts(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return ensure_utc(value).replace(tzinfo=None)


def iso_z(value: datetime | None) -> str | None:
    if value is None:
        return None
    return ensure_utc(value).isoformat().replace("+00:00", "Z")


def parse_ts(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    return ensure_utc(parsed)


def extract_ts_from_text(text: str) -> datetime | None:
    patterns = [
        r"prediction_ts_utc\s*=\s*([0-9T:\-]+Z)",
        r"Timestamp:\s*([0-9T:\-]+Z)",
        r"\(([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:]+Z)\)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return parse_ts(match.group(1))
    return None


def extract_ts_from_filename(path: Path) -> datetime | None:
    name = path.name
    match = re.search(r"(20[0-9]{2})-([0-9]{2})-([0-9]{2})[_-]([0-9]{2})([0-9]{2})", name)
    if match:
        year, month, day, hour, minute = match.groups()
        return datetime(int(year), int(month), int(day), int(hour), int(minute), tzinfo=UTC)
    match = re.search(r"(20[0-9]{6})T([0-9]{6})Z", name)
    if match:
        return datetime.strptime("".join(match.groups()), "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    return None


def content_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def classify_file(path: Path, text: str | None = None) -> str:
    name = path.name.lower()
    lower_text = (text or "").lower()
    if "table1" in name or "breathline_vector" in name or "canonical_breathline" in name:
        return "TABLE1_BREATHLINE_VECTOR"
    if "table2" in name or "harmonic_phase_overlay" in name or "harmonic_overlay" in name:
        return "TABLE2_HARMONIC_PHASE_OVERLAY"
    if "consistency" in name:
        return "CONSISTENCY_RUN"
    if "momentum stability alignment volatility pressure shift" in lower_text:
        return "CONSISTENCY_RUN"
    if "cluster_extension" in name:
        return "CLUSTER_EXTENSION"
    if "table 1" in lower_text and "breathline" in lower_text:
        return "TABLE1_BREATHLINE_VECTOR"
    if "table 2" in lower_text and "harmonic" in lower_text:
        return "TABLE2_HARMONIC_PHASE_OVERLAY"
    return "UNKNOWN_RAW"


def candidate_archive_files(raw_dir: Path, normalized_dirs: list[Path]) -> list[Path]:
    files: list[Path] = []
    if raw_dir.exists():
        files.extend(sorted(raw_dir.glob("*.txt")))
    for directory in normalized_dirs:
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.jsonl")):
            name = path.name
            if name.startswith("table1_normalized_") or name.startswith("table1_only_normalized_"):
                files.append(path)
            elif name.startswith("table2_normalized_") or name.startswith("aplus_table2_harmonic_overlay_"):
                files.append(path)
    return sorted(dict.fromkeys(files), key=lambda p: p.as_posix())


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def normalized_table1_report(path: Path) -> ParsedReport | None:
    rows = read_jsonl(path)
    if not rows:
        return None
    first = rows[0]
    ts_raw = first.get("prediction_ts_utc") or first.get("table1_prediction_ts_utc")
    if not ts_raw:
        return None
    source_path = first.get("source_table1_path") or path.as_posix()
    parsed_rows: list[dict[str, Any]] = []
    for row in rows:
        token = str(row.get("token", "")).strip().upper()
        if not token:
            continue
        parsed_rows.append(
            {
                "token": token,
                "phase": clean(row.get("table1_phase")),
                "coherence": clean(row.get("table1_coherence")),
                "field": clean(row.get("table1_field")),
                "geometry": clean(row.get("table1_geometry")),
                "structural_role": clean(row.get("table1_structural_role")),
                "expansion_quality": clean(row.get("table1_expansion_quality")),
                "anchor_strength": clean(row.get("table1_anchor_strength")),
                "strategic_bias": clean(row.get("table1_strategic_bias")),
                "notes": clean(row.get("table1_notes")),
                "validation_status": clean(row.get("validation_status")) or "VALID",
            }
        )
    return ParsedReport(
        report_type="TABLE1_BREATHLINE_VECTOR",
        prediction_ts_utc=parse_ts(str(ts_raw)),
        source_file_path=str(source_path),
        rows=parsed_rows,
        parser_version=str(first.get("parser_version") or PARSER_VERSION),
    )


def normalized_table2_report(path: Path) -> ParsedReport | None:
    rows = read_jsonl(path)
    if not rows:
        return None
    first = rows[0]
    ts_raw = first.get("prediction_ts_utc") or first.get("table2_prediction_ts_utc")
    if not ts_raw:
        return None
    source_path = first.get("source_table2_path") or first.get("source_path") or path.as_posix()
    parsed_rows: list[dict[str, Any]] = []
    for row in rows:
        token = str(row.get("token", "")).strip().upper()
        if not token:
            continue
        parsed_rows.append(
            {
                "token": token,
                "harmonic_phase": clean(row.get("table2_harmonic_phase") or row.get("harmonic_phase")),
                "phase_state": clean(row.get("table2_phase_state") or row.get("phase_state")),
                "offset_band": clean(row.get("table2_offset_band") or row.get("offset_band")),
                "drift_direction": clean(row.get("table2_drift_direction") or row.get("drift_direction")),
                "quality": clean(row.get("table2_quality") or row.get("quality")),
                "extension_risk": clean(row.get("table2_extension_risk") or row.get("extension_risk")),
                "notes": clean(row.get("table2_notes") or row.get("notes")),
                "validation_status": clean(row.get("validation_status")) or "VALID",
            }
        )
    return ParsedReport(
        report_type="TABLE2_HARMONIC_PHASE_OVERLAY",
        prediction_ts_utc=parse_ts(str(ts_raw)),
        source_file_path=str(source_path),
        rows=parsed_rows,
        parser_version=str(first.get("parser_version") or PARSER_VERSION),
    )


def clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if len(text) >= 2 and text[0] == text[-1] == '"':
        text = text[1:-1].strip()
    return text or None


def split_pipe_row(line: str) -> list[str] | None:
    if "|" not in line:
        return None
    parts = [part.strip() for part in line.strip().strip("|").split("|")]
    if len(parts) < 2:
        return None
    if all(part.replace("-", "").strip() == "" for part in parts):
        return None
    return parts


def parse_table1_raw(path: Path) -> ParsedReport | None:
    text = path.read_text(encoding="utf-8")
    ts = extract_ts_from_text(text) or extract_ts_from_filename(path)
    if ts is None:
        return None
    rows: list[dict[str, Any]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        pipe = split_pipe_row(line)
        if pipe:
            if pipe[0].upper() in {"TOKEN", "---"} or len(pipe) < 10:
                continue
            values = pipe[:9] + [" | ".join(pipe[9:])]
        else:
            parts = line.split()
            if not parts or parts[0].upper() not in EXPECTED_TOKEN_SET or len(parts) < 9:
                continue
            values = parts[:9] + [" ".join(parts[9:])]
        token = values[0].strip().upper()
        if token not in EXPECTED_TOKEN_SET:
            continue
        row = dict(zip(TABLE1_FIELDS, values, strict=True))
        row["validation_status"] = "VALID"
        rows.append(row)
    if not rows:
        return None
    return ParsedReport(
        report_type="TABLE1_BREATHLINE_VECTOR",
        prediction_ts_utc=ts,
        source_file_path=path.as_posix(),
        rows=rows,
        parser_version=PARSER_VERSION,
    )


def parse_table2_raw(path: Path) -> ParsedReport | None:
    text = path.read_text(encoding="utf-8")
    ts = extract_ts_from_text(text) or extract_ts_from_filename(path)
    if ts is None:
        return None
    rows: list[dict[str, Any]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        pipe = split_pipe_row(line)
        if pipe:
            if pipe[0].upper() in {"TOKEN", "---"} or len(pipe) < 8:
                continue
            values = pipe[:7] + [" | ".join(pipe[7:])]
        else:
            parts = line.split()
            if not parts or parts[0].upper() not in EXPECTED_TOKEN_SET or len(parts) < 7:
                continue
            values = parts[:7] + [" ".join(parts[7:])]
        token = values[0].strip().upper()
        if token not in EXPECTED_TOKEN_SET:
            continue
        row = dict(zip(TABLE2_FIELDS, values, strict=True))
        row["validation_status"] = "VALID"
        rows.append(row)
    if not rows:
        return None
    return ParsedReport(
        report_type="TABLE2_HARMONIC_PHASE_OVERLAY",
        prediction_ts_utc=ts,
        source_file_path=path.as_posix(),
        rows=rows,
        parser_version=PARSER_VERSION,
    )


def collect_reports(raw_dir: Path, normalized_dirs: list[Path]) -> tuple[list[ParsedReport], list[dict[str, Any]]]:
    reports_by_key: dict[tuple[str, datetime], ParsedReport] = {}
    skipped: list[dict[str, Any]] = []

    normalized_files: list[Path] = []
    for directory in normalized_dirs:
        if directory.exists():
            normalized_files.extend(sorted(directory.glob("*.jsonl")))

    for path in normalized_files:
        name = path.name
        report: ParsedReport | None = None
        if name.startswith("table1_normalized_") or name.startswith("table1_only_normalized_"):
            report = normalized_table1_report(path)
        elif name.startswith("table2_normalized_") or name.startswith("aplus_table2_harmonic_overlay_"):
            report = normalized_table2_report(path)
        if report is None:
            continue
        key = (report.report_type, report.prediction_ts_utc)
        current = reports_by_key.get(key)
        if current is None or len(report.rows) > len(current.rows):
            reports_by_key[key] = report

    if raw_dir.exists():
        for path in sorted(raw_dir.glob("*.txt")):
            text = path.read_text(encoding="utf-8")
            report_type = classify_file(path, text)
            report = None
            if report_type == "TABLE1_BREATHLINE_VECTOR":
                report = parse_table1_raw(path)
            elif report_type == "TABLE2_HARMONIC_PHASE_OVERLAY":
                report = parse_table2_raw(path)
            if report is None:
                skipped.append(
                    {
                        "source_file_path": path.as_posix(),
                        "report_type": report_type,
                        "parse_status": "PARSE_SKIPPED_MALFORMED" if report_type.startswith("TABLE") else "PARSE_SKIPPED_RAW_ONLY",
                    }
                )
                continue
            key = (report.report_type, report.prediction_ts_utc)
            if key not in reports_by_key:
                reports_by_key[key] = report

    return sorted(reports_by_key.values(), key=lambda r: (r.prediction_ts_utc, r.report_type)), skipped


def token_quality(rows: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    counts = Counter(str(row.get("token", "")).upper() for row in rows)
    missing = [token for token in EXPECTED_TOKENS if counts[token] == 0]
    duplicates = sorted(token for token, count in counts.items() if token and count > 1)
    return missing, duplicates


def archive_file(conn, path: Path, *, status: str, reason: str | None) -> int | None:
    text = path.read_text(encoding="utf-8")
    report_type = classify_file(path, text)
    ts = extract_ts_from_text(text) or extract_ts_from_filename(path)
    source = path.as_posix()
    sql = """
    INSERT INTO aplus_report_file_archive (
        source_file_path,
        content_hash_sha256,
        report_type,
        prediction_ts_utc,
        parse_status,
        parse_reason,
        byte_size
    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        content_hash_sha256 = VALUES(content_hash_sha256),
        report_type = VALUES(report_type),
        prediction_ts_utc = VALUES(prediction_ts_utc),
        parse_status = VALUES(parse_status),
        parse_reason = VALUES(parse_reason),
        byte_size = VALUES(byte_size)
    """
    with conn.cursor() as cur:
        cur.execute(sql, (source, content_hash(path), report_type, db_ts(ts), status, reason, path.stat().st_size))
        cur.execute(
            "SELECT aplus_report_file_id FROM aplus_report_file_archive WHERE source_file_path = %s",
            (source,),
        )
        row = cur.fetchone()
    return int(row["aplus_report_file_id"]) if row else None


def find_archive_id(conn, source_file_path: str) -> int | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT aplus_report_file_id FROM aplus_report_file_archive WHERE source_file_path = %s",
            (source_file_path,),
        )
        row = cur.fetchone()
    return int(row["aplus_report_file_id"]) if row else None


def upsert_table1(conn, report: ParsedReport) -> int:
    missing, duplicates = token_quality(report.rows)
    archive_id = find_archive_id(conn, report.source_file_path)
    sql = """
    INSERT INTO aplus_table1_report (
        aplus_report_file_id,
        source_file_path,
        prediction_ts_utc,
        parser_version,
        row_count,
        expected_token_count,
        missing_tokens_json,
        duplicate_tokens_json
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        aplus_report_file_id = VALUES(aplus_report_file_id),
        source_file_path = VALUES(source_file_path),
        parser_version = VALUES(parser_version),
        row_count = VALUES(row_count),
        expected_token_count = VALUES(expected_token_count),
        missing_tokens_json = VALUES(missing_tokens_json),
        duplicate_tokens_json = VALUES(duplicate_tokens_json)
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                archive_id,
                report.source_file_path,
                db_ts(report.prediction_ts_utc),
                report.parser_version,
                len(report.rows),
                len(EXPECTED_TOKENS),
                json.dumps(missing),
                json.dumps(duplicates),
            ),
        )
        cur.execute(
            "SELECT aplus_table1_report_id FROM aplus_table1_report WHERE prediction_ts_utc = %s",
            (db_ts(report.prediction_ts_utc),),
        )
        report_row = cur.fetchone()
        report_id = int(report_row["aplus_table1_report_id"])
        cur.execute("DELETE FROM aplus_table1_row WHERE aplus_table1_report_id = %s", (report_id,))
        cur.executemany(
            """
            INSERT INTO aplus_table1_row (
                aplus_table1_report_id,
                token,
                phase,
                coherence,
                field,
                geometry,
                structural_role,
                expansion_quality,
                anchor_strength,
                strategic_bias,
                notes,
                validation_status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                (
                    report_id,
                    row.get("token"),
                    row.get("phase"),
                    row.get("coherence"),
                    row.get("field"),
                    row.get("geometry"),
                    row.get("structural_role"),
                    row.get("expansion_quality"),
                    row.get("anchor_strength"),
                    row.get("strategic_bias"),
                    row.get("notes"),
                    row.get("validation_status") or "VALID",
                )
                for row in report.rows
            ],
        )
    return report_id


def upsert_table2(conn, report: ParsedReport) -> int:
    missing, duplicates = token_quality(report.rows)
    archive_id = find_archive_id(conn, report.source_file_path)
    sql = """
    INSERT INTO aplus_table2_report (
        aplus_report_file_id,
        source_file_path,
        prediction_ts_utc,
        parser_version,
        row_count,
        expected_token_count,
        missing_tokens_json,
        duplicate_tokens_json
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        aplus_report_file_id = VALUES(aplus_report_file_id),
        source_file_path = VALUES(source_file_path),
        parser_version = VALUES(parser_version),
        row_count = VALUES(row_count),
        expected_token_count = VALUES(expected_token_count),
        missing_tokens_json = VALUES(missing_tokens_json),
        duplicate_tokens_json = VALUES(duplicate_tokens_json)
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                archive_id,
                report.source_file_path,
                db_ts(report.prediction_ts_utc),
                report.parser_version,
                len(report.rows),
                len(EXPECTED_TOKENS),
                json.dumps(missing),
                json.dumps(duplicates),
            ),
        )
        cur.execute(
            "SELECT aplus_table2_report_id FROM aplus_table2_report WHERE prediction_ts_utc = %s",
            (db_ts(report.prediction_ts_utc),),
        )
        report_row = cur.fetchone()
        report_id = int(report_row["aplus_table2_report_id"])
        cur.execute("DELETE FROM aplus_table2_row WHERE aplus_table2_report_id = %s", (report_id,))
        cur.executemany(
            """
            INSERT INTO aplus_table2_row (
                aplus_table2_report_id,
                token,
                harmonic_phase,
                phase_state,
                offset_band,
                drift_direction,
                quality,
                extension_risk,
                notes,
                validation_status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                (
                    report_id,
                    row.get("token"),
                    row.get("harmonic_phase"),
                    row.get("phase_state"),
                    row.get("offset_band"),
                    row.get("drift_direction"),
                    row.get("quality"),
                    row.get("extension_risk"),
                    row.get("notes"),
                    row.get("validation_status") or "VALID",
                )
                for row in report.rows
            ],
        )
    return report_id


def update_pairing(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT aplus_table1_report_id, prediction_ts_utc FROM aplus_table1_report")
        table1 = [(int(r["aplus_table1_report_id"]), r["prediction_ts_utc"].replace(tzinfo=UTC)) for r in cur.fetchall()]
        cur.execute("SELECT aplus_table2_report_id, prediction_ts_utc FROM aplus_table2_report")
        table2 = [(int(r["aplus_table2_report_id"]), r["prediction_ts_utc"].replace(tzinfo=UTC)) for r in cur.fetchall()]

        for table1_id, ts1 in table1:
            best = min(table2, key=lambda item: abs(item[1] - ts1), default=None)
            if best is None:
                cur.execute(
                    """
                    UPDATE aplus_table1_report
                    SET paired_table2_report_id = NULL,
                        same_snapshot_ts = NULL,
                        timestamp_mismatch_minutes = NULL,
                        pair_reference_ts_utc = NULL
                    WHERE aplus_table1_report_id = %s
                    """,
                    (table1_id,),
                )
                continue
            table2_id, ts2 = best
            mismatch = abs((ts2 - ts1).total_seconds()) / 60
            same = mismatch <= 5
            cur.execute(
                """
                UPDATE aplus_table1_report
                SET paired_table2_report_id = %s,
                    same_snapshot_ts = %s,
                    timestamp_mismatch_minutes = %s,
                    pair_reference_ts_utc = %s
                WHERE aplus_table1_report_id = %s
                """,
                (table2_id if same else None, 1 if same else 0, mismatch, db_ts(max(ts1, ts2)), table1_id),
            )

        for table2_id, ts2 in table2:
            best = min(table1, key=lambda item: abs(item[1] - ts2), default=None)
            if best is None:
                cur.execute(
                    """
                    UPDATE aplus_table2_report
                    SET paired_table1_report_id = NULL,
                        same_snapshot_ts = NULL,
                        timestamp_mismatch_minutes = NULL,
                        pair_reference_ts_utc = NULL
                    WHERE aplus_table2_report_id = %s
                    """,
                    (table2_id,),
                )
                continue
            table1_id, ts1 = best
            mismatch = abs((ts2 - ts1).total_seconds()) / 60
            same = mismatch <= 5
            cur.execute(
                """
                UPDATE aplus_table2_report
                SET paired_table1_report_id = %s,
                    same_snapshot_ts = %s,
                    timestamp_mismatch_minutes = %s,
                    pair_reference_ts_utc = %s
                WHERE aplus_table2_report_id = %s
                """,
                (table1_id if same else None, 1 if same else 0, mismatch, db_ts(max(ts1, ts2)), table2_id),
            )


def fetch_db_summary(conn) -> dict[str, Any]:
    out: dict[str, Any] = {}
    with conn.cursor() as cur:
        for table in [
            "aplus_report_file_archive",
            "aplus_table1_report",
            "aplus_table1_row",
            "aplus_table2_report",
            "aplus_table2_row",
        ]:
            cur.execute(f"SELECT COUNT(*) AS n FROM {table}")
            out[f"{table}_count"] = int(cur.fetchone()["n"])
        cur.execute("SELECT MAX(prediction_ts_utc) AS max_ts FROM aplus_table1_report")
        out["table1_latest_ts"] = iso_z(cur.fetchone()["max_ts"])
        cur.execute("SELECT MAX(prediction_ts_utc) AS max_ts FROM aplus_table2_report")
        out["table2_latest_ts"] = iso_z(cur.fetchone()["max_ts"])
        cur.execute(
            """
            SELECT prediction_ts_utc, row_count, missing_tokens_json, duplicate_tokens_json
            FROM aplus_table1_report
            ORDER BY prediction_ts_utc
            """
        )
        out["table1_reports"] = [
            {
                "prediction_ts_utc": iso_z(r["prediction_ts_utc"]),
                "row_count": int(r["row_count"]),
                "missing_tokens": json.loads(r["missing_tokens_json"]),
                "duplicate_tokens": json.loads(r["duplicate_tokens_json"]),
            }
            for r in cur.fetchall()
        ]
        cur.execute(
            """
            SELECT prediction_ts_utc, row_count, missing_tokens_json, duplicate_tokens_json
            FROM aplus_table2_report
            ORDER BY prediction_ts_utc
            """
        )
        out["table2_reports"] = [
            {
                "prediction_ts_utc": iso_z(r["prediction_ts_utc"]),
                "row_count": int(r["row_count"]),
                "missing_tokens": json.loads(r["missing_tokens_json"]),
                "duplicate_tokens": json.loads(r["duplicate_tokens_json"]),
            }
            for r in cur.fetchall()
        ]
        for table_name, report_table, row_table, report_id_col in [
            ("table1", "aplus_table1_report", "aplus_table1_row", "aplus_table1_report_id"),
            ("table2", "aplus_table2_report", "aplus_table2_row", "aplus_table2_report_id"),
        ]:
            cur.execute(
                f"""
                SELECT r.prediction_ts_utc, row.token, row.*
                FROM {report_table} r
                JOIN {row_table} row
                  ON row.{report_id_col} = r.{report_id_col}
                WHERE row.token IN ('BTC', 'ETH', 'LINK')
                ORDER BY r.prediction_ts_utc, row.token
                """
            )
            out[f"{table_name}_sample_rows"] = [
                {k: (iso_z(v) if isinstance(v, datetime) else v) for k, v in row.items()}
                for row in cur.fetchall()
            ]
    return out


def render_table(payload: dict[str, Any]) -> str:
    lines = [
        f"files_scanned={payload['files_scanned']}",
        f"raw_files_archived={payload['raw_files_archived']}",
        f"table1_reports_parsed={payload['table1_reports_parsed']}",
        f"table2_reports_parsed={payload['table2_reports_parsed']}",
        f"malformed_or_raw_only_skipped_from_parsing={len(payload['parse_skipped'])}",
        f"write_db={payload['write_db']}",
        f"tables_written={', '.join(payload['tables_written']) if payload['write_db'] else 'none'}",
        f"table1_latest_ts={payload.get('db_summary', {}).get('table1_latest_ts')}",
        f"table2_latest_ts={payload.get('db_summary', {}).get('table2_latest_ts')}",
        "",
        "-- table1 reports --",
    ]
    for row in payload.get("db_summary", {}).get("table1_reports", payload["table1_reports"]):
        lines.append(f"{row['prediction_ts_utc']} rows={row['row_count']} missing={row['missing_tokens']} duplicates={row['duplicate_tokens']}")
    lines.append("-- table2 reports --")
    for row in payload.get("db_summary", {}).get("table2_reports", payload["table2_reports"]):
        lines.append(f"{row['prediction_ts_utc']} rows={row['row_count']} missing={row['missing_tokens']} duplicates={row['duplicate_tokens']}")
    lines.append("-- parse skipped --")
    for row in payload["parse_skipped"]:
        lines.append(f"{row['parse_status']} {row['report_type']} {row['source_file_path']}")
    return "\n".join(lines)


def main() -> int:
    load_dotenv()
    args = parse_args()
    raw_dir = Path(args.raw_dir)
    normalized_dirs = [Path(p) for p in args.normalized_dir]

    archive_files = candidate_archive_files(raw_dir, normalized_dirs)
    reports, skipped = collect_reports(raw_dir, normalized_dirs)

    table1_reports = [r for r in reports if r.report_type == "TABLE1_BREATHLINE_VECTOR"]
    table2_reports = [r for r in reports if r.report_type == "TABLE2_HARMONIC_PHASE_OVERLAY"]

    report_by_source = {r.source_file_path: r for r in reports}
    skipped_by_source = {row["source_file_path"]: row for row in skipped}

    db_summary: dict[str, Any] = {}
    if args.write_db:
        conn = get_db_connection()
        try:
            for path in archive_files:
                source = path.as_posix()
                report = report_by_source.get(source)
                if report is not None:
                    status = "PARSED"
                    reason = None
                elif source in skipped_by_source:
                    status = skipped_by_source[source]["parse_status"]
                    reason = skipped_by_source[source]["parse_status"]
                else:
                    status = "ARCHIVED_ONLY"
                    reason = "Normalized duplicate or non-primary report artifact."
                archive_file(conn, path, status=status, reason=reason)

            for report in table1_reports:
                upsert_table1(conn, report)
            for report in table2_reports:
                upsert_table2(conn, report)
            update_pairing(conn)
            conn.commit()
            db_summary = fetch_db_summary(conn)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    payload = {
        "report": REPORT_NAME,
        "version": PARSER_VERSION,
        "write_db": bool(args.write_db),
        "files_scanned": len(archive_files),
        "raw_files_archived": len(archive_files) if args.write_db else 0,
        "table1_reports_parsed": len(table1_reports),
        "table2_reports_parsed": len(table2_reports),
        "table1_reports": [
            {
                "prediction_ts_utc": iso_z(r.prediction_ts_utc),
                "row_count": len(r.rows),
                "missing_tokens": token_quality(r.rows)[0],
                "duplicate_tokens": token_quality(r.rows)[1],
                "source_file_path": r.source_file_path,
            }
            for r in table1_reports
        ],
        "table2_reports": [
            {
                "prediction_ts_utc": iso_z(r.prediction_ts_utc),
                "row_count": len(r.rows),
                "missing_tokens": token_quality(r.rows)[0],
                "duplicate_tokens": token_quality(r.rows)[1],
                "source_file_path": r.source_file_path,
            }
            for r in table2_reports
        ],
        "parse_skipped": skipped,
        "tables_written": [
            "aplus_report_file_archive",
            "aplus_table1_report",
            "aplus_table1_row",
            "aplus_table2_report",
            "aplus_table2_row",
        ],
        "db_summary": db_summary,
        "broker_calls": 0,
        "broker_writes": 0,
        "order_submission": 0,
        "selection_engine_changes": 0,
        "advice_engine_changes": 0,
        "decision_gate_changes": 0,
        "execution_planner_changes": 0,
        "executor_changes": 0,
    }

    if args.output == "json":
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    else:
        print(render_table(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
