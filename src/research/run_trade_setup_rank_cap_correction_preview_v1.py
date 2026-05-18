from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from src.common.db import get_db_connection


REPORT = "trade_setup_rank_cap_correction_preview_v1"
VERSION = "0.1"
DEFAULT_VENUE = "bitvavo"
DEFAULT_INTERVAL = "4h"
DEFAULT_LIMIT = 80

REQUIRED_SELECTION_STATE = "WATCHLIST"
CURRENT_RANK_MIN = 4
CURRENT_RANK_MAX = 10
CORRECTED_RANK_MIN = 1
CORRECTED_RANK_MAX = 10
BTC_PRIOR_MIN = Decimal("-0.015")
BTC_PRIOR_MAX = Decimal("0.015")
CANDIDATE_WEAK_SET = frozenset({"HNT", "SOL", "XLM", "LTC", "ETH", "XRP", "CC", "NOT"})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview rank-cap correction for trade_setup_filter without changing production behavior."
    )
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--interval", default=DEFAULT_INTERVAL)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--max-actionable", type=int, default=3)
    parser.add_argument("--output", choices=("table", "jsonl"), default="table")
    return parser.parse_args()


def parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    text = str(value).strip().replace("T", " ").removesuffix("Z")
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).replace(tzinfo=None)
    except ValueError:
        return None


def as_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        text = format(value, "f")
        return text.rstrip("0").rstrip(".") if "." in text else text
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    return str(value)


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return str(value)


def parse_reason_codes(raw: Any) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(str(raw))
    except json.JSONDecodeError:
        return [str(raw)]
    if isinstance(parsed, list):
        return [str(item) for item in parsed]
    if isinstance(parsed, dict):
        return [f"{key}={value}" for key, value in parsed.items()]
    return [str(parsed)]


def latest_asof(conn: Any, table: str, where_sql: str, params: dict[str, Any]) -> datetime | None:
    with conn.cursor() as cur:
        cur.execute(f"SELECT MAX(asof_ts_utc) AS latest_asof FROM {table} WHERE {where_sql}", params)
        row = cur.fetchone() or {}
    return parse_ts(row.get("latest_asof"))


def fetch_latest_paper_rows(
    conn: Any,
    *,
    venue: str,
    interval: str,
    limit: int,
) -> tuple[datetime | None, list[dict[str, Any]]]:
    asof = latest_asof(
        conn,
        "paper_advice_observation",
        "venue = %(venue)s AND interval_code = %(interval)s",
        {"venue": venue, "interval": interval},
    )
    if asof is None:
        return None, []

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                paper_advice_observation_id,
                asset_id,
                symbol,
                venue,
                interval_code,
                asof_ts_utc,
                selection_state,
                selection_score,
                priority_rank,
                setup_filter_state,
                setup_filter_reason,
                policy_decision,
                allowed_now,
                advice_state,
                advice_action,
                confidence_score,
                risk_label,
                reason_codes_json
            FROM paper_advice_observation
            WHERE venue = %(venue)s
              AND interval_code = %(interval)s
              AND asof_ts_utc = %(asof)s
            ORDER BY
                priority_rank IS NULL,
                priority_rank ASC,
                confidence_score DESC,
                symbol ASC
            LIMIT %(limit)s
            """,
            {"venue": venue, "interval": interval, "asof": asof, "limit": int(limit)},
        )
        return asof, list(cur.fetchall())


def fetch_latest_filter_by_asset(conn: Any, *, venue: str) -> tuple[datetime | None, dict[int, dict[str, Any]]]:
    asof = latest_asof(
        conn,
        "trade_setup_filter_observation",
        "venue = %(venue)s AND filter_name = 'trade_setup_filter_v1' AND filter_version = '1.1'",
        {"venue": venue},
    )
    if asof is None:
        return None, {}

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM trade_setup_filter_observation
            WHERE venue = %(venue)s
              AND asof_ts_utc = %(asof)s
              AND filter_name = 'trade_setup_filter_v1'
              AND filter_version = '1.1'
            """,
            {"venue": venue, "asof": asof},
        )
        rows = list(cur.fetchall())

    return asof, {int(row["asset_id"]): row for row in rows if row.get("asset_id") is not None}


def corrected_rank_eligible(rank: Any) -> bool:
    if rank is None:
        return False
    try:
        value = int(rank)
    except (TypeError, ValueError):
        return False
    return CORRECTED_RANK_MIN <= value <= CORRECTED_RANK_MAX


def preview_setup_state(row: dict[str, Any], filter_row: dict[str, Any] | None) -> tuple[str, str, list[str]]:
    symbol = str(row.get("symbol") or "").upper()
    selection_state = str(row.get("selection_state") or "").upper()
    rank = row.get("priority_rank")
    btc_prior = as_decimal((filter_row or {}).get("btc_prior_24h"))
    notes: list[str] = []

    if selection_state != REQUIRED_SELECTION_STATE:
        return "FAIL", "SELECTION_STATE_NOT_ELIGIBLE", notes

    if rank is None:
        return "FAIL", "PRIORITY_RANK_MISSING", notes

    if not corrected_rank_eligible(rank):
        return "FAIL", "RANK_OUTSIDE_1_10_PREVIEW", notes

    rank_int = int(rank)
    if rank_int < CURRENT_RANK_MIN:
        notes.append("TOP_RANK_PRIORITY")
        notes.append("CHASE_RISK_PREVIEW")

    if btc_prior is None:
        return "FAIL", "BTC_PRIOR_24H_MISSING", notes

    if btc_prior < BTC_PRIOR_MIN:
        return "FAIL", "MARKET_DAMAGE_RISK", notes

    if btc_prior > BTC_PRIOR_MAX:
        return "FAIL", "BTC_PRIOR_OVERHEAT_ZONE", notes

    if symbol in CANDIDATE_WEAK_SET:
        return "FAIL", "ASSET_SUITABILITY_WEAK_SET_CANDIDATE", notes

    return "PASS", "RANK_1_10_AND_MARKET_CONTEXT_OK", notes


def is_current_actionable(row: dict[str, Any]) -> bool:
    setup_state = str(row.get("setup_filter_state") or "").upper()
    policy = str(row.get("policy_decision") or "").upper()
    advice = str(row.get("advice_state") or "").upper()
    return setup_state == "PASS" and policy not in {"BLOCK_FOR_24H"} and advice in {"PAPER_READY", "WATCH", "WATCH_CORE", "BLOCK_24H"}


def apply_actionable_cap(rows: list[dict[str, Any]], max_actionable: int) -> None:
    eligible = [
        row for row in rows
        if row["corrected_setup_state_preview"] == "PASS"
    ]
    eligible.sort(
        key=lambda row: (
            row["rank"] is None,
            int(row["rank"]) if row["rank"] is not None else 999999,
            str(row["symbol"]),
        )
    )
    actionable_ids = {id(row) for row in eligible[: max(0, int(max_actionable))]}

    for row in rows:
        if row["corrected_setup_state_preview"] != "PASS":
            row["actionable_cap_state_preview"] = "NOT_SETUP_ELIGIBLE"
        elif id(row) in actionable_ids:
            row["actionable_cap_state_preview"] = "ACTIONABLE_WITHIN_CAP"
        else:
            row["actionable_cap_state_preview"] = "ELIGIBLE_OVER_CAP"


def build_preview_rows(
    paper_rows: list[dict[str, Any]],
    filter_by_asset: dict[int, dict[str, Any]],
    *,
    max_actionable: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for paper in paper_rows:
        asset_id = int(paper["asset_id"])
        filter_row = filter_by_asset.get(asset_id)
        corrected_state, corrected_reason, notes = preview_setup_state(paper, filter_row)
        current_reason = paper.get("setup_filter_reason") or (filter_row or {}).get("setup_filter_reason")
        current_state = paper.get("setup_filter_state") or (filter_row or {}).get("setup_filter_state")
        rank = paper.get("priority_rank")
        rescued = (
            str(current_state or "").upper() == "FAIL"
            and str(current_reason or "").upper() == "RANK_OUTSIDE_SWEET_SPOT"
            and corrected_state == "PASS"
        )

        rows.append(
            {
                "symbol": paper.get("symbol"),
                "rank": rank,
                "selection_state": paper.get("selection_state"),
                "current_behavior": current_state,
                "current_setup_filter_state": current_state,
                "current_fail_reason": current_reason,
                "rank_1_10_setup_eligible": corrected_rank_eligible(rank),
                "corrected_rank_eligible": corrected_rank_eligible(rank),
                "corrected_setup_state_preview": corrected_state,
                "corrected_setup_reason_preview": corrected_reason,
                "top_rank_priority_warning": "TOP_RANK_PRIORITY" if "TOP_RANK_PRIORITY" in notes else "",
                "actionable_cap_state_preview": "",
                "advice_state": paper.get("advice_state"),
                "policy_decision": paper.get("policy_decision"),
                "confidence_score": paper.get("confidence_score"),
                "reason_codes": parse_reason_codes(paper.get("reason_codes_json")),
                "notes": notes,
                "btc_prior_24h": (filter_row or {}).get("btc_prior_24h"),
                "current_actionable_preview": is_current_actionable(paper),
                "newly_rescued_from_rank_sweet_spot": rescued,
            }
        )

    apply_actionable_cap(rows, max_actionable=max_actionable)
    return rows


def count_state(rows: list[dict[str, Any]], key: str, value: str) -> int:
    return sum(1 for row in rows if str(row.get(key) or "").upper() == value)


def summary(rows: list[dict[str, Any]], *, latest_paper_asof: datetime | None, latest_filter_asof: datetime | None, max_actionable: int) -> dict[str, Any]:
    current_pass = count_state(rows, "current_setup_filter_state", "PASS")
    current_fail = count_state(rows, "current_setup_filter_state", "FAIL")
    corrected_pass = count_state(rows, "corrected_setup_state_preview", "PASS")
    corrected_fail = count_state(rows, "corrected_setup_state_preview", "FAIL")
    current_actionable = sum(1 for row in rows if row.get("current_actionable_preview"))
    capped_actionable = sum(1 for row in rows if row.get("actionable_cap_state_preview") == "ACTIONABLE_WITHIN_CAP")
    rescued = [str(row["symbol"]) for row in rows if row.get("newly_rescued_from_rank_sweet_spot")]
    non_rank_fail = [
        str(row["symbol"])
        for row in rows
        if row.get("corrected_setup_state_preview") == "FAIL"
        and row.get("corrected_setup_reason_preview") != "RANK_OUTSIDE_1_10_PREVIEW"
    ]

    return {
        "report": REPORT,
        "version": VERSION,
        "scope": "read-only preview",
        "latest_paper_advice_asof_ts_utc": latest_paper_asof,
        "latest_trade_setup_filter_asof_ts_utc": latest_filter_asof,
        "row_count": len(rows),
        "max_actionable": int(max_actionable),
        "current_setup_pass_count": current_pass,
        "current_setup_fail_count": current_fail,
        "corrected_setup_pass_count": corrected_pass,
        "corrected_setup_fail_count": corrected_fail,
        "current_actionable_count": current_actionable,
        "capped_actionable_count": capped_actionable,
        "symbols_newly_rescued_from_rank_outside_sweet_spot": rescued,
        "symbols_still_failing_for_non_rank_reasons": non_rank_fail,
        "current_fail_reason_counts": dict(Counter(str(row.get("current_fail_reason") or "") for row in rows)),
        "corrected_fail_reason_counts": dict(Counter(str(row.get("corrected_setup_reason_preview") or "") for row in rows if row.get("corrected_setup_state_preview") == "FAIL")),
        "safety": {
            "broker_private_calls": 0,
            "broker_writes": 0,
            "order_submission": 0,
            "live_orders": 0,
            "decision_gate_changes": 0,
            "execution_planner_changes": 0,
            "executor_changes": 0,
            "setup_filter_behavior_changes": 0,
            "db_writes": 0,
        },
    }


def print_table(rows: list[dict[str, Any]], summary_payload: dict[str, Any]) -> None:
    print(f"report={REPORT} version={VERSION}")
    print("scope=read-only rank-cap correction preview")
    print("broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0")
    print("setup_filter_behavior_changes=0 policy_changes=0 decision_gate_changes=0 execution_planner_changes=0 executor_changes=0 db_writes=0")
    for key in (
        "latest_paper_advice_asof_ts_utc",
        "latest_trade_setup_filter_asof_ts_utc",
        "row_count",
        "max_actionable",
        "current_setup_pass_count",
        "current_setup_fail_count",
        "corrected_setup_pass_count",
        "corrected_setup_fail_count",
        "current_actionable_count",
        "capped_actionable_count",
    ):
        print(f"{key}={fmt(summary_payload.get(key))}")
    print(f"symbols_newly_rescued_from_rank_outside_sweet_spot={','.join(summary_payload['symbols_newly_rescued_from_rank_outside_sweet_spot'])}")
    print(f"current_fail_reason_counts={json.dumps(summary_payload['current_fail_reason_counts'], sort_keys=True)}")
    print(f"corrected_fail_reason_counts={json.dumps(summary_payload['corrected_fail_reason_counts'], sort_keys=True)}")
    print()

    headers = [
        "symbol",
        "rank",
        "selection",
        "current_setup",
        "current_fail_reason",
        "rank_eligible",
        "corrected_setup",
        "cap_preview",
        "advice",
        "policy",
        "confidence",
        "reason_codes",
        "notes",
    ]
    table_rows = [
        [
            fmt(row.get("symbol")),
            fmt(row.get("rank")),
            fmt(row.get("selection_state")),
            fmt(row.get("current_setup_filter_state")),
            fmt(row.get("current_fail_reason")),
            fmt(row.get("corrected_rank_eligible")),
            fmt(row.get("corrected_setup_state_preview")),
            fmt(row.get("actionable_cap_state_preview")),
            fmt(row.get("advice_state")),
            fmt(row.get("policy_decision")),
            fmt(row.get("confidence_score")),
            fmt(row.get("reason_codes")),
            fmt(row.get("notes")),
        ]
        for row in rows
    ]
    widths = [len(header) for header in headers]
    for row_values in table_rows:
        for idx, value in enumerate(row_values):
            widths[idx] = min(max(widths[idx], len(value)), 38)

    def clip(value: str, width: int) -> str:
        if len(value) <= width:
            return value
        return value[: max(0, width - 1)] + "…"

    def line(values: list[str]) -> str:
        return " | ".join(clip(values[idx], widths[idx]).ljust(widths[idx]) for idx in range(len(values)))

    print(line(headers))
    print("-+-".join("-" * width for width in widths))
    for row_values in table_rows:
        print(line(row_values))

    hype = next((row for row in rows if str(row.get("symbol") or "").upper() == "HYPE"), None)
    if hype:
        print()
        print("--- HYPE rank-cap preview ---")
        for key in (
            "symbol",
            "rank",
            "selection_state",
            "current_setup_filter_state",
            "current_fail_reason",
            "rank_1_10_setup_eligible",
            "corrected_rank_eligible",
            "corrected_setup_state_preview",
            "corrected_setup_reason_preview",
            "top_rank_priority_warning",
            "actionable_cap_state_preview",
            "advice_state",
            "policy_decision",
            "btc_prior_24h",
            "notes",
        ):
            print(f"{key}={fmt(hype.get(key))}")


def main() -> int:
    args = parse_args()
    venue = str(args.venue)
    interval = str(args.interval)

    load_dotenv(dotenv_path=Path(".env"))
    conn = get_db_connection()
    try:
        latest_paper_asof, paper_rows = fetch_latest_paper_rows(
            conn,
            venue=venue,
            interval=interval,
            limit=int(args.limit),
        )
        latest_filter_asof, filter_by_asset = fetch_latest_filter_by_asset(conn, venue=venue)
    finally:
        conn.close()

    rows = build_preview_rows(
        paper_rows,
        filter_by_asset,
        max_actionable=int(args.max_actionable),
    )
    summary_payload = summary(
        rows,
        latest_paper_asof=latest_paper_asof,
        latest_filter_asof=latest_filter_asof,
        max_actionable=int(args.max_actionable),
    )

    if args.output == "jsonl":
        print(json.dumps({"summary": summary_payload}, ensure_ascii=False, default=json_default, sort_keys=True))
        for row in rows:
            print(json.dumps(row, ensure_ascii=False, default=json_default, sort_keys=True))
    else:
        print_table(rows, summary_payload)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
