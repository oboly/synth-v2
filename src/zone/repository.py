from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from src.common.db import get_connection
from src.zone.models import (
    CandleRow,
    ExecutionZoneContextInput,
    FibObservationInput,
    ZoneObservationInput,
)


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


class ZoneRepository:
    def fetch_assets(
        self,
        *,
        asset_id: int | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        params: list[Any] = []
        asset_filter_sql = ""
        if asset_id is not None:
            asset_filter_sql = "AND asset_id = %s"
            params.append(asset_id)

        params.append(limit)

        sql = f"""
        SELECT
            asset_id,
            symbol
        FROM asset
        WHERE is_enabled = 1
          AND is_tradeable = 1
          {asset_filter_sql}
        ORDER BY asset_id
        LIMIT %s
        """
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchall() or []
        finally:
            conn.close()

    def fetch_recent_candles(
        self,
        *,
        asset_id: int,
        symbol: str,
        venue: str,
        interval_code: str,
        limit: int,
        asof_ts_utc: str | None = None,
    ) -> list[CandleRow]:
        asof_filter = ""
        params = [asset_id, venue, interval_code]

        if asof_ts_utc is not None:
            asof_filter = "AND open_ts_utc <= %s"
            params.append(asof_ts_utc)

        params.append(limit)

        sql = f"""
        SELECT
            asset_id,
            venue,
            interval_code,
            open_ts_utc,
            close_ts_utc,
            open_price,
            high_price,
            low_price,
            close_price
        FROM obs_market_candle
        WHERE asset_id = %s
          AND venue = %s
          AND interval_code = %s
          {asof_filter}
        ORDER BY open_ts_utc DESC
        LIMIT %s
        """

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall() or []
        finally:
            conn.close()

        rows.reverse()
        return [
            CandleRow(
                asset_id=int(row["asset_id"]),
                symbol=symbol,
                venue=str(row["venue"]),
                interval_code=str(row["interval_code"]),
                open_ts_utc=row["open_ts_utc"],
                close_ts_utc=row["close_ts_utc"],
                open_price=_to_decimal(row["open_price"]),
                high_price=_to_decimal(row["high_price"]),
                low_price=_to_decimal(row["low_price"]),
                close_price=_to_decimal(row["close_price"]),
            )
            for row in rows
        ]

    def upsert_fib_observation(self, fib: FibObservationInput) -> None:
        sql = """
        INSERT INTO fib_observation_v2 (
            asset_id,
            venue,
            interval_code,
            asof_ts_utc,
            anchor_start_ts_utc,
            anchor_end_ts_utc,
            anchor_start_price,
            anchor_end_price,
            leg_direction,
            anchor_span_bars,
            anchor_move_pct,
            fib_0236_price,
            fib_0382_price,
            fib_0500_price,
            fib_0618_price,
            fib_0786_price,
            ext_1272_price,
            ext_1618_price,
            active_retracement_price,
            active_extension_price,
            fib_confluence_score,
            structure_quality_score,
            source_type,
            notes
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        ON DUPLICATE KEY UPDATE
            anchor_start_price = VALUES(anchor_start_price),
            anchor_end_price = VALUES(anchor_end_price),
            leg_direction = VALUES(leg_direction),
            anchor_span_bars = VALUES(anchor_span_bars),
            anchor_move_pct = VALUES(anchor_move_pct),
            fib_0236_price = VALUES(fib_0236_price),
            fib_0382_price = VALUES(fib_0382_price),
            fib_0500_price = VALUES(fib_0500_price),
            fib_0618_price = VALUES(fib_0618_price),
            fib_0786_price = VALUES(fib_0786_price),
            ext_1272_price = VALUES(ext_1272_price),
            ext_1618_price = VALUES(ext_1618_price),
            active_retracement_price = VALUES(active_retracement_price),
            active_extension_price = VALUES(active_extension_price),
            fib_confluence_score = VALUES(fib_confluence_score),
            structure_quality_score = VALUES(structure_quality_score),
            source_type = VALUES(source_type),
            notes = VALUES(notes),
            updated_ts_utc = CURRENT_TIMESTAMP(6)
        """
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    [
                        fib.asset_id,
                        fib.venue,
                        fib.interval_code,
                        fib.asof_ts_utc,
                        fib.anchor_start_ts_utc,
                        fib.anchor_end_ts_utc,
                        fib.anchor_start_price,
                        fib.anchor_end_price,
                        fib.leg_direction,
                        fib.anchor_span_bars,
                        fib.anchor_move_pct,
                        fib.fib_0236_price,
                        fib.fib_0382_price,
                        fib.fib_0500_price,
                        fib.fib_0618_price,
                        fib.fib_0786_price,
                        fib.ext_1272_price,
                        fib.ext_1618_price,
                        fib.active_retracement_price,
                        fib.active_extension_price,
                        fib.fib_confluence_score,
                        fib.structure_quality_score,
                        fib.source_type,
                        fib.notes,
                    ],
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def upsert_zone_observation(self, zone: ZoneObservationInput) -> None:
        sql = """
        INSERT INTO zone_observation_v2 (
            asset_id,
            venue,
            interval_code,
            asof_ts_utc,
            zone_type,
            zone_source_type,
            zone_low_price,
            zone_high_price,
            zone_mid_price,
            zone_width_pct,
            expected_reaction,
            invalidation_price,
            zone_strength_score,
            confluence_score,
            touch_count,
            break_count,
            zone_age_bars,
            source_ref_type,
            source_ref_id,
            parent_zone_observation_id,
            notes
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        ON DUPLICATE KEY UPDATE
            zone_mid_price = VALUES(zone_mid_price),
            zone_width_pct = VALUES(zone_width_pct),
            expected_reaction = VALUES(expected_reaction),
            invalidation_price = VALUES(invalidation_price),
            zone_strength_score = VALUES(zone_strength_score),
            confluence_score = VALUES(confluence_score),
            touch_count = VALUES(touch_count),
            break_count = VALUES(break_count),
            zone_age_bars = VALUES(zone_age_bars),
            source_ref_type = VALUES(source_ref_type),
            source_ref_id = VALUES(source_ref_id),
            parent_zone_observation_id = VALUES(parent_zone_observation_id),
            notes = VALUES(notes),
            updated_ts_utc = CURRENT_TIMESTAMP(6)
        """
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    [
                        zone.asset_id,
                        zone.venue,
                        zone.interval_code,
                        zone.asof_ts_utc,
                        zone.zone_type,
                        zone.zone_source_type,
                        zone.zone_low_price,
                        zone.zone_high_price,
                        zone.zone_mid_price,
                        zone.zone_width_pct,
                        zone.expected_reaction,
                        zone.invalidation_price,
                        zone.zone_strength_score,
                        zone.confluence_score,
                        zone.touch_count,
                        zone.break_count,
                        zone.zone_age_bars,
                        zone.source_ref_type,
                        zone.source_ref_id,
                        zone.parent_zone_observation_id,
                        zone.notes,
                    ],
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def delete_execution_zone_context_scope(
        self,
        *,
        venue: str,
        interval_code: str,
        sleeve_code: str,
        asset_id: int | None = None,
    ) -> int:
        params: list[Any] = [venue, interval_code, sleeve_code]
        asset_filter_sql = ""

        if asset_id is not None:
            asset_filter_sql = "AND asset_id = %s"
            params.append(asset_id)

        sql = f"""
        DELETE FROM execution_zone_context
        WHERE venue = %s
          AND interval_code = %s
          AND sleeve_code = %s
          {asset_filter_sql}
        """

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                deleted_rows = int(cur.rowcount)
            conn.commit()
            return deleted_rows
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def upsert_execution_zone_context(self, ctx: ExecutionZoneContextInput) -> None:
        sql = """
        INSERT INTO execution_zone_context (
            asset_id,
            venue,
            sleeve_code,
            interval_code,
            asof_ts_utc,
            dominant_tf,
            expected_entry_zone_low,
            expected_entry_zone_high,
            expected_entry_zone_type,
            expected_take_profit_zone_low,
            expected_take_profit_zone_high,
            expected_take_profit_zone_type,
            invalidation_price,
            zone_confidence_score,
            zone_alignment_score,
            source_timeframes,
            source_types,
            source_ref_json,
            notes
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        ON DUPLICATE KEY UPDATE
            dominant_tf = VALUES(dominant_tf),
            expected_entry_zone_low = VALUES(expected_entry_zone_low),
            expected_entry_zone_high = VALUES(expected_entry_zone_high),
            expected_entry_zone_type = VALUES(expected_entry_zone_type),
            expected_take_profit_zone_low = VALUES(expected_take_profit_zone_low),
            expected_take_profit_zone_high = VALUES(expected_take_profit_zone_high),
            expected_take_profit_zone_type = VALUES(expected_take_profit_zone_type),
            invalidation_price = VALUES(invalidation_price),
            zone_confidence_score = VALUES(zone_confidence_score),
            zone_alignment_score = VALUES(zone_alignment_score),
            source_timeframes = VALUES(source_timeframes),
            source_types = VALUES(source_types),
            source_ref_json = VALUES(source_ref_json),
            notes = VALUES(notes),
            updated_ts_utc = CURRENT_TIMESTAMP(6)
        """
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    [
                        ctx.asset_id,
                        ctx.venue,
                        ctx.sleeve_code,
                        ctx.interval_code,
                        ctx.asof_ts_utc,
                        ctx.dominant_tf,
                        ctx.expected_entry_zone_low,
                        ctx.expected_entry_zone_high,
                        ctx.expected_entry_zone_type,
                        ctx.expected_take_profit_zone_low,
                        ctx.expected_take_profit_zone_high,
                        ctx.expected_take_profit_zone_type,
                        ctx.invalidation_price,
                        ctx.zone_confidence_score,
                        ctx.zone_alignment_score,
                        ctx.source_timeframes,
                        ctx.source_types,
                        ctx.source_ref_json,
                        ctx.notes,
                    ],
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def dump_result_row(self, ctx: ExecutionZoneContextInput) -> dict[str, Any]:
        return {
            "asset_id": ctx.asset_id,
            "symbol": ctx.symbol,
            "interval_code": ctx.interval_code,
            "asof_ts_utc": str(ctx.asof_ts_utc),
            "entry_zone_low": str(ctx.expected_entry_zone_low) if ctx.expected_entry_zone_low is not None else "",
            "entry_zone_high": str(ctx.expected_entry_zone_high) if ctx.expected_entry_zone_high is not None else "",
            "entry_zone_type": ctx.expected_entry_zone_type or "",
            "tp_zone_low": str(ctx.expected_take_profit_zone_low) if ctx.expected_take_profit_zone_low is not None else "",
            "tp_zone_high": str(ctx.expected_take_profit_zone_high) if ctx.expected_take_profit_zone_high is not None else "",
            "tp_zone_type": ctx.expected_take_profit_zone_type or "",
            "invalidation_price": str(ctx.invalidation_price) if ctx.invalidation_price is not None else "",
            "zone_confidence_score": str(ctx.zone_confidence_score),
            "zone_alignment_score": str(ctx.zone_alignment_score),
        }

    def make_source_ref_json(
        self,
        *,
        fib_anchor_start_ts_utc: str,
        fib_anchor_end_ts_utc: str,
        zones: list[ZoneObservationInput],
    ) -> str:
        payload = {
            "fib_anchor_start_ts_utc": fib_anchor_start_ts_utc,
            "fib_anchor_end_ts_utc": fib_anchor_end_ts_utc,
            "zones": [
                {
                    "zone_type": z.zone_type,
                    "zone_source_type": z.zone_source_type,
                    "zone_low_price": str(z.zone_low_price),
                    "zone_high_price": str(z.zone_high_price),
                    "zone_strength_score": str(z.zone_strength_score),
                    "confluence_score": str(z.confluence_score),
                }
                for z in zones
            ],
        }
        return json.dumps(payload, ensure_ascii=False)
