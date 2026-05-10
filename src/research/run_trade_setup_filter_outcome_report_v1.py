from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from statistics import mean, median
from typing import Any

from dotenv import load_dotenv

from src.common.db import get_db_connection


@dataclass(frozen=True)
class OutcomeRow:
    symbol: str
    asset_id: int
    asof_ts_utc: datetime
    setup_filter_state: str
    setup_filter_reason: str
    selection_state: str
    priority_rank: int | None
    selection_score: Decimal | None
    btc_prior_24h: Decimal | None
    base_ts_utc: datetime
    future_ts_utc: datetime
    base_close: Decimal
    future_close: Decimal
    horizon_hours: int
    return_pct: Decimal


def parse_iso_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only outcome report for trade_setup_filter observations."
    )
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--outcome-interval", default="1h")
    parser.add_argument("--setup-state", default="PASS")
    parser.add_argument("--filter-name", default="trade_setup_filter_v1")
    parser.add_argument("--filter-version", default=None)
    parser.add_argument("--asset-suitability-mode", default=None)
    parser.add_argument("--from-ts", default=None)
    parser.add_argument("--to-ts", default=None)
    parser.add_argument("--horizon-hours", action="append", type=int, default=None)
    parser.add_argument("--min-trades", type=int, default=5)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--csv-out", default=None)
    return parser.parse_args()


def fetch_rows(
    conn: Any,
    *,
    venue: str,
    outcome_interval: str,
    setup_state: str,
    filter_name: str,
    filter_version: str | None,
    asset_suitability_mode: str | None,
    from_ts: datetime | None,
    to_ts: datetime | None,
    horizon_hours: int,
    limit: int | None,
) -> list[OutcomeRow]:
    where_parts = [
        "o.venue = %s",
        "o.setup_filter_state = %s",
        "o.filter_name = %s",
    ]
    params: list[Any] = [venue, setup_state, filter_name]

    if filter_version is not None:
        where_parts.append("o.filter_version = %s")
        params.append(filter_version)

    if asset_suitability_mode is not None:
        where_parts.append("o.asset_suitability_mode = %s")
        params.append(asset_suitability_mode)

    if from_ts is not None:
        where_parts.append("o.asof_ts_utc >= %s")
        params.append(from_ts.replace(tzinfo=None))

    if to_ts is not None:
        where_parts.append("o.asof_ts_utc < %s")
        params.append(to_ts.replace(tzinfo=None))

    limit_sql = ""
    if limit is not None:
        if limit <= 0:
            raise ValueError("--limit must be positive when provided")
        limit_sql = f"LIMIT {int(limit)}"

    sql = f"""
    WITH observations AS (
        SELECT
            o.trade_setup_filter_observation_id,
            o.asset_id,
            o.symbol,
            o.venue,
            o.asof_ts_utc,
            o.setup_filter_state,
            o.setup_filter_reason,
            o.selection_state,
            o.priority_rank,
            o.selection_score,
            o.btc_prior_24h
        FROM trade_setup_filter_observation o
        WHERE {" AND ".join(where_parts)}
        ORDER BY o.asof_ts_utc, o.asset_id
        {limit_sql}
    ),
    base_resolved AS (
        SELECT
            o.*,
            (
                SELECT c.close_ts_utc
                FROM obs_market_candle c
                WHERE c.asset_id = o.asset_id
                  AND c.venue = o.venue
                  AND c.interval_code = %s
                  AND c.close_ts_utc <= o.asof_ts_utc
                ORDER BY c.close_ts_utc DESC
                LIMIT 1
            ) AS base_ts_utc,
            (
                SELECT c.close_price
                FROM obs_market_candle c
                WHERE c.asset_id = o.asset_id
                  AND c.venue = o.venue
                  AND c.interval_code = %s
                  AND c.close_ts_utc <= o.asof_ts_utc
                ORDER BY c.close_ts_utc DESC
                LIMIT 1
            ) AS base_close
        FROM observations o
    ),
    future_resolved AS (
        SELECT
            b.*,
            (
                SELECT c.close_ts_utc
                FROM obs_market_candle c
                WHERE c.asset_id = b.asset_id
                  AND c.venue = b.venue
                  AND c.interval_code = %s
                  AND c.close_ts_utc >= DATE_ADD(b.base_ts_utc, INTERVAL {int(horizon_hours)} HOUR)
                ORDER BY c.close_ts_utc ASC
                LIMIT 1
            ) AS future_ts_utc,
            (
                SELECT c.close_price
                FROM obs_market_candle c
                WHERE c.asset_id = b.asset_id
                  AND c.venue = b.venue
                  AND c.interval_code = %s
                  AND c.close_ts_utc >= DATE_ADD(b.base_ts_utc, INTERVAL {int(horizon_hours)} HOUR)
                ORDER BY c.close_ts_utc ASC
                LIMIT 1
            ) AS future_close
        FROM base_resolved b
        WHERE b.base_ts_utc IS NOT NULL
          AND b.base_close IS NOT NULL
    )
    SELECT
        symbol,
        asset_id,
        asof_ts_utc,
        setup_filter_state,
        setup_filter_reason,
        selection_state,
        priority_rank,
        selection_score,
        btc_prior_24h,
        base_ts_utc,
        future_ts_utc,
        base_close,
        future_close
    FROM future_resolved
    WHERE future_ts_utc IS NOT NULL
      AND future_close IS NOT NULL
      AND base_close > 0
    ORDER BY asof_ts_utc, asset_id
    """

    all_params = params + [outcome_interval, outcome_interval, outcome_interval, outcome_interval]

    with conn.cursor() as cur:
        cur.execute(sql, tuple(all_params))
        raw_rows = cur.fetchall()

    rows: list[OutcomeRow] = []

    for raw in raw_rows:
        if not isinstance(raw, dict):
            raise TypeError("Expected dict rows from DB cursor")

        base_close = Decimal(str(raw["base_close"]))
        future_close = Decimal(str(raw["future_close"]))
        return_pct = ((future_close / base_close) - Decimal("1")) * Decimal("100")

        rows.append(
            OutcomeRow(
                symbol=str(raw["symbol"]).upper(),
                asset_id=int(raw["asset_id"]),
                asof_ts_utc=raw["asof_ts_utc"],
                setup_filter_state=str(raw["setup_filter_state"]),
                setup_filter_reason=str(raw["setup_filter_reason"]),
                selection_state=str(raw["selection_state"]),
                priority_rank=None if raw["priority_rank"] is None else int(raw["priority_rank"]),
                selection_score=None if raw["selection_score"] is None else Decimal(str(raw["selection_score"])),
                btc_prior_24h=None if raw["btc_prior_24h"] is None else Decimal(str(raw["btc_prior_24h"])),
                base_ts_utc=raw["base_ts_utc"],
                future_ts_utc=raw["future_ts_utc"],
                base_close=base_close,
                future_close=future_close,
                horizon_hours=horizon_hours,
                return_pct=return_pct,
            )
        )

    return rows


def summarize(label: str, rows: list[OutcomeRow]) -> dict[str, Any]:
    returns = [float(row.return_pct) for row in rows]
    wins = [value for value in returns if value > 0]
    losses = [value for value in returns if value <= 0]

    return {
        "label": label,
        "trades": len(rows),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": 0.0 if not rows else (len(wins) / len(rows)) * 100.0,
        "avg_return_pct": 0.0 if not rows else mean(returns),
        "median_return_pct": 0.0 if not rows else median(returns),
        "min_return_pct": 0.0 if not rows else min(returns),
        "max_return_pct": 0.0 if not rows else max(returns),
    }


def print_summary(title: str, summaries: list[dict[str, Any]]) -> None:
    print()
    print(title)
    print(
        "label,trades,wins,losses,win_rate_pct,avg_return_pct,"
        "median_return_pct,min_return_pct,max_return_pct"
    )

    for item in summaries:
        print(
            f"{item['label']},"
            f"{item['trades']},"
            f"{item['wins']},"
            f"{item['losses']},"
            f"{item['win_rate_pct']:.2f},"
            f"{item['avg_return_pct']:.4f},"
            f"{item['median_return_pct']:.4f},"
            f"{item['min_return_pct']:.4f},"
            f"{item['max_return_pct']:.4f}"
        )


def write_csv(path: Path, rows: list[OutcomeRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "symbol",
                "asset_id",
                "asof_ts_utc",
                "setup_filter_state",
                "setup_filter_reason",
                "selection_state",
                "priority_rank",
                "selection_score",
                "btc_prior_24h",
                "base_ts_utc",
                "future_ts_utc",
                "base_close",
                "future_close",
                "horizon_hours",
                "return_pct",
            ]
        )

        for row in rows:
            writer.writerow(
                [
                    row.symbol,
                    row.asset_id,
                    row.asof_ts_utc,
                    row.setup_filter_state,
                    row.setup_filter_reason,
                    row.selection_state,
                    row.priority_rank,
                    row.selection_score,
                    row.btc_prior_24h,
                    row.base_ts_utc,
                    row.future_ts_utc,
                    row.base_close,
                    row.future_close,
                    row.horizon_hours,
                    row.return_pct,
                ]
            )


def main() -> int:
    load_dotenv()

    args = parse_args()
    horizons = args.horizon_hours if args.horizon_hours else [4, 12, 24, 72, 168]

    from_ts = parse_iso_utc(args.from_ts) if args.from_ts else None
    to_ts = parse_iso_utc(args.to_ts) if args.to_ts else None

    conn = get_db_connection()

    all_rows: list[OutcomeRow] = []

    try:
        for horizon in horizons:
            if horizon <= 0:
                raise ValueError("All --horizon-hours values must be positive")

            rows = fetch_rows(
                conn,
                venue=args.venue,
                outcome_interval=args.outcome_interval,
                setup_state=args.setup_state,
                filter_name=args.filter_name,
                filter_version=args.filter_version,
                asset_suitability_mode=args.asset_suitability_mode,
                from_ts=from_ts,
                to_ts=to_ts,
                horizon_hours=horizon,
                limit=args.limit,
            )
            all_rows.extend(rows)

            overall = [summarize(f"ALL_PASS_{horizon}H", rows)]

            by_symbol: dict[str, list[OutcomeRow]] = defaultdict(list)
            for row in rows:
                by_symbol[row.symbol].append(row)

            symbol_summaries = [
                summarize(symbol, symbol_rows)
                for symbol, symbol_rows in sorted(by_symbol.items())
            ]
            symbol_summaries.sort(
                key=lambda item: (
                    item["trades"] >= args.min_trades,
                    item["avg_return_pct"],
                    item["win_rate_pct"],
                    item["trades"],
                ),
                reverse=True,
            )

            print_summary(f"--- horizon={horizon}h overall ---", overall)
            print_summary(f"--- horizon={horizon}h by symbol ---", symbol_summaries)

            strong = [
                item for item in symbol_summaries
                if item["trades"] >= args.min_trades
                and item["avg_return_pct"] > 0
                and item["win_rate_pct"] >= 50
            ]

            weak = [
                item for item in symbol_summaries
                if item["trades"] >= args.min_trades
                and item["avg_return_pct"] < 0
                and item["win_rate_pct"] < 50
            ]

            print_summary(f"--- horizon={horizon}h candidate_allowlist ---", strong)
            print_summary(f"--- horizon={horizon}h candidate_blocklist ---", weak)

        if args.csv_out:
            write_csv(Path(args.csv_out), all_rows)
            print()
            print(f"[DONE] wrote csv={args.csv_out} rows={len(all_rows)}")

        print()
        print(f"[DONE] evaluated rows={len(all_rows)} horizons={horizons}")
        return 0

    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
