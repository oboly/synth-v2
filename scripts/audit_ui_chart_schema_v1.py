from __future__ import annotations

import argparse
from typing import Any

import pymysql

from src.common.db import get_connection


TARGET_TABLES = [
    "asset",
    "obs_market_candle",
    "feat_candle",
    "signal_engine_state",
    "selection_state",
    "bt_selection_v2_replay",
    "bt_selection_v2_replay_eval_horizon_v2",
    "research_paper_candidate_signal",
    "asset_profile_snapshot",
    "vw_asset_profile_latest",
]

TIMESTAMP_PRIORITY = [
    "open_ts_utc",
    "close_ts_utc",
    "feature_ts_utc",
    "signal_ts_utc",
    "asof_ts_utc",
    "snapshot_ts_utc",
    "profile_ts_utc",
    "entry_ts_utc",
    "exit_ts_utc",
    "created_ts_utc",
    "updated_ts_utc",
]

ASSET_SYMBOL_COLUMNS = [
    "symbol",
    "asset_symbol",
    "base_symbol",
    "code",
    "asset_code",
]


def qident(name: str) -> str:
    safe = name.replace("`", "``")
    return f"`{safe}`"


def fetch_all(cur: Any, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    cur.execute(sql, params)
    return list(cur.fetchall())


def fetch_one(cur: Any, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    cur.execute(sql, params)
    return cur.fetchone()


def print_section(title: str) -> None:
    print()
    print("=" * 100)
    print(title)
    print("=" * 100)


def get_database_name(cur: Any) -> str:
    row = fetch_one(cur, "SELECT DATABASE() AS db_name")
    return str(row["db_name"])


def load_columns(cur: Any, db_name: str) -> dict[str, list[str]]:
    rows = fetch_all(
        cur,
        """
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = %s
          AND table_name IN (
              'asset',
              'obs_market_candle',
              'feat_candle',
              'signal_engine_state',
              'selection_state',
              'bt_selection_v2_replay',
              'bt_selection_v2_replay_eval_horizon_v2',
              'research_paper_candidate_signal',
              'asset_profile_snapshot',
              'vw_asset_profile_latest'
          )
        ORDER BY table_name, ordinal_position
        """,
        (db_name,),
    )

    out: dict[str, list[str]] = {name: [] for name in TARGET_TABLES}
    for row in rows:
        out[str(row["table_name"])].append(str(row["column_name"]))
    return out


def print_columns(columns_by_table: dict[str, list[str]]) -> None:
    print_section("TABLE / COLUMN AUDIT")
    for table in TARGET_TABLES:
        cols = columns_by_table.get(table, [])
        if not cols:
            print(f"[MISSING] {table}")
            continue

        print(f"[OK] {table}")
        print("  " + ", ".join(cols))


def print_indexes(cur: Any, db_name: str, columns_by_table: dict[str, list[str]]) -> None:
    print_section("INDEX AUDIT")
    rows = fetch_all(
        cur,
        """
        SELECT
            table_name,
            index_name,
            non_unique,
            seq_in_index,
            column_name
        FROM information_schema.statistics
        WHERE table_schema = %s
          AND table_name IN (
              'asset',
              'obs_market_candle',
              'feat_candle',
              'signal_engine_state',
              'selection_state',
              'bt_selection_v2_replay',
              'bt_selection_v2_replay_eval_horizon_v2',
              'research_paper_candidate_signal',
              'asset_profile_snapshot',
              'vw_asset_profile_latest'
          )
        ORDER BY table_name, index_name, seq_in_index
        """,
        (db_name,),
    )

    grouped: dict[tuple[str, str], list[str]] = {}
    unique_flags: dict[tuple[str, str], Any] = {}

    for row in rows:
        key = (str(row["table_name"]), str(row["index_name"]))
        grouped.setdefault(key, []).append(str(row["column_name"]))
        unique_flags[key] = row["non_unique"]

    for table in TARGET_TABLES:
        if not columns_by_table.get(table):
            continue

        table_indexes = [(idx, cols) for (tbl, idx), cols in grouped.items() if tbl == table]
        if not table_indexes:
            print(f"[NO INDEX INFO] {table}")
            continue

        print(f"[INDEXES] {table}")
        for idx, cols in table_indexes:
            unique_label = "UNIQUE" if unique_flags.get((table, idx)) == 0 else "NON_UNIQUE"
            print(f"  {idx} ({unique_label}): {', '.join(cols)}")


def sample_assets(cur: Any, columns_by_table: dict[str, list[str]]) -> None:
    print_section("ASSET SAMPLE")
    cols = columns_by_table.get("asset", [])
    if not cols:
        print("[SKIP] asset table missing")
        return

    wanted = [c for c in ["asset_id", "symbol", "base_symbol", "quote_symbol", "venue", "is_active"] if c in cols]
    if not wanted:
        wanted = cols[:6]

    sql = f"SELECT {', '.join(qident(c) for c in wanted)} FROM asset LIMIT 30"
    rows = fetch_all(cur, sql)

    for row in rows:
        print(row)


def find_asset_id(
    cur: Any,
    columns_by_table: dict[str, list[str]],
    symbol: str,
) -> int | None:
    cols = columns_by_table.get("asset", [])
    if "asset_id" not in cols:
        return None

    searchable = [c for c in ASSET_SYMBOL_COLUMNS if c in cols]
    if not searchable:
        return None

    clauses = [f"UPPER({qident(c)}) = UPPER(%s)" for c in searchable]
    params = tuple(symbol for _ in searchable)

    sql = f"""
        SELECT asset_id
        FROM asset
        WHERE {" OR ".join(clauses)}
        ORDER BY asset_id
        LIMIT 1
    """
    row = fetch_one(cur, sql, params)
    if not row:
        return None

    return int(row["asset_id"])


def pick_timestamp_col(cols: list[str]) -> str | None:
    for col in TIMESTAMP_PRIORITY:
        if col in cols:
            return col

    for col in cols:
        lowered = col.lower()
        if lowered.endswith("_ts_utc") or lowered.endswith("_time_utc"):
            return col

    return None


def probe_table(
    cur: Any,
    table: str,
    cols: list[str],
    asset_id: int | None,
    venue: str,
    interval: str,
    limit: int,
) -> None:
    if not cols:
        print(f"[SKIP] {table}: missing")
        return

    ts_col = pick_timestamp_col(cols)
    if not ts_col:
        print(f"[SKIP] {table}: no obvious timestamp column")
        return

    where_parts: list[str] = []
    params: list[Any] = []

    if asset_id is not None and "asset_id" in cols:
        where_parts.append("asset_id = %s")
        params.append(asset_id)

    if "venue" in cols:
        where_parts.append("venue = %s")
        params.append(venue)

    if "interval_code" in cols:
        where_parts.append("interval_code = %s")
        params.append(interval)

    selected = [
        c for c in [
            "asset_id",
            "venue",
            "interval_code",
            ts_col,
            "open_price",
            "high_price",
            "low_price",
            "close_price",
            "volume_quote_eur",
            "ema20",
            "ema50",
            "rsi14",
            "atr14",
            "volume_ratio",
            "volume_zscore",
            "trend_signal",
            "volume_signal",
            "setup_signal",
            "risk_signal",
            "signal_confidence",
            "selection_state",
            "selection_score",
            "priority_rank",
            "classification_code",
            "rotation_bucket",
            "batch_id",
            "policy_name",
            "simulated_return",
            "pnl_eur",
            "liquidity_class",
            "beta_profile",
            "sector_group_code",
        ]
        if c in cols
    ]

    if ts_col not in selected:
        selected.insert(0, ts_col)

    where_sql = ""
    if where_parts:
        where_sql = "WHERE " + " AND ".join(where_parts)

    sql = f"""
        SELECT {', '.join(qident(c) for c in selected)}
        FROM {qident(table)}
        {where_sql}
        ORDER BY {qident(ts_col)} DESC
        LIMIT %s
    """
    params.append(limit)

    try:
        rows = fetch_all(cur, sql, tuple(params))
    except Exception as exc:
        print(f"[ERROR] {table}: {exc}")
        return

    print(f"[PROBE] {table}: ts_col={ts_col}, rows={len(rows)}")
    for row in rows:
        print(f"  {row}")


def probe_chart_sources(
    cur: Any,
    columns_by_table: dict[str, list[str]],
    symbol: str,
    venue: str,
    interval: str,
    limit: int,
) -> None:
    print_section("TARGETED LATEST-ROW PROBE")
    asset_id = find_asset_id(cur, columns_by_table, symbol)

    if asset_id is None:
        print(f"[WARN] Could not resolve asset_id for symbol={symbol}")
    else:
        print(f"[OK] symbol={symbol} asset_id={asset_id}")

    for table in TARGET_TABLES:
        if table == "asset":
            continue
        probe_table(
            cur=cur,
            table=table,
            cols=columns_by_table.get(table, []),
            asset_id=asset_id,
            venue=venue,
            interval=interval,
            limit=limit,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTC")
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    conn = get_connection()
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            db_name = get_database_name(cur)
            print_section("DATABASE")
            print(f"db={db_name}")
            print(f"symbol={args.symbol} venue={args.venue} interval={args.interval} limit={args.limit}")

            columns_by_table = load_columns(cur, db_name)
            print_columns(columns_by_table)
            print_indexes(cur, db_name, columns_by_table)
            sample_assets(cur, columns_by_table)
            probe_chart_sources(
                cur=cur,
                columns_by_table=columns_by_table,
                symbol=args.symbol,
                venue=args.venue,
                interval=args.interval,
                limit=args.limit,
            )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
