from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.common.db import get_connection
from src.market_data.native_short_fib_context_v1 import (
    DEFAULT_OUTPUT_DIR,
    STATUS_SYMBOL_MISSING,
    Candle,
    NativeShortContextRow,
    build_native_short_context_row,
    summarize_context_rows,
    write_context_rows,
)
from src.reporting.account_dashboard_profile_access_v1 import resolve_dashboard_profile_access
from src.reporting.account_scoped_short_trader_dashboard_v1 import (
    DEFAULT_VENUE,
    load_account_scoped_short_dashboard_context,
    validate_profile_slug,
)


RUNNER_NAME = "run_native_short_fib_context_v1"
RUNNER_VERSION = "0.1"
QUOTE_CURRENCY = "EUR"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build the canonical native SHORT fib context bridge from 4h primary and 1h supporting candles. "
            "Market-only, account-agnostic contract; account profile may be used only to select market scope."
        )
    )
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--symbols", default="", help="Comma-separated symbols. Optional if --account-profile is used.")
    parser.add_argument("--account-profile", default="", help="Optional profile used only to derive market scope.")
    parser.add_argument("--write-files", action="store_true")
    parser.add_argument("--output", choices=("summary", "none"), default="summary")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser.parse_args()


def _parse_symbols(text: str) -> list[str]:
    return sorted({part.strip().upper() for part in text.split(",") if part.strip()})


def _load_markets_for_profile(*, account_profile: str, venue: str) -> list[str]:
    validate_profile_slug(account_profile)
    access = resolve_dashboard_profile_access(account_profile=account_profile, venue=venue)
    context = load_account_scoped_short_dashboard_context(
        profile=account_profile,
        account_code=access.trading_account_stable_ref,
        venue=venue,
    )
    return list(context.markets)


def _select_symbols(*, explicit_symbols: list[str], account_profile: str, venue: str) -> tuple[list[str], list[str]]:
    markets: list[str] = []
    if account_profile:
        markets = _load_markets_for_profile(account_profile=account_profile, venue=venue)
    scoped_symbols = [market.split("-", 1)[0].upper() for market in markets]
    merged = sorted({*explicit_symbols, *scoped_symbols})
    return merged, markets


def _fetch_candles_by_symbol(
    *,
    conn: Any,
    venue: str,
    interval_code: str,
    symbols: list[str],
    since_utc: datetime,
) -> dict[str, list[Candle]]:
    if not symbols:
        return {}
    placeholders = ",".join(["%s"] * len(symbols))
    sql = f"""
    SELECT
        a.symbol,
        c.close_ts_utc,
        c.open_price,
        c.high_price,
        c.low_price,
        c.close_price
    FROM obs_market_candle c
    JOIN asset a
      ON a.asset_id = c.asset_id
    WHERE c.venue = %s
      AND c.interval_code = %s
      AND a.symbol IN ({placeholders})
      AND c.close_ts_utc >= %s
    ORDER BY a.symbol ASC, c.close_ts_utc ASC
    """
    with conn.cursor() as cur:
        cur.execute(sql, (venue, interval_code, *symbols, since_utc))
        rows = list(cur.fetchall())
    grouped: dict[str, list[Candle]] = defaultdict(list)
    for row in rows:
        symbol = str(row.get("symbol") or "").upper()
        close_ts = row.get("close_ts_utc")
        if not symbol or close_ts is None:
            continue
        close_ts_utc = close_ts.replace(tzinfo=UTC) if close_ts.tzinfo is None else close_ts.astimezone(UTC)
        grouped[symbol].append(
            Candle(
                close_ts_utc=close_ts_utc,
                open_price=Decimal(str(row["open_price"])),
                high_price=Decimal(str(row["high_price"])),
                low_price=Decimal(str(row["low_price"])),
                close_price=Decimal(str(row["close_price"])),
            )
        )
    return grouped


def build_rows_for_symbols(
    *,
    venue: str,
    symbols: list[str],
    now_utc: datetime,
) -> list[NativeShortContextRow]:
    primary_since = now_utc - timedelta(days=60)
    support_since = now_utc - timedelta(days=21)
    conn = get_connection()
    try:
        primary_by_symbol = _fetch_candles_by_symbol(
            conn=conn,
            venue=venue,
            interval_code="4h",
            symbols=symbols,
            since_utc=primary_since,
        )
        support_by_symbol = _fetch_candles_by_symbol(
            conn=conn,
            venue=venue,
            interval_code="1h",
            symbols=symbols,
            since_utc=support_since,
        )
    finally:
        conn.close()

    rows: list[NativeShortContextRow] = []
    for symbol in symbols:
        primary = primary_by_symbol.get(symbol, [])
        support = support_by_symbol.get(symbol, [])
        if not primary and not support:
            rows.append(
                NativeShortContextRow(
                    **{
                        **build_native_short_context_row(
                            symbol=symbol,
                            venue=venue,
                            primary_candles=[],
                            support_candles=[],
                            now_utc=now_utc,
                        ).__dict__,
                        "context_status": STATUS_SYMBOL_MISSING,
                    }
                )
            )
            continue
        rows.append(
            build_native_short_context_row(
                symbol=symbol,
                venue=venue,
                primary_candles=primary,
                support_candles=support,
                now_utc=now_utc,
            )
        )
    return rows


def print_summary(*, rows: list[NativeShortContextRow], scope_market_count: int, output_dir: Path) -> None:
    summary = summarize_context_rows(rows)
    print(f"report={RUNNER_NAME}")
    print(f"version={RUNNER_VERSION}")
    print(f"scope_market_count={scope_market_count}")
    print(f"row_count={len(rows)}")
    print(f"output_dir={output_dir}")
    print("broker_private_calls=0")
    print("broker_writes=0")
    print("order_submission=0")
    print("live_orders=0")
    print("decision_gate=none")
    print("execution_planner=none")
    print("executor=none")
    print(
        "native_short_coverage="
        + " ; ".join(
            f"{key}:{summary.get(key, 0)}"
            for key in (
                "NATIVE_SHORT_CONTEXT_AVAILABLE",
                "INSUFFICIENT_4H_HISTORY",
                "INSUFFICIENT_1H_HISTORY",
                "CONTEXT_INVALID_OR_STALE",
                "SYMBOL_CONTEXT_MISSING",
            )
        )
    )
    for row in rows:
        print(
            f"{row.symbol}: status={row.context_status}"
            f" lifecycle={row.primary_4h_lifecycle_state}"
            f" support={row.supporting_1h_state}"
        )


def main() -> int:
    args = parse_args()
    explicit_symbols = _parse_symbols(args.symbols)
    symbols, scoped_markets = _select_symbols(
        explicit_symbols=explicit_symbols,
        account_profile=args.account_profile.strip(),
        venue=args.venue,
    )
    if not symbols:
        raise SystemExit("No symbols selected. Provide --symbols and/or --account-profile.")
    now_utc = datetime.now(UTC)
    rows = build_rows_for_symbols(
        venue=args.venue,
        symbols=symbols,
        now_utc=now_utc,
    )
    output_dir = Path(args.output_dir)
    if args.write_files:
        write_context_rows(rows=rows, output_dir=output_dir)
    if args.output == "summary":
        scope_market_count = len(scoped_markets) if scoped_markets else len(symbols)
        print_summary(rows=rows, scope_market_count=scope_market_count, output_dir=output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
