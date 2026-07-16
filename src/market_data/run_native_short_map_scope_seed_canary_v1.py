from __future__ import annotations

"""Manual market-only native SHORT map scope seed canary.

Reads venue_market + asset for eligibility, reads native_short_map_scope_v1
for existing canonical scope rows, and inserts at most one exact SUPPORTED
scope row in explicit --write mode. Never updates, deletes, or overwrites.

Result statuses:
- planned: dry-run only; the canonical SUPPORTED row would be inserted.
- seeded:  write mode only; the canonical SUPPORTED row was inserted and committed.
- skipped: an identical canonical SUPPORTED row (NULL reason fields) already exists.
- failed:  ineligible market, ambiguous canonical rows, conflicting scope row,
           or an execution error; nothing was written.

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
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from typing import Any

from src.common.db import get_connection
from src.market_data.native_short_map_lifecycle_v1 import (
    DEFAULT_FIB_TRADING_HORIZON,
    DEFAULT_PRIMARY_INTERVAL,
    DEFAULT_QUOTE_CURRENCY,
    DEFAULT_SUPPORTING_INTERVAL,
)
from src.market_data.native_short_scope_status_materializer_v1 import (
    NativeShortRunBuilder,
    _finalize_run,
    _insert_run,
)
from src.market_data.native_short_writer_provenance_v1 import (
    MANUAL_SCOPE_SEED_TRIGGER_TYPE,
    NativeShortWriterExecutionMode,
    NativeShortWriterProvenance,
    NativeShortWriterProvenanceError,
    build_process_provenance,
    validate_native_short_writer_provenance,
)


RUNNER_NAME = "native_short_map_scope_seed_canary_v1"
RUNNER_VERSION = "0.2"
DEFAULT_VENUE = "bitvavo"
SUPPORTED_STATE = "SUPPORTED"
EXPECTED_REASON_CODE = None
EXPECTED_REASON_DETAIL = None

STATUS_PLANNED = "planned"
STATUS_SEEDED = "seeded"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"

REASON_VENUE_MARKET_NOT_FOUND = "VENUE_MARKET_NOT_FOUND"
REASON_AMBIGUOUS_VENUE_MARKET = "AMBIGUOUS_VENUE_MARKET"
REASON_MARKET_DATA_NOT_ENABLED = "MARKET_DATA_NOT_ENABLED"
REASON_MARKET_NOT_TRADEABLE = "MARKET_NOT_TRADEABLE"
REASON_ASSET_NOT_ENABLED = "ASSET_NOT_ENABLED"
REASON_AMBIGUOUS_SCOPE = "AMBIGUOUS_SCOPE"
REASON_SCOPE_CONFLICT = "SCOPE_CONFLICT"
REASON_SCOPE_ALREADY_SUPPORTED = "SCOPE_ALREADY_SUPPORTED"


@dataclass(frozen=True)
class ScopeSeedPlan:
    symbol: str
    venue: str
    market: str
    quote_currency: str
    fib_trading_horizon: str
    primary_interval: str
    supporting_interval: str
    eligible: bool
    status: str
    reason_code: str | None = None
    detail: str | None = None


def parse_symbols(text: str) -> list[str]:
    symbols = sorted({part.strip().upper() for part in text.split(",") if part.strip()})
    if not symbols:
        raise ValueError("--symbols must contain at least one symbol")
    return symbols


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Manual market-only canary for seeding native_short_map_scope_v1. "
            "Defaults to dry-run. Use --write with exactly one symbol for the "
            "explicit mutation path."
        )
    )
    parser.add_argument(
        "--symbols",
        required=True,
        help=(
            "Explicit comma-separated base symbols, e.g. BTC or BTC,ETH. "
            "--write accepts exactly one symbol."
        ),
    )
    parser.add_argument("--venue", choices=(DEFAULT_VENUE,), default=DEFAULT_VENUE)
    parser.add_argument("--quote-currency", choices=(DEFAULT_QUOTE_CURRENCY,), default=DEFAULT_QUOTE_CURRENCY)
    parser.add_argument("--write", action="store_true", help="Insert the canonical SUPPORTED scope row.")
    parser.add_argument("--output", choices=("jsonl", "summary"), default="jsonl")
    parser.add_argument(
        "--execution-mode",
        required=True,
        choices=(NativeShortWriterExecutionMode.MANUAL.value,),
    )
    parser.add_argument("--repository-commit", required=True)
    parser.add_argument("--trigger-ref", required=True)
    return parser.parse_args(argv)


def _market_code(symbol: str, quote_currency: str) -> str:
    return f"{symbol}-{quote_currency}"


def _flag_is_enabled(value: Any) -> bool:
    """Strict TINYINT(1) truth: only int/bool 1 counts. NULL/missing/other fail closed."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 1
    return False


def fetch_market_rows(
    conn: Any,
    *,
    venue: str,
    symbol: str,
    quote_currency: str,
) -> list[dict[str, Any]]:
    sql = """
    SELECT
        vm.venue_market_id,
        vm.venue,
        vm.market,
        a.symbol,
        vm.quote_currency,
        vm.is_market_data_enabled,
        vm.is_tradeable,
        a.is_enabled
    FROM venue_market vm
    JOIN asset a
      ON a.asset_id = vm.base_asset_id
    WHERE vm.venue = %s
      AND vm.market = %s
      AND vm.quote_currency = %s
      AND a.symbol = %s
    ORDER BY vm.venue_market_id ASC
    """
    with conn.cursor() as cur:
        cur.execute(sql, (venue, _market_code(symbol, quote_currency), quote_currency, symbol))
        rows = cur.fetchall()
    return [dict(row) for row in rows]


def fetch_scope_rows(
    conn: Any,
    *,
    venue: str,
    symbol: str,
    quote_currency: str,
    for_update: bool,
) -> list[dict[str, Any]]:
    lock_sql = " FOR UPDATE" if for_update else ""
    sql = f"""
    SELECT
        scope_id,
        venue,
        symbol,
        quote_currency,
        fib_trading_horizon,
        primary_interval,
        supporting_interval,
        scope_support_state,
        scope_reason_code,
        scope_reason_detail
    FROM native_short_map_scope_v1
    WHERE venue = %s
      AND symbol = %s
      AND quote_currency = %s
      AND fib_trading_horizon = %s
      AND primary_interval = %s
      AND supporting_interval = %s
    ORDER BY scope_id ASC{lock_sql}
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                venue,
                symbol,
                quote_currency,
                DEFAULT_FIB_TRADING_HORIZON,
                DEFAULT_PRIMARY_INTERVAL,
                DEFAULT_SUPPORTING_INTERVAL,
            ),
        )
        rows = cur.fetchall()
    return [dict(row) for row in rows]


def _market_ineligibility_reason(row: dict[str, Any]) -> tuple[str, str] | None:
    if not _flag_is_enabled(row.get("is_market_data_enabled")):
        return (
            REASON_MARKET_DATA_NOT_ENABLED,
            "venue_market.is_market_data_enabled is not 1",
        )
    if not _flag_is_enabled(row.get("is_tradeable")):
        return (
            REASON_MARKET_NOT_TRADEABLE,
            "venue_market.is_tradeable is not 1",
        )
    if not _flag_is_enabled(row.get("is_enabled")):
        return (
            REASON_ASSET_NOT_ENABLED,
            "asset.is_enabled is not 1",
        )
    return None


def _identical_supported_scope(row: dict[str, Any]) -> bool:
    return (
        row.get("scope_support_state") == SUPPORTED_STATE
        and row.get("scope_reason_code") is EXPECTED_REASON_CODE
        and row.get("scope_reason_detail") is EXPECTED_REASON_DETAIL
    )


def build_scope_seed_plan(
    conn: Any,
    *,
    venue: str,
    symbol: str,
    quote_currency: str = DEFAULT_QUOTE_CURRENCY,
    for_update: bool = False,
) -> ScopeSeedPlan:
    def _plan(
        *,
        eligible: bool,
        status: str,
        reason_code: str | None = None,
        detail: str | None = None,
    ) -> ScopeSeedPlan:
        return ScopeSeedPlan(
            symbol=symbol,
            venue=venue,
            market=_market_code(symbol, quote_currency),
            quote_currency=quote_currency,
            fib_trading_horizon=DEFAULT_FIB_TRADING_HORIZON,
            primary_interval=DEFAULT_PRIMARY_INTERVAL,
            supporting_interval=DEFAULT_SUPPORTING_INTERVAL,
            eligible=eligible,
            status=status,
            reason_code=reason_code,
            detail=detail,
        )

    market_rows = fetch_market_rows(
        conn,
        venue=venue,
        symbol=symbol,
        quote_currency=quote_currency,
    )
    if not market_rows:
        return _plan(
            eligible=False,
            status=STATUS_FAILED,
            reason_code=REASON_VENUE_MARKET_NOT_FOUND,
            detail="no canonical venue_market row for requested venue/market/quote/symbol",
        )
    if len(market_rows) > 1:
        return _plan(
            eligible=False,
            status=STATUS_FAILED,
            reason_code=REASON_AMBIGUOUS_VENUE_MARKET,
            detail=f"expected exactly one canonical venue_market row, found {len(market_rows)}",
        )

    ineligibility = _market_ineligibility_reason(market_rows[0])
    if ineligibility is not None:
        reason_code, detail = ineligibility
        return _plan(
            eligible=False,
            status=STATUS_FAILED,
            reason_code=reason_code,
            detail=detail,
        )

    scope_rows = fetch_scope_rows(
        conn,
        venue=venue,
        symbol=symbol,
        quote_currency=quote_currency,
        for_update=for_update,
    )
    if len(scope_rows) > 1:
        return _plan(
            eligible=True,
            status=STATUS_FAILED,
            reason_code=REASON_AMBIGUOUS_SCOPE,
            detail=f"expected at most one canonical scope row, found {len(scope_rows)}",
        )
    if not scope_rows:
        return _plan(eligible=True, status=STATUS_PLANNED)

    existing = scope_rows[0]
    if _identical_supported_scope(existing):
        return _plan(
            eligible=True,
            status=STATUS_SKIPPED,
            reason_code=REASON_SCOPE_ALREADY_SUPPORTED,
            detail="identical canonical SUPPORTED scope row already exists",
        )
    return _plan(
        eligible=True,
        status=STATUS_FAILED,
        reason_code=REASON_SCOPE_CONFLICT,
        detail=(
            "existing native_short_map_scope_v1 row is not the exact canonical "
            "SUPPORTED row with NULL reason fields"
        ),
    )


def insert_scope_row(
    conn: Any,
    plan: ScopeSeedPlan,
    *,
    provenance: NativeShortWriterProvenance,
) -> None:
    validate_native_short_writer_provenance(provenance)
    sql = """
    INSERT INTO native_short_map_scope_v1 (
        venue,
        symbol,
        quote_currency,
        fib_trading_horizon,
        primary_interval,
        supporting_interval,
        scope_support_state,
        scope_reason_code,
        scope_reason_detail,
        writer_invocation_uuid
    ) VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
    )
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                plan.venue,
                plan.symbol,
                plan.quote_currency,
                plan.fib_trading_horizon,
                plan.primary_interval,
                plan.supporting_interval,
                SUPPORTED_STATE,
                EXPECTED_REASON_CODE,
                EXPECTED_REASON_DETAIL,
                provenance.invocation_uuid,
            ),
        )


def _failed_plan(*, symbol: str, venue: str, quote_currency: str, exc: Exception) -> ScopeSeedPlan:
    return ScopeSeedPlan(
        symbol=symbol,
        venue=venue,
        market=_market_code(symbol, quote_currency),
        quote_currency=quote_currency,
        fib_trading_horizon=DEFAULT_FIB_TRADING_HORIZON,
        primary_interval=DEFAULT_PRIMARY_INTERVAL,
        supporting_interval=DEFAULT_SUPPORTING_INTERVAL,
        eligible=False,
        status=STATUS_FAILED,
        reason_code=type(exc).__name__,
        detail=str(exc),
    )


def run_dry_run_symbol(conn: Any, *, venue: str, symbol: str, quote_currency: str) -> ScopeSeedPlan:
    """Read-only evaluation. Never begins, commits, or rolls back a transaction."""
    return build_scope_seed_plan(
        conn,
        venue=venue,
        symbol=symbol,
        quote_currency=quote_currency,
        for_update=False,
    )


def run_write_symbol(
    conn: Any,
    *,
    venue: str,
    symbol: str,
    quote_currency: str,
    provenance: NativeShortWriterProvenance,
) -> ScopeSeedPlan:
    """Single-transaction explicit write for exactly one accepted symbol."""
    validate_native_short_writer_provenance(provenance)
    conn.begin()
    try:
        plan = build_scope_seed_plan(
            conn,
            venue=venue,
            symbol=symbol,
            quote_currency=quote_currency,
            for_update=True,
        )
        if plan.status == STATUS_PLANNED:
            builder = NativeShortRunBuilder(
                provenance=provenance,
                contract_version="native_short_map_scope_v1",
                started_at_utc=datetime.now(UTC),
                requested_scope_count=1,
            )
            run_id = _insert_run(conn, builder.started_record())
            insert_scope_row(conn, plan, provenance=provenance)
            builder.record_scope_outcome()
            _finalize_run(conn, run_id, builder.finish(finished_at_utc=datetime.now(UTC)))
            conn.commit()
            return replace(plan, status=STATUS_SEEDED)
        conn.rollback()
        return plan
    except Exception:
        conn.rollback()
        raise


def emit_result(plan: ScopeSeedPlan, *, output: str, write: bool) -> None:
    payload = {
        "event": "RESULT",
        "runner": RUNNER_NAME,
        "runner_version": RUNNER_VERSION,
        "dry_run": not write,
        "write": write,
        **asdict(plan),
    }
    if output == "jsonl":
        print(json.dumps(payload, sort_keys=True))
    else:
        reason = f" reason={plan.reason_code}" if plan.reason_code else ""
        print(f"{plan.status.upper()} symbol={plan.symbol} market={plan.market} eligible={plan.eligible}{reason}")
    sys.stdout.flush()


def _print_started(*, symbols: list[str], write: bool, output: str) -> None:
    payload = {
        "event": "STARTED",
        "runner": RUNNER_NAME,
        "runner_version": RUNNER_VERSION,
        "venue": DEFAULT_VENUE,
        "quote_currency": DEFAULT_QUOTE_CURRENCY,
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
    }
    if output == "jsonl":
        print(json.dumps(payload, sort_keys=True))
    else:
        print(f"STARTED runner={RUNNER_NAME} version={RUNNER_VERSION}")
        print(f"venue={DEFAULT_VENUE} quote_currency={DEFAULT_QUOTE_CURRENCY} symbols={','.join(symbols)}")
        print(f"dry_run={not write} write={write}")
        print("broker_private_calls=0")
        print("broker_writes=0")
        print("order_submission=0")
        print("live_orders=0")
        print("decision_gate=none")
        print("execution_planner=none")
        print("executor=none")
    sys.stdout.flush()


def _print_finished(*, plans: list[ScopeSeedPlan], write: bool, output: str) -> None:
    planned = sum(1 for plan in plans if plan.status == STATUS_PLANNED)
    seeded = sum(1 for plan in plans if plan.status == STATUS_SEEDED)
    skipped = sum(1 for plan in plans if plan.status == STATUS_SKIPPED)
    failed = sum(1 for plan in plans if plan.status == STATUS_FAILED)
    event = "FINISHED" if failed == 0 else "FAILED"
    payload = {
        "event": event,
        "runner": RUNNER_NAME,
        "dry_run": not write,
        "write": write,
        "requested": len(plans),
        "planned": planned,
        "seeded": seeded,
        "skipped": skipped,
        "failed": failed,
    }
    if output == "jsonl":
        print(json.dumps(payload, sort_keys=True))
    else:
        print(
            f"{event} runner={RUNNER_NAME} requested={len(plans)} "
            f"planned={planned} seeded={seeded} skipped={skipped} failed={failed}"
        )
    sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    write = bool(args.write)

    try:
        symbols = parse_symbols(args.symbols)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if write and len(symbols) != 1:
        print(
            f"ERROR: --write requires exactly one explicit symbol; parsed {len(symbols)}",
            file=sys.stderr,
        )
        return 2

    try:
        provenance = build_process_provenance(
            writer_entrypoint="src.market_data.run_native_short_map_scope_seed_canary_v1",
            runner_name=RUNNER_NAME,
            runner_version=RUNNER_VERSION,
            execution_mode=args.execution_mode,
            repository_commit_sha=args.repository_commit,
            trigger_type=MANUAL_SCOPE_SEED_TRIGGER_TYPE,
            trigger_ref=args.trigger_ref,
        )
    except NativeShortWriterProvenanceError as exc:
        print(f"INVALID_PROVENANCE runner={RUNNER_NAME} detail={exc}", file=sys.stderr)
        return 2

    _print_started(symbols=symbols, write=write, output=args.output)

    plans: list[ScopeSeedPlan] = []
    for symbol in symbols:
        try:
            conn = get_connection()
        except Exception as exc:
            plan = _failed_plan(
                symbol=symbol,
                venue=args.venue,
                quote_currency=args.quote_currency,
                exc=exc,
            )
            plans.append(plan)
            emit_result(plan, output=args.output, write=write)
            continue
        try:
            if write:
                plan = run_write_symbol(
                    conn,
                    venue=args.venue,
                    symbol=symbol,
                    quote_currency=args.quote_currency,
                    provenance=provenance,
                )
            else:
                plan = run_dry_run_symbol(
                    conn,
                    venue=args.venue,
                    symbol=symbol,
                    quote_currency=args.quote_currency,
                )
        except Exception as exc:
            plan = _failed_plan(
                symbol=symbol,
                venue=args.venue,
                quote_currency=args.quote_currency,
                exc=exc,
            )
        finally:
            conn.close()
        plans.append(plan)
        emit_result(plan, output=args.output, write=write)

    _print_finished(plans=plans, write=write, output=args.output)
    return 0 if all(plan.status != STATUS_FAILED for plan in plans) else 1


if __name__ == "__main__":
    raise SystemExit(main())
