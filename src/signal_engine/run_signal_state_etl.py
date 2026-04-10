from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from src.common.db import get_db_connection
from src.engine.write_signal_engine_state import (
    SignalEngineStateRow,
    upsert_signal_engine_state,
)
from src.signal_engine.signal_engine import (
    SignalEngineInput,
    evaluate_signal_engine,
)


DEFAULT_VENUE = "bitvavo"
DEFAULT_INTERVALS = ("1h", "4h", "1d")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Synth Signal Engine from feat_candle into signal_engine_state"
    )
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--interval", default=None, help="Optional single interval_code filter")
    parser.add_argument("--asset-id", type=int, default=None, help="Optional single asset_id filter")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _ensure_utc(dt: datetime) -> datetime:
    if not isinstance(dt, datetime):
        raise TypeError("Expected datetime")
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def fetch_snapshot_ts(
    conn,
    *,
    venue: str,
    interval_code: str,
) -> datetime | None:
    sql = """
    SELECT MAX(fc.close_ts_utc) AS snapshot_ts_utc
    FROM feat_candle fc
    JOIN asset a
      ON a.asset_id = fc.asset_id
    WHERE fc.venue = %s
      AND fc.interval_code = %s
      AND a.is_enabled = 1
    """

    with conn.cursor() as cur:
        cur.execute(sql, (venue, interval_code))
        row = cur.fetchone()

    if not row:
        return None

    snapshot_ts = row["snapshot_ts_utc"] if isinstance(row, dict) else row[0]
    if snapshot_ts is None:
        return None

    return _ensure_utc(snapshot_ts)


def fetch_snapshot_feat_rows(
    conn,
    *,
    venue: str,
    interval_code: str,
    snapshot_ts_utc: datetime,
    asset_id: int | None,
) -> list[dict[str, Any]]:
    where = [
        "fc.venue = %s",
        "fc.interval_code = %s",
        "fc.close_ts_utc = %s",
        "a.is_enabled = 1",
    ]
    params: list[Any] = [
        venue,
        interval_code,
        snapshot_ts_utc.replace(tzinfo=None),
    ]

    if asset_id is not None:
        where.append("fc.asset_id = %s")
        params.append(asset_id)

    where_sql = " AND ".join(where)

    sql = f"""
    SELECT
        fc.candle_feat_id,
        fc.candle_id,
        fc.asset_id,
        fc.venue,
        fc.interval_code,
        fc.close_ts_utc,

        fc.ema_20,
        fc.ema_50,
        fc.rsi_14,
        fc.atr_14,
        fc.volume_ratio_20,
        fc.volume_zscore_20,
        fc.obv,
        fc.obv_slope_5,
        fc.dollar_volume_ratio_20,
        fc.price_vs_ema20,
        fc.price_vs_ema50,
        fc.atr_pct,
        fc.ema_spread,
        fc.ema_spread_pct
    FROM feat_candle fc
    JOIN asset a
      ON a.asset_id = fc.asset_id
    WHERE {where_sql}
    ORDER BY fc.asset_id, fc.interval_code
    """

    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    out: list[dict[str, Any]] = []

    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("Expected dict cursor rows from database connection")

        close_ts = row["close_ts_utc"]
        row["close_ts_utc"] = _ensure_utc(close_ts)
        out.append(row)

    return out


def to_decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def classify_trend_signal(row: dict[str, Any]) -> str:
    price_vs_ema20 = float(row["price_vs_ema20"]) if row["price_vs_ema20"] is not None else 0.0
    price_vs_ema50 = float(row["price_vs_ema50"]) if row["price_vs_ema50"] is not None else 0.0
    ema_spread_pct = float(row["ema_spread_pct"]) if row["ema_spread_pct"] is not None else 0.0

    if price_vs_ema20 > 0 and price_vs_ema50 > 0 and ema_spread_pct > 0:
        if ema_spread_pct > 0.01:
            return "TREND_UP_STRONG"
        return "TREND_UP_WEAK"

    if price_vs_ema20 < 0 and price_vs_ema50 < 0 and ema_spread_pct < 0:
        if ema_spread_pct < -0.01:
            return "TREND_DOWN_STRONG"
        return "TREND_DOWN_WEAK"

    if price_vs_ema20 > 0 and price_vs_ema50 < 0:
        return "TREND_RECOVERING"

    return "TREND_SIDEWAYS"


def classify_volume_signal(row: dict[str, Any]) -> str:
    volume_ratio = float(row["volume_ratio_20"]) if row["volume_ratio_20"] is not None else 1.0
    volume_z = float(row["volume_zscore_20"]) if row["volume_zscore_20"] is not None else 0.0
    obv_slope = float(row["obv_slope_5"]) if row["obv_slope_5"] is not None else 0.0

    if volume_ratio >= 1.8 and volume_z >= 1.5 and obv_slope > 0:
        return "VOLUME_CONFIRMED_BREAKOUT"

    if volume_ratio >= 1.3 and obv_slope > 0:
        return "VOLUME_ACCUMULATION"

    if volume_ratio >= 1.2 and obv_slope <= 0:
        return "VOLUME_WEAK_BREAKOUT"

    if volume_ratio < 0.9 and obv_slope < 0:
        return "VOLUME_DISTRIBUTION"

    return "VOLUME_NEUTRAL"


def classify_phase_signal(row: dict[str, Any]) -> str:
    atr_pct = float(row["atr_pct"]) if row["atr_pct"] is not None else 0.0
    ema_spread_pct = float(row["ema_spread_pct"]) if row["ema_spread_pct"] is not None else 0.0
    price_vs_ema20 = float(row["price_vs_ema20"]) if row["price_vs_ema20"] is not None else 0.0

    if abs(ema_spread_pct) < 0.005 and atr_pct < 0.03:
        return "PHASE_COMPRESSION"

    if ema_spread_pct > 0.01 and price_vs_ema20 > 0:
        return "PHASE_EXPANSION_COHERENT"

    if atr_pct > 0.08 and abs(ema_spread_pct) < 0.005:
        return "PHASE_REACTIVE"

    if abs(price_vs_ema20) < 0.01:
        return "PHASE_INTEGRATION"

    return "PHASE_RESET"


def classify_compass_signal(row: dict[str, Any]) -> str:
    phase_signal = classify_phase_signal(row)
    volume_signal = classify_volume_signal(row)

    if phase_signal == "PHASE_EXPANSION_COHERENT" and volume_signal in {
        "VOLUME_ACCUMULATION",
        "VOLUME_CONFIRMED_BREAKOUT",
    }:
        return "COMPASS_EXPANSION_SUPPORT"

    if phase_signal == "PHASE_INTEGRATION":
        return "COMPASS_PATIENCE_MODE"

    if phase_signal == "PHASE_REACTIVE":
        return "COMPASS_NOISE_WARNING"

    return "COMPASS_ALIGNMENT_WEAK"


def classify_rotation_signal(row: dict[str, Any]) -> str:
    trend_signal = classify_trend_signal(row)
    volume_signal = classify_volume_signal(row)
    price_vs_ema20 = float(row["price_vs_ema20"]) if row["price_vs_ema20"] is not None else 0.0

    if trend_signal in {"TREND_UP_STRONG", "TREND_RECOVERING"} and volume_signal in {
        "VOLUME_ACCUMULATION",
        "VOLUME_CONFIRMED_BREAKOUT",
    }:
        return "ROTATION_READY"

    if trend_signal == "TREND_DOWN_WEAK" and price_vs_ema20 > -0.02:
        return "ROTATION_DELAYED"

    return "ROTATION_NONE"


def classify_relative_signal(row: dict[str, Any]) -> str:
    price_vs_ema50 = float(row["price_vs_ema50"]) if row["price_vs_ema50"] is not None else 0.0
    ema_spread_pct = float(row["ema_spread_pct"]) if row["ema_spread_pct"] is not None else 0.0

    if price_vs_ema50 > 0.03 and ema_spread_pct > 0.01:
        return "RELSTR_LEADING"

    if price_vs_ema50 > 0:
        return "RELSTR_IMPROVING"

    if price_vs_ema50 > -0.02:
        return "RELSTR_STABLE"

    return "RELSTR_LAGGING"


def classify_risk_signal(row: dict[str, Any]) -> str:
    atr_pct = float(row["atr_pct"]) if row["atr_pct"] is not None else 0.0
    volume_signal = classify_volume_signal(row)
    trend_signal = classify_trend_signal(row)

    if atr_pct > 0.12:
        return "RISK_HIGH"

    if volume_signal == "VOLUME_DISTRIBUTION":
        return "RISK_CONFLICTING_SIGNALS"

    if trend_signal in {"TREND_RECOVERING", "TREND_DOWN_WEAK"}:
        return "RISK_WAIT_CONFIRMATION"

    return "RISK_OK"


def classify_setup_signal(row: dict[str, Any]) -> str:
    trend_signal = classify_trend_signal(row)
    volume_signal = classify_volume_signal(row)
    relative_signal = classify_relative_signal(row)
    risk_signal = classify_risk_signal(row)

    if (
        trend_signal in {"TREND_UP_STRONG", "TREND_RECOVERING"}
        and volume_signal in {"VOLUME_ACCUMULATION", "VOLUME_CONFIRMED_BREAKOUT"}
        and relative_signal in {"RELSTR_IMPROVING", "RELSTR_LEADING"}
    ):
        return "SETUP_ARMED"

    if (
        trend_signal in {"TREND_DOWN_WEAK", "TREND_RECOVERING", "TREND_UP_WEAK"}
        and relative_signal in {"RELSTR_IMPROVING", "RELSTR_STABLE"}
        and risk_signal in {"RISK_OK", "RISK_WAIT_CONFIRMATION"}
    ):
        return "SETUP_BUILDING"

    return "SETUP_WATCH_ONLY"


def infer_alt_market_phase(interval_code: str) -> str:
    if interval_code == "1d":
        return "LEADER_PHASE"
    if interval_code == "4h":
        return "SECTOR_EXPANSION"
    return "SECTOR_EXPANSION"


def compute_expansion_position_score(row: dict[str, Any]) -> Decimal:
    ema_spread_pct = float(row["ema_spread_pct"]) if row["ema_spread_pct"] is not None else 0.0
    price_vs_ema20 = float(row["price_vs_ema20"]) if row["price_vs_ema20"] is not None else 0.0
    atr_pct = float(row["atr_pct"]) if row["atr_pct"] is not None else 0.0

    score = (
        0.50 * _clamp(ema_spread_pct / 0.03)
        + 0.30 * _clamp(price_vs_ema20 / 0.05)
        + 0.20 * _clamp(atr_pct / 0.08)
    )
    return Decimal(str(round(_clamp(score), 6)))


def compute_pullback_quality_score(row: dict[str, Any]) -> Decimal:
    price_vs_ema20 = float(row["price_vs_ema20"]) if row["price_vs_ema20"] is not None else 0.0
    price_vs_ema50 = float(row["price_vs_ema50"]) if row["price_vs_ema50"] is not None else 0.0
    volume_ratio = float(row["volume_ratio_20"]) if row["volume_ratio_20"] is not None else 1.0
    rsi_14 = float(row["rsi_14"]) if row["rsi_14"] is not None else 50.0

    near_ema20_score = 1.0 - _clamp(abs(price_vs_ema20) / 0.05)
    above_ema50_score = _clamp((price_vs_ema50 + 0.03) / 0.06)
    supportive_volume_score = _clamp(volume_ratio / 1.5)
    neutral_rsi_score = 1.0 - _clamp(abs(rsi_14 - 55.0) / 25.0)

    score = (
        0.35 * near_ema20_score
        + 0.30 * above_ema50_score
        + 0.20 * supportive_volume_score
        + 0.15 * neutral_rsi_score
    )
    return Decimal(str(round(_clamp(score), 6)))


def compute_late_trend_flag(row: dict[str, Any]) -> int:
    trend_signal = classify_trend_signal(row)
    phase_signal = classify_phase_signal(row)
    setup_signal = classify_setup_signal(row)
    expansion_position_score = float(compute_expansion_position_score(row))

    if (
        trend_signal == "TREND_UP_STRONG"
        and phase_signal == "PHASE_EXPANSION_COHERENT"
        and setup_signal == "SETUP_WATCH_ONLY"
    ):
        return 1

    if trend_signal == "TREND_UP_STRONG" and expansion_position_score >= 0.70:
        return 1

    return 0


def build_signal_engine_input(row: dict[str, Any]) -> SignalEngineInput:
    signal_ts = _ensure_utc(row["close_ts_utc"])
    signal_ts_utc = signal_ts.isoformat().replace("+00:00", "Z")

    return SignalEngineInput(
        asset_id=int(row["asset_id"]),
        ts_utc=signal_ts_utc,
        interval_code=str(row["interval_code"]),
        trend_signal=classify_trend_signal(row),
        volume_signal=classify_volume_signal(row),
        phase_signal=classify_phase_signal(row),
        compass_signal=classify_compass_signal(row),
        rotation_signal=classify_rotation_signal(row),
        relative_signal=classify_relative_signal(row),
        setup_signal=classify_setup_signal(row),
        risk_signal=classify_risk_signal(row),
        alt_market_phase=infer_alt_market_phase(str(row["interval_code"])),
    )


def main() -> int:
    args = parse_args()
    intervals = (args.interval,) if args.interval else DEFAULT_INTERVALS

    conn = get_db_connection()

    try:
        total_rows = 0

        for interval_code in intervals:
            snapshot_ts_utc = fetch_snapshot_ts(
                conn,
                venue=args.venue,
                interval_code=interval_code,
            )

            if snapshot_ts_utc is None:
                print(f"[WARN] interval={interval_code} snapshot_ts_utc=None")
                continue

            feat_rows = fetch_snapshot_feat_rows(
                conn,
                venue=args.venue,
                interval_code=interval_code,
                snapshot_ts_utc=snapshot_ts_utc,
                asset_id=args.asset_id,
            )

            print(
                f"[INFO] interval={interval_code} snapshot_ts_utc={snapshot_ts_utc.isoformat()} "
                f"feat_rows={len(feat_rows)}"
            )

            out_rows: list[SignalEngineStateRow] = []

            for row in feat_rows:
                engine_input = build_signal_engine_input(row)
                engine_output = evaluate_signal_engine(engine_input)

                signal_ts = datetime.fromisoformat(engine_output.ts_utc.replace("Z", "+00:00"))

                expansion_position_score = compute_expansion_position_score(row)
                pullback_quality_score = compute_pullback_quality_score(row)
                late_trend_flag = compute_late_trend_flag(row)

                out_rows.append(
                    SignalEngineStateRow(
                        asset_id=engine_output.asset_id,
                        venue=str(row["venue"]),
                        interval_code=str(row["interval_code"]),
                        signal_ts_utc=signal_ts,
                        trend_signal=engine_output.trend_signal,
                        volume_signal=engine_output.volume_signal,
                        phase_signal=engine_output.phase_signal,
                        compass_signal=engine_output.compass_signal,
                        rotation_signal=engine_output.rotation_signal,
                        relative_signal=engine_output.relative_signal,
                        setup_signal=engine_output.setup_signal,
                        risk_signal=engine_output.risk_signal,
                        expansion_delay_state=1 if engine_output.expansion_delay_state else 0,
                        expansion_delay_score=to_decimal_or_none(engine_output.expansion_delay_score),
                        rotation_trigger_state=1 if engine_output.rotation_trigger_state else 0,
                        rotation_trigger_score=to_decimal_or_none(engine_output.rotation_trigger_score),
                        trend_score=to_decimal_or_none(engine_output.trend_score),
                        volume_score=to_decimal_or_none(engine_output.volume_score),
                        phase_score=to_decimal_or_none(engine_output.phase_score),
                        compass_score=to_decimal_or_none(engine_output.compass_score),
                        rotation_score=to_decimal_or_none(engine_output.rotation_score),
                        relative_score=to_decimal_or_none(engine_output.relative_score),
                        setup_score=to_decimal_or_none(engine_output.setup_score),
                        risk_score=to_decimal_or_none(engine_output.risk_score),
                        expansion_position_score=expansion_position_score,
                        pullback_quality_score=pullback_quality_score,
                        late_trend_flag=late_trend_flag,
                        signal_confidence=to_decimal_or_none(engine_output.signal_confidence),
                        reason_code=engine_output.reason_code,
                        reason_text=engine_output.reason_text,
                        created_ts_utc=datetime.now(UTC),
                    )
                )

            if args.dry_run:
                for out_row in out_rows[:10]:
                    print(asdict(out_row))
            else:
                written = upsert_signal_engine_state(conn, out_rows)
                total_rows += written
                print(f"[WRITE] interval={interval_code} rows={written}")

        print(f"[DONE] total_rows={total_rows}")
        return 0

    except Exception as exc:
        import traceback

        conn.rollback()
        traceback.print_exc()
        print(f"[ERROR] {exc}")
        return 1

    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
