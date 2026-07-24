from __future__ import annotations

"""Read-only exact-symbol validation for the enabled Bitvavo EUR asset universe."""

import argparse
from dataclasses import dataclass
from typing import Any, Iterable

from src.common.db import get_db_connection
from src.market.run_bitvavo_market_sync_v1 import fetch_bitvavo_markets


RUNNER_NAME = "validate_bitvavo_enabled_asset_universe_v1"
DEFAULT_QUOTE = "EUR"


@dataclass(frozen=True)
class EnabledUniverseValidation:
    enabled_symbols: tuple[str, ...]
    supported_symbols: tuple[str, ...]
    missing_symbols: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.missing_symbols


def load_enabled_symbols(conn: Any) -> tuple[str, ...]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT symbol
            FROM asset
            WHERE is_enabled = 1
            ORDER BY symbol
            """
        )
        rows = cur.fetchall()
    return tuple(str(row["symbol"]).upper() for row in rows)


def trading_base_symbols(
    raw_markets: Iterable[dict[str, Any]],
    *,
    quote: str = DEFAULT_QUOTE,
) -> tuple[str, ...]:
    expected_quote = quote.upper()
    symbols = {
        str(item.get("base") or "").upper()
        for item in raw_markets
        if str(item.get("quote") or "").upper() == expected_quote
        and str(item.get("status") or "").lower() == "trading"
        and str(item.get("base") or "").strip()
    }
    return tuple(sorted(symbols))


def validate_enabled_universe(
    enabled_symbols: Iterable[str],
    raw_markets: Iterable[dict[str, Any]],
    *,
    quote: str = DEFAULT_QUOTE,
) -> EnabledUniverseValidation:
    enabled = tuple(sorted({str(symbol).upper() for symbol in enabled_symbols}))
    supported = trading_base_symbols(raw_markets, quote=quote)
    missing = tuple(sorted(set(enabled) - set(supported)))
    return EnabledUniverseValidation(
        enabled_symbols=enabled,
        supported_symbols=supported,
        missing_symbols=missing,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only exact-symbol validation of enabled assets against current Bitvavo markets."
    )
    parser.add_argument("--quote", default=DEFAULT_QUOTE)
    args = parser.parse_args()

    print(
        f"STARTED runner={RUNNER_NAME} mode=read_only "
        f"venue=bitvavo quote={args.quote.upper()} worker_count=1"
    )
    conn = get_db_connection()
    try:
        enabled = load_enabled_symbols(conn)
    finally:
        conn.close()

    result = validate_enabled_universe(
        enabled,
        fetch_bitvavo_markets(),
        quote=args.quote,
    )
    print(
        f"enabled_assets={len(result.enabled_symbols)} "
        f"supported_markets={len(result.supported_symbols)} "
        f"mismatch={len(result.missing_symbols)}"
    )
    if result.missing_symbols:
        print(f"missing_symbols={','.join(result.missing_symbols)}")
    print(
        "database_writes=0 candle_writer_invocations=0 broker_private_calls=0 "
        "broker_writes=0 order_submission=0 runtime_changes=0 timer_changes=0"
    )
    status = "PASS" if result.ok else "FAIL"
    print(f"FINISHED runner={RUNNER_NAME} status={status}")
    return 0 if result.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
