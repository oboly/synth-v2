from __future__ import annotations

import argparse
from typing import Any

from src.common.db import get_db_connection


STRUCTURE_ENGINE_NAME = "structure_state_engine"
STRUCTURE_ENGINE_VERSION = "1.1"
SELECTION_ENGINE_NAME = "selection_engine"
SELECTION_ENGINE_VERSION = "1.1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Technical selection report with structure-state context"
    )
    parser.add_argument("--top", type=int, default=20)
    return parser.parse_args()


def fetch_rows(conn) -> list[dict[str, Any]]:
    sql = """
    SELECT
        s.asof_ts_utc,
        s.priority_rank,
        s.selection_state,
        s.selection_bias,
        s.selection_score,
        s.regime_label_1h,
        s.regime_label_4h,
        s.advice_state_1h,
        s.advice_state_4h,
        s.summary_text,
        a.symbol,
        a.asset_class,
        a.sector,

        st1h.trend_state AS trend_state_1h,
        st1h.pullback_state AS pullback_state_1h,
        st1h.reclaim_state AS reclaim_state_1h,

        st4h.trend_state AS trend_state_4h,
        st4h.pullback_state AS pullback_state_4h,
        st4h.reclaim_state AS reclaim_state_4h,

        st1d.trend_state AS trend_state_1d,
        st1d.pullback_state AS pullback_state_1d,
        st1d.reclaim_state AS reclaim_state_1d

    FROM vw_selection_latest s
    JOIN asset a
      ON a.asset_id = s.asset_id

    LEFT JOIN vw_structure_state_latest st1h
      ON st1h.asset_id = s.asset_id
     AND st1h.interval_code = '1h'
     AND st1h.engine_name = %s
     AND st1h.engine_version = %s

    LEFT JOIN vw_structure_state_latest st4h
      ON st4h.asset_id = s.asset_id
     AND st4h.interval_code = '4h'
     AND st4h.engine_name = %s
     AND st4h.engine_version = %s

    LEFT JOIN vw_structure_state_latest st1d
      ON st1d.asset_id = s.asset_id
     AND st1d.interval_code = '1d'
     AND st1d.engine_name = %s
     AND st1d.engine_version = %s

    WHERE s.engine_name = %s
      AND s.engine_version = %s
    ORDER BY s.priority_rank
    """

    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                STRUCTURE_ENGINE_NAME, STRUCTURE_ENGINE_VERSION,
                STRUCTURE_ENGINE_NAME, STRUCTURE_ENGINE_VERSION,
                STRUCTURE_ENGINE_NAME, STRUCTURE_ENGINE_VERSION,
                SELECTION_ENGINE_NAME, SELECTION_ENGINE_VERSION,
            ),
        )
        rows = cur.fetchall()

    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("Expected dict rows")
        out.append(row)
    return out


def print_group(title: str, rows: list[dict[str, Any]], limit: int) -> None:
    print(title)
    if not rows:
        print("(none)")
        print()
        return

    for row in rows[:limit]:
        print(
            f"{row['priority_rank']}. {row['symbol']} | "
            f"{row['selection_state']} | "
            f"score={row['selection_score']} | "
            f"4h_advice={row['advice_state_4h']} | "
            f"1h_advice={row['advice_state_1h']} | "
            f"4h_trend={row['trend_state_4h']} | "
            f"1h_pullback={row['pullback_state_1h']} | "
            f"4h_reclaim={row['reclaim_state_4h']} | "
            f"1d_reclaim={row['reclaim_state_1d']}"
        )
    print()


def main() -> int:
    args = parse_args()
    conn = get_db_connection()

    try:
        rows = fetch_rows(conn)

        if not rows:
            print("[WARN] no selection rows found")
            return 0

        print("=== SYNTH SELECTION REPORT ===")
        print(f"snapshot_ts={rows[0]['asof_ts_utc']}")
        print()

        buy_ready = [r for r in rows if r["selection_state"] == "BUY_READY"]
        prepare = [r for r in rows if r["selection_state"] == "PREPARE"]
        watchlist = [r for r in rows if r["selection_state"] == "WATCHLIST"]
        tactical = [r for r in rows if r["selection_state"] == "TACTICAL_ONLY"]
        avoid = [r for r in rows if r["selection_state"] == "AVOID"]

        print_group("BUY READY", buy_ready, args.top)
        print_group("PREPARE", prepare, args.top)
        print_group("WATCHLIST", watchlist, args.top)
        print_group("TACTICAL ONLY", tactical, args.top)
        print_group("AVOID", avoid, args.top)

        print("SUMMARY")
        print(f"buy_ready={len(buy_ready)}")
        print(f"prepare={len(prepare)}")
        print(f"watchlist={len(watchlist)}")
        print(f"tactical_only={len(tactical)}")
        print(f"avoid={len(avoid)}")

        return 0

    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
