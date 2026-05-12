from __future__ import annotations

import argparse
import csv
import json
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Any

import pymysql
from dotenv import load_dotenv

from src.common.db import get_db_connection


REPORT_NAME = "breath_curve_research_policy_baseline_v1"
VERSION = "0.1"

CONTEXT_KEYS = (
    "market_regime",
    "regime",
    "btc_regime",
    "btc_context",
    "rotation_bucket",
    "classification_code",
    "sleeve_fit_code",
)


@dataclass(frozen=True)
class Candle:
    ts: datetime
    close: float


@dataclass(frozen=True)
class PolicyRow:
    run_id: int
    policy_name: str
    policy_version: str
    checkpoint_set: str
    cost_bps: float
    require_offset_match: bool
    symbol: str
    anchor_date: str
    checkpoint_ratio: str
    offset_matches_best_full: bool
    policy_return_pct: float
    return_to_1000_pct: float | None
    return_to_1272_pct: float | None
    source_row: dict[str, Any]


@dataclass(frozen=True)
class EvaluatedRow:
    run_id: int
    policy_name: str
    symbol: str
    anchor_date: str
    checkpoint_ratio: str
    offset_matches_best_full: bool
    context_bucket: str
    policy_return_pct: float
    same_window_return_pct: float | None
    random_anchor_return_pct: float | None
    random_sample_count: int


def parse_dt(value: str) -> datetime:
    text = str(value).strip()
    if not text:
        raise ValueError("empty datetime")
    text = text.replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def maybe_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "" or text.lower() in {"none", "null", "nan"}:
        return None
    return float(text)


def truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def fmt(value: float | int | None, places: int = 4) -> str:
    if value is None:
        return ""
    return f"{float(value):.{places}f}"


def print_table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [len(header) for header in headers]

    for row in rows:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(value))

    print(" | ".join(headers[idx].ljust(widths[idx]) for idx in range(len(headers))))
    print("-+-".join("-" * width for width in widths))

    for row in rows:
        print(" | ".join(row[idx].ljust(widths[idx]) for idx in range(len(headers))))


def table_cols(conn: Any, table_name: str) -> set[str]:
    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(
            """
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = %s
            """,
            (table_name,),
        )
        return {str(row["COLUMN_NAME"]) for row in cur.fetchall()}


def choose(cols: set[str], options: list[str], required: bool = True) -> str | None:
    for option in options:
        if option in cols:
            return option
    if required:
        raise RuntimeError(f"Missing expected column. Tried: {options}")
    return None


def resolve_asset_id(conn: Any, symbol: str) -> int:
    cols = table_cols(conn, "asset")
    id_col = choose(cols, ["asset_id", "id"])
    symbol_col = choose(cols, ["symbol", "asset_code", "code", "base_symbol", "ticker"])

    candidates = sorted({
        symbol,
        symbol.upper(),
        symbol.replace("-EUR", "").upper(),
        symbol.replace("/EUR", "").upper(),
        symbol.replace("USDT", "").upper(),
    })

    placeholders = ",".join(["%s"] * len(candidates))
    sql = f"SELECT `{id_col}` AS asset_id FROM asset WHERE `{symbol_col}` IN ({placeholders}) LIMIT 1"

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, tuple(candidates))
        row = cur.fetchone()

    if not row:
        raise RuntimeError(f"Could not resolve asset_id for symbol={symbol}")

    return int(row["asset_id"])


def parse_json_dict(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    text = str(raw).strip()
    if not text:
        return {}
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def context_bucket(source_row: dict[str, Any]) -> str:
    for key in CONTEXT_KEYS:
        value = str(source_row.get(key, "")).strip()
        if value:
            return f"{key}={value}"
    return "context=UNAVAILABLE"


def fetch_policy_rows(
    conn: Any,
    *,
    run_ids: list[int],
    latest_per_policy: bool,
    policy_name_like: str | None,
) -> list[PolicyRow]:
    params: list[Any] = []

    if run_ids:
        placeholders = ",".join(["%s"] * len(run_ids))
        run_filter = f"r.research_breath_curve_policy_run_id IN ({placeholders})"
        params.extend(run_ids)
        latest_join = ""
    elif latest_per_policy:
        run_filter = "1 = 1"
        latest_join = """
        JOIN (
            SELECT
                policy_name,
                MAX(research_breath_curve_policy_run_id) AS latest_run_id
            FROM research_breath_curve_policy_run
            GROUP BY policy_name
        ) latest
          ON latest.latest_run_id = r.research_breath_curve_policy_run_id
        """
    else:
        run_filter = "1 = 1"
        latest_join = ""

    policy_filter = ""
    if policy_name_like:
        policy_filter = "AND r.policy_name LIKE %s"
        params.append(policy_name_like)

    sql = f"""
    SELECT
        r.research_breath_curve_policy_run_id AS run_id,
        r.policy_name,
        r.policy_version,
        r.checkpoint_set,
        r.cost_bps,
        r.require_offset_match,
        x.symbol,
        x.anchor_date,
        x.checkpoint_ratio,
        x.offset_matches_best_full,
        x.policy_return_pct,
        x.return_to_1000_pct,
        x.return_to_1272_pct,
        x.source_row_json
    FROM research_breath_curve_policy_run r
    {latest_join}
    JOIN research_breath_curve_policy_result x
      ON x.research_breath_curve_policy_run_id = r.research_breath_curve_policy_run_id
    WHERE {run_filter}
      {policy_filter}
    ORDER BY
        r.research_breath_curve_policy_run_id,
        x.symbol,
        x.anchor_date,
        x.checkpoint_ratio
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, tuple(params))
        rows = list(cur.fetchall())

    out: list[PolicyRow] = []
    for row in rows:
        source_row = parse_json_dict(row.get("source_row_json"))
        out.append(
            PolicyRow(
                run_id=int(row["run_id"]),
                policy_name=str(row["policy_name"]),
                policy_version=str(row["policy_version"]),
                checkpoint_set=str(row["checkpoint_set"]),
                cost_bps=float(row["cost_bps"] or 0.0),
                require_offset_match=truthy(row["require_offset_match"]),
                symbol=str(row["symbol"]),
                anchor_date=str(row["anchor_date"]),
                checkpoint_ratio=str(row["checkpoint_ratio"]),
                offset_matches_best_full=truthy(row["offset_matches_best_full"]),
                policy_return_pct=float(row["policy_return_pct"]),
                return_to_1000_pct=maybe_float(row.get("return_to_1000_pct")),
                return_to_1272_pct=maybe_float(row.get("return_to_1272_pct")),
                source_row=source_row,
            )
        )

    return out


def fetch_candles(conn: Any, *, symbol: str, venue: str, interval_code: str) -> list[Candle]:
    cols = table_cols(conn, "obs_market_candle")

    asset_col = choose(cols, ["asset_id"])
    ts_col = choose(cols, ["open_ts_utc", "close_ts_utc", "ts_utc", "timestamp_utc"])
    close_col = choose(cols, ["close", "close_price", "close_close", "c"])
    venue_col = choose(cols, ["venue"], required=False)
    interval_col = choose(cols, ["interval_code", "timeframe"], required=False)

    asset_id = resolve_asset_id(conn, symbol)

    where = [f"`{asset_col}` = %s"]
    params: list[Any] = [asset_id]

    if venue_col:
        where.append(f"`{venue_col}` = %s")
        params.append(venue)

    if interval_col:
        where.append(f"`{interval_col}` = %s")
        params.append(interval_code)

    sql = f"""
    SELECT
        `{ts_col}` AS ts,
        `{close_col}` AS close_price
    FROM obs_market_candle
    WHERE {' AND '.join(where)}
    ORDER BY `{ts_col}` ASC
    """

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, tuple(params))
        rows = list(cur.fetchall())

    out: list[Candle] = []
    for row in rows:
        ts = row["ts"]
        if isinstance(ts, str):
            dt = parse_dt(ts)
        else:
            dt = ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)

        out.append(Candle(ts=dt, close=float(row["close_price"])))

    return out


def close_at_or_before(candles: list[Candle], ts: datetime) -> float | None:
    prior: Candle | None = None
    for candle in candles:
        if candle.ts <= ts:
            prior = candle
        else:
            break
    return prior.close if prior else None


def pct_return(start_price: float | None, end_price: float | None, cost_bps: float) -> float | None:
    if start_price is None or end_price is None or start_price == 0:
        return None
    gross = ((end_price / start_price) - 1.0) * 100.0
    return gross - (cost_bps / 100.0)


def source_ts(row: PolicyRow, key: str) -> datetime | None:
    raw = str(row.source_row.get(key, "")).strip()
    if not raw:
        return None
    try:
        return parse_dt(raw)
    except Exception:
        return None


def same_window_return(row: PolicyRow, candles: list[Candle]) -> float | None:
    as_of = source_ts(row, "as_of_ts_utc")
    target = source_ts(row, "future_target_expected_ts_utc")

    if as_of is None or target is None or target <= as_of:
        return None

    start_price = close_at_or_before(candles, as_of)
    end_price = close_at_or_before(candles, target)
    return pct_return(start_price, end_price, row.cost_bps)


def random_anchor_returns(
    row: PolicyRow,
    candles: list[Candle],
    *,
    rng: random.Random,
    samples: int,
) -> list[float]:
    as_of = source_ts(row, "as_of_ts_utc")
    target = source_ts(row, "future_target_expected_ts_utc")

    if as_of is None or target is None or target <= as_of or len(candles) < 3 or samples <= 0:
        return []

    duration = target - as_of
    latest_start = candles[-1].ts - duration
    candidates = [c for c in candles if c.ts <= latest_start]
    if not candidates:
        return []

    returns: list[float] = []
    for _ in range(samples):
        start_candle = rng.choice(candidates)
        end_ts = start_candle.ts + duration
        end_price = close_at_or_before(candles, end_ts)
        value = pct_return(start_candle.close, end_price, row.cost_bps)
        if value is not None:
            returns.append(value)

    return returns


def evaluate_rows(
    rows: list[PolicyRow],
    candles_by_symbol: dict[str, list[Candle]],
    *,
    random_samples_per_row: int,
    seed: int,
) -> list[EvaluatedRow]:
    rng = random.Random(seed)
    evaluated: list[EvaluatedRow] = []

    for row in rows:
        candles = candles_by_symbol.get(row.symbol, [])
        same = same_window_return(row, candles)
        random_returns = random_anchor_returns(
            row,
            candles,
            rng=rng,
            samples=random_samples_per_row,
        )
        random_avg = sum(random_returns) / len(random_returns) if random_returns else None

        evaluated.append(
            EvaluatedRow(
                run_id=row.run_id,
                policy_name=row.policy_name,
                symbol=row.symbol,
                anchor_date=row.anchor_date,
                checkpoint_ratio=row.checkpoint_ratio,
                offset_matches_best_full=row.offset_matches_best_full,
                context_bucket=context_bucket(row.source_row),
                policy_return_pct=row.policy_return_pct,
                same_window_return_pct=same,
                random_anchor_return_pct=random_avg,
                random_sample_count=len(random_returns),
            )
        )

    return evaluated


def avg(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def positive_rate(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(1 for value in values if value > 0.0) / len(values) * 100.0


def summary_for(rows: list[EvaluatedRow]) -> dict[str, float | int | None]:
    policy_values = [row.policy_return_pct for row in rows]
    same_values = [row.same_window_return_pct for row in rows if row.same_window_return_pct is not None]
    random_values = [row.random_anchor_return_pct for row in rows if row.random_anchor_return_pct is not None]

    avg_policy = avg(policy_values)
    avg_same = avg(same_values)
    avg_random = avg(random_values)

    return {
        "rows": len(rows),
        "avg_policy": avg_policy,
        "median_policy": median(policy_values) if policy_values else None,
        "policy_positive": positive_rate(policy_values),
        "avg_same_window": avg_same,
        "same_window_positive": positive_rate(same_values),
        "edge_vs_same_window": (avg_policy - avg_same) if avg_policy is not None and avg_same is not None else None,
        "avg_random_anchor": avg_random,
        "random_anchor_positive": positive_rate(random_values),
        "edge_vs_random_anchor": (avg_policy - avg_random) if avg_policy is not None and avg_random is not None else None,
        "random_rows": len(random_values),
    }


def grouped(rows: list[EvaluatedRow], key_fn: Any) -> dict[str, list[EvaluatedRow]]:
    out: dict[str, list[EvaluatedRow]] = {}
    for row in rows:
        out.setdefault(str(key_fn(row)), []).append(row)
    return out


def print_summary_block(title: str, groups: dict[str, list[EvaluatedRow]], limit: int | None = None) -> None:
    print()
    print(f"--- {title} ---")

    items = []
    for name, rows in groups.items():
        stats = summary_for(rows)
        items.append((name, stats))

    items.sort(key=lambda item: (float(item[1]["avg_policy"] or -999999.0)), reverse=True)
    if limit is not None:
        items = items[:limit]

    print_table(
        [
            "bucket",
            "rows",
            "avg_policy",
            "pos_policy",
            "avg_same",
            "edge_same",
            "avg_random",
            "edge_random",
            "random_rows",
        ],
        [
            [
                name,
                str(stats["rows"]),
                fmt(stats["avg_policy"]),
                fmt(stats["policy_positive"], 2),
                fmt(stats["avg_same_window"]),
                fmt(stats["edge_vs_same_window"]),
                fmt(stats["avg_random_anchor"]),
                fmt(stats["edge_vs_random_anchor"]),
                str(stats["random_rows"]),
            ]
            for name, stats in items
        ],
    )


def write_csv(path: Path, rows: list[EvaluatedRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "run_id",
        "policy_name",
        "symbol",
        "anchor_date",
        "checkpoint_ratio",
        "offset_matches_best_full",
        "context_bucket",
        "policy_return_pct",
        "same_window_return_pct",
        "random_anchor_return_pct",
        "random_sample_count",
        "policy_edge_vs_same_window_pct",
        "policy_edge_vs_random_anchor_pct",
    ]

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "run_id": row.run_id,
                    "policy_name": row.policy_name,
                    "symbol": row.symbol,
                    "anchor_date": row.anchor_date,
                    "checkpoint_ratio": row.checkpoint_ratio,
                    "offset_matches_best_full": int(row.offset_matches_best_full),
                    "context_bucket": row.context_bucket,
                    "policy_return_pct": fmt(row.policy_return_pct),
                    "same_window_return_pct": fmt(row.same_window_return_pct),
                    "random_anchor_return_pct": fmt(row.random_anchor_return_pct),
                    "random_sample_count": row.random_sample_count,
                    "policy_edge_vs_same_window_pct": fmt(
                        row.policy_return_pct - row.same_window_return_pct
                        if row.same_window_return_pct is not None
                        else None
                    ),
                    "policy_edge_vs_random_anchor_pct": fmt(
                        row.policy_return_pct - row.random_anchor_return_pct
                        if row.random_anchor_return_pct is not None
                        else None
                    ),
                }
            )


def parse_run_ids(raw: str) -> list[int]:
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Research-only Breath Curve policy baseline comparison."
    )
    parser.add_argument("--run-ids", default="", help="Comma-separated policy run IDs. Overrides latest-per-policy mode.")
    parser.add_argument("--latest-per-policy", action="store_true", default=True)
    parser.add_argument("--all-runs", action="store_true", help="Read all policy runs instead of latest per policy.")
    parser.add_argument("--policy-name-like", default=None)
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", dest="interval_code", default="1d")
    parser.add_argument("--random-samples-per-row", type=int, default=20)
    parser.add_argument("--seed", type=int, default=2801)
    parser.add_argument("--symbol-limit", type=int, default=0)
    parser.add_argument("--output-csv", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_dotenv(dotenv_path=".env", override=False)

    run_ids = parse_run_ids(args.run_ids)
    latest_per_policy = bool(args.latest_per_policy and not args.all_runs and not run_ids)

    conn = get_db_connection()
    try:
        policy_rows = fetch_policy_rows(
            conn,
            run_ids=run_ids,
            latest_per_policy=latest_per_policy,
            policy_name_like=args.policy_name_like,
        )

        symbols = sorted({row.symbol for row in policy_rows})
        if args.symbol_limit > 0:
            symbols = symbols[: args.symbol_limit]

        candles_by_symbol = {
            symbol: fetch_candles(
                conn,
                symbol=symbol,
                venue=args.venue,
                interval_code=args.interval_code,
            )
            for symbol in symbols
        }
    finally:
        conn.close()

    filtered_policy_rows = [row for row in policy_rows if row.symbol in candles_by_symbol]
    evaluated = evaluate_rows(
        filtered_policy_rows,
        candles_by_symbol,
        random_samples_per_row=args.random_samples_per_row,
        seed=args.seed,
    )

    print(f"report={REPORT_NAME} version={VERSION}")
    print("scope=research-only market-only account-agnostic")
    print("broker_calls=0 broker_writes=0 order_submission=0 decision_gate=none execution_planner=none executor=none")
    print(f"rows_input={len(policy_rows)} rows_evaluated={len(evaluated)} symbols={len(candles_by_symbol)}")
    print(f"latest_per_policy={latest_per_policy} run_ids={','.join(str(x) for x in run_ids)}")
    print(f"venue={args.venue} interval={args.interval_code}")
    print(f"random_samples_per_row={args.random_samples_per_row} seed={args.seed}")

    print_summary_block("overall", {"ALL": evaluated})
    print_summary_block("checkpoint comparison", grouped(evaluated, lambda row: row.checkpoint_ratio))
    print_summary_block(
        "offset-match-only variant",
        {
            "offset_match_only": [row for row in evaluated if row.offset_matches_best_full],
            "offset_non_match": [row for row in evaluated if not row.offset_matches_best_full],
        },
    )
    print_summary_block("by policy", grouped(evaluated, lambda row: row.policy_name))
    print_summary_block("by symbol", grouped(evaluated, lambda row: row.symbol))
    print_summary_block("context buckets", grouped(evaluated, lambda row: row.context_bucket), limit=30)

    if args.output_csv:
        output_path = Path(args.output_csv)
        write_csv(output_path, evaluated)
        print()
        print(f"wrote_csv={output_path}")

    print()
    print(
        f"[DONE] evaluated_rows={len(evaluated)} db_writes=0 "
        "broker_calls=0 broker_writes=0 order_submission=0"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
