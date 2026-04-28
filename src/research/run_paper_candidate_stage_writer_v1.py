from __future__ import annotations

# Synth v2 - Paper Candidate Stage Writer V1.
#
# LAYER:
# research / paper-candidate staging
#
# BOUNDARY:
# Allowed:
# - read paper candidate contract JSONL
# - validate market-only transport payloads
# - write validated rows into a research staging table
# - keep deterministic candidate identity via candidate_key
#
# Forbidden:
# - account balances
# - live positions
# - open orders
# - execution plans
# - broker/order actions
# - decision_gate writes
# - execution_intent writes
# - execution_plan writes
# - order creation

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.common.db import get_connection
from src.research.paper_candidate_contract_v1 import (
    ResearchPaperCandidateV1,
    require_valid_candidate,
)


BT_DB = "synth_bt"
DEFAULT_TABLE = "research_paper_candidate_signal"
TABLE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")


@dataclass(frozen=True)
class LoadedCandidate:
    line_no: int
    candidate: ResearchPaperCandidateV1
    candidate_key: str


@dataclass(frozen=True)
class InvalidPayload:
    line_no: int
    error: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stage validated paper candidate contract JSONL into a research table."
    )
    parser.add_argument("--input", default="-", help="JSONL input path, or '-' for stdin.")
    parser.add_argument("--database", default=BT_DB)
    parser.add_argument("--table", default=DEFAULT_TABLE)
    parser.add_argument("--init-db", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--signal-status", default="VALIDATED")
    parser.add_argument("--batch-id", default=None)
    parser.add_argument("--max-error-samples", type=int, default=10)
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args()


def validate_table_name(table_name: str) -> str:
    if not TABLE_NAME_PATTERN.match(table_name):
        raise ValueError(f"Unsafe table name: {table_name}")
    return table_name


def parse_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if value is None:
        raise ValueError("timestamp is required")
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)


def parse_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def parse_int(value: Any) -> int:
    if value is None:
        raise ValueError("integer field is required")
    return int(value)


def payload_to_candidate(payload: dict[str, Any]) -> ResearchPaperCandidateV1:
    candidate = ResearchPaperCandidateV1(
        contract_version=str(payload["contract_version"]),
        policy_name=str(payload["policy_name"]),
        policy_version=str(payload["policy_version"]),
        candidate_state=str(payload["candidate_state"]),
        asset_id=parse_int(payload["asset_id"]),
        symbol=str(payload["symbol"]),
        venue=str(payload["venue"]),
        asof_ts_utc=parse_ts(payload["asof_ts_utc"]),
        selection_state=str(payload["selection_state"]),
        priority_rank=None if payload.get("priority_rank") is None else int(payload["priority_rank"]),
        selection_score=parse_decimal(payload.get("selection_score")),
        btc_prior_24h=parse_decimal(payload.get("btc_prior_24h")),
        rotation_bucket=None if payload.get("rotation_bucket") is None else str(payload["rotation_bucket"]),
        classification_code=None if payload.get("classification_code") is None else str(payload["classification_code"]),
        execution_regime_label=str(payload["execution_regime_label"]),
        sleeve_fit_code=None if payload.get("sleeve_fit_code") is None else str(payload["sleeve_fit_code"]),
        simulated_horizon_hours=parse_int(payload["simulated_horizon_hours"]),
        simulated_net_return=parse_decimal(payload.get("simulated_net_return")),
        source_table=str(payload["source_table"]),
        source_replay_id=parse_int(payload["source_replay_id"]),
        notes=None if payload.get("notes") is None else str(payload["notes"]),
    )
    require_valid_candidate(candidate)
    return candidate


def build_candidate_key(candidate: ResearchPaperCandidateV1) -> str:
    raw = "|".join(
        [
            candidate.contract_version,
            candidate.policy_name,
            candidate.policy_version,
            candidate.venue,
            candidate.source_table,
            str(candidate.source_replay_id),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def iter_json_lines(input_path: str):
    if input_path == "-":
        for line_no, line in enumerate(sys.stdin, start=1):
            yield line_no, line
        return
    with Path(input_path).open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            yield line_no, line


def load_candidates(input_path: str) -> tuple[list[LoadedCandidate], list[InvalidPayload]]:
    valid: list[LoadedCandidate] = []
    invalid: list[InvalidPayload] = []
    for line_no, line in iter_json_lines(input_path):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
            if not isinstance(payload, dict):
                raise TypeError("JSONL row must be an object")
            candidate = payload_to_candidate(payload)
            valid.append(
                LoadedCandidate(
                    line_no=line_no,
                    candidate=candidate,
                    candidate_key=build_candidate_key(candidate),
                )
            )
        except Exception as exc:
            invalid.append(InvalidPayload(line_no=line_no, error=str(exc)))
    return valid, invalid


def create_table_sql(table_name: str) -> str:
    safe_table = validate_table_name(table_name)
    return f"""
CREATE TABLE IF NOT EXISTS {safe_table} (
    candidate_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    candidate_key CHAR(64) NOT NULL,
    contract_version VARCHAR(64) NOT NULL,
    policy_name VARCHAR(96) NOT NULL,
    policy_version VARCHAR(96) NOT NULL,
    candidate_state VARCHAR(64) NOT NULL,
    signal_status VARCHAR(32) NOT NULL,
    asset_id BIGINT NOT NULL,
    symbol VARCHAR(32) NOT NULL,
    venue VARCHAR(32) NOT NULL,
    asof_ts_utc DATETIME(6) NOT NULL,
    selection_state VARCHAR(64) NOT NULL,
    priority_rank INT NULL,
    selection_score DECIMAL(20, 8) NULL,
    btc_prior_24h DECIMAL(24, 14) NULL,
    rotation_bucket VARCHAR(64) NULL,
    classification_code VARCHAR(64) NULL,
    execution_regime_label VARCHAR(32) NULL,
    sleeve_fit_code VARCHAR(64) NULL,
    simulated_horizon_hours INT NOT NULL,
    simulated_net_return DECIMAL(24, 14) NULL,
    source_table VARCHAR(128) NOT NULL,
    source_replay_id BIGINT NOT NULL,
    notes TEXT NULL,
    load_batch_id VARCHAR(64) NOT NULL,
    created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (candidate_id),
    UNIQUE KEY uq_research_paper_candidate_signal_key (candidate_key),
    KEY ix_research_paper_candidate_signal_status_ts (signal_status, asof_ts_utc),
    KEY ix_research_paper_candidate_signal_policy_ts (policy_name, policy_version, asof_ts_utc),
    KEY ix_research_paper_candidate_signal_symbol_ts (symbol, asof_ts_utc),
    KEY ix_research_paper_candidate_signal_source (source_table, source_replay_id)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci
  COMMENT='Research-only staging table for validated paper candidate contract rows.'
"""




def fetch_column_names(cur: Any, table_name: str) -> set[str]:
    safe_table = validate_table_name(table_name)
    cur.execute(f"SHOW COLUMNS FROM {safe_table}")
    rows = cur.fetchall() or []
    return {str(row["Field"]) for row in rows}


def ensure_table_schema(cur: Any, table_name: str) -> None:
    safe_table = validate_table_name(table_name)
    columns = fetch_column_names(cur, safe_table)
    if "execution_regime_label" not in columns:
        cur.execute(
            f"ALTER TABLE {safe_table} "
            "ADD COLUMN execution_regime_label VARCHAR(32) NULL AFTER classification_code"
        )

def init_db(*, database: str, table_name: str) -> None:
    conn = get_connection(database=database)
    try:
        with conn.cursor() as cur:
            cur.execute(create_table_sql(table_name))
            ensure_table_schema(cur, table_name)
        conn.commit()
    finally:
        conn.close()


def insert_sql(table_name: str) -> str:
    safe_table = validate_table_name(table_name)
    return f"""
INSERT INTO {safe_table} (
    candidate_key, contract_version, policy_name, policy_version, candidate_state,
    signal_status, asset_id, symbol, venue, asof_ts_utc, selection_state,
    priority_rank, selection_score, btc_prior_24h, rotation_bucket,
    classification_code, execution_regime_label, sleeve_fit_code, simulated_horizon_hours,
    simulated_net_return, source_table, source_replay_id, notes, load_batch_id
) VALUES (
    %(candidate_key)s, %(contract_version)s, %(policy_name)s, %(policy_version)s,
    %(candidate_state)s, %(signal_status)s, %(asset_id)s, %(symbol)s, %(venue)s,
    %(asof_ts_utc)s, %(selection_state)s, %(priority_rank)s, %(selection_score)s,
    %(btc_prior_24h)s, %(rotation_bucket)s, %(classification_code)s,
    %(execution_regime_label)s, %(sleeve_fit_code)s, %(simulated_horizon_hours)s, %(simulated_net_return)s,
    %(source_table)s, %(source_replay_id)s, %(notes)s, %(load_batch_id)s
)
ON DUPLICATE KEY UPDATE
    candidate_state = VALUES(candidate_state),
    signal_status = VALUES(signal_status),
    selection_state = VALUES(selection_state),
    priority_rank = VALUES(priority_rank),
    selection_score = VALUES(selection_score),
    btc_prior_24h = VALUES(btc_prior_24h),
    rotation_bucket = VALUES(rotation_bucket),
    classification_code = VALUES(classification_code),
    execution_regime_label = VALUES(execution_regime_label),
    sleeve_fit_code = VALUES(sleeve_fit_code),
    simulated_horizon_hours = VALUES(simulated_horizon_hours),
    simulated_net_return = VALUES(simulated_net_return),
    notes = VALUES(notes),
    load_batch_id = VALUES(load_batch_id),
    updated_ts_utc = UTC_TIMESTAMP(6)
"""


def candidate_to_db_params(loaded: LoadedCandidate, *, signal_status: str, batch_id: str) -> dict[str, Any]:
    c = loaded.candidate
    return {
        "candidate_key": loaded.candidate_key,
        "contract_version": c.contract_version,
        "policy_name": c.policy_name,
        "policy_version": c.policy_version,
        "candidate_state": c.candidate_state,
        "signal_status": signal_status,
        "asset_id": c.asset_id,
        "symbol": c.symbol,
        "venue": c.venue,
        "asof_ts_utc": c.asof_ts_utc,
        "selection_state": c.selection_state,
        "priority_rank": c.priority_rank,
        "selection_score": c.selection_score,
        "btc_prior_24h": c.btc_prior_24h,
        "rotation_bucket": c.rotation_bucket,
        "classification_code": c.classification_code,
        "execution_regime_label": c.execution_regime_label,
        "sleeve_fit_code": c.sleeve_fit_code,
        "simulated_horizon_hours": c.simulated_horizon_hours,
        "simulated_net_return": c.simulated_net_return,
        "source_table": c.source_table,
        "source_replay_id": c.source_replay_id,
        "notes": c.notes,
        "load_batch_id": batch_id,
    }


def write_candidates(*, database: str, table_name: str, candidates: list[LoadedCandidate], signal_status: str, batch_id: str) -> int:
    if not candidates:
        return 0
    params = [
        candidate_to_db_params(row, signal_status=signal_status, batch_id=batch_id)
        for row in candidates
    ]
    conn = get_connection(database=database)
    try:
        with conn.cursor() as cur:
            cur.executemany(insert_sql(table_name), params)
        conn.commit()
    finally:
        conn.close()
    return len(params)


def count_batch_rows(*, database: str, table_name: str, batch_id: str) -> int:
    safe_table = validate_table_name(table_name)
    conn = get_connection(database=database)
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS rows_total FROM {safe_table} WHERE load_batch_id = %s", (batch_id,))
            row = cur.fetchone()
    finally:
        conn.close()
    return int(row["rows_total"]) if isinstance(row, dict) else 0


def build_summary(*, args: argparse.Namespace, batch_id: str, valid: list[LoadedCandidate], invalid: list[InvalidPayload], rows_written: int, rows_in_batch: int) -> dict[str, Any]:
    symbols = sorted({row.candidate.symbol for row in valid})
    policies = sorted({row.candidate.policy_name for row in valid})
    return {
        "input": args.input,
        "database": args.database,
        "table": args.table,
        "batch_id": batch_id,
        "dry_run": args.dry_run,
        "signal_status": args.signal_status,
        "rows_read": len(valid) + len(invalid),
        "valid_rows": len(valid),
        "invalid_rows": len(invalid),
        "rows_written": rows_written,
        "rows_in_batch": rows_in_batch,
        "symbols": len(symbols),
        "policies": policies,
        "error_samples": [{"line": row.line_no, "error": row.error} for row in invalid[: args.max_error_samples]],
    }


def print_table(summary: dict[str, Any]) -> None:
    print("Paper candidate stage writer")
    for key in [
        "input", "database", "table", "batch_id", "dry_run", "signal_status",
        "rows_read", "valid_rows", "invalid_rows", "rows_written", "rows_in_batch",
        "symbols", "policies",
    ]:
        print(f"{key}: {summary[key]}")
    if summary["error_samples"]:
        print()
        print("error_samples:")
        for row in summary["error_samples"]:
            print(row)


def main() -> int:
    args = parse_args()
    validate_table_name(args.table)
    batch_id = args.batch_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    valid, invalid = load_candidates(args.input)

    if args.init_db:
        init_db(database=args.database, table_name=args.table)

    rows_written = 0
    rows_in_batch = 0

    if invalid:
        summary = build_summary(args=args, batch_id=batch_id, valid=valid, invalid=invalid, rows_written=0, rows_in_batch=0)
        if args.output == "json":
            print(json.dumps(summary, indent=2, sort_keys=True))
        else:
            print_table(summary)
        return 2

    if not args.dry_run:
        rows_written = write_candidates(
            database=args.database,
            table_name=args.table,
            candidates=valid,
            signal_status=args.signal_status,
            batch_id=batch_id,
        )
        rows_in_batch = count_batch_rows(database=args.database, table_name=args.table, batch_id=batch_id)

    summary = build_summary(args=args, batch_id=batch_id, valid=valid, invalid=invalid, rows_written=rows_written, rows_in_batch=rows_in_batch)
    if args.output == "json":
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print_table(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
