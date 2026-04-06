from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from statistics import median
from typing import Iterable

from src.common.db import db_cursor
from src.market_structure.models import ZoneObservation


@dataclass(slots=True)
class CandlePoint:
    asset_id: int
    interval_code: str
    open_ts_utc: datetime
    close_ts_utc: datetime
    high_price: Decimal
    low_price: Decimal


@dataclass(slots=True)
class PivotPoint:
    price: Decimal
    ts_utc: datetime


INTERVAL_CONFIG = {
    "4h": {
        "limit_per_asset": 180,
        "tolerance_bps": Decimal("45"),
        "min_zone_width_bps": Decimal("20"),
        "pivot_span": 2,
        "max_zones_per_type": 3,
    },
    "1d": {
        "limit_per_asset": 220,
        "tolerance_bps": Decimal("65"),
        "min_zone_width_bps": Decimal("35"),
        "pivot_span": 2,
        "max_zones_per_type": 3,
    },
}


def _fetch_candles(interval_code: str, limit_per_asset: int) -> dict[int, list[CandlePoint]]:
    sql = f"""
    SELECT
        x.asset_id,
        x.interval_code,
        x.open_ts_utc,
        x.close_ts_utc,
        x.high_price,
        x.low_price
    FROM (
        SELECT
            c.asset_id,
            c.interval_code,
            c.open_ts_utc,
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

    out: dict[int, list[CandlePoint]] = defaultdict(list)
    for r in rows:
        out[int(r["asset_id"])].append(
            CandlePoint(
                asset_id=int(r["asset_id"]),
                interval_code=str(r["interval_code"]),
                open_ts_utc=r["open_ts_utc"],
                close_ts_utc=r["close_ts_utc"],
                high_price=Decimal(str(r["high_price"])),
                low_price=Decimal(str(r["low_price"])),
            )
        )
    return out


def _find_high_pivots(points: list[CandlePoint], span: int) -> list[PivotPoint]:
    out: list[PivotPoint] = []
    for i in range(span, len(points) - span):
        center = points[i]
        left = points[i - span:i]
        right = points[i + 1:i + span + 1]
        if all(center.high_price > p.high_price for p in left + right):
            out.append(PivotPoint(price=center.high_price, ts_utc=center.close_ts_utc))
    return out


def _find_low_pivots(points: list[CandlePoint], span: int) -> list[PivotPoint]:
    out: list[PivotPoint] = []
    for i in range(span, len(points) - span):
        center = points[i]
        left = points[i - span:i]
        right = points[i + 1:i + span + 1]
        if all(center.low_price < p.low_price for p in left + right):
            out.append(PivotPoint(price=center.low_price, ts_utc=center.close_ts_utc))
    return out


def _bps_distance(a: Decimal, b: Decimal) -> Decimal:
    if b == Decimal("0"):
        return Decimal("999999")
    return abs(a - b) / b * Decimal("10000")


def _cluster_pivots(pivots: list[PivotPoint], tolerance_bps: Decimal) -> list[list[PivotPoint]]:
    if not pivots:
        return []

    pivots_sorted = sorted(pivots, key=lambda p: p.price)
    clusters: list[list[PivotPoint]] = [[pivots_sorted[0]]]

    for pivot in pivots_sorted[1:]:
        cluster = clusters[-1]
        center = sum((p.price for p in cluster), Decimal("0")) / Decimal(len(cluster))
        if _bps_distance(pivot.price, center) <= tolerance_bps:
            cluster.append(pivot)
        else:
            clusters.append([pivot])

    return clusters


def _median_candle_range(points: Iterable[CandlePoint]) -> Decimal:
    ranges = [p.high_price - p.low_price for p in points if p.high_price >= p.low_price]
    if not ranges:
        return Decimal("0")
    return Decimal(str(median([float(x) for x in ranges])))


def _build_zone_from_cluster(
    asset_id: int,
    interval_code: str,
    zone_type: str,
    cluster: list[PivotPoint],
    median_range: Decimal,
    min_zone_width_bps: Decimal,
) -> ZoneObservation:
    prices = [p.price for p in cluster]
    center = sum(prices, Decimal("0")) / Decimal(len(prices))
    min_width = center * (min_zone_width_bps / Decimal("10000"))
    range_width = median_range * Decimal("0.35")
    half_width = max(min_width, range_width)

    zone_low = center - half_width
    zone_high = center + half_width
    touch_count = len(cluster)
    last_touch_ts_utc = max(p.ts_utc for p in cluster)

    base_strength = min(Decimal("1.0"), Decimal(str(touch_count)) / Decimal("4.0"))

    return ZoneObservation(
        asset_id=asset_id,
        interval_code=interval_code,
        zone_type=zone_type,
        zone_low=zone_low,
        zone_high=zone_high,
        zone_strength=base_strength,
        zone_source="swing_cluster",
        touch_count=touch_count,
        last_touch_ts_utc=last_touch_ts_utc,
        is_active=True,
    )


def _top_clusters_by_relevance(
    clusters: list[list[PivotPoint]],
    max_count: int,
) -> list[list[PivotPoint]]:
    ranked = sorted(
        clusters,
        key=lambda c: (len(c), max(p.ts_utc for p in c)),
        reverse=True,
    )
    return ranked[:max_count]


def build_zone_observations(intervals: list[str] | None = None) -> list[ZoneObservation]:
    intervals = intervals or ["4h", "1d"]
    all_zones: list[ZoneObservation] = []

    for interval_code in intervals:
        cfg = INTERVAL_CONFIG[interval_code]
        candles_by_asset = _fetch_candles(
            interval_code=interval_code,
            limit_per_asset=int(cfg["limit_per_asset"]),
        )

        for asset_id, points in candles_by_asset.items():
            if len(points) < 10:
                continue

            span = int(cfg["pivot_span"])
            tolerance_bps = Decimal(str(cfg["tolerance_bps"]))
            min_zone_width_bps = Decimal(str(cfg["min_zone_width_bps"]))
            max_zones_per_type = int(cfg["max_zones_per_type"])

            high_pivots = _find_high_pivots(points, span=span)
            low_pivots = _find_low_pivots(points, span=span)

            median_range = _median_candle_range(points)

            resistance_clusters = _cluster_pivots(high_pivots, tolerance_bps=tolerance_bps)
            support_clusters = _cluster_pivots(low_pivots, tolerance_bps=tolerance_bps)

            resistance_clusters = _top_clusters_by_relevance(
                resistance_clusters,
                max_count=max_zones_per_type,
            )
            support_clusters = _top_clusters_by_relevance(
                support_clusters,
                max_count=max_zones_per_type,
            )

            for cluster in support_clusters:
                all_zones.append(
                    _build_zone_from_cluster(
                        asset_id=asset_id,
                        interval_code=interval_code,
                        zone_type="support",
                        cluster=cluster,
                        median_range=median_range,
                        min_zone_width_bps=min_zone_width_bps,
                    )
                )

            for cluster in resistance_clusters:
                all_zones.append(
                    _build_zone_from_cluster(
                        asset_id=asset_id,
                        interval_code=interval_code,
                        zone_type="resistance",
                        cluster=cluster,
                        median_range=median_range,
                        min_zone_width_bps=min_zone_width_bps,
                    )
                )

    return all_zones
