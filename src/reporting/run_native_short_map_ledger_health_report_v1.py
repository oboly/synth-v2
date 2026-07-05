from __future__ import annotations

"""Manual native SHORT map ledger health report.

Read-only, market-only, account-agnostic. Reports ledger state; does not
create, materialize, rebuild, repair, or promote maps, and never invokes the
materializer, scope seeder, or lifecycle mutation paths.

Safety markers:
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
db_writes=0

Reads:
- native_short_map_scope_v1
- native_short_map_v1
- native_short_map_generation_event_v1
- native_short_map_lifecycle_event_v1
- obs_market_candle (latest closed primary/supporting candle timestamp only)

Writes: none.
"""

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from typing import Any

from src.common.db import get_connection
from src.reporting.native_short_map_ledger_health_report_v1 import (
    DEFAULT_VENUE,
    OVERALL_HEALTH_HEALTHY,
    OVERALL_HEALTH_NOT_APPLICABLE,
    STATUS_FAILED,
    LedgerHealthReport,
    failed_report,
    generate_report_for_symbol,
)
from src.market_data.native_short_map_lifecycle_v1 import (
    DEFAULT_FIB_TRADING_HORIZON,
    DEFAULT_PRIMARY_INTERVAL,
    DEFAULT_QUOTE_CURRENCY,
    DEFAULT_SUPPORTING_INTERVAL,
)

RUNNER_NAME = "run_native_short_map_ledger_health_report_v1"
RUNNER_VERSION = "0.1"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Manual, read-only native SHORT map ledger health report. "
            "Reports ledger state only; never creates, materializes, rebuilds, "
            "repairs, or promotes maps."
        )
    )
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument(
        "--symbols",
        required=True,
        help="Explicit comma-separated symbols, e.g. BTC or BTC,ETH. Never enumerated.",
    )
    parser.add_argument("--quote-currency", default=DEFAULT_QUOTE_CURRENCY)
    parser.add_argument("--fib-trading-horizon", default=DEFAULT_FIB_TRADING_HORIZON)
    parser.add_argument("--primary-interval", default=DEFAULT_PRIMARY_INTERVAL)
    parser.add_argument("--supporting-interval", default=DEFAULT_SUPPORTING_INTERVAL)
    parser.add_argument(
        "--output",
        choices=("jsonl", "summary"),
        default="jsonl",
        help="jsonl emits one machine-readable record per event/result.",
    )
    return parser.parse_args(argv)


def parse_symbols(text: str) -> list[str]:
    symbols = sorted({part.strip().upper() for part in text.split(",") if part.strip()})
    if not symbols:
        raise ValueError("--symbols must contain at least one symbol")
    return symbols


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def emit_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True, default=_json_default))
    sys.stdout.flush()


SAFETY_MARKERS: dict[str, Any] = {
    "broker_private_calls": 0,
    "broker_writes": 0,
    "order_submission": 0,
    "live_orders": 0,
    "decision_gate": "none",
    "execution_planner": "none",
    "executor": "none",
    "db_writes": 0,
}


def _print_started(*, args: argparse.Namespace, symbols: list[str]) -> None:
    if args.output == "jsonl":
        emit_json(
            {
                "event": "STARTED",
                "runner": RUNNER_NAME,
                "runner_version": RUNNER_VERSION,
                "venue": args.venue,
                "quote_currency": args.quote_currency,
                "fib_trading_horizon": args.fib_trading_horizon,
                "primary_interval": args.primary_interval,
                "supporting_interval": args.supporting_interval,
                "symbols": symbols,
                **SAFETY_MARKERS,
                "started_at_utc": datetime.now(UTC),
            }
        )
    else:
        print(f"STARTED runner={RUNNER_NAME} version={RUNNER_VERSION}")
        print(
            f"venue={args.venue} quote_currency={args.quote_currency} "
            f"fib_trading_horizon={args.fib_trading_horizon} "
            f"primary_interval={args.primary_interval} "
            f"supporting_interval={args.supporting_interval} "
            f"symbols={','.join(symbols)}"
        )
        for key, value in SAFETY_MARKERS.items():
            print(f"{key}={value}")
        sys.stdout.flush()


def _emit_result(report: LedgerHealthReport, *, output: str) -> None:
    payload = {"event": "RESULT", "runner": RUNNER_NAME, **report.to_json_dict()}
    if output == "jsonl":
        emit_json(payload)
    else:
        print(
            f"{report.overall_health_status} symbol={report.symbol} "
            f"scope_status={report.scope_status} lifecycle_state={report.lifecycle_state} "
            f"active_map_id={report.active_map_id} "
            f"generation_chain={report.generation_chain_integrity_status} "
            f"source_freshness={report.source_freshness_state} "
            f"reasons={','.join(report.overall_health_reason_codes)}"
        )
        sys.stdout.flush()


def _print_finished(*, reports: list[LedgerHealthReport], output: str, elapsed: float) -> None:
    healthy = sum(1 for report in reports if report.overall_health_status == OVERALL_HEALTH_HEALTHY)
    not_applicable = sum(
        1 for report in reports if report.overall_health_status == OVERALL_HEALTH_NOT_APPLICABLE
    )
    needs_review = sum(
        1
        for report in reports
        if report.overall_health_status not in (OVERALL_HEALTH_HEALTHY, OVERALL_HEALTH_NOT_APPLICABLE)
    )
    failed = sum(1 for report in reports if report.status == STATUS_FAILED)
    event = "FINISHED" if failed == 0 else "FAILED"
    summary = {
        "event": event,
        "runner": RUNNER_NAME,
        "requested": len(reports),
        "healthy": healthy,
        "not_applicable": not_applicable,
        "needs_review": needs_review,
        "failed": failed,
        "elapsed_seconds": round(elapsed, 3),
    }
    if output == "jsonl":
        emit_json(summary)
    else:
        print(
            f"{event} runner={RUNNER_NAME} requested={len(reports)} healthy={healthy} "
            f"not_applicable={not_applicable} needs_review={needs_review} failed={failed} "
            f"elapsed={elapsed:.3f}s"
        )
        sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        symbols = parse_symbols(args.symbols)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    started_monotonic = time.monotonic()
    _print_started(args=args, symbols=symbols)

    reports: list[LedgerHealthReport] = []
    for symbol in symbols:
        generated_at_utc = datetime.now(UTC)
        try:
            conn = get_connection()
        except Exception as exc:
            report = failed_report(
                venue=args.venue,
                symbol=symbol,
                quote_currency=args.quote_currency,
                fib_trading_horizon=args.fib_trading_horizon,
                primary_interval=args.primary_interval,
                supporting_interval=args.supporting_interval,
                generated_at_utc=generated_at_utc,
                exc=exc,
            )
            reports.append(report)
            _emit_result(report, output=args.output)
            continue

        try:
            report = generate_report_for_symbol(
                conn,
                venue=args.venue,
                symbol=symbol,
                quote_currency=args.quote_currency,
                fib_trading_horizon=args.fib_trading_horizon,
                primary_interval=args.primary_interval,
                supporting_interval=args.supporting_interval,
                generated_at_utc=generated_at_utc,
            )
        except Exception as exc:
            report = failed_report(
                venue=args.venue,
                symbol=symbol,
                quote_currency=args.quote_currency,
                fib_trading_horizon=args.fib_trading_horizon,
                primary_interval=args.primary_interval,
                supporting_interval=args.supporting_interval,
                generated_at_utc=generated_at_utc,
                exc=exc,
            )
        finally:
            conn.rollback()
            conn.close()

        reports.append(report)
        _emit_result(report, output=args.output)
        if report.status == STATUS_FAILED:
            print(f"FAILED {symbol}: {report.detail}", file=sys.stderr)

    elapsed = time.monotonic() - started_monotonic
    _print_finished(reports=reports, output=args.output, elapsed=elapsed)
    return 0 if all(report.status != STATUS_FAILED for report in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
