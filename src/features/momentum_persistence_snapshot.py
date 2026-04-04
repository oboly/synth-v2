"""
SYNTH v2
Module: features.momentum_persistence_snapshot
Purpose:
    Compute momentum persistence snapshots from obs_market_candle.
Notes:
    - UTC only
    - Uses daily candles
    - Stores 7d and 14d persistence metrics
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from statistics import pstdev
from typing import Any

import pymysql
from pymysql.cursors import DictCursor


@dataclass(slots=True)
class DailyPoint:
    close_ts_utc: datetime
    close_price: Decimal


class MomentumPersistenceSnapshotService:
    def __init__(self, connection_params: dict[str, Any]) -> None:
        self._connection_params = connection_params

    def _connect(self) -> pymysql.connections.Connection:
        return pymysql.connect(
            cursorclass=DictCursor,
            autocommit=False,
            charset="utf8mb4",
            **self._connection_params,
        )

    @staticmethod
    def _dec(v: Any) -> Decimal:
        return Decimal(str(v))

    def _fetch_daily_series(self, max_days: int) -> dict[int, list[DailyPoint]]:
        sql = f"""
        SELECT
            c.asset_id,
            c.close_ts_utc,
            c.close_price
        FROM obs_market_candle c
        JOIN (
            SELECT MAX(close_ts_utc) AS max_close_ts_utc
            FROM obs_market_candle
            WHERE interval_code = '1d'
        ) mx
        WHERE c.interval_code = '1d'
          AND c.close_ts_utc >= mx.max_close_ts_utc - INTERVAL {int(max_days + 3)} DAY
        ORDER BY c.asset_id, c.close_ts_utc
        """

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = cur.fetchall()

        out: dict[int, list[DailyPoint]] = defaultdict(list)
        for r in rows:
            out[int(r["asset_id"])].append(
                DailyPoint(
                    close_ts_utc=r["close_ts_utc"],
                    close_price=self._dec(r["close_price"]),
                )
            )
        return out

    @staticmethod
    def _daily_return_pct(prev_close: Decimal, curr_close: Decimal) -> Decimal:
        if prev_close <= Decimal("0"):
            return Decimal("0")
        return ((curr_close / prev_close) - Decimal("1")) * Decimal("100")

    def _build_rows_for_lookback(
        self,
        series_by_asset: dict[int, list[DailyPoint]],
        lookback_days: int,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []

        for asset_id, points in series_by_asset.items():
            if len(points) < lookback_days + 1:
                continue

            tail = points[-(lookback_days + 1):]
            daily_returns: list[Decimal] = []

            up_days = 0
            down_days = 0
            flat_days = 0

            for i in range(1, len(tail)):
                ret = self._daily_return_pct(tail[i - 1].close_price, tail[i].close_price)
                daily_returns.append(ret)

                if ret > Decimal("0"):
                    up_days += 1
                elif ret < Decimal("0"):
                    down_days += 1
                else:
                    flat_days += 1

            total_days = len(daily_returns)
            if total_days == 0:
                continue

            green_ratio = Decimal(str(up_days / total_days))
            mean_daily_return_pct = sum(daily_returns, start=Decimal("0")) / Decimal(total_days)

            ret_values_float = [float(x) for x in daily_returns]
            std_daily_return_pct = Decimal(str(pstdev(ret_values_float))) if len(ret_values_float) > 1 else Decimal("0")

            # Simple persistence score:
            # higher if more green days, positive average return, and lower volatility
            denom = std_daily_return_pct + Decimal("1")
            persistence_score = (green_ratio * Decimal("100") + mean_daily_return_pct) / denom

            rows.append(
                {
                    "snapshot_ts_utc": tail[-1].close_ts_utc,
                    "asset_id": asset_id,
                    "lookback_days": lookback_days,
                    "up_days": up_days,
                    "down_days": down_days,
                    "flat_days": flat_days,
                    "green_ratio": green_ratio,
                    "mean_daily_return_pct": mean_daily_return_pct,
                    "std_daily_return_pct": std_daily_return_pct,
                    "persistence_score": persistence_score,
                }
            )

        return rows

    def write_snapshot(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0

        sql = """
        INSERT INTO momentum_persistence_snapshot (
            snapshot_ts_utc,
            asset_id,
            lookback_days,
            up_days,
            down_days,
            flat_days,
            green_ratio,
            mean_daily_return_pct,
            std_daily_return_pct,
            persistence_score
        ) VALUES (
            %(snapshot_ts_utc)s,
            %(asset_id)s,
            %(lookback_days)s,
            %(up_days)s,
            %(down_days)s,
            %(flat_days)s,
            %(green_ratio)s,
            %(mean_daily_return_pct)s,
            %(std_daily_return_pct)s,
            %(persistence_score)s
        )
        ON DUPLICATE KEY UPDATE
            up_days = VALUES(up_days),
            down_days = VALUES(down_days),
            flat_days = VALUES(flat_days),
            green_ratio = VALUES(green_ratio),
            mean_daily_return_pct = VALUES(mean_daily_return_pct),
            std_daily_return_pct = VALUES(std_daily_return_pct),
            persistence_score = VALUES(persistence_score)
        """

        payload = []
        for row in rows:
            payload.append(
                {
                    "snapshot_ts_utc": row["snapshot_ts_utc"],
                    "asset_id": row["asset_id"],
                    "lookback_days": row["lookback_days"],
                    "up_days": row["up_days"],
                    "down_days": row["down_days"],
                    "flat_days": row["flat_days"],
                    "green_ratio": str(row["green_ratio"]),
                    "mean_daily_return_pct": str(row["mean_daily_return_pct"]),
                    "std_daily_return_pct": str(row["std_daily_return_pct"]),
                    "persistence_score": str(row["persistence_score"]),
                }
            )

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.executemany(sql, payload)
            conn.commit()

        return len(payload)

    def run(self, lookbacks: list[int]) -> dict[str, int]:
        max_lookback = max(lookbacks)
        series_by_asset = self._fetch_daily_series(max_days=max_lookback)

        total_rows = 0
        for lookback_days in lookbacks:
            rows = self._build_rows_for_lookback(
                series_by_asset=series_by_asset,
                lookback_days=lookback_days,
            )
            total_rows += self.write_snapshot(rows)

        return {
            "assets_series": len(series_by_asset),
            "rows_written": total_rows,
        }
