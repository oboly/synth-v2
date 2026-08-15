from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pymysql
from dotenv import load_dotenv

from src.common.db import get_db_connection


WRITER_NAME = "broker_account_position_snapshot_writer_v1"
WRITER_VERSION = "0.1"

DEFAULT_ACCOUNT_CODE = "bitvavo_synth_read"
DEFAULT_VENUE = "bitvavo"
DEFAULT_INTERVAL = "1h"
DEFAULT_BALANCE_SOURCE_NAME = "bitvavo_private_balance_read_v1"

SOURCE_NAME = "bitvavo_private_balance_position_snapshot_v1"


@dataclass(frozen=True)
class TradingAccount:
    trading_account_id: int
    account_code: str
    venue: str
    account_mode: str
    enabled: int
    live_trading_enabled: int


@dataclass(frozen=True)
class BalanceRow:
    currency_code: str
    available_amount: Decimal
    reserved_amount: Decimal
    total_amount: Decimal
    snapshot_ts_utc: Any


@dataclass(frozen=True)
class PriceRow:
    symbol: str
    price_eur: Decimal
    price_ts_utc: Any


@dataclass(frozen=True)
class PositionRow:
    asset_id: int
    symbol: str
    quantity_base: Decimal
    available_quantity_base: Decimal
    reserved_quantity_base: Decimal
    mark_price_eur: Decimal | None
    raw_json: str


@dataclass(frozen=True)
class WriteResult:
    symbol: str
    action: str
    row_id: int | None


def decimal_value(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def format_decimal(value: Any) -> str:
    if value is None:
        return ""

    dec = Decimal(str(value))
    out = format(dec, "f")

    if "." in out:
        out = out.rstrip("0").rstrip(".")

    return out or "0"


def broker_write_permission_state() -> str:
    expected = "I_UNDERSTAND_THIS_PLACES_REAL_ORDERS"
    actual = os.getenv("SYNTH_BROKER_WRITE_PERMISSION")

    if actual == expected:
        return "GRANTED"
    if actual:
        return "PRESENT_BUT_NOT_GRANTED"
    return "MISSING"


def detect_candle_columns(conn: Any) -> tuple[str, str]:
    sql = """
    SELECT column_name
    FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'obs_market_candle'
      AND column_name IN (
          'close',
          'close_price',
          'close_eur',
          'price_close',
          'open_ts_utc',
          'close_ts_utc'
      )
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql)
        cols = {str(row["column_name"]) for row in cur.fetchall()}

    ts_col = "close_ts_utc" if "close_ts_utc" in cols else "open_ts_utc"

    for price_col in ("close_price", "close", "close_eur", "price_close"):
        if price_col in cols:
            return ts_col, price_col

    raise RuntimeError("Could not detect close price column in obs_market_candle.")


def fetch_trading_account(conn: Any, *, account_code: str, venue: str) -> TradingAccount:
    sql = """
    SELECT
        trading_account_id,
        account_code,
        venue,
        account_mode,
        enabled,
        live_trading_enabled
    FROM trading_account
    WHERE account_code = %s
      AND venue = %s
    LIMIT 1
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, (account_code, venue))
        row = cur.fetchone()

    if not row:
        raise RuntimeError(
            f"Trading account not found: account_code={account_code} venue={venue}"
        )

    account = TradingAccount(
        trading_account_id=int(row["trading_account_id"]),
        account_code=str(row["account_code"]),
        venue=str(row["venue"]),
        account_mode=str(row["account_mode"]),
        enabled=int(row["enabled"]),
        live_trading_enabled=int(row["live_trading_enabled"]),
    )

    if account.enabled != 1:
        raise RuntimeError(f"Trading account disabled: account_code={account.account_code}")

    if account.live_trading_enabled != 0:
        raise RuntimeError(
            "Refusing position snapshot writer because trading_account.live_trading_enabled is not 0."
        )

    return account


def fetch_latest_balance_snapshot_ts(
    conn: Any,
    *,
    account: TradingAccount,
    source_name: str,
) -> Any | None:
    sql = """
    SELECT MAX(snapshot_ts_utc) AS latest_snapshot_ts_utc
    FROM trading_account_balance_snapshot
    WHERE trading_account_id = %s
      AND venue = %s
      AND source_name = %s
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, (account.trading_account_id, account.venue, source_name))
        row = cur.fetchone()

    return None if not row else row["latest_snapshot_ts_utc"]


def fetch_balances(
    conn: Any,
    *,
    account: TradingAccount,
    source_name: str,
    snapshot_ts_utc: Any,
) -> dict[str, BalanceRow]:
    sql = """
    SELECT
        currency_code,
        available_amount,
        reserved_amount,
        total_amount,
        snapshot_ts_utc
    FROM trading_account_balance_snapshot
    WHERE trading_account_id = %s
      AND venue = %s
      AND source_name = %s
      AND snapshot_ts_utc = %s
      AND currency_code <> 'EUR'
      AND total_amount > 0
    ORDER BY currency_code
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(
            sql,
            (
                account.trading_account_id,
                account.venue,
                source_name,
                snapshot_ts_utc,
            ),
        )
        rows = cur.fetchall()

    out: dict[str, BalanceRow] = {}

    for row in rows:
        symbol = str(row["currency_code"])
        out[symbol] = BalanceRow(
            currency_code=symbol,
            available_amount=decimal_value(row["available_amount"]),
            reserved_amount=decimal_value(row["reserved_amount"]),
            total_amount=decimal_value(row["total_amount"]),
            snapshot_ts_utc=row["snapshot_ts_utc"],
        )

    return out


def fetch_asset_ids(conn: Any, *, symbols: list[str]) -> dict[str, int]:
    if not symbols:
        return {}

    placeholders = ",".join(["%s"] * len(symbols))
    sql = f"""
    SELECT asset_id, symbol
    FROM asset
    WHERE symbol IN ({placeholders})
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, symbols)
        rows = cur.fetchall()

    return {str(row["symbol"]): int(row["asset_id"]) for row in rows}


def fetch_prices(
    conn: Any,
    *,
    venue: str,
    interval_code: str,
    symbols: list[str],
    ts_col: str,
    price_col: str,
) -> dict[str, PriceRow]:
    if not symbols:
        return {}

    placeholders = ",".join(["%s"] * len(symbols))
    sql = f"""
    SELECT
        a.symbol,
        c.{price_col} AS price_eur,
        c.{ts_col} AS price_ts_utc
    FROM asset a
    JOIN obs_market_candle c
      ON c.asset_id = a.asset_id
    JOIN (
        SELECT
            c2.asset_id,
            MAX(c2.{ts_col}) AS max_price_ts_utc
        FROM obs_market_candle c2
        JOIN asset a2
          ON a2.asset_id = c2.asset_id
        WHERE c2.venue = %s
          AND c2.interval_code = %s
          AND a2.symbol IN ({placeholders})
        GROUP BY c2.asset_id
    ) latest
      ON latest.asset_id = c.asset_id
     AND latest.max_price_ts_utc = c.{ts_col}
    WHERE c.venue = %s
      AND c.interval_code = %s
      AND a.symbol IN ({placeholders})
    """

    params = [venue, interval_code, *symbols, venue, interval_code, *symbols]

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    return {
        str(row["symbol"]): PriceRow(
            symbol=str(row["symbol"]),
            price_eur=decimal_value(row["price_eur"]),
            price_ts_utc=row["price_ts_utc"],
        )
        for row in rows
    }


def build_position_rows(
    *,
    balances: dict[str, BalanceRow],
    asset_ids: dict[str, int],
    prices: dict[str, PriceRow],
    account: TradingAccount,
    balance_snapshot_ts_utc: Any,
) -> tuple[list[PositionRow], list[str]]:
    rows: list[PositionRow] = []
    skipped_symbols: list[str] = []

    for symbol, balance in sorted(balances.items()):
        asset_id = asset_ids.get(symbol)

        if asset_id is None:
            skipped_symbols.append(symbol)
            continue

        price = prices.get(symbol)

        raw = {
            "source": SOURCE_NAME,
            "writer": WRITER_NAME,
            "writer_version": WRITER_VERSION,
            "account_code": account.account_code,
            "account_mode": account.account_mode,
            "venue": account.venue,
            "balance_snapshot_ts_utc": str(balance_snapshot_ts_utc),
            "currency_code": symbol,
            "available_amount": format_decimal(balance.available_amount),
            "reserved_amount": format_decimal(balance.reserved_amount),
            "total_amount": format_decimal(balance.total_amount),
            "mark_price_eur": None if price is None else format_decimal(price.price_eur),
            "price_ts_utc": None if price is None else str(price.price_ts_utc),
            "broker_submission": False,
            "live_trading_enabled": False,
            "position_mutation": False,
        }

        rows.append(
            PositionRow(
                asset_id=asset_id,
                symbol=symbol,
                quantity_base=balance.total_amount,
                available_quantity_base=balance.available_amount,
                reserved_quantity_base=balance.reserved_amount,
                mark_price_eur=None if price is None else price.price_eur,
                raw_json=json.dumps(raw, sort_keys=True, separators=(",", ":")),
            )
        )

    return rows, skipped_symbols


def write_position_rows(
    conn: Any,
    *,
    account: TradingAccount,
    snapshot_ts_utc: Any,
    rows: list[PositionRow],
    commit: bool = True,
) -> list[WriteResult]:
    select_sql = """
    SELECT account_position_snapshot_id
    FROM account_position_snapshot
    WHERE trading_account_id = %s
      AND venue = %s
      AND source_name = %s
      AND snapshot_ts_utc = %s
      AND symbol = %s
    LIMIT 1
    """

    insert_sql = """
    INSERT INTO account_position_snapshot (
        snapshot_ts_utc,
        trading_account_id,
        asset_id,
        symbol,
        venue,
        quantity_base,
        available_quantity_base,
        reserved_quantity_base,
        average_entry_price_eur,
        mark_price_eur,
        source_name,
        raw_json
    ) VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, NULL, %s, %s, %s
    )
    """

    results: list[WriteResult] = []

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        for row in rows:
            cur.execute(
                select_sql,
                (
                    account.trading_account_id,
                    account.venue,
                    SOURCE_NAME,
                    snapshot_ts_utc,
                    row.symbol,
                ),
            )
            existing = cur.fetchone()

            if existing:
                results.append(
                    WriteResult(
                        symbol=row.symbol,
                        action="REUSED_EXISTING",
                        row_id=int(existing["account_position_snapshot_id"]),
                    )
                )
                continue

            cur.execute(
                insert_sql,
                (
                    snapshot_ts_utc,
                    account.trading_account_id,
                    row.asset_id,
                    row.symbol,
                    account.venue,
                    row.quantity_base,
                    row.available_quantity_base,
                    row.reserved_quantity_base,
                    row.mark_price_eur,
                    SOURCE_NAME,
                    row.raw_json,
                ),
            )
            results.append(
                WriteResult(
                    symbol=row.symbol,
                    action="INSERTED",
                    row_id=int(cur.lastrowid),
                )
            )

    if commit:
        conn.commit()
    return results


def write_positions_from_balance_snapshot(
    conn: Any,
    *,
    account: TradingAccount,
    balance_source_name: str,
    balance_snapshot_ts_utc: Any,
    interval_code: str = DEFAULT_INTERVAL,
    commit: bool = True,
) -> tuple[list[WriteResult], list[str]]:
    """Derive persisted positions from one exact persisted balance snapshot.

    The caller supplies the account and balance identity, so a coordinating
    account-state producer can keep this write inside its own transaction.
    This function performs no broker call and does not create execution intent.
    """
    balances = fetch_balances(
        conn,
        account=account,
        source_name=balance_source_name,
        snapshot_ts_utc=balance_snapshot_ts_utc,
    )
    symbols = sorted(balances.keys())
    if not symbols:
        return write_position_rows(
            conn,
            account=account,
            snapshot_ts_utc=balance_snapshot_ts_utc,
            rows=[],
            commit=commit,
        ), []

    ts_col, price_col = detect_candle_columns(conn)
    asset_ids = fetch_asset_ids(conn, symbols=symbols)
    prices = fetch_prices(
        conn,
        venue=account.venue,
        interval_code=interval_code,
        symbols=symbols,
        ts_col=ts_col,
        price_col=price_col,
    )
    position_rows, skipped_symbols = build_position_rows(
        balances=balances,
        asset_ids=asset_ids,
        prices=prices,
        account=account,
        balance_snapshot_ts_utc=balance_snapshot_ts_utc,
    )
    if skipped_symbols:
        raise RuntimeError(
            "POSITION_SNAPSHOT_INCOMPLETE: missing asset identity for "
            + ",".join(skipped_symbols)
        )
    return write_position_rows(
        conn,
        account=account,
        snapshot_ts_utc=balance_snapshot_ts_utc,
        rows=position_rows,
        commit=commit,
    ), skipped_symbols


def fetch_latest_written_summary(
    conn: Any,
    *,
    account: TradingAccount,
    snapshot_ts_utc: Any,
) -> list[dict[str, Any]]:
    sql = """
    SELECT
        COUNT(*) AS rows_total,
        COUNT(DISTINCT snapshot_ts_utc) AS distinct_snapshot_ts,
        COUNT(DISTINCT symbol) AS symbols_total,
        SUM(quantity_base) AS quantity_base_sum,
        SUM(available_quantity_base) AS available_quantity_base_sum,
        SUM(reserved_quantity_base) AS reserved_quantity_base_sum,
        SUM(CASE WHEN mark_price_eur IS NULL THEN 1 ELSE 0 END) AS missing_mark_price_rows
    FROM account_position_snapshot
    WHERE trading_account_id = %s
      AND venue = %s
      AND source_name = %s
      AND snapshot_ts_utc = %s
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(
            sql,
            (
                account.trading_account_id,
                account.venue,
                SOURCE_NAME,
                snapshot_ts_utc,
            ),
        )
        return list(cur.fetchall())


def fetch_hard_safety_rows(conn: Any) -> list[dict[str, Any]]:
    sql = """
    SELECT
        'execution_sell_plan_broker_submission_enabled' AS check_name,
        COUNT(*) AS rows_total
    FROM execution_sell_plan
    WHERE broker_submission_enabled = 1

    UNION ALL

    SELECT
        'execution_sell_plan_live_trading_enabled' AS check_name,
        COUNT(*) AS rows_total
    FROM execution_sell_plan
    WHERE live_trading_enabled = 1

    UNION ALL

    SELECT
        'execution_sell_intent_live_trading_enabled' AS check_name,
        COUNT(*) AS rows_total
    FROM execution_sell_intent
    WHERE live_trading_enabled = 1

    UNION ALL

    SELECT
        'execution_sell_intent_execution_enabled' AS check_name,
        COUNT(*) AS rows_total
    FROM execution_sell_intent
    WHERE execution_enabled = 1
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql)
        return list(cur.fetchall())


def print_table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [len(header) for header in headers]

    for row in rows:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(value))

    print(" | ".join(header.ljust(widths[idx]) for idx, header in enumerate(headers)))
    print("-+-".join("-" * width for width in widths))

    for row in rows:
        print(" | ".join(value.ljust(widths[idx]) for idx, value in enumerate(row)))


def print_position_rows(rows: list[PositionRow], *, limit: int) -> None:
    headers = [
        "symbol",
        "qty",
        "available",
        "reserved",
        "mark_price",
        "value_eur",
    ]

    table_rows: list[list[str]] = []

    for row in rows[:limit]:
        value_eur = None
        if row.mark_price_eur is not None:
            value_eur = row.quantity_base * row.mark_price_eur

        table_rows.append(
            [
                row.symbol,
                format_decimal(row.quantity_base),
                format_decimal(row.available_quantity_base),
                format_decimal(row.reserved_quantity_base),
                format_decimal(row.mark_price_eur),
                format_decimal(value_eur),
            ]
        )

    if not table_rows:
        print("(no rows)")
        return

    print_table(headers, table_rows)

    if len(rows) > limit:
        print(f"[INFO] output truncated rows_shown={limit} rows_total={len(rows)}")


def print_write_results(results: list[WriteResult]) -> None:
    headers = ["symbol", "action", "row_id"]
    rows = [[r.symbol, r.action, "" if r.row_id is None else str(r.row_id)] for r in results]
    print_table(headers, rows)


def run(args: argparse.Namespace) -> int:
    load_dotenv(dotenv_path=".env", override=False)

    write_permission = broker_write_permission_state()
    if write_permission == "GRANTED":
        print(
            "FAIL: SYNTH_BROKER_WRITE_PERMISSION is granted; refusing read-only-derived position snapshot writer."
        )
        return 2

    conn = get_db_connection()

    try:
        account = fetch_trading_account(conn, account_code=args.account_code, venue=args.venue)
        ts_col, price_col = detect_candle_columns(conn)

        latest_balance_ts = fetch_latest_balance_snapshot_ts(
            conn,
            account=account,
            source_name=args.balance_source_name,
        )

        if latest_balance_ts is None:
            print("FAIL: no latest balance snapshot found")
            return 3

        balances = fetch_balances(
            conn,
            account=account,
            source_name=args.balance_source_name,
            snapshot_ts_utc=latest_balance_ts,
        )
        symbols = sorted(balances.keys())

        asset_ids = fetch_asset_ids(conn, symbols=symbols)
        prices = fetch_prices(
            conn,
            venue=args.venue,
            interval_code=args.interval,
            symbols=symbols,
            ts_col=ts_col,
            price_col=price_col,
        )

        position_rows, skipped_symbols = build_position_rows(
            balances=balances,
            asset_ids=asset_ids,
            prices=prices,
            account=account,
            balance_snapshot_ts_utc=latest_balance_ts,
        )

        hard_safety_rows = fetch_hard_safety_rows(conn)
        unsafe_hard_rows = [
            row for row in hard_safety_rows if int(row["rows_total"]) != 0
        ]

        print(f"writer={WRITER_NAME} version={WRITER_VERSION}")
        print(
            f"account_code={account.account_code} "
            f"trading_account_id={account.trading_account_id} "
            f"venue={account.venue}"
        )
        print("[INFO] local DB snapshot writer; no broker calls; no broker writes; no orders")
        print(f"SYNTH_BROKER_WRITE_PERMISSION={write_permission}")
        print(f"balance_snapshot_ts_utc={latest_balance_ts}")
        print(f"price_ts_column={ts_col}")
        print(f"price_column={price_col}")

        print()
        print("--- build result ---")
        print(f"balance_symbols={len(balances)}")
        print(f"position_rows={len(position_rows)}")
        print(f"skipped_symbols={','.join(skipped_symbols) if skipped_symbols else 'NONE'}")

        if args.output == "table":
            print()
            print("--- position rows preview ---")
            print_position_rows(position_rows, limit=args.limit)

            print()
            print("--- hard safety ---")
            print_table(
                ["check_name", "rows_total"],
                [[str(row["check_name"]), str(row["rows_total"])] for row in hard_safety_rows],
            )

        write_results: list[WriteResult] = []

        if args.write_db:
            write_results = write_position_rows(
                conn,
                account=account,
                snapshot_ts_utc=latest_balance_ts,
                rows=position_rows,
            )

            summary_rows = fetch_latest_written_summary(
                conn,
                account=account,
                snapshot_ts_utc=latest_balance_ts,
            )

            if args.output == "table":
                print()
                print("--- write results ---")
                print_write_results(write_results)

            print()
            print("--- written summary ---")
            for row in summary_rows:
                print(row)
        else:
            print()
            print("[DRY_RUN] no DB writes performed")

        inserted_count = sum(1 for r in write_results if r.action == "INSERTED")
        reused_count = sum(1 for r in write_results if r.action == "REUSED_EXISTING")

        print()
        print("--- permission/safety summary ---")
        print(f"SYNTH_BROKER_WRITE_PERMISSION={write_permission}")
        print(f"hard_safety_nonzero_checks={len(unsafe_hard_rows)}")

        if unsafe_hard_rows:
            print("FAIL: hard safety checks contain nonzero rows")
            return 4

        print()
        print(
            "[DONE] "
            f"position_rows={len(position_rows)} "
            f"inserted={inserted_count} "
            f"reused={reused_count} "
            "broker_calls=0 broker_writes=0 order_submission=0"
        )

        return 0

    finally:
        conn.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account-code", default=DEFAULT_ACCOUNT_CODE)
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--interval", default=DEFAULT_INTERVAL)
    parser.add_argument("--balance-source-name", default=DEFAULT_BALANCE_SOURCE_NAME)
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--write-db", action="store_true")
    parser.add_argument("--output", choices=["table", "none"], default="table")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
