from __future__ import annotations

"""Market-only native SHORT map ledger health report.

Layer:
- This is a reporting/ops observability lane (`src/reporting/`), not a
  market-data acquisition module. It presents ledger state; it does not
  produce, ingest, or materialize it.

Boundary:
- Read-only. Never inserts, updates, deletes, or invokes the materializer,
  scope seeder, or lifecycle mutation paths.
- Market-only, account-agnostic. No balance/position/order/broker access.
- No decision_gate, execution_planner, executor, or trading interpretation.

Reads:
- native_short_map_scope_v1
- native_short_map_v1
- native_short_map_generation_event_v1
- native_short_map_lifecycle_event_v1
- obs_market_candle (latest closed primary/supporting candle timestamp only)

The only cross-package import is `src.market_data.native_short_map_lifecycle_v1`,
the shared, DB-free lifecycle contract module (dataclasses, enums, and the
pure `project_current_native_short_map_lifecycle` projection function). It is
not a market-data producer/acquisition module and performs no DB access, so
depending on it does not pull ledger writers into this lane. This module
never imports the materializer, the scope seeder, or the candle-fetching
runner.

This module reuses the canonical lifecycle projection in
`native_short_map_lifecycle_v1.project_current_native_short_map_lifecycle`
for the `lifecycle_state`/`lifecycle_state_source` fields. All other sections
(active-map candidate resolution, generation-chain integrity, source
freshness) are derived independently and deterministically from raw ledger
rows so that ambiguity or inconsistency is surfaced explicitly rather than
silently resolved.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

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
    project_current_native_short_map_lifecycle,
)

DEFAULT_VENUE = "bitvavo"

SCOPE_STATUS_MISSING = "MISSING"
SCOPE_STATUS_SUPPORTED = "SUPPORTED"
SCOPE_STATUS_NOT_APPLICABLE = "NOT_APPLICABLE"
SCOPE_STATUS_AMBIGUOUS = "AMBIGUOUS"
SCOPE_STATUS_CONFLICTING = "CONFLICTING"

ACTIVE_MAP_RESOLUTION_NO_ACTIVE_MAP = "NO_ACTIVE_MAP"
ACTIVE_MAP_RESOLUTION_SINGLE = "SINGLE_ACTIVE_MAP"
ACTIVE_MAP_RESOLUTION_AMBIGUOUS = "AMBIGUOUS_ACTIVE_MAP_CANDIDATES"

CHAIN_STATUS_NO_ACTIVE_MAP = "NO_ACTIVE_MAP"
CHAIN_STATUS_ATTEMPT_STARTED_MISSING = "ATTEMPT_STARTED_MISSING"
CHAIN_STATUS_PUBLISHED_EVENT_MISSING = "PUBLISHED_EVENT_MISSING"
CHAIN_STATUS_PUBLISHED_MAP_ID_MISMATCH = "PUBLISHED_MAP_ID_MISMATCH"
CHAIN_STATUS_OK = "OK"

FRESHNESS_NO_ACTIVE_MAP = "NO_ACTIVE_MAP"
FRESHNESS_MISSING = "MISSING"
FRESHNESS_UNAVAILABLE = "UNAVAILABLE"
FRESHNESS_CURRENT = "CURRENT"
FRESHNESS_STALE = "STALE"
FRESHNESS_AHEAD_OR_INCONSISTENT = "AHEAD_OR_INCONSISTENT"
_FRESHNESS_PRECEDENCE = [
    FRESHNESS_MISSING,
    FRESHNESS_UNAVAILABLE,
    FRESHNESS_AHEAD_OR_INCONSISTENT,
    FRESHNESS_STALE,
    FRESHNESS_CURRENT,
]

OVERALL_HEALTH_HEALTHY = "HEALTHY"
OVERALL_HEALTH_NEEDS_REVIEW = "NEEDS_REVIEW"
OVERALL_HEALTH_NOT_APPLICABLE = "NOT_APPLICABLE"

STATUS_REPORTED = "reported"
STATUS_FAILED = "failed"


def _ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _dec(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _int_or_none(value: Any) -> int | None:
    return None if value is None else int(value)


@dataclass(frozen=True)
class LedgerHealthReport:
    symbol: str
    venue: str
    quote_currency: str
    fib_trading_horizon: str
    primary_interval: str
    supporting_interval: str
    generated_at_utc: datetime
    status: str

    scope_row_count: int = 0
    scope_status: str = SCOPE_STATUS_MISSING
    scope_status_detail: str | None = None
    scope_support_state: str | None = None
    scope_reason_code: str | None = None
    scope_reason_detail: str | None = None

    lifecycle_evaluated: bool = False
    lifecycle_state: str = "NOT_EVALUATED"
    lifecycle_state_source: str | None = None
    latest_authoritative_event_type: str | None = None
    latest_authoritative_reason_code: str | None = None
    latest_authoritative_event_ts_utc: datetime | None = None
    latest_terminal_lifecycle_event_type: str | None = None
    latest_terminal_lifecycle_event_ts_utc: datetime | None = None
    latest_skip_reason_code: str | None = None
    latest_skip_event_ts_utc: datetime | None = None

    map_count: int = 0
    active_map_resolution_status: str = ACTIVE_MAP_RESOLUTION_NO_ACTIVE_MAP
    active_map_candidate_ids: list[int] = field(default_factory=list)
    active_map_id: int | None = None
    active_map_structure_hash: str | None = None
    active_map_published_generation_attempt_id: str | None = None
    active_map_cycle_id: str | None = None
    active_map_previous_map_id: int | None = None
    active_map_previous_map_cycle_id: str | None = None
    active_map_published_at_utc: datetime | None = None
    active_map_market_snapshot_ts_utc: datetime | None = None
    active_map_anchor_low_ts_utc: datetime | None = None
    active_map_anchor_low_price: Decimal | None = None
    active_map_anchor_high_ts_utc: datetime | None = None
    active_map_anchor_high_price: Decimal | None = None
    active_map_invalidation_price: Decimal | None = None
    active_map_invalidation_rule: str | None = None
    active_map_target_levels_json: str | None = None

    generation_chain_integrity_status: str = CHAIN_STATUS_NO_ACTIVE_MAP
    generation_chain_integrity_reason: str | None = None
    generation_chain_attempt_id: str | None = None
    generation_chain_has_attempt_started: bool = False
    generation_chain_has_published_event: bool = False
    generation_chain_published_event_map_id: int | None = None

    source_freshness_state: str = FRESHNESS_NO_ACTIVE_MAP
    primary_source_freshness_state: str | None = None
    supporting_source_freshness_state: str | None = None
    stored_primary_candle_ts_utc: datetime | None = None
    stored_support_candle_ts_utc: datetime | None = None
    latest_primary_candle_ts_utc: datetime | None = None
    latest_support_candle_ts_utc: datetime | None = None

    overall_health_status: str = OVERALL_HEALTH_NEEDS_REVIEW
    overall_health_reason_codes: list[str] = field(default_factory=list)

    reason_code: str | None = None
    detail: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def resolve_scope_status(scope_rows: list[dict[str, Any]]) -> tuple[str, dict[str, Any] | None, str]:
    if not scope_rows:
        return SCOPE_STATUS_MISSING, None, "no native_short_map_scope_v1 row for canonical scope key"
    if len(scope_rows) == 1:
        row = scope_rows[0]
        state = str(row["scope_support_state"])
        return state, row, f"exactly one canonical scope row ({state})"
    states = {str(row["scope_support_state"]) for row in scope_rows}
    count = len(scope_rows)
    if len(states) == 1:
        return (
            SCOPE_STATUS_AMBIGUOUS,
            None,
            f"found {count} canonical scope rows with identical support_state={next(iter(states))}",
        )
    return (
        SCOPE_STATUS_CONFLICTING,
        None,
        f"found {count} canonical scope rows with differing support_state values {sorted(states)}",
    )


def _latest_lifecycle_event_by_map(
    lifecycle_events: list[NativeShortMapLifecycleEvent],
) -> dict[int, NativeShortMapLifecycleEvent]:
    latest: dict[int, NativeShortMapLifecycleEvent] = {}
    for event in lifecycle_events:
        current = latest.get(event.map_id)
        if current is None or event.lifecycle_event_id > current.lifecycle_event_id:
            latest[event.map_id] = event
    return latest


def compute_active_map_candidates(
    maps: list[NativeShortMapRecord],
    lifecycle_events: list[NativeShortMapLifecycleEvent],
) -> list[NativeShortMapRecord]:
    """Maps with no lifecycle event, or whose latest lifecycle event is ACTIVATED.

    Mirrors the active-map predicate inside
    `project_current_native_short_map_lifecycle` so ambiguity (more than one
    candidate) can be surfaced instead of silently resolved by tie-break.
    """
    latest_by_map = _latest_lifecycle_event_by_map(lifecycle_events)
    candidates = [
        map_record
        for map_record in maps
        if latest_by_map.get(map_record.map_id) is None
        or latest_by_map[map_record.map_id].event_type == NativeShortMapLifecycleEventType.ACTIVATED
    ]
    return sorted(candidates, key=lambda item: (item.published_at_utc, item.map_id))


def _freshness_state(stored: datetime | None, latest: datetime | None) -> str:
    if stored is None:
        return FRESHNESS_MISSING
    if latest is None:
        return FRESHNESS_UNAVAILABLE
    if stored == latest:
        return FRESHNESS_CURRENT
    if stored < latest:
        return FRESHNESS_STALE
    return FRESHNESS_AHEAD_OR_INCONSISTENT


def _combine_freshness(primary_state: str, supporting_state: str) -> str:
    return min(
        (primary_state, supporting_state),
        key=lambda state: _FRESHNESS_PRECEDENCE.index(state),
    )


def build_ledger_health_report(
    *,
    venue: str,
    symbol: str,
    quote_currency: str,
    fib_trading_horizon: str,
    primary_interval: str,
    supporting_interval: str,
    generated_at_utc: datetime,
    scope_rows: list[dict[str, Any]],
    maps: list[NativeShortMapRecord],
    generation_events: list[NativeShortMapGenerationEvent],
    lifecycle_events: list[NativeShortMapLifecycleEvent],
    latest_primary_candle_ts_utc: datetime | None,
    latest_support_candle_ts_utc: datetime | None,
) -> LedgerHealthReport:
    scope_status, single_scope_row, scope_status_detail = resolve_scope_status(scope_rows)
    scope_support_state = str(single_scope_row["scope_support_state"]) if single_scope_row else None
    scope_reason_code = single_scope_row.get("scope_reason_code") if single_scope_row else None
    scope_reason_detail = single_scope_row.get("scope_reason_detail") if single_scope_row else None

    map_count = len(maps)
    active_candidates = compute_active_map_candidates(maps, lifecycle_events)
    if not active_candidates:
        active_map_resolution_status = ACTIVE_MAP_RESOLUTION_NO_ACTIVE_MAP
        resolved_active_map_id = None
    elif len(active_candidates) == 1:
        active_map_resolution_status = ACTIVE_MAP_RESOLUTION_SINGLE
        resolved_active_map_id = active_candidates[0].map_id
    else:
        active_map_resolution_status = ACTIVE_MAP_RESOLUTION_AMBIGUOUS
        resolved_active_map_id = active_candidates[-1].map_id
    active_map_candidate_ids = [item.map_id for item in active_candidates]

    active_map_record = None
    if resolved_active_map_id is not None:
        active_map_record = next(
            (item for item in maps if item.map_id == resolved_active_map_id), None
        )

    lifecycle_evaluated = scope_status in (SCOPE_STATUS_SUPPORTED, SCOPE_STATUS_NOT_APPLICABLE)
    lifecycle_state = "NOT_EVALUATED"
    lifecycle_state_source: str | None = f"SCOPE_STATUS_{scope_status}"
    latest_authoritative_event_type = None
    latest_authoritative_reason_code = None
    latest_authoritative_event_ts_utc = None
    latest_terminal_lifecycle_event_type = None
    latest_terminal_lifecycle_event_ts_utc = None
    latest_skip_reason_code = None
    latest_skip_event_ts_utc = None

    if lifecycle_evaluated:
        scope_key = NativeShortMapScopeKey(
            venue=venue,
            symbol=symbol,
            quote_currency=quote_currency,
            fib_trading_horizon=fib_trading_horizon,
            primary_interval=primary_interval,
            supporting_interval=supporting_interval,
        )
        scope_support = NativeShortMapScopeSupport(
            key=scope_key,
            support_state=NativeShortMapScopeSupportState(scope_status),
            reason_code=scope_reason_code,
        )
        projection = project_current_native_short_map_lifecycle(
            scope_support=scope_support,
            maps=maps,
            generation_events=generation_events,
            lifecycle_events=lifecycle_events,
        )
        lifecycle_state = str(projection.lifecycle_state)
        lifecycle_state_source = projection.lifecycle_state_source
        latest_authoritative_event_type = (
            str(projection.authoritative_event_type) if projection.authoritative_event_type else None
        )
        latest_authoritative_reason_code = projection.authoritative_reason_code
        latest_authoritative_event_ts_utc = projection.authoritative_event_ts_utc
        latest_terminal_lifecycle_event_type = (
            str(projection.terminal_event_type) if projection.terminal_event_type else None
        )
        latest_terminal_lifecycle_event_ts_utc = projection.terminal_event_ts_utc
        latest_skip_reason_code = projection.latest_skip_reason_code
        latest_skip_event_ts_utc = projection.latest_skip_event_ts_utc

    if active_map_record is None:
        chain_status = CHAIN_STATUS_NO_ACTIVE_MAP
        chain_reason = "no resolved active map candidate for this canonical scope key"
        chain_attempt_id = None
        chain_has_started = False
        chain_has_published = False
        chain_published_map_id = None
    else:
        chain_attempt_id = active_map_record.published_generation_attempt_id
        attempt_events = [event for event in generation_events if event.attempt_id == chain_attempt_id]
        chain_has_started = any(
            event.event_type == NativeShortMapGenerationEventType.ATTEMPT_STARTED for event in attempt_events
        )
        published_events = sorted(
            (event for event in attempt_events if event.event_type == NativeShortMapGenerationEventType.PUBLISHED),
            key=lambda event: event.generation_event_id,
        )
        chain_has_published = bool(published_events)
        chain_published_map_id = published_events[0].map_id if published_events else None
        if not chain_has_started:
            chain_status = CHAIN_STATUS_ATTEMPT_STARTED_MISSING
            chain_reason = f"no ATTEMPT_STARTED event for attempt_id={chain_attempt_id}"
        elif not chain_has_published:
            chain_status = CHAIN_STATUS_PUBLISHED_EVENT_MISSING
            chain_reason = f"no PUBLISHED event for attempt_id={chain_attempt_id}"
        elif chain_published_map_id != active_map_record.map_id:
            chain_status = CHAIN_STATUS_PUBLISHED_MAP_ID_MISMATCH
            chain_reason = (
                f"PUBLISHED.map_id={chain_published_map_id} does not match "
                f"active_map_id={active_map_record.map_id}"
            )
        else:
            chain_status = CHAIN_STATUS_OK
            chain_reason = "ATTEMPT_STARTED and PUBLISHED present; PUBLISHED.map_id matches active map"

    if active_map_record is None:
        source_freshness_state = FRESHNESS_NO_ACTIVE_MAP
        primary_freshness_state = None
        supporting_freshness_state = None
        stored_primary_ts = None
        stored_support_ts = None
    else:
        stored_primary_ts = active_map_record.source_primary_candle_ts_utc
        stored_support_ts = active_map_record.source_support_candle_ts_utc
        primary_freshness_state = _freshness_state(stored_primary_ts, latest_primary_candle_ts_utc)
        supporting_freshness_state = _freshness_state(stored_support_ts, latest_support_candle_ts_utc)
        source_freshness_state = _combine_freshness(primary_freshness_state, supporting_freshness_state)

    reasons: set[str] = set()
    if scope_status == SCOPE_STATUS_MISSING:
        reasons.add("SCOPE_MISSING")
    elif scope_status == SCOPE_STATUS_AMBIGUOUS:
        reasons.add("SCOPE_AMBIGUOUS")
    elif scope_status == SCOPE_STATUS_CONFLICTING:
        reasons.add("SCOPE_CONFLICTING")
    elif scope_status == SCOPE_STATUS_NOT_APPLICABLE and map_count > 0:
        reasons.add("MAPS_EXIST_UNDER_NOT_APPLICABLE_SCOPE")

    if active_map_resolution_status == ACTIVE_MAP_RESOLUTION_AMBIGUOUS:
        reasons.add("AMBIGUOUS_ACTIVE_MAP_CANDIDATES")

    if scope_status == SCOPE_STATUS_SUPPORTED:
        if lifecycle_state != "MAP_ACTIVE":
            reasons.add(f"LIFECYCLE_STATE_{lifecycle_state}")
        if chain_status not in (CHAIN_STATUS_OK, CHAIN_STATUS_NO_ACTIVE_MAP):
            reasons.add(f"GENERATION_CHAIN_{chain_status}")
        if source_freshness_state not in (FRESHNESS_CURRENT, FRESHNESS_NO_ACTIVE_MAP):
            reasons.add(f"SOURCE_FRESHNESS_{source_freshness_state}")

    if reasons:
        overall_health_status = OVERALL_HEALTH_NEEDS_REVIEW
    elif scope_status == SCOPE_STATUS_NOT_APPLICABLE:
        overall_health_status = OVERALL_HEALTH_NOT_APPLICABLE
    elif scope_status == SCOPE_STATUS_SUPPORTED:
        overall_health_status = OVERALL_HEALTH_HEALTHY
    else:
        overall_health_status = OVERALL_HEALTH_NEEDS_REVIEW

    return LedgerHealthReport(
        symbol=symbol,
        venue=venue,
        quote_currency=quote_currency,
        fib_trading_horizon=fib_trading_horizon,
        primary_interval=primary_interval,
        supporting_interval=supporting_interval,
        generated_at_utc=generated_at_utc,
        status=STATUS_REPORTED,
        scope_row_count=len(scope_rows),
        scope_status=scope_status,
        scope_status_detail=scope_status_detail,
        scope_support_state=scope_support_state,
        scope_reason_code=scope_reason_code,
        scope_reason_detail=scope_reason_detail,
        lifecycle_evaluated=lifecycle_evaluated,
        lifecycle_state=lifecycle_state,
        lifecycle_state_source=lifecycle_state_source,
        latest_authoritative_event_type=latest_authoritative_event_type,
        latest_authoritative_reason_code=latest_authoritative_reason_code,
        latest_authoritative_event_ts_utc=latest_authoritative_event_ts_utc,
        latest_terminal_lifecycle_event_type=latest_terminal_lifecycle_event_type,
        latest_terminal_lifecycle_event_ts_utc=latest_terminal_lifecycle_event_ts_utc,
        latest_skip_reason_code=latest_skip_reason_code,
        latest_skip_event_ts_utc=latest_skip_event_ts_utc,
        map_count=map_count,
        active_map_resolution_status=active_map_resolution_status,
        active_map_candidate_ids=active_map_candidate_ids,
        active_map_id=resolved_active_map_id,
        active_map_structure_hash=active_map_record.structure_hash if active_map_record else None,
        active_map_published_generation_attempt_id=(
            active_map_record.published_generation_attempt_id if active_map_record else None
        ),
        active_map_cycle_id=active_map_record.map_cycle_id if active_map_record else None,
        active_map_previous_map_id=active_map_record.previous_map_id if active_map_record else None,
        active_map_previous_map_cycle_id=(
            active_map_record.previous_map_cycle_id if active_map_record else None
        ),
        active_map_published_at_utc=active_map_record.published_at_utc if active_map_record else None,
        active_map_market_snapshot_ts_utc=(
            active_map_record.market_snapshot_ts_utc if active_map_record else None
        ),
        active_map_anchor_low_ts_utc=active_map_record.anchor_low_ts_utc if active_map_record else None,
        active_map_anchor_low_price=active_map_record.anchor_low_price if active_map_record else None,
        active_map_anchor_high_ts_utc=active_map_record.anchor_high_ts_utc if active_map_record else None,
        active_map_anchor_high_price=active_map_record.anchor_high_price if active_map_record else None,
        active_map_invalidation_price=active_map_record.invalidation_price if active_map_record else None,
        active_map_invalidation_rule=active_map_record.invalidation_rule if active_map_record else None,
        active_map_target_levels_json=(
            active_map_record.target_levels_json if active_map_record else None
        ),
        generation_chain_integrity_status=chain_status,
        generation_chain_integrity_reason=chain_reason,
        generation_chain_attempt_id=chain_attempt_id,
        generation_chain_has_attempt_started=chain_has_started,
        generation_chain_has_published_event=chain_has_published,
        generation_chain_published_event_map_id=chain_published_map_id,
        source_freshness_state=source_freshness_state,
        primary_source_freshness_state=primary_freshness_state,
        supporting_source_freshness_state=supporting_freshness_state,
        stored_primary_candle_ts_utc=stored_primary_ts,
        stored_support_candle_ts_utc=stored_support_ts,
        latest_primary_candle_ts_utc=latest_primary_candle_ts_utc,
        latest_support_candle_ts_utc=latest_support_candle_ts_utc,
        overall_health_status=overall_health_status,
        overall_health_reason_codes=sorted(reasons),
    )


def fetch_scope_rows(
    conn: Any,
    key: NativeShortMapScopeKey,
) -> list[dict[str, Any]]:
    sql = """
    SELECT
        scope_id,
        venue,
        symbol,
        quote_currency,
        fib_trading_horizon,
        primary_interval,
        supporting_interval,
        scope_support_state,
        scope_reason_code,
        scope_reason_detail
    FROM native_short_map_scope_v1
    WHERE venue = %s AND symbol = %s AND quote_currency = %s
      AND fib_trading_horizon = %s AND primary_interval = %s AND supporting_interval = %s
    ORDER BY scope_id ASC
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
    return [dict(row) for row in rows]


def fetch_maps_for_scope(conn: Any, key: NativeShortMapScopeKey) -> list[NativeShortMapRecord]:
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
            previous_map_id=_int_or_none(row.get("previous_map_id")),
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
            source_primary_candle_count=_int_or_none(row.get("source_primary_candle_count")),
            source_support_candle_count=_int_or_none(row.get("source_support_candle_count")),
            map_payload_json=row.get("map_payload_json") or "{}",
        )
        for row in rows
    ]


def fetch_generation_events_for_scope(
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
            map_id=_int_or_none(row.get("map_id")),
            trigger_type=row.get("trigger_type"),
            candidate_map_cycle_id=row.get("candidate_map_cycle_id"),
            candidate_previous_map_id=_int_or_none(row.get("candidate_previous_map_id")),
            candidate_primary_lifecycle_state=row.get("candidate_primary_lifecycle_state"),
            candidate_current_map_status=row.get("candidate_current_map_status"),
            latest_primary_close_ts_utc=_ensure_utc(row.get("latest_primary_close_ts_utc")),
            latest_support_close_ts_utc=_ensure_utc(row.get("latest_support_close_ts_utc")),
            latest_primary_close_price=_dec(row.get("latest_primary_close_price")),
            source_primary_ref=row.get("source_primary_ref"),
            source_support_ref=row.get("source_support_ref"),
            source_primary_candle_count=_int_or_none(row.get("source_primary_candle_count")),
            source_support_candle_count=_int_or_none(row.get("source_support_candle_count")),
        )
        for row in rows
    ]


def fetch_lifecycle_events_for_map_ids(
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
            successor_map_id=_int_or_none(row.get("successor_map_id")),
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


def fetch_latest_closed_candle_ts(
    conn: Any,
    *,
    venue: str,
    symbol: str,
    interval_code: str,
) -> datetime | None:
    """Latest available closed candle timestamp for one venue/symbol/interval.

    Uses the same `obs_market_candle` join-on-`asset` shape already used by
    `run_native_short_map_materializer_v1._fetch_candles_by_symbol`.
    Closedness is an ingest-side guarantee (no `is_closed` column); "latest"
    is simply the maximum stored `close_ts_utc` row.
    """
    sql = """
    SELECT c.close_ts_utc
    FROM obs_market_candle c
    JOIN asset a
      ON a.asset_id = c.asset_id
    WHERE c.venue = %s
      AND c.interval_code = %s
      AND a.symbol = %s
    ORDER BY c.close_ts_utc DESC
    LIMIT 1
    """
    with conn.cursor() as cur:
        cur.execute(sql, (venue, interval_code, symbol))
        rows = list(cur.fetchall())
    if not rows:
        return None
    return _ensure_utc(rows[0]["close_ts_utc"])


def generate_report_for_symbol(
    conn: Any,
    *,
    venue: str,
    symbol: str,
    quote_currency: str = DEFAULT_QUOTE_CURRENCY,
    fib_trading_horizon: str = DEFAULT_FIB_TRADING_HORIZON,
    primary_interval: str = DEFAULT_PRIMARY_INTERVAL,
    supporting_interval: str = DEFAULT_SUPPORTING_INTERVAL,
    generated_at_utc: datetime,
) -> LedgerHealthReport:
    """Read-only orchestration: fetch every ledger row for one canonical scope
    key and build the deterministic health report. Never mutates state."""
    key = NativeShortMapScopeKey(
        venue=venue,
        symbol=symbol,
        quote_currency=quote_currency,
        fib_trading_horizon=fib_trading_horizon,
        primary_interval=primary_interval,
        supporting_interval=supporting_interval,
    )
    scope_rows = fetch_scope_rows(conn, key)
    maps = fetch_maps_for_scope(conn, key)
    generation_events = fetch_generation_events_for_scope(conn, key)
    lifecycle_events = fetch_lifecycle_events_for_map_ids(conn, [item.map_id for item in maps])
    latest_primary_ts = fetch_latest_closed_candle_ts(
        conn, venue=venue, symbol=symbol, interval_code=primary_interval
    )
    latest_support_ts = fetch_latest_closed_candle_ts(
        conn, venue=venue, symbol=symbol, interval_code=supporting_interval
    )
    return build_ledger_health_report(
        venue=venue,
        symbol=symbol,
        quote_currency=quote_currency,
        fib_trading_horizon=fib_trading_horizon,
        primary_interval=primary_interval,
        supporting_interval=supporting_interval,
        generated_at_utc=generated_at_utc,
        scope_rows=scope_rows,
        maps=maps,
        generation_events=generation_events,
        lifecycle_events=lifecycle_events,
        latest_primary_candle_ts_utc=latest_primary_ts,
        latest_support_candle_ts_utc=latest_support_ts,
    )


def failed_report(
    *,
    venue: str,
    symbol: str,
    quote_currency: str,
    fib_trading_horizon: str,
    primary_interval: str,
    supporting_interval: str,
    generated_at_utc: datetime,
    exc: Exception,
) -> LedgerHealthReport:
    return LedgerHealthReport(
        symbol=symbol,
        venue=venue,
        quote_currency=quote_currency,
        fib_trading_horizon=fib_trading_horizon,
        primary_interval=primary_interval,
        supporting_interval=supporting_interval,
        generated_at_utc=generated_at_utc,
        status=STATUS_FAILED,
        overall_health_status=OVERALL_HEALTH_NEEDS_REVIEW,
        overall_health_reason_codes=["REPORT_GENERATION_FAILED"],
        reason_code=type(exc).__name__,
        detail=str(exc),
    )
