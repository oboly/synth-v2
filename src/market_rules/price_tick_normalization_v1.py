"""
price_tick_normalization_v1 — Deterministic Decimal-only tick-size normalization.

This module is the canonical owner of market price-increment rules for Synth.

Layer: public market metadata — account-agnostic, broker-read-free.

Usage:
  1. Load tick rules from DB (preferred): load_tick_rules_from_db(conn, venue, markets)
  2. Resolve per-market rule (DB-first, static fallback): resolve_tick_rule(...)
  3. Normalize a price: normalize_price_to_tick(raw_price, tick_rule, price_role)

Rounding semantics (all executable roles):
  ROUND_DOWN (floor to nearest valid tick below the raw analytical price).

  Rationale:
    SELL/TARGET  — executable sell at or below the analytical level is valid.
    BUY/REENTRY  — executable buy at or below the analytical level is valid.
    INVALIDATION — floor preserves risk semantics; the displayed level is not
                   more than 1 tick above the analytical value.

  DISPLAY_ONLY prices use ROUND_HALF_UP (nearest tick).

Fail-closed:
  When tick rules are unavailable for a market, normalize_price_to_tick returns
  the raw price unchanged with price_rule_status=MISSING_TICK_RULE.
  Callers must surface MISSING_TICK_RULE visibly rather than treating it as success.

Static fallback:
  _BITVAVO_EUR_STATIC_PRECISION documents Bitvavo /v2/markets pricePrecision values
  observed from the public API. These are used only when the DB is unavailable or
  the market has no synced price_precision row. Never inferred from price magnitude.

broker_private_calls=0
broker_writes=0
order_submission=0
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from typing import Any

# ---------------------------------------------------------------------------
# Price role constants
# ---------------------------------------------------------------------------

PRICE_ROLE_TARGET_SELL = "TARGET_SELL"
PRICE_ROLE_REENTRY_BUY = "REENTRY_BUY"
PRICE_ROLE_INVALIDATION = "INVALIDATION"
PRICE_ROLE_DISPLAY_ONLY = "DISPLAY_ONLY"

_EXECUTABLE_ROLES: frozenset[str] = frozenset({
    PRICE_ROLE_TARGET_SELL,
    PRICE_ROLE_REENTRY_BUY,
    PRICE_ROLE_INVALIDATION,
})

# ---------------------------------------------------------------------------
# Tick rule source constants
# ---------------------------------------------------------------------------

TICK_RULE_SOURCE_DB = "TICK_RULE_FROM_DB"
TICK_RULE_SOURCE_STATIC = "TICK_RULE_FROM_STATIC"
TICK_RULE_SOURCE_MISSING = "MISSING_TICK_RULE"

# ---------------------------------------------------------------------------
# Normalization result status constants
# ---------------------------------------------------------------------------

NORM_STATUS_APPLIED = "TICK_RULE_APPLIED"
NORM_STATUS_MISSING = "MISSING_TICK_RULE"
NORM_STATUS_DISPLAY_ONLY = "DISPLAY_ONLY_NOT_EXECUTABLE"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TickRule:
    """Describes a market's price increment / tick-size rule.

    source values:
      TICK_RULE_FROM_DB      — loaded from venue_market.price_precision
      TICK_RULE_FROM_STATIC  — from _BITVAVO_EUR_STATIC_PRECISION fallback
      MISSING_TICK_RULE      — no rule found; tick_size is Decimal("0")
    """
    venue: str
    market: str
    tick_size: Decimal
    decimal_places: int
    source: str


@dataclass(frozen=True)
class PriceNormalizationResult:
    """Result of normalizing one price to its market's tick size."""
    raw_price: Decimal
    normalized_price: Decimal
    tick_size: Decimal | None
    decimal_places: int | None
    price_rule_status: str   # TICK_RULE_APPLIED | MISSING_TICK_RULE | DISPLAY_ONLY_NOT_EXECUTABLE
    price_role: str
    rule_source: str


# ---------------------------------------------------------------------------
# Static fallback tick rules
# ---------------------------------------------------------------------------
# Source: Bitvavo public /v2/markets endpoint, pricePrecision field.
# These values are documented, deterministic, and test-covered.
# Never inferred from current price magnitude.
# Only used when the DB does not have a synced price_precision for the market.

_BITVAVO_EUR_STATIC_PRECISION: dict[str, int] = {
    # Micro-price markets (~< 0.0001 EUR) — pricePrecision=8
    "PEPE-EUR": 8,
    "MOG-EUR": 8,
    "SHIB-EUR": 8,
    "FLOKI-EUR": 8,
    "IOST-EUR": 8,
    # Sub-cent markets (~0.001 – 0.10 EUR) — pricePrecision=6
    "HOT-EUR": 6,
    "VET-EUR": 6,
    "XPL-EUR": 6,
    "CC-EUR": 6,
    # Low-price markets (~0.10 – 2.00 EUR) — pricePrecision=5
    "LDO-EUR": 5,
    "RED-EUR": 5,
    "FET-EUR": 5,
    "ALGO-EUR": 5,
    "XRP-EUR": 5,
    "HBAR-EUR": 5,
    "THETA-EUR": 5,
    "RLC-EUR": 5,
    # Mid-price markets (~2.00 – 20.00 EUR) — pricePrecision=4
    "SUI-EUR": 4,
    "ICP-EUR": 4,
    "HNT-EUR": 4,
    "SOL-EUR": 4,
    # Higher-price markets (~100+ EUR) — pricePrecision=2
    "ETH-EUR": 2,
    "AAVE-EUR": 2,
    "BNB-EUR": 2,
    # Single decimal place for very high-value assets
    "BTC-EUR": 1,
}


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def tick_size_from_precision(decimal_places: int) -> Decimal:
    """Convert integer decimal-place count to tick size Decimal.

    tick_size_from_precision(5) == Decimal("0.00001")
    tick_size_from_precision(8) == Decimal("0.00000001")
    """
    return Decimal(10) ** -decimal_places


def _quantize_to_tick(price: Decimal, tick_size: Decimal, rounding: str) -> Decimal:
    """Quantize price to the nearest valid tick using the given rounding mode.

    Uses integer tick arithmetic (price // tick_size * tick_size) for
    ROUND_DOWN to avoid Decimal string-format precision loss, then
    re-quantizes to canonical decimal places.
    """
    ticks = (price / tick_size).to_integral_value(rounding=rounding)
    return ticks * tick_size


# ---------------------------------------------------------------------------
# TickRule factories
# ---------------------------------------------------------------------------

def _missing_tick_rule(venue: str, market: str) -> TickRule:
    return TickRule(
        venue=venue,
        market=market,
        tick_size=Decimal("0"),
        decimal_places=0,
        source=TICK_RULE_SOURCE_MISSING,
    )


def resolve_tick_rule_from_static(venue: str, market: str) -> TickRule | None:
    """Return a TickRule from the static fallback table, or None if not present."""
    if venue == "bitvavo":
        dp = _BITVAVO_EUR_STATIC_PRECISION.get(market)
        if dp is not None:
            return TickRule(
                venue=venue,
                market=market,
                tick_size=tick_size_from_precision(dp),
                decimal_places=dp,
                source=TICK_RULE_SOURCE_STATIC,
            )
    return None


def load_tick_rules_from_db(
    conn: Any,
    *,
    venue: str,
    markets: list[str],
) -> dict[str, TickRule]:
    """Load price_precision for each market from venue_market table.

    Returns only markets that have a non-NULL price_precision row.
    Markets missing from the DB or with NULL precision are omitted;
    callers should fall back to resolve_tick_rule_from_static or MISSING.

    broker_private_calls=0
    """
    if not markets:
        return {}
    placeholders = ", ".join(["%s"] * len(markets))
    sql = (
        f"SELECT market, price_precision FROM venue_market "
        f"WHERE venue = %s AND market IN ({placeholders})"
    )
    params: tuple[Any, ...] = (venue, *markets)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    except Exception:
        return {}

    result: dict[str, TickRule] = {}
    for row in rows:
        market = str(row["market"])
        pp = row.get("price_precision")
        if pp is not None:
            dp = int(pp)
            result[market] = TickRule(
                venue=venue,
                market=market,
                tick_size=tick_size_from_precision(dp),
                decimal_places=dp,
                source=TICK_RULE_SOURCE_DB,
            )
    return result


def resolve_tick_rule(
    *,
    venue: str,
    market: str,
    db_rules: dict[str, TickRule] | None = None,
) -> TickRule:
    """Resolve the tick rule for a market: DB first, static fallback, then MISSING.

    Never infers precision from price magnitude.
    Returns a MISSING_TICK_RULE TickRule (not None) when no source is available.
    """
    if db_rules:
        rule = db_rules.get(market)
        if rule and rule.source != TICK_RULE_SOURCE_MISSING:
            return rule
    static = resolve_tick_rule_from_static(venue, market)
    if static is not None:
        return static
    return _missing_tick_rule(venue, market)


# ---------------------------------------------------------------------------
# Price normalization
# ---------------------------------------------------------------------------

def normalize_price_to_tick(
    raw_price: Decimal,
    tick_rule: TickRule,
    price_role: str,
) -> PriceNormalizationResult:
    """Normalize raw_price to the nearest valid tick boundary.

    Executable roles (TARGET_SELL, REENTRY_BUY, INVALIDATION):
      Use ROUND_DOWN (floor). The normalized price is ≤ raw_price.

    DISPLAY_ONLY:
      Use ROUND_HALF_UP (nearest tick). Marks result DISPLAY_ONLY_NOT_EXECUTABLE.

    MISSING_TICK_RULE:
      Raw price returned unchanged. Result has MISSING_TICK_RULE status.

    Always returns a Decimal quantized to tick_rule.decimal_places.
    Never uses float arithmetic.
    """
    if tick_rule.source == TICK_RULE_SOURCE_MISSING:
        return PriceNormalizationResult(
            raw_price=raw_price,
            normalized_price=raw_price,
            tick_size=None,
            decimal_places=None,
            price_rule_status=NORM_STATUS_MISSING if price_role != PRICE_ROLE_DISPLAY_ONLY else NORM_STATUS_DISPLAY_ONLY,
            price_role=price_role,
            rule_source=TICK_RULE_SOURCE_MISSING,
        )

    tick_size = tick_rule.tick_size
    dp = tick_rule.decimal_places
    q = Decimal(10) ** -dp  # canonical quantizer for the market

    if price_role == PRICE_ROLE_DISPLAY_ONLY:
        normalized = _quantize_to_tick(raw_price, tick_size, ROUND_HALF_UP)
        normalized = normalized.quantize(q, rounding=ROUND_HALF_UP)
        return PriceNormalizationResult(
            raw_price=raw_price,
            normalized_price=normalized,
            tick_size=tick_size,
            decimal_places=dp,
            price_rule_status=NORM_STATUS_DISPLAY_ONLY,
            price_role=price_role,
            rule_source=tick_rule.source,
        )

    # All executable roles: ROUND_DOWN
    normalized = _quantize_to_tick(raw_price, tick_size, ROUND_DOWN)
    normalized = normalized.quantize(q, rounding=ROUND_DOWN)
    return PriceNormalizationResult(
        raw_price=raw_price,
        normalized_price=normalized,
        tick_size=tick_size,
        decimal_places=dp,
        price_rule_status=NORM_STATUS_APPLIED,
        price_role=price_role,
        rule_source=tick_rule.source,
    )


def normalize_prices(
    prices: tuple[Decimal, ...],
    tick_rule: TickRule,
    price_role: str,
) -> tuple[tuple[Decimal, ...], list[PriceNormalizationResult]]:
    """Normalize a tuple of prices, returning normalized tuple and audit list."""
    normalized: list[Decimal] = []
    audit: list[PriceNormalizationResult] = []
    for p in prices:
        result = normalize_price_to_tick(p, tick_rule, price_role)
        normalized.append(result.normalized_price)
        audit.append(result)
    return tuple(normalized), audit


def normalize_optional_price(
    price: Decimal | None,
    tick_rule: TickRule,
    price_role: str,
) -> tuple[Decimal | None, PriceNormalizationResult | None]:
    """Normalize an optional price, returning normalized value and optional audit."""
    if price is None:
        return None, None
    result = normalize_price_to_tick(price, tick_rule, price_role)
    return result.normalized_price, result
