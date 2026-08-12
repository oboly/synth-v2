"""account_portfolio_member_backfill_v1 — Per-account is_portfolio_member seed.

Seeds account_asset.is_portfolio_member = 1 from a single trading_account_id's
own positive holdings, using the canonical account balance/holding source
already produced by run_account_wallet_refresh_v1.py
(trading_account_balance_snapshot). This module does not invent a new
holdings source and does not call the broker.

Explicit non-goal (Issue #372 / architecture audit R3): this backfill must
NEVER read, join, or reference the global publication-cohort column on the
`asset` table (the one historically named "is_portfolio", account-agnostic).
It seeds membership only from the requested account's own positive balances.
Deriving membership from the global cohort would bake today's
cohort/membership conflation permanently into per-account data.

Scope and safety:
  - Exactly one trading_account_id per call. No cross-account writes.
  - Reads only trading_account_balance_snapshot (latest snapshot per
    currency_code) and venue_market/account_asset identity tables.
  - Never inserts new account_asset rows. A positive holding with no existing
    account_asset row for that (trading_account_id, venue_market_id) is
    logged and skipped, not silently dropped and not force-created.
  - Never clears is_portfolio_member on zero-balance rows. This is a seed,
    not ongoing reconciliation: existing membership survives unrelated runs.
  - Idempotent: re-running produces the same end state; already-1 rows are
    left untouched (no redundant write).

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
import sys
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

from src.common.db import get_connection


RUNNER_NAME = "account_portfolio_member_backfill_v1"
RUNNER_VERSION = "0.1"
DEFAULT_VENUE = "bitvavo"
DEFAULT_QUOTE_CURRENCY = "EUR"

ROW_ACTION_SEED = "SEED"
ROW_ACTION_ALREADY_MEMBER = "ALREADY_MEMBER"
ROW_ACTION_SKIP_NO_ACCOUNT_ASSET = "SKIP_NO_ACCOUNT_ASSET"


@dataclass(frozen=True)
class PortfolioMemberBackfillRow:
    currency_code: str
    market: str
    venue_market_id: int | None
    total_amount: Decimal
    account_asset_exists: bool
    row_action: str


@dataclass(frozen=True)
class PortfolioMemberBackfillResult:
    trading_account_id: int
    venue: str
    quote_currency: str
    dry_run: bool
    seeded: int
    already_member: int
    skipped_no_account_asset: int
    rows: tuple[PortfolioMemberBackfillRow, ...]


class PortfolioMemberBackfillRepo(Protocol):
    def fetch_latest_positive_balances(
        self,
        *,
        trading_account_id: int,
        venue: str,
    ) -> list[dict[str, Any]]: ...

    def fetch_venue_market_id(self, *, venue: str, market: str) -> int | None: ...

    def fetch_account_asset(
        self,
        *,
        trading_account_id: int,
        venue_market_id: int,
    ) -> dict[str, Any] | None: ...

    def set_portfolio_member(
        self,
        *,
        trading_account_id: int,
        venue_market_id: int,
    ) -> None: ...


def compute_and_apply_portfolio_member_backfill(
    repo: PortfolioMemberBackfillRepo,
    *,
    trading_account_id: int,
    venue: str = DEFAULT_VENUE,
    quote_currency: str = DEFAULT_QUOTE_CURRENCY,
    dry_run: bool = True,
) -> PortfolioMemberBackfillResult:
    """Compute the backfill plan for one trading_account_id and, unless
    dry_run, apply it. Deterministic and idempotent: only positive-balance
    holdings with an existing account_asset row are touched, and only to set
    is_portfolio_member = 1. No other row, field, or account is modified.
    """
    balances = repo.fetch_latest_positive_balances(
        trading_account_id=trading_account_id,
        venue=venue,
    )

    rows: list[PortfolioMemberBackfillRow] = []
    seeded = 0
    already_member = 0
    skipped_no_account_asset = 0

    for balance in sorted(balances, key=lambda b: str(b["currency_code"])):
        currency_code = str(balance["currency_code"]).strip().upper()
        if not currency_code or currency_code == quote_currency:
            continue
        total_amount = Decimal(str(balance["total_amount"]))
        if total_amount <= 0:
            continue

        market = f"{currency_code}-{quote_currency}"
        venue_market_id = repo.fetch_venue_market_id(venue=venue, market=market)

        if venue_market_id is None:
            rows.append(
                PortfolioMemberBackfillRow(
                    currency_code=currency_code,
                    market=market,
                    venue_market_id=None,
                    total_amount=total_amount,
                    account_asset_exists=False,
                    row_action=ROW_ACTION_SKIP_NO_ACCOUNT_ASSET,
                )
            )
            skipped_no_account_asset += 1
            continue

        account_asset = repo.fetch_account_asset(
            trading_account_id=trading_account_id,
            venue_market_id=venue_market_id,
        )
        if account_asset is None:
            rows.append(
                PortfolioMemberBackfillRow(
                    currency_code=currency_code,
                    market=market,
                    venue_market_id=venue_market_id,
                    total_amount=total_amount,
                    account_asset_exists=False,
                    row_action=ROW_ACTION_SKIP_NO_ACCOUNT_ASSET,
                )
            )
            skipped_no_account_asset += 1
            continue

        already_set = int(account_asset.get("is_portfolio_member") or 0) == 1
        if already_set:
            rows.append(
                PortfolioMemberBackfillRow(
                    currency_code=currency_code,
                    market=market,
                    venue_market_id=venue_market_id,
                    total_amount=total_amount,
                    account_asset_exists=True,
                    row_action=ROW_ACTION_ALREADY_MEMBER,
                )
            )
            already_member += 1
            continue

        rows.append(
            PortfolioMemberBackfillRow(
                currency_code=currency_code,
                market=market,
                venue_market_id=venue_market_id,
                total_amount=total_amount,
                account_asset_exists=True,
                row_action=ROW_ACTION_SEED,
            )
        )
        seeded += 1
        if not dry_run:
            repo.set_portfolio_member(
                trading_account_id=trading_account_id,
                venue_market_id=venue_market_id,
            )

    return PortfolioMemberBackfillResult(
        trading_account_id=trading_account_id,
        venue=venue,
        quote_currency=quote_currency,
        dry_run=dry_run,
        seeded=seeded,
        already_member=already_member,
        skipped_no_account_asset=skipped_no_account_asset,
        rows=tuple(rows),
    )


class MySqlPortfolioMemberBackfillRepo:
    def __init__(self, conn: Any):
        self.conn = conn

    def fetch_latest_positive_balances(
        self,
        *,
        trading_account_id: int,
        venue: str,
    ) -> list[dict[str, Any]]:
        sql = """
        SELECT s1.currency_code, s1.total_amount
        FROM trading_account_balance_snapshot s1
        WHERE s1.trading_account_id = %s
          AND s1.venue = %s
          AND s1.snapshot_ts_utc = (
              SELECT MAX(s2.snapshot_ts_utc)
              FROM trading_account_balance_snapshot s2
              WHERE s2.trading_account_id = s1.trading_account_id
                AND s2.venue = s1.venue
                AND s2.currency_code = s1.currency_code
          )
          AND s1.total_amount > 0
        """
        with self.conn.cursor() as cur:
            cur.execute(sql, (trading_account_id, venue))
            rows = cur.fetchall()
        return [dict(row) for row in rows]

    def fetch_venue_market_id(self, *, venue: str, market: str) -> int | None:
        sql = "SELECT venue_market_id FROM venue_market WHERE venue = %s AND market = %s LIMIT 1"
        with self.conn.cursor() as cur:
            cur.execute(sql, (venue, market))
            row = cur.fetchone()
        return int(row["venue_market_id"]) if row else None

    def fetch_account_asset(
        self,
        *,
        trading_account_id: int,
        venue_market_id: int,
    ) -> dict[str, Any] | None:
        sql = """
        SELECT account_asset_id, trading_account_id, venue_market_id, is_portfolio_member
        FROM account_asset
        WHERE trading_account_id = %s
          AND venue_market_id = %s
        LIMIT 1
        """
        with self.conn.cursor() as cur:
            cur.execute(sql, (trading_account_id, venue_market_id))
            row = cur.fetchone()
        return None if not row else dict(row)

    def set_portfolio_member(
        self,
        *,
        trading_account_id: int,
        venue_market_id: int,
    ) -> None:
        sql = """
        UPDATE account_asset
        SET is_portfolio_member = 1,
            updated_ts = CURRENT_TIMESTAMP
        WHERE trading_account_id = %s
          AND venue_market_id = %s
        """
        with self.conn.cursor() as cur:
            cur.execute(sql, (trading_account_id, venue_market_id))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Per-account is_portfolio_member backfill from that account's own "
            "positive holdings only (trading_account_balance_snapshot). "
            "Never reads the global asset publication-cohort column. No "
            "broker calls, no broker writes, no order submission. Dry-run "
            "by default."
        )
    )
    parser.add_argument("--trading-account-id", required=True, type=int)
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--quote-currency", default=DEFAULT_QUOTE_CURRENCY)
    parser.add_argument(
        "--write-db",
        action="store_true",
        default=False,
        help="Persist the backfill. Dry-run (preview only) if omitted.",
    )
    parser.add_argument("--output", choices=("summary", "none"), default="summary")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    conn = get_connection()
    try:
        repo = MySqlPortfolioMemberBackfillRepo(conn)
        result = compute_and_apply_portfolio_member_backfill(
            repo,
            trading_account_id=args.trading_account_id,
            venue=args.venue,
            quote_currency=args.quote_currency,
            dry_run=not args.write_db,
        )
        if args.write_db:
            conn.commit()
        else:
            conn.rollback()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    if args.output == "summary":
        print(f"runner={RUNNER_NAME} version={RUNNER_VERSION}")
        print(f"trading_account_id={result.trading_account_id} venue={result.venue}")
        print(f"dry_run={int(result.dry_run)}")
        for row in result.rows:
            print(
                f"row currency={row.currency_code} market={row.market} "
                f"venue_market_id={row.venue_market_id} total_amount={row.total_amount} "
                f"account_asset_exists={int(row.account_asset_exists)} action={row.row_action}"
            )
        print(f"seeded={result.seeded}")
        print(f"already_member={result.already_member}")
        print(f"skipped_no_account_asset={result.skipped_no_account_asset}")
        if not args.write_db:
            print("[DRY_RUN] --write-db not set; no DB writes performed")
        print("broker_private_calls=0")
        print("broker_writes=0")
        print("order_submission=0")
        print("decision_gate=none")
        print("execution_planner=none")
        print("executor=none")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
