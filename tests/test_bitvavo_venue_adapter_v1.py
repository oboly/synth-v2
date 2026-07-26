"""
Tests for src/market_rules/bitvavo_venue_adapter_v1.py.

Pure Python transform tests — no network call. Fixture rows are shaped
exactly like Bitvavo's public /v2/markets response, including the 8 A+
Week-1 markets as observed live during the P0 implementation session
(2026-07-25T19:43:17Z), to prove required metadata resolves for all of
them per the P0 task's backfill requirement.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from src.market_rules.bitvavo_venue_adapter_v1 import (
    BITVAVO_SUPPORTED_TIME_IN_FORCE,
    parse_bitvavo_market_row,
    parse_bitvavo_markets_response,
)
from src.market_rules.venue_execution_constraints_v1 import (
    SOURCE_BITVAVO_PUBLIC_MARKETS_API_V2,
    STATUS_FRESH,
)


_A_PLUS_MARKETS = (
    "DEEP-EUR", "RED-EUR", "NEAR-EUR", "NOT-EUR", "TAO-EUR", "POL-EUR", "LDO-EUR", "BTC-EUR",
)

# Exact values observed live from https://api.bitvavo.com/v2/markets at
# 2026-07-25T19:43:17Z during this implementation session.
_OBSERVED_ROWS = {
    "DEEP-EUR": {"tickSize": "0.00000100", "quantityDecimals": 8, "minOrderInBaseAsset": "328.18903132", "minOrderInQuoteAsset": "5.00"},
    "RED-EUR":  {"tickSize": "0.0000100",  "quantityDecimals": 8, "minOrderInBaseAsset": "58.33696571",   "minOrderInQuoteAsset": "5.00"},
    "NEAR-EUR": {"tickSize": "0.000100",   "quantityDecimals": 8, "minOrderInBaseAsset": "3.07148361",    "minOrderInQuoteAsset": "5.00"},
    "NOT-EUR":  {"tickSize": "0.000000010","quantityDecimals": 3, "minOrderInBaseAsset": "15841.648",     "minOrderInQuoteAsset": "5.00"},
    "TAO-EUR":  {"tickSize": "0.0100",     "quantityDecimals": 8, "minOrderInBaseAsset": "0.02889021",    "minOrderInQuoteAsset": "5.00"},
    "POL-EUR":  {"tickSize": "0.0000010",  "quantityDecimals": 8, "minOrderInBaseAsset": "75.27700538",   "minOrderInQuoteAsset": "5.00"},
    "LDO-EUR":  {"tickSize": "0.0000100",  "quantityDecimals": 8, "minOrderInBaseAsset": "15.00183796",   "minOrderInQuoteAsset": "5.00"},
    "BTC-EUR":  {"tickSize": "1.00",       "quantityDecimals": 8, "minOrderInBaseAsset": "0.00008817",    "minOrderInQuoteAsset": "5.00"},
}


def _row(market: str, *, status: str = "trading", **overrides) -> dict:
    base = {
        "market": market,
        "status": status,
        "orderTypes": ["market", "limit", "stopLoss", "stopLossLimit", "takeProfit", "takeProfitLimit"],
        "pricePrecision": None,  # confirmed deprecated/null on the live endpoint
    }
    base.update(_OBSERVED_ROWS.get(market, {}))
    base.update(overrides)
    return base


class TestAllEightAPlusMarketsResolve:
    def test_all_eight_markets_produce_usable_constraints(self) -> None:
        rows = [_row(m) for m in _A_PLUS_MARKETS]
        result = parse_bitvavo_markets_response(
            rows, markets=set(_A_PLUS_MARKETS),
            synced_ts_utc=datetime(2026, 7, 25, 19, 43, 17, tzinfo=timezone.utc),
        )
        assert set(result.keys()) == set(_A_PLUS_MARKETS)
        for market, constraints in result.items():
            assert constraints.status == STATUS_FRESH
            assert constraints.tick_size > 0
            assert constraints.qty_step_size > 0
            assert constraints.min_base_quantity > 0
            assert constraints.min_quote_notional > 0
            assert constraints.supported_order_types
            assert constraints.supported_time_in_force == BITVAVO_SUPPORTED_TIME_IN_FORCE
            assert constraints.source_provenance == SOURCE_BITVAVO_PUBLIC_MARKETS_API_V2

    def test_btc_tick_size_matches_current_live_field_not_deprecated_static_table(self) -> None:
        # Regression for the discovered discrepancy: the old
        # _BITVAVO_EUR_STATIC_PRECISION fallback implies a 0.1 EUR tick for
        # BTC-EUR (pricePrecision=1); the exchange's current explicit
        # tickSize field is actually "1.00" (a 1 EUR tick).
        row = _row("BTC-EUR")
        constraints = parse_bitvavo_market_row(row)
        assert constraints is not None
        assert constraints.tick_size == Decimal("1.00")
        assert constraints.tick_size != Decimal("0.1")

    def test_not_eur_quantity_decimals_differs_from_others(self) -> None:
        # NOT-EUR has quantityDecimals=3, not the common 8 — proves the
        # adapter reads the per-market field rather than assuming a constant.
        row = _row("NOT-EUR")
        constraints = parse_bitvavo_market_row(row)
        assert constraints is not None
        assert constraints.qty_step_size == Decimal("0.001")


class TestFailClosedOnMissingOrNonTradingMarkets:
    def test_non_trading_status_returns_none(self) -> None:
        row = _row("BTC-EUR", status="halted")
        assert parse_bitvavo_market_row(row) is None

    def test_missing_required_field_returns_none(self) -> None:
        row = _row("BTC-EUR")
        row["tickSize"] = None
        assert parse_bitvavo_market_row(row) is None

    def test_response_parse_omits_unresolvable_markets_rather_than_guessing(self) -> None:
        rows = [_row("BTC-EUR"), _row("RED-EUR", status="halted")]
        result = parse_bitvavo_markets_response(rows, markets={"BTC-EUR", "RED-EUR"})
        assert "BTC-EUR" in result
        assert "RED-EUR" not in result
