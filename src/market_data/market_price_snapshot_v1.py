from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class MarketPriceSnapshot:
    venue: str
    symbol: str
    market: str
    quote_currency: str
    price: Decimal
    source_name: str
    source_ts_utc: datetime | None
    observed_ts_utc: datetime


def normalize_symbol(value: str) -> str:
    return value.strip().upper()


def split_market_symbol(market: str, quote_currency: str) -> str | None:
    normalized_market = market.strip().upper()
    normalized_quote = quote_currency.strip().upper()
    suffix = f"-{normalized_quote}"
    if not normalized_market.endswith(suffix):
        return None
    symbol = normalized_market[: -len(suffix)]
    if not symbol:
        return None
    return symbol


def utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def insert_market_price_snapshots(
    conn: Any,
    snapshots: list[MarketPriceSnapshot],
    *,
    authorization: Any = None,
) -> int:
    from src.operations.writer_capability_authorization_v1 import (
        require_writer_mutation_authorization,
    )

    # Fail closed before any SQL execution: the mutation determines its own
    # capability owner; a missing/invalid context is denied.
    require_writer_mutation_authorization(authorization, "public_price_snapshot")
    if not snapshots:
        return 0

    sql = """
    INSERT INTO market_price_snapshot (
        venue,
        symbol,
        market,
        quote_currency,
        price,
        source_name,
        source_ts_utc,
        observed_ts_utc,
        created_ts_utc
    ) VALUES (
        %(venue)s,
        %(symbol)s,
        %(market)s,
        %(quote_currency)s,
        %(price)s,
        %(source_name)s,
        %(source_ts_utc)s,
        %(observed_ts_utc)s,
        CURRENT_TIMESTAMP(6)
    )
    ON DUPLICATE KEY UPDATE
        market = VALUES(market),
        price = VALUES(price),
        source_ts_utc = VALUES(source_ts_utc)
    """
    params = [
        {
            "venue": snapshot.venue,
            "symbol": snapshot.symbol,
            "market": snapshot.market,
            "quote_currency": snapshot.quote_currency,
            "price": snapshot.price,
            "source_name": snapshot.source_name,
            "source_ts_utc": snapshot.source_ts_utc,
            "observed_ts_utc": snapshot.observed_ts_utc,
        }
        for snapshot in snapshots
    ]
    with conn.cursor() as cur:
        cur.executemany(sql, params)
    return len(snapshots)


def fetch_latest_prices_by_symbol(
    conn: Any,
    *,
    venue: str,
    quote_currency: str,
    symbols: list[str] | set[str] | tuple[str, ...] | None = None,
) -> dict[str, MarketPriceSnapshot]:
    normalized_symbols = sorted({normalize_symbol(symbol) for symbol in symbols or [] if symbol})

    latest_symbol_filter = ""
    outer_symbol_filter = ""
    params: dict[str, Any] = {
        "venue": venue.lower(),
        "quote_currency": quote_currency.upper(),
    }
    if normalized_symbols:
        placeholders = []
        for idx, symbol in enumerate(normalized_symbols):
            key = f"symbol_{idx}"
            placeholders.append(f"%({key})s")
            params[key] = symbol
        joined = ", ".join(placeholders)
        latest_symbol_filter = f"AND symbol IN ({joined})"
        outer_symbol_filter = f"AND m.symbol IN ({joined})"

    # Keep market identity in the latest-row key. A newer row for the same
    # symbol but a different market must never hide the canonical quote market.
    sql = f"""
    WITH latest_price AS (
        SELECT
            venue,
            symbol,
            market,
            quote_currency,
            MAX(observed_ts_utc) AS observed_ts_utc
        FROM market_price_snapshot
        WHERE venue = %(venue)s
          AND quote_currency = %(quote_currency)s
          {latest_symbol_filter}
        GROUP BY venue, symbol, market, quote_currency
    )
    SELECT
        m.venue,
        m.symbol,
        m.market,
        m.quote_currency,
        m.price,
        m.source_name,
        m.source_ts_utc,
        m.observed_ts_utc
    FROM market_price_snapshot m
    JOIN latest_price lp
      ON lp.venue = m.venue
     AND lp.symbol = m.symbol
     AND lp.market = m.market
     AND lp.quote_currency = m.quote_currency
     AND lp.observed_ts_utc = m.observed_ts_utc
    WHERE m.venue = %(venue)s
      AND m.quote_currency = %(quote_currency)s
      {outer_symbol_filter}
    ORDER BY m.symbol, m.observed_ts_utc DESC, m.source_ts_utc DESC, m.source_name DESC
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = list(cur.fetchall())

    out: dict[str, MarketPriceSnapshot] = {}
    for row in rows:
        symbol = normalize_symbol(str(row["symbol"]))
        quote = str(row["quote_currency"]).strip().upper()
        market = str(row["market"]).strip().upper()
        if market != f"{symbol}-{quote}":
            continue
        # SQL ordering makes equal-observation ties deterministic; keep the
        # newest canonical row for each symbol.
        if symbol in out:
            continue
        out[symbol] = MarketPriceSnapshot(
            venue=str(row["venue"]),
            symbol=symbol,
            market=market,
            quote_currency=quote,
            price=Decimal(str(row["price"])),
            source_name=str(row["source_name"]),
            source_ts_utc=row.get("source_ts_utc"),
            observed_ts_utc=row["observed_ts_utc"],
        )
    return out
