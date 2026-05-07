from __future__ import annotations

import argparse
from datetime import UTC, datetime
from typing import Any

from src.common.db import get_db_connection


ENGINE_NAME = "advice_engine"
ENGINE_VERSION = "1.1"


def risk_penalty(risk_signal: str) -> float:
    return {
        "RISK_OK": 0.0,
        "RISK_WAIT_CONFIRMATION": 0.45,
        "RISK_CONFLICTING_SIGNALS": 0.85,
        "RISK_HIGH": 1.0,
    }.get(risk_signal, 0.5)


def map_regime(row: dict[str, Any]) -> str:
    trend = str(row["trend_signal"])
    phase = str(row["phase_signal"])
    relative = str(row["relative_signal"])
    setup = str(row["setup_signal"])
    risk = str(row["risk_signal"])
    volume = str(row["volume_signal"])
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

    if trend in ("TREND_UP_STRONG", "TREND_UP_WEAK") and relative in (
        "RELSTR_IMPROVING",
        "RELSTR_LEADING",
    ):
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


def _normalize_ts(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def fetch_recent_snapshot_candidates(
    conn,
    *,
    venue: str,
    interval: str,
    limit: int = 20,
) -> list[datetime]:
    sql = """
    SELECT DISTINCT
        ses.signal_ts_utc
    FROM signal_engine_state ses
    WHERE ses.venue = %s
      AND ses.interval_code = %s
    ORDER BY ses.signal_ts_utc DESC
    LIMIT %s
    """

    with conn.cursor() as cur:
        cur.execute(sql, (venue, interval, limit))
        rows = cur.fetchall()

    out: list[datetime] = []
    for row in rows:
        value = row["signal_ts_utc"] if isinstance(row, dict) else row[0]
        if value is not None:
            out.append(_normalize_ts(value))
    return out


def count_enabled_rows_for_snapshot(
    conn,
    *,
    venue: str,
    interval: str,
    snapshot_ts_utc: datetime,
) -> int:
    sql = """
    SELECT
        COUNT(*) AS snapshot_rows
    FROM signal_engine_state ses
    JOIN asset a
      ON a.asset_id = ses.asset_id
    WHERE ses.venue = %s
      AND ses.interval_code = %s
      AND ses.signal_ts_utc = %s
      AND a.is_enabled = 1
    """

    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                venue,
                interval,
                snapshot_ts_utc.replace(tzinfo=None),
            ),
        )
        row = cur.fetchone()

    if not row:
        return 0

    return int(row["snapshot_rows"] if isinstance(row, dict) else row[0])


def fetch_latest_snapshot_ts(
    conn,
    *,
    venue: str,
    interval: str,
) -> datetime | None:
    min_snapshot_rows = {
        "1h": 20,
        "4h": 20,
        "1d": 20,
    }.get(interval, 20)

    candidates = fetch_recent_snapshot_candidates(
        conn,
        venue=venue,
        interval=interval,
        limit=20,
    )

    for snapshot_ts_utc in candidates:
        snapshot_rows = count_enabled_rows_for_snapshot(
            conn,
            venue=venue,
            interval=interval,
            snapshot_ts_utc=snapshot_ts_utc,
        )
        if snapshot_rows >= min_snapshot_rows:
            return snapshot_ts_utc

    return None


def fetch_signal_rows(
    conn,
    *,
    venue: str,
    interval: str,
) -> tuple[datetime | None, list[dict[str, Any]]]:
    snapshot_ts_utc = fetch_latest_snapshot_ts(
        conn,
        venue=venue,
        interval=interval,
    )

    if snapshot_ts_utc is None:
        return None, []

    sql = """
    SELECT
        ses.*
    FROM signal_engine_state ses
    JOIN asset a
      ON a.asset_id = ses.asset_id
    WHERE ses.venue = %s
      AND ses.interval_code = %s
      AND ses.signal_ts_utc = %s
      AND a.is_enabled = 1
    ORDER BY ses.asset_id
    """

    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                venue,
                interval,
                snapshot_ts_utc.replace(tzinfo=None),
            ),
        )
        rows = cur.fetchall()

    out: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            out.append(row)
        else:
            raise TypeError("Expected dict rows from database cursor")

    return snapshot_ts_utc, out


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


def build_advice_rows(signal_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
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

    return advice_rows


def run(*, interval: str, venue: str) -> int:
    conn = get_db_connection()

    try:
        snapshot_ts_utc, signal_rows = fetch_signal_rows(
            conn,
            venue=venue,
            interval=interval,
        )

        if not signal_rows:
            print(
                f"[WARN] no latest signal snapshot found "
                f"engine={ENGINE_NAME} version={ENGINE_VERSION} "
                f"venue={venue} interval={interval}"
            )
            return 0

        advice_rows = build_advice_rows(signal_rows)
        written = upsert_advice_rows(conn, advice_rows)

        print(
            f"[DONE] advice rows={written} "
            f"engine={ENGINE_NAME} version={ENGINE_VERSION} "
            f"venue={venue} interval={interval} "
            f"snapshot_ts_utc={snapshot_ts_utc.isoformat(sep=' ') if snapshot_ts_utc else ''}"
        )
        return written

    finally:
        conn.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run latest-only advice engine.")
    parser.add_argument("--interval", required=True)
    parser.add_argument("--venue", default="bitvavo")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run(interval=args.interval, venue=args.venue)
