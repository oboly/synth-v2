from __future__ import annotations

"""
Synth v2 - Replay Policy Eval V1.

LAYER:
research/backtest evaluation

BOUNDARY:
Allowed:
- read synth_bt.bt_selection_v2_replay
- read market/ranking/candle context
- build synth_bt research eval table
- evaluate market-only policy variants

Forbidden:
- account state
- balances
- positions
- orders
- execution plans
- broker actions

Notes:
- This is research tooling only.
- It intentionally rebuilds a materialized eval table to avoid slow ad hoc SQL.
"""

import argparse
import json
from decimal import Decimal
from typing import Any

from src.common.db import get_connection


SOURCE_DB = "synth"
BT_DB = "synth_bt"
EVAL_TABLE = "bt_selection_v2_replay_eval_horizon_v1"

DEFAULT_VENUE = "bitvavo"
DEFAULT_ENGINE_NAME = "selection_engine_v2"
DEFAULT_ENGINE_VERSION = "2.0"
DEFAULT_FEE_BPS_PER_SIDE = Decimal("25")

WEAK_SET = ("HNT", "SOL", "XLM", "LTC", "ETH", "XRP", "CC", "NOT")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Automated replay policy evaluation for Synth v2."
    )
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--engine-name", default=DEFAULT_ENGINE_NAME)
    parser.add_argument("--engine-version", default=DEFAULT_ENGINE_VERSION)
    parser.add_argument("--fee-bps-per-side", default=str(DEFAULT_FEE_BPS_PER_SIDE))
    parser.add_argument("--refresh-eval-table", action="store_true")
    parser.add_argument("--min-rows", type=int, default=25)
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args()


def _as_decimal(value: str | Decimal) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def _print_table(title: str, rows: list[dict[str, Any]]) -> None:
    print()
    print(f"=== {title} ===")

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


def rebuild_eval_table(
    *,
    venue: str,
    engine_name: str,
    engine_version: str,
    fee_bps_per_side: Decimal,
) -> None:
    roundtrip_fee = (fee_bps_per_side * Decimal("2")) / Decimal("10000")

    sql = f"""
    DROP TABLE IF EXISTS {BT_DB}.{EVAL_TABLE};

    CREATE TABLE {BT_DB}.{EVAL_TABLE} AS
    SELECT
        r.bt_selection_v2_replay_id,
        r.asset_id,
        r.symbol,
        r.venue,
        r.replay_asof_ts_utc,
        r.selection_state,
        r.selection_bias,
        r.selection_score,
        r.priority_rank,
        r.allow_trade_flag,
        r.allowed_sleeves,
        r.blocked_reason,
        r.trade_quality_score,
        r.timing_refinement_score,
        r.quality_penalty,
        r.quality_status_1d,
        r.quality_status_4h,
        r.quality_status_1h,

        rs.rotation_bucket,
        rs.classification_code,
        rs.sleeve_fit_code,
        rs.relative_strength_score,
        rs.context_score,
        rs.pullback_quality_score,
        rs.expansion_position_score,
        rs.signal_confidence_score,

        CASE
            WHEN btc_now.close_price IS NULL
              OR btc_prev24.close_price IS NULL
              OR btc_prev24.close_price = 0
            THEN NULL
            ELSE ((btc_now.close_price - btc_prev24.close_price) / btc_prev24.close_price)
        END AS btc_prior_24h,

        e.close_price AS entry_close_price,

        f4.close_price AS forward_close_price_4h,
        CASE
            WHEN e.close_price IS NULL
              OR e.close_price = 0
              OR f4.close_price IS NULL
            THEN NULL
            ELSE (f4.close_price - e.close_price) / e.close_price
        END AS gross_return_4h,
        CASE
            WHEN e.close_price IS NULL
              OR e.close_price = 0
              OR f4.close_price IS NULL
            THEN NULL
            ELSE ((f4.close_price - e.close_price) / e.close_price) - {roundtrip_fee}
        END AS net_return_4h,

        f24.close_price AS forward_close_price_24h,
        CASE
            WHEN e.close_price IS NULL
              OR e.close_price = 0
              OR f24.close_price IS NULL
            THEN NULL
            ELSE (f24.close_price - e.close_price) / e.close_price
        END AS gross_return_24h,
        CASE
            WHEN e.close_price IS NULL
              OR e.close_price = 0
              OR f24.close_price IS NULL
            THEN NULL
            ELSE ((f24.close_price - e.close_price) / e.close_price) - {roundtrip_fee}
        END AS net_return_24h,

        CURRENT_TIMESTAMP(6) AS created_ts_utc

    FROM {BT_DB}.bt_selection_v2_replay r

    LEFT JOIN (
        SELECT
            deduped.*
        FROM (
            SELECT
                rs.*,
                ROW_NUMBER() OVER (
                    PARTITION BY
                        rs.asset_id,
                        rs.venue,
                        rs.interval_code,
                        rs.asof_ts_utc
                    ORDER BY
                        rs.ranking_state_id DESC
                ) AS row_rank
            FROM {SOURCE_DB}.ranking_state rs
            WHERE rs.venue = '{venue}'
              AND rs.interval_code = '1h'
        ) deduped
        WHERE deduped.row_rank = 1
    ) rs
      ON rs.asset_id = r.asset_id
     AND rs.venue = '{venue}'
     AND rs.interval_code = '1h'
     AND rs.asof_ts_utc = r.replay_asof_ts_utc

    LEFT JOIN {SOURCE_DB}.obs_market_candle e
      ON e.asset_id = r.asset_id
     AND e.venue = '{venue}'
     AND e.interval_code = '1h'
     AND e.close_ts_utc = r.replay_asof_ts_utc

    LEFT JOIN {SOURCE_DB}.obs_market_candle f4
      ON f4.asset_id = r.asset_id
     AND f4.venue = '{venue}'
     AND f4.interval_code = '1h'
     AND f4.close_ts_utc = DATE_ADD(r.replay_asof_ts_utc, INTERVAL 4 HOUR)

    LEFT JOIN {SOURCE_DB}.obs_market_candle f24
      ON f24.asset_id = r.asset_id
     AND f24.venue = '{venue}'
     AND f24.interval_code = '1h'
     AND f24.close_ts_utc = DATE_ADD(r.replay_asof_ts_utc, INTERVAL 24 HOUR)

    JOIN {SOURCE_DB}.asset btc
      ON btc.symbol = 'BTC'

    LEFT JOIN {SOURCE_DB}.obs_market_candle btc_now
      ON btc_now.asset_id = btc.asset_id
     AND btc_now.venue = '{venue}'
     AND btc_now.interval_code = '1h'
     AND btc_now.close_ts_utc = r.replay_asof_ts_utc

    LEFT JOIN {SOURCE_DB}.obs_market_candle btc_prev24
      ON btc_prev24.asset_id = btc.asset_id
     AND btc_prev24.venue = '{venue}'
     AND btc_prev24.interval_code = '1h'
     AND btc_prev24.close_ts_utc = DATE_SUB(r.replay_asof_ts_utc, INTERVAL 24 HOUR)

    WHERE r.venue = '{venue}'
      AND r.engine_name = '{engine_name}'
      AND r.engine_version = '{engine_version}';

    ALTER TABLE {BT_DB}.{EVAL_TABLE}
        ADD PRIMARY KEY (bt_selection_v2_replay_id),
        ADD INDEX ix_replay_policy_eval_state_rank (
            selection_state,
            priority_rank,
            btc_prior_24h,
            selection_score
        ),
        ADD INDEX ix_replay_policy_eval_ranking (
            rotation_bucket,
            classification_code,
            sleeve_fit_code
        ),
        ADD INDEX ix_replay_policy_eval_symbol_ts (
            symbol,
            replay_asof_ts_utc
        ),
        ADD INDEX ix_replay_policy_eval_ts (
            replay_asof_ts_utc
        );
    """

    conn = get_connection(database=BT_DB)
    try:
        with conn.cursor() as cur:
            for statement in [part.strip() for part in sql.split(";") if part.strip()]:
                cur.execute(statement)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def fetch_rows(sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
    conn = get_connection(database=BT_DB)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or [])
            rows = cur.fetchall() or []
            if not all(isinstance(row, dict) for row in rows):
                raise TypeError("Expected dict rows from database cursor")
            return list(rows)
    finally:
        conn.close()


def query_coverage() -> list[dict[str, Any]]:
    return fetch_rows(
        f"""
        SELECT
            COUNT(*) AS rows_total,
            COUNT(DISTINCT bt_selection_v2_replay_id) AS distinct_replay_rows,
            COUNT(*) - COUNT(DISTINCT bt_selection_v2_replay_id) AS duplicate_rows,
            COUNT(DISTINCT replay_asof_ts_utc) AS snapshots,
            MIN(replay_asof_ts_utc) AS first_ts,
            MAX(replay_asof_ts_utc) AS last_ts,
            COUNT(entry_close_price) AS rows_with_entry,
            COUNT(forward_close_price_4h) AS rows_with_f4,
            COUNT(forward_close_price_24h) AS rows_with_f24,
            COUNT(rotation_bucket) AS rows_with_ranking
        FROM {EVAL_TABLE}
        """
    )


def query_policy_buckets() -> list[dict[str, Any]]:
    weak_symbols = ",".join(f"'{symbol}'" for symbol in WEAK_SET)

    return fetch_rows(
        f"""
        WITH policy AS (
            SELECT
                *,

                CASE
                    WHEN selection_state = 'WATCHLIST'
                     AND priority_rank BETWEEN 4 AND 10
                     AND btc_prior_24h >= -0.015
                     AND btc_prior_24h <= 0.015
                     AND symbol NOT IN ({weak_symbols})
                    THEN 'PASS_V11_BASE'

                    ELSE 'FAIL'
                END AS v11_state,

                CASE
                    WHEN selection_state = 'WATCHLIST'
                     AND priority_rank BETWEEN 4 AND 10
                     AND btc_prior_24h >= -0.015
                     AND btc_prior_24h <= 0.015
                     AND symbol NOT IN ({weak_symbols})
                     AND rotation_bucket = 'ROTATION_FOLLOWER'
                     AND classification_code = 'CONTINUATION_CANDIDATE'
                     AND sleeve_fit_code = 'SWING_STRUCTURAL'
                     AND selection_score >= 0.50400000
                    THEN 'PASS_V13_STRICT_SCORE'

                    ELSE 'FAIL'
                END AS v13_state,

                CASE
                    WHEN selection_state <> 'WATCHLIST'
                    THEN 'SELECTION_STATE_NOT_ELIGIBLE'
                    WHEN priority_rank IS NULL
                    THEN 'PRIORITY_RANK_MISSING'
                    WHEN priority_rank < 4 OR priority_rank > 10
                    THEN 'RANK_OUTSIDE_SWEET_SPOT'
                    WHEN btc_prior_24h IS NULL
                    THEN 'BTC_PRIOR_24H_MISSING'
                    WHEN btc_prior_24h < -0.015
                    THEN 'MARKET_DAMAGE_RISK'
                    WHEN btc_prior_24h > 0.015
                    THEN 'BTC_PRIOR_OVERHEAT_ZONE'
                    WHEN symbol IN ({weak_symbols})
                    THEN 'ASSET_SUITABILITY_WEAK_SET_CANDIDATE'
                    WHEN rotation_bucket IS NULL
                      OR classification_code IS NULL
                      OR sleeve_fit_code IS NULL
                    THEN 'RANKING_CONTEXT_MISSING'
                    WHEN rotation_bucket <> 'ROTATION_FOLLOWER'
                      OR classification_code <> 'CONTINUATION_CANDIDATE'
                      OR sleeve_fit_code <> 'SWING_STRUCTURAL'
                    THEN 'RANKING_ALIGNMENT_NOT_STRICT'
                    WHEN selection_score < 0.50400000
                    THEN 'RANKING_ALIGNED_SCORE_TOO_LOW'
                    ELSE 'RANKING_ALIGNED_SWING_FOLLOWER_SCORE_OK'
                END AS policy_reason
            FROM {EVAL_TABLE}
        )
        SELECT
            v13_state AS policy_state,
            policy_reason,
            COUNT(*) AS rows_total,

            COUNT(net_return_4h) AS rows_4h,
            AVG(net_return_4h) AS avg_net_4h,
            AVG(gross_return_4h) AS avg_gross_4h,
            AVG(CASE
                WHEN net_return_4h IS NULL THEN NULL
                WHEN net_return_4h > 0 THEN 1
                ELSE 0
            END) AS winrate_4h,

            COUNT(net_return_24h) AS rows_24h,
            AVG(net_return_24h) AS avg_net_24h,
            AVG(gross_return_24h) AS avg_gross_24h,
            AVG(CASE
                WHEN net_return_24h IS NULL THEN NULL
                WHEN net_return_24h > 0 THEN 1
                ELSE 0
            END) AS winrate_24h,

            MIN(net_return_4h) AS worst_net_4h,
            MAX(net_return_4h) AS best_net_4h

        FROM policy
        GROUP BY
            v13_state,
            policy_reason
        ORDER BY
            CASE v13_state
                WHEN 'PASS_V13_STRICT_SCORE' THEN 0
                ELSE 1
            END,
            rows_total DESC
        """
    )


def query_ranking_grid(min_rows: int) -> list[dict[str, Any]]:
    weak_symbols = ",".join(f"'{symbol}'" for symbol in WEAK_SET)

    return fetch_rows(
        f"""
        SELECT
            rotation_bucket,
            classification_code,
            sleeve_fit_code,

            COUNT(*) AS rows_total,

            COUNT(net_return_4h) AS rows_4h,
            AVG(net_return_4h) AS avg_net_4h,
            AVG(gross_return_4h) AS avg_gross_4h,
            AVG(CASE
                WHEN net_return_4h IS NULL THEN NULL
                WHEN net_return_4h > 0 THEN 1
                ELSE 0
            END) AS winrate_4h,

            COUNT(net_return_24h) AS rows_24h,
            AVG(net_return_24h) AS avg_net_24h,
            AVG(gross_return_24h) AS avg_gross_24h,
            AVG(CASE
                WHEN net_return_24h IS NULL THEN NULL
                WHEN net_return_24h > 0 THEN 1
                ELSE 0
            END) AS winrate_24h

        FROM {EVAL_TABLE}
        WHERE selection_state = 'WATCHLIST'
          AND priority_rank BETWEEN 4 AND 10
          AND btc_prior_24h >= -0.015
          AND btc_prior_24h <= 0.015
          AND symbol NOT IN ({weak_symbols})
        GROUP BY
            rotation_bucket,
            classification_code,
            sleeve_fit_code
        HAVING rows_4h >= %s
        ORDER BY
            avg_net_4h DESC,
            winrate_4h DESC
        """,
        [min_rows],
    )


def query_score_grid() -> list[dict[str, Any]]:
    weak_symbols = ",".join(f"'{symbol}'" for symbol in WEAK_SET)

    return fetch_rows(
        f"""
        WITH thresholds AS (
            SELECT 'score_lt_0.5000' AS bucket, NULL AS min_score, 0.50000000 AS max_score
            UNION ALL SELECT 'score_0.5000_0.5040', 0.50000000, 0.50400000
            UNION ALL SELECT 'score_0.5040_0.5100', 0.50400000, 0.51000000
            UNION ALL SELECT 'score_0.5100_0.5200', 0.51000000, 0.52000000
            UNION ALL SELECT 'score_ge_0.5200', 0.52000000, NULL
        )
        SELECT
            t.bucket,
            COUNT(e.bt_selection_v2_replay_id) AS rows_total,

            COUNT(e.net_return_4h) AS rows_4h,
            AVG(e.net_return_4h) AS avg_net_4h,
            AVG(e.gross_return_4h) AS avg_gross_4h,
            AVG(CASE
                WHEN e.net_return_4h IS NULL THEN NULL
                WHEN e.net_return_4h > 0 THEN 1
                ELSE 0
            END) AS winrate_4h,

            COUNT(e.net_return_24h) AS rows_24h,
            AVG(e.net_return_24h) AS avg_net_24h,
            AVG(e.gross_return_24h) AS avg_gross_24h,
            AVG(CASE
                WHEN e.net_return_24h IS NULL THEN NULL
                WHEN e.net_return_24h > 0 THEN 1
                ELSE 0
            END) AS winrate_24h

        FROM thresholds t
        JOIN {EVAL_TABLE} e
          ON (
                (t.min_score IS NULL OR e.selection_score >= t.min_score)
            AND (t.max_score IS NULL OR e.selection_score < t.max_score)
          )
        WHERE e.selection_state = 'WATCHLIST'
          AND e.priority_rank BETWEEN 4 AND 10
          AND e.btc_prior_24h >= -0.015
          AND e.btc_prior_24h <= 0.015
          AND e.symbol NOT IN ({weak_symbols})
          AND e.rotation_bucket = 'ROTATION_FOLLOWER'
          AND e.classification_code = 'CONTINUATION_CANDIDATE'
          AND e.sleeve_fit_code = 'SWING_STRUCTURAL'
        GROUP BY
            t.bucket
        ORDER BY
            MIN(COALESCE(t.min_score, -1))
        """
    )


def query_symbol_breakdown(min_rows: int) -> list[dict[str, Any]]:
    weak_symbols = ",".join(f"'{symbol}'" for symbol in WEAK_SET)

    return fetch_rows(
        f"""
        SELECT
            symbol,
            COUNT(*) AS rows_total,

            COUNT(net_return_4h) AS rows_4h,
            AVG(net_return_4h) AS avg_net_4h,
            AVG(gross_return_4h) AS avg_gross_4h,
            AVG(CASE
                WHEN net_return_4h IS NULL THEN NULL
                WHEN net_return_4h > 0 THEN 1
                ELSE 0
            END) AS winrate_4h,

            COUNT(net_return_24h) AS rows_24h,
            AVG(net_return_24h) AS avg_net_24h,
            AVG(gross_return_24h) AS avg_gross_24h,
            AVG(CASE
                WHEN net_return_24h IS NULL THEN NULL
                WHEN net_return_24h > 0 THEN 1
                ELSE 0
            END) AS winrate_24h,

            MIN(net_return_4h) AS worst_net_4h,
            MAX(net_return_4h) AS best_net_4h

        FROM {EVAL_TABLE}
        WHERE selection_state = 'WATCHLIST'
          AND priority_rank BETWEEN 4 AND 10
          AND btc_prior_24h >= -0.015
          AND btc_prior_24h <= 0.015
          AND symbol NOT IN ({weak_symbols})
        GROUP BY
            symbol
        HAVING rows_4h >= %s
        ORDER BY
            avg_net_4h DESC,
            rows_4h DESC
        """,
        [min_rows],
    )


def main() -> int:
    args = parse_args()

    venue = str(args.venue)
    engine_name = str(args.engine_name)
    engine_version = str(args.engine_version)
    fee_bps_per_side = _as_decimal(args.fee_bps_per_side)
    min_rows = int(args.min_rows)

    if args.refresh_eval_table:
        print(
            f"[INFO] rebuilding {BT_DB}.{EVAL_TABLE} "
            f"venue={venue} engine={engine_name}:{engine_version} "
            f"fee_bps_per_side={fee_bps_per_side}"
        )
        rebuild_eval_table(
            venue=venue,
            engine_name=engine_name,
            engine_version=engine_version,
            fee_bps_per_side=fee_bps_per_side,
        )

    results = {
        "coverage": query_coverage(),
        "policy_buckets": query_policy_buckets(),
        "ranking_grid": query_ranking_grid(min_rows),
        "score_grid": query_score_grid(),
        "symbol_breakdown": query_symbol_breakdown(min_rows),
    }

    if args.output == "json":
        print(json.dumps(results, indent=2, ensure_ascii=False, default=_json_default))
        return 0

    _print_table("COVERAGE", results["coverage"])
    _print_table("POLICY BUCKETS", results["policy_buckets"])
    _print_table("RANKING GRID", results["ranking_grid"])
    _print_table("SCORE GRID STRICT FOLLOWER", results["score_grid"])
    _print_table("SYMBOL BREAKDOWN BASE V1.1", results["symbol_breakdown"])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
