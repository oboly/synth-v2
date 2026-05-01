from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from src.asset_profile.models import AssetProfileSnapshot
from src.common.db import get_connection


@dataclass(frozen=True)
class AssetProfileRepository:
    database: str = "synth"

    def fetch_market_rows(
        self,
        *,
        venue: str,
        interval_code: str,
        from_ts_utc: str,
        asof_ts_utc: str,
    ) -> list[dict[str, Any]]:
        sql = """
        SELECT
            a.asset_id,
            a.symbol,
            c.close_ts_utc,
            c.close_price,
            c.volume_quote_eur,
            c.trade_count
        FROM obs_market_candle c
        JOIN asset a
          ON a.asset_id = c.asset_id
        WHERE a.is_enabled = 1
          AND c.venue = %s
          AND c.interval_code = %s
          AND c.close_ts_utc > %s
          AND c.close_ts_utc <= %s
        ORDER BY c.close_ts_utc ASC, a.symbol ASC
        """

        conn = get_connection(database=self.database)
        try:
            with conn.cursor() as cur:
                cur.execute(sql, [venue, interval_code, from_ts_utc, asof_ts_utc])
                return list(cur.fetchall() or [])
        finally:
            conn.close()

    def upsert_snapshots(self, rows: list[AssetProfileSnapshot]) -> int:
        if not rows:
            return 0

        sql = """
        INSERT INTO asset_profile_snapshot (
            asset_id,
            venue,
            interval_code,
            asof_ts_utc,
            lookback_days,
            profile_version,
            liquidity_score,
            liquidity_class,
            beta_to_market,
            beta_profile,
            realized_volatility,
            sector_group_code,
            sector_confidence,
            candles_observed,
            coverage_ratio,
            benchmark_symbols,
            notes
        ) VALUES (
            %(asset_id)s,
            %(venue)s,
            %(interval_code)s,
            %(asof_ts_utc)s,
            %(lookback_days)s,
            %(profile_version)s,
            %(liquidity_score)s,
            %(liquidity_class)s,
            %(beta_to_market)s,
            %(beta_profile)s,
            %(realized_volatility)s,
            %(sector_group_code)s,
            %(sector_confidence)s,
            %(candles_observed)s,
            %(coverage_ratio)s,
            %(benchmark_symbols)s,
            %(notes)s
        )
        ON DUPLICATE KEY UPDATE
            liquidity_score = VALUES(liquidity_score),
            liquidity_class = VALUES(liquidity_class),
            beta_to_market = VALUES(beta_to_market),
            beta_profile = VALUES(beta_profile),
            realized_volatility = VALUES(realized_volatility),
            sector_group_code = VALUES(sector_group_code),
            sector_confidence = VALUES(sector_confidence),
            candles_observed = VALUES(candles_observed),
            coverage_ratio = VALUES(coverage_ratio),
            benchmark_symbols = VALUES(benchmark_symbols),
            notes = VALUES(notes)
        """

        payload = [asdict(row) for row in rows]

        conn = get_connection(database=self.database)
        try:
            with conn.cursor() as cur:
                written = cur.executemany(sql, payload)
            conn.commit()
            return int(written)
        finally:
            conn.close()
