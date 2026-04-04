from __future__ import annotations

import argparse
from typing import Any

from src.common.db import get_db_connection


STATE_PRIORITY: dict[str, int] = {
    "STRONG_CANDIDATE": 1,
    "PRE_ALIGNMENT": 2,
    "EARLY_WATCH": 3,
    "TRIGGER_NO_HTF_CONFIRM": 4,
    "HTF_READY_LTF_LAG": 5,
    "MIXED_NEUTRAL": 6,
    "LOW_PRIORITY": 7,
    "REJECTED_HTF": 8,
    "REJECTED_LTF": 9,
    "INCOMPLETE_4H": 10,
    "INCOMPLETE_1H": 11,
    "NO_DATA": 12,
}


def fetch_latest_advice_by_interval(conn, interval_code: str) -> dict[int, dict[str, Any]]:
    sql = """
    SELECT *
    FROM (
        SELECT
            a.*,
            ROW_NUMBER() OVER (
                PARTITION BY a.asset_id, a.venue, a.interval_code
                ORDER BY a.asof_ts_utc DESC
            ) AS rn
        FROM advice_state a
        WHERE a.interval_code = %s
    ) q
    WHERE q.rn = 1
    """

    with conn.cursor() as cur:
        cur.execute(sql, (interval_code,))
        rows = cur.fetchall()

    out: dict[int, dict[str, Any]] = {}

    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("Expected dict rows from database cursor")
        out[int(row["asset_id"])] = row

    return out


def map_selection(
    row_1h: dict[str, Any] | None,
    row_4h: dict[str, Any] | None,
) -> tuple[str, str, float, str]:
    if row_1h is None and row_4h is None:
        return ("NO_DATA", "NEUTRAL", 0.0, "No 1h or 4h advice available.")

    if row_4h is None:
        opp_1h = float(row_1h["opportunity_score"])
        risk_1h = float(row_1h["risk_score"])
        score = max(0.0, opp_1h - (0.25 * risk_1h))
        return (
            "INCOMPLETE_4H",
            "WATCH",
            round(score, 6),
            "1h advice available, but 4h context missing.",
        )

    if row_1h is None:
        opp_4h = float(row_4h["opportunity_score"])
        risk_4h = float(row_4h["risk_score"])
        score = max(0.0, opp_4h - (0.25 * risk_4h))
        return (
            "INCOMPLETE_1H",
            "WATCH",
            round(score, 6),
            "4h advice available, but 1h timing context missing.",
        )

    regime_1h = str(row_1h["regime_label"])
    regime_4h = str(row_4h["regime_label"])
    advice_1h = str(row_1h["advice_state"])
    advice_4h = str(row_4h["advice_state"])

    opp_1h = float(row_1h["opportunity_score"])
    opp_4h = float(row_4h["opportunity_score"])
    risk_1h = float(row_1h["risk_score"])
    risk_4h = float(row_4h["risk_score"])

    score = (
        0.55 * opp_1h
        + 0.45 * opp_4h
        - 0.25 * risk_1h
        - 0.20 * risk_4h
    )

    # Hard higher-timeframe rejection
    if regime_4h in {"RISK_OFF", "RESET_DAMAGE"} or advice_4h == "AVOID":
        score -= 0.25
        return (
            "REJECTED_HTF",
            "AVOID",
            round(max(0.0, score), 6),
            f"4h context is weak/damaged ({regime_4h}, {advice_4h}).",
        )

    # Hard lower-timeframe rejection when 1h is clearly risk-off
    # and 4h is not strong enough to rescue the setup.
    if regime_1h == "RISK_OFF" or advice_1h == "AVOID":
        if not (
            regime_4h in {"TREND_EXPANSION", "COMPRESSION_BUILD"}
            and advice_4h in {"BUILD", "ARM", "TRIGGERED"}
        ):
            score -= 0.18
            return (
                "REJECTED_LTF",
                "AVOID",
                round(max(0.0, score), 6),
                f"1h context is weak/risk-off ({regime_1h}, {advice_1h}) without strong 4h rescue.",
            )

    # Best aligned cases
    if advice_1h in {"BUILD", "ARM"} and advice_4h in {"ARM", "WATCH", "BUILD"}:
        if regime_4h in {"TREND_EXPANSION", "COMPRESSION_BUILD", "NEUTRAL_TRANSITION"}:
            score += 0.12
            return (
                "STRONG_CANDIDATE",
                "LONG_BIAS",
                round(min(1.0, score), 6),
                f"1h is actionable ({advice_1h}) and 4h supports continuation ({regime_4h}/{advice_4h}).",
            )

    # Higher timeframe ready, lower timeframe not aligned yet
    if advice_4h in {"ARM", "BUILD"} and advice_1h in {"WATCH", "NO_ACTION"}:
        if regime_4h in {"TREND_EXPANSION", "COMPRESSION_BUILD"}:
            score += 0.05
            return (
                "PRE_ALIGNMENT",
                "WATCH",
                round(min(1.0, score), 6),
                f"4h structure is constructive ({advice_4h}) but 1h timing is not aligned yet.",
            )

    # 1h constructive, 4h neutral but not weak
    if advice_1h in {"BUILD", "ARM"} and regime_4h in {"RANGE_CHOP", "NEUTRAL_TRANSITION", "COMPRESSION_BUILD"}:
        return (
            "EARLY_WATCH",
            "WATCH",
            round(max(0.0, score), 6),
            f"1h is constructive ({advice_1h}) while 4h remains neutral/compression ({regime_4h}).",
        )

    # 1h triggered but 4h still too passive
    if advice_1h == "TRIGGERED" and advice_4h in {"NO_ACTION", "WATCH"}:
        score -= 0.05
        return (
            "TRIGGER_NO_HTF_CONFIRM",
            "WATCH",
            round(max(0.0, score), 6),
            f"1h trigger is active, but 4h confirmation is still limited ({advice_4h}/{regime_4h}).",
        )

    # 4h strong/triggered, 1h still lagging
    if advice_4h in {"TRIGGERED", "ARM"} and advice_1h in {"WATCH", "NO_ACTION"}:
        score += 0.03
        return (
            "HTF_READY_LTF_LAG",
            "WATCH",
            round(max(0.0, score), 6),
            f"4h is active/ready ({advice_4h}) while 1h timing still lags.",
        )

    # Both mostly passive
    if advice_1h in {"WATCH", "NO_ACTION"} and advice_4h in {"WATCH", "NO_ACTION"}:
        return (
            "LOW_PRIORITY",
            "NEUTRAL",
            round(max(0.0, score), 6),
            "Both 1h and 4h remain non-actionable or watch-only.",
        )

    # Remaining cases are neutral mismatches, not top priority
    score -= 0.04
    return (
        "MIXED_NEUTRAL",
        "WATCH",
        round(max(0.0, score), 6),
        f"Mixed timeframe state: 1h={advice_1h}/{regime_1h}, 4h={advice_4h}/{regime_4h}.",
    )


def upsert_selection_rows(conn, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0

    sql = """
    INSERT INTO selection_state (
        asset_id,
        venue,
        asof_ts_utc,
        advice_ts_1h_utc,
        advice_ts_4h_utc,
        selection_state,
        selection_bias,
        selection_score,
        regime_label_1h,
        regime_label_4h,
        advice_state_1h,
        advice_state_4h,
        opportunity_score_1h,
        opportunity_score_4h,
        risk_score_1h,
        risk_score_4h,
        priority_rank,
        summary_text
    ) VALUES (
        %(asset_id)s,
        %(venue)s,
        %(asof_ts_utc)s,
        %(advice_ts_1h_utc)s,
        %(advice_ts_4h_utc)s,
        %(selection_state)s,
        %(selection_bias)s,
        %(selection_score)s,
        %(regime_label_1h)s,
        %(regime_label_4h)s,
        %(advice_state_1h)s,
        %(advice_state_4h)s,
        %(opportunity_score_1h)s,
        %(opportunity_score_4h)s,
        %(risk_score_1h)s,
        %(risk_score_4h)s,
        %(priority_rank)s,
        %(summary_text)s
    )
    ON DUPLICATE KEY UPDATE
        advice_ts_1h_utc = VALUES(advice_ts_1h_utc),
        advice_ts_4h_utc = VALUES(advice_ts_4h_utc),
        selection_state = VALUES(selection_state),
        selection_bias = VALUES(selection_bias),
        selection_score = VALUES(selection_score),
        regime_label_1h = VALUES(regime_label_1h),
        regime_label_4h = VALUES(regime_label_4h),
        advice_state_1h = VALUES(advice_state_1h),
        advice_state_4h = VALUES(advice_state_4h),
        opportunity_score_1h = VALUES(opportunity_score_1h),
        opportunity_score_4h = VALUES(opportunity_score_4h),
        risk_score_1h = VALUES(risk_score_1h),
        risk_score_4h = VALUES(risk_score_4h),
        priority_rank = VALUES(priority_rank),
        summary_text = VALUES(summary_text)
    """

    with conn.cursor() as cur:
        cur.executemany(sql, rows)

    conn.commit()
    return len(rows)


def run() -> int:
    conn = get_db_connection()

    try:
        latest_1h = fetch_latest_advice_by_interval(conn, "1h")
        latest_4h = fetch_latest_advice_by_interval(conn, "4h")

        all_asset_ids = sorted(set(latest_1h.keys()) | set(latest_4h.keys()))
        rows: list[dict[str, Any]] = []

        for asset_id in all_asset_ids:
            row_1h = latest_1h.get(asset_id)
            row_4h = latest_4h.get(asset_id)

            venue = str(row_1h["venue"]) if row_1h is not None else str(row_4h["venue"])
            asof_ts_utc = row_1h["asof_ts_utc"] if row_1h is not None else row_4h["asof_ts_utc"]

            selection_state, selection_bias, selection_score, summary_text = map_selection(
                row_1h,
                row_4h,
            )

            rows.append(
                {
                    "asset_id": asset_id,
                    "venue": venue,
                    "asof_ts_utc": asof_ts_utc,
                    "advice_ts_1h_utc": None if row_1h is None else row_1h["asof_ts_utc"],
                    "advice_ts_4h_utc": None if row_4h is None else row_4h["asof_ts_utc"],
                    "selection_state": selection_state,
                    "selection_bias": selection_bias,
                    "selection_score": round(selection_score, 6),
                    "regime_label_1h": None if row_1h is None else row_1h["regime_label"],
                    "regime_label_4h": None if row_4h is None else row_4h["regime_label"],
                    "advice_state_1h": None if row_1h is None else row_1h["advice_state"],
                    "advice_state_4h": None if row_4h is None else row_4h["advice_state"],
                    "opportunity_score_1h": None if row_1h is None else row_1h["opportunity_score"],
                    "opportunity_score_4h": None if row_4h is None else row_4h["opportunity_score"],
                    "risk_score_1h": None if row_1h is None else row_1h["risk_score"],
                    "risk_score_4h": None if row_4h is None else row_4h["risk_score"],
                    "priority_rank": None,
                    "summary_text": summary_text,
                }
            )

        rows.sort(
            key=lambda r: (
                STATE_PRIORITY.get(r["selection_state"], 999),
                -r["selection_score"],
            )
        )

        for idx, row in enumerate(rows, start=1):
            row["priority_rank"] = idx

        written = upsert_selection_rows(conn, rows)
        print(f"[DONE] selection rows={written}")
        return written

    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run multi-timeframe selection engine")
    _ = parser.parse_args()
    run()
