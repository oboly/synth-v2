from __future__ import annotations

import argparse
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from src.common.db import get_db_connection


RANKING_VERSION = "v2"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Synth ranking / rotation engine from advice_state + signal_engine_state"
    )
    parser.add_argument("--interval", default="4h", help="Interval to rank, e.g. 1h / 4h / 1d")
    parser.add_argument("--venue", default="bitvavo")
    return parser.parse_args()


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    return Decimal(str(value))


def fetch_latest_snapshot_ts(conn, *, venue: str, interval_code: str) -> datetime | None:
    min_snapshot_rows = {
        "1h": 20,
        "4h": 20,
        "1d": 20,
    }.get(interval_code, 20)

    sql = """
    SELECT
        s.signal_ts_utc AS snapshot_ts_utc,
        COUNT(*) AS snapshot_rows
    FROM signal_engine_state s
    JOIN asset a
      ON a.asset_id = s.asset_id
    WHERE s.venue = %s
      AND s.interval_code = %s
      AND a.is_enabled = 1
    GROUP BY s.signal_ts_utc
    HAVING COUNT(*) >= %s
    ORDER BY s.signal_ts_utc DESC
    LIMIT 1
    """

    with conn.cursor() as cur:
        cur.execute(sql, (venue, interval_code, min_snapshot_rows))
        row = cur.fetchone()

    if not row:
        return None

    snapshot_ts = row["snapshot_ts_utc"] if isinstance(row, dict) else row[0]
    if snapshot_ts is None:
        return None

    if snapshot_ts.tzinfo is None:
        return snapshot_ts.replace(tzinfo=UTC)

    return snapshot_ts.astimezone(UTC)


def fetch_ranking_inputs(
    conn,
    *,
    venue: str,
    interval_code: str,
    snapshot_ts_utc: datetime,
) -> list[dict[str, Any]]:
    sql = """
    SELECT
        a.asset_id,
        a.symbol,
        a.asset_class,
        a.sector,

        s.venue,
        s.interval_code,
        s.signal_ts_utc,

        s.trend_signal,
        s.volume_signal,
        s.phase_signal,
        s.compass_signal,
        s.rotation_signal,
        s.relative_signal,
        s.setup_signal,
        s.risk_signal,

        s.signal_confidence,
        s.trend_score,
        s.volume_score,
        s.phase_score,
        s.compass_score,
        s.rotation_score,
        s.relative_score,
        s.setup_score,
        s.risk_score,
        s.rotation_trigger_score,
        s.expansion_delay_score,

        s.expansion_position_score,
        s.pullback_quality_score,
        s.late_trend_flag,

        adv.asof_ts_utc,
        adv.regime_label,
        adv.time_horizon_hint,
        adv.advice_state,
        adv.regime_fit_score,
        adv.opportunity_score,
        adv.risk_score AS advice_risk_score,
        adv.priority_rank,
        adv.summary_text

    FROM signal_engine_state s
    JOIN asset a
      ON a.asset_id = s.asset_id
    LEFT JOIN advice_state adv
      ON adv.asset_id = s.asset_id
     AND adv.venue = s.venue
     AND adv.interval_code = s.interval_code
     AND adv.asof_ts_utc = s.signal_ts_utc
    WHERE s.venue = %s
      AND s.interval_code = %s
      AND s.signal_ts_utc = %s
      AND a.is_enabled = 1
    ORDER BY a.symbol
    """

    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                venue,
                interval_code,
                snapshot_ts_utc.replace(tzinfo=None),
            ),
        )
        rows = cur.fetchall()

    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("Expected dict rows from database cursor")
        out.append(row)

    return out


def compute_relative_strength_score(row: dict[str, Any]) -> Decimal:
    relative_score = _to_decimal(row.get("relative_score"), "0")
    trend_score = _to_decimal(row.get("trend_score"), "0")
    rotation_score = _to_decimal(row.get("rotation_score"), "0")

    score = (
        Decimal("0.50") * relative_score
        + Decimal("0.30") * trend_score
        + Decimal("0.20") * rotation_score
    )
    return score.quantize(Decimal("0.000001"))


def compute_trade_quality_score(row: dict[str, Any]) -> Decimal:
    context_score = _to_decimal(row.get("opportunity_score"), "0")
    pullback_quality_score = _to_decimal(row.get("pullback_quality_score"), "0")
    expansion_position_score = _to_decimal(row.get("expansion_position_score"), "0")
    signal_confidence_score = _to_decimal(row.get("signal_confidence"), "0")
    relative_strength_score = compute_relative_strength_score(row)

    score = (
        Decimal("0.35") * context_score
        + Decimal("0.20") * pullback_quality_score
        + Decimal("0.20") * expansion_position_score
        + Decimal("0.15") * signal_confidence_score
        + Decimal("0.10") * relative_strength_score
    )
    return score.quantize(Decimal("0.000001"))


def classify_code(row: dict[str, Any], trade_quality_score: Decimal) -> str:
    trend_signal = str(row.get("trend_signal") or "")
    phase_signal = str(row.get("phase_signal") or "")
    risk_signal = str(row.get("risk_signal") or "")
    advice_state = str(row.get("advice_state") or "")
    asset_class = str(row.get("asset_class") or "")
    late_trend_flag = int(row.get("late_trend_flag") or 0)

    signal_confidence = _to_decimal(row.get("signal_confidence"), "0")
    relative_strength_score = compute_relative_strength_score(row)
    pullback_quality_score = _to_decimal(row.get("pullback_quality_score"), "0")

    if risk_signal in {"RISK_HIGH", "RISK_CONFLICTING_SIGNALS"}:
        return "NO_TRADE"

    if trend_signal == "TREND_SIDEWAYS":
        return "RANGE_TRADER"

    if (
        trend_signal == "TREND_UP_STRONG"
        and phase_signal == "PHASE_EXPANSION_COHERENT"
        and late_trend_flag == 0
        and signal_confidence >= Decimal("0.60")
        and relative_strength_score >= Decimal("0.55")
        and trade_quality_score >= Decimal("0.68")
    ):
        return "LEADER"

    if (
        late_trend_flag == 1
        and pullback_quality_score >= Decimal("0.55")
        and trade_quality_score >= Decimal("0.50")
    ):
        return "PULLBACK_WATCH"

    if (
        advice_state in {"TRIGGERED", "ARM", "BUILD"}
        and trend_signal in {"TREND_UP_STRONG", "TREND_UP_WEAK", "TREND_RECOVERING"}
        and trade_quality_score >= Decimal("0.48")
    ):
        return "CONTINUATION_CANDIDATE"

    if asset_class == "MEME" and trade_quality_score >= Decimal("0.50"):
        return "SPECULATIVE_HIGH_BETA"

    return "NO_TRADE"


def classify_rotation_bucket(
    row: dict[str, Any],
    trade_quality_score: Decimal,
    classification_code: str,
) -> str:
    risk_signal = str(row.get("risk_signal") or "")

    if risk_signal in {"RISK_HIGH", "RISK_CONFLICTING_SIGNALS"}:
        return "ROTATION_EXIT"

    if classification_code == "LEADER":
        return "ROTATION_LEADER"

    if classification_code == "CONTINUATION_CANDIDATE":
        return "ROTATION_FOLLOWER"

    if classification_code == "PULLBACK_WATCH":
        return "ROTATION_EARLY"

    if classification_code in {"RANGE_TRADER", "SPECULATIVE_HIGH_BETA"}:
        return "ROTATION_NEUTRAL"

    if trade_quality_score >= Decimal("0.35"):
        return "ROTATION_WEAK"

    return "ROTATION_EXIT"


def classify_sleeve_fit(rotation_bucket: str, classification_code: str) -> str:
    if rotation_bucket == "ROTATION_LEADER":
        return "CORE_STRUCTURAL"

    if rotation_bucket in {"ROTATION_FOLLOWER", "ROTATION_EARLY"}:
        return "SWING_STRUCTURAL"

    if classification_code in {"RANGE_TRADER", "SPECULATIVE_HIGH_BETA"}:
        return "TACTICAL_PULSE"

    return "EXPERIMENTAL"


def build_notes(row: dict[str, Any], classification_code: str, rotation_bucket: str) -> str:
    symbol = str(row.get("symbol") or "?")
    regime = str(row.get("regime_label") or "UNKNOWN")
    advice = str(row.get("advice_state") or "UNKNOWN")
    return (
        f"{symbol}; class={classification_code}; bucket={rotation_bucket}; "
        f"regime={regime}; advice={advice}"
    )[:255]


def upsert_ranking_rows(conn, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0

    sql = """
    INSERT INTO ranking_state (
        asset_id,
        venue,
        interval_code,
        asof_ts_utc,
        trade_quality_score,
        relative_strength_score,
        context_score,
        pullback_quality_score,
        expansion_position_score,
        signal_confidence_score,
        rotation_bucket,
        classification_code,
        sleeve_fit_code,
        final_rank,
        ranking_version,
        notes
    ) VALUES (
        %(asset_id)s,
        %(venue)s,
        %(interval_code)s,
        %(asof_ts_utc)s,
        %(trade_quality_score)s,
        %(relative_strength_score)s,
        %(context_score)s,
        %(pullback_quality_score)s,
        %(expansion_position_score)s,
        %(signal_confidence_score)s,
        %(rotation_bucket)s,
        %(classification_code)s,
        %(sleeve_fit_code)s,
        %(final_rank)s,
        %(ranking_version)s,
        %(notes)s
    )
    ON DUPLICATE KEY UPDATE
        trade_quality_score = VALUES(trade_quality_score),
        relative_strength_score = VALUES(relative_strength_score),
        context_score = VALUES(context_score),
        pullback_quality_score = VALUES(pullback_quality_score),
        expansion_position_score = VALUES(expansion_position_score),
        signal_confidence_score = VALUES(signal_confidence_score),
        rotation_bucket = VALUES(rotation_bucket),
        classification_code = VALUES(classification_code),
        sleeve_fit_code = VALUES(sleeve_fit_code),
        final_rank = VALUES(final_rank),
        notes = VALUES(notes)
    """

    with conn.cursor() as cur:
        cur.executemany(sql, rows)

    conn.commit()
    return len(rows)


def run(interval_code: str, venue: str) -> int:
    conn = get_db_connection()

    try:
        snapshot_ts_utc = fetch_latest_snapshot_ts(
            conn,
            venue=venue,
            interval_code=interval_code,
        )

        if snapshot_ts_utc is None:
            print(f"[WARN] no signal snapshot found for interval={interval_code}")
            return 0

        input_rows = fetch_ranking_inputs(
            conn,
            venue=venue,
            interval_code=interval_code,
            snapshot_ts_utc=snapshot_ts_utc,
        )

        if not input_rows:
            print(
                f"[WARN] no ranking inputs found interval={interval_code} "
                f"snapshot_ts_utc={snapshot_ts_utc}"
            )
            return 0

        ranking_rows: list[dict[str, Any]] = []

        for row in input_rows:
            trade_quality_score = compute_trade_quality_score(row)
            relative_strength_score = compute_relative_strength_score(row)
            classification_code = classify_code(row, trade_quality_score)
            rotation_bucket = classify_rotation_bucket(row, trade_quality_score, classification_code)
            sleeve_fit_code = classify_sleeve_fit(rotation_bucket, classification_code)

            ranking_rows.append(
                {
                    "asset_id": int(row["asset_id"]),
                    "venue": str(row["venue"]),
                    "interval_code": str(row["interval_code"]),
                    "asof_ts_utc": snapshot_ts_utc.replace(tzinfo=None),
                    "trade_quality_score": str(trade_quality_score),
                    "relative_strength_score": str(relative_strength_score),
                    "context_score": str(_to_decimal(row.get("opportunity_score"), "0")),
                    "pullback_quality_score": str(_to_decimal(row.get("pullback_quality_score"), "0")),
                    "expansion_position_score": str(_to_decimal(row.get("expansion_position_score"), "0")),
                    "signal_confidence_score": str(_to_decimal(row.get("signal_confidence"), "0")),
                    "rotation_bucket": rotation_bucket,
                    "classification_code": classification_code,
                    "sleeve_fit_code": sleeve_fit_code,
                    "final_rank": None,
                    "ranking_version": RANKING_VERSION,
                    "notes": build_notes(row, classification_code, rotation_bucket),
                }
            )

        rank_bias = {
            "LEADER": 4,
            "CONTINUATION_CANDIDATE": 3,
            "PULLBACK_WATCH": 2,
            "SPECULATIVE_HIGH_BETA": 1,
            "RANGE_TRADER": 0,
            "NO_TRADE": -1,
        }

        ranking_rows.sort(
            key=lambda r: (
                rank_bias.get(r["classification_code"], -9),
                Decimal(r["trade_quality_score"]),
                Decimal(r["relative_strength_score"]),
                Decimal(r["context_score"]),
            ),
            reverse=True,
        )

        for idx, row in enumerate(ranking_rows, start=1):
            row["final_rank"] = idx

        written = upsert_ranking_rows(conn, ranking_rows)
        print(
            f"[DONE] ranking rows={written} interval={interval_code} "
            f"snapshot_ts_utc={snapshot_ts_utc.isoformat()} version={RANKING_VERSION}"
        )
        return written

    finally:
        conn.close()


if __name__ == "__main__":
    args = parse_args()
    raise SystemExit(run(interval_code=args.interval, venue=args.venue))
