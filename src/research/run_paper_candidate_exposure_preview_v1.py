from __future__ import annotations

# Synth v2 - Paper Candidate Exposure Preview V1.
#
# LAYER:
# research / paper-candidate diagnostics
#
# BOUNDARY:
# Allowed:
# - read staged paper candidate rows
# - simulate simple fixed-hold exposure windows
# - compute concurrent exposure and capacity diagnostics
# - print table or JSON output
#
# Forbidden:
# - account balance writes
# - portfolio writes
# - decision_state writes
# - execution_intent writes
# - execution_plan writes
# - executor calls
# - broker/exchange actions
# - order handling
#
# IMPORTANT:
# This is a read-only diagnostic. It does not create paper positions.
# It estimates whether staged candidate cadence fits the intended sleeve capacity.

import argparse
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from src.common.db import get_connection


DEFAULT_DATABASE = "synth_bt"
DEFAULT_TABLE = "research_paper_candidate_signal"
DEFAULT_POLICY_NAME = "swing_pullback_recovery_v5_24h_tactical"
DEFAULT_SIGNAL_STATUS = "PROMOTION_CANDIDATE"
TABLE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")


@dataclass(frozen=True)
class CandidateExposureRow:
    candidate_id: int
    symbol: str
    open_ts_utc: datetime
    close_ts_utc: datetime
    priority_rank: int | None
    selection_score: Decimal | None
    simulated_net_return: Decimal
    notional_eur: Decimal
    simulated_pnl_eur: Decimal


@dataclass(frozen=True)
class ExposureEvent:
    ts_utc: datetime
    event_type: str
    candidate_id: int
    symbol: str
    notional_delta_eur: Decimal


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only exposure overlap preview for staged paper candidate rows."
    )
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    parser.add_argument("--table", default=DEFAULT_TABLE)
    parser.add_argument("--policy-name", default=DEFAULT_POLICY_NAME)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--signal-status", default=DEFAULT_SIGNAL_STATUS)
    parser.add_argument("--account-equity-eur", default="1000.00")
    parser.add_argument("--target-fraction", default="0.03300000")
    parser.add_argument("--hold-hours", type=int, default=24)
    parser.add_argument("--max-sleeve-fraction", default="0.25")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args()


def validate_table_name(table_name: str) -> str:
    if not TABLE_NAME_PATTERN.match(table_name):
        raise ValueError(f"Unsafe table name: {table_name}")
    return table_name


def decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def decimal_required(value: Any, field_name: str) -> Decimal:
    result = decimal_or_none(value)
    if result is None:
        raise ValueError(f"{field_name} is required")
    return result


def q(value: Decimal, places: str) -> Decimal:
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return str(value)


def fetch_rows(args: argparse.Namespace) -> list[CandidateExposureRow]:
    safe_table = validate_table_name(args.table)
    account_equity_eur = Decimal(str(args.account_equity_eur))
    target_fraction = Decimal(str(args.target_fraction))
    notional_eur = account_equity_eur * target_fraction
    hold_delta = timedelta(hours=int(args.hold_hours))

    sql = f"""
    SELECT
        candidate_id,
        symbol,
        asof_ts_utc,
        priority_rank,
        selection_score,
        simulated_net_return
    FROM {safe_table}
    WHERE policy_name = %s
      AND load_batch_id = %s
      AND signal_status = %s
      AND simulated_net_return IS NOT NULL
    ORDER BY asof_ts_utc ASC, candidate_id ASC
    """

    conn = get_connection(database=args.database)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, [args.policy_name, args.batch_id, args.signal_status])
            raw_rows = cur.fetchall() or []
    finally:
        conn.close()

    out: list[CandidateExposureRow] = []
    for row in raw_rows:
        simulated_return = decimal_required(row["simulated_net_return"], "simulated_net_return")
        open_ts = row["asof_ts_utc"]
        out.append(
            CandidateExposureRow(
                candidate_id=int(row["candidate_id"]),
                symbol=str(row["symbol"]),
                open_ts_utc=open_ts,
                close_ts_utc=open_ts + hold_delta,
                priority_rank=None if row.get("priority_rank") is None else int(row["priority_rank"]),
                selection_score=decimal_or_none(row.get("selection_score")),
                simulated_net_return=simulated_return,
                notional_eur=notional_eur,
                simulated_pnl_eur=notional_eur * simulated_return,
            )
        )

    return out


def build_events(rows: list[CandidateExposureRow]) -> list[ExposureEvent]:
    events: list[ExposureEvent] = []

    for row in rows:
        events.append(
            ExposureEvent(
                ts_utc=row.open_ts_utc,
                event_type="OPEN",
                candidate_id=row.candidate_id,
                symbol=row.symbol,
                notional_delta_eur=row.notional_eur,
            )
        )
        events.append(
            ExposureEvent(
                ts_utc=row.close_ts_utc,
                event_type="CLOSE",
                candidate_id=row.candidate_id,
                symbol=row.symbol,
                notional_delta_eur=-row.notional_eur,
            )
        )

    return sorted(
        events,
        key=lambda item: (
            item.ts_utc,
            0 if item.event_type == "CLOSE" else 1,
            item.candidate_id,
        ),
    )


def exposure_timeline(rows: list[CandidateExposureRow]) -> list[dict[str, Any]]:
    events = build_events(rows)
    active_notional = Decimal("0")
    active_ids: set[int] = set()
    timeline: list[dict[str, Any]] = []

    for event in events:
        if event.event_type == "OPEN":
            active_notional += event.notional_delta_eur
            active_ids.add(event.candidate_id)
        else:
            active_notional += event.notional_delta_eur
            active_ids.discard(event.candidate_id)

        timeline.append(
            {
                "ts_utc": event.ts_utc,
                "event_type": event.event_type,
                "candidate_id": event.candidate_id,
                "symbol": event.symbol,
                "active_positions": len(active_ids),
                "active_notional_eur": active_notional,
            }
        )

    return timeline


def aggregate(args: argparse.Namespace, rows: list[CandidateExposureRow], timeline: list[dict[str, Any]]) -> dict[str, Any]:
    account_equity_eur = Decimal(str(args.account_equity_eur))
    sleeve_cap_eur = account_equity_eur * Decimal(str(args.max_sleeve_fraction))

    max_active_positions = max((row["active_positions"] for row in timeline), default=0)
    max_active_notional = max((row["active_notional_eur"] for row in timeline), default=Decimal("0"))
    total_pnl = sum((row.simulated_pnl_eur for row in rows), Decimal("0"))
    total_notional = sum((row.notional_eur for row in rows), Decimal("0"))

    return {
        "trades": len(rows),
        "symbols": len({row.symbol for row in rows}),
        "hold_hours": int(args.hold_hours),
        "account_equity_eur": str(q(account_equity_eur, "0.01")),
        "target_fraction": str(Decimal(str(args.target_fraction))),
        "per_trade_notional_eur": str(q(account_equity_eur * Decimal(str(args.target_fraction)), "0.01")),
        "max_sleeve_fraction": str(Decimal(str(args.max_sleeve_fraction))),
        "sleeve_cap_eur": str(q(sleeve_cap_eur, "0.01")),
        "gross_turnover_notional_eur": str(q(total_notional, "0.01")),
        "max_active_positions": max_active_positions,
        "max_active_notional_eur": str(q(max_active_notional, "0.01")),
        "max_active_fraction_of_equity": str(q(max_active_notional / account_equity_eur, "0.0001")) if account_equity_eur else "0.0000",
        "max_active_fraction_of_sleeve": str(q(max_active_notional / sleeve_cap_eur, "0.0001")) if sleeve_cap_eur else "0.0000",
        "capacity_state": "PASS" if max_active_notional <= sleeve_cap_eur else "EXCEEDS_SLEEVE_CAP",
        "total_sim_pnl_eur": str(q(total_pnl, "0.0001")),
    }


def row_to_dict(row: CandidateExposureRow) -> dict[str, Any]:
    payload = asdict(row)
    payload["open_ts_utc"] = row.open_ts_utc.isoformat(sep=" ")
    payload["close_ts_utc"] = row.close_ts_utc.isoformat(sep=" ")
    payload["selection_score"] = None if row.selection_score is None else str(row.selection_score)
    payload["simulated_net_return"] = str(row.simulated_net_return)
    payload["notional_eur"] = str(row.notional_eur)
    payload["simulated_pnl_eur"] = str(row.simulated_pnl_eur)
    return payload


def timeline_to_jsonable(timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in timeline:
        item = dict(row)
        item["ts_utc"] = row["ts_utc"].isoformat(sep=" ")
        item["active_notional_eur"] = str(row["active_notional_eur"])
        out.append(item)
    return out


def build_payload(args: argparse.Namespace, rows: list[CandidateExposureRow]) -> dict[str, Any]:
    timeline = exposure_timeline(rows)
    display_rows = rows if args.limit is None else rows[: max(args.limit, 0)]

    return {
        "meta": {
            "database": args.database,
            "table": args.table,
            "policy_name": args.policy_name,
            "batch_id": args.batch_id,
            "signal_status": args.signal_status,
            "rows_matched": len(rows),
            "detail_limit": args.limit,
            "writes": "none",
            "live_execution_permission": "NOT_GRANTED",
        },
        "aggregate": aggregate(args, rows, timeline),
        "detail_rows": [row_to_dict(row) for row in display_rows],
        "timeline": timeline_to_jsonable(timeline),
    }


def print_table(payload: dict[str, Any]) -> None:
    meta = payload["meta"]
    agg = payload["aggregate"]

    print("Paper candidate exposure preview")
    for key in [
        "database",
        "table",
        "policy_name",
        "batch_id",
        "signal_status",
        "rows_matched",
        "detail_limit",
        "writes",
    ]:
        print(f"{key}: {meta[key]}")

    print()
    print("--- exposure aggregate ---")
    for key in [
        "trades",
        "symbols",
        "hold_hours",
        "account_equity_eur",
        "target_fraction",
        "per_trade_notional_eur",
        "max_sleeve_fraction",
        "sleeve_cap_eur",
        "gross_turnover_notional_eur",
        "max_active_positions",
        "max_active_notional_eur",
        "max_active_fraction_of_equity",
        "max_active_fraction_of_sleeve",
        "capacity_state",
        "total_sim_pnl_eur",
    ]:
        print(f"{key}: {agg[key]}")

    print()
    print("--- candidate windows ---")
    if meta["detail_limit"] is not None:
        print(f"displayed_rows: {len(payload['detail_rows'])} / {meta['rows_matched']}")
    print("candidate_id | open_ts | close_ts | symbol | rank | score | notional_eur | sim_pnl_eur")
    print("-" * 130)

    for row in payload["detail_rows"]:
        print(
            f"{row['candidate_id']} | "
            f"{row['open_ts_utc']} | "
            f"{row['close_ts_utc']} | "
            f"{row['symbol']} | "
            f"{row['priority_rank']} | "
            f"{row['selection_score']} | "
            f"{q(Decimal(row['notional_eur']), '0.01')} | "
            f"{q(Decimal(row['simulated_pnl_eur']), '0.0001')}"
        )

    print()
    print("--- interpretation ---")
    print("READ_ONLY_PREVIEW: no DB writes, no execution plans, no orders.")
    print("CAPACITY_CHECK_ONLY: uses fixed hold window and fixed notional.")
    print("LIVE_EXECUTION_PERMISSION: NOT_GRANTED")


def main() -> int:
    args = parse_args()
    validate_table_name(args.table)

    rows = fetch_rows(args)
    payload = build_payload(args, rows)

    if args.output == "json":
        print(json.dumps(payload, default=json_default, indent=2, sort_keys=True))
    else:
        print_table(payload)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
