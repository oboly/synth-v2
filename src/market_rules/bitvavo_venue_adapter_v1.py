"""
bitvavo_venue_adapter_v1 — Bitvavo-specific resolution of venue execution
constraints.

Layer: venue adapter, isolated behind this module per the manual execution
ladder future-readiness audit finding F10. Public market metadata only — no
private account calls, no credentials required, no broker writes.

Bitvavo's /v2/markets response (observed 2026-07-25T19:43:17Z) no longer
populates `pricePrecision` (it returns null). The previously used
src.market_rules.price_tick_normalization_v1._BITVAVO_EUR_STATIC_PRECISION
static fallback table was built from that now-deprecated field and is
confirmed stale for at least BTC-EUR (that table implies a 0.1 EUR tick;
the exchange's current explicit `tickSize` field is "1.00", a 1 EUR tick).
This adapter uses the current explicit fields instead: tickSize,
quantityDecimals, minOrderInBaseAsset, minOrderInQuoteAsset, orderTypes.

Bitvavo does not expose supported time-in-force per market via this
endpoint; GTC/IOC/FOK are the venue-wide documented values and are applied
uniformly here, not inferred per market.

This module is a pure transform: parse_bitvavo_markets_response() takes
already-fetched rows (from BitvavoClient.get_markets() or a test fixture)
and never performs I/O itself, so it is fully testable without a network
call.

broker_private_calls=0
broker_writes=0
order_submission=0
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Final

from src.market_rules.venue_execution_constraints_v1 import (
    SOURCE_BITVAVO_PUBLIC_MARKETS_API_V2,
    STATUS_FRESH,
    VenueExecutionConstraints,
)


BITVAVO_SUPPORTED_TIME_IN_FORCE: Final[tuple[str, ...]] = ("GTC", "IOC", "FOK")

_REQUIRED_FIELDS: Final[tuple[str, ...]] = (
    "market",
    "tickSize",
    "quantityDecimals",
    "minOrderInBaseAsset",
    "minOrderInQuoteAsset",
    "orderTypes",
)


def parse_bitvavo_market_row(
    row: dict[str, Any],
    *,
    venue: str = "bitvavo",
    synced_ts_utc: datetime | None = None,
) -> VenueExecutionConstraints | None:
    """Transform one raw Bitvavo /v2/markets row into VenueExecutionConstraints.

    Returns None for markets missing a required field or not in 'trading'
    status — callers must treat None the same as MISSING, never guess a
    value for it.
    """
    if row.get("status") != "trading":
        return None

    if any(row.get(field_name) in (None, "") for field_name in _REQUIRED_FIELDS):
        return None

    market = str(row["market"])
    tick_size = Decimal(str(row["tickSize"]))
    qty_step_size = Decimal(1).scaleb(-int(row["quantityDecimals"]))
    min_base_quantity = Decimal(str(row["minOrderInBaseAsset"]))
    min_quote_notional = Decimal(str(row["minOrderInQuoteAsset"]))
    order_types = tuple(str(value) for value in row["orderTypes"])

    return VenueExecutionConstraints(
        venue=venue,
        market=market,
        tick_size=tick_size,
        qty_step_size=qty_step_size,
        min_base_quantity=min_base_quantity,
        min_quote_notional=min_quote_notional,
        supported_order_types=order_types,
        supported_time_in_force=BITVAVO_SUPPORTED_TIME_IN_FORCE,
        source_provenance=SOURCE_BITVAVO_PUBLIC_MARKETS_API_V2,
        metadata_synced_ts_utc=synced_ts_utc or datetime.now(timezone.utc),
        status=STATUS_FRESH,
    )


def parse_bitvavo_markets_response(
    rows: list[dict[str, Any]],
    *,
    markets: set[str] | None = None,
    venue: str = "bitvavo",
    synced_ts_utc: datetime | None = None,
) -> dict[str, VenueExecutionConstraints]:
    """Transform a full Bitvavo /v2/markets response into
    {market: VenueExecutionConstraints}, optionally filtered to `markets`.

    Pure function: no network call, no DB access. Callers supply `rows`
    from BitvavoClient.get_markets() (live) or a fixture (tests).
    """
    result: dict[str, VenueExecutionConstraints] = {}
    ts = synced_ts_utc or datetime.now(timezone.utc)
    for row in rows:
        market = row.get("market")
        if markets is not None and market not in markets:
            continue
        parsed = parse_bitvavo_market_row(row, venue=venue, synced_ts_utc=ts)
        if parsed is not None:
            result[str(market)] = parsed
    return result
