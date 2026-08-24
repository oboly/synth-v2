"""
bitvavo_venue_execution_constraint_sync_v1 — canonical refresh writer for
`venue_execution_constraint`.

Layer: venue/market execution metadata. Market-only, account-agnostic.
Public Bitvavo `/v2/markets` metadata only (BitvavoClient.for_public()) — no
credentials, no private/authenticated calls, no broker writes, no order
submission.

This is the missing writer half of the existing fail-closed contract in
src.market_rules.venue_execution_constraints_v1 (resolve/DB read side) and
src.market_rules.bitvavo_venue_adapter_v1 (pure Bitvavo -> contract
transform, already implemented and tested). This runner adds only the I/O
glue: fetch public markets, filter to the requested quote currency, run the
existing transform, and idempotently upsert the result into
`venue_execution_constraint` keyed on the table's existing
(venue, market) unique key.

Malformed or partial per-market metadata is never written:
parse_bitvavo_markets_response() (src.market_rules.bitvavo_venue_adapter_v1)
already drops any row missing a required field or not in `status=trading`,
so those markets simply keep whatever row (or absence) already exists in the
DB and continue to resolve MISSING/STALE at the fail-closed resolver — this
runner never invents a permissive default for them.

broker_private_calls=0
broker_writes=0
order_submission=0
decision_gate=none
execution_planner=none
executor=none
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from src.common.db import get_db_connection
from src.execution.bitvavo_client import BitvavoClient
from src.market_rules.bitvavo_venue_adapter_v1 import parse_bitvavo_markets_response
from src.market_rules.venue_execution_constraints_v1 import VenueExecutionConstraints


RUNNER_NAME = "bitvavo_venue_execution_constraint_sync_v1"
RUNNER_VERSION = "0.1"
DEFAULT_VENUE = "bitvavo"
DEFAULT_QUOTE_FILTER = "EUR"

_UPSERT_SQL = """
INSERT INTO venue_execution_constraint (
    venue, market, tick_size, qty_step_size, min_base_quantity, min_quote_notional,
    supported_order_types, supported_time_in_force, source_provenance, metadata_synced_ts_utc
) VALUES (
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
)
ON DUPLICATE KEY UPDATE
    tick_size = VALUES(tick_size),
    qty_step_size = VALUES(qty_step_size),
    min_base_quantity = VALUES(min_base_quantity),
    min_quote_notional = VALUES(min_quote_notional),
    supported_order_types = VALUES(supported_order_types),
    supported_time_in_force = VALUES(supported_time_in_force),
    source_provenance = VALUES(source_provenance),
    metadata_synced_ts_utc = VALUES(metadata_synced_ts_utc)
"""


@dataclass(frozen=True)
class ConstraintSyncBuild:
    rows: tuple[VenueExecutionConstraints, ...]
    eur_market_count: int
    skipped_markets: tuple[str, ...]


@dataclass(frozen=True)
class ConstraintSyncResult:
    venue: str
    eur_market_count: int
    resolved_count: int
    skipped_count: int
    inserted: int
    updated: int
    unchanged: int


def fetch_bitvavo_markets(client: BitvavoClient) -> list[dict[str, Any]]:
    """Public /v2/markets fetch. No credentials, no private call."""
    rows = client.get_markets()
    if not isinstance(rows, list):
        raise RuntimeError(f"Unexpected Bitvavo /markets response type: {type(rows)}")
    return rows


def build_constraint_rows(
    raw_markets: list[dict[str, Any]],
    *,
    venue: str = DEFAULT_VENUE,
    quote_filter: str = DEFAULT_QUOTE_FILTER,
    synced_ts_utc: datetime | None = None,
) -> ConstraintSyncBuild:
    """Filter raw public market rows to `quote_filter` and run the existing
    Bitvavo -> VenueExecutionConstraints transform. Deterministically
    ordered by market name so repeated runs over identical source state
    produce identical write ordering.

    A market present in the quote-filtered universe but dropped by the
    transform (missing required field, or status != trading) is reported in
    `skipped_markets` and is never written — it fails closed at the resolver
    instead, exactly like a market with no row at all.
    """
    ts = synced_ts_utc or datetime.now(timezone.utc)
    eur_markets = {
        str(row["market"])
        for row in raw_markets
        if str(row.get("quote") or "").upper() == quote_filter.upper() and row.get("market")
    }
    parsed = parse_bitvavo_markets_response(
        raw_markets, markets=eur_markets, venue=venue, synced_ts_utc=ts,
    )
    skipped = sorted(eur_markets - set(parsed.keys()))
    rows = tuple(parsed[market] for market in sorted(parsed.keys()))
    return ConstraintSyncBuild(
        rows=rows,
        eur_market_count=len(eur_markets),
        skipped_markets=tuple(skipped),
    )


def upsert_constraint_row(conn: Any, row: VenueExecutionConstraints) -> str:
    """Idempotent upsert keyed on the table's (venue, market) unique key.

    Returns INSERTED | UPDATED | UNCHANGED, read off MariaDB's
    ON DUPLICATE KEY UPDATE rowcount convention (1 = insert, 2 = changed
    update, 0 = matched but identical — a true no-op rerun).
    """
    params = (
        row.venue,
        row.market,
        str(row.tick_size),
        str(row.qty_step_size),
        str(row.min_base_quantity),
        str(row.min_quote_notional),
        ",".join(row.supported_order_types),
        ",".join(row.supported_time_in_force),
        row.source_provenance,
        row.metadata_synced_ts_utc,
    )
    with conn.cursor() as cur:
        cur.execute(_UPSERT_SQL, params)
        affected = cur.rowcount
    if affected == 1:
        return "INSERTED"
    if affected == 2:
        return "UPDATED"
    return "UNCHANGED"


def run_constraint_sync(
    conn: Any,
    *,
    venue: str,
    build: ConstraintSyncBuild,
    write_db: bool,
) -> ConstraintSyncResult:
    inserted = updated = unchanged = 0
    if write_db:
        for row in build.rows:
            action = upsert_constraint_row(conn, row)
            if action == "INSERTED":
                inserted += 1
            elif action == "UPDATED":
                updated += 1
            else:
                unchanged += 1
        conn.commit()

    return ConstraintSyncResult(
        venue=venue,
        eur_market_count=build.eur_market_count,
        resolved_count=len(build.rows),
        skipped_count=len(build.skipped_markets),
        inserted=inserted,
        updated=updated,
        unchanged=unchanged,
    )


def print_summary(result: ConstraintSyncResult, *, build: ConstraintSyncBuild, write_db: bool) -> None:
    print(f"runner={RUNNER_NAME} version={RUNNER_VERSION}")
    print(f"venue={result.venue}")
    print(f"eur_market_count={result.eur_market_count}")
    print(f"resolved_count={result.resolved_count}")
    print(f"skipped_count={result.skipped_count}")
    if result.skipped_count:
        print(f"skipped_markets={','.join(build.skipped_markets)}")
    if write_db:
        print(f"inserted={result.inserted}")
        print(f"updated={result.updated}")
        print(f"unchanged={result.unchanged}")
    else:
        print("[DRY_RUN] --write-db not set; no DB writes performed")
    print("broker_private_calls=0")
    print("broker_writes=0")
    print("order_submission=0")
    print("decision_gate=none")
    print("execution_planner=none")
    print("executor=none")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Refresh venue_execution_constraint from Bitvavo public /v2/markets "
            "metadata. Public API only. No broker writes, no order submission."
        )
    )
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument(
        "--quote-filter",
        default=DEFAULT_QUOTE_FILTER,
        help="Only sync markets quoted in this currency.",
    )
    parser.add_argument(
        "--write-db",
        action="store_true",
        default=False,
        help="Persist upserts to DB. Dry-run if omitted.",
    )
    parser.add_argument("--timeout-seconds", type=int, default=15)
    parser.add_argument("--output", choices=("summary", "none"), default="summary")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    started_at = time.monotonic()
    print(
        f"STARTED runner={RUNNER_NAME} mode={'write' if args.write_db else 'dry_run'} "
        f"venue={args.venue} quote_filter={args.quote_filter}"
    )
    sys.stdout.flush()

    client = BitvavoClient.for_public(timeout_seconds=args.timeout_seconds)
    try:
        raw_markets = fetch_bitvavo_markets(client)
    except Exception as exc:
        print(f"[error] market fetch failed: {exc}", file=sys.stderr)
        print(f"FAILED runner={RUNNER_NAME} elapsed_s={time.monotonic() - started_at:.2f}")
        return 1

    build = build_constraint_rows(raw_markets, venue=args.venue, quote_filter=args.quote_filter)

    conn = get_db_connection()
    try:
        result = run_constraint_sync(conn, venue=args.venue, build=build, write_db=args.write_db)
    finally:
        conn.close()

    if args.output == "summary":
        print_summary(result, build=build, write_db=args.write_db)

    print(f"FINISHED runner={RUNNER_NAME} elapsed_s={time.monotonic() - started_at:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
