from __future__ import annotations

from typing import Iterable

from src.common.db import db_cursor
from src.market_structure.models import (
    ExecutionPlan,
    FibObservation,
    StrategySignalContext,
    WaveCountObservation,
    WaveCountSet,
    ZoneObservation,
)


class MarketStructureRepository:
    def upsert_zone_observations(self, rows: Iterable[ZoneObservation]) -> int:
        rows = list(rows)
        if not rows:
            return 0

        touched_pairs = sorted({(r.asset_id, r.interval_code) for r in rows})

        with db_cursor(commit=True) as (_conn, cur):
            for asset_id, interval_code in touched_pairs:
                cur.execute(
                    """
                    UPDATE zone_observation
                    SET is_active = 0
                    WHERE asset_id = %s
                      AND interval_code = %s
                      AND is_active = 1
                    """,
                    (asset_id, interval_code),
                )

            insert_sql = """
            INSERT INTO zone_observation (
                asset_id,
                interval_code,
                zone_type,
                zone_low,
                zone_high,
                zone_strength,
                zone_source,
                touch_count,
                last_touch_ts_utc,
                is_active
            ) VALUES (
                %(asset_id)s,
                %(interval_code)s,
                %(zone_type)s,
                %(zone_low)s,
                %(zone_high)s,
                %(zone_strength)s,
                %(zone_source)s,
                %(touch_count)s,
                %(last_touch_ts_utc)s,
                %(is_active)s
            )
            """

            payload = [
                {
                    "asset_id": r.asset_id,
                    "interval_code": r.interval_code,
                    "zone_type": r.zone_type,
                    "zone_low": r.zone_low,
                    "zone_high": r.zone_high,
                    "zone_strength": r.zone_strength,
                    "zone_source": r.zone_source,
                    "touch_count": r.touch_count,
                    "last_touch_ts_utc": r.last_touch_ts_utc,
                    "is_active": int(r.is_active),
                }
                for r in rows
            ]
            cur.executemany(insert_sql, payload)

        return len(rows)

    def upsert_fib_observations(self, rows: Iterable[FibObservation]) -> int:
        rows = list(rows)
        if not rows:
            return 0

        sql = """
        INSERT INTO fib_observation (
            asset_id,
            interval_code,
            anchor_start_ts_utc,
            anchor_end_ts_utc,
            swing_direction,
            fib_level,
            fib_price,
            is_retracement,
            is_extension,
            confluence_score,
            is_active
        ) VALUES (
            %(asset_id)s,
            %(interval_code)s,
            %(anchor_start_ts_utc)s,
            %(anchor_end_ts_utc)s,
            %(swing_direction)s,
            %(fib_level)s,
            %(fib_price)s,
            %(is_retracement)s,
            %(is_extension)s,
            %(confluence_score)s,
            %(is_active)s
        )
        """

        payload = [
            {
                "asset_id": r.asset_id,
                "interval_code": r.interval_code,
                "anchor_start_ts_utc": r.anchor_start_ts_utc,
                "anchor_end_ts_utc": r.anchor_end_ts_utc,
                "swing_direction": r.swing_direction,
                "fib_level": r.fib_level,
                "fib_price": r.fib_price,
                "is_retracement": int(r.is_retracement),
                "is_extension": int(r.is_extension),
                "confluence_score": r.confluence_score,
                "is_active": int(r.is_active),
            }
            for r in rows
        ]

        with db_cursor(commit=True) as (_conn, cur):
            cur.executemany(sql, payload)
        return len(rows)

    def upsert_wave_count_sets(self, rows: Iterable[WaveCountSet]) -> int:
        rows = list(rows)
        if not rows:
            return 0

        sql = """
        INSERT INTO wave_count_set (
            asset_id,
            interval_code,
            count_state,
            bias,
            confidence_score,
            invalidation_price,
            is_primary_count,
            is_alternate_count
        ) VALUES (
            %(asset_id)s,
            %(interval_code)s,
            %(count_state)s,
            %(bias)s,
            %(confidence_score)s,
            %(invalidation_price)s,
            %(is_primary_count)s,
            %(is_alternate_count)s
        )
        """

        payload = [
            {
                "asset_id": r.asset_id,
                "interval_code": r.interval_code,
                "count_state": r.count_state,
                "bias": r.bias,
                "confidence_score": r.confidence_score,
                "invalidation_price": r.invalidation_price,
                "is_primary_count": int(r.is_primary_count),
                "is_alternate_count": int(r.is_alternate_count),
            }
            for r in rows
        ]

        with db_cursor(commit=True) as (_conn, cur):
            cur.executemany(sql, payload)
        return len(rows)

    def upsert_wave_count_observations(self, rows: Iterable[WaveCountObservation]) -> int:
        rows = list(rows)
        if not rows:
            return 0

        sql = """
        INSERT INTO wave_count_observation (
            asset_id,
            interval_code,
            wave_label,
            start_ts_utc,
            end_ts_utc,
            start_price,
            end_price,
            confidence_score,
            invalidation_price,
            parent_wave_id
        ) VALUES (
            %(asset_id)s,
            %(interval_code)s,
            %(wave_label)s,
            %(start_ts_utc)s,
            %(end_ts_utc)s,
            %(start_price)s,
            %(end_price)s,
            %(confidence_score)s,
            %(invalidation_price)s,
            %(parent_wave_id)s
        )
        """

        payload = [
            {
                "asset_id": r.asset_id,
                "interval_code": r.interval_code,
                "wave_label": r.wave_label,
                "start_ts_utc": r.start_ts_utc,
                "end_ts_utc": r.end_ts_utc,
                "start_price": r.start_price,
                "end_price": r.end_price,
                "confidence_score": r.confidence_score,
                "invalidation_price": r.invalidation_price,
                "parent_wave_id": r.parent_wave_id,
            }
            for r in rows
        ]

        with db_cursor(commit=True) as (_conn, cur):
            cur.executemany(sql, payload)
        return len(rows)

    def upsert_strategy_signal_context(self, rows: Iterable[StrategySignalContext]) -> int:
        rows = list(rows)
        if not rows:
            return 0

        sql = """
        INSERT INTO strategy_signal_context (
            asset_id,
            interval_code,
            context_ts_utc,
            zone_state,
            fib_state,
            wave_label,
            wave_confidence,
            zone_confluence_score,
            fib_confluence_score,
            context_score,
            volume_ratio,
            volume_zscore,
            volume_state,
            volume_alignment_score,
            distance_to_support,
            distance_to_resistance,
            distance_to_support_bps,
            distance_to_resistance_bps,
            fib_level,
            fib_price,
            fib_distance_bps
        ) VALUES (
            %(asset_id)s,
            %(interval_code)s,
            %(context_ts_utc)s,
            %(zone_state)s,
            %(fib_state)s,
            %(wave_label)s,
            %(wave_confidence)s,
            %(zone_confluence_score)s,
            %(fib_confluence_score)s,
            %(context_score)s,
            %(volume_ratio)s,
            %(volume_zscore)s,
            %(volume_state)s,
            %(volume_alignment_score)s,
            %(distance_to_support)s,
            %(distance_to_resistance)s,
            %(distance_to_support_bps)s,
            %(distance_to_resistance_bps)s,
            %(fib_level)s,
            %(fib_price)s,
            %(fib_distance_bps)s
        )
        ON DUPLICATE KEY UPDATE
            zone_state = VALUES(zone_state),
            fib_state = VALUES(fib_state),
            wave_label = VALUES(wave_label),
            wave_confidence = VALUES(wave_confidence),
            zone_confluence_score = VALUES(zone_confluence_score),
            fib_confluence_score = VALUES(fib_confluence_score),
            context_score = VALUES(context_score),
            volume_ratio = VALUES(volume_ratio),
            volume_zscore = VALUES(volume_zscore),
            volume_state = VALUES(volume_state),
            volume_alignment_score = VALUES(volume_alignment_score),
            distance_to_support = VALUES(distance_to_support),
            distance_to_resistance = VALUES(distance_to_resistance),
            distance_to_support_bps = VALUES(distance_to_support_bps),
            distance_to_resistance_bps = VALUES(distance_to_resistance_bps),
            fib_level = VALUES(fib_level),
            fib_price = VALUES(fib_price),
            fib_distance_bps = VALUES(fib_distance_bps)
        """

        payload = [
            {
                "asset_id": r.asset_id,
                "interval_code": r.interval_code,
                "context_ts_utc": r.context_ts_utc,
                "zone_state": r.zone_state,
                "fib_state": r.fib_state,
                "wave_label": r.wave_label,
                "wave_confidence": r.wave_confidence,
                "zone_confluence_score": r.zone_confluence_score,
                "fib_confluence_score": r.fib_confluence_score,
                "context_score": r.context_score,
                "volume_ratio": r.volume_ratio,
                "volume_zscore": r.volume_zscore,
                "volume_state": r.volume_state,
                "volume_alignment_score": r.volume_alignment_score,
                "distance_to_support": r.distance_to_support,
                "distance_to_resistance": r.distance_to_resistance,
                "distance_to_support_bps": r.distance_to_support_bps,
                "distance_to_resistance_bps": r.distance_to_resistance_bps,
                "fib_level": r.fib_level,
                "fib_price": r.fib_price,
                "fib_distance_bps": r.fib_distance_bps,
            }
            for r in rows
        ]

        with db_cursor(commit=True) as (_conn, cur):
            cur.executemany(sql, payload)
        return len(rows)

    def insert_execution_plans(self, rows: Iterable[ExecutionPlan]) -> int:
        rows = list(rows)
        if not rows:
            return 0

        sql = """
        INSERT INTO execution_plan (
            asset_id,
            sleeve_code,
            desired_action,
            plan_ts_utc,
            execution_mode,
            target_fraction,
            reference_price_eur,
            passive_price_eur,
            urgent_limit_price_eur,
            max_reprices,
            max_wait_seconds,
            max_chase_bps,
            min_spread_bps_for_capture,
            escalation_to_urgent_limit,
            abort_if_signal_invalidates,
            plan_state,
            notes
        ) VALUES (
            %(asset_id)s,
            %(sleeve_code)s,
            %(desired_action)s,
            %(plan_ts_utc)s,
            %(execution_mode)s,
            %(target_fraction)s,
            %(reference_price_eur)s,
            %(passive_price_eur)s,
            %(urgent_limit_price_eur)s,
            %(max_reprices)s,
            %(max_wait_seconds)s,
            %(max_chase_bps)s,
            %(min_spread_bps_for_capture)s,
            %(escalation_to_urgent_limit)s,
            %(abort_if_signal_invalidates)s,
            %(plan_state)s,
            %(notes)s
        )
        """

        payload = [
            {
                "asset_id": r.asset_id,
                "sleeve_code": r.sleeve_code,
                "desired_action": r.desired_action,
                "plan_ts_utc": r.plan_ts_utc,
                "execution_mode": r.execution_mode,
                "target_fraction": r.target_fraction,
                "reference_price_eur": r.reference_price_eur,
                "passive_price_eur": r.passive_price_eur,
                "urgent_limit_price_eur": r.urgent_limit_price_eur,
                "max_reprices": r.max_reprices,
                "max_wait_seconds": r.max_wait_seconds,
                "max_chase_bps": r.max_chase_bps,
                "min_spread_bps_for_capture": r.min_spread_bps_for_capture,
                "escalation_to_urgent_limit": int(r.escalation_to_urgent_limit),
                "abort_if_signal_invalidates": int(r.abort_if_signal_invalidates),
                "plan_state": r.plan_state,
                "notes": r.notes,
            }
            for r in rows
        ]

        with db_cursor(commit=True) as (_conn, cur):
            cur.executemany(sql, payload)
        return len(rows)
