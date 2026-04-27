from __future__ import annotations

"""
Synth v2 - Policy Result Report V1.

LAYER:
research/backtest reporting

BOUNDARY:
Allowed:
- read persisted named policy evaluation summaries from synth_bt
- compare train/test windows
- report walk-forward degradation and promotion status

Forbidden:
- account state
- balances
- positions
- orders
- execution plans
- broker actions

Purpose:
Turn persisted policy evaluation rows into a compact walk-forward scoreboard.
"""

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from src.common.db import get_connection


BT_DB = "synth_bt"
RESULT_TABLE = "bt_named_policy_eval_result_v1"


@dataclass(frozen=True)
class PolicyEvalRow:
    named_policy_eval_result_id: int
    result_set_name: str
    policy_name: str
    from_ts_utc: datetime | None
    to_ts_utc: datetime | None
    rows_total: int
    symbol_count: int
    day_count: int
    rows_4h: int
    avg_net_4h: Decimal | None
    winrate_4h: Decimal | None
    rows_24h: int
    avg_net_24h: Decimal | None
    winrate_24h: Decimal | None
    created_ts_utc: datetime


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Report persisted named policy walk-forward results."
    )
    parser.add_argument("--result-set-name", default=None)
    parser.add_argument("--min-test-rows-24h", type=int, default=10)
    parser.add_argument("--min-test-net-24h", default="0.00000000")
    parser.add_argument("--min-test-winrate-24h", default="0.55000000")
    parser.add_argument("--min-net24-retention-ratio", default="0.25000000")
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args()


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return str(value)


def _fmt_decimal(value: Decimal | None, places: int = 6) -> str:
    if value is None:
        return ""
    quant = Decimal("1").scaleb(-places)
    return str(value.quantize(quant))


def _fmt_window(row: PolicyEvalRow) -> str:
    start = "" if row.from_ts_utc is None else row.from_ts_utc.strftime("%Y-%m-%d")
    end = "" if row.to_ts_utc is None else row.to_ts_utc.strftime("%Y-%m-%d")
    return f"{start}->{end}"


def _print_table(title: str, rows: list[dict[str, Any]]) -> None:
    print()
    print(f"=== {title} ===")

    if not rows:
        print("(no rows)")
        return

    headers = list(rows[0].keys())
    printable = [[str(row.get(header, "")) for header in headers] for row in rows]

    widths = [len(header) for header in headers]
    for row in printable:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(value))

    def fmt(values: list[str]) -> str:
        return " | ".join(value.ljust(widths[idx]) for idx, value in enumerate(values))

    print(fmt(headers))
    print("-+-".join("-" * width for width in widths))

    for row in printable:
        print(fmt(row))


def fetch_latest_result_set_name() -> str | None:
    sql = f"""
    SELECT
        result_set_name
    FROM {RESULT_TABLE}
    GROUP BY
        result_set_name
    ORDER BY
        MAX(created_ts_utc) DESC
    LIMIT 1
    """

    conn = get_connection(database=BT_DB)
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()
            if not row:
                return None
            if not isinstance(row, dict):
                raise TypeError("Expected dict row from database cursor")
            return str(row["result_set_name"])
    finally:
        conn.close()


def fetch_eval_rows(*, result_set_name: str) -> list[PolicyEvalRow]:
    sql = f"""
    SELECT
        named_policy_eval_result_id,
        result_set_name,
        policy_name,
        from_ts_utc,
        to_ts_utc,
        rows_total,
        symbol_count,
        day_count,
        rows_4h,
        avg_net_4h,
        winrate_4h,
        rows_24h,
        avg_net_24h,
        winrate_24h,
        created_ts_utc
    FROM {RESULT_TABLE}
    WHERE result_set_name = %s
    ORDER BY
        policy_name,
        from_ts_utc,
        to_ts_utc,
        named_policy_eval_result_id
    """

    conn = get_connection(database=BT_DB)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, [result_set_name])
            rows = cur.fetchall() or []
            if not all(isinstance(row, dict) for row in rows):
                raise TypeError("Expected dict rows from database cursor")
    finally:
        conn.close()

    out: list[PolicyEvalRow] = []
    for row in rows:
        out.append(
            PolicyEvalRow(
                named_policy_eval_result_id=int(row["named_policy_eval_result_id"]),
                result_set_name=str(row["result_set_name"]),
                policy_name=str(row["policy_name"]),
                from_ts_utc=row["from_ts_utc"],
                to_ts_utc=row["to_ts_utc"],
                rows_total=int(row["rows_total"]),
                symbol_count=int(row["symbol_count"]),
                day_count=int(row["day_count"]),
                rows_4h=int(row["rows_4h"]),
                avg_net_4h=_to_decimal(row["avg_net_4h"]),
                winrate_4h=_to_decimal(row["winrate_4h"]),
                rows_24h=int(row["rows_24h"]),
                avg_net_24h=_to_decimal(row["avg_net_24h"]),
                winrate_24h=_to_decimal(row["winrate_24h"]),
                created_ts_utc=row["created_ts_utc"],
            )
        )

    return out


def _retention_ratio(train: Decimal | None, test: Decimal | None) -> Decimal | None:
    if train is None or test is None:
        return None
    if train <= 0:
        return None
    return test / train


def _delta(test: Decimal | None, train: Decimal | None) -> Decimal | None:
    if train is None or test is None:
        return None
    return test - train


def _promotion_status(
    *,
    train: PolicyEvalRow | None,
    test: PolicyEvalRow | None,
    min_test_rows_24h: int,
    min_test_net_24h: Decimal,
    min_test_winrate_24h: Decimal,
    min_net24_retention_ratio: Decimal,
) -> str:
    if train is None or test is None:
        return "INSUFFICIENT_WINDOWS"

    if test.rows_24h < min_test_rows_24h:
        return "INSUFFICIENT_TEST_ROWS"

    if test.avg_net_24h is None or test.avg_net_24h <= min_test_net_24h:
        return "FAIL_TEST_NET_24H"

    if test.winrate_24h is None or test.winrate_24h < min_test_winrate_24h:
        return "FAIL_TEST_WINRATE_24H"

    retention = _retention_ratio(train.avg_net_24h, test.avg_net_24h)
    if retention is not None and retention < min_net24_retention_ratio:
        return "POSITIVE_BUT_DEGRADED"

    return "PASS_WALK_FORWARD"


def build_report(
    rows: list[PolicyEvalRow],
    *,
    min_test_rows_24h: int,
    min_test_net_24h: Decimal,
    min_test_winrate_24h: Decimal,
    min_net24_retention_ratio: Decimal,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[PolicyEvalRow]] = {}

    for row in rows:
        grouped.setdefault(row.policy_name, []).append(row)

    report_rows: list[dict[str, Any]] = []

    for policy_name, policy_rows in sorted(grouped.items()):
        ordered = sorted(
            policy_rows,
            key=lambda row: (
                row.from_ts_utc or datetime.min,
                row.to_ts_utc or datetime.min,
                row.named_policy_eval_result_id,
            ),
        )

        train = ordered[0] if len(ordered) >= 1 else None
        test = ordered[-1] if len(ordered) >= 2 else None

        net24_retention = (
            None if train is None or test is None
            else _retention_ratio(train.avg_net_24h, test.avg_net_24h)
        )
        net24_delta = (
            None if train is None or test is None
            else _delta(test.avg_net_24h, train.avg_net_24h)
        )
        net4_retention = (
            None if train is None or test is None
            else _retention_ratio(train.avg_net_4h, test.avg_net_4h)
        )
        net4_delta = (
            None if train is None or test is None
            else _delta(test.avg_net_4h, train.avg_net_4h)
        )

        status = _promotion_status(
            train=train,
            test=test,
            min_test_rows_24h=min_test_rows_24h,
            min_test_net_24h=min_test_net_24h,
            min_test_winrate_24h=min_test_winrate_24h,
            min_net24_retention_ratio=min_net24_retention_ratio,
        )

        report_rows.append(
            {
                "policy": policy_name,
                "train_window": "" if train is None else _fmt_window(train),
                "test_window": "" if test is None else _fmt_window(test),
                "train_rows24": "" if train is None else train.rows_24h,
                "train_net24": "" if train is None else _fmt_decimal(train.avg_net_24h),
                "train_wr24": "" if train is None else _fmt_decimal(train.winrate_24h, 4),
                "test_rows24": "" if test is None else test.rows_24h,
                "test_net24": "" if test is None else _fmt_decimal(test.avg_net_24h),
                "test_wr24": "" if test is None else _fmt_decimal(test.winrate_24h, 4),
                "net24_retention": _fmt_decimal(net24_retention, 4),
                "net24_delta": _fmt_decimal(net24_delta),
                "train_rows4": "" if train is None else train.rows_4h,
                "train_net4": "" if train is None else _fmt_decimal(train.avg_net_4h),
                "test_rows4": "" if test is None else test.rows_4h,
                "test_net4": "" if test is None else _fmt_decimal(test.avg_net_4h),
                "net4_retention": _fmt_decimal(net4_retention, 4),
                "net4_delta": _fmt_decimal(net4_delta),
                "status": status,
            }
        )

    return report_rows


def main() -> int:
    args = parse_args()

    result_set_name = args.result_set_name
    if result_set_name is None:
        result_set_name = fetch_latest_result_set_name()

    if result_set_name is None:
        raise RuntimeError(f"No rows found in {BT_DB}.{RESULT_TABLE}")

    rows = fetch_eval_rows(result_set_name=str(result_set_name))

    report = build_report(
        rows,
        min_test_rows_24h=int(args.min_test_rows_24h),
        min_test_net_24h=Decimal(str(args.min_test_net_24h)),
        min_test_winrate_24h=Decimal(str(args.min_test_winrate_24h)),
        min_net24_retention_ratio=Decimal(str(args.min_net24_retention_ratio)),
    )

    payload = {
        "result_set_name": result_set_name,
        "rows_loaded": len(rows),
        "policy_count": len(report),
        "report": report,
    }

    if args.output == "json":
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default))
        return 0

    print(f"result_set_name={result_set_name}")
    print(f"rows_loaded={len(rows)}")
    print(f"policy_count={len(report)}")

    _print_table("POLICY WALK-FORWARD REPORT", report)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
