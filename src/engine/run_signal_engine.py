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
    parser.add_argument(
        "--limit-per-asset",
        type=int,
        default=1,
        help="How many latest feat rows per asset/interval to evaluate (default: 1)",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def fetch_latest_feat_rows(
    conn,
    *,
    venue: str,
    interval_code: str | None,
    asset_id: int | None,
    limit_per_asset: int,
) -> list[dict[str, Any]]:
    where = ["fc.venue = %s", "a.is_enabled = 1"]
    params: list[Any] = [venue]

    if interval_code:
        where.append("fc.interval_code = %s")
        params.append(interval_code)

    if asset_id is not None:
        where.append("fc.asset_id = %s")
        params.append(asset_id)

    where_sql = " AND ".join(where)

    sql = f"""
    SELECT *
    FROM (
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
            fc.ema_spread_pct,

            ROW_NUMBER() OVER (
                PARTITION BY fc.asset_id, fc.venue, fc.interval_code
                ORDER BY fc.close_ts_utc DESC
            ) AS rn
        FROM feat_candle fc
        JOIN asset a
          ON a.asset_id = fc.asset_id
        WHERE {where_sql}
    ) q
    WHERE q.rn <= %s
    ORDER BY q.asset_id, q.interval_code, q.close_ts_utc DESC
    """
    params.append(limit_per_asset)

    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    out: list[dict[str, Any]] = []

    for row in rows:
        if isinstance(row, dict):
            out.append(row)
        else:
            raise TypeError("Expected dict cursor rows from database connection")

    return out


def to_decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


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

    # Tuning:
    # allow BUILDING earlier when structure is improving,
    # even if volume is not fully confirmed yet.
    if (
        trend_signal in {"TREND_DOWN_WEAK", "TREND_RECOVERING", "TREND_UP_WEAK"}
        and relative_signal in {"RELSTR_IMPROVING", "RELSTR_STABLE"}
        and risk_signal in {"RISK_OK", "RISK_WAIT_CONFIRMATION"}
    ):
        return "SETUP_BUILDING"

    return "SETUP_WATCH_ONLY"


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


def infer_alt_market_phase(interval_code: str) -> str:
    if interval_code == "1d":
        return "LEADER_PHASE"
    if interval_code == "4h":
        return "SECTOR_EXPANSION"
    return "SECTOR_EXPANSION"


def build_signal_engine_input(row: dict[str, Any]) -> SignalEngineInput:
    signal_ts = row["close_ts_utc"]
    if not isinstance(signal_ts, datetime):
        raise TypeError("close_ts_utc must be a datetime")

    signal_ts_utc = signal_ts.astimezone(UTC).isoformat().replace("+00:00", "Z")

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
            feat_rows = fetch_latest_feat_rows(
                conn,
                venue=args.venue,
                interval_code=interval_code,
                asset_id=args.asset_id,
                limit_per_asset=args.limit_per_asset,
            )

            print(f"[INFO] interval={interval_code} feat_rows={len(feat_rows)}")

            out_rows: list[SignalEngineStateRow] = []

            for row in feat_rows:
                engine_input = build_signal_engine_input(row)
                engine_output = evaluate_signal_engine(engine_input)

                signal_ts = datetime.fromisoformat(engine_output.ts_utc.replace("Z", "+00:00"))

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
