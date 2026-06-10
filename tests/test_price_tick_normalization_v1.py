"""
Unit tests for src/market_rules/price_tick_normalization_v1.py

Covers:
  - tick_size_from_precision
  - normalize_price_to_tick: exact boundary, round-down above tick,
    tiny markets, high-price markets, missing rule, Decimal-only
  - resolve_tick_rule: DB-first, static fallback, missing
  - normalize_prices / normalize_optional_price helpers
  - Static precision table: configured markets have metadata
  - Idempotency: already-valid price unchanged
  - BUY rounds down, SELL rounds down
  - DISPLAY_ONLY uses nearest (round half-up)
  - MISSING_TICK_RULE: visible status, raw price preserved

broker_private_calls=0
broker_writes=0
order_submission=0
executor=none
"""
from __future__ import annotations

import sqlite3
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.market_rules.price_tick_normalization_v1 import (
    NORM_STATUS_APPLIED,
    NORM_STATUS_DISPLAY_ONLY,
    NORM_STATUS_MISSING,
    PRICE_ROLE_DISPLAY_ONLY,
    PRICE_ROLE_INVALIDATION,
    PRICE_ROLE_REENTRY_BUY,
    PRICE_ROLE_TARGET_SELL,
    TICK_RULE_SOURCE_DB,
    TICK_RULE_SOURCE_MISSING,
    TICK_RULE_SOURCE_STATIC,
    TickRule,
    _BITVAVO_EUR_STATIC_PRECISION,
    load_tick_rules_from_db,
    normalize_optional_price,
    normalize_price_to_tick,
    normalize_prices,
    resolve_tick_rule,
    resolve_tick_rule_from_static,
    tick_size_from_precision,
)


# ---------------------------------------------------------------------------
# tick_size_from_precision
# ---------------------------------------------------------------------------

def test_tick_size_precision_5() -> None:
    assert tick_size_from_precision(5) == Decimal("0.00001")


def test_tick_size_precision_8() -> None:
    assert tick_size_from_precision(8) == Decimal("0.00000001")


def test_tick_size_precision_2() -> None:
    assert tick_size_from_precision(2) == Decimal("0.01")


def test_tick_size_precision_1() -> None:
    assert tick_size_from_precision(1) == Decimal("0.1")


def test_tick_size_is_decimal_not_float() -> None:
    result = tick_size_from_precision(5)
    assert isinstance(result, Decimal)


# ---------------------------------------------------------------------------
# normalize_price_to_tick — exact boundaries
# ---------------------------------------------------------------------------

def _ldo_rule() -> TickRule:
    return TickRule(
        venue="bitvavo", market="LDO-EUR",
        tick_size=Decimal("0.00001"), decimal_places=5,
        source=TICK_RULE_SOURCE_STATIC,
    )


def _pepe_rule() -> TickRule:
    return TickRule(
        venue="bitvavo", market="PEPE-EUR",
        tick_size=Decimal("0.00000001"), decimal_places=8,
        source=TICK_RULE_SOURCE_STATIC,
    )


def _sol_rule() -> TickRule:
    return TickRule(
        venue="bitvavo", market="SOL-EUR",
        tick_size=Decimal("0.0001"), decimal_places=4,
        source=TICK_RULE_SOURCE_STATIC,
    )


def _eth_rule() -> TickRule:
    return TickRule(
        venue="bitvavo", market="ETH-EUR",
        tick_size=Decimal("0.01"), decimal_places=2,
        source=TICK_RULE_SOURCE_STATIC,
    )


def test_ldo_sell_exact_tick_boundary_unchanged() -> None:
    """A price that is already on a valid tick must not change."""
    raw = Decimal("0.23260")
    result = normalize_price_to_tick(raw, _ldo_rule(), PRICE_ROLE_TARGET_SELL)
    assert result.normalized_price == Decimal("0.23260")
    assert result.price_rule_status == NORM_STATUS_APPLIED


def test_ldo_sell_floors_to_nearest_tick_below() -> None:
    """LDO 0.232605 SELL → 0.23260 (floor, not 0.23261)."""
    raw = Decimal("0.232605")
    result = normalize_price_to_tick(raw, _ldo_rule(), PRICE_ROLE_TARGET_SELL)
    assert result.normalized_price == Decimal("0.23260")
    assert result.normalized_price < raw


def test_ldo_sell_production_example() -> None:
    """Exact production example from task description: 0.232605 → 0.23260."""
    result = normalize_price_to_tick(
        Decimal("0.232605"), _ldo_rule(), PRICE_ROLE_TARGET_SELL
    )
    assert result.normalized_price == Decimal("0.23260")


def test_ldo_buy_rounds_down() -> None:
    """BUY also rounds down (pay no more than the analytical level)."""
    raw = Decimal("0.232609")
    result = normalize_price_to_tick(raw, _ldo_rule(), PRICE_ROLE_REENTRY_BUY)
    assert result.normalized_price == Decimal("0.23260")


def test_ldo_price_already_aligned_buy() -> None:
    raw = Decimal("0.23261")
    result = normalize_price_to_tick(raw, _ldo_rule(), PRICE_ROLE_REENTRY_BUY)
    assert result.normalized_price == Decimal("0.23261")


# ---------------------------------------------------------------------------
# Tiny markets (8dp: PEPE/MOG/SHIB/FLOKI)
# ---------------------------------------------------------------------------

def test_pepe_eur_rounds_down() -> None:
    raw = Decimal("0.000007563")
    result = normalize_price_to_tick(raw, _pepe_rule(), PRICE_ROLE_TARGET_SELL)
    assert result.normalized_price == Decimal("0.00000756")
    assert result.decimal_places == 8


def test_pepe_eur_exact_boundary_unchanged() -> None:
    raw = Decimal("0.00000756")
    result = normalize_price_to_tick(raw, _pepe_rule(), PRICE_ROLE_TARGET_SELL)
    assert result.normalized_price == Decimal("0.00000756")


def test_pepe_normalized_has_8_decimal_places() -> None:
    raw = Decimal("0.000007562345")
    result = normalize_price_to_tick(raw, _pepe_rule(), PRICE_ROLE_TARGET_SELL)
    _, _, exp = result.normalized_price.as_tuple()
    assert -exp == 8


# ---------------------------------------------------------------------------
# High-price markets (ETH/SOL)
# ---------------------------------------------------------------------------

def test_eth_eur_rounds_down_2dp() -> None:
    raw = Decimal("2573.999")
    result = normalize_price_to_tick(raw, _eth_rule(), PRICE_ROLE_TARGET_SELL)
    assert result.normalized_price == Decimal("2573.99")


def test_eth_eur_exact_unchanged() -> None:
    raw = Decimal("2574.00")
    result = normalize_price_to_tick(raw, _eth_rule(), PRICE_ROLE_TARGET_SELL)
    assert result.normalized_price == Decimal("2574.00")


def test_sol_eur_4dp_rounds_down() -> None:
    raw = Decimal("143.56789")
    result = normalize_price_to_tick(raw, _sol_rule(), PRICE_ROLE_TARGET_SELL)
    assert result.normalized_price == Decimal("143.5678")


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

def test_normalization_is_idempotent() -> None:
    """Normalizing a normalized price produces the same price."""
    raw = Decimal("0.232605")
    r1 = normalize_price_to_tick(raw, _ldo_rule(), PRICE_ROLE_TARGET_SELL)
    r2 = normalize_price_to_tick(r1.normalized_price, _ldo_rule(), PRICE_ROLE_TARGET_SELL)
    assert r1.normalized_price == r2.normalized_price


def test_pepe_normalization_is_idempotent() -> None:
    raw = Decimal("0.000007563")
    r1 = normalize_price_to_tick(raw, _pepe_rule(), PRICE_ROLE_TARGET_SELL)
    r2 = normalize_price_to_tick(r1.normalized_price, _pepe_rule(), PRICE_ROLE_TARGET_SELL)
    assert r1.normalized_price == r2.normalized_price


# ---------------------------------------------------------------------------
# DISPLAY_ONLY uses nearest (round half-up)
# ---------------------------------------------------------------------------

def test_display_only_uses_round_half_up() -> None:
    raw = Decimal("0.232605")  # exactly halfway above 0.23260, below 0.23261
    result = normalize_price_to_tick(raw, _ldo_rule(), PRICE_ROLE_DISPLAY_ONLY)
    # 0.232605 / 0.00001 = 23260.5 → ROUND_HALF_UP → 23261 → 0.23261
    assert result.normalized_price == Decimal("0.23261")
    assert result.price_rule_status == NORM_STATUS_DISPLAY_ONLY


def test_display_only_status_present() -> None:
    result = normalize_price_to_tick(
        Decimal("0.232600"), _ldo_rule(), PRICE_ROLE_DISPLAY_ONLY
    )
    assert result.price_rule_status == NORM_STATUS_DISPLAY_ONLY


# ---------------------------------------------------------------------------
# MISSING_TICK_RULE — fail-closed, raw price preserved
# ---------------------------------------------------------------------------

def _missing_rule() -> TickRule:
    return TickRule(
        venue="bitvavo", market="UNKNOWN-EUR",
        tick_size=Decimal("0"), decimal_places=0,
        source=TICK_RULE_SOURCE_MISSING,
    )


def test_missing_rule_returns_raw_price() -> None:
    raw = Decimal("0.123456789")
    result = normalize_price_to_tick(raw, _missing_rule(), PRICE_ROLE_TARGET_SELL)
    assert result.normalized_price == raw


def test_missing_rule_status_is_missing() -> None:
    result = normalize_price_to_tick(
        Decimal("1.0"), _missing_rule(), PRICE_ROLE_TARGET_SELL
    )
    assert result.price_rule_status == NORM_STATUS_MISSING


def test_missing_rule_display_only_status() -> None:
    result = normalize_price_to_tick(
        Decimal("1.0"), _missing_rule(), PRICE_ROLE_DISPLAY_ONLY
    )
    assert result.price_rule_status == NORM_STATUS_DISPLAY_ONLY


def test_missing_rule_tick_size_is_none() -> None:
    result = normalize_price_to_tick(
        Decimal("1.0"), _missing_rule(), PRICE_ROLE_TARGET_SELL
    )
    assert result.tick_size is None
    assert result.decimal_places is None


# ---------------------------------------------------------------------------
# Decimal-only — no float artifact
# ---------------------------------------------------------------------------

def test_result_is_decimal_not_float() -> None:
    result = normalize_price_to_tick(
        Decimal("0.232605"), _ldo_rule(), PRICE_ROLE_TARGET_SELL
    )
    assert isinstance(result.normalized_price, Decimal)
    assert isinstance(result.raw_price, Decimal)


def test_no_float_in_computation() -> None:
    """Verify tick_size and normalized_price are Decimal throughout."""
    result = normalize_price_to_tick(
        Decimal("0.000007563"), _pepe_rule(), PRICE_ROLE_TARGET_SELL
    )
    assert isinstance(result.tick_size, Decimal)
    assert isinstance(result.normalized_price, Decimal)


# ---------------------------------------------------------------------------
# Trailing zeroes preserved
# ---------------------------------------------------------------------------

def test_trailing_zeroes_preserved_ldo() -> None:
    """0.23260 (5dp) must display as '0.23260' not '0.2326'."""
    result = normalize_price_to_tick(
        Decimal("0.232605"), _ldo_rule(), PRICE_ROLE_TARGET_SELL
    )
    s = str(result.normalized_price)
    assert s.count(".") == 1
    decimal_part = s.split(".")[1]
    assert len(decimal_part) == 5, f"Expected 5dp, got: {s!r}"


def test_trailing_zeroes_preserved_pepe() -> None:
    result = normalize_price_to_tick(
        Decimal("0.000007000001"), _pepe_rule(), PRICE_ROLE_TARGET_SELL
    )
    s = str(result.normalized_price)
    decimal_part = s.split(".")[1]
    assert len(decimal_part) == 8, f"Expected 8dp, got: {s!r}"


# ---------------------------------------------------------------------------
# normalize_prices / normalize_optional_price helpers
# ---------------------------------------------------------------------------

def test_normalize_prices_empty_tuple() -> None:
    normalized, audits = normalize_prices((), _ldo_rule(), PRICE_ROLE_TARGET_SELL)
    assert normalized == ()
    assert audits == []


def test_normalize_prices_multiple() -> None:
    prices = (Decimal("0.232605"), Decimal("0.26000"), Decimal("0.30001"))
    normalized, audits = normalize_prices(prices, _ldo_rule(), PRICE_ROLE_TARGET_SELL)
    assert len(normalized) == 3
    assert len(audits) == 3
    assert normalized[0] == Decimal("0.23260")
    assert normalized[1] == Decimal("0.26000")
    assert normalized[2] == Decimal("0.30001")


def test_normalize_optional_price_none() -> None:
    v, result = normalize_optional_price(None, _ldo_rule(), PRICE_ROLE_TARGET_SELL)
    assert v is None
    assert result is None


def test_normalize_optional_price_value() -> None:
    v, result = normalize_optional_price(
        Decimal("0.232605"), _ldo_rule(), PRICE_ROLE_TARGET_SELL
    )
    assert v == Decimal("0.23260")
    assert result is not None
    assert result.price_rule_status == NORM_STATUS_APPLIED


# ---------------------------------------------------------------------------
# resolve_tick_rule_from_static
# ---------------------------------------------------------------------------

def test_static_ldo_eur_returns_5dp() -> None:
    rule = resolve_tick_rule_from_static("bitvavo", "LDO-EUR")
    assert rule is not None
    assert rule.decimal_places == 5
    assert rule.tick_size == Decimal("0.00001")
    assert rule.source == TICK_RULE_SOURCE_STATIC


def test_static_pepe_eur_returns_8dp() -> None:
    rule = resolve_tick_rule_from_static("bitvavo", "PEPE-EUR")
    assert rule is not None
    assert rule.decimal_places == 8


def test_static_hot_eur_returns_6dp() -> None:
    rule = resolve_tick_rule_from_static("bitvavo", "HOT-EUR")
    assert rule is not None
    assert rule.decimal_places == 6


def test_static_vet_eur_returns_6dp() -> None:
    rule = resolve_tick_rule_from_static("bitvavo", "VET-EUR")
    assert rule is not None
    assert rule.decimal_places == 6


def test_static_sol_eur_returns_4dp() -> None:
    rule = resolve_tick_rule_from_static("bitvavo", "SOL-EUR")
    assert rule is not None
    assert rule.decimal_places == 4


def test_static_eth_eur_returns_2dp() -> None:
    rule = resolve_tick_rule_from_static("bitvavo", "ETH-EUR")
    assert rule is not None
    assert rule.decimal_places == 2


def test_static_unknown_market_returns_none() -> None:
    rule = resolve_tick_rule_from_static("bitvavo", "NOTREAL-EUR")
    assert rule is None


def test_static_wrong_venue_returns_none() -> None:
    rule = resolve_tick_rule_from_static("kraken", "LDO-EUR")
    assert rule is None


# ---------------------------------------------------------------------------
# resolve_tick_rule: DB first, static fallback, missing
# ---------------------------------------------------------------------------

def test_resolve_uses_db_over_static() -> None:
    db_rules = {
        "LDO-EUR": TickRule(
            venue="bitvavo", market="LDO-EUR",
            tick_size=Decimal("0.0001"), decimal_places=4,
            source=TICK_RULE_SOURCE_DB,
        )
    }
    rule = resolve_tick_rule(venue="bitvavo", market="LDO-EUR", db_rules=db_rules)
    assert rule.source == TICK_RULE_SOURCE_DB
    assert rule.decimal_places == 4  # DB value, not static 5


def test_resolve_falls_back_to_static_when_db_missing() -> None:
    rule = resolve_tick_rule(venue="bitvavo", market="LDO-EUR", db_rules={})
    assert rule.source == TICK_RULE_SOURCE_STATIC
    assert rule.decimal_places == 5


def test_resolve_returns_missing_when_no_source() -> None:
    rule = resolve_tick_rule(venue="bitvavo", market="NOTREAL-EUR", db_rules={})
    assert rule.source == TICK_RULE_SOURCE_MISSING


def test_resolve_no_db_rules_uses_static() -> None:
    rule = resolve_tick_rule(venue="bitvavo", market="ETH-EUR")
    assert rule.source == TICK_RULE_SOURCE_STATIC


# ---------------------------------------------------------------------------
# load_tick_rules_from_db
# ---------------------------------------------------------------------------

_VENUE_MARKET_SCHEMA = """
CREATE TABLE IF NOT EXISTS venue_market (
    venue_market_id INTEGER PRIMARY KEY AUTOINCREMENT,
    venue TEXT NOT NULL,
    market TEXT NOT NULL,
    price_precision INTEGER,
    qty_precision INTEGER
);
"""


class _MockCursor:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._cur = conn.cursor()

    def execute(self, sql: str, params: tuple = ()) -> None:
        normalized = sql.replace("%s", "?")
        self._cur.execute(normalized, params)

    def fetchall(self) -> list:
        return [dict(r) for r in self._cur.fetchall()]

    def __enter__(self) -> "_MockCursor":
        return self

    def __exit__(self, *args: Any) -> None:
        pass


class _MockConn:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def cursor(self) -> _MockCursor:
        return _MockCursor(self._conn)


def _fresh_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_VENUE_MARKET_SCHEMA)
    return conn


def test_load_tick_rules_from_db_returns_rule() -> None:
    raw = _fresh_db()
    raw.execute(
        "INSERT INTO venue_market (venue, market, price_precision) VALUES (?, ?, ?)",
        ("bitvavo", "LDO-EUR", 5),
    )
    raw.commit()
    rules = load_tick_rules_from_db(_MockConn(raw), venue="bitvavo", markets=["LDO-EUR"])
    assert "LDO-EUR" in rules
    assert rules["LDO-EUR"].decimal_places == 5
    assert rules["LDO-EUR"].source == TICK_RULE_SOURCE_DB


def test_load_tick_rules_from_db_skips_null_precision() -> None:
    raw = _fresh_db()
    raw.execute(
        "INSERT INTO venue_market (venue, market, price_precision) VALUES (?, ?, ?)",
        ("bitvavo", "NOPRECISION-EUR", None),
    )
    raw.commit()
    rules = load_tick_rules_from_db(
        _MockConn(raw), venue="bitvavo", markets=["NOPRECISION-EUR"]
    )
    assert "NOPRECISION-EUR" not in rules


def test_load_tick_rules_from_db_empty_markets() -> None:
    raw = _fresh_db()
    rules = load_tick_rules_from_db(_MockConn(raw), venue="bitvavo", markets=[])
    assert rules == {}


def test_load_tick_rules_from_db_multiple_markets() -> None:
    raw = _fresh_db()
    raw.executemany(
        "INSERT INTO venue_market (venue, market, price_precision) VALUES (?, ?, ?)",
        [("bitvavo", "LDO-EUR", 5), ("bitvavo", "ETH-EUR", 2), ("bitvavo", "PEPE-EUR", 8)],
    )
    raw.commit()
    rules = load_tick_rules_from_db(
        _MockConn(raw), venue="bitvavo", markets=["LDO-EUR", "ETH-EUR", "PEPE-EUR"]
    )
    assert len(rules) == 3
    assert rules["ETH-EUR"].decimal_places == 2
    assert rules["PEPE-EUR"].decimal_places == 8


# ---------------------------------------------------------------------------
# Static precision table completeness: configured Synth markets have metadata
# ---------------------------------------------------------------------------

_SYNTH_CONFIGURED_MARKETS = [
    "ALGO-EUR", "CC-EUR", "FET-EUR", "FLOKI-EUR", "HBAR-EUR",
    "HNT-EUR", "HOT-EUR", "IOST-EUR", "MOG-EUR", "PEPE-EUR",
    "RLC-EUR", "SHIB-EUR", "SOL-EUR", "SUI-EUR", "THETA-EUR",
    "VET-EUR", "XPL-EUR", "XRP-EUR", "LDO-EUR", "RED-EUR",
    "ICP-EUR", "ETH-EUR", "AAVE-EUR", "BTC-EUR",
]


def test_all_configured_synth_markets_have_static_metadata() -> None:
    missing = [m for m in _SYNTH_CONFIGURED_MARKETS if m not in _BITVAVO_EUR_STATIC_PRECISION]
    assert missing == [], f"Markets missing static precision: {missing}"


def test_all_static_entries_have_positive_decimal_places() -> None:
    for market, dp in _BITVAVO_EUR_STATIC_PRECISION.items():
        assert dp > 0, f"{market} has non-positive decimal_places={dp}"


def test_all_static_entries_have_valid_tick_size() -> None:
    for market, dp in _BITVAVO_EUR_STATIC_PRECISION.items():
        tick = tick_size_from_precision(dp)
        assert tick > Decimal("0"), f"{market} has zero tick_size"


if __name__ == "__main__":
    tests = [
        test_tick_size_precision_5,
        test_tick_size_precision_8,
        test_tick_size_precision_2,
        test_tick_size_precision_1,
        test_tick_size_is_decimal_not_float,
        test_ldo_sell_exact_tick_boundary_unchanged,
        test_ldo_sell_floors_to_nearest_tick_below,
        test_ldo_sell_production_example,
        test_ldo_buy_rounds_down,
        test_ldo_price_already_aligned_buy,
        test_pepe_eur_rounds_down,
        test_pepe_eur_exact_boundary_unchanged,
        test_pepe_normalized_has_8_decimal_places,
        test_eth_eur_rounds_down_2dp,
        test_eth_eur_exact_unchanged,
        test_sol_eur_4dp_rounds_down,
        test_normalization_is_idempotent,
        test_pepe_normalization_is_idempotent,
        test_display_only_uses_round_half_up,
        test_display_only_status_present,
        test_missing_rule_returns_raw_price,
        test_missing_rule_status_is_missing,
        test_missing_rule_display_only_status,
        test_missing_rule_tick_size_is_none,
        test_result_is_decimal_not_float,
        test_no_float_in_computation,
        test_trailing_zeroes_preserved_ldo,
        test_trailing_zeroes_preserved_pepe,
        test_normalize_prices_empty_tuple,
        test_normalize_prices_multiple,
        test_normalize_optional_price_none,
        test_normalize_optional_price_value,
        test_static_ldo_eur_returns_5dp,
        test_static_pepe_eur_returns_8dp,
        test_static_hot_eur_returns_6dp,
        test_static_vet_eur_returns_6dp,
        test_static_sol_eur_returns_4dp,
        test_static_eth_eur_returns_2dp,
        test_static_unknown_market_returns_none,
        test_static_wrong_venue_returns_none,
        test_resolve_uses_db_over_static,
        test_resolve_falls_back_to_static_when_db_missing,
        test_resolve_returns_missing_when_no_source,
        test_resolve_no_db_rules_uses_static,
        test_load_tick_rules_from_db_returns_rule,
        test_load_tick_rules_from_db_skips_null_precision,
        test_load_tick_rules_from_db_empty_markets,
        test_load_tick_rules_from_db_multiple_markets,
        test_all_configured_synth_markets_have_static_metadata,
        test_all_static_entries_have_positive_decimal_places,
        test_all_static_entries_have_valid_tick_size,
    ]
    for t in tests:
        t()
    print("ok")
