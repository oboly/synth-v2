from __future__ import annotations

from src.market.validate_bitvavo_enabled_asset_universe_v1 import (
    trading_base_symbols,
    validate_enabled_universe,
)


def _market(base: str, *, quote: str = "EUR", status: str = "trading") -> dict[str, str]:
    return {
        "market": f"{base}-{quote}",
        "base": base,
        "quote": quote,
        "status": status,
    }


def test_enabled_assets_map_to_exact_current_trading_eur_symbols() -> None:
    result = validate_enabled_universe(
        ["BTC", "ETH"],
        [_market("BTC"), _market("ETH"), _market("BTC", quote="USDT")],
    )
    assert result.ok
    assert result.missing_symbols == ()


def test_missing_enabled_asset_fails_closed() -> None:
    result = validate_enabled_universe(["BTC", "STALE"], [_market("BTC")])
    assert not result.ok
    assert result.missing_symbols == ("STALE",)


def test_disabled_or_delisted_assets_do_not_enter_enabled_universe() -> None:
    enabled_symbols = ["BTC"]
    result = validate_enabled_universe(
        enabled_symbols,
        [_market("BTC"), _market("DELISTED", status="halted")],
    )
    assert result.ok
    assert "DELISTED" not in result.enabled_symbols
    assert "DELISTED" not in trading_base_symbols([_market("DELISTED", status="halted")])


def test_renamed_symbol_requires_explicit_canonical_row() -> None:
    result = validate_enabled_universe(["OLD"], [_market("NEW")])
    assert result.missing_symbols == ("OLD",)

    explicit_result = validate_enabled_universe(["NEW"], [_market("NEW")])
    assert explicit_result.ok
    assert explicit_result.enabled_symbols == ("NEW",)


def test_validation_does_not_silently_alias_symbols() -> None:
    result = validate_enabled_universe(["MATIC"], [_market("POL")])
    assert result.missing_symbols == ("MATIC",)
