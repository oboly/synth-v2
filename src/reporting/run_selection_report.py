from __future__ import annotations

import argparse
from typing import Any

from src.common.db import get_db_connection


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Technical selection report using effective overlay-adjusted selection output"
    )
    parser.add_argument("--top", type=int, default=20)
    return parser.parse_args()


def fetch_rows(conn) -> list[dict[str, Any]]:
    sql = """
    SELECT
        asof_ts_utc,
        priority_rank,
        symbol,
        selection_state,
        selection_bias,

        base_selection_score,
        effective_selection_score,

        breakout_failure_regime_tier,
        structural_conflict_type,
        htf_rule_state,

        recommendation_cap_final,
        effective_recommendation,

        regime_label_1h,
        regime_label_4h,
        advice_state_1h,
        advice_state_4h,
        latest_failed_breakout_ts_utc,
        hours_since_failed_breakout,
        summary_text

    FROM v_selection_latest_effective
    ORDER BY effective_selection_score DESC, symbol ASC
    """

    with conn.cursor() as cur:
        cur.execute(sql)
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
        overlay_bits: list[str] = []

        if row.get("breakout_failure_regime_tier"):
            overlay_bits.append(f"failure={row['breakout_failure_regime_tier']}")

        if row.get("structural_conflict_type"):
            overlay_bits.append(f"struct={row['structural_conflict_type']}")

        if row.get("htf_rule_state"):
            overlay_bits.append(f"htf={row['htf_rule_state']}")

        if row.get("recommendation_cap_final"):
            overlay_bits.append(f"cap={row['recommendation_cap_final']}")

        overlay_text = " | ".join(overlay_bits) if overlay_bits else "-"

        print(
            f"{row['symbol']} | "
            f"state={row['selection_state']} | "
            f"bias={row['selection_bias']} | "
            f"base={row['base_selection_score']} | "
            f"effective={row['effective_selection_score']} | "
            f"rec={row['effective_recommendation']} | "
            f"4h_advice={row['advice_state_4h']} | "
            f"1h_advice={row['advice_state_1h']} | "
            f"overlays={overlay_text}"
        )
    print()


def main() -> int:
    args = parse_args()
    conn = get_db_connection()

    try:
        rows = fetch_rows(conn)

        if not rows:
            print("[WARN] no effective selection rows found")
            return 0

        print("=== SYNTH SELECTION REPORT (EFFECTIVE) ===")
        print(f"snapshot_ts={rows[0]['asof_ts_utc']}")
        print()

        buy_ready = [r for r in rows if r["effective_recommendation"] == "BUY"]
        watch = [r for r in rows if r["effective_recommendation"] == "WATCH"]
        tactical = [r for r in rows if r["effective_recommendation"] == "TACTICAL_ONLY"]
        avoid = [r for r in rows if r["effective_recommendation"] == "NO_TRADE"]

        print_group("BUY", buy_ready, args.top)
        print_group("WATCH", watch, args.top)
        print_group("TACTICAL ONLY", tactical, args.top)
        print_group("NO TRADE", avoid, args.top)

        print("SUMMARY")
        print(f"buy={len(buy_ready)}")
        print(f"watch={len(watch)}")
        print(f"tactical_only={len(tactical)}")
        print(f"no_trade={len(avoid)}")

        return 0

    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
