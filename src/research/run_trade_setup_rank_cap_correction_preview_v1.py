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


REPORT = "trade_setup_rank_cap_correction_preview_v1"
DEFAULT_VENUE = "bitvavo"
DEFAULT_INTERVAL = "4h"
DEFAULT_ENGINE_NAME = "selection_engine_v2"
DEFAULT_ENGINE_VERSION = "2.0"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview legacy rank sweet-spot behavior versus production rank 1..10 setup eligibility."
    )
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--interval", default=DEFAULT_INTERVAL)
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--max-actionable", type=int, default=3)
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
        p.reason_codes_json
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


def apply_actionable_cap(rows: list[dict[str, Any]], max_actionable: int) -> None:
    eligible = [row for row in rows if row["corrected_setup_state_preview"] == "PASS"]
    eligible.sort(
        key=lambda row: (
            row["rank"] is None,
            int(row["rank"]) if row["rank"] is not None else 999999,
            str(row["symbol"]),
        )
    )
    actionable = {id(row) for row in eligible[: max(0, int(max_actionable))]}
    for row in rows:
        if row["corrected_setup_state_preview"] != "PASS":
            row["actionable_cap_state_preview"] = "NOT_SETUP_ELIGIBLE"
        elif id(row) in actionable:
            row["actionable_cap_state_preview"] = "ACTIONABLE_WITHIN_CAP"
        else:
            row["actionable_cap_state_preview"] = "ELIGIBLE_OVER_CAP"


def build_rows(*, venue: str, interval: str, limit: int, max_actionable: int) -> list[dict[str, Any]]:
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
        legacy = evaluate_trade_setup(
            candidate,
            rank_min=4,
            rank_max=10,
            asset_suitability_mode="candidate_weak_set",
        )
        corrected = evaluate_trade_setup(
            candidate,
            rank_min=1,
            rank_max=10,
            asset_suitability_mode="candidate_weak_set",
        )
        advice = advice_by_asset.get(candidate.asset_id, {})
        notes: list[str] = []
        if candidate.priority_rank is not None and candidate.priority_rank < 4:
            notes.extend(["TOP_RANK_PRIORITY", "CHASE_RISK_CONTEXT"])

        legacy_fail_reason = "" if legacy.setup_filter_state == "PASS" else legacy.setup_filter_reason
        if legacy_fail_reason == "RANK_OUTSIDE_SETUP_ELIGIBLE_RANGE":
            legacy_fail_reason = "RANK_OUTSIDE_SWEET_SPOT"
        corrected_fail_reason = "" if corrected.setup_filter_state == "PASS" else corrected.setup_filter_reason
        rank_gate_removed = (
            legacy.setup_filter_state == "FAIL"
            and legacy_fail_reason == "RANK_OUTSIDE_SWEET_SPOT"
            and corrected_fail_reason != "RANK_OUTSIDE_SETUP_ELIGIBLE_RANGE"
        )

        rows.append(
            {
                "symbol": candidate.symbol,
                "rank": candidate.priority_rank,
                "selection_state": candidate.selection_state,
                "legacy_setup_filter_state": legacy.setup_filter_state,
                "legacy_fail_reason": legacy_fail_reason,
                "current_setup_filter_state": corrected.setup_filter_state,
                "current_fail_reason": corrected_fail_reason,
                "corrected_rank_eligible": candidate.priority_rank is not None and 1 <= candidate.priority_rank <= 10,
                "corrected_setup_state_preview": corrected.setup_filter_state,
                "corrected_setup_reason_preview": corrected.setup_filter_reason,
                "actionable_cap_state_preview": "",
                "advice_state": advice.get("advice_state"),
                "policy_decision": advice.get("policy_decision"),
                "confidence_score": advice.get("confidence_score"),
                "reason_codes": parse_reason_codes(advice.get("reason_codes_json")),
                "notes": notes,
                "rank_gate_removed": rank_gate_removed,
                "newly_rescued_from_legacy_rank_sweet_spot": rank_gate_removed and corrected.setup_filter_state == "PASS",
                "btc_prior_24h": candidate.btc_prior_24h,
            }
        )

    apply_actionable_cap(rows, max_actionable=max_actionable)
    return rows


def summary(rows: list[dict[str, Any]], max_actionable: int) -> dict[str, Any]:
    rank_gate_removed = [str(row["symbol"]) for row in rows if row["rank_gate_removed"]]
    rescued = [str(row["symbol"]) for row in rows if row["newly_rescued_from_legacy_rank_sweet_spot"]]
    return {
        "report": REPORT,
        "scope": "read-only preview",
        "row_count": len(rows),
        "max_actionable": int(max_actionable),
        "legacy_setup_pass_count": sum(1 for row in rows if row["legacy_setup_filter_state"] == "PASS"),
        "legacy_setup_fail_count": sum(1 for row in rows if row["legacy_setup_filter_state"] == "FAIL"),
        "corrected_setup_pass_count": sum(1 for row in rows if row["corrected_setup_state_preview"] == "PASS"),
        "corrected_setup_fail_count": sum(1 for row in rows if row["corrected_setup_state_preview"] == "FAIL"),
        "capped_actionable_count": sum(1 for row in rows if row["actionable_cap_state_preview"] == "ACTIONABLE_WITHIN_CAP"),
        "symbols_rank_gate_removed": rank_gate_removed,
        "symbols_newly_rescued_from_legacy_rank_sweet_spot": rescued,
        "legacy_fail_reason_counts": dict(Counter(str(row["legacy_fail_reason"]) for row in rows if row["legacy_setup_filter_state"] == "FAIL")),
        "corrected_fail_reason_counts": dict(Counter(str(row["current_fail_reason"]) for row in rows if row["corrected_setup_state_preview"] == "FAIL")),
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
    print(f"report={REPORT}")
    print("scope=read-only production correction preview")
    print("broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0 db_writes=0")
    for key in (
        "row_count",
        "max_actionable",
        "legacy_setup_pass_count",
        "legacy_setup_fail_count",
        "corrected_setup_pass_count",
        "corrected_setup_fail_count",
        "capped_actionable_count",
    ):
        print(f"{key}={payload[key]}")
    print(f"symbols_rank_gate_removed={','.join(payload['symbols_rank_gate_removed'])}")
    print(f"symbols_newly_rescued_from_legacy_rank_sweet_spot={','.join(payload['symbols_newly_rescued_from_legacy_rank_sweet_spot'])}")
    print(f"legacy_fail_reason_counts={json.dumps(payload['legacy_fail_reason_counts'], sort_keys=True)}")
    print(f"corrected_fail_reason_counts={json.dumps(payload['corrected_fail_reason_counts'], sort_keys=True)}")
    print()

    headers = ["symbol", "rank", "selection", "legacy_setup", "legacy_fail", "corrected_setup", "current_fail", "cap_preview", "advice", "policy", "notes"]
    data = [
        [
            fmt(row["symbol"]),
            fmt(row["rank"]),
            fmt(row["selection_state"]),
            fmt(row["legacy_setup_filter_state"]),
            fmt(row["legacy_fail_reason"]),
            fmt(row["corrected_setup_state_preview"]),
            fmt(row["current_fail_reason"]),
            fmt(row["actionable_cap_state_preview"]),
            fmt(row["advice_state"]),
            fmt(row["policy_decision"]),
            fmt(row["notes"]),
        ]
        for row in rows
    ]
    widths = [len(header) for header in headers]
    for line in data:
        for idx, value in enumerate(line):
            widths[idx] = min(max(widths[idx], len(value)), 40)

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
        print("--- HYPE rank-cap preview ---")
        for key, value in payload["hype"].items():
            print(f"{key}={fmt(value)}")


def main() -> int:
    args = parse_args()
    rows = build_rows(
        venue=str(args.venue),
        interval=str(args.interval),
        limit=int(args.limit),
        max_actionable=int(args.max_actionable),
    )
    payload = summary(rows, max_actionable=int(args.max_actionable))
    if args.output == "jsonl":
        print(json.dumps({"summary": payload}, default=json_default, sort_keys=True))
        for row in rows:
            print(json.dumps(row, default=json_default, sort_keys=True))
    else:
        print_table(rows, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
