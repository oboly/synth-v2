from __future__ import annotations

import argparse
from typing import Any


from src.common.db import get_db_connection


def risk_penalty(risk_signal: str) -> float:
    return {
        "RISK_OK": 0.0,
        "RISK_WAIT_CONFIRMATION": 0.45,
        "RISK_CONFLICTING_SIGNALS": 0.85,
        "RISK_HIGH": 1.0,
    }.get(risk_signal, 0.5)


def map_regime(row: dict[str, Any]) -> str:
    trend = row["trend_signal"]
    phase = row["phase_signal"]
    relative = row["relative_signal"]
    setup = row["setup_signal"]
    risk = row["risk_signal"]
    volume = row["volume_signal"]
    delay = int(row["expansion_delay_state"])
    rotation_score = float(row["rotation_trigger_score"])

    if risk in ("RISK_HIGH", "RISK_CONFLICTING_SIGNALS") or volume == "VOLUME_DISTRIBUTION":
        return "RISK_OFF"

    if trend == "TREND_DOWN_STRONG":
        return "RESET_DAMAGE"

    if delay == 1 and phase in ("PHASE_COMPRESSION", "PHASE_INTEGRATION"):
        return "COMPRESSION_BUILD"

    if rotation_score >= 0.45:
        return "ROTATION_OPENING"

    if trend in ("TREND_UP_STRONG", "TREND_UP_WEAK") and relative in ("RELSTR_IMPROVING", "RELSTR_LEADING"):
        return "TREND_EXPANSION"

    if trend == "TREND_SIDEWAYS":
        return "RANGE_CHOP"

    if setup == "SETUP_BUILDING":
        return "NEUTRAL_TRANSITION"

    return "NEUTRAL_TRANSITION"


def map_horizon(regime: str) -> str:
    return {
        "ROTATION_OPENING": "SWING_SHORT",
        "TREND_EXPANSION": "SWING_MEDIUM",
        "COMPRESSION_BUILD": "WATCH_ONLY",
        "RANGE_CHOP": "WATCH_ONLY",
        "RISK_OFF": "NO_TRADE",
        "RESET_DAMAGE": "NO_TRADE",
        "NEUTRAL_TRANSITION": "WATCH_ONLY",
    }.get(regime, "WATCH_ONLY")


def map_advice(regime: str, setup: str, rotation_state: int) -> str:
    if regime in ("RISK_OFF", "RESET_DAMAGE"):
        return "AVOID"

    if regime == "ROTATION_OPENING" and rotation_state == 1:
        return "TRIGGERED"

    if regime == "COMPRESSION_BUILD" and setup == "SETUP_BUILDING":
        return "BUILD"

    if regime == "TREND_EXPANSION" and setup in ("SETUP_BUILDING", "SETUP_ARMED"):
        return "ARM"

    if regime == "RANGE_CHOP":
        return "WATCH"

    if regime == "NEUTRAL_TRANSITION" and setup == "SETUP_BUILDING":
        return "WATCH"

    return "NO_ACTION"


def compute_scores(row: dict[str, Any]) -> dict[str, float]:
    penalty = risk_penalty(str(row["risk_signal"]))

    signal_confidence = float(row["signal_confidence"])
    phase_score = float(row["phase_score"])
    relative_score = float(row["relative_score"])
    setup_score = float(row["setup_score"])
    rotation_trigger_score = float(row["rotation_trigger_score"])
    expansion_delay_score = float(row["expansion_delay_score"])
    engine_risk_score = float(row["risk_score"])

    regime_fit = (
        0.30 * signal_confidence
        + 0.20 * phase_score
        + 0.20 * relative_score
        + 0.15 * setup_score
        + 0.15 * (1.0 - penalty)
    )

    opportunity = (
        0.35 * signal_confidence
        + 0.20 * setup_score
        + 0.20 * relative_score
        + 0.15 * rotation_trigger_score
        + 0.10 * expansion_delay_score
    )

    risk_score = 1.0 - engine_risk_score

    return {
        "regime_fit_score": round(regime_fit, 6),
        "opportunity_score": round(opportunity, 6),
        "risk_score": round(risk_score, 6),
    }


def build_summary(
    regime_label: str,
    horizon_hint: str,
    advice_state: str,
    row: dict[str, Any],
) -> str:
    return (
        f"{regime_label}; horizon={horizon_hint}; advice={advice_state}; "
        f"trend={row['trend_signal']}; phase={row['phase_signal']}; "
        f"setup={row['setup_signal']}; risk={row['risk_signal']}"
    )


def fetch_signal_rows(conn, interval: str) -> list[dict[str, Any]]:
    sql = """
    SELECT
        ses.*
    FROM signal_engine_state ses
    WHERE ses.interval_code = %s
    ORDER BY ses.signal_ts_utc DESC, ses.asset_id
    """

    with conn.cursor() as cur:
        cur.execute(sql, (interval,))
        rows = cur.fetchall()

    if not rows:
        return []

    out: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            out.append(row)
        else:
            raise TypeError("Expected dict rows from database cursor")

    return out


def upsert_advice_rows(conn, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0

    sql = """
    INSERT INTO advice_state (
        asset_id,
        venue,
        interval_code,
        asof_ts_utc,
        regime_label,
        time_horizon_hint,
        advice_state,
        regime_fit_score,
        opportunity_score,
        risk_score,
        priority_rank,
        summary_text
    ) VALUES (
        %(asset_id)s,
        %(venue)s,
        %(interval_code)s,
        %(asof_ts_utc)s,
        %(regime_label)s,
        %(time_horizon_hint)s,
        %(advice_state)s,
        %(regime_fit_score)s,
        %(opportunity_score)s,
        %(risk_score)s,
        %(priority_rank)s,
        %(summary_text)s
    )
    ON DUPLICATE KEY UPDATE
        regime_label = VALUES(regime_label),
        time_horizon_hint = VALUES(time_horizon_hint),
        advice_state = VALUES(advice_state),
        regime_fit_score = VALUES(regime_fit_score),
        opportunity_score = VALUES(opportunity_score),
        risk_score = VALUES(risk_score),
        priority_rank = VALUES(priority_rank),
        summary_text = VALUES(summary_text)
    """

    with conn.cursor() as cur:
        cur.executemany(sql, rows)

    conn.commit()
    return len(rows)


def run(interval: str) -> int:
    conn = get_db_connection()

    try:
        signal_rows = fetch_signal_rows(conn, interval=interval)

        if not signal_rows:
            print(f"[WARN] no signal rows found for interval={interval}")
            return 0

        advice_rows: list[dict[str, Any]] = []

        for row in signal_rows:
            regime_label = map_regime(row)
            horizon_hint = map_horizon(regime_label)
            advice_state = map_advice(
                regime_label,
                str(row["setup_signal"]),
                int(row["rotation_trigger_state"]),
            )
            scores = compute_scores(row)
            summary_text = build_summary(
                regime_label,
                horizon_hint,
                advice_state,
                row,
            )

            advice_rows.append(
                {
                    "asset_id": int(row["asset_id"]),
                    "venue": str(row["venue"]),
                    "interval_code": str(row["interval_code"]),
                    "asof_ts_utc": row["signal_ts_utc"],
                    "regime_label": regime_label,
                    "time_horizon_hint": horizon_hint,
                    "advice_state": advice_state,
                    "regime_fit_score": scores["regime_fit_score"],
                    "opportunity_score": scores["opportunity_score"],
                    "risk_score": scores["risk_score"],
                    "priority_rank": None,
                    "summary_text": summary_text,
                }
            )

        advice_rows.sort(
            key=lambda r: (
                r["opportunity_score"],
                r["regime_fit_score"],
                -r["risk_score"],
            ),
            reverse=True,
        )

        for idx, row in enumerate(advice_rows, start=1):
            row["priority_rank"] = idx

        written = upsert_advice_rows(conn, advice_rows)
        print(f"[DONE] advice rows={written} interval={interval}")
        return written

    finally:
        conn.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run advice engine from signal_engine_state")
    parser.add_argument("--interval", default="1h")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run(interval=args.interval)
