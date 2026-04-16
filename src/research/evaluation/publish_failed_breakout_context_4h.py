from __future__ import annotations

from decimal import Decimal
from typing import Any

from src.common.db import db_cursor


SELECT_SQL = """
SELECT
    asset_id,
    interval_code,
    asof_ts_utc,
    failed_breakout_flag_4h,
    breakout_failure_state,
    bearish_failure_context_score,
    avoid_long_overlay_flag
FROM v_failed_breakout_context_bridge_4h
WHERE interval_code = '4h'
  AND asof_ts_utc >= %s
"""

UPSERT_SQL = """
INSERT INTO strategy_signal_context (
    asset_id,
    interval_code,
    context_ts_utc,
    failed_breakout_flag_4h,
    breakout_failure_state,
    bearish_failure_context_score,
    avoid_long_overlay_flag
) VALUES (
    %(asset_id)s,
    %(interval_code)s,
    %(context_ts_utc)s,
    %(failed_breakout_flag_4h)s,
    %(breakout_failure_state)s,
    %(bearish_failure_context_score)s,
    %(avoid_long_overlay_flag)s
)
ON DUPLICATE KEY UPDATE
    failed_breakout_flag_4h = VALUES(failed_breakout_flag_4h),
    breakout_failure_state = VALUES(breakout_failure_state),
    bearish_failure_context_score = VALUES(bearish_failure_context_score),
    avoid_long_overlay_flag = VALUES(avoid_long_overlay_flag),
    updated_ts_utc = CURRENT_TIMESTAMP
"""


def _normalize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    return value


def main() -> None:
    from_ts = "2026-01-01 00:00:00"

    with db_cursor(commit=True) as (_conn, cur):
        cur.execute(SELECT_SQL, (from_ts,))
        rows = cur.fetchall()

        if not rows:
            print("No rows found in bridge view.")
            return

        payload = []
        for row in rows:
            clean = {k: _normalize(v) for k, v in row.items()}

            payload.append(
                {
                    "asset_id": clean["asset_id"],
                    "interval_code": clean["interval_code"],
                    "context_ts_utc": clean["asof_ts_utc"],
                    "failed_breakout_flag_4h": clean["failed_breakout_flag_4h"],
                    "breakout_failure_state": clean["breakout_failure_state"],
                    "bearish_failure_context_score": clean["bearish_failure_context_score"],
                    "avoid_long_overlay_flag": clean["avoid_long_overlay_flag"],
                }
            )

        cur.executemany(UPSERT_SQL, payload)

    print(f"[DONE] published_rows={len(payload)} from_ts={from_ts}")


if __name__ == "__main__":
    main()
