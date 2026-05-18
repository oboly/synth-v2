from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from src.common.db import get_connection
from src.trade_setup_filter.engine_v1 import evaluate_trade_setup
from src.trade_setup_filter.repository import fetch_latest_candidates


DEFAULT_VENUE = "bitvavo"
DEFAULT_INTERVAL = "4h"
DEFAULT_ENGINE_NAME = "selection_engine_v2"
DEFAULT_ENGINE_VERSION = "2.0"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only diagnostic for latest trade setup filter fail reasons."
    )
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--interval", default=DEFAULT_INTERVAL)
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--symbol")
    parser.add_argument("--output", choices=("table", "jsonl"), default="table")
    return parser.parse_args()


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return format(value, "f").rstrip("0").rstrip(".")
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
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
    return [str(parsed)]


def fetch_latest_paper_advice_rows(*, venue: str, interval: str, limit: int) -> list[dict[str, Any]]:
    sql = """
    WITH latest AS (
        SELECT MAX(asof_ts_utc) AS asof_ts_utc
        FROM paper_advice_observation
        WHERE venue = %(venue)s
          AND interval_code = %(interval)s
    )
    SELECT
        paper_advice_observation_id,
        asset_id,
        symbol,
        venue,
        interval_code,
        p.asof_ts_utc,
        p.selection_state,
        p.selection_score,
        p.priority_rank,
        p.setup_filter_state,
        p.setup_filter_reason,
        p.policy_decision,
        p.advice_state,
        p.advice_action,
        p.confidence_score,
        p.risk_label,
        p.reason_codes_json,
        p.leg_direction,
        p.entry_zone_low,
        p.entry_zone_high,
        p.tp_zone_low,
        p.tp_zone_high,
        p.invalidation_price
    FROM paper_advice_observation p
    JOIN latest l
      ON l.asof_ts_utc = p.asof_ts_utc
    WHERE p.venue = %(venue)s
      AND p.interval_code = %(interval)s
    ORDER BY
        p.priority_rank IS NULL,
        p.priority_rank ASC,
        p.confidence_score DESC,
        p.symbol ASC
    LIMIT %(limit)s
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, {"venue": venue, "interval": interval, "limit": int(limit)})
            return list(cur.fetchall())
    finally:
        conn.close()


def build_rows(*, venue: str, interval: str, limit: int, symbol: str | None) -> list[dict[str, Any]]:
    candidates = fetch_latest_candidates(
        venue=venue,
        engine_name=DEFAULT_ENGINE_NAME,
        engine_version=DEFAULT_ENGINE_VERSION,
        limit=limit,
    )
    advice_rows = fetch_latest_paper_advice_rows(venue=venue, interval=interval, limit=limit)
    advice_by_asset = {int(row["asset_id"]): row for row in advice_rows}

    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        if symbol and candidate.symbol.upper() != symbol.upper():
            continue
        decision = evaluate_trade_setup(
            candidate,
            asset_suitability_mode="candidate_weak_set",
        )
        advice = advice_by_asset.get(candidate.asset_id, {})
        reason_codes = parse_reason_codes(advice.get("reason_codes_json"))
        fail_reason = "" if decision.setup_filter_state == "PASS" else decision.setup_filter_reason
        rows.append(
            {
                "symbol": candidate.symbol,
                "advice_state": advice.get("advice_state"),
                "action": advice.get("advice_action"),
                "confidence_score": advice.get("confidence_score"),
                "leg_direction": advice.get("leg_direction"),
                "selection_state": candidate.selection_state,
                "rank": candidate.priority_rank,
                "setup_filter_state": decision.setup_filter_state,
                "policy_decision": advice.get("policy_decision"),
                "risk_label": advice.get("risk_label"),
                "reason_codes": reason_codes,
                "fail_primary_reason": fail_reason,
                "fail_reason_codes": [] if decision.setup_filter_state == "PASS" else [decision.setup_filter_reason],
                "failed_guard_name": fail_reason,
                "failed_guard_detail": decision.notes if decision.setup_filter_state == "FAIL" else "",
                "relevant_metric": "priority_rank" if "RANK" in fail_reason else "",
                "threshold": "1..10" if "RANK" in fail_reason else "",
                "observed_value": candidate.priority_rank if "RANK" in fail_reason else "",
                "source_table": "selection_state + obs_market_candle",
                "source_ts_utc": candidate.asof_ts_utc,
                "entry_zone_low": advice.get("entry_zone_low"),
                "entry_zone_high": advice.get("entry_zone_high"),
                "tp_zone_low": advice.get("tp_zone_low"),
                "tp_zone_high": advice.get("tp_zone_high"),
                "invalidation_price": advice.get("invalidation_price"),
                "btc_prior_24h": candidate.btc_prior_24h,
                "notes": decision.notes,
            }
        )
    return rows


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    fail_rows = [row for row in rows if row["setup_filter_state"] == "FAIL"]
    return {
        "total_rows": len(rows),
        "setup_pass_count": sum(1 for row in rows if row["setup_filter_state"] == "PASS"),
        "setup_fail_count": len(fail_rows),
        "by_selection_state": dict(Counter(str(row.get("selection_state") or "") for row in rows)),
        "by_advice_state": dict(Counter(str(row.get("advice_state") or "") for row in rows)),
        "by_policy_decision": dict(Counter(str(row.get("policy_decision") or "") for row in rows)),
        "by_fail_primary_reason": dict(Counter(str(row.get("fail_primary_reason") or "") for row in fail_rows)),
        "watch_setup_fail_symbols": [
            str(row["symbol"])
            for row in fail_rows
            if str(row.get("selection_state") or "").upper() == "WATCHLIST"
        ],
        "hype": next((row for row in rows if str(row.get("symbol") or "").upper() == "HYPE"), None),
        "safety": {
            "broker_private_calls": 0,
            "broker_writes": 0,
            "order_submission": 0,
            "live_orders": 0,
            "db_writes": 0,
            "decision_gate_changes": 0,
            "execution_planner_changes": 0,
            "executor_changes": 0,
        },
    }


def print_table(rows: list[dict[str, Any]], payload: dict[str, Any]) -> None:
    print("report=trade_setup_fail_reason_diagnostic_v1")
    print("scope=read-only diagnostic")
    print("broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0 db_writes=0")
    for key in ("total_rows", "setup_pass_count", "setup_fail_count"):
        print(f"{key}={payload[key]}")
    print(f"by_fail_primary_reason={json.dumps(payload['by_fail_primary_reason'], sort_keys=True)}")
    print()

    headers = ["symbol", "rank", "selection", "setup", "fail_primary_reason", "advice", "policy", "confidence", "notes"]
    data = [
        [
            fmt(row.get("symbol")),
            fmt(row.get("rank")),
            fmt(row.get("selection_state")),
            fmt(row.get("setup_filter_state")),
            fmt(row.get("fail_primary_reason")),
            fmt(row.get("advice_state")),
            fmt(row.get("policy_decision")),
            fmt(row.get("confidence_score")),
            fmt(row.get("notes")),
        ]
        for row in rows
    ]
    widths = [len(header) for header in headers]
    for line in data:
        for idx, value in enumerate(line):
            widths[idx] = min(max(widths[idx], len(value)), 44)

    def clip(value: str, width: int) -> str:
        return value if len(value) <= width else value[: width - 1] + "…"

    def render(values: list[str]) -> str:
        return " | ".join(clip(values[idx], widths[idx]).ljust(widths[idx]) for idx in range(len(values)))

    print(render(headers))
    print("-+-".join("-" * width for width in widths))
    for line in data:
        print(render(line))

    if payload.get("hype"):
        print()
        print("--- HYPE diagnostic ---")
        for key, value in payload["hype"].items():
            print(f"{key}={fmt(value)}")


def main() -> int:
    args = parse_args()
    rows = build_rows(
        venue=str(args.venue),
        interval=str(args.interval),
        limit=int(args.limit),
        symbol=args.symbol,
    )
    payload = summary(rows)
    if args.output == "jsonl":
        print(json.dumps({"summary": payload}, default=json_default, sort_keys=True))
        for row in rows:
            print(json.dumps(row, default=json_default, sort_keys=True))
    else:
        print_table(rows, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
