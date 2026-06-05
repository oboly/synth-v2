from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.common.db import get_connection
from src.market_data.market_price_snapshot_v1 import MarketPriceSnapshot, fetch_latest_prices_by_symbol
from src.reporting.account_wallet_dashboard_v1 import QUOTE_CURRENCY, to_decimal
from src.reporting.current_price_snapshot_v1 import (
    DEFAULT_CURRENT_PRICE_FRESH_AFTER,
    CurrentPriceDisplay,
    classify_current_price_snapshot,
)
from src.reporting.manual_short_trader_dashboard_v1 import BrokerBalanceRow, BrokerOrderRow


DEFAULT_OUTPUT_ROOT = Path("/var/www/html/synth")
DEFAULT_VENUE = "bitvavo"
PROFILE_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")


@dataclass(frozen=True)
class AccountScopedShortDashboardContext:
    profile: str
    account_code: str
    trading_account_id: int
    venue: str
    latest_balance_snapshot_ts_utc: datetime | None
    latest_order_snapshot_ts_utc: datetime | None
    balances: tuple[BrokerBalanceRow, ...]
    orders: tuple[BrokerOrderRow, ...]
    account_asset_rows: tuple[dict[str, Any], ...]
    open_order_count_by_market: dict[str, int]
    market_price_by_symbol: dict[str, MarketPriceSnapshot]
    markets: tuple[str, ...]


def classify_market_prices_by_market(
    *,
    context: AccountScopedShortDashboardContext,
    now_utc: datetime | None = None,
) -> dict[str, CurrentPriceDisplay]:
    now_utc = now_utc or datetime.now(UTC)
    out: dict[str, CurrentPriceDisplay] = {}
    for market in context.markets:
        symbol = market.split("-", 1)[0].upper()
        out[market] = classify_current_price_snapshot(
            context.market_price_by_symbol.get(symbol),
            now_utc=now_utc,
            fresh_after=DEFAULT_CURRENT_PRICE_FRESH_AFTER,
        )
    return out


def validate_profile_slug(profile: str) -> None:
    if not PROFILE_SLUG_RE.match(profile):
        raise ValueError(
            f"Invalid profile slug {profile!r}. Must match [a-z0-9][a-z0-9_-]{{0,62}}."
        )
    if ".." in profile or "/" in profile:
        raise ValueError(f"Path traversal rejected in profile slug: {profile!r}")


def default_page_paths(*, output_root: Path, profile: str, page_stem: str) -> tuple[Path, Path]:
    profile_dir = output_root / "accounts" / profile
    return profile_dir / f"{page_stem}.html", profile_dir / f"{page_stem}.json"


def public_page_href(*, profile: str, page_stem: str) -> str:
    return f"/synth/accounts/{profile}/{page_stem}.html"


def _resolve_trading_account(conn: Any, *, account_code: str, venue: str) -> dict[str, Any]:
    sql = """
    SELECT
        trading_account_id,
        account_code,
        venue
    FROM trading_account
    WHERE account_code = %s
      AND venue = %s
    ORDER BY trading_account_id
    """
    with conn.cursor() as cur:
        cur.execute(sql, (account_code, venue))
        rows = list(cur.fetchall())
    if not rows:
        raise RuntimeError(f"trading_account missing: account_code={account_code} venue={venue}")
    if len(rows) != 1:
        raise RuntimeError(f"trading_account ambiguous: account_code={account_code} venue={venue} matches={len(rows)}")
    return dict(rows[0])


def _fetch_latest_balance_snapshot_ts(
    conn: Any,
    *,
    trading_account_id: int,
    venue: str,
) -> datetime | None:
    sql = """
    SELECT MAX(snapshot_ts_utc) AS latest_snapshot_ts_utc
    FROM trading_account_balance_snapshot
    WHERE trading_account_id = %s
      AND venue = %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (trading_account_id, venue))
        row = cur.fetchone()
    return None if not row else row.get("latest_snapshot_ts_utc")


def _fetch_balance_rows(
    conn: Any,
    *,
    trading_account_id: int,
    venue: str,
    snapshot_ts_utc: datetime | None,
) -> list[BrokerBalanceRow]:
    if snapshot_ts_utc is None:
        return []
    sql = """
    SELECT
        currency_code,
        available_amount,
        reserved_amount,
        total_amount
    FROM trading_account_balance_snapshot
    WHERE trading_account_id = %s
      AND venue = %s
      AND snapshot_ts_utc = %s
    ORDER BY currency_code
    """
    with conn.cursor() as cur:
        cur.execute(sql, (trading_account_id, venue, snapshot_ts_utc))
        rows = list(cur.fetchall())
    balances: list[BrokerBalanceRow] = []
    for row in rows:
        available = to_decimal(row.get("available_amount")) or Decimal("0")
        in_order = to_decimal(row.get("reserved_amount")) or Decimal("0")
        balances.append(
            BrokerBalanceRow(
                symbol=str(row.get("currency_code") or "").upper(),
                available=available,
                in_order=in_order,
            )
        )
    return balances


def _fetch_latest_order_snapshot_ts(
    conn: Any,
    *,
    trading_account_id: int,
    venue: str,
) -> datetime | None:
    sql = """
    SELECT MAX(snapshot_ts_utc) AS latest_snapshot_ts_utc
    FROM account_open_order_snapshot
    WHERE trading_account_id = %s
      AND venue = %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (trading_account_id, venue))
        row = cur.fetchone()
    return None if not row else row.get("latest_snapshot_ts_utc")


def _dt_to_ms(value: datetime | None) -> int | None:
    if value is None:
        return None
    return int(value.replace(tzinfo=UTC if value.tzinfo is None else value.tzinfo).timestamp() * 1000)


def _fetch_open_order_rows(
    conn: Any,
    *,
    trading_account_id: int,
    venue: str,
    snapshot_ts_utc: datetime | None,
) -> list[BrokerOrderRow]:
    if snapshot_ts_utc is None:
        return []
    sql = """
    SELECT
        market,
        broker_order_id,
        side,
        order_type,
        limit_price,
        quantity,
        filled_quantity,
        remaining_quantity,
        broker_status,
        created_ts
    FROM account_open_order_snapshot
    WHERE trading_account_id = %s
      AND venue = %s
      AND snapshot_ts_utc = %s
    ORDER BY market, side, limit_price, broker_order_id
    """
    with conn.cursor() as cur:
        cur.execute(sql, (trading_account_id, venue, snapshot_ts_utc))
        rows = list(cur.fetchall())
    orders: list[BrokerOrderRow] = []
    for row in rows:
        limit_price = to_decimal(row.get("limit_price")) or Decimal("0")
        amount = to_decimal(row.get("quantity")) or Decimal("0")
        filled = to_decimal(row.get("filled_quantity")) or Decimal("0")
        remaining = to_decimal(row.get("remaining_quantity")) or Decimal("0")
        orders.append(
            BrokerOrderRow(
                order_id=str(row.get("broker_order_id") or ""),
                market=str(row.get("market") or "").upper(),
                side=str(row.get("side") or "").lower(),
                order_type=str(row.get("order_type") or "limit").lower(),
                limit_price=limit_price,
                amount=amount,
                filled_amount=filled,
                remaining_amount=remaining,
                status=str(row.get("broker_status") or ""),
                created_at_ms=_dt_to_ms(row.get("created_ts")),
            )
        )
    return orders


def _fetch_account_asset_rows(
    conn: Any,
    *,
    trading_account_id: int,
    venue: str,
) -> list[dict[str, Any]]:
    sql = """
    SELECT
        vm.market,
        vm.quote_currency,
        a.symbol AS asset_symbol,
        a.is_enabled AS asset_is_enabled,
        aa.source,
        aa.is_visible,
        aa.is_candidate_enabled,
        aa.is_order_proposal_enabled,
        aa.is_hidden,
        aa.disabled_until_utc
    FROM account_asset aa
    JOIN venue_market vm
      ON vm.venue_market_id = aa.venue_market_id
    JOIN asset a
      ON a.asset_id = vm.base_asset_id
    WHERE aa.trading_account_id = %s
      AND vm.venue = %s
    ORDER BY vm.market
    """
    with conn.cursor() as cur:
        cur.execute(sql, (trading_account_id, venue))
        rows = list(cur.fetchall())
    return [dict(row) for row in rows]


def build_account_market_scope(
    *,
    account_asset_rows: list[dict[str, Any]],
    balances: list[BrokerBalanceRow],
    orders: list[BrokerOrderRow],
) -> list[str]:
    positive_balance_markets: set[str] = set()
    for row in balances:
        symbol = str(row.symbol or "").upper()
        if not symbol or symbol == QUOTE_CURRENCY:
            continue
        total = (row.available or Decimal("0")) + (row.in_order or Decimal("0"))
        if total > Decimal("0"):
            positive_balance_markets.add(f"{symbol}-{QUOTE_CURRENCY}")

    open_order_markets = {str(row.market or "").upper() for row in orders if str(row.market or "").strip()}
    included_markets: set[str] = set(open_order_markets)

    for raw in account_asset_rows:
        market = str(raw.get("market") or "").upper()
        if not market:
            continue
        has_open_order = market in open_order_markets
        is_hidden = bool(raw.get("is_hidden"))
        is_visible = bool(raw.get("is_visible"))
        source = str(raw.get("source") or "").upper()
        has_positive_balance = market in positive_balance_markets

        if has_open_order:
            included_markets.add(market)
            continue
        if is_hidden:
            continue
        if is_visible or has_positive_balance or source == "MANUAL_ADD":
            included_markets.add(market)

    return sorted(included_markets)


def load_account_scoped_short_dashboard_context(
    *,
    profile: str,
    account_code: str,
    venue: str = DEFAULT_VENUE,
) -> AccountScopedShortDashboardContext:
    validate_profile_slug(profile)
    conn = get_connection()
    try:
        account = _resolve_trading_account(conn, account_code=account_code, venue=venue)
        trading_account_id = int(account["trading_account_id"])
        latest_balance_snapshot_ts_utc = _fetch_latest_balance_snapshot_ts(
            conn,
            trading_account_id=trading_account_id,
            venue=venue,
        )
        latest_order_snapshot_ts_utc = _fetch_latest_order_snapshot_ts(
            conn,
            trading_account_id=trading_account_id,
            venue=venue,
        )
        balances = _fetch_balance_rows(
            conn,
            trading_account_id=trading_account_id,
            venue=venue,
            snapshot_ts_utc=latest_balance_snapshot_ts_utc,
        )
        orders = _fetch_open_order_rows(
            conn,
            trading_account_id=trading_account_id,
            venue=venue,
            snapshot_ts_utc=latest_order_snapshot_ts_utc,
        )
        account_asset_rows = _fetch_account_asset_rows(
            conn,
            trading_account_id=trading_account_id,
            venue=venue,
        )
        markets = build_account_market_scope(
            account_asset_rows=account_asset_rows,
            balances=balances,
            orders=orders,
        )
        symbols = sorted({market.split("-", 1)[0].upper() for market in markets if "-" in market})
        market_price_by_symbol = fetch_latest_prices_by_symbol(
            conn,
            venue=venue,
            quote_currency=QUOTE_CURRENCY,
            symbols=symbols,
        )
    finally:
        conn.close()

    open_order_count_by_market: dict[str, int] = {}
    for order in orders:
        open_order_count_by_market[order.market] = open_order_count_by_market.get(order.market, 0) + 1

    return AccountScopedShortDashboardContext(
        profile=profile,
        account_code=account_code,
        trading_account_id=trading_account_id,
        venue=venue,
        latest_balance_snapshot_ts_utc=latest_balance_snapshot_ts_utc,
        latest_order_snapshot_ts_utc=latest_order_snapshot_ts_utc,
        balances=tuple(balances),
        orders=tuple(orders),
        account_asset_rows=tuple(account_asset_rows),
        open_order_count_by_market=open_order_count_by_market,
        market_price_by_symbol=market_price_by_symbol,
        markets=tuple(markets),
    )
