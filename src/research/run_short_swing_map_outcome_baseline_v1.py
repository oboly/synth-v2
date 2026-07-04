from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Sequence

from src.common.db import get_connection


RUNNER_NAME = "short_swing_map_outcome_baseline_v1"
RUNNER_VERSION = "0.1"
SCHEMA_VERSION = "short_swing_map_outcome_baseline_v1"
DEFAULT_OUTPUT_ROOT = Path("data/research/short_swing_map_outcome_baseline_v1")
DEFAULT_VENUE = "bitvavo"
DEFAULT_QUOTE_CURRENCY = "EUR"
DEFAULT_HORIZON = "SHORT"
DEFAULT_PRIMARY_INTERVAL = "4h"
DEFAULT_SUPPORTING_INTERVAL = "1h"
DEFAULT_FORWARD_CANDLES = 12
FETCH_BATCH_ROWS = 1000
SAMPLE_MODE_PUBLISHED_EVENT = "PUBLISHED_EVENT"
SAMPLE_MODES = (SAMPLE_MODE_PUBLISHED_EVENT,)

SAMPLE_MODE_DESCRIPTIONS = {
    SAMPLE_MODE_PUBLISHED_EVENT: (
        "Samples native map publication moments only, using append-only PUBLISHED "
        "generation events deduplicated by (symbol, event_ts_utc). This is not a "
        "full Profit Plan card baseline across the active map lifecycle."
    ),
}

STATUS_OK = "OK"
STATUS_HISTORY_INCOMPLETE = "HISTORY_INCOMPLETE"
STATUS_DATA_UNAVAILABLE = "DATA_UNAVAILABLE"

OUTCOME_TARGET_FIRST = "TARGET_FIRST"
OUTCOME_INVALIDATION_FIRST = "INVALIDATION_FIRST"
OUTCOME_AMBIGUOUS = "AMBIGUOUS_SAME_CANDLE"
OUTCOME_NO_TOUCH = "NO_TOUCH"
OUTCOME_DATA_UNAVAILABLE = "DATA_UNAVAILABLE"

SOURCE_TABLE_INVENTORY: tuple[dict[str, Any], ...] = (
    {
        "table": "native_short_map_v1",
        "historical_role": "immutable_published_map_payload",
        "primary_key": ("map_id",),
        "map_cycle_lineage": ("map_cycle_id", "previous_map_id", "previous_map_cycle_id"),
        "effective_or_event_timestamps": ("published_at_utc", "market_snapshot_ts_utc"),
        "observable_or_recorded_timestamps": ("created_at_utc",),
        "used_for_historical_reconstruction": True,
    },
    {
        "table": "native_short_map_generation_event_v1",
        "historical_role": "append_only_generation_attempt_ledger",
        "primary_key": ("generation_event_id",),
        "map_cycle_lineage": (
            "generation_attempt_id",
            "candidate_map_cycle_id",
            "candidate_previous_map_id",
            "map_id",
        ),
        "effective_or_event_timestamps": ("event_ts_utc",),
        "observable_or_recorded_timestamps": ("created_at_utc",),
        "used_for_historical_reconstruction": True,
    },
    {
        "table": "native_short_map_lifecycle_event_v1",
        "historical_role": "append_only_map_lifecycle_ledger",
        "primary_key": ("lifecycle_event_id",),
        "map_cycle_lineage": ("map_id", "successor_map_id"),
        "effective_or_event_timestamps": ("event_ts_utc",),
        "observable_or_recorded_timestamps": ("created_at_utc",),
        "used_for_historical_reconstruction": True,
    },
    {
        "table": "native_short_map_scope_v1",
        "historical_role": "current_scope_registry_not_append_only",
        "primary_key": ("scope_id",),
        "map_cycle_lineage": (),
        "effective_or_event_timestamps": (),
        "observable_or_recorded_timestamps": ("created_at_utc", "updated_at_utc"),
        "used_for_historical_reconstruction": False,
    },
)

KNOWN_BY_T_RULE = (
    "A native row is known by replay timestamp T only when its effective/event "
    "timestamp is <= T and its observable recorded timestamp created_at_utc is <= T. "
    "For native_short_map_v1 the effective timestamp is published_at_utc. For "
    "generation and lifecycle rows the effective timestamp is event_ts_utc. Rows "
    "with older effective timestamps but created_at_utc after T are post-T revisions "
    "and are excluded."
)

FORBIDDEN_HISTORICAL_SOURCES = (
    "native_short_fib_context_rows_v1.csv",
    "fibo_target_map_rows_v1.csv",
    "current_snapshot_csv",
)

SAFETY_MARKERS = {
    "research_only": True,
    "market_only": True,
    "select_only": True,
    "db_writes": 0,
    "broker_private_calls": 0,
    "broker_writes": 0,
    "order_submission": 0,
    "live_orders": 0,
    "decision_gate": "none",
    "execution_planner": "none",
    "executor": "none",
}


@dataclass(frozen=True)
class NativeMapHistoryRow:
    map_id: int
    venue: str
    symbol: str
    quote_currency: str
    fib_trading_horizon: str
    primary_interval: str
    supporting_interval: str
    published_at_utc: datetime
    created_at_utc: datetime
    structure_hash: str
    published_generation_attempt_id: str
    map_cycle_id: str | None
    previous_map_id: int | None
    previous_map_cycle_id: str | None
    anchor_low_ts_utc: datetime | None
    anchor_low_price: Decimal | None
    anchor_high_ts_utc: datetime | None
    anchor_high_price: Decimal | None
    target_levels_json: str
    invalidation_price: Decimal | None
    invalidation_rule: str
    map_payload_json: str


@dataclass(frozen=True)
class GenerationHistoryEvent:
    generation_event_id: int
    venue: str
    symbol: str
    quote_currency: str
    fib_trading_horizon: str
    primary_interval: str
    supporting_interval: str
    generation_attempt_id: str
    event_type: str
    event_ts_utc: datetime
    created_at_utc: datetime
    map_id: int | None
    reason_code: str | None


@dataclass(frozen=True)
class LifecycleHistoryEvent:
    lifecycle_event_id: int
    map_id: int
    lifecycle_event_type: str
    event_ts_utc: datetime
    created_at_utc: datetime
    successor_map_id: int | None
    reason_code: str | None


@dataclass(frozen=True)
class OutcomeCandle:
    symbol: str
    close_ts_utc: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal


@dataclass(frozen=True)
class HistoricalMapChoice:
    status: str
    reason_code: str
    as_of_ts_utc: datetime
    map_row: NativeMapHistoryRow | None
    published_generation_event: GenerationHistoryEvent | None
    latest_lifecycle_event: LifecycleHistoryEvent | None


@dataclass(frozen=True)
class ExtractedMapLevels:
    target_levels: tuple[Decimal, ...]
    reload_levels: tuple[Decimal, ...]
    invalidation_price: Decimal
    direction: str


def parse_ts(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).replace(microsecond=0)


def fmt_ts(value: datetime | None) -> str:
    if value is None:
        return ""
    resolved = value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    return resolved.isoformat().replace("+00:00", "Z")


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _json_loads(value: str) -> Any:
    try:
        return json.loads(value or "null")
    except json.JSONDecodeError:
        return None


def _scope_key(row: NativeMapHistoryRow | GenerationHistoryEvent) -> tuple[str, str, str, str, str, str]:
    return (
        row.venue.upper(),
        row.symbol.upper(),
        row.quote_currency.upper(),
        row.fib_trading_horizon.upper(),
        row.primary_interval,
        row.supporting_interval,
    )


def _known_map_by_t(row: NativeMapHistoryRow, as_of_ts_utc: datetime) -> bool:
    return _utc(row.published_at_utc) <= as_of_ts_utc and _utc(row.created_at_utc) <= as_of_ts_utc


def _known_generation_by_t(row: GenerationHistoryEvent, as_of_ts_utc: datetime) -> bool:
    return _utc(row.event_ts_utc) <= as_of_ts_utc and _utc(row.created_at_utc) <= as_of_ts_utc


def _known_lifecycle_by_t(row: LifecycleHistoryEvent, as_of_ts_utc: datetime) -> bool:
    return _utc(row.event_ts_utc) <= as_of_ts_utc and _utc(row.created_at_utc) <= as_of_ts_utc


def _published_generation_event_known(
    *,
    map_row: NativeMapHistoryRow,
    generation_events: Sequence[GenerationHistoryEvent],
    as_of_ts_utc: datetime,
) -> GenerationHistoryEvent | None:
    map_scope = _scope_key(map_row)
    matches: list[GenerationHistoryEvent] = []
    for event in generation_events:
        if not _known_generation_by_t(event, as_of_ts_utc):
            continue
        if _scope_key(event) != map_scope:
            continue
        if event.event_type != "PUBLISHED":
            continue
        if event.map_id != map_row.map_id:
            continue
        if event.generation_attempt_id != map_row.published_generation_attempt_id:
            continue
        matches.append(event)
    if not matches:
        return None
    return max(matches, key=lambda event: event.generation_event_id)


def build_sample_points_from_generation_events(
    *,
    generation_events: Sequence[GenerationHistoryEvent],
    sample_mode: str,
    venue: str,
    quote_currency: str,
    symbols: Sequence[str],
    start_ts: datetime,
    end_ts: datetime,
    max_samples: int,
) -> list[tuple[str, datetime]]:
    if sample_mode != SAMPLE_MODE_PUBLISHED_EVENT:
        raise ValueError(f"Unsupported sample_mode: {sample_mode}")
    symbol_set = {symbol.upper() for symbol in symbols}
    rows = [
        event
        for event in generation_events
        if event.venue == venue
        and event.quote_currency == quote_currency
        and event.fib_trading_horizon == DEFAULT_HORIZON
        and event.primary_interval == DEFAULT_PRIMARY_INTERVAL
        and event.supporting_interval == DEFAULT_SUPPORTING_INTERVAL
        and event.symbol.upper() in symbol_set
        and event.event_type == "PUBLISHED"
        and start_ts <= _utc(event.event_ts_utc) <= end_ts
        and _utc(event.created_at_utc) <= _utc(event.event_ts_utc)
    ]
    rows.sort(key=lambda event: (event.event_ts_utc, event.symbol, event.generation_event_id))
    deduped: dict[tuple[str, datetime], GenerationHistoryEvent] = {}
    for event in rows:
        key = (event.symbol.upper(), _utc(event.event_ts_utc))
        if key not in deduped:
            deduped[key] = event
    rows = list(deduped.values())
    if max_samples > 0:
        rows = rows[:max_samples]
    return [(event.symbol.upper(), _utc(event.event_ts_utc)) for event in rows]


def discover_default_symbols_from_generation_events(
    *,
    generation_events: Sequence[GenerationHistoryEvent],
    venue: str,
    quote_currency: str,
    start_ts: datetime,
    end_ts: datetime,
    max_symbols: int,
) -> list[str]:
    symbols = {
        event.symbol.upper()
        for event in generation_events
        if event.venue == venue
        and event.quote_currency == quote_currency
        and event.fib_trading_horizon == DEFAULT_HORIZON
        and event.primary_interval == DEFAULT_PRIMARY_INTERVAL
        and event.supporting_interval == DEFAULT_SUPPORTING_INTERVAL
        and event.event_type == "PUBLISHED"
        and start_ts <= _utc(event.event_ts_utc) <= end_ts
        and _utc(event.created_at_utc) <= _utc(event.event_ts_utc)
    }
    ordered = sorted(symbols)
    if max_symbols > 0:
        ordered = ordered[:max_symbols]
    return ordered


def choose_native_map_as_of(
    *,
    symbol: str,
    venue: str,
    quote_currency: str,
    as_of_ts_utc: datetime,
    maps: Sequence[NativeMapHistoryRow],
    generation_events: Sequence[GenerationHistoryEvent],
    lifecycle_events: Sequence[LifecycleHistoryEvent],
) -> HistoricalMapChoice:
    resolved_symbol = symbol.upper()
    resolved_venue = venue.upper()
    resolved_quote = quote_currency.upper()
    known_maps = [
        row
        for row in maps
        if row.symbol.upper() == resolved_symbol
        and row.venue.upper() == resolved_venue
        and row.quote_currency.upper() == resolved_quote
        and row.fib_trading_horizon == DEFAULT_HORIZON
        and row.primary_interval == DEFAULT_PRIMARY_INTERVAL
        and row.supporting_interval == DEFAULT_SUPPORTING_INTERVAL
        and _known_map_by_t(row, as_of_ts_utc)
    ]
    if not known_maps:
        return HistoricalMapChoice(
            status=STATUS_DATA_UNAVAILABLE,
            reason_code="NO_KNOWN_NATIVE_MAP_BY_T",
            as_of_ts_utc=as_of_ts_utc,
            map_row=None,
            published_generation_event=None,
            latest_lifecycle_event=None,
        )

    published_event_by_map = {
        row.map_id: published_event
        for row in known_maps
        if (
            published_event := _published_generation_event_known(
                map_row=row,
                generation_events=generation_events,
                as_of_ts_utc=as_of_ts_utc,
            )
        )
        is not None
    }
    published_known = [row for row in known_maps if row.map_id in published_event_by_map]
    if not published_known:
        return HistoricalMapChoice(
            status=STATUS_HISTORY_INCOMPLETE,
            reason_code="PUBLISHED_GENERATION_EVENT_MISSING_BY_T",
            as_of_ts_utc=as_of_ts_utc,
            map_row=max(known_maps, key=lambda row: (row.published_at_utc, row.map_id)),
            published_generation_event=None,
            latest_lifecycle_event=None,
        )

    known_map_ids = {row.map_id for row in published_known}
    known_lifecycle = [
        event
        for event in lifecycle_events
        if event.map_id in known_map_ids and _known_lifecycle_by_t(event, as_of_ts_utc)
    ]
    latest_lifecycle_by_map: dict[int, LifecycleHistoryEvent] = {}
    for event in sorted(known_lifecycle, key=lambda item: item.lifecycle_event_id):
        latest_lifecycle_by_map[event.map_id] = event

    active_maps = [
        row
        for row in published_known
        if row.map_id not in latest_lifecycle_by_map
        or latest_lifecycle_by_map[row.map_id].lifecycle_event_type == "ACTIVATED"
    ]
    if not active_maps:
        selected_unavailable = max(published_known, key=lambda row: (row.published_at_utc, row.map_id))
        return HistoricalMapChoice(
            status=STATUS_DATA_UNAVAILABLE,
            reason_code="NO_ACTIVE_NATIVE_MAP_BY_T",
            as_of_ts_utc=as_of_ts_utc,
            map_row=selected_unavailable,
            published_generation_event=published_event_by_map[selected_unavailable.map_id],
            latest_lifecycle_event=latest_lifecycle_by_map.get(selected_unavailable.map_id),
        )

    selected = max(active_maps, key=lambda row: (row.published_at_utc, row.map_id))
    return HistoricalMapChoice(
        status=STATUS_OK,
        reason_code="ACTIVE_NATIVE_MAP_KNOWN_BY_T",
        as_of_ts_utc=as_of_ts_utc,
        map_row=selected,
        published_generation_event=published_event_by_map[selected.map_id],
        latest_lifecycle_event=latest_lifecycle_by_map.get(selected.map_id),
    )


def _extract_decimal_list(payload: Any) -> tuple[Decimal, ...]:
    if payload is None:
        return ()
    if isinstance(payload, dict):
        for key in ("price", "target_price", "level_price", "value"):
            parsed = _decimal(payload.get(key))
            if parsed is not None:
                return (parsed,)
        return ()
    if isinstance(payload, (str, int, float, Decimal)):
        parsed = _decimal(payload)
        return () if parsed is None else (parsed,)
    if not isinstance(payload, list):
        return ()
    out: list[Decimal] = []
    for item in payload:
        out.extend(_extract_decimal_list(item))
    return tuple(out)


def extract_map_levels(map_row: NativeMapHistoryRow) -> tuple[ExtractedMapLevels | None, str | None]:
    target_levels = tuple(dict.fromkeys(_extract_decimal_list(_json_loads(map_row.target_levels_json))))
    payload = _json_loads(map_row.map_payload_json)
    reload_levels: tuple[Decimal, ...] = ()
    if isinstance(payload, dict):
        direct_reload_values = [
            payload.get("reload_r382_price"),
            payload.get("reload_r500_price"),
            payload.get("reload_r618_price"),
            payload.get("reload_r786_price"),
            payload.get("reload_r382"),
            payload.get("reload_r500"),
            payload.get("reload_r618"),
            payload.get("reload_r786"),
        ]
        reload_levels = tuple(parsed for parsed in (_decimal(value) for value in direct_reload_values) if parsed is not None)
        if not reload_levels:
            for key in ("reload_levels", "reload_levels_json", "retrace_levels", "retracement_levels"):
                candidate = payload.get(key)
                if isinstance(candidate, str):
                    candidate = _json_loads(candidate)
                reload_levels = _extract_decimal_list(candidate)
                if reload_levels:
                    break
    invalidation = map_row.invalidation_price
    if invalidation is None and isinstance(payload, dict):
        invalidation = _decimal(payload.get("invalidation_price"))

    if not target_levels:
        return None, "TARGET_LEVELS_MISSING_IN_NATIVE_HISTORY"
    if not reload_levels:
        return None, "RELOAD_LEVELS_MISSING_IN_NATIVE_HISTORY"
    if invalidation is None:
        return None, "INVALIDATION_PRICE_MISSING_IN_NATIVE_HISTORY"

    avg_target = sum(target_levels, Decimal("0")) / Decimal(str(len(target_levels)))
    direction = "BULLISH" if avg_target >= invalidation else "BEARISH"
    ordered_targets = tuple(sorted(target_levels, reverse=(direction == "BEARISH")))
    ordered_reload = tuple(sorted(dict.fromkeys(reload_levels), reverse=(direction == "BEARISH")))
    return (
        ExtractedMapLevels(
            target_levels=ordered_targets,
            reload_levels=ordered_reload,
            invalidation_price=invalidation,
            direction=direction,
        ),
        None,
    )


def evaluate_outcome(
    *,
    levels: ExtractedMapLevels,
    candles_after_t: Sequence[OutcomeCandle],
) -> dict[str, Any]:
    if not candles_after_t:
        return {
            "outcome_state": OUTCOME_DATA_UNAVAILABLE,
            "outcome_reason_code": "NO_FORWARD_CANDLES",
            "first_touch_ts_utc": "",
            "first_target_price": "",
            "first_invalidation_price": str(levels.invalidation_price),
            "max_high": "",
            "min_low": "",
            "last_close": "",
        }

    max_high = max(candle.high_price for candle in candles_after_t)
    min_low = min(candle.low_price for candle in candles_after_t)
    for candle in candles_after_t:
        if levels.direction == "BULLISH":
            target_hit = next((target for target in levels.target_levels if candle.high_price >= target), None)
            invalidation_hit = candle.low_price <= levels.invalidation_price
        else:
            target_hit = next((target for target in levels.target_levels if candle.low_price <= target), None)
            invalidation_hit = candle.high_price >= levels.invalidation_price
        if target_hit is not None and invalidation_hit:
            return {
                "outcome_state": OUTCOME_AMBIGUOUS,
                "outcome_reason_code": "TARGET_AND_INVALIDATION_IN_SAME_CANDLE",
                "first_touch_ts_utc": fmt_ts(candle.close_ts_utc),
                "first_target_price": str(target_hit),
                "first_invalidation_price": str(levels.invalidation_price),
                "max_high": str(max_high),
                "min_low": str(min_low),
                "last_close": str(candles_after_t[-1].close_price),
            }
        if target_hit is not None:
            return {
                "outcome_state": OUTCOME_TARGET_FIRST,
                "outcome_reason_code": "TARGET_TOUCHED_BEFORE_INVALIDATION",
                "first_touch_ts_utc": fmt_ts(candle.close_ts_utc),
                "first_target_price": str(target_hit),
                "first_invalidation_price": str(levels.invalidation_price),
                "max_high": str(max_high),
                "min_low": str(min_low),
                "last_close": str(candles_after_t[-1].close_price),
            }
        if invalidation_hit:
            return {
                "outcome_state": OUTCOME_INVALIDATION_FIRST,
                "outcome_reason_code": "INVALIDATION_TOUCHED_BEFORE_TARGET",
                "first_touch_ts_utc": fmt_ts(candle.close_ts_utc),
                "first_target_price": str(levels.target_levels[0]),
                "first_invalidation_price": str(levels.invalidation_price),
                "max_high": str(max_high),
                "min_low": str(min_low),
                "last_close": str(candles_after_t[-1].close_price),
            }
    return {
        "outcome_state": OUTCOME_NO_TOUCH,
        "outcome_reason_code": "NO_TARGET_OR_INVALIDATION_TOUCH_IN_FORWARD_WINDOW",
        "first_touch_ts_utc": "",
        "first_target_price": str(levels.target_levels[0]),
        "first_invalidation_price": str(levels.invalidation_price),
        "max_high": str(max_high),
        "min_low": str(min_low),
        "last_close": str(candles_after_t[-1].close_price),
    }


def _selection_provenance_fields(choice: HistoricalMapChoice) -> dict[str, Any]:
    generation = choice.published_generation_event
    lifecycle = choice.latest_lifecycle_event
    if lifecycle is None:
        lifecycle_status = "NO_LIFECYCLE_ROW_KNOWN_BY_T"
        lifecycle_reason = "ACTIVE_BY_ABSENCE_OF_LIFECYCLE_EVENT_KNOWN_BY_T"
    else:
        lifecycle_status = "LIFECYCLE_ROW_KNOWN_BY_T"
        lifecycle_reason = lifecycle.lifecycle_event_type
    return {
        "selection_reason": choice.reason_code,
        "published_generation_source_table": (
            "native_short_map_generation_event_v1" if generation is not None else ""
        ),
        "published_generation_row_id": "" if generation is None else generation.generation_event_id,
        "published_generation_event_ts_utc": "" if generation is None else fmt_ts(generation.event_ts_utc),
        "published_generation_recorded_ts_utc": "" if generation is None else fmt_ts(generation.created_at_utc),
        "published_generation_provenance_status": (
            "PUBLISHED_GENERATION_ROW_KNOWN_BY_T"
            if generation is not None
            else "PUBLISHED_GENERATION_ROW_UNAVAILABLE_BY_T"
        ),
        "published_generation_provenance_reason": (
            "MAP_PUBLICATION_CONFIRMED_BY_APPEND_ONLY_LEDGER"
            if generation is not None
            else choice.reason_code
        ),
        "lifecycle_source_table": "native_short_map_lifecycle_event_v1" if lifecycle is not None else "",
        "lifecycle_row_id": "" if lifecycle is None else lifecycle.lifecycle_event_id,
        "lifecycle_event_ts_utc": "" if lifecycle is None else fmt_ts(lifecycle.event_ts_utc),
        "lifecycle_recorded_ts_utc": "" if lifecycle is None else fmt_ts(lifecycle.created_at_utc),
        "lifecycle_provenance_status": lifecycle_status,
        "lifecycle_provenance_reason": lifecycle_reason,
    }


def build_baseline_rows(
    *,
    sample_points: Sequence[tuple[str, datetime]],
    venue: str,
    quote_currency: str,
    maps: Sequence[NativeMapHistoryRow],
    generation_events: Sequence[GenerationHistoryEvent],
    lifecycle_events: Sequence[LifecycleHistoryEvent],
    candles_by_symbol: dict[str, list[OutcomeCandle]],
    forward_candles: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for symbol, as_of_ts in sorted(sample_points, key=lambda item: (item[1], item[0])):
        choice = choose_native_map_as_of(
            symbol=symbol,
            venue=venue,
            quote_currency=quote_currency,
            as_of_ts_utc=as_of_ts,
            maps=maps,
            generation_events=generation_events,
            lifecycle_events=lifecycle_events,
        )
        base: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "symbol": symbol.upper(),
            "venue": venue,
            "quote_currency": quote_currency,
            "as_of_ts_utc": fmt_ts(as_of_ts),
            "history_status": choice.status,
            "history_reason_code": choice.reason_code,
            "map_id": "" if choice.map_row is None else choice.map_row.map_id,
            "map_cycle_id": "" if choice.map_row is None else (choice.map_row.map_cycle_id or ""),
            "previous_map_id": "" if choice.map_row is None or choice.map_row.previous_map_id is None else choice.map_row.previous_map_id,
            "previous_map_cycle_id": "" if choice.map_row is None else (choice.map_row.previous_map_cycle_id or ""),
            "published_at_utc": "" if choice.map_row is None else fmt_ts(choice.map_row.published_at_utc),
            "map_created_at_utc": "" if choice.map_row is None else fmt_ts(choice.map_row.created_at_utc),
            "structure_hash": "" if choice.map_row is None else choice.map_row.structure_hash,
            "target_levels_json": "",
            "reload_levels_json": "",
            "invalidation_price": "",
            "map_direction": "",
            "outcome_state": OUTCOME_DATA_UNAVAILABLE,
            "outcome_reason_code": choice.reason_code,
            "first_touch_ts_utc": "",
            "first_target_price": "",
            "first_invalidation_price": "",
            "max_high": "",
            "min_low": "",
            "last_close": "",
            "forward_candle_count": 0,
            "research_only": True,
            **_selection_provenance_fields(choice),
        }
        if choice.status != STATUS_OK or choice.map_row is None:
            rows.append(base)
            continue
        levels, incomplete_reason = extract_map_levels(choice.map_row)
        if levels is None:
            rows.append(
                {
                    **base,
                    "history_status": STATUS_HISTORY_INCOMPLETE,
                    "history_reason_code": incomplete_reason or "HISTORY_PAYLOAD_INCOMPLETE",
                    "outcome_reason_code": incomplete_reason or "HISTORY_PAYLOAD_INCOMPLETE",
                }
            )
            continue
        candles_after_t = [
            candle
            for candle in candles_by_symbol.get(symbol.upper(), [])
            if candle.close_ts_utc > as_of_ts
        ][:forward_candles]
        outcome = evaluate_outcome(levels=levels, candles_after_t=candles_after_t)
        rows.append(
            {
                **base,
                "target_levels_json": json.dumps([str(value) for value in levels.target_levels]),
                "reload_levels_json": json.dumps([str(value) for value in levels.reload_levels]),
                "invalidation_price": str(levels.invalidation_price),
                "map_direction": levels.direction,
                "forward_candle_count": len(candles_after_t),
                **outcome,
            }
        )
    return rows


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return fmt_ts(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_safe(payload), indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(_json_safe(row), sort_keys=True, ensure_ascii=True) + "\n")


def _write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _json_safe(value) for key, value in row.items()})


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_summary_rows(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: Counter[tuple[str, str]] = Counter(
        (str(row.get("history_status") or ""), str(row.get("outcome_state") or ""))
        for row in rows
    )
    return [
        {
            "history_status": history_status,
            "outcome_state": outcome_state,
            "row_count": count,
        }
        for (history_status, outcome_state), count in sorted(grouped.items())
    ]


def deterministic_run_id(
    *,
    venue: str,
    symbols: Sequence[str],
    start_ts: datetime,
    end_ts: datetime,
    forward_candles: int,
    sample_mode: str,
) -> str:
    if sample_mode != SAMPLE_MODE_PUBLISHED_EVENT:
        raise ValueError(f"Unsupported sample_mode: {sample_mode}")
    payload = json.dumps(
        {
            "venue": venue,
            "symbols": sorted(symbols),
            "start_ts": fmt_ts(start_ts),
            "end_ts": fmt_ts(end_ts),
            "forward_candles": forward_candles,
            "sample_mode": sample_mode,
            "runner": RUNNER_NAME,
            "version": RUNNER_VERSION,
        },
        sort_keys=True,
    )
    return "run_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def build_manifest(
    *,
    run_id: str,
    output_dir: Path,
    symbols: Sequence[str],
    start_ts: datetime,
    end_ts: datetime,
    venue: str,
    quote_currency: str,
    forward_candles: int,
    sample_mode: str,
    rows: Sequence[dict[str, Any]],
    artifact_paths: dict[str, Path],
    generated_at_ts_utc: datetime,
) -> dict[str, Any]:
    if sample_mode != SAMPLE_MODE_PUBLISHED_EVENT:
        raise ValueError(f"Unsupported sample_mode: {sample_mode}")
    artifact_hashes = {
        name: _sha256_file(path)
        for name, path in artifact_paths.items()
        if name != "manifest.json" and path.exists()
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "runner_name": RUNNER_NAME,
        "runner_version": RUNNER_VERSION,
        "run_id": run_id,
        "generated_at_ts_utc": fmt_ts(generated_at_ts_utc),
        "output_dir": str(output_dir),
        "scope": {
            "venue": venue,
            "quote_currency": quote_currency,
            "fib_trading_horizon": DEFAULT_HORIZON,
            "primary_interval": DEFAULT_PRIMARY_INTERVAL,
            "supporting_interval": DEFAULT_SUPPORTING_INTERVAL,
            "symbols": sorted(symbols),
            "start_ts_utc": fmt_ts(start_ts),
            "end_ts_utc": fmt_ts(end_ts),
            "forward_candles": forward_candles,
            "sample_mode": sample_mode,
            "sample_mode_description": SAMPLE_MODE_DESCRIPTIONS[sample_mode],
            "sample_mode_boundary": (
                "PUBLISHED_EVENT samples map publication moments only and is not a "
                "full Profit Plan card baseline across the active lifecycle."
            ),
            "sample_point_dedupe_key": ["symbol", "event_ts_utc"],
        },
        "known_by_t_rule": KNOWN_BY_T_RULE,
        "source_table_inventory": list(SOURCE_TABLE_INVENTORY),
        "source_tables_used": [
            "native_short_map_v1",
            "native_short_map_generation_event_v1",
            "native_short_map_lifecycle_event_v1",
            "obs_market_candle",
            "asset",
        ],
        "forbidden_historical_sources": list(FORBIDDEN_HISTORICAL_SOURCES),
        "current_snapshot_csv_usage": "PROHIBITED_FOR_HISTORICAL_RECONSTRUCTION",
        "non_historical_diagnostic_cross_check_used": False,
        "row_counts": {
            "baseline_rows": len(rows),
            "summary_rows": len(build_summary_rows(rows)),
        },
        "history_status_distribution": dict(Counter(str(row.get("history_status") or "") for row in rows)),
        "outcome_state_distribution": dict(Counter(str(row.get("outcome_state") or "") for row in rows)),
        "safety_markers": dict(SAFETY_MARKERS),
        "artifact_sha256": artifact_hashes,
        "manifest_hash_note": "manifest.json hash is computed before embedding artifact_sha256.manifest.json",
    }
    preimage = json.dumps(_json_safe(manifest), sort_keys=True, separators=(",", ":")).encode("utf-8")
    manifest["artifact_sha256"]["manifest.json"] = hashlib.sha256(preimage).hexdigest()
    return manifest


def _fetch_batched(conn: Any, sql: str, params: Sequence[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        while True:
            batch = list(cur.fetchmany(FETCH_BATCH_ROWS))
            if not batch:
                break
            rows.extend(batch)
    return rows


def fetch_symbols(
    conn: Any,
    *,
    venue: str,
    quote_currency: str,
    symbols: list[str] | None,
    start_ts: datetime,
    end_ts: datetime,
    max_symbols: int,
) -> list[str]:
    if symbols:
        return sorted(dict.fromkeys(symbol.upper() for symbol in symbols))
    sql = """
        SELECT DISTINCT symbol
        FROM native_short_map_generation_event_v1
        WHERE venue = %s
          AND quote_currency = %s
          AND fib_trading_horizon = %s
          AND primary_interval = %s
          AND supporting_interval = %s
          AND event_type = 'PUBLISHED'
          AND event_ts_utc >= %s
          AND event_ts_utc <= %s
          AND created_at_utc <= event_ts_utc
        ORDER BY symbol ASC
        LIMIT %s
    """
    rows = _fetch_batched(
        conn,
        sql,
        [
            venue,
            quote_currency,
            DEFAULT_HORIZON,
            DEFAULT_PRIMARY_INTERVAL,
            DEFAULT_SUPPORTING_INTERVAL,
            start_ts,
            end_ts,
            max_symbols,
        ],
    )
    return [str(row["symbol"]).upper() for row in rows]


def fetch_native_maps(
    conn: Any,
    *,
    venue: str,
    quote_currency: str,
    symbols: Sequence[str],
    end_ts: datetime,
) -> list[NativeMapHistoryRow]:
    placeholders = ",".join(["%s"] * len(symbols))
    sql = f"""
        SELECT
            map_id, venue, symbol, quote_currency, fib_trading_horizon,
            primary_interval, supporting_interval, published_at_utc, created_at_utc,
            structure_hash, published_generation_attempt_id, map_cycle_id,
            previous_map_id, previous_map_cycle_id, anchor_low_ts_utc,
            anchor_low_price, anchor_high_ts_utc, anchor_high_price,
            target_levels_json, invalidation_price, invalidation_rule, map_payload_json
        FROM native_short_map_v1
        WHERE venue = %s
          AND quote_currency = %s
          AND fib_trading_horizon = %s
          AND primary_interval = %s
          AND supporting_interval = %s
          AND UPPER(symbol) IN ({placeholders})
          AND published_at_utc <= %s
          AND created_at_utc <= %s
        ORDER BY symbol ASC, published_at_utc ASC, map_id ASC
    """
    rows = _fetch_batched(
        conn,
        sql,
        [venue, quote_currency, DEFAULT_HORIZON, DEFAULT_PRIMARY_INTERVAL, DEFAULT_SUPPORTING_INTERVAL, *symbols, end_ts, end_ts],
    )
    return [
        NativeMapHistoryRow(
            map_id=int(row["map_id"]),
            venue=str(row["venue"]),
            symbol=str(row["symbol"]).upper(),
            quote_currency=str(row["quote_currency"]),
            fib_trading_horizon=str(row["fib_trading_horizon"]),
            primary_interval=str(row["primary_interval"]),
            supporting_interval=str(row["supporting_interval"]),
            published_at_utc=_utc(row["published_at_utc"]),
            created_at_utc=_utc(row["created_at_utc"]),
            structure_hash=str(row["structure_hash"]),
            published_generation_attempt_id=str(row["published_generation_attempt_id"]),
            map_cycle_id=row.get("map_cycle_id"),
            previous_map_id=None if row.get("previous_map_id") is None else int(row["previous_map_id"]),
            previous_map_cycle_id=row.get("previous_map_cycle_id"),
            anchor_low_ts_utc=None if row.get("anchor_low_ts_utc") is None else _utc(row["anchor_low_ts_utc"]),
            anchor_low_price=_decimal(row.get("anchor_low_price")),
            anchor_high_ts_utc=None if row.get("anchor_high_ts_utc") is None else _utc(row["anchor_high_ts_utc"]),
            anchor_high_price=_decimal(row.get("anchor_high_price")),
            target_levels_json=str(row.get("target_levels_json") or "[]"),
            invalidation_price=_decimal(row.get("invalidation_price")),
            invalidation_rule=str(row.get("invalidation_rule") or ""),
            map_payload_json=str(row.get("map_payload_json") or "{}"),
        )
        for row in rows
    ]


def fetch_generation_events(
    conn: Any,
    *,
    venue: str,
    quote_currency: str,
    symbols: Sequence[str],
    end_ts: datetime,
) -> list[GenerationHistoryEvent]:
    placeholders = ",".join(["%s"] * len(symbols))
    sql = f"""
        SELECT
            generation_event_id, venue, symbol, quote_currency, fib_trading_horizon,
            primary_interval, supporting_interval, generation_attempt_id, event_type,
            event_ts_utc, created_at_utc, map_id, reason_code
        FROM native_short_map_generation_event_v1
        WHERE venue = %s
          AND quote_currency = %s
          AND fib_trading_horizon = %s
          AND primary_interval = %s
          AND supporting_interval = %s
          AND UPPER(symbol) IN ({placeholders})
          AND event_ts_utc <= %s
          AND created_at_utc <= %s
        ORDER BY symbol ASC, generation_event_id ASC
    """
    rows = _fetch_batched(
        conn,
        sql,
        [venue, quote_currency, DEFAULT_HORIZON, DEFAULT_PRIMARY_INTERVAL, DEFAULT_SUPPORTING_INTERVAL, *symbols, end_ts, end_ts],
    )
    return [
        GenerationHistoryEvent(
            generation_event_id=int(row["generation_event_id"]),
            venue=str(row["venue"]),
            symbol=str(row["symbol"]).upper(),
            quote_currency=str(row["quote_currency"]),
            fib_trading_horizon=str(row["fib_trading_horizon"]),
            primary_interval=str(row["primary_interval"]),
            supporting_interval=str(row["supporting_interval"]),
            generation_attempt_id=str(row["generation_attempt_id"]),
            event_type=str(row["event_type"]),
            event_ts_utc=_utc(row["event_ts_utc"]),
            created_at_utc=_utc(row["created_at_utc"]),
            map_id=None if row.get("map_id") is None else int(row["map_id"]),
            reason_code=row.get("reason_code"),
        )
        for row in rows
    ]


def fetch_lifecycle_events(conn: Any, *, map_ids: Sequence[int], end_ts: datetime) -> list[LifecycleHistoryEvent]:
    if not map_ids:
        return []
    placeholders = ",".join(["%s"] * len(map_ids))
    sql = f"""
        SELECT
            lifecycle_event_id, map_id, lifecycle_event_type, event_ts_utc,
            created_at_utc, successor_map_id, reason_code
        FROM native_short_map_lifecycle_event_v1
        WHERE map_id IN ({placeholders})
          AND event_ts_utc <= %s
          AND created_at_utc <= %s
        ORDER BY map_id ASC, lifecycle_event_id ASC
    """
    rows = _fetch_batched(conn, sql, [*map_ids, end_ts, end_ts])
    return [
        LifecycleHistoryEvent(
            lifecycle_event_id=int(row["lifecycle_event_id"]),
            map_id=int(row["map_id"]),
            lifecycle_event_type=str(row["lifecycle_event_type"]),
            event_ts_utc=_utc(row["event_ts_utc"]),
            created_at_utc=_utc(row["created_at_utc"]),
            successor_map_id=None if row.get("successor_map_id") is None else int(row["successor_map_id"]),
            reason_code=row.get("reason_code"),
        )
        for row in rows
    ]


def fetch_sample_points(
    conn: Any,
    *,
    sample_mode: str,
    venue: str,
    quote_currency: str,
    symbols: Sequence[str],
    start_ts: datetime,
    end_ts: datetime,
    max_samples: int,
) -> list[tuple[str, datetime]]:
    if sample_mode != SAMPLE_MODE_PUBLISHED_EVENT:
        raise ValueError(f"Unsupported sample_mode: {sample_mode}")
    placeholders = ",".join(["%s"] * len(symbols))
    limit_clause = "" if max_samples <= 0 else "LIMIT %s"
    params: list[Any] = [
        venue,
        quote_currency,
        DEFAULT_HORIZON,
        DEFAULT_PRIMARY_INTERVAL,
        DEFAULT_SUPPORTING_INTERVAL,
        *symbols,
        start_ts,
        end_ts,
    ]
    if max_samples > 0:
        params.append(max_samples)
    sql = f"""
        SELECT UPPER(symbol) AS symbol, event_ts_utc, MIN(generation_event_id) AS representative_generation_event_id
        FROM native_short_map_generation_event_v1
        WHERE venue = %s
          AND quote_currency = %s
          AND fib_trading_horizon = %s
          AND primary_interval = %s
          AND supporting_interval = %s
          AND UPPER(symbol) IN ({placeholders})
          AND event_type = 'PUBLISHED'
          AND event_ts_utc >= %s
          AND event_ts_utc <= %s
          AND created_at_utc <= event_ts_utc
        GROUP BY UPPER(symbol), event_ts_utc
        ORDER BY event_ts_utc ASC, symbol ASC, representative_generation_event_id ASC
        {limit_clause}
    """
    rows = _fetch_batched(conn, sql, params)
    return [(str(row["symbol"]).upper(), _utc(row["event_ts_utc"])) for row in rows]


def fetch_outcome_candles(
    conn: Any,
    *,
    venue: str,
    symbols: Sequence[str],
    start_ts: datetime,
    end_ts: datetime,
) -> dict[str, list[OutcomeCandle]]:
    placeholders = ",".join(["%s"] * len(symbols))
    sql = f"""
        SELECT
            a.symbol, c.close_ts_utc, c.open_price, c.high_price, c.low_price, c.close_price
        FROM obs_market_candle c
        JOIN asset a
          ON a.asset_id = c.asset_id
        WHERE c.venue = %s
          AND c.interval_code = %s
          AND UPPER(a.symbol) IN ({placeholders})
          AND c.close_ts_utc > %s
          AND c.close_ts_utc <= %s
        ORDER BY a.symbol ASC, c.close_ts_utc ASC
    """
    rows = _fetch_batched(conn, sql, [venue, DEFAULT_PRIMARY_INTERVAL, *symbols, start_ts, end_ts])
    grouped: dict[str, list[OutcomeCandle]] = {symbol.upper(): [] for symbol in symbols}
    for row in rows:
        symbol = str(row["symbol"]).upper()
        grouped.setdefault(symbol, []).append(
            OutcomeCandle(
                symbol=symbol,
                close_ts_utc=_utc(row["close_ts_utc"]),
                open_price=Decimal(str(row["open_price"])),
                high_price=Decimal(str(row["high_price"])),
                low_price=Decimal(str(row["low_price"])),
                close_price=Decimal(str(row["close_price"])),
            )
        )
    return grouped


def parse_symbols_arg(value: str | None) -> list[str] | None:
    if not value:
        return None
    return sorted(dict.fromkeys(piece.strip().upper() for piece in value.split(",") if piece.strip()))


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build the PUBLISHED_EVENT replay foundation for native SHORT swing map "
            "publication outcomes from append-only native map lifecycle/history tables "
            "only. Research-only, SELECT-only, no CSV fallback."
        )
    )
    parser.add_argument("--venue", default=DEFAULT_VENUE)
    parser.add_argument("--quote-currency", default=DEFAULT_QUOTE_CURRENCY)
    parser.add_argument("--symbols", default=None, help="Comma-separated symbols. Defaults to native-map symbols.")
    parser.add_argument("--start-ts", required=True)
    parser.add_argument("--end-ts", required=True)
    parser.add_argument("--forward-candles", type=int, default=DEFAULT_FORWARD_CANDLES)
    parser.add_argument(
        "--sample-mode",
        choices=SAMPLE_MODES,
        default=SAMPLE_MODE_PUBLISHED_EVENT,
        help=(
            "Sampling mode. PUBLISHED_EVENT samples map publication moments only; "
            "it is not a full Profit Plan card lifecycle baseline."
        ),
    )
    parser.add_argument("--max-symbols", type=int, default=25)
    parser.add_argument("--max-samples", type=int, default=100)
    parser.add_argument("--database", default=None)
    parser.add_argument("--write-files", action="store_true")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--output", choices=("summary", "json"), default="summary")
    return parser.parse_args(argv)


def run_baseline(args: argparse.Namespace, *, generated_at_ts_utc: datetime | None = None) -> dict[str, Any]:
    start_ts = parse_ts(args.start_ts)
    end_ts = parse_ts(args.end_ts)
    if end_ts < start_ts:
        raise ValueError("end-ts must be >= start-ts")
    if args.forward_candles <= 0:
        raise ValueError("forward-candles must be positive")

    conn = get_connection(database=args.database)
    try:
        symbols = fetch_symbols(
            conn,
            venue=args.venue,
            quote_currency=args.quote_currency,
            symbols=parse_symbols_arg(args.symbols),
            start_ts=start_ts,
            end_ts=end_ts,
            max_symbols=args.max_symbols,
        )
        if not symbols:
            raise ValueError("No symbols available for baseline scope")
        maps = fetch_native_maps(
            conn,
            venue=args.venue,
            quote_currency=args.quote_currency,
            symbols=symbols,
            end_ts=end_ts,
        )
        generation_events = fetch_generation_events(
            conn,
            venue=args.venue,
            quote_currency=args.quote_currency,
            symbols=symbols,
            end_ts=end_ts,
        )
        lifecycle_events = fetch_lifecycle_events(
            conn,
            map_ids=[row.map_id for row in maps],
            end_ts=end_ts,
        )
        sample_points = fetch_sample_points(
            conn,
            sample_mode=args.sample_mode,
            venue=args.venue,
            quote_currency=args.quote_currency,
            symbols=symbols,
            start_ts=start_ts,
            end_ts=end_ts,
            max_samples=args.max_samples,
        )
        outcome_end = end_ts + timedelta(hours=4 * args.forward_candles)
        candles_by_symbol = fetch_outcome_candles(
            conn,
            venue=args.venue,
            symbols=symbols,
            start_ts=start_ts,
            end_ts=outcome_end,
        )
        conn.rollback()
    finally:
        conn.close()

    rows = build_baseline_rows(
        sample_points=sample_points,
        venue=args.venue,
        quote_currency=args.quote_currency,
        maps=maps,
        generation_events=generation_events,
        lifecycle_events=lifecycle_events,
        candles_by_symbol=candles_by_symbol,
        forward_candles=args.forward_candles,
    )
    summary_rows = build_summary_rows(rows)
    run_id = deterministic_run_id(
        venue=args.venue,
        symbols=symbols,
        start_ts=start_ts,
        end_ts=end_ts,
        forward_candles=args.forward_candles,
        sample_mode=args.sample_mode,
    )
    output_dir = Path(args.output_dir) / run_id
    artifact_paths = {
        "baseline_rows.csv": output_dir / "baseline_rows.csv",
        "baseline_rows.jsonl": output_dir / "baseline_rows.jsonl",
        "summary_by_status.csv": output_dir / "summary_by_status.csv",
        "provenance_manifest.json": output_dir / "provenance_manifest.json",
    }
    if args.write_files:
        _write_csv(artifact_paths["baseline_rows.csv"], rows)
        _write_jsonl(artifact_paths["baseline_rows.jsonl"], rows)
        _write_csv(artifact_paths["summary_by_status.csv"], summary_rows)
    manifest = build_manifest(
        run_id=run_id,
        output_dir=output_dir,
        symbols=symbols,
        start_ts=start_ts,
        end_ts=end_ts,
        venue=args.venue,
        quote_currency=args.quote_currency,
        forward_candles=args.forward_candles,
        sample_mode=args.sample_mode,
        rows=rows,
        artifact_paths=artifact_paths,
        generated_at_ts_utc=(generated_at_ts_utc or datetime.now(UTC)).replace(microsecond=0),
    )
    if args.write_files:
        _write_json(artifact_paths["provenance_manifest.json"], manifest)
    return {
        "run_id": run_id,
        "output_dir": str(output_dir),
        "rows": rows,
        "summary_rows": summary_rows,
        "manifest": manifest,
    }


def print_summary(result: dict[str, Any]) -> None:
    manifest = result["manifest"]
    print(f"report={RUNNER_NAME}")
    print(f"version={RUNNER_VERSION}")
    print(f"run_id={result['run_id']}")
    print(f"output_dir={result['output_dir']}")
    print(f"sample_mode={manifest['scope']['sample_mode']}")
    print(f"baseline_row_count={len(result['rows'])}")
    print(f"history_status_distribution={manifest['history_status_distribution']}")
    print(f"outcome_state_distribution={manifest['outcome_state_distribution']}")
    print("broker_private_calls=0")
    print("broker_writes=0")
    print("order_submission=0")
    print("live_orders=0")
    print("decision_gate=none")
    print("execution_planner=none")
    print("executor=none")
    print("db_writes=0")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    result = run_baseline(args)
    if args.output == "json":
        print(json.dumps(_json_safe(result), indent=2, sort_keys=True, ensure_ascii=True))
    else:
        print_summary(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
