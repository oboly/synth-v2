"""
SYNTH v2
Module: features.relative_strength_snapshot
Purpose:
    Compute cross-asset relative strength snapshots from obs_market_candle.
Notes:
    - UTC only
    - Uses latest available daily close per asset
    - Stores 7d and 14d cross-sectional rankings
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from statistics import pstdev
from typing import Any

import pymysql
from pymysql.cursors import DictCursor


@dataclass(slots=True)
class RsRow:
    asset_id: int
    close_ts_utc: datetime
    close_price: Decimal


class RelativeStrengthSnapshotService:
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

    def _fetch_latest_daily_closes(self) -> dict[int, RsRow]:
        sql = """
        SELECT
            c.asset_id,
            c.close_ts_utc,
            c.close_price
        FROM obs_market_candle c
        JOIN (
            SELECT asset_id, MAX(close_ts_utc) AS max_close_ts_utc
            FROM obs_market_candle
            WHERE interval_code = '1d'
            GROUP BY asset_id
        ) x
          ON c.asset_id = x.asset_id
         AND c.close_ts_utc = x.max_close_ts_utc
        WHERE c.interval_code = '1d'
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = cur.fetchall()

        out: dict[int, RsRow] = {}
        for r in rows:
            out[int(r["asset_id"])] = RsRow(
                asset_id=int(r["asset_id"]),
                close_ts_utc=r["close_ts_utc"],
                close_price=self._dec(r["close_price"]),
            )
        return out

    def _fetch_lookback_daily_closes(self, lookback_days: int) -> dict[int, RsRow]:
        sql = f"""
        SELECT
            c.asset_id,
            c.close_ts_utc,
            c.close_price
        FROM obs_market_candle c
        JOIN (
            SELECT asset_id, MAX(close_ts_utc) AS max_close_ts_utc
            FROM obs_market_candle
            WHERE interval_code = '1d'
              AND close_ts_utc <= (
                  SELECT MAX(close_ts_utc)
                  FROM obs_market_candle
                  WHERE interval_code = '1d'
              ) - INTERVAL {int(lookback_days)} DAY
            GROUP BY asset_id
        ) x
          ON c.asset_id = x.asset_id
         AND c.close_ts_utc = x.max_close_ts_utc
        WHERE c.interval_code = '1d'
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = cur.fetchall()

        out: dict[int, RsRow] = {}
        for r in rows:
            out[int(r["asset_id"])] = RsRow(
                asset_id=int(r["asset_id"]),
                close_ts_utc=r["close_ts_utc"],
                close_price=self._dec(r["close_price"]),
            )
        return out

    def _compute_return_pct(
        self,
        latest_close: Decimal,
        prev_close: Decimal,
    ) -> Decimal:
        if prev_close <= Decimal("0"):
            return Decimal("0")
        return ((latest_close / prev_close) - Decimal("1")) * Decimal("100")

    def _build_snapshot_rows(
        self,
        lookback_days: int,
        latest_by_asset: dict[int, RsRow],
        prev_by_asset: dict[int, RsRow],
    ) -> list[dict[str, Any]]:
        common_asset_ids = sorted(set(latest_by_asset.keys()) & set(prev_by_asset.keys()))
        if not common_asset_ids:
            return []

        returns: list[tuple[int, Decimal, datetime]] = []
        for asset_id in common_asset_ids:
            latest = latest_by_asset[asset_id]
            prev = prev_by_asset[asset_id]
            ret = self._compute_return_pct(latest.close_price, prev.close_price)
            returns.append((asset_id, ret, latest.close_ts_utc))

        sorted_returns = sorted(returns, key=lambda x: (x[1], x[0]), reverse=True)
        universe_size = len(sorted_returns)

        ret_values_float = [float(x[1]) for x in sorted_returns]
        mean_ret = sum(ret_values_float) / len(ret_values_float) if ret_values_float else 0.0
        std_ret = pstdev(ret_values_float) if len(ret_values_float) > 1 else 0.0

        rows: list[dict[str, Any]] = []
        for idx, (asset_id, ret, snapshot_ts_utc) in enumerate(sorted_returns, start=1):
            rank_pct = Decimal(str((universe_size - idx + 1) / universe_size))
            if std_ret > 0:
                zscore = Decimal(str((float(ret) - mean_ret) / std_ret))
            else:
                zscore = Decimal("0")

            rows.append(
                {
                    "snapshot_ts_utc": snapshot_ts_utc,
                    "asset_id": asset_id,
                    "lookback_days": lookback_days,
                    "return_pct": ret,
                    "rank_value": idx,
                    "universe_size": universe_size,
                    "rank_pct": rank_pct,
                    "zscore": zscore,
                }
            )

        return rows

    def write_snapshot(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0

        sql = """
        INSERT INTO relative_strength_snapshot (
            snapshot_ts_utc,
            asset_id,
            lookback_days,
            return_pct,
            rank_value,
            universe_size,
            rank_pct,
            zscore
        ) VALUES (
            %(snapshot_ts_utc)s,
            %(asset_id)s,
            %(lookback_days)s,
            %(return_pct)s,
            %(rank_value)s,
            %(universe_size)s,
            %(rank_pct)s,
            %(zscore)s
        )
        ON DUPLICATE KEY UPDATE
            return_pct = VALUES(return_pct),
            rank_value = VALUES(rank_value),
            universe_size = VALUES(universe_size),
            rank_pct = VALUES(rank_pct),
            zscore = VALUES(zscore)
        """

        payload = []
        for row in rows:
            payload.append(
                {
                    "snapshot_ts_utc": row["snapshot_ts_utc"],
                    "asset_id": row["asset_id"],
                    "lookback_days": row["lookback_days"],
                    "return_pct": str(row["return_pct"]),
                    "rank_value": row["rank_value"],
                    "universe_size": row["universe_size"],
                    "rank_pct": str(row["rank_pct"]),
                    "zscore": str(row["zscore"]),
                }
            )

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.executemany(sql, payload)
            conn.commit()

        return len(payload)

    def run(self, lookbacks: list[int]) -> dict[str, int]:
        latest_by_asset = self._fetch_latest_daily_closes()

        total_rows = 0
        for lookback_days in lookbacks:
            prev_by_asset = self._fetch_lookback_daily_closes(lookback_days)
            rows = self._build_snapshot_rows(
                lookback_days=lookback_days,
                latest_by_asset=latest_by_asset,
                prev_by_asset=prev_by_asset,
            )
            total_rows += self.write_snapshot(rows)

        return {
            "assets_latest": len(latest_by_asset),
            "rows_written": total_rows,
        }
