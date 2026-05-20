from __future__ import annotations

import argparse
import json
from decimal import Decimal
from typing import Any

from src.common.utc import utc_now
from src.decision_gate.audit_writer_v1 import (
    DEFAULT_SAFETY_MARKERS,
    DecisionGateAuditRecord,
    build_decision_gate_audit_payload,
    count_decision_gate_audit_rows,
    insert_decision_gate_audit_record,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Smoke-test decision_gate_audit_log writer. "
            "Default is dry-run only; --write-db is required for an insert."
        )
    )
    parser.add_argument("--write-db", action="store_true")
    parser.add_argument("--trading-account-id", type=int, default=0)
    parser.add_argument("--user-id", type=int, default=None)
    parser.add_argument("--strategy-profile-id", type=int, default=None)
    parser.add_argument("--strategy-candidate-id", type=int, default=None)
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--asset-id", type=int, default=0)
    parser.add_argument("--symbol", default="SMOKE")
    parser.add_argument("--interval-code", default="4h")
    parser.add_argument("--asof-ts-utc", default=None)
    parser.add_argument("--created-ts-utc", default=None)
    parser.add_argument(
        "--execution-mode",
        choices=("PAPER", "LIVE_DRY_RUN"),
        default="PAPER",
    )
    parser.add_argument("--decision-state", default="SMOKE_DECISION_RECORDED")
    parser.add_argument("--permission-state", default="SMOKE_PERMISSION_CONTEXT_ONLY")
    parser.add_argument("--decision-reason", default="SMOKE_TEST_NO_PERMISSION_GRANTED")
    parser.add_argument("--execution-intent", default="NO_EXECUTION_INTENT")
    parser.add_argument("--action-type", default="AUDIT_WRITE_SMOKE")
    parser.add_argument("--requested-side", default=None, choices=("BUY", "SELL"))
    parser.add_argument("--requested-notional-eur", default=None)
    parser.add_argument("--requested-quantity-base", default=None)
    parser.add_argument("--limit-price", default=None)
    parser.add_argument("--reason-code", action="append", default=["SMOKE_TEST"])
    parser.add_argument("--upstream-ref-type", default="SMOKE_TEST")
    parser.add_argument("--upstream-ref-id", default=None)
    parser.add_argument("--output", choices=("table", "json", "summary"), default="table")
    return parser.parse_args()


def _optional_decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    stripped = str(value).strip()
    if not stripped:
        return None
    return Decimal(stripped)


def _default_ts() -> str:
    return utc_now().strftime("%Y-%m-%d %H:%M:%S.%f")


def _build_record(args: argparse.Namespace) -> DecisionGateAuditRecord:
    generated_ts = _default_ts()
    return DecisionGateAuditRecord(
        trading_account_id=args.trading_account_id,
        user_id=args.user_id,
        strategy_profile_id=args.strategy_profile_id,
        strategy_candidate_id=args.strategy_candidate_id,
        venue=args.venue,
        asset_id=args.asset_id,
        symbol=args.symbol,
        interval_code=args.interval_code,
        asof_ts_utc=args.asof_ts_utc or generated_ts,
        created_ts_utc=args.created_ts_utc or generated_ts,
        execution_mode=args.execution_mode,
        lifecycle_state="DECISION_GATE_AUDIT_SMOKE",
        permission_state=args.permission_state,
        decision_state=args.decision_state,
        decision_reason=args.decision_reason,
        execution_intent=args.execution_intent,
        action_type=args.action_type,
        requested_side=args.requested_side,
        requested_notional_eur=_optional_decimal(args.requested_notional_eur),
        requested_quantity_base=_optional_decimal(args.requested_quantity_base),
        limit_price=_optional_decimal(args.limit_price),
        reason_codes_json={
            "reason_codes": args.reason_code,
            "smoke_test": True,
            "permission_granted": False,
            "execution_planner": "none",
            "executor": "none",
        },
        safety_markers_json=dict(DEFAULT_SAFETY_MARKERS),
        upstream_ref_type=args.upstream_ref_type,
        upstream_ref_id=args.upstream_ref_id or f"decision_gate_audit_smoke:{generated_ts}",
    )


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _print_table(row: dict[str, Any]) -> None:
    fields = [
        "decision_gate_audit_log_id",
        "write_db",
        "row_count_before",
        "row_count_after",
        "row_count_delta",
        "execution_mode",
        "trading_account_id",
        "venue",
        "asset_id",
        "symbol",
        "interval_code",
        "decision_state",
        "permission_state",
        "decision_reason",
        "upstream_ref_type",
        "upstream_ref_id",
        "asof_ts_utc",
        "created_ts_utc",
    ]
    width = max(len(item) for item in fields)
    for field in fields:
        print(f"{field.ljust(width)} : {row.get(field, '')}")


def _print_safety_markers() -> None:
    print("broker_private_calls=0")
    print("broker_calls=0")
    print("broker_writes=0")
    print("order_submission=0")
    print("live_orders=0")
    print("execution_planner=none")
    print("executor=none")


def main() -> int:
    args = parse_args()
    record = _build_record(args)
    payload = build_decision_gate_audit_payload(record)

    row_count_before: int | None = None
    row_count_after: int | None = None
    inserted_id: int | None = None

    if args.write_db:
        row_count_before = count_decision_gate_audit_rows()
        inserted_id = insert_decision_gate_audit_record(record)
        row_count_after = count_decision_gate_audit_rows()

    output_row: dict[str, Any] = {
        **payload,
        "decision_gate_audit_log_id": inserted_id,
        "write_db": bool(args.write_db),
        "row_count_before": row_count_before,
        "row_count_after": row_count_after,
        "row_count_delta": (
            None
            if row_count_before is None or row_count_after is None
            else row_count_after - row_count_before
        ),
        "broker_private_calls": 0,
        "broker_calls": 0,
        "broker_writes": 0,
        "order_submission": 0,
        "live_orders": 0,
        "execution_planner": "none",
        "executor": "none",
    }

    if args.output == "json":
        print(json.dumps(output_row, indent=2, ensure_ascii=False, default=_json_default))
    elif args.output == "table":
        _print_table(output_row)
    else:
        print(
            "decision_gate_audit_writer_smoke_v1 "
            f"write_db={args.write_db} "
            f"inserted_id={inserted_id or ''} "
            f"row_count_delta={output_row['row_count_delta']}"
        )

    print()
    _print_safety_markers()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
