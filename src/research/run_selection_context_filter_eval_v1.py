from __future__ import annotations

import argparse
import json
from decimal import Decimal
from typing import Any

from src.common.db import get_connection


DEFAULT_VENUE = "bitvavo"
DEFAULT_ENGINE_NAME = "selection_engine_v2"
DEFAULT_ENGINE_VERSION = "2.0"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate selection v2 context filters against forward returns."
    )
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--engine-name", default=DEFAULT_ENGINE_NAME)
    parser.add_argument("--engine-version", default=DEFAULT_ENGINE_VERSION)
    parser.add_argument("--selection-state", default="WATCHLIST")
    parser.add_argument("--rank-min", type=int, default=4)
    parser.add_argument("--rank-max", type=int, default=10)
    parser.add_argument("--btc-prior-min", default="-0.015")
    parser.add_argument("--btc-prior-max", default="0.015")
    parser.add_argument("--fee-bps-per-side", default="25")
    parser.add_argument("--min-symbol-rows", type=int, default=5)
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args()


def _as_decimal(value: str) -> Decimal:
    return Decimal(str(value))


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def _base_cte() -> str:
    return """
        WITH btc AS (
            SELECT asset_id
            FROM asset
            WHERE symbol = 'BTC'
            LIMIT 1
        ),
        eval AS (
            SELECT
                r.replay_asof_ts_utc,
                DATE(r.replay_asof_ts_utc) AS replay_day,
                r.asset_id,
                r.symbol,
                r.selection_state,
                r.selection_bias,
                r.selection_score,
                r.priority_rank,

                CASE
                    WHEN btc_now.close_price IS NULL
                      OR btc_prev24.close_price IS NULL
                      OR btc_prev24.close_price = 0
                    THEN NULL
                    ELSE ((btc_now.close_price - btc_prev24.close_price) / btc_prev24.close_price)
                END AS btc_prior_24h,

                CASE
                    WHEN e.close_price IS NULL OR e.close_price = 0 OR f4.close_price IS NULL
                    THEN NULL
                    ELSE ((f4.close_price - e.close_price) / e.close_price) - %s
                END AS net_4h,

                CASE
                    WHEN e.close_price IS NULL OR e.close_price = 0 OR f24.close_price IS NULL
                    THEN NULL
                    ELSE ((f24.close_price - e.close_price) / e.close_price) - %s
                END AS net_24h

            FROM synth_bt.bt_selection_v2_replay r

            LEFT JOIN obs_market_candle e
              ON e.asset_id = r.asset_id
             AND e.venue = r.venue
             AND e.interval_code = '1h'
             AND e.close_ts_utc = r.replay_asof_ts_utc

            LEFT JOIN obs_market_candle f4
              ON f4.asset_id = r.asset_id
             AND f4.venue = r.venue
             AND f4.interval_code = '1h'
             AND f4.close_ts_utc = DATE_ADD(r.replay_asof_ts_utc, INTERVAL 4 HOUR)

            LEFT JOIN obs_market_candle f24
              ON f24.asset_id = r.asset_id
             AND f24.venue = r.venue
             AND f24.interval_code = '1h'
             AND f24.close_ts_utc = DATE_ADD(r.replay_asof_ts_utc, INTERVAL 24 HOUR)

            JOIN btc

            LEFT JOIN obs_market_candle btc_now
              ON btc_now.asset_id = btc.asset_id
             AND btc_now.venue = r.venue
             AND btc_now.interval_code = '1h'
             AND btc_now.close_ts_utc = r.replay_asof_ts_utc

            LEFT JOIN obs_market_candle btc_prev24
              ON btc_prev24.asset_id = btc.asset_id
             AND btc_prev24.venue = r.venue
             AND btc_prev24.interval_code = '1h'
             AND btc_prev24.close_ts_utc = DATE_SUB(r.replay_asof_ts_utc, INTERVAL 24 HOUR)

            WHERE r.venue = %s
              AND r.engine_name = %s
              AND r.engine_version = %s
              AND r.selection_state = %s
        )
    """


def fetch_rows(
    *,
    venue: str,
    engine_name: str,
    engine_version: str,
    selection_state: str,
    rank_min: int,
    rank_max: int,
    btc_prior_min: Decimal,
    btc_prior_max: Decimal,
    fee_bps_per_side: Decimal,
    min_symbol_rows: int,
) -> dict[str, list[dict[str, Any]]]:
    roundtrip_fee = (fee_bps_per_side * Decimal("2")) / Decimal("10000")

    base_params: list[Any] = [
        str(roundtrip_fee),
        str(roundtrip_fee),
        venue,
        engine_name,
        engine_version,
        selection_state,
    ]

    filter_params: list[Any] = [
        rank_min,
        rank_max,
        str(btc_prior_min),
        str(btc_prior_max),
    ]

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                _base_cte()
                + """
                SELECT
                    CASE
                        WHEN priority_rank BETWEEN %s AND %s
                         AND btc_prior_24h >= %s
                         AND btc_prior_24h <= %s
                        THEN 'PASS'
                        ELSE 'FAIL'
                    END AS rule_bucket,
                    COUNT(*) AS n,
                    COUNT(net_24h) AS n_24h,
                    ROUND(AVG(net_4h), 6) AS avg_net_4h,
                    ROUND(AVG(net_24h), 6) AS avg_net_24h,
                    ROUND(AVG(net_4h > 0), 4) AS win_4h,
                    ROUND(AVG(net_24h > 0), 4) AS win_24h
                FROM eval
                GROUP BY rule_bucket
                ORDER BY avg_net_24h DESC
                """,
                base_params + filter_params,
            )
            overall = list(cur.fetchall())

            cur.execute(
                _base_cte()
                + """
                SELECT
                    replay_day AS day,
                    COUNT(*) AS n,
                    COUNT(net_24h) AS n_24h,
                    ROUND(AVG(net_4h), 6) AS avg_net_4h,
                    ROUND(AVG(net_24h), 6) AS avg_net_24h,
                    ROUND(AVG(net_4h > 0), 4) AS win_4h,
                    ROUND(AVG(net_24h > 0), 4) AS win_24h
                FROM eval
                WHERE priority_rank BETWEEN %s AND %s
                  AND btc_prior_24h >= %s
                  AND btc_prior_24h <= %s
                GROUP BY replay_day
                ORDER BY replay_day
                """,
                base_params + filter_params,
            )
            by_day = list(cur.fetchall())

            cur.execute(
                _base_cte()
                + """
                SELECT
                    symbol,
                    COUNT(*) AS n,
                    COUNT(net_24h) AS n_24h,
                    ROUND(AVG(net_4h), 6) AS avg_net_4h,
                    ROUND(AVG(net_24h), 6) AS avg_net_24h,
                    ROUND(AVG(net_4h > 0), 4) AS win_4h,
                    ROUND(AVG(net_24h > 0), 4) AS win_24h
                FROM eval
                WHERE priority_rank BETWEEN %s AND %s
                  AND btc_prior_24h >= %s
                  AND btc_prior_24h <= %s
                GROUP BY symbol
                HAVING n_24h >= %s
                ORDER BY avg_net_24h DESC
                """,
                base_params + filter_params + [min_symbol_rows],
            )
            by_symbol = list(cur.fetchall())

            cur.execute(
                _base_cte()
                + """
                SELECT
                    CASE
                        WHEN btc_prior_24h < -0.030 THEN 'lt_minus_3pct'
                        WHEN btc_prior_24h < -0.015 THEN 'minus_3_to_minus_1p5pct'
                        WHEN btc_prior_24h < 0.000 THEN 'minus_1p5_to_0pct'
                        WHEN btc_prior_24h < 0.015 THEN 'zero_to_1p5pct'
                        WHEN btc_prior_24h < 0.030 THEN 'onep5_to_3pct'
                        ELSE 'gte_3pct'
                    END AS btc_prior_bucket,
                    CASE
                        WHEN priority_rank <= 3 THEN 'rank_1_3'
                        WHEN priority_rank <= 10 THEN 'rank_4_10'
                        WHEN priority_rank <= 20 THEN 'rank_11_20'
                        ELSE 'rank_21_plus'
                    END AS rank_bucket,
                    COUNT(*) AS n,
                    COUNT(net_24h) AS n_24h,
                    ROUND(AVG(net_24h), 6) AS avg_net_24h,
                    ROUND(AVG(net_24h > 0), 4) AS win_24h
                FROM eval
                WHERE btc_prior_24h IS NOT NULL
                GROUP BY btc_prior_bucket, rank_bucket
                HAVING n_24h >= 20
                ORDER BY btc_prior_bucket, rank_bucket
                """,
                base_params,
            )
            grid = list(cur.fetchall())

        return {
            "overall": overall,
            "by_day": by_day,
            "by_symbol": by_symbol,
            "grid": grid,
        }

    finally:
        conn.close()


def print_table(title: str, rows: list[dict[str, Any]]) -> None:
    print(f"\n=== {title} ===")
    if not rows:
        print("(no rows)")
        return

    headers = list(rows[0].keys())
    printable = [[str(row.get(header, "")) for header in headers] for row in rows]

    widths = [len(header) for header in headers]
    for row in printable:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(value))

    def fmt(values: list[str]) -> str:
        return " | ".join(value.ljust(widths[idx]) for idx, value in enumerate(values))

    print(fmt(headers))
    print("-+-".join("-" * width for width in widths))
    for row in printable:
        print(fmt(row))


def main() -> int:
    args = parse_args()

    result = fetch_rows(
        venue=str(args.venue),
        engine_name=str(args.engine_name),
        engine_version=str(args.engine_version),
        selection_state=str(args.selection_state),
        rank_min=int(args.rank_min),
        rank_max=int(args.rank_max),
        btc_prior_min=_as_decimal(args.btc_prior_min),
        btc_prior_max=_as_decimal(args.btc_prior_max),
        fee_bps_per_side=_as_decimal(args.fee_bps_per_side),
        min_symbol_rows=int(args.min_symbol_rows),
    )

    if args.output == "json":
        print(json.dumps(result, indent=2, ensure_ascii=False, default=_json_default))
        return 0

    print_table("overall", result["overall"])
    print_table("by_day", result["by_day"])
    print_table("by_symbol", result["by_symbol"])
    print_table("btc_prior_rank_grid", result["grid"])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
