from __future__ import annotations

"""Bounded runner for the native SHORT map-level status materializer.

Safety markers:
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
"""

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Callable

from src.common.db import get_connection
from src.market_data.native_short_map_level_status_materializer_v1 import (
    BLOCKED,
    GEOMETRY_INVALID,
    NO_CURRENT_MAP,
    PROJECTION_INVALID,
    PROJECTION_MISSING,
    MapLevelStatusMaterializationOutcome,
    materialize_native_short_map_level_status_for_scope,
)
from src.market_data.native_short_map_lifecycle_v1 import NativeShortMapScopeKey


RUNNER_NAME = "run_native_short_map_level_status_materializer_v1"
RUNNER_VERSION = "0.1"
EXPECTED_LEVEL_ROW_COUNT = 3

SAFETY_MARKERS: dict[str, int | str] = {
    "broker_private_calls": 0,
    "broker_writes": 0,
    "order_submission": 0,
    "live_orders": 0,
    "decision_gate": "none",
    "execution_planner": "none",
    "executor": "none",
}


@dataclass(frozen=True)
class ScopeRunResult:
    venue: str
    symbol: str
    quote_currency: str
    fib_trading_horizon: str
    primary_interval: str
    supporting_interval: str
    status: str
    branch: str | None
    reason_code: str | None
    detail: str | None
    row_count: int
    current_map_id: int | None
    map_cycle_id: str | None
    level_status_as_of_utc: datetime | None


def _required_text(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise argparse.ArgumentTypeError("value must not be empty")
    return normalized


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Atomically rebuild native SHORT map-level status rows for an "
            "explicit full market-data scope."
        )
    )
    parser.add_argument("--venue", required=True, type=_required_text)
    parser.add_argument(
        "--symbols",
        required=True,
        type=_required_text,
        help="Explicit comma-separated symbols, e.g. BTC or BTC,ETH.",
    )
    parser.add_argument("--quote-currency", required=True, type=_required_text)
    parser.add_argument("--fib-trading-horizon", required=True, type=_required_text)
    parser.add_argument("--primary-interval", required=True, type=_required_text)
    parser.add_argument("--supporting-interval", required=True, type=_required_text)
    parser.add_argument(
        "--output",
        choices=("jsonl", "summary"),
        default="jsonl",
        help="jsonl emits one deterministic machine-readable record per event/result.",
    )
    return parser.parse_args(argv)


def parse_symbols(text: str) -> list[str]:
    symbols = sorted({part.strip().upper() for part in text.split(",") if part.strip()})
    if not symbols:
        raise ValueError("--symbols must contain at least one explicit symbol")
    return symbols


def utc_now() -> datetime:
    """Operational metadata clock; never used as materializer semantic time."""
    return datetime.now(UTC)


def _blocked_detail(reason_code: str | None) -> str:
    if reason_code == PROJECTION_MISSING:
        return "scope projection row missing; no level-status rows emitted"
    if reason_code == PROJECTION_INVALID:
        return "selected map missing or projection/map identity invalid; no level-status rows emitted"
    if reason_code == NO_CURRENT_MAP:
        return "selected map missing from scope projection; no level-status rows emitted"
    if reason_code == GEOMETRY_INVALID:
        return "selected map geometry invalid; no level-status rows emitted"
    return f"unsupported scope state blocks row emission: {reason_code or 'UNKNOWN'}"


def _result_from_outcome(outcome: MapLevelStatusMaterializationOutcome) -> ScopeRunResult:
    status = "materialized"
    detail = None
    reason_code = outcome.reason_code
    if outcome.branch == BLOCKED:
        status = "blocked"
        detail = _blocked_detail(reason_code)
    elif outcome.row_count != EXPECTED_LEVEL_ROW_COUNT:
        status = "failed"
        reason_code = "UNEXPECTED_ROW_COUNT"
        detail = (
            f"expected {EXPECTED_LEVEL_ROW_COUNT} level-status rows, "
            f"materializer reported {outcome.row_count}"
        )

    return ScopeRunResult(
        venue=outcome.key.venue,
        symbol=outcome.key.symbol,
        quote_currency=outcome.key.quote_currency,
        fib_trading_horizon=outcome.key.fib_trading_horizon,
        primary_interval=outcome.key.primary_interval,
        supporting_interval=outcome.key.supporting_interval,
        status=status,
        branch=outcome.branch,
        reason_code=reason_code,
        detail=detail,
        row_count=outcome.row_count,
        current_map_id=outcome.current_map_id,
        map_cycle_id=outcome.map_cycle_id,
        level_status_as_of_utc=outcome.level_status_as_of_utc,
    )


def _failed_result(key: NativeShortMapScopeKey, exc: Exception) -> ScopeRunResult:
    return ScopeRunResult(
        venue=key.venue,
        symbol=key.symbol,
        quote_currency=key.quote_currency,
        fib_trading_horizon=key.fib_trading_horizon,
        primary_interval=key.primary_interval,
        supporting_interval=key.supporting_interval,
        status="failed",
        branch=None,
        reason_code=type(exc).__name__,
        detail=str(exc),
        row_count=0,
        current_map_id=None,
        map_cycle_id=None,
        level_status_as_of_utc=None,
    )


def run_scope(
    *,
    key: NativeShortMapScopeKey,
    operational_clock: Callable[[], datetime],
) -> ScopeRunResult:
    conn = None
    try:
        conn = get_connection()
        conn.begin()
        outcome = materialize_native_short_map_level_status_for_scope(
            conn,
            key=key,
            operational_clock=operational_clock,
        )
        result = _result_from_outcome(outcome)
        if result.status == "failed":
            conn.rollback()
        else:
            # A blocked materialization deliberately deletes stale scope rows,
            # so its bounded cleanup must commit even though the CLI exits 1.
            conn.commit()
        return result
    except Exception as exc:
        if conn is not None:
            conn.rollback()
        return _failed_result(key, exc)
    finally:
        if conn is not None:
            conn.close()


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _emit_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True, default=_json_default))
    sys.stdout.flush()


def _scope_payload(args: argparse.Namespace, symbols: list[str]) -> dict[str, Any]:
    return {
        "venue": args.venue,
        "symbols": symbols,
        "quote_currency": args.quote_currency,
        "fib_trading_horizon": args.fib_trading_horizon,
        "primary_interval": args.primary_interval,
        "supporting_interval": args.supporting_interval,
    }


def _emit_started(args: argparse.Namespace, symbols: list[str]) -> None:
    scope = _scope_payload(args, symbols)
    if args.output == "jsonl":
        _emit_json(
            {
                "event": "STARTED",
                "runner": RUNNER_NAME,
                "runner_version": RUNNER_VERSION,
                **scope,
                **SAFETY_MARKERS,
            }
        )
        return

    print(f"STARTED runner={RUNNER_NAME} version={RUNNER_VERSION}")
    print(
        f"venue={args.venue} symbols={','.join(symbols)} "
        f"quote_currency={args.quote_currency} "
        f"fib_trading_horizon={args.fib_trading_horizon} "
        f"primary_interval={args.primary_interval} "
        f"supporting_interval={args.supporting_interval}"
    )
    for marker, value in SAFETY_MARKERS.items():
        print(f"{marker}={value}")
    sys.stdout.flush()


def _emit_result(result: ScopeRunResult, output: str) -> None:
    if output == "jsonl":
        _emit_json({"event": "RESULT", "runner": RUNNER_NAME, **asdict(result)})
        return

    reason = f" reason={result.reason_code}" if result.reason_code else ""
    detail = f" detail={result.detail}" if result.detail else ""
    print(
        f"{result.status.upper()} symbol={result.symbol} branch={result.branch} "
        f"rows={result.row_count}{reason}{detail}"
    )
    sys.stdout.flush()


def _emit_finished(results: list[ScopeRunResult], output: str) -> None:
    materialized = sum(result.status == "materialized" for result in results)
    blocked = sum(result.status == "blocked" for result in results)
    failed = sum(result.status == "failed" for result in results)
    event = "FINISHED" if blocked == 0 and failed == 0 else "FAILED"
    payload = {
        "event": event,
        "runner": RUNNER_NAME,
        "requested": len(results),
        "materialized": materialized,
        "blocked": blocked,
        "failed": failed,
    }
    if output == "jsonl":
        _emit_json(payload)
        return
    print(
        f"{event} runner={RUNNER_NAME} requested={len(results)} "
        f"materialized={materialized} blocked={blocked} failed={failed}"
    )
    sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        symbols = parse_symbols(args.symbols)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    _emit_started(args, symbols)
    results: list[ScopeRunResult] = []
    for symbol in symbols:
        key = NativeShortMapScopeKey(
            venue=args.venue,
            symbol=symbol,
            quote_currency=args.quote_currency,
            fib_trading_horizon=args.fib_trading_horizon,
            primary_interval=args.primary_interval,
            supporting_interval=args.supporting_interval,
        )
        result = run_scope(key=key, operational_clock=utc_now)
        results.append(result)
        _emit_result(result, args.output)
        if result.status != "materialized":
            print(
                f"{result.status.upper()} {symbol}: "
                f"{result.reason_code or 'UNKNOWN'}: {result.detail or ''}",
                file=sys.stderr,
            )

    _emit_finished(results, args.output)
    return 0 if all(result.status == "materialized" for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
