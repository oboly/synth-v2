from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Iterable

from src.common.db import db_cursor
from src.market_structure.models import FibObservation


@dataclass(slots=True)
class SwingAnchor:
    asset_id: int
    interval_code: str
    anchor_start_ts_utc: datetime
    anchor_end_ts_utc: datetime
    swing_direction: str
    start_price: Decimal
    end_price: Decimal


@dataclass(slots=True)
class CandlePoint:
    asset_id: int
    interval_code: str
    close_ts_utc: datetime
    high_price: Decimal
    low_price: Decimal


INTERVAL_CONFIG = {
    "4h": {
        "limit_per_asset": 220,
        "pivot_span": 2,
        "max_anchors_per_asset": 3,
    },
    "1d": {
        "limit_per_asset": 260,
        "pivot_span": 2,
        "max_anchors_per_asset": 3,
    },
}

FIB_LEVELS = (
    Decimal("0.382"),
    Decimal("0.500"),
    Decimal("0.618"),
    Decimal("1.000"),
    Decimal("1.272"),
    Decimal("1.618"),
)


def _fetch_candles(interval_code: str, limit_per_asset: int) -> dict[int, list[CandlePoint]]:
    sql = f"""
    SELECT
        x.asset_id,
        x.interval_code,
        x.close_ts_utc,
        x.high_price,
        x.low_price
    FROM (
        SELECT
            c.asset_id,
            c.interval_code,
            c.close_ts_utc,
            c.high_price,
            c.low_price,
            ROW_NUMBER() OVER (
                PARTITION BY c.asset_id, c.interval_code
                ORDER BY c.close_ts_utc DESC
            ) AS rn
        FROM obs_market_candle c
        WHERE c.interval_code = %s
    ) x
    WHERE x.rn <= {int(limit_per_asset)}
    ORDER BY x.asset_id, x.close_ts_utc
    """

    with db_cursor(commit=False) as (_conn, cur):
        cur.execute(sql, (interval_code,))
        rows = cur.fetchall()

    out: dict[int, list[CandlePoint]] = {}
    for r in rows:
        asset_id = int(r["asset_id"])
        out.setdefault(asset_id, []).append(
            CandlePoint(
                asset_id=asset_id,
                interval_code=str(r["interval_code"]),
                close_ts_utc=r["close_ts_utc"],
                high_price=Decimal(str(r["high_price"])),
                low_price=Decimal(str(r["low_price"])),
            )
        )
    return out


def _find_high_pivots(points: list[CandlePoint], span: int) -> list[tuple[int, CandlePoint]]:
    out: list[tuple[int, CandlePoint]] = []
    for i in range(span, len(points) - span):
        center = points[i]
        left = points[i - span:i]
        right = points[i + 1:i + span + 1]
        if all(center.high_price > p.high_price for p in left + right):
            out.append((i, center))
    return out


def _find_low_pivots(points: list[CandlePoint], span: int) -> list[tuple[int, CandlePoint]]:
    out: list[tuple[int, CandlePoint]] = []
    for i in range(span, len(points) - span):
        center = points[i]
        left = points[i - span:i]
        right = points[i + 1:i + span + 1]
        if all(center.low_price < p.low_price for p in left + right):
            out.append((i, center))
    return out


def _latest_swing_anchors(points: list[CandlePoint], span: int, max_count: int) -> list[SwingAnchor]:
    high_pivots = _find_high_pivots(points, span=span)
    low_pivots = _find_low_pivots(points, span=span)

    all_pivots: list[tuple[int, str, CandlePoint]] = []
    all_pivots.extend((idx, "high", p) for idx, p in high_pivots)
    all_pivots.extend((idx, "low", p) for idx, p in low_pivots)
    all_pivots.sort(key=lambda x: x[0])

    anchors: list[SwingAnchor] = []

    for i in range(1, len(all_pivots)):
        prev_idx, prev_type, prev_pivot = all_pivots[i - 1]
        curr_idx, curr_type, curr_pivot = all_pivots[i]

        if prev_type == curr_type:
            continue

        if prev_type == "low" and curr_type == "high":
            anchors.append(
                SwingAnchor(
                    asset_id=curr_pivot.asset_id,
                    interval_code=curr_pivot.interval_code,
                    anchor_start_ts_utc=prev_pivot.close_ts_utc,
                    anchor_end_ts_utc=curr_pivot.close_ts_utc,
                    swing_direction="up",
                    start_price=prev_pivot.low_price,
                    end_price=curr_pivot.high_price,
                )
            )
        elif prev_type == "high" and curr_type == "low":
            anchors.append(
                SwingAnchor(
                    asset_id=curr_pivot.asset_id,
                    interval_code=curr_pivot.interval_code,
                    anchor_start_ts_utc=prev_pivot.close_ts_utc,
                    anchor_end_ts_utc=curr_pivot.close_ts_utc,
                    swing_direction="down",
                    start_price=prev_pivot.high_price,
                    end_price=curr_pivot.low_price,
                )
            )

        anchors.sort(key=lambda x: x.anchor_end_ts_utc, reverse=True)

        if not anchors and len(points) > 5:
            # fallback: gebruik simpele laatste swing
            p0 = points[-6]
            p1 = points[-1]

            direction = "up" if p1.high_price > p0.low_price else "down"

            anchors.append(
                SwingAnchor(
                    asset_id=p1.asset_id,
                    interval_code=p1.interval_code,
                    anchor_start_ts_utc=p0.close_ts_utc,
                    anchor_end_ts_utc=p1.close_ts_utc,
                    swing_direction=direction,
                    start_price=p0.low_price,
                    end_price=p1.high_price,
                )
            )

        return anchors[:max_count]

def _fib_price(anchor: SwingAnchor, fib_level: Decimal) -> tuple[Decimal, bool, bool]:
    move = anchor.end_price - anchor.start_price

    if anchor.swing_direction == "up":
        if fib_level <= Decimal("1.0"):
            fib_price = anchor.end_price - (move * fib_level)
            return fib_price, True, False
        fib_price = anchor.start_price + (move * fib_level)
        return fib_price, False, True

    if fib_level <= Decimal("1.0"):
        fib_price = anchor.end_price + ((anchor.start_price - anchor.end_price) * fib_level)
        return fib_price, True, False
    fib_price = anchor.start_price - ((anchor.start_price - anchor.end_price) * (fib_level - Decimal("1.0")))
    return fib_price, False, True


def _confluence_score(fib_level: Decimal) -> Decimal:
    if fib_level == Decimal("0.618"):
        return Decimal("1.0")
    if fib_level == Decimal("0.500"):
        return Decimal("0.8")
    if fib_level == Decimal("0.382"):
        return Decimal("0.6")
    if fib_level == Decimal("1.618"):
        return Decimal("0.9")
    if fib_level == Decimal("1.272"):
        return Decimal("0.7")
    return Decimal("0.5")


def build_fib_observations(intervals: list[str] | None = None) -> list[FibObservation]:
    intervals = intervals or ["4h", "1d"]
    out: list[FibObservation] = []

    for interval_code in intervals:
        cfg = INTERVAL_CONFIG[interval_code]
        candles_by_asset = _fetch_candles(
            interval_code=interval_code,
            limit_per_asset=int(cfg["limit_per_asset"]),
        )

        for _asset_id, points in candles_by_asset.items():
            if len(points) < 12:
                continue

            anchors = _latest_swing_anchors(
                points=points,
                span=int(cfg["pivot_span"]),
                max_count=int(cfg["max_anchors_per_asset"]),
            )

            for anchor in anchors:
                for fib_level in FIB_LEVELS:
                    fib_price, is_retracement, is_extension = _fib_price(anchor, fib_level)
                    out.append(
                        FibObservation(
                            asset_id=anchor.asset_id,
                            interval_code=anchor.interval_code,
                            anchor_start_ts_utc=anchor.anchor_start_ts_utc,
                            anchor_end_ts_utc=anchor.anchor_end_ts_utc,
                            swing_direction=anchor.swing_direction,
                            fib_level=fib_level,
                            fib_price=fib_price,
                            is_retracement=is_retracement,
                            is_extension=is_extension,
                            confluence_score=_confluence_score(fib_level),
                            is_active=True,
                        )
                    )

    return out
