from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from src.common.db import get_db_connection


POLICY_NAME = "trade_setup_filter_policy_preview_v1"
POLICY_VERSION = "0.1"
DEFAULT_VENUE = "bitvavo"
DEFAULT_TARGET_HORIZON = "24H"


ALLOW_24H = {
    "POL",
    "CRV",
    "PEPE",
    "BTC",
}

LONG_HORIZON_ONLY = {
    "INJ",
}

BLOCK_FOR_24H = {
    "MOG",
    "HYPE",
    "RENDER",
    "VET",
    "DOT",
    "HBAR",
    "ALGO",
    "SUI",
    "FIL",
    "HOT",
    "AAVE",
}

INSUFFICIENT_SAMPLE = {
    "LINK",
    "DEEP",
    "WAL",
    "ADA",
    "ONDO",
    "ICP",
    "TAO",
    "RLC",
    "FET",
}


@dataclass(frozen=True)
class SourcePassRow:
    source_id: int
    asset_id: int
    symbol: str
    venue: str
    asof_ts_utc: datetime
    context_ts_utc: datetime | None
    filter_name: str
    filter_version: str
    asset_suitability_mode: str | None
    selection_state: str
    priority_rank: int | None
    selection_score: Decimal | None
    btc_prior_24h: Decimal | None
    setup_filter_state: str
    setup_filter_reason: str | None
    target_horizon: str


@dataclass(frozen=True)
class PolicyPreviewRow:
    source: SourcePassRow
    policy_name: str
    policy_version: str
    policy_decision: str
    suggested_horizon: str
    allowed_now: bool
    policy_reason: str
    config_hash: str
    config_json: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only/write-db preview policy for trade setup filter PASS rows."
    )

    parser.add_argument(
        "--venue",
        default=DEFAULT_VENUE,
        help=f"Venue filter. Default: {DEFAULT_VENUE}",
    )

    parser.add_argument(
        "--target-horizon",
        default=DEFAULT_TARGET_HORIZON,
        help=f"Current runtime target horizon. Default: {DEFAULT_TARGET_HORIZON}",
    )

    parser.add_argument(
        "--output",
        choices=["table", "csv", "none"],
        default="table",
        help="Output format. Default: table.",
    )

    parser.add_argument(
        "--csv-path",
        default="/tmp/synth_trade_setup_filter_policy_preview_v1.csv",
        help="CSV output path.",
    )

    parser.add_argument(
        "--write-db",
        action="store_true",
        help="Write preview observations to trade_setup_policy_preview_observation.",
    )

    return parser.parse_args()


def decimal_to_str(value: Decimal | None) -> str:
    if value is None:
        return ""
    return str(value)


def normalize_horizon(value: str) -> str:
    return value.strip().upper()


def row_value(row: Any, key: str, index: int) -> Any:
    if isinstance(row, dict):
        return row[key]
    return row[index]


def policy_config_json() -> str:
    payload = {
        "policy_name": POLICY_NAME,
        "policy_version": POLICY_VERSION,
        "target_horizon": DEFAULT_TARGET_HORIZON,
        "allow_24h": sorted(ALLOW_24H),
        "long_horizon_only": sorted(LONG_HORIZON_ONLY),
        "block_for_24h": sorted(BLOCK_FOR_24H),
        "insufficient_sample": sorted(INSUFFICIENT_SAMPLE),
        "runtime_impact": "none",
        "decision_execution_impact": "none",
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def policy_config_hash(config_json: str) -> str:
    return hashlib.sha256(config_json.encode("utf-8")).hexdigest()


def latest_pass_asof_ts(
    conn,
    *,
    venue: str,
    target_horizon: str,
) -> datetime | None:
    sql = """
    SELECT MAX(asof_ts_utc) AS latest_ts
    FROM trade_setup_filter_observation
    WHERE venue = %s
      AND setup_filter_state = 'PASS'
      AND UPPER(TRIM(target_horizon)) = %s
    """

    with conn.cursor() as cur:
        cur.execute(sql, (venue, normalize_horizon(target_horizon)))
        row = cur.fetchone()

    if not row:
        return None

    latest_ts = row_value(row, "latest_ts", 0)
    if latest_ts is None:
        return None

    return latest_ts


def load_latest_pass_rows(
    conn,
    *,
    venue: str,
    target_horizon: str,
) -> list[SourcePassRow]:
    latest_ts = latest_pass_asof_ts(
        conn,
        venue=venue,
        target_horizon=target_horizon,
    )

    if latest_ts is None:
        return []

    sql = """
    SELECT
        trade_setup_filter_observation_id,
        asset_id,
        symbol,
        venue,
        asof_ts_utc,
        context_ts_utc,
        filter_name,
        filter_version,
        asset_suitability_mode,
        selection_state,
        priority_rank,
        selection_score,
        btc_prior_24h,
        setup_filter_state,
        setup_filter_reason,
        target_horizon
    FROM trade_setup_filter_observation
    WHERE venue = %s
      AND asof_ts_utc = %s
      AND setup_filter_state = 'PASS'
      AND UPPER(TRIM(target_horizon)) = %s
    ORDER BY
        priority_rank IS NULL,
        priority_rank,
        symbol
    """

    with conn.cursor() as cur:
        cur.execute(sql, (venue, latest_ts, normalize_horizon(target_horizon)))
        rows = cur.fetchall()

    result: list[SourcePassRow] = []

    for row in rows:
        result.append(
            SourcePassRow(
                source_id=int(row_value(row, "trade_setup_filter_observation_id", 0)),
                asset_id=int(row_value(row, "asset_id", 1)),
                symbol=str(row_value(row, "symbol", 2)).upper(),
                venue=str(row_value(row, "venue", 3)),
                asof_ts_utc=row_value(row, "asof_ts_utc", 4),
                context_ts_utc=row_value(row, "context_ts_utc", 5),
                filter_name=str(row_value(row, "filter_name", 6)),
                filter_version=str(row_value(row, "filter_version", 7)),
                asset_suitability_mode=(
                    None
                    if row_value(row, "asset_suitability_mode", 8) is None
                    else str(row_value(row, "asset_suitability_mode", 8))
                ),
                selection_state=str(row_value(row, "selection_state", 9)),
                priority_rank=(
                    None
                    if row_value(row, "priority_rank", 10) is None
                    else int(row_value(row, "priority_rank", 10))
                ),
                selection_score=row_value(row, "selection_score", 11),
                btc_prior_24h=row_value(row, "btc_prior_24h", 12),
                setup_filter_state=str(row_value(row, "setup_filter_state", 13)),
                setup_filter_reason=(
                    None
                    if row_value(row, "setup_filter_reason", 14) is None
                    else str(row_value(row, "setup_filter_reason", 14))
                ),
                target_horizon=normalize_horizon(str(row_value(row, "target_horizon", 15))),
            )
        )

    return result


def classify_policy(row: SourcePassRow) -> tuple[str, str, bool, str]:
    symbol = row.symbol

    if row.target_horizon == "24H" and symbol in ALLOW_24H:
        return (
            "ALLOW_24H",
            "24H",
            True,
            "symbol has positive 24H outcome profile for this setup family",
        )

    if symbol in LONG_HORIZON_ONLY:
        return (
            "LONG_HORIZON_ONLY",
            "72H_OR_168H",
            False,
            "symbol is negative at 24H but positive at longer horizons",
        )

    if row.target_horizon == "24H" and symbol in BLOCK_FOR_24H:
        return (
            "BLOCK_FOR_24H",
            "NONE",
            False,
            "symbol has poor 24H outcome profile for this setup family",
        )

    if symbol in INSUFFICIENT_SAMPLE:
        return (
            "INSUFFICIENT_SAMPLE",
            "NONE",
            False,
            "symbol has insufficient or mixed sample for 24H promotion",
        )

    return (
        "WATCH_ONLY",
        "NONE",
        False,
        "symbol is not yet classified for this policy version",
    )


def build_policy_rows(source_rows: list[SourcePassRow]) -> list[PolicyPreviewRow]:
    config_json = policy_config_json()
    config_hash = policy_config_hash(config_json)

    result: list[PolicyPreviewRow] = []

    for source_row in source_rows:
        decision, suggested_horizon, allowed_now, reason = classify_policy(source_row)
        result.append(
            PolicyPreviewRow(
                source=source_row,
                policy_name=POLICY_NAME,
                policy_version=POLICY_VERSION,
                policy_decision=decision,
                suggested_horizon=suggested_horizon,
                allowed_now=allowed_now,
                policy_reason=reason,
                config_hash=config_hash,
                config_json=config_json,
            )
        )

    return result


def render_table(rows: list[PolicyPreviewRow]) -> None:
    headers = [
        "symbol",
        "rank",
        "score",
        "setup",
        "current_horizon",
        "policy_decision",
        "suggested_horizon",
        "allowed_now",
    ]

    table_rows: list[list[str]] = []

    for row in rows:
        source = row.source
        table_rows.append(
            [
                source.symbol,
                "" if source.priority_rank is None else str(source.priority_rank),
                decimal_to_str(source.selection_score),
                source.setup_filter_state,
                source.target_horizon,
                row.policy_decision,
                row.suggested_horizon,
                "YES" if row.allowed_now else "NO",
            ]
        )

    widths = [
        max(len(headers[i]), *(len(table_row[i]) for table_row in table_rows))
        if table_rows
        else len(headers[i])
        for i in range(len(headers))
    ]

    print(" | ".join(headers[i].ljust(widths[i]) for i in range(len(headers))))
    print("-+-".join("-" * widths[i] for i in range(len(headers))))

    for table_row in table_rows:
        print(" | ".join(table_row[i].ljust(widths[i]) for i in range(len(headers))))


def write_csv(rows: list[PolicyPreviewRow], csv_path: str) -> None:
    path = Path(csv_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "symbol",
        "asset_id",
        "venue",
        "asof_ts_utc",
        "context_ts_utc",
        "selection_state",
        "priority_rank",
        "selection_score",
        "btc_prior_24h",
        "setup_filter_state",
        "setup_filter_reason",
        "current_target_horizon",
        "policy_decision",
        "suggested_horizon",
        "allowed_now",
        "policy_reason",
        "policy_name",
        "policy_version",
        "config_hash",
        "source_trade_setup_filter_observation_id",
    ]

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()

        for row in rows:
            source = row.source
            writer.writerow(
                {
                    "symbol": source.symbol,
                    "asset_id": source.asset_id,
                    "venue": source.venue,
                    "asof_ts_utc": source.asof_ts_utc,
                    "context_ts_utc": source.context_ts_utc,
                    "selection_state": source.selection_state,
                    "priority_rank": source.priority_rank,
                    "selection_score": decimal_to_str(source.selection_score),
                    "btc_prior_24h": decimal_to_str(source.btc_prior_24h),
                    "setup_filter_state": source.setup_filter_state,
                    "setup_filter_reason": source.setup_filter_reason,
                    "current_target_horizon": source.target_horizon,
                    "policy_decision": row.policy_decision,
                    "suggested_horizon": row.suggested_horizon,
                    "allowed_now": 1 if row.allowed_now else 0,
                    "policy_reason": row.policy_reason,
                    "policy_name": row.policy_name,
                    "policy_version": row.policy_version,
                    "config_hash": row.config_hash,
                    "source_trade_setup_filter_observation_id": source.source_id,
                }
            )

    print(f"[DONE] wrote csv={path} rows={len(rows)}")


def write_policy_rows(conn, rows: list[PolicyPreviewRow]) -> int:
    if not rows:
        return 0

    sql = """
    INSERT INTO trade_setup_policy_preview_observation (
        source_trade_setup_filter_observation_id,
        policy_name,
        policy_version,
        asset_id,
        symbol,
        venue,
        asof_ts_utc,
        context_ts_utc,
        source_filter_name,
        source_filter_version,
        asset_suitability_mode,
        selection_state,
        priority_rank,
        selection_score,
        btc_prior_24h,
        setup_filter_state,
        setup_filter_reason,
        current_target_horizon,
        policy_decision,
        suggested_horizon,
        allowed_now,
        policy_reason,
        config_hash,
        config_json
    ) VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
    )
    ON DUPLICATE KEY UPDATE
        asset_id = VALUES(asset_id),
        symbol = VALUES(symbol),
        venue = VALUES(venue),
        asof_ts_utc = VALUES(asof_ts_utc),
        context_ts_utc = VALUES(context_ts_utc),
        source_filter_name = VALUES(source_filter_name),
        source_filter_version = VALUES(source_filter_version),
        asset_suitability_mode = VALUES(asset_suitability_mode),
        selection_state = VALUES(selection_state),
        priority_rank = VALUES(priority_rank),
        selection_score = VALUES(selection_score),
        btc_prior_24h = VALUES(btc_prior_24h),
        setup_filter_state = VALUES(setup_filter_state),
        setup_filter_reason = VALUES(setup_filter_reason),
        current_target_horizon = VALUES(current_target_horizon),
        policy_decision = VALUES(policy_decision),
        suggested_horizon = VALUES(suggested_horizon),
        allowed_now = VALUES(allowed_now),
        policy_reason = VALUES(policy_reason),
        config_hash = VALUES(config_hash),
        config_json = VALUES(config_json),
        updated_ts_utc = UTC_TIMESTAMP(6)
    """

    data: list[tuple[Any, ...]] = []

    for row in rows:
        source = row.source
        data.append(
            (
                source.source_id,
                row.policy_name,
                row.policy_version,
                source.asset_id,
                source.symbol,
                source.venue,
                source.asof_ts_utc,
                source.context_ts_utc,
                source.filter_name,
                source.filter_version,
                source.asset_suitability_mode,
                source.selection_state,
                source.priority_rank,
                source.selection_score,
                source.btc_prior_24h,
                source.setup_filter_state,
                source.setup_filter_reason,
                source.target_horizon,
                row.policy_decision,
                row.suggested_horizon,
                1 if row.allowed_now else 0,
                row.policy_reason,
                row.config_hash,
                row.config_json,
            )
        )

    with conn.cursor() as cur:
        cur.executemany(sql, data)

    conn.commit()
    return len(rows)


def print_summary(rows: list[PolicyPreviewRow]) -> None:
    counts: dict[str, int] = {}
    allowed_symbols: list[str] = []
    blocked_symbols: list[str] = []

    for row in rows:
        counts[row.policy_decision] = counts.get(row.policy_decision, 0) + 1
        if row.allowed_now:
            allowed_symbols.append(row.source.symbol)
        else:
            blocked_symbols.append(row.source.symbol)

    print()
    print("--- policy summary ---")
    print(f"policy={POLICY_NAME} version={POLICY_VERSION}")
    print(f"latest_pass_rows={len(rows)}")

    for decision in sorted(counts):
        print(f"{decision}={counts[decision]}")

    print()
    print("--- runtime allowed now ---")
    print(",".join(allowed_symbols) if allowed_symbols else "NONE")

    print()
    print("--- not allowed for current 24H runtime ---")
    print(",".join(blocked_symbols) if blocked_symbols else "NONE")


def main() -> int:
    load_dotenv()

    args = parse_args()
    venue = str(args.venue)
    target_horizon = normalize_horizon(str(args.target_horizon))

    conn = get_db_connection()

    try:
        source_rows = load_latest_pass_rows(
            conn,
            venue=venue,
            target_horizon=target_horizon,
        )
        policy_rows = build_policy_rows(source_rows)

        if args.output == "table":
            render_table(policy_rows)

        if args.output in {"table", "csv"}:
            write_csv(policy_rows, args.csv_path)

        print_summary(policy_rows)

        if args.write_db:
            written = write_policy_rows(conn, policy_rows)
            print(f"[DONE] wrote trade_setup_policy_preview_observation rows={written}")

        print()
        print("[DONE] policy preview complete")
        return 0

    except Exception as exc:
        conn.rollback()
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
