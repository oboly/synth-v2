from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
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
class PreviewRow:
    symbol: str
    selection_state: str
    priority_rank: int | None
    selection_score: Decimal | None
    btc_prior_24h: Decimal | None
    setup_filter_state: str
    setup_filter_reason: str
    target_horizon: str
    policy_decision: str
    policy_reason: str
    suggested_target_horizon: str
    runtime_allowed_now: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only setup filter policy preview."
    )

    parser.add_argument(
        "--venue",
        default=DEFAULT_VENUE,
        help=f"Venue filter. Default: {DEFAULT_VENUE}",
    )

    parser.add_argument(
        "--target-horizon",
        default=DEFAULT_TARGET_HORIZON,
        help=f"Runtime target horizon. Default: {DEFAULT_TARGET_HORIZON}",
    )

    parser.add_argument(
        "--output",
        choices=["table", "csv"],
        default="table",
        help="Output format. Default: table.",
    )

    parser.add_argument(
        "--csv-path",
        default=None,
        help="Optional CSV output path.",
    )

    return parser.parse_args()


def classify_symbol(symbol: str, target_horizon: str) -> tuple[str, str, str, bool]:
    normalized_symbol = symbol.upper()
    normalized_horizon = target_horizon.upper()

    if normalized_horizon != "24H":
        return (
            "WATCH_ONLY",
            f"Policy v1 is calibrated for 24H, not {normalized_horizon}",
            normalized_horizon,
            False,
        )

    if normalized_symbol in ALLOW_24H:
        return (
            "ALLOW_24H",
            "Symbol has positive 24H outcome profile in setup-filter research.",
            "24H",
            True,
        )

    if normalized_symbol in LONG_HORIZON_ONLY:
        return (
            "LONG_HORIZON_ONLY",
            "Symbol is poor at 24H but positive at longer horizons; do not use as 24H candidate.",
            "72H_OR_168H",
            False,
        )

    if normalized_symbol in BLOCK_FOR_24H:
        return (
            "BLOCK_FOR_24H",
            "Symbol has negative 24H outcome profile for this setup family.",
            "NONE",
            False,
        )

    if normalized_symbol in INSUFFICIENT_SAMPLE:
        return (
            "INSUFFICIENT_SAMPLE",
            "Symbol lacks enough 24H evidence for policy promotion.",
            "NONE",
            False,
        )

    return (
        "WATCH_ONLY",
        "Symbol has no explicit policy bucket yet.",
        "NONE",
        False,
    )


def fetch_latest_pass_rows(conn, venue: str) -> list[dict[str, Any]]:
    latest_sql = """
    SELECT MAX(asof_ts_utc) AS latest_ts
    FROM trade_setup_filter_observation
    WHERE venue = %s
    """

    with conn.cursor() as cur:
        cur.execute(latest_sql, (venue,))
        latest_row = cur.fetchone()

    if not latest_row:
        return []

    latest_ts = latest_row["latest_ts"] if isinstance(latest_row, dict) else latest_row[0]

    if latest_ts is None:
        return []

    rows_sql = """
    SELECT
        symbol,
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
    ORDER BY priority_rank IS NULL, priority_rank, symbol
    """

    with conn.cursor() as cur:
        cur.execute(rows_sql, (venue, latest_ts))
        rows = cur.fetchall()

    if not rows:
        return []

    if isinstance(rows[0], dict):
        return list(rows)

    columns = [
        "symbol",
        "selection_state",
        "priority_rank",
        "selection_score",
        "btc_prior_24h",
        "setup_filter_state",
        "setup_filter_reason",
        "target_horizon",
    ]

    return [dict(zip(columns, row, strict=True)) for row in rows]


def build_preview_rows(
    source_rows: list[dict[str, Any]],
    *,
    target_horizon: str,
) -> list[PreviewRow]:
    preview_rows: list[PreviewRow] = []

    for row in source_rows:
        symbol = str(row["symbol"]).upper()
        policy_decision, policy_reason, suggested_horizon, runtime_allowed_now = classify_symbol(
            symbol=symbol,
            target_horizon=target_horizon,
        )

        preview_rows.append(
            PreviewRow(
                symbol=symbol,
                selection_state=str(row["selection_state"]),
                priority_rank=None if row["priority_rank"] is None else int(row["priority_rank"]),
                selection_score=row["selection_score"],
                btc_prior_24h=row["btc_prior_24h"],
                setup_filter_state=str(row["setup_filter_state"]),
                setup_filter_reason=str(row["setup_filter_reason"]),
                target_horizon=str(row["target_horizon"]),
                policy_decision=policy_decision,
                policy_reason=policy_reason,
                suggested_target_horizon=suggested_horizon,
                runtime_allowed_now=runtime_allowed_now,
            )
        )

    return preview_rows


def decimal_to_str(value: Decimal | None) -> str:
    if value is None:
        return ""
    return str(value)


def row_to_dict(row: PreviewRow) -> dict[str, Any]:
    return {
        "symbol": row.symbol,
        "selection_state": row.selection_state,
        "priority_rank": "" if row.priority_rank is None else row.priority_rank,
        "selection_score": decimal_to_str(row.selection_score),
        "btc_prior_24h": decimal_to_str(row.btc_prior_24h),
        "setup_filter_state": row.setup_filter_state,
        "setup_filter_reason": row.setup_filter_reason,
        "target_horizon": row.target_horizon,
        "policy_decision": row.policy_decision,
        "suggested_target_horizon": row.suggested_target_horizon,
        "runtime_allowed_now": int(row.runtime_allowed_now),
        "policy_reason": row.policy_reason,
    }


def print_table(rows: list[PreviewRow]) -> None:
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

    table_rows = [
        [
            row.symbol,
            "" if row.priority_rank is None else str(row.priority_rank),
            decimal_to_str(row.selection_score),
            row.setup_filter_state,
            row.target_horizon,
            row.policy_decision,
            row.suggested_target_horizon,
            "YES" if row.runtime_allowed_now else "NO",
        ]
        for row in rows
    ]

    widths = [
        max(len(str(value)) for value in [header] + [r[i] for r in table_rows])
        for i, header in enumerate(headers)
    ]

    print(" | ".join(header.ljust(widths[i]) for i, header in enumerate(headers)))
    print("-+-".join("-" * width for width in widths))

    for table_row in table_rows:
        print(" | ".join(str(value).ljust(widths[i]) for i, value in enumerate(table_row)))


def write_csv(rows: list[PreviewRow], csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    dict_rows = [row_to_dict(row) for row in rows]

    if not dict_rows:
        csv_path.write_text("", encoding="utf-8")
        return

    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(dict_rows[0].keys()))
        writer.writeheader()
        writer.writerows(dict_rows)


def print_summary(rows: list[PreviewRow]) -> None:
    counts: dict[str, int] = {}

    for row in rows:
        counts[row.policy_decision] = counts.get(row.policy_decision, 0) + 1

    print()
    print("--- policy summary ---")
    print(f"policy={POLICY_NAME} version={POLICY_VERSION}")
    print(f"latest_pass_rows={len(rows)}")

    for key in sorted(counts):
        print(f"{key}={counts[key]}")

    allowed = [row.symbol for row in rows if row.runtime_allowed_now]
    blocked = [row.symbol for row in rows if not row.runtime_allowed_now]

    print()
    print("--- runtime allowed now ---")
    print(",".join(allowed) if allowed else "NONE")

    print()
    print("--- not allowed for current 24H runtime ---")
    print(",".join(blocked) if blocked else "NONE")


def main() -> int:
    load_dotenv()

    args = parse_args()

    conn = get_db_connection()

    try:
        source_rows = fetch_latest_pass_rows(conn, venue=args.venue)
        preview_rows = build_preview_rows(
            source_rows,
            target_horizon=args.target_horizon,
        )

        if args.output == "table":
            print_table(preview_rows)
        else:
            for row in preview_rows:
                print(row_to_dict(row))

        print_summary(preview_rows)

        if args.csv_path:
            write_csv(preview_rows, Path(args.csv_path))
            print()
            print(f"[DONE] wrote csv={args.csv_path} rows={len(preview_rows)}")

        print()
        print("[DONE] read-only policy preview complete")
        return 0

    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
