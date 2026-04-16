#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd
import pymysql
from dotenv import load_dotenv


SUPPORTED_INTERVALS = {"1h"}
FORWARD_HOURS = (1, 4, 24)
DEFAULT_OUTPUT_DIR = Path("artifacts/backtest_v3")


@dataclass(frozen=True)
class DbConfig:
    host: str
    port: int
    user: str
    password: str
    database: str


@dataclass(frozen=True)
class PolicySpec:
    name: str
    hold_hours: int
    states: tuple[str, ...] = ()
    biases: tuple[str, ...] = ()
    max_rank: int | None = None


POLICIES: tuple[PolicySpec, ...] = (
    PolicySpec(name="rejected_htf_1h", hold_hours=1, states=("REJECTED_HTF",)),
    PolicySpec(name="rejected_htf_4h", hold_hours=4, states=("REJECTED_HTF",)),
    PolicySpec(name="rejected_htf_24h", hold_hours=24, states=("REJECTED_HTF",)),
    PolicySpec(name="rejected_htf_top5_4h", hold_hours=4, states=("REJECTED_HTF",), max_rank=5),
    PolicySpec(name="rejected_htf_top10_4h", hold_hours=4, states=("REJECTED_HTF",), max_rank=10),
    PolicySpec(name="rejected_htf_top15_4h", hold_hours=4, states=("REJECTED_HTF",), max_rank=15),
    PolicySpec(name="strong_candidate_4h", hold_hours=4, states=("STRONG_CANDIDATE",)),
    PolicySpec(name="watch_4h", hold_hours=4, biases=("WATCH",)),
    PolicySpec(name="prepare_4h", hold_hours=4, states=("PREPARE",)),
    PolicySpec(name="buy_ready_4h", hold_hours=4, states=("BUY_READY",)),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Policy backtest with trade export, fees, and non-overlap per asset."
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--from-ts", dest="from_ts", default=None)
    parser.add_argument("--to-ts", dest="to_ts", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--selection-state", dest="selection_state", default=None)
    parser.add_argument("--max-priority-rank", dest="max_priority_rank", type=int, default=None)
    parser.add_argument("--output-dir", dest="output_dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--fee-bps", dest="fee_bps", type=float, default=0.0)
    parser.add_argument("--max-open-trades-per-asset", dest="max_open_trades_per_asset", type=int, default=1)
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
    s = pd.to_numeric(series, errors="coerce").dropna()
    if s.empty:
        return None
    return float(s.mean())


def safe_median(series: pd.Series) -> float | None:
    s = pd.to_numeric(series, errors="coerce").dropna()
    if s.empty:
        return None
    return float(s.median())


def safe_winrate(series: pd.Series) -> float | None:
    s = pd.to_numeric(series, errors="coerce").dropna()
    if s.empty:
        return None
    return float((s > 0).mean())


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
        ss.priority_rank
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

    df["asof_ts_utc"] = pd.to_datetime(df["asof_ts_utc"], errors="coerce")
    df["selection_score"] = pd.to_numeric(df["selection_score"], errors="coerce")
    df["priority_rank"] = pd.to_numeric(df["priority_rank"], errors="coerce")
    df["symbol"] = df["symbol"].astype(str).str.upper().str.strip()
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
    params: list[object] = [venue, interval_code, *asset_ids, start_ts.to_pydatetime(), end_ts.to_pydatetime()]
    df = query_dataframe(conn, sql, params=params)
    if df.empty:
        return df

    df["open_ts_utc"] = pd.to_datetime(df["open_ts_utc"], errors="coerce")
    df["close_price"] = pd.to_numeric(df["close_price"], errors="coerce")
    return df


def attach_forward_returns(snapshots: pd.DataFrame, candles: pd.DataFrame) -> pd.DataFrame:
    out = snapshots.copy()
    if out.empty or candles.empty:
        out["px_t0"] = pd.NA
        for hours in FORWARD_HOURS:
            out[f"px_{hours}h"] = pd.NA
            out[f"ret_{hours}h"] = pd.NA
        return out

    price_map = (
        candles[["asset_id", "open_ts_utc", "close_price"]]
        .dropna(subset=["close_price"])
        .rename(columns={"open_ts_utc": "ts", "close_price": "px"})
        .set_index(["asset_id", "ts"])["px"]
        .to_dict()
    )

    def lookup_price(asset_id: int, ts: pd.Timestamp) -> float | None:
        return price_map.get((int(asset_id), pd.Timestamp(ts).to_pydatetime()), None)

    out["px_t0"] = out.apply(
        lambda r: lookup_price(int(r["asset_id"]), pd.Timestamp(r["asof_ts_utc"])),
        axis=1,
    )

    for hours in FORWARD_HOURS:
        out[f"px_{hours}h"] = out.apply(
            lambda r: lookup_price(
                int(r["asset_id"]),
                pd.Timestamp(r["asof_ts_utc"]) + pd.Timedelta(hours=hours),
            ),
            axis=1,
        )
        out[f"ret_{hours}h"] = (
            (pd.to_numeric(out[f"px_{hours}h"], errors="coerce") - pd.to_numeric(out["px_t0"], errors="coerce"))
            / pd.to_numeric(out["px_t0"], errors="coerce")
        )

    return out


def filter_policy(df: pd.DataFrame, policy: PolicySpec) -> pd.DataFrame:
    out = df.copy()

    if policy.states:
        out = out[out["selection_state"].isin(policy.states)]

    if policy.biases:
        out = out[out["selection_bias"].isin(policy.biases)]

    if policy.max_rank is not None:
        out = out[out["priority_rank"].notna() & (out["priority_rank"] <= policy.max_rank)]

    return out


def apply_non_overlap_per_asset(trades: pd.DataFrame, max_open_trades_per_asset: int) -> pd.DataFrame:
    if trades.empty:
        return trades

    accepted_rows: list[int] = []
    active_until: dict[int, list[pd.Timestamp]] = {}

    for idx, row in trades.iterrows():
        asset_id = int(row["asset_id"])
        entry_ts = pd.Timestamp(row["entry_ts_utc"])
        exit_ts = pd.Timestamp(row["exit_ts_utc"])

        current_active = active_until.get(asset_id, [])
        current_active = [ts for ts in current_active if ts > entry_ts]

        if len(current_active) >= max_open_trades_per_asset:
            active_until[asset_id] = current_active
            continue

        current_active.append(exit_ts)
        active_until[asset_id] = current_active
        accepted_rows.append(idx)

    return trades.loc[accepted_rows].copy()


def build_trades(df: pd.DataFrame, policy: PolicySpec, fee_bps: float, max_open_trades_per_asset: int) -> pd.DataFrame:
    trades = filter_policy(df, policy).copy()
    if trades.empty:
        return trades

    ret_col = f"ret_{policy.hold_hours}h"
    exit_px_col = f"px_{policy.hold_hours}h"

    trades = trades[trades["px_t0"].notna() & trades[exit_px_col].notna()].copy()
    if trades.empty:
        return trades

    trades["entry_ts_utc"] = trades["asof_ts_utc"]
    trades["exit_ts_utc"] = trades["asof_ts_utc"] + pd.to_timedelta(policy.hold_hours, unit="h")
    trades["entry_price"] = pd.to_numeric(trades["px_t0"], errors="coerce")
    trades["exit_price"] = pd.to_numeric(trades[exit_px_col], errors="coerce")
    trades["gross_trade_return"] = pd.to_numeric(trades[ret_col], errors="coerce")
    trades["fee_fraction"] = fee_bps / 10000.0
    trades["trade_return"] = trades["gross_trade_return"] - trades["fee_fraction"]
    trades["actual_direction"] = trades["trade_return"].apply(
        lambda x: "UP" if pd.notna(x) and x > 0 else ("DOWN" if pd.notna(x) and x < 0 else "NEUTRAL")
    )
    trades["policy_name"] = policy.name
    trades["hold_hours"] = policy.hold_hours
    trades["ts_utc"] = trades["entry_ts_utc"]

    trades = trades.sort_values(["entry_ts_utc", "priority_rank", "asset_id"]).reset_index(drop=True)
    trades = apply_non_overlap_per_asset(trades, max_open_trades_per_asset)
    if trades.empty:
        return trades

    trades["equity_mult"] = 1.0 + trades["trade_return"]
    trades["equity_curve"] = trades["equity_mult"].cumprod()
    trades["equity_peak"] = trades["equity_curve"].cummax()
    trades["drawdown"] = (trades["equity_curve"] / trades["equity_peak"]) - 1.0

    keep_cols = [
        "policy_name",
        "hold_hours",
        "asset_id",
        "symbol",
        "ts_utc",
        "entry_ts_utc",
        "exit_ts_utc",
        "selection_state",
        "selection_bias",
        "selection_score",
        "priority_rank",
        "entry_price",
        "exit_price",
        "gross_trade_return",
        "fee_fraction",
        "trade_return",
        "actual_direction",
        "equity_curve",
        "drawdown",
    ]
    return trades[keep_cols].copy()


def calc_profit_factor(trades: pd.DataFrame) -> float | None:
    if trades.empty:
        return None

    wins = trades.loc[trades["trade_return"] > 0, "trade_return"].sum()
    losses = trades.loc[trades["trade_return"] < 0, "trade_return"].sum()

    if losses == 0:
        if wins > 0:
            return float("inf")
        return None

    return float(wins / abs(losses))


def summarize_policy(trades: pd.DataFrame, policy: PolicySpec) -> dict[str, object]:
    if trades.empty:
        return {
            "policy": policy.name,
            "hold_h": policy.hold_hours,
            "trades": 0,
            "avg_trade": "-",
            "median_trade": "-",
            "winrate": "-",
            "cum_return": "-",
            "max_dd": "-",
            "profit_factor": "-",
        }

    cum_return = float(trades["equity_curve"].iloc[-1] - 1.0)
    max_dd = float(trades["drawdown"].min())
    pf = calc_profit_factor(trades)

    return {
        "policy": policy.name,
        "hold_h": policy.hold_hours,
        "trades": int(len(trades)),
        "avg_trade": fmt_float(safe_mean(trades["trade_return"])),
        "median_trade": fmt_float(safe_median(trades["trade_return"])),
        "winrate": fmt_float(safe_winrate(trades["trade_return"])),
        "cum_return": fmt_float(cum_return),
        "max_dd": fmt_float(max_dd),
        "profit_factor": "inf" if pf == float("inf") else fmt_float(pf),
    }


def export_policy_outputs(trades: pd.DataFrame, output_dir: Path, policy: PolicySpec) -> tuple[Path | None, Path | None]:
    if trades.empty:
        return None, None

    output_dir.mkdir(parents=True, exist_ok=True)

    trades_path = output_dir / f"{policy.name}_trades.csv"
    equity_path = output_dir / f"{policy.name}_equity.csv"

    trades.to_csv(trades_path, index=False)

    equity = trades[["ts_utc", "policy_name", "equity_curve", "drawdown"]].copy()
    equity.to_csv(equity_path, index=False)

    return trades_path, equity_path


def main() -> int:
    args = parse_args()

    if args.interval not in SUPPORTED_INTERVALS:
        print(
            f"Unsupported interval '{args.interval}'. Currently supported: {', '.join(sorted(SUPPORTED_INTERVALS))}.",
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

        candles = fetch_candles(
            conn=conn,
            venue=args.venue,
            interval_code=args.interval,
            asset_ids=snapshots["asset_id"].astype(int).tolist(),
            start_ts=min_asof,
            end_ts=max_asof + pd.Timedelta(hours=max(FORWARD_HOURS)),
        )

        enriched = attach_forward_returns(snapshots, candles)

        output_dir = Path(args.output_dir)
        summary_rows: list[dict[str, object]] = []

        for policy in POLICIES:
            trades = build_trades(
                enriched,
                policy,
                fee_bps=args.fee_bps,
                max_open_trades_per_asset=args.max_open_trades_per_asset,
            )
            summary_rows.append(summarize_policy(trades, policy))
            export_policy_outputs(trades, output_dir, policy)

        print_table(
            "BACKTEST V3 — POLICY SUMMARY",
            summary_rows,
            [
                ("policy", "policy"),
                ("hold_h", "hold_h"),
                ("trades", "trades"),
                ("avg_trade", "avg_trade"),
                ("median_trade", "median_trade"),
                ("winrate", "winrate"),
                ("cum_return", "cum_return"),
                ("max_dd", "max_dd"),
                ("profit_factor", "profit_factor"),
            ],
        )

        print()
        print(f"fee_bps: {args.fee_bps}")
        print(f"max_open_trades_per_asset: {args.max_open_trades_per_asset}")
        print(f"Exports written to: {output_dir}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
