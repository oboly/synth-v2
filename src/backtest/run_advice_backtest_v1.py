#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import os
import sys
from dataclasses import dataclass
from typing import Iterable

import pandas as pd
import pymysql
from dotenv import load_dotenv


SUPPORTED_INTERVALS = {"1h"}
FORWARD_HOURS = (1, 4, 24)


@dataclass(frozen=True)
class DbConfig:
    host: str
    port: int
    user: str
    password: str
    database: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backtest selection/advice quality from historical selection_state snapshots."
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--from-ts", dest="from_ts", default=None)
    parser.add_argument("--to-ts", dest="to_ts", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--selection-state", dest="selection_state", default=None)
    parser.add_argument(
        "--max-priority-rank",
        dest="max_priority_rank",
        type=int,
        default=None,
        help="Only include rows with priority_rank <= this value.",
    )
    return parser.parse_args()


def load_db_config() -> DbConfig:
    load_dotenv()

    host = os.getenv("DB_HOST", "127.0.0.1")
    port = int(os.getenv("DB_PORT", "3306"))
    user = os.getenv("DB_USER", "root")
    password = (
        os.getenv("DB_PASSWORD")
        or os.getenv("DB_PASS")
        or os.getenv("MYSQL_PASSWORD")
        or ""
    )
    database = os.getenv("DB_NAME", "")

    if not database:
        raise RuntimeError("DB_NAME is not set.")

    return DbConfig(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
    )


def get_connection(cfg: DbConfig) -> pymysql.connections.Connection:
    return pymysql.connect(
        host=cfg.host,
        port=cfg.port,
        user=cfg.user,
        password=cfg.password,
        database=cfg.database,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


def query_dataframe(
    conn: pymysql.connections.Connection,
    sql: str,
    params: list[object] | tuple[object, ...] | None = None,
) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(sql, params or [])
        rows = cur.fetchall()
    return pd.DataFrame(rows)


def fmt_float(value: float | None, digits: int = 4) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "-"
    return f"{value:.{digits}f}"


def safe_mean(series: pd.Series) -> float | None:
    series = pd.to_numeric(series, errors="coerce").dropna()
    if series.empty:
        return None
    return float(series.mean())


def safe_winrate(series: pd.Series) -> float | None:
    series = pd.to_numeric(series, errors="coerce").dropna()
    if series.empty:
        return None
    return float((series > 0).mean())


def print_table(title: str, rows: list[dict[str, object]], columns: list[tuple[str, str]]) -> None:
    print()
    print(title)
    print("=" * len(title))

    if not rows:
        print("No rows.")
        return

    widths: dict[str, int] = {}
    for key, header in columns:
        widths[key] = len(header)

    for row in rows:
        for key, _header in columns:
            widths[key] = max(widths[key], len(str(row.get(key, ""))))

    header_line = " | ".join(header.ljust(widths[key]) for key, header in columns)
    print(header_line)
    print("-" * len(header_line))

    for row in rows:
        print(" | ".join(str(row.get(key, "")).ljust(widths[key]) for key, _header in columns))


def fetch_snapshots(
    conn: pymysql.connections.Connection,
    venue: str,
    from_ts: str | None,
    to_ts: str | None,
    selection_state: str | None,
    max_priority_rank: int | None,
    limit: int | None,
) -> pd.DataFrame:
    filters: list[str] = ["ss.venue = %s"]
    params: list[object] = [venue]

    if from_ts:
        filters.append("ss.asof_ts_utc >= %s")
        params.append(from_ts)

    if to_ts:
        filters.append("ss.asof_ts_utc <= %s")
        params.append(to_ts)

    if selection_state:
        filters.append("ss.selection_state = %s")
        params.append(selection_state)

    if max_priority_rank is not None:
        filters.append("ss.priority_rank IS NOT NULL")
        filters.append("ss.priority_rank <= %s")
        params.append(max_priority_rank)

    where_sql = " AND ".join(filters)
    limit_sql = f"LIMIT {int(limit)}" if limit is not None else ""

    sql = f"""
    SELECT
        ss.asset_id,
        COALESCE(a.symbol, CAST(ss.asset_id AS CHAR)) AS symbol,
        ss.asof_ts_utc,
        ss.selection_state,
        ss.selection_bias,
        ss.selection_score,
        ss.priority_rank,
        ss.advice_ts_1h_utc,
        ss.advice_ts_4h_utc
    FROM selection_state ss
    LEFT JOIN asset a
        ON a.asset_id = ss.asset_id
    WHERE {where_sql}
    ORDER BY ss.asof_ts_utc ASC, ss.priority_rank ASC, ss.asset_id ASC
    {limit_sql}
    """

    df = query_dataframe(conn, sql, params=params)
    if df.empty:
        return df

    df["asof_ts_utc"] = pd.to_datetime(df["asof_ts_utc"], utc=False)
    df["advice_ts_1h_utc"] = pd.to_datetime(df["advice_ts_1h_utc"], utc=False, errors="coerce")
    df["advice_ts_4h_utc"] = pd.to_datetime(df["advice_ts_4h_utc"], utc=False, errors="coerce")
    df["selection_score"] = pd.to_numeric(df["selection_score"], errors="coerce")
    df["priority_rank"] = pd.to_numeric(df["priority_rank"], errors="coerce")
    return df


def fetch_candles(
    conn: pymysql.connections.Connection,
    venue: str,
    interval_code: str,
    asset_ids: Iterable[int],
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
) -> pd.DataFrame:
    asset_ids = list(sorted(set(int(x) for x in asset_ids)))
    if not asset_ids:
        return pd.DataFrame()

    placeholders = ",".join(["%s"] * len(asset_ids))
    sql = f"""
    SELECT
        c.asset_id,
        c.open_ts_utc,
        c.close_price
    FROM obs_market_candle c
    WHERE c.venue = %s
      AND c.interval_code = %s
      AND c.asset_id IN ({placeholders})
      AND c.open_ts_utc >= %s
      AND c.open_ts_utc <= %s
    ORDER BY c.asset_id ASC, c.open_ts_utc ASC
    """

    params: list[object] = [
        venue,
        interval_code,
        *asset_ids,
        start_ts.to_pydatetime(),
        end_ts.to_pydatetime(),
    ]

    df = query_dataframe(conn, sql, params=params)
    if df.empty:
        return df

    df["open_ts_utc"] = pd.to_datetime(df["open_ts_utc"], utc=False)
    df["close_price"] = pd.to_numeric(df["close_price"], errors="coerce")
    return df


def attach_forward_returns(
    snapshots: pd.DataFrame,
    candles: pd.DataFrame,
) -> pd.DataFrame:
    if snapshots.empty:
        return snapshots.copy()

    out = snapshots.copy()

    price_map = (
        candles[["asset_id", "open_ts_utc", "close_price"]]
        .dropna(subset=["close_price"])
        .rename(columns={"open_ts_utc": "ts", "close_price": "px"})
        .set_index(["asset_id", "ts"])["px"]
        .to_dict()
    )

    def lookup_price(asset_id: int, ts: pd.Timestamp) -> float | None:
        return price_map.get((int(asset_id), pd.Timestamp(ts).to_pydatetime()), None)

    px_t0: list[float | None] = []
    px_1h: list[float | None] = []
    px_4h: list[float | None] = []
    px_24h: list[float | None] = []

    for row in out.itertuples(index=False):
        asset_id = int(row.asset_id)
        ts0 = pd.Timestamp(row.asof_ts_utc)

        p0 = lookup_price(asset_id, ts0)
        p1 = lookup_price(asset_id, ts0 + pd.Timedelta(hours=1))
        p4 = lookup_price(asset_id, ts0 + pd.Timedelta(hours=4))
        p24 = lookup_price(asset_id, ts0 + pd.Timedelta(hours=24))

        px_t0.append(p0)
        px_1h.append(p1)
        px_4h.append(p4)
        px_24h.append(p24)

    out["px_t0"] = px_t0
    out["px_1h"] = px_1h
    out["px_4h"] = px_4h
    out["px_24h"] = px_24h

    for hours in FORWARD_HOURS:
        out[f"ret_{hours}h"] = (
            (pd.to_numeric(out[f"px_{hours}h"], errors="coerce") - pd.to_numeric(out["px_t0"], errors="coerce"))
            / pd.to_numeric(out["px_t0"], errors="coerce")
        )

    return out


def summarize_group(df: pd.DataFrame, group_col: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []

    for key, g in df.groupby(group_col, dropna=False):
        rows.append(
            {
                "key": str(key),
                "count": int(len(g)),
                "v1h": int(g["ret_1h"].notna().sum()),
                "v4h": int(g["ret_4h"].notna().sum()),
                "v24h": int(g["ret_24h"].notna().sum()),
                "avg_score": fmt_float(safe_mean(g["selection_score"])),
                "avg_1h": fmt_float(safe_mean(g["ret_1h"])),
                "avg_4h": fmt_float(safe_mean(g["ret_4h"])),
                "avg_24h": fmt_float(safe_mean(g["ret_24h"])),
                "win_1h": fmt_float(safe_winrate(g["ret_1h"])),
                "win_4h": fmt_float(safe_winrate(g["ret_4h"])),
                "win_24h": fmt_float(safe_winrate(g["ret_24h"])),
            }
        )

    rows.sort(key=lambda x: (-int(x["count"]), str(x["key"])))
    return rows


def summarize_overall(df: pd.DataFrame) -> None:
    print()
    print("BACKTEST — OVERALL")
    print("==================")
    print(f"rows: {len(df)}")
    print(f"valid_1h:  {int(df['ret_1h'].notna().sum())}")
    print(f"valid_4h:  {int(df['ret_4h'].notna().sum())}")
    print(f"valid_24h: {int(df['ret_24h'].notna().sum())}")
    print(f"avg_ret_1h:  {fmt_float(safe_mean(df['ret_1h']))}")
    print(f"avg_ret_4h:  {fmt_float(safe_mean(df['ret_4h']))}")
    print(f"avg_ret_24h: {fmt_float(safe_mean(df['ret_24h']))}")
    print(f"winrate_1h:  {fmt_float(safe_winrate(df['ret_1h']))}")
    print(f"winrate_4h:  {fmt_float(safe_winrate(df['ret_4h']))}")
    print(f"winrate_24h: {fmt_float(safe_winrate(df['ret_24h']))}")


def example_rows(df: pd.DataFrame, limit: int = 20) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    sample = df.head(limit)

    for r in sample.itertuples(index=False):
        rows.append(
            {
                "asset": f"{r.symbol}({r.asset_id})",
                "ts": str(r.asof_ts_utc),
                "state": str(r.selection_state),
                "bias": str(r.selection_bias),
                "score": fmt_float(r.selection_score),
                "rank": int(r.priority_rank) if pd.notna(r.priority_rank) else "-",
                "ret_1h": fmt_float(r.ret_1h),
                "ret_4h": fmt_float(r.ret_4h),
                "ret_24h": fmt_float(r.ret_24h),
            }
        )
    return rows


def main() -> int:
    args = parse_args()

    if args.interval not in SUPPORTED_INTERVALS:
        print(
            f"Unsupported interval '{args.interval}'. "
            f"Currently supported: {', '.join(sorted(SUPPORTED_INTERVALS))}.",
            file=sys.stderr,
        )
        return 2

    cfg = load_db_config()
    conn = get_connection(cfg)

    try:
        snapshots = fetch_snapshots(
            conn=conn,
            venue=args.venue,
            from_ts=args.from_ts,
            to_ts=args.to_ts,
            selection_state=args.selection_state,
            max_priority_rank=args.max_priority_rank,
            limit=args.limit,
        )

        if snapshots.empty:
            print("No rows found.")
            return 0

        min_asof = pd.Timestamp(snapshots["asof_ts_utc"].min())
        max_asof = pd.Timestamp(snapshots["asof_ts_utc"].max())

        candle_start = min_asof
        candle_end = max_asof + pd.Timedelta(hours=max(FORWARD_HOURS))

        candles = fetch_candles(
            conn=conn,
            venue=args.venue,
            interval_code=args.interval,
            asset_ids=snapshots["asset_id"].astype(int).tolist(),
            start_ts=candle_start,
            end_ts=candle_end,
        )

        result = attach_forward_returns(snapshots, candles)

        summarize_overall(result)

        by_state = summarize_group(result, "selection_state")
        print_table(
            "BACKTEST — BY selection_state",
            by_state,
            [
                ("key", "key"),
                ("count", "count"),
                ("v1h", "v1h"),
                ("v4h", "v4h"),
                ("v24h", "v24h"),
                ("avg_score", "avg_score"),
                ("avg_1h", "avg_1h"),
                ("avg_4h", "avg_4h"),
                ("avg_24h", "avg_24h"),
                ("win_1h", "win_1h"),
                ("win_4h", "win_4h"),
                ("win_24h", "win_24h"),
            ],
        )

        by_bias = summarize_group(result, "selection_bias")
        print_table(
            "BACKTEST — BY selection_bias",
            by_bias,
            [
                ("key", "key"),
                ("count", "count"),
                ("v1h", "v1h"),
                ("v4h", "v4h"),
                ("v24h", "v24h"),
                ("avg_score", "avg_score"),
                ("avg_1h", "avg_1h"),
                ("avg_4h", "avg_4h"),
                ("avg_24h", "avg_24h"),
                ("win_1h", "win_1h"),
                ("win_4h", "win_4h"),
                ("win_24h", "win_24h"),
            ],
        )

        print_table(
            "BACKTEST — EXAMPLE ROWS",
            example_rows(result, limit=20),
            [
                ("asset", "asset"),
                ("ts", "ts"),
                ("state", "state"),
                ("bias", "bias"),
                ("score", "score"),
                ("rank", "rank"),
                ("ret_1h", "ret_1h"),
                ("ret_4h", "ret_4h"),
                ("ret_24h", "ret_24h"),
            ],
        )

        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
