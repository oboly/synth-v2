"""
run_held_market_enrollment_v1 -- Enroll resolvable positive wallet holdings
(across every linked trading account) into the account-agnostic market/Fib
publication cohort (Issue #238 follow-up).

Root cause fixed by this enrollment step: ``asset.is_portfolio`` /
``asset.is_core_sensor`` gate both the canonical 4h Fib writer's tracked-
symbol cohort (``canonical_fib_zone_map_v1.fetch_tracked_symbols``) and the
Profit Plan's account-plan selection layer. A wallet-discovered held asset
(e.g. LIGHTER) can be flagged in the per-account ``account_asset`` table
without ever setting the market-wide ``asset.is_portfolio`` flag, leaving it
permanently excluded from the canonical Fib publication cohort even though it
has ample public candle history.

This script only ever flips ``asset.is_portfolio`` from 0 to 1 for an asset
that is resolvable (exact ``asset.symbol`` match, never a display alias),
enabled, and tradeable, and that is currently held with a positive balance in
at least one trading account. It never creates/edits venue_market or asset
identity rows, never touches account-scoped tables, and never invokes the
canonical Fib writer itself -- the already-scheduled writer picks up newly
enrolled symbols on its next run because it queries ``asset`` flags fresh
every cycle. This keeps the writer itself account-agnostic: the *only* new
input this script feeds it is a market-wide "this asset is portfolio-
relevant" boolean, computed once from cross-account holdings.

Dry run by default (default report only, no mutation). Mutation requires
--apply, --operator and --reason.

Safety markers:
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Sequence

from src.common.db import get_connection
from src.market_data.held_market_coverage_v1 import (
    SAFETY_MARKERS,
    AssetRegistryRow,
    HeldBalance,
    resolutions_needing_enrollment,
    resolve_held_markets,
)

RUNNER_NAME = "held_market_enrollment_v1"
RUNNER_VERSION = "0.1"
DEFAULT_VENUE = "bitvavo"
DEFAULT_QUOTE_CURRENCY = "EUR"


def emit(message: str) -> None:
    print(message, flush=True)


def fetch_latest_positive_balances(conn: Any, *, venue: str) -> list[HeldBalance]:
    sql = """
    WITH latest AS (
        SELECT trading_account_id, venue, MAX(snapshot_ts_utc) AS snapshot_ts_utc
        FROM trading_account_balance_snapshot
        WHERE venue = %s
        GROUP BY trading_account_id, venue
    )
    SELECT b.trading_account_id, ta.account_code, b.currency_code, b.total_amount
    FROM trading_account_balance_snapshot b
    JOIN latest l
      ON l.trading_account_id = b.trading_account_id
     AND l.venue = b.venue
     AND l.snapshot_ts_utc = b.snapshot_ts_utc
    JOIN trading_account ta
      ON ta.trading_account_id = b.trading_account_id
    WHERE b.venue = %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (venue, venue))
        rows = list(cur.fetchall())
    out: list[HeldBalance] = []
    for row in rows:
        total = row.get("total_amount")
        out.append(
            HeldBalance(
                trading_account_id=int(row["trading_account_id"]),
                account_code=str(row["account_code"]),
                currency_code=str(row["currency_code"] or ""),
                total_amount=Decimal(str(total)) if total is not None else Decimal("0"),
            )
        )
    return out


def fetch_asset_registry(conn: Any) -> dict[str, AssetRegistryRow]:
    sql = """
    SELECT asset_id, symbol, is_enabled, is_tradeable, is_portfolio, is_core_sensor
    FROM asset
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = list(cur.fetchall())
    out: dict[str, AssetRegistryRow] = {}
    for row in rows:
        symbol = str(row["symbol"]).upper()
        out[symbol] = AssetRegistryRow(
            asset_id=int(row["asset_id"]),
            symbol=symbol,
            is_enabled=bool(row.get("is_enabled")),
            is_tradeable=bool(row.get("is_tradeable")),
            is_portfolio=bool(row.get("is_portfolio")),
            is_core_sensor=bool(row.get("is_core_sensor")),
        )
    return out


def apply_enrollment(conn: Any, *, asset_id: int) -> bool:
    """Idempotent, guarded flip 0 -> 1. Never touches an asset already
    enrolled via is_portfolio or is_core_sensor. Returns True only when this
    call actually flipped the row (False means it was already enrolled by a
    concurrent run -- a no-op, not a failure)."""
    sql = """
    UPDATE asset
    SET is_portfolio = 1
    WHERE asset_id = %s
      AND is_portfolio = 0
      AND is_core_sensor = 0
    """
    with conn.cursor() as cur:
        cur.execute(sql, (asset_id,))
        return cur.rowcount == 1


@dataclass(frozen=True)
class EnrollmentOutcome:
    enrolled: tuple[str, ...]
    skipped_already_enrolled: tuple[str, ...]
    failed: tuple[dict[str, str], ...]


def apply_pending_enrollments(conn: Any, pending: Sequence[Any]) -> EnrollmentOutcome:
    """Apply each pending enrollment as its own committed unit.

    One row-per-commit (not one all-or-nothing transaction for the whole
    batch) is deliberate: a reconciliation job must make every successful
    enrollment durable even if a later symbol in the same run fails, and a
    retry of the same run must be a safe no-op for rows already applied.
    Every outcome -- enrolled, already-enrolled (race with a concurrent run),
    or failed -- is reported explicitly; nothing is silently dropped.
    """
    enrolled: list[str] = []
    skipped: list[str] = []
    failed: list[dict[str, str]] = []
    for resolution in pending:
        symbol = resolution.symbol or resolution.currency_code
        assert resolution.asset_id is not None
        try:
            flipped = apply_enrollment(conn, asset_id=resolution.asset_id)
            conn.commit()
        except Exception as exc:  # noqa: BLE001 -- must record every failure, never abort the batch
            try:
                conn.rollback()
            except Exception:
                pass
            failed.append({"symbol": symbol, "error": str(exc)})
            continue
        if flipped:
            enrolled.append(symbol)
        else:
            skipped.append(symbol)
    return EnrollmentOutcome(enrolled=tuple(enrolled), skipped_already_enrolled=tuple(skipped), failed=tuple(failed))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Enroll resolvable positive wallet holdings into the canonical "
            "market/Fib publication cohort by flipping asset.is_portfolio. "
            "Dry run by default."
        )
    )
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--quote-currency", default=DEFAULT_QUOTE_CURRENCY)
    parser.add_argument("--apply", action="store_true", help="Perform the UPDATE. Omit for a dry-run report only.")
    parser.add_argument("--operator", default=None, help="Required with --apply.")
    parser.add_argument("--reason", default=None, help="Required with --apply.")
    parser.add_argument("--output", choices=("summary", "json"), default="summary")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.apply and (not args.operator or not args.reason):
        print("[error] --apply requires --operator and --reason", file=sys.stderr)
        return 1

    started_ts = datetime.now(UTC)
    emit(
        f"STARTED {RUNNER_NAME} v{RUNNER_VERSION} venue={args.venue} "
        f"mode={'apply' if args.apply else 'dry_run'} ts={started_ts.isoformat()}"
    )

    conn = get_connection()
    try:
        balances = fetch_latest_positive_balances(conn, venue=args.venue)
        asset_registry_by_symbol = fetch_asset_registry(conn)
        resolutions = resolve_held_markets(
            held_balances=balances,
            quote_currency=args.quote_currency,
            asset_registry_by_symbol=asset_registry_by_symbol,
        )
        pending = resolutions_needing_enrollment(resolutions)

        outcome = EnrollmentOutcome(enrolled=(), skipped_already_enrolled=(), failed=())
        if args.apply:
            outcome = apply_pending_enrollments(conn, pending)
    finally:
        conn.close()

    non_resolvable = [r for r in resolutions if not r.resolvable]

    summary = {
        "report": RUNNER_NAME,
        "version": RUNNER_VERSION,
        "generated_ts_utc": started_ts.isoformat(),
        "mode": "apply" if args.apply else "dry_run",
        "operator": args.operator,
        "reason": args.reason,
        "held_symbol_count": len(resolutions),
        "already_enrolled_count": sum(1 for r in resolutions if r.resolvable and not r.needs_enrollment),
        "needs_enrollment_count": len(pending),
        "enrolled_this_run": list(outcome.enrolled),
        "skipped_already_enrolled_this_run": list(outcome.skipped_already_enrolled),
        "failed_this_run": list(outcome.failed),
        "non_resolvable": [
            {"currency_code": r.currency_code, "reason": r.reason, "held_by": list(r.held_by_account_codes)}
            for r in non_resolvable
        ],
        "pending_enrollment": [
            {"symbol": r.symbol, "market": r.market, "held_by": list(r.held_by_account_codes)}
            for r in pending
        ],
        **SAFETY_MARKERS,
    }

    if args.output == "json":
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        emit(f"held_symbol_count={summary['held_symbol_count']}")
        emit(f"already_enrolled_count={summary['already_enrolled_count']}")
        emit(f"needs_enrollment_count={summary['needs_enrollment_count']}")
        if not args.apply and pending:
            emit("[dry-run] pending enrollment (re-run with --apply --operator ... --reason ... to mutate):")
            for row in summary["pending_enrollment"]:
                emit(f"  {row['symbol']} ({row['market']}) held_by={row['held_by']}")
        if args.apply:
            emit(f"enrolled_this_run={summary['enrolled_this_run']}")
            emit(f"skipped_already_enrolled_this_run={summary['skipped_already_enrolled_this_run']}")
            if outcome.failed:
                emit("[error] enrollment failures this run:")
                for row in summary["failed_this_run"]:
                    emit(f"  {row['symbol']} error={row['error']}")
        if non_resolvable:
            emit("[warn] non-resolvable held currency codes (need registry/venue_market attention):")
            for row in summary["non_resolvable"]:
                emit(f"  {row['currency_code']} reason={row['reason']} held_by={row['held_by']}")

    if outcome.failed:
        emit(f"FAILED {RUNNER_NAME} ts={datetime.now(UTC).isoformat()} failed_count={len(outcome.failed)}")
        return 1
    emit(f"FINISHED {RUNNER_NAME} ts={datetime.now(UTC).isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
