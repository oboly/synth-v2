from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pymysql
from dotenv import load_dotenv

from src.common.db import get_db_connection


DEFAULT_MANIFEST_PATH = Path(
    "data/external/pro_elliott_fibo/manifest/pro_fibo_reference_values_20260507.jsonl"
)


def load_manifest(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                rows.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise SystemExit(f"Invalid JSONL at line {line_number}: {exc}") from exc
    return rows


def fetch_bitvavo_markets(timeout_seconds: int = 20) -> list[dict[str, Any]]:
    url = "https://api.bitvavo.com/v2/markets"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "synth-pro-fibo-reference-verifier/1.0",
            "Accept": "application/json",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except urllib.error.URLError as exc:
        print(f"[WARN] Bitvavo public market fetch failed: {exc}")
        return []

    data = json.loads(body)
    if not isinstance(data, list):
        print("[WARN] Bitvavo public market response was not a list")
        return []

    return [row for row in data if isinstance(row, dict)]


def print_section(title: str) -> None:
    print()
    print(f"--- {title} ---")


def table_exists(conn: Any, table_name: str) -> bool:
    sql = """
    SELECT COUNT(*) AS rows_total
    FROM information_schema.tables
    WHERE table_schema = DATABASE()
      AND table_name = %s
    """
    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, (table_name,))
        row = cur.fetchone()
    return bool(row and int(row["rows_total"]) > 0)


def fetch_table_columns(conn: Any, table_name: str) -> list[str]:
    sql = """
    SELECT column_name
    FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = %s
    ORDER BY ordinal_position
    """
    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, (table_name,))
        return [str(row["column_name"]) for row in cur.fetchall()]


def quote_identifier(identifier: str) -> str:
    return "`" + identifier.replace("`", "``") + "`"


def fetch_asset_rows(conn: Any, symbols: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    if not table_exists(conn, "asset"):
        return [], symbols

    columns = fetch_table_columns(conn, "asset")
    candidate_symbol_columns = [
        column for column in columns if column.lower() in {"symbol", "asset_symbol", "code", "asset_code"}
    ]

    if not candidate_symbol_columns:
        print("[WARN] asset table exists but no obvious symbol/code column found")
        return [], symbols

    symbol_column = candidate_symbol_columns[0]
    placeholders = ", ".join(["%s"] * len(symbols))

    select_columns = [
        column for column in [
            "asset_id",
            symbol_column,
            "symbol",
            "asset_symbol",
            "code",
            "name",
            "enabled",
            "created_ts_utc",
            "updated_ts_utc",
        ]
        if column in columns
    ]

    sql = f"""
    SELECT {", ".join(quote_identifier(column) for column in select_columns)}
    FROM asset
    WHERE UPPER({quote_identifier(symbol_column)}) IN ({placeholders})
    ORDER BY {quote_identifier(symbol_column)}
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, tuple(symbol.upper() for symbol in symbols))
        rows = [dict(row) for row in cur.fetchall()]

    found_symbols: set[str] = set()
    for row in rows:
        value = row.get(symbol_column)
        if value is not None:
            found_symbols.add(str(value).upper())

    missing_symbols = [symbol for symbol in symbols if symbol.upper() not in found_symbols]
    return rows, missing_symbols


def fetch_candidate_mapping_hits(conn: Any, search_values: list[str]) -> list[dict[str, Any]]:
    table_sql = """
    SELECT DISTINCT c.table_name
    FROM information_schema.columns c
    JOIN information_schema.tables t
      ON t.table_schema = c.table_schema
     AND t.table_name = c.table_name
    WHERE c.table_schema = DATABASE()
      AND t.table_type = 'BASE TABLE'
      AND (
             LOWER(c.table_name) REGEXP 'asset|market|universe|mapping|symbol|watch|pair|instrument'
          OR LOWER(c.column_name) REGEXP 'symbol|market|pair|code|asset'
      )
      AND c.data_type IN ('varchar','char','text','mediumtext','longtext')
    ORDER BY c.table_name
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(table_sql)
        tables = [str(row["table_name"]) for row in cur.fetchall()]

    hits: list[dict[str, Any]] = []
    upper_values = [value.upper() for value in search_values]

    for table_name in tables:
        columns = fetch_table_columns(conn, table_name)
        text_columns = [
            column for column in columns
            if any(token in column.lower() for token in ["symbol", "market", "pair", "code", "asset"])
        ]

        if not text_columns:
            continue

        for column in text_columns:
            count_sql = f"""
            SELECT COUNT(*) AS rows_total
            FROM {quote_identifier(table_name)}
            WHERE UPPER(CAST({quote_identifier(column)} AS CHAR)) IN ({", ".join(["%s"] * len(upper_values))})
            """

            try:
                with conn.cursor(pymysql.cursors.DictCursor) as cur:
                    cur.execute(count_sql, tuple(upper_values))
                    count_row = cur.fetchone()
            except Exception as exc:
                hits.append(
                    {
                        "table_name": table_name,
                        "column_name": column,
                        "error": str(exc),
                    }
                )
                continue

            rows_total = int(count_row["rows_total"]) if count_row else 0
            if rows_total <= 0:
                continue

            sample_sql = f"""
            SELECT *
            FROM {quote_identifier(table_name)}
            WHERE UPPER(CAST({quote_identifier(column)} AS CHAR)) IN ({", ".join(["%s"] * len(upper_values))})
            LIMIT 5
            """

            with conn.cursor(pymysql.cursors.DictCursor) as cur:
                cur.execute(sample_sql, tuple(upper_values))
                samples = [dict(row) for row in cur.fetchall()]

            hits.append(
                {
                    "table_name": table_name,
                    "column_name": column,
                    "rows_total": rows_total,
                    "samples": samples,
                }
            )

    return hits


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest-path", default=str(DEFAULT_MANIFEST_PATH))
    parser.add_argument("--skip-bitvavo", action="store_true")
    args = parser.parse_args()

    load_dotenv(dotenv_path=".env", override=False)

    manifest_path = Path(args.manifest_path)
    rows = load_manifest(manifest_path)

    symbols = [str(row["asset_symbol"]).upper() for row in rows]
    market_hints = [str(row["market_hint"]).upper() for row in rows if row.get("market_hint")]
    search_values = sorted(set(symbols + market_hints + [market.replace("-", "") for market in market_hints]))

    print_section("manifest")
    print(f"manifest_path={manifest_path}")
    print(f"rows={len(rows)}")
    for row in rows:
        print(
            {
                "reference_id": row["reference_id"],
                "asset_symbol": row["asset_symbol"],
                "market_hint": row.get("market_hint"),
                "research_only": row.get("research_only"),
                "direct_signal": row.get("direct_signal"),
            }
        )

    if not args.skip_bitvavo:
        print_section("bitvavo public markets")
        markets = fetch_bitvavo_markets()
        by_market = {str(row.get("market", "")).upper(): row for row in markets}
        for market in market_hints:
            hit = by_market.get(market)
            if hit:
                print(
                    {
                        "market": market,
                        "status": hit.get("status"),
                        "base": hit.get("base"),
                        "quote": hit.get("quote"),
                        "present": True,
                    }
                )
            else:
                print({"market": market, "present": False})

    conn = get_db_connection()

    try:
        print_section("DB asset rows for TON/TAO/NEAR")
        asset_rows, missing_symbols = fetch_asset_rows(conn, symbols)
        if asset_rows:
            for row in asset_rows:
                print(row)
        else:
            print("NO_ASSET_ROWS_FOUND")

        print_section("DB asset missing symbols")
        if missing_symbols:
            for symbol in missing_symbols:
                print(symbol)
        else:
            print("NONE")

        print_section("candidate mapping table hits")
        hits = fetch_candidate_mapping_hits(conn, search_values)
        if not hits:
            print("NO_MAPPING_HITS_FOUND")
        for hit in hits:
            print(
                {
                    "table_name": hit.get("table_name"),
                    "column_name": hit.get("column_name"),
                    "rows_total": hit.get("rows_total"),
                    "error": hit.get("error"),
                }
            )
            for sample in hit.get("samples", []):
                print(sample)

        print_section("TON-focused search values")
        for value in ["TON", "TON-EUR", "TONEUR"]:
            print(value)

        print()
        print("[DONE] read-only verifier complete; no DB writes, no broker calls, no execution logic")
        return 0

    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
