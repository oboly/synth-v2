from __future__ import annotations

"""
ENGINE: run_backtest_selection_eval_v1
MODE: historical

INPUT:
- selection_state
- obs_market_candle
- asset
- synth_bt.config_set
- synth_bt.config_param

OUTPUT:
- synth_bt.bt_run
- synth_bt.bt_selection_eval

NOTES:
- evaluates persisted pipeline output only
- does NOT invent a new strategy
- uses advice_ts_1h_utc as canonical entry timestamp
- next_return_* is NET after round-trip fees
- gross_return_* is stored separately
- prints overall summary plus per-selection_state breakdown
"""

import argparse
import json
from collections import defaultdict
from decimal import Decimal
from typing import Any

from src.common.db import get_connection
from src.config_registry.loader import load_config_set


SOURCE_DB = "synth"
BT_DB = "synth_bt"
DEFAULT_ENGINE_NAME = "selection_engine_v2"
DEFAULT_ENGINE_VERSION = "2.0"
DEFAULT_SELECTION_STATES = ("PREPARE", "BUY_READY")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate persisted selection_state forward returns.")
    parser.add_argument("--config-scope", default="BACKTEST")
    parser.add_argument("--config-name", required=True)
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--from-ts", required=True)
    parser.add_argument("--to-ts", required=True)
    parser.add_argument("--engine-name", default=DEFAULT_ENGINE_NAME)
    parser.add_argument("--engine-version", default=DEFAULT_ENGINE_VERSION)
    parser.add_argument("--selection-states", nargs="*", default=list(DEFAULT_SELECTION_STATES))
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _require_int(cfg: dict[str, dict[str, Any]], component: str, parameter_name: str) -> int:
    return int(cfg[component][parameter_name])


def _require_decimal_with_default(
    cfg: dict[str, dict[str, Any]],
    component: str,
    parameter_name: str,
    default: str,
) -> Decimal:
    component_map = cfg.get(component, {})
    if parameter_name not in component_map:
        return Decimal(default)
    return _to_decimal(component_map[parameter_name])


def _snapshot_json(loaded_config) -> str:
    return json.dumps(loaded_config.snapshot_json_ready, ensure_ascii=False)


def ensure_bt_tables() -> None:
    sql_statements = [
        """
        CREATE TABLE IF NOT EXISTS bt_run (
            bt_run_id BIGINT AUTO_INCREMENT PRIMARY KEY,
            run_name VARCHAR(100),
            strategy_name VARCHAR(100),
            created_ts_utc DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6),
            notes TEXT,
            config_set_id BIGINT NULL,
            config_snapshot_json LONGTEXT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
        """
        CREATE TABLE IF NOT EXISTS bt_selection_eval (
            bt_selection_eval_id BIGINT AUTO_INCREMENT PRIMARY KEY,
            bt_run_id BIGINT NOT NULL,
            asset_id INT NOT NULL,
            symbol VARCHAR(32) NOT NULL,
            venue VARCHAR(32) NOT NULL,
            entry_ts_utc DATETIME(6) NOT NULL,
            selection_state VARCHAR(64) DEFAULT NULL,
            selection_bias VARCHAR(32) DEFAULT NULL,
            selection_score DECIMAL(18,8) DEFAULT NULL,
            priority_rank INT DEFAULT NULL,
            fee_bps_per_side DECIMAL(18,8) DEFAULT NULL,
            entry_close_price DECIMAL(28,10) DEFAULT NULL,
            next_ts_1h_utc DATETIME(6) DEFAULT NULL,
            next_close_price_1h DECIMAL(28,10) DEFAULT NULL,
            gross_return_1h DECIMAL(18,8) DEFAULT NULL,
            next_return_1h DECIMAL(18,8) DEFAULT NULL,
            next_ts_4h_utc DATETIME(6) DEFAULT NULL,
            next_close_price_4h DECIMAL(28,10) DEFAULT NULL,
            gross_return_4h DECIMAL(18,8) DEFAULT NULL,
            next_return_4h DECIMAL(18,8) DEFAULT NULL,
            next_ts_24h_utc DATETIME(6) DEFAULT NULL,
            next_close_price_24h DECIMAL(28,10) DEFAULT NULL,
            gross_return_24h DECIMAL(18,8) DEFAULT NULL,
            next_return_24h DECIMAL(18,8) DEFAULT NULL,
            created_ts_utc DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
            UNIQUE KEY uq_bt_selection_eval (bt_run_id, asset_id, venue, entry_ts_utc),
            KEY ix_bt_selection_eval_run (bt_run_id),
            KEY ix_bt_selection_eval_asset_ts (asset_id, entry_ts_utc)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
        """
        ALTER TABLE bt_selection_eval
            ADD COLUMN IF NOT EXISTS fee_bps_per_side DECIMAL(18,8) DEFAULT NULL
        """,
        """
        ALTER TABLE bt_selection_eval
            ADD COLUMN IF NOT EXISTS gross_return_1h DECIMAL(18,8) DEFAULT NULL
        """,
        """
        ALTER TABLE bt_selection_eval
            ADD COLUMN IF NOT EXISTS gross_return_4h DECIMAL(18,8) DEFAULT NULL
        """,
        """
        ALTER TABLE bt_selection_eval
            ADD COLUMN IF NOT EXISTS gross_return_24h DECIMAL(18,8) DEFAULT NULL
        """,
    ]

    conn = get_connection(database=BT_DB)
    try:
        with conn.cursor() as cur:
            for sql in sql_statements:
                cur.execute(sql)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def insert_bt_run(
    *,
    config_set_id: int,
    config_snapshot_json: str,
    venue: str,
    from_ts: str,
    to_ts: str,
    engine_name: str,
    engine_version: str,
    selection_states: list[str],
    fee_bps_per_side: Decimal,
    dry_run: bool,
) -> int:
    notes = (
        f"Selection evaluation only; venue={venue}; "
        f"window=[{from_ts},{to_ts}); "
        f"engine={engine_name}:{engine_version}; "
        f"states={','.join(selection_states)}; "
        f"fee_bps_per_side={fee_bps_per_side}"
    )

    conn = get_connection(database=BT_DB)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO bt_run (
                    run_name,
                    strategy_name,
                    notes,
                    config_set_id,
                    config_snapshot_json
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                [
                    "selection_eval_v1",
                    "SELECTION_STATE_FORWARD_EVAL",
                    notes,
                    config_set_id,
                    config_snapshot_json,
                ],
            )
            bt_run_id = int(cur.lastrowid)
        if dry_run:
            conn.rollback()
        else:
            conn.commit()
        return bt_run_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def fetch_eval_rows(
    *,
    venue: str,
    from_ts: str,
    to_ts: str,
    engine_name: str,
    engine_version: str,
    selection_states: list[str],
    fee_bps_per_side: Decimal,
) -> list[dict[str, Any]]:
    state_placeholders = ",".join(["%s"] * len(selection_states))
    round_trip_fee = (fee_bps_per_side * Decimal("2")) / Decimal("10000")

    sql = f"""
    WITH base AS (
        SELECT
            s.asset_id,
            a.symbol,
            s.venue,
            s.advice_ts_1h_utc AS entry_ts_utc,
            s.selection_state,
            s.selection_bias,
            s.selection_score,
            s.priority_rank
        FROM selection_state s
        JOIN asset a
          ON a.asset_id = s.asset_id
        WHERE s.venue = %s
          AND s.engine_name = %s
          AND s.engine_version = %s
          AND s.advice_ts_1h_utc IS NOT NULL
          AND s.advice_ts_1h_utc >= %s
          AND s.advice_ts_1h_utc < %s
          AND s.selection_state IN ({state_placeholders})
    )
    SELECT
        b.asset_id,
        b.symbol,
        b.venue,
        b.entry_ts_utc,
        b.selection_state,
        b.selection_bias,
        b.selection_score,
        b.priority_rank,
        %s AS fee_bps_per_side,

        e1.close_price AS entry_close_price,

        n1.open_ts_utc AS next_ts_1h_utc,
        n1.close_price AS next_close_price_1h,
        CASE
            WHEN e1.close_price IS NULL OR e1.close_price = 0 OR n1.close_price IS NULL THEN NULL
            ELSE (n1.close_price - e1.close_price) / e1.close_price
        END AS gross_return_1h,
        CASE
            WHEN e1.close_price IS NULL OR e1.close_price = 0 OR n1.close_price IS NULL THEN NULL
            ELSE ((n1.close_price - e1.close_price) / e1.close_price) - %s
        END AS next_return_1h,

        n4.open_ts_utc AS next_ts_4h_utc,
        n4.close_price AS next_close_price_4h,
        CASE
            WHEN e1.close_price IS NULL OR e1.close_price = 0 OR n4.close_price IS NULL THEN NULL
            ELSE (n4.close_price - e1.close_price) / e1.close_price
        END AS gross_return_4h,
        CASE
            WHEN e1.close_price IS NULL OR e1.close_price = 0 OR n4.close_price IS NULL THEN NULL
            ELSE ((n4.close_price - e1.close_price) / e1.close_price) - %s
        END AS next_return_4h,

        n24.open_ts_utc AS next_ts_24h_utc,
        n24.close_price AS next_close_price_24h,
        CASE
            WHEN e1.close_price IS NULL OR e1.close_price = 0 OR n24.close_price IS NULL THEN NULL
            ELSE (n24.close_price - e1.close_price) / e1.close_price
        END AS gross_return_24h,
        CASE
            WHEN e1.close_price IS NULL OR e1.close_price = 0 OR n24.close_price IS NULL THEN NULL
            ELSE ((n24.close_price - e1.close_price) / e1.close_price) - %s
        END AS next_return_24h

    FROM base b
    LEFT JOIN obs_market_candle e1
      ON e1.asset_id = b.asset_id
     AND e1.venue = b.venue
     AND e1.interval_code = '1h'
     AND e1.open_ts_utc = b.entry_ts_utc
    LEFT JOIN obs_market_candle n1
      ON n1.asset_id = b.asset_id
     AND n1.venue = b.venue
     AND n1.interval_code = '1h'
     AND n1.open_ts_utc = DATE_ADD(b.entry_ts_utc, INTERVAL 1 HOUR)
    LEFT JOIN obs_market_candle n4
      ON n4.asset_id = b.asset_id
     AND n4.venue = b.venue
     AND n4.interval_code = '1h'
     AND n4.open_ts_utc = DATE_ADD(b.entry_ts_utc, INTERVAL 4 HOUR)
    LEFT JOIN obs_market_candle n24
      ON n24.asset_id = b.asset_id
     AND n24.venue = b.venue
     AND n24.interval_code = '1h'
     AND n24.open_ts_utc = DATE_ADD(b.entry_ts_utc, INTERVAL 24 HOUR)
    ORDER BY b.entry_ts_utc ASC, b.asset_id ASC
    """

    params: list[Any] = (
        [venue, engine_name, engine_version, from_ts, to_ts]
        + selection_states
        + [fee_bps_per_side, round_trip_fee, round_trip_fee, round_trip_fee]
    )

    conn = get_connection(database=SOURCE_DB)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall() or []
    finally:
        conn.close()

    return rows


def write_eval_rows(
    *,
    bt_run_id: int,
    rows: list[dict[str, Any]],
    dry_run: bool,
) -> int:
    if not rows:
        return 0

    conn = get_connection(database=BT_DB)
    try:
        with conn.cursor() as cur:
            for row in rows:
                cur.execute(
                    """
                    INSERT INTO bt_selection_eval (
                        bt_run_id,
                        asset_id,
                        symbol,
                        venue,
                        entry_ts_utc,
                        selection_state,
                        selection_bias,
                        selection_score,
                        priority_rank,
                        fee_bps_per_side,
                        entry_close_price,
                        next_ts_1h_utc,
                        next_close_price_1h,
                        gross_return_1h,
                        next_return_1h,
                        next_ts_4h_utc,
                        next_close_price_4h,
                        gross_return_4h,
                        next_return_4h,
                        next_ts_24h_utc,
                        next_close_price_24h,
                        gross_return_24h,
                        next_return_24h
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON DUPLICATE KEY UPDATE
                        selection_state = VALUES(selection_state),
                        selection_bias = VALUES(selection_bias),
                        selection_score = VALUES(selection_score),
                        priority_rank = VALUES(priority_rank),
                        fee_bps_per_side = VALUES(fee_bps_per_side),
                        entry_close_price = VALUES(entry_close_price),
                        next_ts_1h_utc = VALUES(next_ts_1h_utc),
                        next_close_price_1h = VALUES(next_close_price_1h),
                        gross_return_1h = VALUES(gross_return_1h),
                        next_return_1h = VALUES(next_return_1h),
                        next_ts_4h_utc = VALUES(next_ts_4h_utc),
                        next_close_price_4h = VALUES(next_close_price_4h),
                        gross_return_4h = VALUES(gross_return_4h),
                        next_return_4h = VALUES(next_return_4h),
                        next_ts_24h_utc = VALUES(next_ts_24h_utc),
                        next_close_price_24h = VALUES(next_close_price_24h),
                        gross_return_24h = VALUES(gross_return_24h),
                        next_return_24h = VALUES(next_return_24h)
                    """,
                    [
                        bt_run_id,
                        int(row["asset_id"]),
                        str(row["symbol"]),
                        str(row["venue"]),
                        row["entry_ts_utc"],
                        row["selection_state"],
                        row["selection_bias"],
                        row["selection_score"],
                        row["priority_rank"],
                        row["fee_bps_per_side"],
                        row["entry_close_price"],
                        row["next_ts_1h_utc"],
                        row["next_close_price_1h"],
                        row["gross_return_1h"],
                        row["next_return_1h"],
                        row["next_ts_4h_utc"],
                        row["next_close_price_4h"],
                        row["gross_return_4h"],
                        row["next_return_4h"],
                        row["next_ts_24h_utc"],
                        row["next_close_price_24h"],
                        row["gross_return_24h"],
                        row["next_return_24h"],
                    ],
                )
        if dry_run:
            conn.rollback()
        else:
            conn.commit()
        return len(rows)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def summarize(rows: list[dict[str, Any]]) -> dict[str, str]:
    count_all = len(rows)
    count_1h = 0
    count_4h = 0
    count_24h = 0

    sum_1h = Decimal("0")
    sum_4h = Decimal("0")
    sum_24h = Decimal("0")

    wins_1h = 0
    wins_4h = 0
    wins_24h = 0

    for row in rows:
        r1 = row["next_return_1h"]
        r4 = row["next_return_4h"]
        r24 = row["next_return_24h"]

        if r1 is not None:
            d1 = _to_decimal(r1)
            count_1h += 1
            sum_1h += d1
            if d1 > 0:
                wins_1h += 1

        if r4 is not None:
            d4 = _to_decimal(r4)
            count_4h += 1
            sum_4h += d4
            if d4 > 0:
                wins_4h += 1

        if r24 is not None:
            d24 = _to_decimal(r24)
            count_24h += 1
            sum_24h += d24
            if d24 > 0:
                wins_24h += 1

    def _avg(total: Decimal, count: int) -> str:
        if count == 0:
            return ""
        return str((total / Decimal(str(count))).quantize(Decimal("0.00000001")))

    def _winrate(wins: int, count: int) -> str:
        if count == 0:
            return ""
        return str((Decimal(str(wins)) / Decimal(str(count))).quantize(Decimal("0.0001")))

    return {
        "rows_total": str(count_all),
        "rows_1h": str(count_1h),
        "rows_4h": str(count_4h),
        "rows_24h": str(count_24h),
        "avg_return_1h": _avg(sum_1h, count_1h),
        "avg_return_4h": _avg(sum_4h, count_4h),
        "avg_return_24h": _avg(sum_24h, count_24h),
        "winrate_1h": _winrate(wins_1h, count_1h),
        "winrate_4h": _winrate(wins_4h, count_4h),
        "winrate_24h": _winrate(wins_24h, count_24h),
    }


def summarize_by_state(rows: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["selection_state"])].append(row)

    out: dict[str, dict[str, str]] = {}
    for state_name, state_rows in sorted(grouped.items()):
        out[state_name] = summarize(state_rows)
    return out


def print_state_breakdown(rows: list[dict[str, Any]]) -> None:
    breakdown = summarize_by_state(rows)
    print("=== STATE BREAKDOWN ===")
    print(
        "selection_state | rows_total | rows_1h | rows_4h | rows_24h | "
        "avg_return_1h | avg_return_4h | avg_return_24h | "
        "winrate_1h | winrate_4h | winrate_24h"
    )
    print(
        "---------------+------------+---------+---------+----------+"
        "---------------+---------------+----------------+"
        "------------+------------+-------------"
    )
    for state_name, stats in breakdown.items():
        print(
            f"{state_name} | "
            f"{stats['rows_total']} | "
            f"{stats['rows_1h']} | "
            f"{stats['rows_4h']} | "
            f"{stats['rows_24h']} | "
            f"{stats['avg_return_1h']} | "
            f"{stats['avg_return_4h']} | "
            f"{stats['avg_return_24h']} | "
            f"{stats['winrate_1h']} | "
            f"{stats['winrate_4h']} | "
            f"{stats['winrate_24h']}"
        )


def main() -> int:
    args = parse_args()

    loaded_config = load_config_set(
        scope=args.config_scope,
        config_name=args.config_name,
    )
    cfg = loaded_config.config_by_component

    entry_interval_code = str(cfg["backtest"]["entry_interval_code"])
    forward_horizon_candles = _require_int(cfg, "backtest", "forward_horizon_candles")
    fee_bps_per_side = _require_decimal_with_default(cfg, "backtest", "fee_bps_per_side", "0")

    if entry_interval_code != "1h":
        raise ValueError("run_backtest_selection_eval_v1 currently supports only backtest.entry_interval_code = '1h'")

    if forward_horizon_candles != 4:
        print(
            f"[WARN] backtest.forward_horizon_candles={forward_horizon_candles} "
            f"but this evaluator still writes canonical 1h/4h/24h outputs."
        )

    ensure_bt_tables()

    rows = fetch_eval_rows(
        venue=args.venue,
        from_ts=args.from_ts,
        to_ts=args.to_ts,
        engine_name=args.engine_name,
        engine_version=args.engine_version,
        selection_states=args.selection_states,
        fee_bps_per_side=fee_bps_per_side,
    )

    bt_run_id = insert_bt_run(
        config_set_id=loaded_config.config_set.config_set_id,
        config_snapshot_json=_snapshot_json(loaded_config),
        venue=args.venue,
        from_ts=args.from_ts,
        to_ts=args.to_ts,
        engine_name=args.engine_name,
        engine_version=args.engine_version,
        selection_states=args.selection_states,
        fee_bps_per_side=fee_bps_per_side,
        dry_run=args.dry_run,
    )

    rows_written = write_eval_rows(
        bt_run_id=bt_run_id,
        rows=rows,
        dry_run=args.dry_run,
    )

    summary = summarize(rows)

    print(
        f"bt_run_id={bt_run_id} "
        f"config_set_id={loaded_config.config_set.config_set_id} "
        f"config_name={loaded_config.config_set.config_name} "
        f"venue={args.venue} "
        f"from_ts={args.from_ts} "
        f"to_ts={args.to_ts} "
        f"states={','.join(args.selection_states)} "
        f"fee_bps_per_side={fee_bps_per_side} "
        f"rows_total={summary['rows_total']} "
        f"rows_written={rows_written} "
        f"rows_1h={summary['rows_1h']} "
        f"rows_4h={summary['rows_4h']} "
        f"rows_24h={summary['rows_24h']} "
        f"avg_return_1h={summary['avg_return_1h']} "
        f"avg_return_4h={summary['avg_return_4h']} "
        f"avg_return_24h={summary['avg_return_24h']} "
        f"winrate_1h={summary['winrate_1h']} "
        f"winrate_4h={summary['winrate_4h']} "
        f"winrate_24h={summary['winrate_24h']} "
        f"dry_run={args.dry_run}"
    )

    print_state_breakdown(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
