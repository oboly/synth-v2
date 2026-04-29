from __future__ import annotations

# Synth v2.5 - Replay Policy Eval Horizon V2.
#
# LAYER:
# research / backtest evaluation
#
# BOUNDARY:
# Allowed:
# - read synth_bt.bt_selection_v2_replay
# - read synth.ranking_state
# - read synth.obs_market_candle
# - build a materialized research eval table in synth_bt
#
# Forbidden:
# - account balances
# - positions
# - open orders
# - decision_gate writes
# - execution_intent writes
# - execution_plan writes
# - broker/order actions
#
# Purpose:
# Build a multi-horizon evaluation table for strategy battle arena runs.
# V1 only had 4h and 24h. V2 adds 48h, 72h, and 168h for swing evaluation.

import argparse
import json
from decimal import Decimal
from typing import Any

from src.common.db import get_connection


SOURCE_DB = "synth"
BT_DB = "synth_bt"
EVAL_TABLE = "bt_selection_v2_replay_eval_horizon_v2"

DEFAULT_VENUE = "bitvavo"
DEFAULT_ENGINE_NAME = "selection_engine_v2"
DEFAULT_ENGINE_VERSION = "2.0"
DEFAULT_FEE_BPS_PER_SIDE = Decimal("25")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build multi-horizon replay policy eval table for Synth v2.5."
    )
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--engine-name", default=DEFAULT_ENGINE_NAME)
    parser.add_argument("--engine-version", default=DEFAULT_ENGINE_VERSION)
    parser.add_argument("--fee-bps-per-side", default=str(DEFAULT_FEE_BPS_PER_SIDE))
    parser.add_argument("--refresh-eval-table", action="store_true")
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args()


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def print_rows(title: str, rows: list[dict[str, Any]]) -> None:
    print()
    print(f"=== {title} ===")
    if not rows:
        print("(no rows)")
        return

    headers = list(rows[0].keys())
    widths = {header: len(header) for header in headers}
    for row in rows:
        for header in headers:
            widths[header] = max(widths[header], len(str(row.get(header, ""))))

    print(" | ".join(header.ljust(widths[header]) for header in headers))
    print("-+-".join("-" * widths[header] for header in headers))
    for row in rows:
        print(" | ".join(str(row.get(header, "")).ljust(widths[header]) for header in headers))


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
            WHEN e.close_price IS NULL OR e.close_price = 0 OR f4.close_price IS NULL
            THEN NULL
            ELSE (f4.close_price - e.close_price) / e.close_price
        END AS gross_return_4h,
        CASE
            WHEN e.close_price IS NULL OR e.close_price = 0 OR f4.close_price IS NULL
            THEN NULL
            ELSE ((f4.close_price - e.close_price) / e.close_price) - {roundtrip_fee}
        END AS net_return_4h,

        f24.close_price AS forward_close_price_24h,
        CASE
            WHEN e.close_price IS NULL OR e.close_price = 0 OR f24.close_price IS NULL
            THEN NULL
            ELSE (f24.close_price - e.close_price) / e.close_price
        END AS gross_return_24h,
        CASE
            WHEN e.close_price IS NULL OR e.close_price = 0 OR f24.close_price IS NULL
            THEN NULL
            ELSE ((f24.close_price - e.close_price) / e.close_price) - {roundtrip_fee}
        END AS net_return_24h,

        f48.close_price AS forward_close_price_48h,
        CASE
            WHEN e.close_price IS NULL OR e.close_price = 0 OR f48.close_price IS NULL
            THEN NULL
            ELSE (f48.close_price - e.close_price) / e.close_price
        END AS gross_return_48h,
        CASE
            WHEN e.close_price IS NULL OR e.close_price = 0 OR f48.close_price IS NULL
            THEN NULL
            ELSE ((f48.close_price - e.close_price) / e.close_price) - {roundtrip_fee}
        END AS net_return_48h,

        f72.close_price AS forward_close_price_72h,
        CASE
            WHEN e.close_price IS NULL OR e.close_price = 0 OR f72.close_price IS NULL
            THEN NULL
            ELSE (f72.close_price - e.close_price) / e.close_price
        END AS gross_return_72h,
        CASE
            WHEN e.close_price IS NULL OR e.close_price = 0 OR f72.close_price IS NULL
            THEN NULL
            ELSE ((f72.close_price - e.close_price) / e.close_price) - {roundtrip_fee}
        END AS net_return_72h,

        f168.close_price AS forward_close_price_168h,
        CASE
            WHEN e.close_price IS NULL OR e.close_price = 0 OR f168.close_price IS NULL
            THEN NULL
            ELSE (f168.close_price - e.close_price) / e.close_price
        END AS gross_return_168h,
        CASE
            WHEN e.close_price IS NULL OR e.close_price = 0 OR f168.close_price IS NULL
            THEN NULL
            ELSE ((f168.close_price - e.close_price) / e.close_price) - {roundtrip_fee}
        END AS net_return_168h,

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

    LEFT JOIN {SOURCE_DB}.obs_market_candle f48
      ON f48.asset_id = r.asset_id
     AND f48.venue = '{venue}'
     AND f48.interval_code = '1h'
     AND f48.close_ts_utc = DATE_ADD(r.replay_asof_ts_utc, INTERVAL 48 HOUR)

    LEFT JOIN {SOURCE_DB}.obs_market_candle f72
      ON f72.asset_id = r.asset_id
     AND f72.venue = '{venue}'
     AND f72.interval_code = '1h'
     AND f72.close_ts_utc = DATE_ADD(r.replay_asof_ts_utc, INTERVAL 72 HOUR)

    LEFT JOIN {SOURCE_DB}.obs_market_candle f168
      ON f168.asset_id = r.asset_id
     AND f168.venue = '{venue}'
     AND f168.interval_code = '1h'
     AND f168.close_ts_utc = DATE_ADD(r.replay_asof_ts_utc, INTERVAL 168 HOUR)

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
        ADD INDEX ix_eval_horizon_v2_state_rank (
            selection_state,
            priority_rank,
            btc_prior_24h,
            selection_score
        ),
        ADD INDEX ix_eval_horizon_v2_context (
            rotation_bucket,
            classification_code,
            sleeve_fit_code
        ),
        ADD INDEX ix_eval_horizon_v2_symbol_ts (
            symbol,
            replay_asof_ts_utc
        ),
        ADD INDEX ix_eval_horizon_v2_returns (
            net_return_24h,
            net_return_72h,
            net_return_168h
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


def fetch_summary() -> dict[str, Any]:
    conn = get_connection(database=BT_DB)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    COUNT(*) AS rows_total,
                    COUNT(net_return_4h) AS rows_4h,
                    AVG(net_return_4h) AS avg_net_4h,
                    AVG(net_return_4h > 0) AS winrate_4h,
                    COUNT(net_return_24h) AS rows_24h,
                    AVG(net_return_24h) AS avg_net_24h,
                    AVG(net_return_24h > 0) AS winrate_24h,
                    COUNT(net_return_48h) AS rows_48h,
                    AVG(net_return_48h) AS avg_net_48h,
                    AVG(net_return_48h > 0) AS winrate_48h,
                    COUNT(net_return_72h) AS rows_72h,
                    AVG(net_return_72h) AS avg_net_72h,
                    AVG(net_return_72h > 0) AS winrate_72h,
                    COUNT(net_return_168h) AS rows_168h,
                    AVG(net_return_168h) AS avg_net_168h,
                    AVG(net_return_168h > 0) AS winrate_168h
                FROM {EVAL_TABLE}
                """
            )
            summary = cur.fetchone() or {}

            cur.execute(
                f"""
                SELECT
                    selection_state,
                    rotation_bucket,
                    classification_code,
                    sleeve_fit_code,
                    COUNT(*) AS rows_total,
                    COUNT(net_return_72h) AS rows_72h,
                    AVG(net_return_72h) AS avg_net_72h,
                    AVG(net_return_72h > 0) AS winrate_72h,
                    COUNT(net_return_168h) AS rows_168h,
                    AVG(net_return_168h) AS avg_net_168h,
                    AVG(net_return_168h > 0) AS winrate_168h
                FROM {EVAL_TABLE}
                GROUP BY
                    selection_state,
                    rotation_bucket,
                    classification_code,
                    sleeve_fit_code
                ORDER BY rows_total DESC
                LIMIT 30
                """
            )
            context_rows = cur.fetchall() or []
    finally:
        conn.close()

    return {
        "table": EVAL_TABLE,
        "summary": summary,
        "context_rows": context_rows,
    }


def main() -> int:
    args = parse_args()

    if args.refresh_eval_table:
        rebuild_eval_table(
            venue=args.venue,
            engine_name=args.engine_name,
            engine_version=args.engine_version,
            fee_bps_per_side=Decimal(str(args.fee_bps_per_side)),
        )

    payload = fetch_summary()

    if args.output == "json":
        print(json.dumps(payload, default=json_default, indent=2, sort_keys=True))
        return 0

    print(f"Replay policy eval horizon table: {payload['table']}")
    print_rows("summary", [payload["summary"]])
    print_rows("context rows", payload["context_rows"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
