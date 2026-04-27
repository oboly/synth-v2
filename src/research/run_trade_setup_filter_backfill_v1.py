from __future__ import annotations

"""
Synth v2 - Trade Setup Filter V1 research backfill.

LAYER:
research/backtest replay

BOUNDARY:
Allowed:
- replay historical selection_state snapshots
- recompute market-only trade_setup_filter_v1 decisions
- write replay observations into synth_bt

Forbidden:
- writing operational synth.trade_setup_filter_observation
- account state
- balances
- positions
- open orders
- execution plans
- broker/order actions

IMPORTANT:
This runner intentionally writes to synth_bt.bt_trade_setup_filter_observation.
Operational live/latest observations belong in synth.trade_setup_filter_observation.
"""

import argparse
import hashlib
import json
from collections import Counter
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from typing import Any

from src.common.db import get_connection
from src.trade_setup_filter.engine_v1 import evaluate_trade_setup
from src.trade_setup_filter.models import TradeSetupCandidate, TradeSetupDecision


DEFAULT_VENUE = "bitvavo"
DEFAULT_ENGINE_NAME = "selection_engine_v2"
DEFAULT_ENGINE_VERSION = "2.0"
FILTER_NAME = "trade_setup_filter_v1"
FILTER_VERSION = "1.0"
RESULT_DB = "synth_bt"
RESULT_TABLE = "bt_trade_setup_filter_observation"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Research backfill for market-only trade_setup_filter_v1."
    )
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--engine-name", default=DEFAULT_ENGINE_NAME)
    parser.add_argument("--engine-version", default=DEFAULT_ENGINE_VERSION)
    parser.add_argument("--from-ts", required=True)
    parser.add_argument("--to-ts", required=True)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--selection-state", default="WATCHLIST")
    parser.add_argument("--rank-min", type=int, default=4)
    parser.add_argument("--rank-max", type=int, default=10)
    parser.add_argument("--btc-prior-min", default="-0.015")
    parser.add_argument("--btc-prior-max", default="0.015")
    parser.add_argument(
        "--asset-suitability-mode",
        choices=("off", "candidate_weak_set"),
        default="candidate_weak_set",
    )
    parser.add_argument("--write-db", action="store_true")
    parser.add_argument("--output", choices=("summary", "json"), default="summary")
    return parser.parse_args()


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("T", " "))


def _as_decimal(value: str) -> Decimal:
    return Decimal(str(value))


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return str(value)


def _build_filter_config(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "filter_name": FILTER_NAME,
        "filter_version": FILTER_VERSION,
        "required_selection_state": str(args.selection_state),
        "rank_min": int(args.rank_min),
        "rank_max": int(args.rank_max),
        "btc_prior_min": str(args.btc_prior_min),
        "btc_prior_max": str(args.btc_prior_max),
        "asset_suitability_mode": str(args.asset_suitability_mode),
    }


def _config_hash(config: dict[str, Any]) -> str:
    payload = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def ensure_result_table() -> None:
    sql = f"""
    CREATE TABLE IF NOT EXISTS {RESULT_DB}.{RESULT_TABLE} (
        bt_trade_setup_filter_observation_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

        asset_id INT NOT NULL,
        symbol VARCHAR(32) NOT NULL,
        venue VARCHAR(32) NOT NULL,

        asof_ts_utc DATETIME(6) NOT NULL,
        context_ts_utc DATETIME(6) DEFAULT NULL,

        engine_name VARCHAR(64) NOT NULL,
        engine_version VARCHAR(32) NOT NULL,

        filter_name VARCHAR(64) NOT NULL,
        filter_version VARCHAR(32) NOT NULL,
        asset_suitability_mode VARCHAR(64) NOT NULL,
        filter_config_hash CHAR(64) NOT NULL,
        filter_config_json LONGTEXT NOT NULL,

        selection_state VARCHAR(32) NOT NULL,
        selection_bias VARCHAR(32) DEFAULT NULL,
        selection_score DECIMAL(18,8) DEFAULT NULL,
        priority_rank INT DEFAULT NULL,
        allowed_sleeves VARCHAR(255) DEFAULT NULL,

        btc_prior_24h DECIMAL(18,8) DEFAULT NULL,

        setup_filter_state VARCHAR(32) NOT NULL,
        setup_filter_reason VARCHAR(128) NOT NULL,
        target_horizon VARCHAR(32) NOT NULL,
        notes VARCHAR(512) DEFAULT NULL,

        backfill_run_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
        created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
        updated_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
            ON UPDATE CURRENT_TIMESTAMP(6),

        PRIMARY KEY (bt_trade_setup_filter_observation_id),

        UNIQUE KEY uq_bt_trade_setup_filter_observation (
            asset_id,
            venue,
            asof_ts_utc,
            filter_name,
            filter_version,
            asset_suitability_mode,
            filter_config_hash
        ),

        KEY ix_bt_trade_setup_filter_context (
            context_ts_utc
        ),

        KEY ix_bt_trade_setup_filter_state (
            setup_filter_state,
            setup_filter_reason
        ),

        KEY ix_bt_trade_setup_filter_symbol_context (
            symbol,
            context_ts_utc
        ),

        KEY ix_bt_trade_setup_filter_config (
            filter_name,
            filter_version,
            asset_suitability_mode,
            filter_config_hash
        )
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
    finally:
        conn.close()


def fetch_historical_candidates(
    *,
    venue: str,
    engine_name: str,
    engine_version: str,
    from_ts: datetime,
    to_ts: datetime,
    limit: int | None,
) -> list[TradeSetupCandidate]:
    sql = """
    WITH snapshots AS (
        SELECT
            ss.asof_ts_utc,
            MAX(ss.advice_ts_1h_utc) AS context_ts_utc
        FROM synth.selection_state ss
        WHERE ss.venue = %s
          AND ss.engine_name = %s
          AND ss.engine_version = %s
          AND ss.asof_ts_utc >= %s
          AND ss.asof_ts_utc < %s
        GROUP BY
            ss.asof_ts_utc
    ),
    btc AS (
        SELECT asset_id
        FROM synth.asset
        WHERE symbol = 'BTC'
        LIMIT 1
    )
    SELECT
        ss.asset_id,
        a.symbol,
        ss.venue,
        ss.asof_ts_utc,
        s.context_ts_utc,
        ss.selection_state,
        ss.selection_bias,
        ss.selection_score,
        ss.priority_rank,
        NULL AS allowed_sleeves,
        ss.summary_text,

        CASE
            WHEN btc_now.close_price IS NULL
              OR btc_prev24.close_price IS NULL
              OR btc_prev24.close_price = 0
            THEN NULL
            ELSE ((btc_now.close_price - btc_prev24.close_price) / btc_prev24.close_price)
        END AS btc_prior_24h

    FROM synth.selection_state ss
    INNER JOIN snapshots s
        ON s.asof_ts_utc = ss.asof_ts_utc
    INNER JOIN synth.asset a
        ON a.asset_id = ss.asset_id
    INNER JOIN btc

    LEFT JOIN synth.obs_market_candle btc_now
        ON btc_now.asset_id = btc.asset_id
       AND btc_now.venue = ss.venue
       AND btc_now.interval_code = '1h'
       AND btc_now.close_ts_utc = s.context_ts_utc

    LEFT JOIN synth.obs_market_candle btc_prev24
        ON btc_prev24.asset_id = btc.asset_id
       AND btc_prev24.venue = ss.venue
       AND btc_prev24.interval_code = '1h'
       AND btc_prev24.close_ts_utc = DATE_SUB(s.context_ts_utc, INTERVAL 24 HOUR)

    WHERE ss.venue = %s
      AND ss.engine_name = %s
      AND ss.engine_version = %s
      AND ss.asof_ts_utc >= %s
      AND ss.asof_ts_utc < %s

    ORDER BY
        ss.asof_ts_utc ASC,
        ss.priority_rank IS NULL ASC,
        ss.priority_rank ASC,
        ss.selection_score DESC,
        a.symbol ASC
    """

    params: list[Any] = [
        venue,
        engine_name,
        engine_version,
        from_ts,
        to_ts,
        venue,
        engine_name,
        engine_version,
        from_ts,
        to_ts,
    ]

    if limit is not None:
        sql += "\nLIMIT %s"
        params.append(int(limit))

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    finally:
        conn.close()

    candidates: list[TradeSetupCandidate] = []

    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("Expected dict rows from database cursor")

        candidates.append(
            TradeSetupCandidate(
                asset_id=int(row["asset_id"]),
                symbol=str(row["symbol"]),
                venue=str(row["venue"]),
                asof_ts_utc=row["asof_ts_utc"],
                context_ts_utc=row["context_ts_utc"],
                selection_state=str(row["selection_state"]),
                selection_bias=row["selection_bias"],
                selection_score=_to_decimal(row["selection_score"]),
                priority_rank=_to_int(row["priority_rank"]),
                allowed_sleeves=row["allowed_sleeves"],
                btc_prior_24h=_to_decimal(row["btc_prior_24h"]),
                summary_text=row["summary_text"],
            )
        )

    return candidates


def write_research_observations(
    decisions: list[TradeSetupDecision],
    *,
    engine_name: str,
    engine_version: str,
    filter_config: dict[str, Any],
    filter_config_hash: str,
) -> int:
    if not decisions:
        return 0

    ensure_result_table()

    filter_config_json = json.dumps(
        filter_config,
        sort_keys=True,
        ensure_ascii=False,
        default=_json_default,
    )

    rows: list[dict[str, Any]] = []
    for decision in decisions:
        row = asdict(decision)
        row["engine_name"] = engine_name
        row["engine_version"] = engine_version
        row["filter_name"] = FILTER_NAME
        row["filter_version"] = FILTER_VERSION
        row["asset_suitability_mode"] = str(filter_config["asset_suitability_mode"])
        row["filter_config_hash"] = filter_config_hash
        row["filter_config_json"] = filter_config_json
        rows.append(row)

    sql = f"""
    INSERT INTO {RESULT_DB}.{RESULT_TABLE} (
        asset_id,
        symbol,
        venue,
        asof_ts_utc,
        context_ts_utc,

        engine_name,
        engine_version,

        filter_name,
        filter_version,
        asset_suitability_mode,
        filter_config_hash,
        filter_config_json,

        selection_state,
        selection_bias,
        selection_score,
        priority_rank,
        allowed_sleeves,

        btc_prior_24h,

        setup_filter_state,
        setup_filter_reason,
        target_horizon,
        notes
    ) VALUES (
        %(asset_id)s,
        %(symbol)s,
        %(venue)s,
        %(asof_ts_utc)s,
        %(context_ts_utc)s,

        %(engine_name)s,
        %(engine_version)s,

        %(filter_name)s,
        %(filter_version)s,
        %(asset_suitability_mode)s,
        %(filter_config_hash)s,
        %(filter_config_json)s,

        %(selection_state)s,
        %(selection_bias)s,
        %(selection_score)s,
        %(priority_rank)s,
        %(allowed_sleeves)s,

        %(btc_prior_24h)s,

        %(setup_filter_state)s,
        %(setup_filter_reason)s,
        %(target_horizon)s,
        %(notes)s
    )
    ON DUPLICATE KEY UPDATE
        context_ts_utc = VALUES(context_ts_utc),
        engine_name = VALUES(engine_name),
        engine_version = VALUES(engine_version),
        filter_config_json = VALUES(filter_config_json),
        selection_state = VALUES(selection_state),
        selection_bias = VALUES(selection_bias),
        selection_score = VALUES(selection_score),
        priority_rank = VALUES(priority_rank),
        allowed_sleeves = VALUES(allowed_sleeves),
        btc_prior_24h = VALUES(btc_prior_24h),
        setup_filter_state = VALUES(setup_filter_state),
        setup_filter_reason = VALUES(setup_filter_reason),
        target_horizon = VALUES(target_horizon),
        notes = VALUES(notes),
        backfill_run_ts_utc = UTC_TIMESTAMP(6),
        updated_ts_utc = UTC_TIMESTAMP(6)
    """

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def _print_summary(
    *,
    decisions: list[TradeSetupDecision],
    from_ts: datetime,
    to_ts: datetime,
    filter_config_hash: str,
    written: int,
    write_db: bool,
) -> None:
    state_counts = Counter(decision.setup_filter_state for decision in decisions)
    reason_counts = Counter(
        (decision.setup_filter_state, decision.setup_filter_reason)
        for decision in decisions
    )
    snapshots = {decision.asof_ts_utc for decision in decisions}
    context_snapshots = {decision.context_ts_utc for decision in decisions if decision.context_ts_utc is not None}

    print("trade_setup_filter_v1 research backfill")
    print(f"window=[{from_ts},{to_ts})")
    print(f"rows_total={len(decisions)}")
    print(f"snapshots={len(snapshots)}")
    print(f"context_snapshots={len(context_snapshots)}")
    print(f"pass_rows={state_counts.get('PASS', 0)}")
    print(f"fail_rows={state_counts.get('FAIL', 0)}")
    print(f"filter_config_hash={filter_config_hash}")
    print(f"write_db={write_db}")
    print(f"rows_written={written}")

    print()
    print("state | reason | rows")
    print("------+--------+-----")
    for (state, reason), count in sorted(
        reason_counts.items(),
        key=lambda item: (item[0][0], -item[1], item[0][1]),
    ):
        print(f"{state} | {reason} | {count}")


def main() -> int:
    args = parse_args()

    from_ts = _parse_ts(str(args.from_ts))
    to_ts = _parse_ts(str(args.to_ts))

    filter_config = _build_filter_config(args)
    filter_config_hash = _config_hash(filter_config)

    candidates = fetch_historical_candidates(
        venue=str(args.venue),
        engine_name=str(args.engine_name),
        engine_version=str(args.engine_version),
        from_ts=from_ts,
        to_ts=to_ts,
        limit=args.limit,
    )

    decisions = [
        evaluate_trade_setup(
            candidate,
            required_selection_state=str(args.selection_state),
            rank_min=int(args.rank_min),
            rank_max=int(args.rank_max),
            btc_prior_min=_as_decimal(args.btc_prior_min),
            btc_prior_max=_as_decimal(args.btc_prior_max),
            asset_suitability_mode=str(args.asset_suitability_mode),
        )
        for candidate in candidates
    ]

    written = 0
    if args.write_db:
        written = write_research_observations(
            decisions,
            engine_name=str(args.engine_name),
            engine_version=str(args.engine_version),
            filter_config=filter_config,
            filter_config_hash=filter_config_hash,
        )

    if args.output == "json":
        print(json.dumps([asdict(row) for row in decisions], indent=2, ensure_ascii=False, default=_json_default))
    else:
        _print_summary(
            decisions=decisions,
            from_ts=from_ts,
            to_ts=to_ts,
            filter_config_hash=filter_config_hash,
            written=written,
            write_db=bool(args.write_db),
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
