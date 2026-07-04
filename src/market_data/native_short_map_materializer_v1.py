from __future__ import annotations

"""Market-only native SHORT map ledger materializer canary.

Safety markers:
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none

Reads:
- native_short_map_scope_v1
- native_short_map_v1
- native_short_map_generation_event_v1
- native_short_map_lifecycle_event_v1
- obs_market_candle through the market-only canary context builder

Writes, only when the caller passes write=True:
- native_short_map_v1
- native_short_map_generation_event_v1
- native_short_map_lifecycle_event_v1
"""

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from src.market_data.native_short_fib_context_v1 import (
    STATUS_AVAILABLE,
    NativeShortContextRow,
)
from src.market_data.native_short_map_lifecycle_v1 import (
    DEFAULT_FIB_TRADING_HORIZON,
    DEFAULT_PRIMARY_INTERVAL,
    DEFAULT_QUOTE_CURRENCY,
    DEFAULT_SUPPORTING_INTERVAL,
    NativeShortMapGenerationEvent,
    NativeShortMapGenerationEventType,
    NativeShortMapLifecycleEvent,
    NativeShortMapLifecycleEventType,
    NativeShortMapRecord,
    NativeShortMapScopeKey,
    NativeShortMapScopeSupport,
    NativeShortMapScopeSupportState,
    validate_native_short_map_write_intent,
)

GENERATOR_NAME = "native_short_map_materializer_v1"
GENERATOR_VERSION = "0.1"
FIB_MODEL_NAME = "native_short_fib_context_v1"
FIB_MODEL_VERSION = "0.1"
TRIGGER_TYPE = "MANUAL_NATIVE_SHORT_MAP_LEDGER_CANARY"

REASON_DRY_RUN = "DRY_RUN_WRITE_DISABLED"
REASON_STRUCTURE_UNCHANGED = "STRUCTURE_HASH_UNCHANGED"
REASON_PRIOR_REJECTION_UNCHANGED = "PRIOR_REJECTION_UNCHANGED"
REASON_SCOPE_NOT_SUPPORTED = "SCOPE_NOT_SUPPORTED"

_CONTEXT_STATUS_TO_REJECTION_REASON: dict[str, str] = {
    "INSUFFICIENT_4H_HISTORY": "CANDLES_INSUFFICIENT",
    "INSUFFICIENT_1H_HISTORY": "CANDLES_INSUFFICIENT",
    "CONTEXT_INVALID_OR_STALE": "CANDLE_SNAPSHOT_STALE",
    "SYMBOL_CONTEXT_MISSING": "CANDLES_INSUFFICIENT",
}

_TERMINAL_LIFECYCLE_TYPES = {
    NativeShortMapLifecycleEventType.COMPLETED,
    NativeShortMapLifecycleEventType.EXPIRED,
    NativeShortMapLifecycleEventType.INVALIDATED,
    NativeShortMapLifecycleEventType.SUPERSEDED,
}


@dataclass(frozen=True)
class ScopeMaterializationResult:
    symbol: str
    attempted: bool
    status: str
    dry_run: bool
    map_id: int | None = None
    generation_attempt_id: str | None = None
    generation_event_ids: list[int] = field(default_factory=list)
    lifecycle_event_ids: list[int] = field(default_factory=list)
    structure_hash: str | None = None
    reason_code: str | None = None
    detail: str | None = None
    planned_status: str | None = None
    generation_event_type: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "attempted": self.attempted,
            "status": self.status,
            "dry_run": self.dry_run,
            "map_id": self.map_id,
            "generation_attempt_id": self.generation_attempt_id,
            "generation_event_ids": self.generation_event_ids,
            "lifecycle_event_ids": self.lifecycle_event_ids,
            "structure_hash": self.structure_hash,
            "reason_code": self.reason_code,
            "detail": self.detail,
            "planned_status": self.planned_status,
            "generation_event_type": self.generation_event_type,
        }


def compute_structure_hash(
    *,
    generator_name: str,
    generator_version: str,
    fib_model_name: str,
    fib_model_version: str,
    map_cycle_id: str,
    anchor_low_price: Decimal,
    anchor_high_price: Decimal,
) -> str:
    payload = json.dumps(
        {
            "anchor_high_price": str(anchor_high_price),
            "anchor_low_price": str(anchor_low_price),
            "fib_model_name": fib_model_name,
            "fib_model_version": fib_model_version,
            "generator_name": generator_name,
            "generator_version": generator_version,
            "map_cycle_id": map_cycle_id,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def context_status_to_rejection_reason(context_status: str) -> str | None:
    return _CONTEXT_STATUS_TO_REJECTION_REASON.get(context_status)


def _ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _dec(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def fetch_supported_scopes(
    conn: Any,
    *,
    venue: str,
    symbols: list[str],
    quote_currency: str = DEFAULT_QUOTE_CURRENCY,
    fib_trading_horizon: str = DEFAULT_FIB_TRADING_HORIZON,
    primary_interval: str = DEFAULT_PRIMARY_INTERVAL,
    supporting_interval: str = DEFAULT_SUPPORTING_INTERVAL,
) -> list[NativeShortMapScopeSupport]:
    if not symbols:
        return []
    normalized_symbols = [symbol.upper() for symbol in symbols]
    placeholders = ",".join(["%s"] * len(normalized_symbols))
    sql = f"""
    SELECT venue, symbol, quote_currency, fib_trading_horizon,
           primary_interval, supporting_interval, scope_support_state, scope_reason_code
    FROM native_short_map_scope_v1
    WHERE scope_support_state = 'SUPPORTED'
      AND venue = %s
      AND quote_currency = %s
      AND fib_trading_horizon = %s
      AND primary_interval = %s
      AND supporting_interval = %s
      AND symbol IN ({placeholders})
    ORDER BY symbol ASC
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                venue,
                quote_currency,
                fib_trading_horizon,
                primary_interval,
                supporting_interval,
                *normalized_symbols,
            ),
        )
        rows = list(cur.fetchall())

    result: list[NativeShortMapScopeSupport] = []
    for row in rows:
        key = NativeShortMapScopeKey(
            venue=str(row["venue"]),
            symbol=str(row["symbol"]).upper(),
            quote_currency=str(row["quote_currency"]),
            fib_trading_horizon=str(row["fib_trading_horizon"]),
            primary_interval=str(row["primary_interval"]),
            supporting_interval=str(row["supporting_interval"]),
        )
        result.append(
            NativeShortMapScopeSupport(
                key=key,
                support_state=NativeShortMapScopeSupportState(str(row["scope_support_state"])),
                reason_code=row.get("scope_reason_code"),
            )
        )
    return result


def _lock_scope(conn: Any, key: NativeShortMapScopeKey) -> None:
    sql = """
    SELECT scope_id
    FROM native_short_map_scope_v1
    WHERE venue = %s AND symbol = %s AND quote_currency = %s
      AND fib_trading_horizon = %s AND primary_interval = %s AND supporting_interval = %s
    FOR UPDATE
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                key.venue,
                key.symbol,
                key.quote_currency,
                key.fib_trading_horizon,
                key.primary_interval,
                key.supporting_interval,
            ),
        )
        rows = list(cur.fetchall())
    if not rows:
        raise ValueError(f"SCOPE_NOT_FOUND_FOR_WRITE symbol={key.symbol} venue={key.venue}")


def _fetch_maps_for_scope(conn: Any, key: NativeShortMapScopeKey) -> list[NativeShortMapRecord]:
    sql = """
    SELECT map_id, venue, symbol, quote_currency, fib_trading_horizon,
           primary_interval, supporting_interval,
           structure_hash, generator_name, generator_version,
           fib_model_name, fib_model_version,
           published_generation_attempt_id,
           previous_map_id, previous_map_cycle_id, map_cycle_id,
           market_snapshot_ts_utc, published_at_utc,
           anchor_low_ts_utc, anchor_low_price,
           anchor_high_ts_utc, anchor_high_price,
           retrace_ratio, retrace_price,
           fib_ratios_json, target_levels_json,
           invalidation_price, invalidation_rule,
           source_primary_candle_ts_utc, source_support_candle_ts_utc,
           source_primary_ref, source_support_ref,
           source_primary_candle_count, source_support_candle_count,
           map_payload_json
    FROM native_short_map_v1
    WHERE venue = %s AND symbol = %s AND quote_currency = %s
      AND fib_trading_horizon = %s AND primary_interval = %s AND supporting_interval = %s
    ORDER BY map_id ASC
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                key.venue,
                key.symbol,
                key.quote_currency,
                key.fib_trading_horizon,
                key.primary_interval,
                key.supporting_interval,
            ),
        )
        rows = list(cur.fetchall())

    return [
        NativeShortMapRecord(
            map_id=int(row["map_id"]),
            key=key,
            published_at_utc=_ensure_utc(row["published_at_utc"]) or datetime.now(UTC),
            structure_hash=str(row["structure_hash"]),
            generator_name=str(row["generator_name"]),
            generator_version=str(row["generator_version"]),
            fib_model_name=str(row["fib_model_name"]),
            fib_model_version=str(row["fib_model_version"]),
            published_generation_attempt_id=str(row["published_generation_attempt_id"]),
            previous_map_id=(
                int(row["previous_map_id"]) if row.get("previous_map_id") is not None else None
            ),
            previous_map_cycle_id=row.get("previous_map_cycle_id"),
            map_cycle_id=row.get("map_cycle_id"),
            market_snapshot_ts_utc=_ensure_utc(row.get("market_snapshot_ts_utc")),
            anchor_low_ts_utc=_ensure_utc(row.get("anchor_low_ts_utc")),
            anchor_low_price=_dec(row.get("anchor_low_price")),
            anchor_high_ts_utc=_ensure_utc(row.get("anchor_high_ts_utc")),
            anchor_high_price=_dec(row.get("anchor_high_price")),
            retrace_ratio=_dec(row.get("retrace_ratio")),
            retrace_price=_dec(row.get("retrace_price")),
            fib_ratios_json=row.get("fib_ratios_json") or "[]",
            target_levels_json=row.get("target_levels_json") or "[]",
            invalidation_price=_dec(row.get("invalidation_price")),
            invalidation_rule=row.get("invalidation_rule") or "",
            source_primary_candle_ts_utc=_ensure_utc(row.get("source_primary_candle_ts_utc")),
            source_support_candle_ts_utc=_ensure_utc(row.get("source_support_candle_ts_utc")),
            source_primary_ref=row.get("source_primary_ref") or "",
            source_support_ref=row.get("source_support_ref") or "",
            source_primary_candle_count=int(row.get("source_primary_candle_count") or 0),
            source_support_candle_count=int(row.get("source_support_candle_count") or 0),
            map_payload_json=row.get("map_payload_json") or "{}",
        )
        for row in rows
    ]


def _fetch_generation_events_for_scope(
    conn: Any,
    key: NativeShortMapScopeKey,
) -> list[NativeShortMapGenerationEvent]:
    sql = """
    SELECT generation_event_id, venue, symbol, quote_currency, fib_trading_horizon,
           primary_interval, supporting_interval,
           generation_attempt_id, event_type, event_ts_utc,
           reason_code, map_id, trigger_type,
           candidate_map_cycle_id, candidate_previous_map_id,
           candidate_primary_lifecycle_state, candidate_current_map_status,
           latest_primary_close_ts_utc, latest_support_close_ts_utc,
           latest_primary_close_price,
           source_primary_ref, source_support_ref,
           source_primary_candle_count, source_support_candle_count
    FROM native_short_map_generation_event_v1
    WHERE venue = %s AND symbol = %s AND quote_currency = %s
      AND fib_trading_horizon = %s AND primary_interval = %s AND supporting_interval = %s
    ORDER BY generation_event_id ASC
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                key.venue,
                key.symbol,
                key.quote_currency,
                key.fib_trading_horizon,
                key.primary_interval,
                key.supporting_interval,
            ),
        )
        rows = list(cur.fetchall())

    return [
        NativeShortMapGenerationEvent(
            generation_event_id=int(row["generation_event_id"]),
            key=key,
            attempt_id=str(row["generation_attempt_id"]),
            event_type=NativeShortMapGenerationEventType(str(row["event_type"])),
            event_ts_utc=_ensure_utc(row["event_ts_utc"]) or datetime.now(UTC),
            reason_code=row.get("reason_code"),
            map_id=int(row["map_id"]) if row.get("map_id") is not None else None,
            trigger_type=row.get("trigger_type"),
            candidate_map_cycle_id=row.get("candidate_map_cycle_id"),
            candidate_previous_map_id=(
                int(row["candidate_previous_map_id"])
                if row.get("candidate_previous_map_id") is not None
                else None
            ),
            candidate_primary_lifecycle_state=row.get("candidate_primary_lifecycle_state"),
            candidate_current_map_status=row.get("candidate_current_map_status"),
            latest_primary_close_ts_utc=_ensure_utc(row.get("latest_primary_close_ts_utc")),
            latest_support_close_ts_utc=_ensure_utc(row.get("latest_support_close_ts_utc")),
            latest_primary_close_price=_dec(row.get("latest_primary_close_price")),
            source_primary_ref=row.get("source_primary_ref"),
            source_support_ref=row.get("source_support_ref"),
            source_primary_candle_count=(
                int(row["source_primary_candle_count"])
                if row.get("source_primary_candle_count") is not None
                else None
            ),
            source_support_candle_count=(
                int(row["source_support_candle_count"])
                if row.get("source_support_candle_count") is not None
                else None
            ),
        )
        for row in rows
    ]


def _fetch_lifecycle_events_for_map_ids(
    conn: Any,
    map_ids: list[int],
) -> list[NativeShortMapLifecycleEvent]:
    if not map_ids:
        return []
    placeholders = ",".join(["%s"] * len(map_ids))
    sql = f"""
    SELECT lifecycle_event_id, map_id, lifecycle_event_type, event_ts_utc,
           reason_code, successor_map_id,
           observed_current_price, observed_max_high_since_anchor, observed_min_low_since_anchor,
           latest_primary_close_ts_utc, latest_support_close_ts_utc,
           observer_name, observer_version
    FROM native_short_map_lifecycle_event_v1
    WHERE map_id IN ({placeholders})
    ORDER BY lifecycle_event_id ASC
    """
    with conn.cursor() as cur:
        cur.execute(sql, map_ids)
        rows = list(cur.fetchall())

    return [
        NativeShortMapLifecycleEvent(
            lifecycle_event_id=int(row["lifecycle_event_id"]),
            map_id=int(row["map_id"]),
            event_type=NativeShortMapLifecycleEventType(str(row["lifecycle_event_type"])),
            event_ts_utc=_ensure_utc(row["event_ts_utc"]) or datetime.now(UTC),
            reason_code=row.get("reason_code"),
            successor_map_id=(
                int(row["successor_map_id"]) if row.get("successor_map_id") is not None else None
            ),
            observed_current_price=_dec(row.get("observed_current_price")),
            observed_max_high_since_anchor=_dec(row.get("observed_max_high_since_anchor")),
            observed_min_low_since_anchor=_dec(row.get("observed_min_low_since_anchor")),
            latest_primary_close_ts_utc=_ensure_utc(row.get("latest_primary_close_ts_utc")),
            latest_support_close_ts_utc=_ensure_utc(row.get("latest_support_close_ts_utc")),
            observer_name=row.get("observer_name"),
            observer_version=row.get("observer_version"),
        )
        for row in rows
    ]


def _latest_published_event_for_map(
    events: list[NativeShortMapGenerationEvent],
    *,
    map_id: int,
) -> NativeShortMapGenerationEvent | None:
    matches = [
        event
        for event in events
        if event.event_type == NativeShortMapGenerationEventType.PUBLISHED and event.map_id == map_id
    ]
    return max(matches, key=lambda event: event.generation_event_id) if matches else None


def _latest_authoritative_rejected_event(
    events: list[NativeShortMapGenerationEvent],
    *,
    reason_code: str,
) -> NativeShortMapGenerationEvent | None:
    authoritative_events = [
        event
        for event in events
        if event.event_type
        in {
            NativeShortMapGenerationEventType.PUBLISHED,
            NativeShortMapGenerationEventType.REJECTED,
            NativeShortMapGenerationEventType.FAILED,
        }
    ]
    latest = (
        max(authoritative_events, key=lambda event: event.generation_event_id)
        if authoritative_events
        else None
    )
    if (
        latest is not None
        and latest.event_type == NativeShortMapGenerationEventType.REJECTED
        and latest.reason_code == reason_code
    ):
        return latest
    return None


def _find_current_active_map(
    maps: list[NativeShortMapRecord],
    lifecycle_events: list[NativeShortMapLifecycleEvent],
) -> NativeShortMapRecord | None:
    terminal_map_ids = {
        event.map_id for event in lifecycle_events if event.event_type in _TERMINAL_LIFECYCLE_TYPES
    }
    active_maps = [item for item in maps if item.map_id not in terminal_map_ids]
    return max(active_maps, key=lambda item: (item.published_at_utc, item.map_id)) if active_maps else None


def _insert_generation_event(
    conn: Any,
    *,
    key: NativeShortMapScopeKey,
    attempt_id: str,
    event_type: NativeShortMapGenerationEventType,
    event_ts_utc: datetime,
    reason_code: str | None = None,
    reason_detail: str | None = None,
    map_id: int | None = None,
    trigger_type: str | None = None,
    candidate_map_cycle_id: str | None = None,
    candidate_previous_map_id: int | None = None,
    candidate_primary_lifecycle_state: str | None = None,
    candidate_current_map_status: str | None = None,
    latest_primary_close_ts_utc: datetime | None = None,
    latest_support_close_ts_utc: datetime | None = None,
    latest_primary_close_price: Decimal | None = None,
    source_primary_ref: str | None = None,
    source_support_ref: str | None = None,
    source_primary_candle_count: int | None = None,
    source_support_candle_count: int | None = None,
) -> int:
    sql = """
    INSERT INTO native_short_map_generation_event_v1 (
        venue, symbol, quote_currency, fib_trading_horizon,
        primary_interval, supporting_interval,
        generation_attempt_id, event_type, event_ts_utc,
        reason_code, reason_detail, trigger_type,
        candidate_map_cycle_id, candidate_previous_map_id,
        candidate_primary_lifecycle_state, candidate_current_map_status,
        latest_primary_close_ts_utc, latest_support_close_ts_utc,
        latest_primary_close_price,
        source_primary_ref, source_support_ref,
        source_primary_candle_count, source_support_candle_count,
        map_id
    ) VALUES (
        %s, %s, %s, %s, %s, %s,
        %s, %s, %s,
        %s, %s, %s,
        %s, %s,
        %s, %s,
        %s, %s,
        %s,
        %s, %s,
        %s, %s,
        %s
    )
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                key.venue,
                key.symbol,
                key.quote_currency,
                key.fib_trading_horizon,
                key.primary_interval,
                key.supporting_interval,
                attempt_id,
                event_type.value,
                event_ts_utc,
                reason_code,
                reason_detail,
                trigger_type,
                candidate_map_cycle_id,
                candidate_previous_map_id,
                candidate_primary_lifecycle_state,
                candidate_current_map_status,
                latest_primary_close_ts_utc,
                latest_support_close_ts_utc,
                str(latest_primary_close_price) if latest_primary_close_price is not None else None,
                source_primary_ref,
                source_support_ref,
                source_primary_candle_count,
                source_support_candle_count,
                map_id,
            ),
        )
        return int(cur.lastrowid)


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _insert_map_row(
    conn: Any,
    *,
    key: NativeShortMapScopeKey,
    context_row: NativeShortContextRow,
    attempt_id: str,
    structure_hash: str,
    now_utc: datetime,
    previous_map_id: int | None,
    previous_map_cycle_id: str | None,
) -> int:
    fib_ratios_json = _json_dumps(
        {
            "breakout_gate": (
                str(context_row.breakout_gate_price)
                if context_row.breakout_gate_price is not None
                else None
            ),
            "ext_1_272": (
                str(context_row.ext_1_272_price)
                if context_row.ext_1_272_price is not None
                else None
            ),
            "ext_1_618": (
                str(context_row.ext_1_618_price)
                if context_row.ext_1_618_price is not None
                else None
            ),
            "ext_2_000": (
                str(context_row.ext_2_000_price)
                if context_row.ext_2_000_price is not None
                else None
            ),
            "reload_r382": (
                str(context_row.reload_r382_price)
                if context_row.reload_r382_price is not None
                else None
            ),
            "reload_r500": (
                str(context_row.reload_r500_price)
                if context_row.reload_r500_price is not None
                else None
            ),
            "reload_r618": (
                str(context_row.reload_r618_price)
                if context_row.reload_r618_price is not None
                else None
            ),
            "reload_r786": (
                str(context_row.reload_r786_price)
                if context_row.reload_r786_price is not None
                else None
            ),
        }
    )
    target_levels_json = _json_dumps(
        {
            "active": [str(value) for value in context_row.active_target_levels],
            "previous": [str(value) for value in context_row.previous_target_levels],
        }
    )
    map_payload_json = _json_dumps(context_row.to_csv_row())
    sql = """
    INSERT INTO native_short_map_v1 (
        venue, symbol, quote_currency, fib_trading_horizon,
        primary_interval, supporting_interval,
        map_schema_version, generator_name, generator_version,
        fib_model_name, fib_model_version,
        structure_hash, published_generation_attempt_id,
        market_snapshot_ts_utc, published_at_utc,
        map_cycle_id, previous_map_id, previous_map_cycle_id,
        anchor_low_ts_utc, anchor_low_price,
        anchor_high_ts_utc, anchor_high_price,
        fib_ratios_json, target_levels_json,
        invalidation_price, invalidation_rule,
        source_primary_candle_ts_utc, source_support_candle_ts_utc,
        source_primary_ref, source_support_ref,
        source_primary_candle_count, source_support_candle_count,
        map_payload_json
    ) VALUES (
        %s, %s, %s, %s, %s, %s,
        'native_short_map_v1', %s, %s,
        %s, %s,
        %s, %s,
        %s, %s,
        %s, %s, %s,
        %s, %s,
        %s, %s,
        %s, %s,
        %s, %s,
        %s, %s,
        %s, %s,
        %s, %s,
        %s
    )
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                key.venue,
                key.symbol,
                key.quote_currency,
                key.fib_trading_horizon,
                key.primary_interval,
                key.supporting_interval,
                GENERATOR_NAME,
                GENERATOR_VERSION,
                FIB_MODEL_NAME,
                FIB_MODEL_VERSION,
                structure_hash,
                attempt_id,
                context_row.latest_primary_close_ts_utc,
                now_utc,
                context_row.map_cycle_id,
                previous_map_id,
                previous_map_cycle_id,
                context_row.anchor_start_ts_utc,
                str(context_row.anchor_low_price)
                if context_row.anchor_low_price is not None
                else None,
                context_row.anchor_end_ts_utc,
                str(context_row.anchor_high_price)
                if context_row.anchor_high_price is not None
                else None,
                fib_ratios_json,
                target_levels_json,
                str(context_row.invalidation_price)
                if context_row.invalidation_price is not None
                else None,
                "ANCHOR_LOW_BREAK",
                context_row.latest_primary_close_ts_utc,
                context_row.latest_support_close_ts_utc,
                context_row.source_primary_ref,
                context_row.source_support_ref,
                0,
                0,
                map_payload_json,
            ),
        )
        return int(cur.lastrowid)


def _insert_lifecycle_event(
    conn: Any,
    *,
    map_id: int,
    event_type: NativeShortMapLifecycleEventType,
    event_ts_utc: datetime,
    successor_map_id: int | None = None,
    reason_code: str | None = None,
    latest_primary_close_ts_utc: datetime | None = None,
    latest_support_close_ts_utc: datetime | None = None,
) -> int:
    sql = """
    INSERT INTO native_short_map_lifecycle_event_v1 (
        map_id, lifecycle_event_type, successor_map_id,
        event_ts_utc, reason_code,
        latest_primary_close_ts_utc, latest_support_close_ts_utc,
        observer_name, observer_version
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                map_id,
                event_type.value,
                successor_map_id,
                event_ts_utc,
                reason_code,
                latest_primary_close_ts_utc,
                latest_support_close_ts_utc,
                GENERATOR_NAME,
                GENERATOR_VERSION,
            ),
        )
        return int(cur.lastrowid)


def _new_map_record(
    *,
    map_id: int,
    key: NativeShortMapScopeKey,
    context_row: NativeShortContextRow,
    attempt_id: str,
    structure_hash: str,
    now_utc: datetime,
    previous_map_id: int | None,
    previous_map_cycle_id: str | None,
) -> NativeShortMapRecord:
    return NativeShortMapRecord(
        map_id=map_id,
        key=key,
        published_at_utc=now_utc,
        structure_hash=structure_hash,
        generator_name=GENERATOR_NAME,
        generator_version=GENERATOR_VERSION,
        fib_model_name=FIB_MODEL_NAME,
        fib_model_version=FIB_MODEL_VERSION,
        published_generation_attempt_id=attempt_id,
        previous_map_id=previous_map_id,
        previous_map_cycle_id=previous_map_cycle_id,
        map_cycle_id=context_row.map_cycle_id,
        market_snapshot_ts_utc=context_row.latest_primary_close_ts_utc,
        anchor_low_ts_utc=context_row.anchor_start_ts_utc,
        anchor_low_price=context_row.anchor_low_price,
        anchor_high_ts_utc=context_row.anchor_end_ts_utc,
        anchor_high_price=context_row.anchor_high_price,
        invalidation_price=context_row.invalidation_price,
        invalidation_rule="ANCHOR_LOW_BREAK",
        source_primary_candle_ts_utc=context_row.latest_primary_close_ts_utc,
        source_support_candle_ts_utc=context_row.latest_support_close_ts_utc,
        source_primary_ref=context_row.source_primary_ref,
        source_support_ref=context_row.source_support_ref,
        map_payload_json=_json_dumps(context_row.to_csv_row()),
    )


def materialize_scope_symbol(
    conn: Any,
    *,
    scope_support: NativeShortMapScopeSupport,
    context_row: NativeShortContextRow,
    now_utc: datetime,
    write: bool,
) -> ScopeMaterializationResult:
    key = scope_support.key
    symbol = key.symbol
    if scope_support.support_state != NativeShortMapScopeSupportState.SUPPORTED:
        return ScopeMaterializationResult(
            symbol=symbol,
            attempted=False,
            status="skipped",
            dry_run=not write,
            reason_code=REASON_SCOPE_NOT_SUPPORTED,
            detail=scope_support.reason_code,
        )

    if write:
        _lock_scope(conn, key)

    existing_maps = _fetch_maps_for_scope(conn, key)
    existing_generation_events = _fetch_generation_events_for_scope(conn, key)
    existing_lifecycle_events = _fetch_lifecycle_events_for_map_ids(
        conn,
        [item.map_id for item in existing_maps],
    )
    validate_native_short_map_write_intent(
        scope_support=scope_support,
        maps=existing_maps,
        generation_events=existing_generation_events,
        lifecycle_events=existing_lifecycle_events,
    )

    if context_row.context_status != STATUS_AVAILABLE:
        reason_code = (
            context_status_to_rejection_reason(context_row.context_status)
            or "CANDLES_INSUFFICIENT"
        )
        prior_rejection = _latest_authoritative_rejected_event(
            existing_generation_events,
            reason_code=reason_code,
        )
        if prior_rejection is not None:
            return ScopeMaterializationResult(
                symbol=symbol,
                attempted=True,
                status="skipped",
                dry_run=not write,
                generation_attempt_id=prior_rejection.attempt_id,
                generation_event_ids=[prior_rejection.generation_event_id],
                reason_code=REASON_PRIOR_REJECTION_UNCHANGED,
                detail=context_row.context_status,
                generation_event_type=NativeShortMapGenerationEventType.REJECTED.value,
            )
        if not write:
            return ScopeMaterializationResult(
                symbol=symbol,
                attempted=True,
                status="skipped",
                dry_run=True,
                reason_code=REASON_DRY_RUN,
                detail=context_row.context_status,
                planned_status="skipped",
                generation_event_type=NativeShortMapGenerationEventType.REJECTED.value,
            )

        attempt_id = str(uuid.uuid4())
        started_event_id = _insert_generation_event(
            conn,
            key=key,
            attempt_id=attempt_id,
            event_type=NativeShortMapGenerationEventType.ATTEMPT_STARTED,
            event_ts_utc=now_utc,
            trigger_type=TRIGGER_TYPE,
            latest_primary_close_ts_utc=context_row.latest_primary_close_ts_utc,
            latest_support_close_ts_utc=context_row.latest_support_close_ts_utc,
            source_primary_ref=context_row.source_primary_ref,
            source_support_ref=context_row.source_support_ref,
        )
        rejected_event_id = _insert_generation_event(
            conn,
            key=key,
            attempt_id=attempt_id,
            event_type=NativeShortMapGenerationEventType.REJECTED,
            event_ts_utc=now_utc,
            reason_code=reason_code,
            reason_detail=context_row.context_status,
            candidate_current_map_status=context_row.current_map_status,
            latest_primary_close_ts_utc=context_row.latest_primary_close_ts_utc,
            latest_support_close_ts_utc=context_row.latest_support_close_ts_utc,
            source_primary_ref=context_row.source_primary_ref,
            source_support_ref=context_row.source_support_ref,
        )
        new_generation_events = [
            NativeShortMapGenerationEvent(
                generation_event_id=started_event_id,
                key=key,
                attempt_id=attempt_id,
                event_type=NativeShortMapGenerationEventType.ATTEMPT_STARTED,
                event_ts_utc=now_utc,
            ),
            NativeShortMapGenerationEvent(
                generation_event_id=rejected_event_id,
                key=key,
                attempt_id=attempt_id,
                event_type=NativeShortMapGenerationEventType.REJECTED,
                event_ts_utc=now_utc,
                reason_code=reason_code,
            ),
        ]
        validate_native_short_map_write_intent(
            scope_support=scope_support,
            maps=existing_maps,
            generation_events=existing_generation_events + new_generation_events,
            lifecycle_events=existing_lifecycle_events,
        )
        return ScopeMaterializationResult(
            symbol=symbol,
            attempted=True,
            status="skipped",
            dry_run=False,
            generation_attempt_id=attempt_id,
            generation_event_ids=[started_event_id, rejected_event_id],
            reason_code=reason_code,
            detail=context_row.context_status,
            generation_event_type=NativeShortMapGenerationEventType.REJECTED.value,
        )

    if context_row.anchor_low_price is None or context_row.anchor_high_price is None:
        raise ValueError(f"AVAILABLE_CONTEXT_MISSING_ANCHORS symbol={symbol}")

    structure_hash = compute_structure_hash(
        generator_name=GENERATOR_NAME,
        generator_version=GENERATOR_VERSION,
        fib_model_name=FIB_MODEL_NAME,
        fib_model_version=FIB_MODEL_VERSION,
        map_cycle_id=context_row.map_cycle_id,
        anchor_low_price=context_row.anchor_low_price,
        anchor_high_price=context_row.anchor_high_price,
    )
    existing_same_hash = next(
        (
            item
            for item in existing_maps
            if item.generator_name == GENERATOR_NAME
            and item.generator_version == GENERATOR_VERSION
            and item.structure_hash == structure_hash
        ),
        None,
    )
    if existing_same_hash is not None:
        published_event = _latest_published_event_for_map(
            existing_generation_events,
            map_id=existing_same_hash.map_id,
        )
        if published_event is None:
            raise ValueError(
                "EXISTING_MAP_PUBLISHED_EVENT_MISSING "
                f"symbol={symbol} map_id={existing_same_hash.map_id}"
            )
        return ScopeMaterializationResult(
            symbol=symbol,
            attempted=True,
            status="skipped",
            dry_run=not write,
            map_id=existing_same_hash.map_id,
            generation_attempt_id=published_event.attempt_id,
            generation_event_ids=[published_event.generation_event_id],
            structure_hash=structure_hash,
            reason_code=REASON_STRUCTURE_UNCHANGED,
            generation_event_type=NativeShortMapGenerationEventType.PUBLISHED.value,
        )

    if not write:
        return ScopeMaterializationResult(
            symbol=symbol,
            attempted=True,
            status="skipped",
            dry_run=True,
            structure_hash=structure_hash,
            reason_code=REASON_DRY_RUN,
            planned_status="published",
            generation_event_type=NativeShortMapGenerationEventType.PUBLISHED.value,
        )

    current_active_map = _find_current_active_map(existing_maps, existing_lifecycle_events)
    previous_map_id = current_active_map.map_id if current_active_map is not None else None
    previous_map_cycle_id = current_active_map.map_cycle_id if current_active_map is not None else None
    attempt_id = str(uuid.uuid4())
    started_event_id = _insert_generation_event(
        conn,
        key=key,
        attempt_id=attempt_id,
        event_type=NativeShortMapGenerationEventType.ATTEMPT_STARTED,
        event_ts_utc=now_utc,
        trigger_type=TRIGGER_TYPE,
        candidate_map_cycle_id=context_row.map_cycle_id,
        candidate_previous_map_id=previous_map_id,
        candidate_primary_lifecycle_state=context_row.primary_4h_lifecycle_state,
        candidate_current_map_status=context_row.current_map_status,
        latest_primary_close_ts_utc=context_row.latest_primary_close_ts_utc,
        latest_support_close_ts_utc=context_row.latest_support_close_ts_utc,
        latest_primary_close_price=context_row.latest_primary_close_price,
        source_primary_ref=context_row.source_primary_ref,
        source_support_ref=context_row.source_support_ref,
    )
    new_map_id = _insert_map_row(
        conn,
        key=key,
        context_row=context_row,
        attempt_id=attempt_id,
        structure_hash=structure_hash,
        now_utc=now_utc,
        previous_map_id=previous_map_id,
        previous_map_cycle_id=previous_map_cycle_id,
    )
    published_event_id = _insert_generation_event(
        conn,
        key=key,
        attempt_id=attempt_id,
        event_type=NativeShortMapGenerationEventType.PUBLISHED,
        event_ts_utc=now_utc,
        map_id=new_map_id,
        candidate_map_cycle_id=context_row.map_cycle_id,
        candidate_previous_map_id=previous_map_id,
        candidate_primary_lifecycle_state=context_row.primary_4h_lifecycle_state,
        candidate_current_map_status=context_row.current_map_status,
        latest_primary_close_ts_utc=context_row.latest_primary_close_ts_utc,
        latest_support_close_ts_utc=context_row.latest_support_close_ts_utc,
        latest_primary_close_price=context_row.latest_primary_close_price,
        source_primary_ref=context_row.source_primary_ref,
        source_support_ref=context_row.source_support_ref,
    )
    activated_lifecycle_id = _insert_lifecycle_event(
        conn,
        map_id=new_map_id,
        event_type=NativeShortMapLifecycleEventType.ACTIVATED,
        event_ts_utc=now_utc,
        latest_primary_close_ts_utc=context_row.latest_primary_close_ts_utc,
        latest_support_close_ts_utc=context_row.latest_support_close_ts_utc,
    )
    lifecycle_event_ids = [activated_lifecycle_id]
    new_lifecycle_events = [
        NativeShortMapLifecycleEvent(
            lifecycle_event_id=activated_lifecycle_id,
            map_id=new_map_id,
            event_type=NativeShortMapLifecycleEventType.ACTIVATED,
            event_ts_utc=now_utc,
        )
    ]
    if current_active_map is not None:
        superseded_lifecycle_id = _insert_lifecycle_event(
            conn,
            map_id=current_active_map.map_id,
            event_type=NativeShortMapLifecycleEventType.SUPERSEDED,
            event_ts_utc=now_utc,
            successor_map_id=new_map_id,
            reason_code="NEW_NATIVE_SHORT_MAP_PUBLISHED",
        )
        lifecycle_event_ids.append(superseded_lifecycle_id)
        new_lifecycle_events.append(
            NativeShortMapLifecycleEvent(
                lifecycle_event_id=superseded_lifecycle_id,
                map_id=current_active_map.map_id,
                event_type=NativeShortMapLifecycleEventType.SUPERSEDED,
                event_ts_utc=now_utc,
                reason_code="NEW_NATIVE_SHORT_MAP_PUBLISHED",
                successor_map_id=new_map_id,
            )
        )

    new_map = _new_map_record(
        map_id=new_map_id,
        key=key,
        context_row=context_row,
        attempt_id=attempt_id,
        structure_hash=structure_hash,
        now_utc=now_utc,
        previous_map_id=previous_map_id,
        previous_map_cycle_id=previous_map_cycle_id,
    )
    new_generation_events = [
        NativeShortMapGenerationEvent(
            generation_event_id=started_event_id,
            key=key,
            attempt_id=attempt_id,
            event_type=NativeShortMapGenerationEventType.ATTEMPT_STARTED,
            event_ts_utc=now_utc,
        ),
        NativeShortMapGenerationEvent(
            generation_event_id=published_event_id,
            key=key,
            attempt_id=attempt_id,
            event_type=NativeShortMapGenerationEventType.PUBLISHED,
            event_ts_utc=now_utc,
            map_id=new_map_id,
        ),
    ]
    validate_native_short_map_write_intent(
        scope_support=scope_support,
        maps=existing_maps + [new_map],
        generation_events=existing_generation_events + new_generation_events,
        lifecycle_events=existing_lifecycle_events + new_lifecycle_events,
    )
    return ScopeMaterializationResult(
        symbol=symbol,
        attempted=True,
        status="published",
        dry_run=False,
        map_id=new_map_id,
        generation_attempt_id=attempt_id,
        generation_event_ids=[started_event_id, published_event_id],
        lifecycle_event_ids=lifecycle_event_ids,
        structure_hash=structure_hash,
        generation_event_type=NativeShortMapGenerationEventType.PUBLISHED.value,
    )


# Backward-compatible spelling for source branch references.
materialise_scope_symbol = materialize_scope_symbol
