from __future__ import annotations

"""Manual native SHORT map ledger materializer canary.

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
import time
from collections import defaultdict
from datetime import UTC, datetime
from datetime import timedelta
from decimal import Decimal
from typing import Any

from src.common.db import get_connection
from src.market_data.native_short_fib_context_v1 import (
    STATUS_SYMBOL_MISSING,
    Candle,
    NativeShortContextRow,
    build_native_short_context_row,
)
from src.market_data.native_short_map_lifecycle_v1 import (
    DEFAULT_FIB_TRADING_HORIZON,
    DEFAULT_PRIMARY_INTERVAL,
    DEFAULT_QUOTE_CURRENCY,
    DEFAULT_SUPPORTING_INTERVAL,
    NativeShortMapScopeSupport,
)
from src.market_data.native_short_map_materializer_v1 import (
    GENERATOR_NAME,
    GENERATOR_VERSION,
    ScopeMaterializationResult,
    fetch_supported_scopes,
    materialize_scope_symbol,
)

RUNNER_NAME = "run_native_short_map_materializer_v1"
RUNNER_VERSION = "0.1"
DEFAULT_VENUE = "bitvavo"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Manual native SHORT map ledger materializer canary. "
            "Defaults to dry-run. Use --write for explicit DB writes."
        )
    )
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument(
        "--symbols",
        required=True,
        help="Comma-separated symbols, e.g. BTC or BTC,ETH.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Explicitly write native_short_map_v1 ledger rows. Omit for dry-run.",
    )
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


def _missing_scope_result(symbol: str, *, write: bool) -> ScopeMaterializationResult:
    return ScopeMaterializationResult(
        symbol=symbol,
        attempted=False,
        status="skipped",
        dry_run=not write,
        reason_code="SCOPE_NOT_FOUND_OR_NOT_SUPPORTED",
        detail="native_short_map_scope_v1 requires a SUPPORTED row for this scope",
    )


def _failed_result(symbol: str, *, write: bool, exc: Exception) -> ScopeMaterializationResult:
    return ScopeMaterializationResult(
        symbol=symbol,
        attempted=True,
        status="failed",
        dry_run=not write,
        reason_code=type(exc).__name__,
        detail=str(exc),
    )


def _ambiguous_scope_result(symbol: str, *, write: bool, count: int) -> ScopeMaterializationResult:
    return ScopeMaterializationResult(
        symbol=symbol,
        attempted=False,
        status="failed",
        dry_run=not write,
        reason_code="AMBIGUOUS_SCOPE",
        detail=f"expected exactly one canonical SUPPORTED scope row, found {count}",
    )


def _canonical_scope_by_symbol(
    *,
    symbols: list[str],
    scopes: list[NativeShortMapScopeSupport],
    write: bool,
) -> tuple[dict[str, NativeShortMapScopeSupport], list[ScopeMaterializationResult]]:
    grouped: dict[str, list[NativeShortMapScopeSupport]] = {symbol: [] for symbol in symbols}
    for scope in scopes:
        grouped.setdefault(scope.key.symbol, []).append(scope)

    resolved: dict[str, NativeShortMapScopeSupport] = {}
    results: list[ScopeMaterializationResult] = []
    for symbol in symbols:
        matches = grouped.get(symbol, [])
        if len(matches) == 1:
            resolved[symbol] = matches[0]
        elif not matches:
            results.append(_missing_scope_result(symbol, write=write))
        else:
            results.append(_ambiguous_scope_result(symbol, write=write, count=len(matches)))
    return resolved, results


def _fetch_candles_by_symbol(
    *,
    conn: Any,
    venue: str,
    interval_code: str,
    symbols: list[str],
    since_utc: datetime,
) -> dict[str, list[Candle]]:
    if not symbols:
        return {}
    placeholders = ",".join(["%s"] * len(symbols))
    sql = f"""
    SELECT
        a.symbol,
        c.close_ts_utc,
        c.open_price,
        c.high_price,
        c.low_price,
        c.close_price
    FROM obs_market_candle c
    JOIN asset a
      ON a.asset_id = c.asset_id
    WHERE c.venue = %s
      AND c.interval_code = %s
      AND a.symbol IN ({placeholders})
      AND c.close_ts_utc >= %s
    ORDER BY a.symbol ASC, c.close_ts_utc ASC
    """
    with conn.cursor() as cur:
        cur.execute(sql, (venue, interval_code, *symbols, since_utc))
        rows = list(cur.fetchall())

    grouped: dict[str, list[Candle]] = defaultdict(list)
    for row in rows:
        symbol = str(row.get("symbol") or "").upper()
        close_ts = row.get("close_ts_utc")
        if not symbol or close_ts is None:
            continue
        close_ts_utc = close_ts.replace(tzinfo=UTC) if close_ts.tzinfo is None else close_ts.astimezone(UTC)
        grouped[symbol].append(
            Candle(
                close_ts_utc=close_ts_utc,
                open_price=Decimal(str(row["open_price"])),
                high_price=Decimal(str(row["high_price"])),
                low_price=Decimal(str(row["low_price"])),
                close_price=Decimal(str(row["close_price"])),
            )
        )
    return grouped


def build_rows_for_symbols(
    *,
    venue: str,
    symbols: list[str],
    now_utc: datetime,
) -> list[NativeShortContextRow]:
    primary_since = now_utc - timedelta(days=60)
    support_since = now_utc - timedelta(days=21)
    conn = get_connection()
    try:
        primary_by_symbol = _fetch_candles_by_symbol(
            conn=conn,
            venue=venue,
            interval_code=DEFAULT_PRIMARY_INTERVAL,
            symbols=symbols,
            since_utc=primary_since,
        )
        support_by_symbol = _fetch_candles_by_symbol(
            conn=conn,
            venue=venue,
            interval_code=DEFAULT_SUPPORTING_INTERVAL,
            symbols=symbols,
            since_utc=support_since,
        )
    finally:
        conn.close()

    rows: list[NativeShortContextRow] = []
    for symbol in symbols:
        primary = primary_by_symbol.get(symbol, [])
        support = support_by_symbol.get(symbol, [])
        row = build_native_short_context_row(
            symbol=symbol,
            venue=venue,
            primary_candles=primary,
            support_candles=support,
            now_utc=now_utc,
        )
        if not primary and not support:
            row = NativeShortContextRow(
                **{
                    **row.__dict__,
                    "context_status": STATUS_SYMBOL_MISSING,
                }
            )
        rows.append(row)
    return rows


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        symbols = parse_symbols(args.symbols)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    write = bool(args.write)
    if write and len(symbols) != 1:
        print(
            f"ERROR: --write requires exactly one symbol; parsed {len(symbols)}",
            file=sys.stderr,
        )
        return 2

    now_utc = datetime.now(UTC)
    started_monotonic = time.monotonic()

    if args.output == "jsonl":
        emit_json(
            {
                "event": "STARTED",
                "runner": RUNNER_NAME,
                "runner_version": RUNNER_VERSION,
                "generator_name": GENERATOR_NAME,
                "generator_version": GENERATOR_VERSION,
                "venue": args.venue,
                "symbols": symbols,
                "dry_run": not write,
                "write": write,
                "broker_private_calls": 0,
                "broker_writes": 0,
                "order_submission": 0,
                "live_orders": 0,
                "decision_gate": "none",
                "execution_planner": "none",
                "executor": "none",
                "started_at_utc": now_utc,
            }
        )
    else:
        print(f"STARTED runner={RUNNER_NAME} version={RUNNER_VERSION}")
        print(f"venue={args.venue} symbols={','.join(symbols)} dry_run={not write} write={write}")
        print("broker_private_calls=0")
        print("broker_writes=0")
        print("order_submission=0")
        print("live_orders=0")
        print("decision_gate=none")
        print("execution_planner=none")
        print("executor=none")
        sys.stdout.flush()

    scope_conn = get_connection()
    try:
        scopes = fetch_supported_scopes(
            scope_conn,
            venue=args.venue,
            symbols=symbols,
            quote_currency=DEFAULT_QUOTE_CURRENCY,
            fib_trading_horizon=DEFAULT_FIB_TRADING_HORIZON,
            primary_interval=DEFAULT_PRIMARY_INTERVAL,
            supporting_interval=DEFAULT_SUPPORTING_INTERVAL,
        )
    finally:
        scope_conn.close()
    scopes_by_symbol, scope_results = _canonical_scope_by_symbol(
        symbols=symbols,
        scopes=scopes,
        write=write,
    )

    context_rows = build_rows_for_symbols(
        venue=args.venue,
        symbols=[symbol for symbol in symbols if symbol in scopes_by_symbol],
        now_utc=now_utc,
    )
    context_by_symbol = {row.symbol: row for row in context_rows}

    results: list[ScopeMaterializationResult] = []
    for result in scope_results:
        results.append(result)
        if args.output == "jsonl":
            emit_json({"event": "RESULT", **result.to_json_dict()})
        else:
            print(f"{result.status.upper()} {result.symbol} reason={result.reason_code}")

    for symbol in symbols:
        scope = scopes_by_symbol.get(symbol)
        if scope is None:
            continue

        context_row = context_by_symbol.get(symbol)
        if context_row is None:
            result = ScopeMaterializationResult(
                symbol=symbol,
                attempted=False,
                status="skipped",
                dry_run=not write,
                reason_code="CONTEXT_ROW_MISSING",
            )
            results.append(result)
            if args.output == "jsonl":
                emit_json({"event": "RESULT", **result.to_json_dict()})
            else:
                print(f"SKIPPED {symbol} reason={result.reason_code}")
            continue

        conn = get_connection()
        try:
            if write:
                conn.begin()
            result = materialize_scope_symbol(
                conn,
                scope_support=scope,
                context_row=context_row,
                now_utc=now_utc,
                write=write,
            )
            if write:
                conn.commit()
            else:
                conn.rollback()
        except Exception as exc:
            conn.rollback()
            result = _failed_result(symbol, write=write, exc=exc)
        finally:
            conn.close()

        results.append(result)
        if args.output == "jsonl":
            emit_json({"event": "RESULT", **result.to_json_dict()})
        else:
            print(
                f"{result.status.upper()} {symbol} attempted={result.attempted} "
                f"map_id={result.map_id} generation_attempt_id={result.generation_attempt_id} "
                f"reason={result.reason_code}"
            )
        if result.status == "failed":
            print(f"FAILED {symbol}: {result.detail}", file=sys.stderr)

    elapsed = time.monotonic() - started_monotonic
    attempted = sum(1 for result in results if result.attempted)
    published = sum(1 for result in results if result.status == "published")
    skipped = sum(1 for result in results if result.status == "skipped")
    failed = sum(1 for result in results if result.status == "failed")
    summary = {
        "event": "FINISHED" if failed == 0 else "FAILED",
        "runner": RUNNER_NAME,
        "attempted": attempted,
        "published": published,
        "skipped": skipped,
        "failed": failed,
        "dry_run": not write,
        "write": write,
        "elapsed_seconds": round(elapsed, 3),
    }
    if args.output == "jsonl":
        emit_json(summary)
    else:
        print(
            f"{summary['event']} runner={RUNNER_NAME} attempted={attempted} "
            f"published={published} skipped={skipped} failed={failed} "
            f"elapsed={elapsed:.3f}s"
        )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
