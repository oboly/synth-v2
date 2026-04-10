from __future__ import annotations

import argparse
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any


from src.common.db import get_db_connection


ENGINE_NAME = "structure_state_engine"
ENGINE_VERSION = "1.1"
DEFAULT_VENUE = "bitvavo"
DEFAULT_INTERVALS = ("1h", "4h", "1d")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run timeframe-aware structure state engine from feat_candle"
    )
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--interval", action="append", default=None)
    parser.add_argument("--asset-id", type=int, default=None)
    return parser.parse_args()


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _to_decimal_str(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return str(value)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def fetch_latest_feat_rows(
    conn,
    *,
    venue: str,
    interval_code: str,
    asset_id: int | None,
) -> list[dict[str, Any]]:
    where = [
        "fc.venue = %s",
        "fc.interval_code = %s",
        "a.is_enabled = 1",
    ]
    params: list[Any] = [venue, interval_code]

    if asset_id is not None:
        where.append("fc.asset_id = %s")
        params.append(asset_id)

    where_sql = " AND ".join(where)

    sql = f"""
    SELECT *
    FROM (
        SELECT
            fc.asset_id,
            fc.venue,
            fc.interval_code,
            fc.close_ts_utc,
            fc.price_vs_ema20,
            fc.price_vs_ema50,
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
    WHERE q.rn <= 2
    ORDER BY q.asset_id, q.rn
    """

    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("Expected dict rows from database cursor")
        row["close_ts_utc"] = _ensure_utc(row["close_ts_utc"])
        out.append(row)

    return out


def group_current_previous(
    rows: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], dict[str, Any] | None]]:
    grouped: dict[tuple[int, str, str], list[dict[str, Any]]] = {}

    for row in rows:
        key = (
            int(row["asset_id"]),
            str(row["venue"]),
            str(row["interval_code"]),
        )
        grouped.setdefault(key, []).append(row)

    out: list[tuple[dict[str, Any], dict[str, Any] | None]] = []

    for _, bucket in grouped.items():
        bucket_sorted = sorted(
            bucket,
            key=lambda r: r["close_ts_utc"],
            reverse=True,
        )
        current_row = bucket_sorted[0]
        previous_row = bucket_sorted[1] if len(bucket_sorted) > 1 else None
        out.append((current_row, previous_row))

    out.sort(key=lambda pair: int(pair[0]["asset_id"]))
    return out


def compute_trend_state(row: dict[str, Any]) -> tuple[str, Decimal]:
    p20 = float(row["price_vs_ema20"]) if row["price_vs_ema20"] is not None else 0.0
    p50 = float(row["price_vs_ema50"]) if row["price_vs_ema50"] is not None else 0.0
    spread = float(row["ema_spread_pct"]) if row["ema_spread_pct"] is not None else 0.0

    bullish_score = (
        0.40 * _clamp((spread + 0.02) / 0.04)
        + 0.30 * _clamp((p20 + 0.03) / 0.06)
        + 0.30 * _clamp((p50 + 0.05) / 0.10)
    )

    if p20 > 0 and p50 > 0 and spread >= 0.01:
        return "UPTREND_STRONG", Decimal(str(round(bullish_score, 6)))

    if p50 > 0:
        return "UPTREND_WEAK", Decimal(str(round(bullish_score, 6)))

    if abs(p20) < 0.01 and abs(spread) < 0.005:
        return "RANGE", Decimal(str(round(bullish_score, 6)))

    if p20 < 0 and p50 < 0 and spread <= -0.01:
        return "DOWNTREND_STRONG", Decimal(str(round(1.0 - bullish_score, 6)))

    if p50 < 0:
        return "DOWNTREND_WEAK", Decimal(str(round(1.0 - bullish_score, 6)))

    return "RANGE", Decimal(str(round(bullish_score, 6)))


def compute_pullback_state(row: dict[str, Any], trend_state: str) -> tuple[str, Decimal]:
    p20 = float(row["price_vs_ema20"]) if row["price_vs_ema20"] is not None else 0.0
    p50 = float(row["price_vs_ema50"]) if row["price_vs_ema50"] is not None else 0.0

    if trend_state not in {"UPTREND_STRONG", "UPTREND_WEAK"}:
        if trend_state in {"DOWNTREND_WEAK", "DOWNTREND_STRONG"}:
            return "POTENTIAL_REVERSAL", Decimal("0.000000")
        return "NO_PULLBACK", Decimal("0.000000")

    if p20 >= 0:
        score = Decimal(str(round(_clamp(1.0 - min(abs(p20) / 0.05, 1.0)), 6)))
        return "NO_PULLBACK", score

    if p20 < 0 and p50 >= 0:
        depth = abs(p20)
        score = Decimal(
            str(
                round(
                    0.70 + 0.30 * _clamp(1.0 - abs(depth - 0.02) / 0.03),
                    6,
                )
            )
        )
        return "HEALTHY_PULLBACK", score

    if p50 < 0:
        depth = abs(p50)
        score = Decimal(str(round(0.20 + 0.40 * _clamp(1.0 - depth / 0.08), 6)))
        return "DEEP_PULLBACK", score

    return "POTENTIAL_REVERSAL", Decimal("0.000000")


def compute_reclaim_state(
    current_row: dict[str, Any],
    previous_row: dict[str, Any] | None,
    current_trend_state: str,
) -> tuple[str, Decimal]:
    curr_p20 = (
        float(current_row["price_vs_ema20"])
        if current_row["price_vs_ema20"] is not None
        else 0.0
    )
    curr_p50 = (
        float(current_row["price_vs_ema50"])
        if current_row["price_vs_ema50"] is not None
        else 0.0
    )

    if previous_row is None:
        return "NO_RECLAIM_ATTEMPT", Decimal("0.000000")

    prev_p20 = (
        float(previous_row["price_vs_ema20"])
        if previous_row["price_vs_ema20"] is not None
        else 0.0
    )
    prev_p50 = (
        float(previous_row["price_vs_ema50"])
        if previous_row["price_vs_ema50"] is not None
        else 0.0
    )

    had_ema20_weakness = prev_p20 < 0.0
    had_broader_weakness = (prev_p20 < 0.0) or (prev_p50 < 0.0)
    trend_is_bullish = current_trend_state in {"UPTREND_STRONG", "UPTREND_WEAK"}

    # 1) Attempt:
    # previous candle below EMA20, current candle back above EMA20
    if had_ema20_weakness and curr_p20 >= 0.0:
        score_value = (
            0.45
            + 0.20 * _clamp(curr_p20 / 0.03)
            + 0.10 * _clamp((curr_p50 + 0.03) / 0.06)
        )
        return "RECLAIM_ATTEMPT", Decimal(str(round(_clamp(score_value), 6)))

    # 2) Confirmed:
    # prior weakness existed, price is now clearly back above EMA20,
    # with either near/above EMA50 or bullish trend context.
    if had_broader_weakness and curr_p20 >= 0.005 and (
        curr_p50 >= -0.01 or trend_is_bullish
    ):
        score_value = (
            0.68
            + 0.17 * _clamp(curr_p20 / 0.04)
            + 0.10 * _clamp((curr_p50 + 0.02) / 0.05)
        )
        if trend_is_bullish:
            score_value += 0.03
        return "RECLAIM_CONFIRMED", Decimal(str(round(_clamp(score_value), 6)))

    # 3) Failed:
    # previous candle was near/above EMA20 after weakness, current loses it again
    if had_broader_weakness and prev_p20 >= -0.002 and curr_p20 < -0.005:
        score_value = 0.05 + 0.12 * _clamp(abs(curr_p20) / 0.04)
        return "FAILED_RECLAIM", Decimal(str(round(_clamp(score_value), 6)))

    return "NO_RECLAIM_ATTEMPT", Decimal("0.000000")

def upsert_structure_rows(conn, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0

    sql = """
    INSERT INTO structure_state (
        asset_id,
        venue,
        interval_code,
        asof_ts_utc,
        trend_state,
        pullback_state,
        reclaim_state,
        trend_score,
        pullback_score,
        reclaim_score,
        engine_name,
        engine_version
    ) VALUES (
        %(asset_id)s,
        %(venue)s,
        %(interval_code)s,
        %(asof_ts_utc)s,
        %(trend_state)s,
        %(pullback_state)s,
        %(reclaim_state)s,
        %(trend_score)s,
        %(pullback_score)s,
        %(reclaim_score)s,
        %(engine_name)s,
        %(engine_version)s
    )
    ON DUPLICATE KEY UPDATE
        trend_state = VALUES(trend_state),
        pullback_state = VALUES(pullback_state),
        reclaim_state = VALUES(reclaim_state),
        trend_score = VALUES(trend_score),
        pullback_score = VALUES(pullback_score),
        reclaim_score = VALUES(reclaim_score)
    """

    with conn.cursor() as cur:
        cur.executemany(sql, rows)

    conn.commit()
    return len(rows)


def run(*, venue: str, intervals: tuple[str, ...], asset_id: int | None) -> int:
    conn = get_db_connection()

    try:
        total_rows = 0

        for interval_code in intervals:
            feat_rows = fetch_latest_feat_rows(
                conn,
                venue=venue,
                interval_code=interval_code,
                asset_id=asset_id,
            )

            paired_rows = group_current_previous(feat_rows)
            out_rows: list[dict[str, Any]] = []

            for current_row, previous_row in paired_rows:
                trend_state, trend_score = compute_trend_state(current_row)
                pullback_state, pullback_score = compute_pullback_state(
                    current_row,
                    trend_state,
                )
                reclaim_state, reclaim_score = compute_reclaim_state(
                    current_row,
                    previous_row,
                    trend_state,
                )

                out_rows.append(
                    {
                        "asset_id": int(current_row["asset_id"]),
                        "venue": str(current_row["venue"]),
                        "interval_code": str(current_row["interval_code"]),
                        "asof_ts_utc": current_row["close_ts_utc"].replace(tzinfo=None),
                        "trend_state": trend_state,
                        "pullback_state": pullback_state,
                        "reclaim_state": reclaim_state,
                        "trend_score": _to_decimal_str(trend_score),
                        "pullback_score": _to_decimal_str(pullback_score),
                        "reclaim_score": _to_decimal_str(reclaim_score),
                        "engine_name": ENGINE_NAME,
                        "engine_version": ENGINE_VERSION,
                    }
                )

            written = upsert_structure_rows(conn, out_rows)
            total_rows += written
            print(f"[DONE] interval={interval_code} rows={written}")

        print(f"[DONE] total_rows={total_rows}")
        return total_rows

    finally:
        conn.close()


if __name__ == "__main__":
    args = parse_args()
    intervals = tuple(args.interval) if args.interval else DEFAULT_INTERVALS
    raise SystemExit(
        0 if run(
            venue=args.venue,
            intervals=intervals,
            asset_id=args.asset_id,
        ) >= 0 else 1
    )
