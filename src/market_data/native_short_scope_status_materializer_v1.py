from __future__ import annotations

"""Native SHORT scope-status materializer integration (PR A2).

Safety markers:
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none

Boundary:
- Market-only, account-agnostic. Reads/writes only native SHORT market-data
  ledgers and the scope-status projection defined in
  docs/architecture/native_short_scope_status_contract_v1.md.
- No scheduler, timer, service, systemd, or deployment wiring belongs here
  (PR B). No broker/account/wallet/order/execution code.

This module has two clearly separated layers:

1. Pure decision logic (no DB, no wall-clock reads): `NativeShortRunBuilder`,
   `decide_genuine_lifecycle_transition`, `map_geometry_action`, and the
   observation-record builders. These take an explicit `as_of_utc` and
   already-fetched facts, and are fully unit-testable without a database.
2. Thin MariaDB I/O: fetch helpers for the new A1/A1b tables (this module is
   the first writer of `native_short_materializer_run_v1` and
   `native_short_scope_observation_v1`, and the only writer of
   `native_short_scope_status_v1`), plus `run_native_short_scope_status_materializer`,
   the bounded-run orchestrator that wires the pure logic to real reads/writes
   and reuses the existing `native_short_map_materializer_v1.materialize_scope_symbol`
   geometry path unchanged (no duplicate maps/generation heartbeats, by
   construction of that existing function).

Genuine lifecycle transition detection reuses the existing deterministic
`native_short_fib_context_v1` predicate (`primary_4h_lifecycle_state`,
computed by `_classify_primary_lifecycle` from persisted candle evidence). No
new market/lifecycle predicate is invented here. MAP_EXPIRED has no existing
deterministic predicate anywhere in the codebase, so this module does not
attempt to detect or append EXPIRED transitions; the projection engine still
reads/handles MAP_EXPIRED correctly if one is ever appended by a future lane.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Sequence

from src.market_data.native_short_fib_context_v1 import (
    PRIMARY_LIFECYCLE_COMPLETED,
    PRIMARY_LIFECYCLE_INVALIDATED,
    STATUS_SYMBOL_MISSING,
    NativeShortContextRow,
)
from src.market_data.native_short_map_lifecycle_v1 import (
    NativeShortMapLifecycleEventType,
    NativeShortMapScopeKey,
    NativeShortMapScopeSupport,
    NativeShortMapScopeSupportState,
)
from src.market_data.native_short_map_materializer_v1 import (
    REASON_PRIOR_REJECTION_UNCHANGED,
    REASON_STRUCTURE_UNCHANGED,
    ScopeMaterializationResult,
    materialize_scope_symbol,
)
from src.market_data.native_short_scope_status_projection_v1 import (
    CadenceConfigFact,
    GenerationEventFact,
    LifecycleEventFact,
    MapFact,
    ObservationFact,
    ScopeSupportEventFact,
    classify_source_freshness,
    project_native_short_scope_status,
    resolve_scope_support_state_at_cutoff,
    select_current_map,
    select_eligible_cadence_config,
)
from src.market_data.native_short_scope_status_v1 import (
    NO_ELIGIBLE_CADENCE_CONFIG_REASON_CODE,
    NativeShortMaterializerRunRecord,
    NativeShortRunTerminalStatus,
    NativeShortScopeGeometryAction,
    NativeShortScopeObservationRecord,
    NativeShortScopeObservationStatus,
    NativeShortScopeSourceState,
    NativeShortScopeStatusRecord,
    NativeShortScopeSupportEventState,
)

__all__ = [
    "CONTRACT_VERSION",
    "NativeShortRunBuilder",
    "ScopeEvaluationOutcome",
    "build_configuration_unavailable_observation",
    "build_normal_observation",
    "decide_genuine_lifecycle_transition",
    "evaluate_scope",
    "map_geometry_action",
    "run_native_short_scope_status_materializer",
]

RUNNER_NAME = "native_short_scope_status_materializer_v1"
RUNNER_VERSION = "0.1"
CONTRACT_VERSION = "native_short_scope_status_contract_v1"

_TERMINAL_LIFECYCLE_EVENT_TYPE_VALUES = frozenset(
    {
        NativeShortMapLifecycleEventType.COMPLETED.value,
        NativeShortMapLifecycleEventType.EXPIRED.value,
        NativeShortMapLifecycleEventType.INVALIDATED.value,
        NativeShortMapLifecycleEventType.SUPERSEDED.value,
    }
)


# ---------------------------------------------------------------------------
# Pure decision logic
# ---------------------------------------------------------------------------


@dataclass
class NativeShortRunBuilder:
    """Pure, DB-free accumulator for one bounded materializer run.

    Guarantees terminal fields are set exactly once: `finish()` raises if
    called a second time, and `record_scope_outcome()` raises once the run
    has been finished. The caller inserts the run row from the initial
    "started" record and updates it once from the record `finish()` returns.
    """

    run_uuid: str
    runner_name: str
    runner_version: str
    contract_version: str
    trigger_type: str
    started_at_utc: datetime
    requested_scope_count: int
    observed_scope_count: int = field(default=0, init=False)
    published_map_count: int = field(default=0, init=False)
    lifecycle_event_count: int = field(default=0, init=False)
    failed_scope_count: int = field(default=0, init=False)
    _finished: bool = field(default=False, init=False, repr=False)

    def started_record(self) -> NativeShortMaterializerRunRecord:
        return NativeShortMaterializerRunRecord(
            run_uuid=self.run_uuid,
            runner_name=self.runner_name,
            runner_version=self.runner_version,
            contract_version=self.contract_version,
            trigger_type=self.trigger_type,
            started_at_utc=self.started_at_utc,
            requested_scope_count=self.requested_scope_count,
        )

    def record_scope_outcome(
        self,
        *,
        published_map: bool = False,
        lifecycle_event_appended: bool = False,
        failed: bool = False,
    ) -> None:
        if self._finished:
            raise ValueError("RUN_ALREADY_FINISHED")
        self.observed_scope_count += 1
        if published_map:
            self.published_map_count += 1
        if lifecycle_event_appended:
            self.lifecycle_event_count += 1
        if failed:
            self.failed_scope_count += 1

    def finish(
        self,
        *,
        finished_at_utc: datetime,
        terminal_status: NativeShortRunTerminalStatus | str = NativeShortRunTerminalStatus.FINISHED,
        failure_reason_code: str | None = None,
        failure_detail: str | None = None,
    ) -> NativeShortMaterializerRunRecord:
        if self._finished:
            raise ValueError("RUN_ALREADY_FINISHED")
        self._finished = True
        return NativeShortMaterializerRunRecord(
            run_uuid=self.run_uuid,
            runner_name=self.runner_name,
            runner_version=self.runner_version,
            contract_version=self.contract_version,
            trigger_type=self.trigger_type,
            started_at_utc=self.started_at_utc,
            requested_scope_count=self.requested_scope_count,
            terminal_status=terminal_status,
            finished_at_utc=finished_at_utc,
            observed_scope_count=self.observed_scope_count,
            published_map_count=self.published_map_count,
            lifecycle_event_count=self.lifecycle_event_count,
            failed_scope_count=self.failed_scope_count,
            failure_reason_code=failure_reason_code,
            failure_detail=failure_detail,
        )


def decide_genuine_lifecycle_transition(
    *,
    selected_map: MapFact | None,
    context_row: NativeShortContextRow | None,
    existing_lifecycle_event_types_for_map: frozenset[str],
) -> NativeShortMapLifecycleEventType | None:
    """Reuses the existing `native_short_fib_context_v1` deterministic
    predicate (`primary_4h_lifecycle_state`, computed from persisted candle
    evidence via `_classify_primary_lifecycle`) to decide whether the
    currently selected map warrants a genuine COMPLETED or INVALIDATED
    transition. Returns None when there is nothing to append: no selected
    map, no context evidence, the context's evaluated swing does not match
    the selected map's geometry, or the transition was already recorded.

    No EXPIRED detection: no deterministic expiry predicate exists anywhere
    in the codebase, so this function never invents one.
    """
    if selected_map is None or context_row is None:
        return None
    if not context_row.map_cycle_id or context_row.map_cycle_id != selected_map.map_cycle_id:
        return None
    if context_row.primary_4h_lifecycle_state == PRIMARY_LIFECYCLE_INVALIDATED:
        if NativeShortMapLifecycleEventType.INVALIDATED.value in existing_lifecycle_event_types_for_map:
            return None
        return NativeShortMapLifecycleEventType.INVALIDATED
    if context_row.primary_4h_lifecycle_state == PRIMARY_LIFECYCLE_COMPLETED:
        if NativeShortMapLifecycleEventType.COMPLETED.value in existing_lifecycle_event_types_for_map:
            return None
        return NativeShortMapLifecycleEventType.COMPLETED
    return None


def map_geometry_action(result: ScopeMaterializationResult) -> NativeShortScopeGeometryAction:
    if result.status == "published":
        return NativeShortScopeGeometryAction.PUBLISHED_NEW_MAP
    if result.reason_code == REASON_STRUCTURE_UNCHANGED:
        return NativeShortScopeGeometryAction.UNCHANGED_GEOMETRY
    if result.reason_code == REASON_PRIOR_REJECTION_UNCHANGED or result.generation_event_type == "REJECTED":
        return NativeShortScopeGeometryAction.REJECTED_CONTEXT
    return NativeShortScopeGeometryAction.NO_MAP_AVAILABLE


def build_configuration_unavailable_observation(
    *,
    key: NativeShortMapScopeKey,
    run_id: int,
    run_uuid: str,
    observed_at_utc: datetime,
) -> NativeShortScopeObservationRecord:
    return NativeShortScopeObservationRecord(
        key=key,
        run_id=run_id,
        run_uuid=run_uuid,
        observed_at_utc=observed_at_utc,
        observation_status=NativeShortScopeObservationStatus.SKIPPED_CONFIGURATION_UNAVAILABLE,
        observation_reason_code=NO_ELIGIBLE_CADENCE_CONFIG_REASON_CODE,
    )


def build_source_unavailable_observation(
    *,
    key: NativeShortMapScopeKey,
    run_id: int,
    run_uuid: str,
    observed_at_utc: datetime,
    cadence_contract_version: str,
    primary_source_freshness_limit_seconds: int,
    supporting_source_freshness_limit_seconds: int,
    current_map_id_before: int | None,
) -> NativeShortScopeObservationRecord:
    """SUPPORTED scope, eligible cadence config, but no candle evidence at
    all was fetchable (context builder returned SYMBOL_MISSING). This is a
    genuine SKIPPED_SOURCE_UNAVAILABLE observation, distinct from the
    configuration-unavailable path."""
    return NativeShortScopeObservationRecord(
        key=key,
        run_id=run_id,
        run_uuid=run_uuid,
        observed_at_utc=observed_at_utc,
        observation_status=NativeShortScopeObservationStatus.SKIPPED_SOURCE_UNAVAILABLE,
        cadence_contract_version=cadence_contract_version,
        source_state=NativeShortScopeSourceState.SOURCE_UNAVAILABLE,
        primary_source_freshness_limit_seconds=primary_source_freshness_limit_seconds,
        supporting_source_freshness_limit_seconds=supporting_source_freshness_limit_seconds,
        geometry_action=NativeShortScopeGeometryAction.NO_MAP_AVAILABLE,
        context_status=STATUS_SYMBOL_MISSING,
        current_map_id_before=current_map_id_before,
        current_map_id_after=current_map_id_before,
    )


def build_normal_observation(
    *,
    key: NativeShortMapScopeKey,
    run_id: int,
    run_uuid: str,
    observed_at_utc: datetime,
    cadence_contract_version: str,
    source_state: NativeShortScopeSourceState,
    primary_source_freshness_limit_seconds: int,
    supporting_source_freshness_limit_seconds: int,
    geometry_action: NativeShortScopeGeometryAction,
    result: ScopeMaterializationResult,
    current_map_id_before: int | None,
    current_map_id_after: int | None,
    lifecycle_event_id: int | None,
    lifecycle_state_before: str | None,
    lifecycle_state_after: str | None,
    primary_latest_candle_ts_utc: datetime | None,
    supporting_latest_candle_ts_utc: datetime | None,
    context_status: str,
    source_primary_candle_count: int | None,
    source_support_candle_count: int | None,
) -> NativeShortScopeObservationRecord:
    observation_status = (
        NativeShortScopeObservationStatus.FAILED
        if result.status == "failed"
        else NativeShortScopeObservationStatus.EVALUATED
    )
    return NativeShortScopeObservationRecord(
        key=key,
        run_id=run_id,
        run_uuid=run_uuid,
        observed_at_utc=observed_at_utc,
        observation_status=observation_status,
        cadence_contract_version=cadence_contract_version,
        source_state=source_state,
        primary_source_freshness_limit_seconds=primary_source_freshness_limit_seconds,
        supporting_source_freshness_limit_seconds=supporting_source_freshness_limit_seconds,
        geometry_action=geometry_action,
        observation_reason_code=result.reason_code,
        observation_detail=result.detail,
        context_status=context_status,
        current_map_id_before=current_map_id_before,
        current_map_id_after=current_map_id_after,
        published_map_id=result.map_id if result.status == "published" else None,
        generation_attempt_id=result.generation_attempt_id,
        generation_event_id=(result.generation_event_ids[-1] if result.generation_event_ids else None),
        lifecycle_event_id=lifecycle_event_id,
        lifecycle_state_before=lifecycle_state_before,
        lifecycle_state_after=lifecycle_state_after,
        structure_hash=result.structure_hash,
        primary_latest_candle_ts_utc=primary_latest_candle_ts_utc,
        supporting_latest_candle_ts_utc=supporting_latest_candle_ts_utc,
        source_primary_candle_count=source_primary_candle_count,
        source_support_candle_count=source_support_candle_count,
    )


@dataclass(frozen=True)
class ScopeEvaluationOutcome:
    key: NativeShortMapScopeKey
    skipped_not_supported: bool
    observation: NativeShortScopeObservationRecord | None
    published_map: bool
    lifecycle_event_appended: bool
    failed: bool


# ---------------------------------------------------------------------------
# Thin MariaDB I/O
# ---------------------------------------------------------------------------

_SCOPE_KEY_COLUMNS = (
    "venue",
    "symbol",
    "quote_currency",
    "fib_trading_horizon",
    "primary_interval",
    "supporting_interval",
)
_SCOPE_KEY_WHERE = " AND ".join(f"{column} = %s" for column in _SCOPE_KEY_COLUMNS)


def _scope_key_params(key: NativeShortMapScopeKey) -> tuple[str, ...]:
    return (
        key.venue,
        key.symbol,
        key.quote_currency,
        key.fib_trading_horizon,
        key.primary_interval,
        key.supporting_interval,
    )


def fetch_scope_support_events(conn: Any, key: NativeShortMapScopeKey) -> list[ScopeSupportEventFact]:
    sql = f"""
    SELECT scope_support_event_id, scope_support_state, event_ts_utc
    FROM native_short_scope_support_event_v1
    WHERE {_SCOPE_KEY_WHERE}
    ORDER BY event_ts_utc ASC, scope_support_event_id ASC
    """
    with conn.cursor() as cur:
        cur.execute(sql, _scope_key_params(key))
        rows = list(cur.fetchall())
    return [
        ScopeSupportEventFact(
            scope_support_event_id=int(row["scope_support_event_id"]),
            scope_support_state=str(row["scope_support_state"]),
            event_ts_utc=row["event_ts_utc"],
        )
        for row in rows
    ]


def fetch_cadence_configs(conn: Any, key: NativeShortMapScopeKey) -> list[CadenceConfigFact]:
    sql = f"""
    SELECT cadence_contract_version, target_evaluation_interval,
           primary_source_freshness_limit_seconds, supporting_source_freshness_limit_seconds,
           evaluation_grace_seconds, recent_scope_grace_seconds,
           effective_from_utc, effective_to_utc
    FROM native_short_scope_cadence_config_v1
    WHERE {_SCOPE_KEY_WHERE}
    """
    with conn.cursor() as cur:
        cur.execute(sql, _scope_key_params(key))
        rows = list(cur.fetchall())
    return [
        CadenceConfigFact(
            cadence_contract_version=str(row["cadence_contract_version"]),
            target_evaluation_interval=str(row["target_evaluation_interval"]),
            primary_source_freshness_limit_seconds=int(row["primary_source_freshness_limit_seconds"]),
            supporting_source_freshness_limit_seconds=int(row["supporting_source_freshness_limit_seconds"]),
            evaluation_grace_seconds=int(row["evaluation_grace_seconds"]),
            recent_scope_grace_seconds=int(row["recent_scope_grace_seconds"]),
            effective_from_utc=row["effective_from_utc"],
            effective_to_utc=row.get("effective_to_utc"),
        )
        for row in rows
    ]


def fetch_scope_observations(conn: Any, key: NativeShortMapScopeKey) -> list[ObservationFact]:
    sql = f"""
    SELECT scope_observation_id, run_id, observed_at_utc, observation_status, observation_reason_code
    FROM native_short_scope_observation_v1
    WHERE {_SCOPE_KEY_WHERE}
    ORDER BY observed_at_utc ASC, scope_observation_id ASC
    """
    with conn.cursor() as cur:
        cur.execute(sql, _scope_key_params(key))
        rows = list(cur.fetchall())
    return [
        ObservationFact(
            scope_observation_id=int(row["scope_observation_id"]),
            run_id=int(row["run_id"]),
            observed_at_utc=row["observed_at_utc"],
            observation_status=row.get("observation_status"),
            observation_reason_code=row.get("observation_reason_code"),
        )
        for row in rows
    ]


def _to_map_facts(maps: Sequence[Any]) -> list[MapFact]:
    return [
        MapFact(
            map_id=item.map_id,
            published_at_utc=item.published_at_utc,
            map_cycle_id=item.map_cycle_id,
            structure_hash=item.structure_hash,
        )
        for item in maps
    ]


def _to_generation_event_facts(events: Sequence[Any]) -> list[GenerationEventFact]:
    return [
        GenerationEventFact(generation_event_id=event.generation_event_id, event_ts_utc=event.event_ts_utc)
        for event in events
    ]


def _to_lifecycle_event_facts(events: Sequence[Any]) -> list[LifecycleEventFact]:
    return [
        LifecycleEventFact(
            lifecycle_event_id=event.lifecycle_event_id,
            map_id=event.map_id,
            event_type=event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type),
            event_ts_utc=event.event_ts_utc,
            successor_map_id=event.successor_map_id,
        )
        for event in events
    ]


def _insert_run(conn: Any, record: NativeShortMaterializerRunRecord) -> int:
    sql = """
    INSERT INTO native_short_materializer_run_v1 (
        run_uuid, runner_name, runner_version, contract_version, trigger_type,
        started_at_utc, requested_scope_count
    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                record.run_uuid,
                record.runner_name,
                record.runner_version,
                record.contract_version,
                record.trigger_type,
                record.started_at_utc,
                record.requested_scope_count,
            ),
        )
        return int(cur.lastrowid)


def _finalize_run(conn: Any, run_id: int, record: NativeShortMaterializerRunRecord) -> None:
    sql = """
    UPDATE native_short_materializer_run_v1
    SET finished_at_utc = %s,
        terminal_status = %s,
        observed_scope_count = %s,
        published_map_count = %s,
        lifecycle_event_count = %s,
        failed_scope_count = %s,
        failure_reason_code = %s,
        failure_detail = %s
    WHERE run_id = %s
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                record.finished_at_utc,
                str(record.terminal_status),
                record.observed_scope_count,
                record.published_map_count,
                record.lifecycle_event_count,
                record.failed_scope_count,
                record.failure_reason_code,
                record.failure_detail,
                run_id,
            ),
        )


def _insert_observation(conn: Any, record: NativeShortScopeObservationRecord) -> int:
    sql = """
    INSERT INTO native_short_scope_observation_v1 (
        run_id, run_uuid, venue, symbol, quote_currency, fib_trading_horizon,
        primary_interval, supporting_interval, observed_at_utc,
        evaluation_due_at_utc, cadence_contract_version,
        observation_status, observation_reason_code, observation_detail,
        source_state, primary_latest_candle_ts_utc, supporting_latest_candle_ts_utc,
        primary_source_freshness_limit_seconds, supporting_source_freshness_limit_seconds,
        context_status, current_map_id_before, current_map_id_after,
        published_map_id, generation_attempt_id, generation_event_id, lifecycle_event_id,
        lifecycle_state_before, lifecycle_state_after, geometry_action, structure_hash,
        source_primary_candle_count, source_support_candle_count
    ) VALUES (
        %s, %s, %s, %s, %s, %s,
        %s, %s, %s,
        %s, %s,
        %s, %s, %s,
        %s, %s, %s,
        %s, %s,
        %s, %s, %s,
        %s, %s, %s, %s,
        %s, %s, %s, %s,
        %s, %s
    )
    """
    key = record.key
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                record.run_id,
                record.run_uuid,
                key.venue,
                key.symbol,
                key.quote_currency,
                key.fib_trading_horizon,
                key.primary_interval,
                key.supporting_interval,
                record.observed_at_utc,
                record.evaluation_due_at_utc,
                record.cadence_contract_version,
                str(record.observation_status),
                record.observation_reason_code,
                record.observation_detail,
                str(record.source_state) if record.source_state is not None else None,
                record.primary_latest_candle_ts_utc,
                record.supporting_latest_candle_ts_utc,
                record.primary_source_freshness_limit_seconds,
                record.supporting_source_freshness_limit_seconds,
                record.context_status,
                record.current_map_id_before,
                record.current_map_id_after,
                record.published_map_id,
                record.generation_attempt_id,
                record.generation_event_id,
                record.lifecycle_event_id,
                record.lifecycle_state_before,
                record.lifecycle_state_after,
                str(record.geometry_action) if record.geometry_action is not None else None,
                record.structure_hash,
                record.source_primary_candle_count,
                record.source_support_candle_count,
            ),
        )
        return int(cur.lastrowid)


def _insert_lifecycle_event(
    conn: Any,
    *,
    map_id: int,
    event_type: NativeShortMapLifecycleEventType,
    event_ts_utc: datetime,
) -> int:
    sql = """
    INSERT INTO native_short_map_lifecycle_event_v1 (
        map_id, lifecycle_event_type, event_ts_utc, observer_name, observer_version
    ) VALUES (%s, %s, %s, %s, %s)
    """
    with conn.cursor() as cur:
        cur.execute(sql, (map_id, event_type.value, event_ts_utc, RUNNER_NAME, RUNNER_VERSION))
        return int(cur.lastrowid)


def upsert_scope_status_projection(conn: Any, record: NativeShortScopeStatusRecord) -> None:
    """Deterministic per-scope upsert keyed on the full canonical scope key.
    Writes only native_short_scope_status_v1; never touches source ledgers."""
    key = record.key
    sql = """
    INSERT INTO native_short_scope_status_v1 (
        venue, symbol, quote_currency, fib_trading_horizon, primary_interval, supporting_interval,
        scope_support_state, scope_status_code, scope_status_reason_code,
        map_lifecycle_state, observation_freshness_state, source_freshness_state, actionability_state,
        current_map_id, current_map_cycle_id, current_map_published_at_utc, current_map_structure_hash,
        latest_generation_event_id, latest_lifecycle_event_id,
        latest_observation_id, latest_run_id, latest_observed_at_utc,
        next_expected_evaluation_at_utc, observation_overdue_after_utc,
        primary_latest_candle_ts_utc, supporting_latest_candle_ts_utc,
        primary_source_freshness_limit_seconds, supporting_source_freshness_limit_seconds,
        cadence_contract_version, projection_as_of_utc, status_payload_json
    ) VALUES (
        %s, %s, %s, %s, %s, %s,
        %s, %s, %s,
        %s, %s, %s, %s,
        %s, %s, %s, %s,
        %s, %s,
        %s, %s, %s,
        %s, %s,
        %s, %s,
        %s, %s,
        %s, %s, %s
    )
    ON DUPLICATE KEY UPDATE
        scope_support_state = VALUES(scope_support_state),
        scope_status_code = VALUES(scope_status_code),
        scope_status_reason_code = VALUES(scope_status_reason_code),
        map_lifecycle_state = VALUES(map_lifecycle_state),
        observation_freshness_state = VALUES(observation_freshness_state),
        source_freshness_state = VALUES(source_freshness_state),
        actionability_state = VALUES(actionability_state),
        current_map_id = VALUES(current_map_id),
        current_map_cycle_id = VALUES(current_map_cycle_id),
        current_map_published_at_utc = VALUES(current_map_published_at_utc),
        current_map_structure_hash = VALUES(current_map_structure_hash),
        latest_generation_event_id = VALUES(latest_generation_event_id),
        latest_lifecycle_event_id = VALUES(latest_lifecycle_event_id),
        latest_observation_id = VALUES(latest_observation_id),
        latest_run_id = VALUES(latest_run_id),
        latest_observed_at_utc = VALUES(latest_observed_at_utc),
        next_expected_evaluation_at_utc = VALUES(next_expected_evaluation_at_utc),
        observation_overdue_after_utc = VALUES(observation_overdue_after_utc),
        primary_latest_candle_ts_utc = VALUES(primary_latest_candle_ts_utc),
        supporting_latest_candle_ts_utc = VALUES(supporting_latest_candle_ts_utc),
        primary_source_freshness_limit_seconds = VALUES(primary_source_freshness_limit_seconds),
        supporting_source_freshness_limit_seconds = VALUES(supporting_source_freshness_limit_seconds),
        cadence_contract_version = VALUES(cadence_contract_version),
        projection_as_of_utc = VALUES(projection_as_of_utc),
        status_payload_json = VALUES(status_payload_json)
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
                str(record.scope_support_state),
                str(record.scope_status_code),
                record.scope_status_reason_code,
                str(record.map_lifecycle_state),
                str(record.observation_freshness_state),
                str(record.source_freshness_state) if record.source_freshness_state is not None else None,
                str(record.actionability_state),
                record.current_map_id,
                record.current_map_cycle_id,
                record.current_map_published_at_utc,
                record.current_map_structure_hash,
                record.latest_generation_event_id,
                record.latest_lifecycle_event_id,
                record.latest_observation_id,
                record.latest_run_id,
                record.latest_observed_at_utc,
                record.next_expected_evaluation_at_utc,
                record.observation_overdue_after_utc,
                record.primary_latest_candle_ts_utc,
                record.supporting_latest_candle_ts_utc,
                record.primary_source_freshness_limit_seconds,
                record.supporting_source_freshness_limit_seconds,
                record.cadence_contract_version,
                record.projection_as_of_utc,
                record.status_payload_json,
            ),
        )


def rebuild_scope_projection(
    conn: Any,
    *,
    key: NativeShortMapScopeKey,
    as_of_utc: datetime,
    rebuilt_at_utc: datetime,
    existing_maps: Sequence[Any],
    existing_generation_events: Sequence[Any],
    existing_lifecycle_events: Sequence[Any],
    primary_candle_close_timestamps: Sequence[datetime],
    supporting_candle_close_timestamps: Sequence[datetime],
) -> NativeShortScopeStatusRecord | None:
    """Fetch cutoff-independent facts already held in memory plus the
    support-event/cadence-config/observation ledgers, project, and upsert.
    Read-only against every table except native_short_scope_status_v1."""
    support_events = fetch_scope_support_events(conn, key)
    cadence_configs = fetch_cadence_configs(conn, key)
    observations = fetch_scope_observations(conn, key)
    record = project_native_short_scope_status(
        key=key,
        as_of_utc=as_of_utc,
        support_events=support_events,
        cadence_configs=cadence_configs,
        maps=_to_map_facts(existing_maps),
        generation_events=_to_generation_event_facts(existing_generation_events),
        lifecycle_events=_to_lifecycle_event_facts(existing_lifecycle_events),
        observations=observations,
        primary_candle_close_timestamps=primary_candle_close_timestamps,
        supporting_candle_close_timestamps=supporting_candle_close_timestamps,
        rebuilt_at_utc=rebuilt_at_utc,
    )
    if record is not None:
        upsert_scope_status_projection(conn, record)
    return record


def evaluate_scope(
    conn: Any,
    *,
    key: NativeShortMapScopeKey,
    as_of_utc: datetime,
    run_id: int,
    run_uuid: str,
    fetch_context_row: Callable[[NativeShortMapScopeKey, datetime], NativeShortContextRow | None],
    fetch_existing_maps: Callable[[Any, NativeShortMapScopeKey], list[Any]],
    fetch_existing_generation_events: Callable[[Any, NativeShortMapScopeKey], list[Any]],
    fetch_existing_lifecycle_events: Callable[[Any, list[int]], list[Any]],
    materialize_scope_symbol_fn: Callable[..., ScopeMaterializationResult] = materialize_scope_symbol,
) -> ScopeEvaluationOutcome:
    """Evaluate exactly one canonical scope for one bounded run.

    `fetch_context_row(key, as_of_utc)` must return candle-derived context
    bounded to `as_of_utc` (or None if no candles are available at all); this
    module never fetches candles itself so it never risks reading future
    data relative to `as_of_utc`.
    """
    support_events = fetch_scope_support_events(conn, key)
    support_state = resolve_scope_support_state_at_cutoff(support_events, as_of_utc)
    if support_state != NativeShortScopeSupportEventState.SUPPORTED:
        return ScopeEvaluationOutcome(
            key=key,
            skipped_not_supported=True,
            observation=None,
            published_map=False,
            lifecycle_event_appended=False,
            failed=False,
        )

    cadence_configs = fetch_cadence_configs(conn, key)
    cadence_config = select_eligible_cadence_config(cadence_configs, as_of_utc)
    if cadence_config is None:
        observation = build_configuration_unavailable_observation(
            key=key, run_id=run_id, run_uuid=run_uuid, observed_at_utc=as_of_utc
        )
        _insert_observation(conn, observation)
        return ScopeEvaluationOutcome(
            key=key,
            skipped_not_supported=False,
            observation=observation,
            published_map=False,
            lifecycle_event_appended=False,
            failed=False,
        )

    existing_maps = fetch_existing_maps(conn, key)
    existing_generation_events = fetch_existing_generation_events(conn, key)
    existing_lifecycle_events = fetch_existing_lifecycle_events(conn, [item.map_id for item in existing_maps])
    map_facts_before = _to_map_facts(existing_maps)
    lifecycle_facts_before = _to_lifecycle_event_facts(existing_lifecycle_events)
    map_before, map_lifecycle_state_before, _ = select_current_map(map_facts_before, lifecycle_facts_before, as_of_utc)

    context_row = fetch_context_row(key, as_of_utc)
    if context_row is None or context_row.context_status == STATUS_SYMBOL_MISSING:
        observation = build_source_unavailable_observation(
            key=key,
            run_id=run_id,
            run_uuid=run_uuid,
            observed_at_utc=as_of_utc,
            cadence_contract_version=cadence_config.cadence_contract_version,
            primary_source_freshness_limit_seconds=cadence_config.primary_source_freshness_limit_seconds,
            supporting_source_freshness_limit_seconds=cadence_config.supporting_source_freshness_limit_seconds,
            current_map_id_before=map_before.map_id if map_before is not None else None,
        )
        _insert_observation(conn, observation)
        return ScopeEvaluationOutcome(
            key=key,
            skipped_not_supported=False,
            observation=observation,
            published_map=False,
            lifecycle_event_appended=False,
            failed=False,
        )

    scope_support = NativeShortMapScopeSupport(key=key, support_state=NativeShortMapScopeSupportState.SUPPORTED)
    try:
        result = materialize_scope_symbol_fn(
            conn,
            scope_support=scope_support,
            context_row=context_row,
            now_utc=as_of_utc,
            write=True,
        )
    except Exception as exc:  # noqa: BLE001 - preserved as observation evidence, not swallowed
        observation = NativeShortScopeObservationRecord(
            key=key,
            run_id=run_id,
            run_uuid=run_uuid,
            observed_at_utc=as_of_utc,
            observation_status=NativeShortScopeObservationStatus.FAILED,
            cadence_contract_version=cadence_config.cadence_contract_version,
            source_state=NativeShortScopeSourceState.SOURCE_UNAVAILABLE,
            primary_source_freshness_limit_seconds=cadence_config.primary_source_freshness_limit_seconds,
            supporting_source_freshness_limit_seconds=cadence_config.supporting_source_freshness_limit_seconds,
            geometry_action=NativeShortScopeGeometryAction.NO_MAP_AVAILABLE,
            observation_reason_code=type(exc).__name__,
            observation_detail=str(exc),
            current_map_id_before=map_before.map_id if map_before is not None else None,
        )
        _insert_observation(conn, observation)
        return ScopeEvaluationOutcome(
            key=key,
            skipped_not_supported=False,
            observation=observation,
            published_map=False,
            lifecycle_event_appended=False,
            failed=True,
        )

    geometry_action = map_geometry_action(result)
    source_state = classify_source_freshness(
        primary_latest_ts=context_row.latest_primary_close_ts_utc,
        supporting_latest_ts=context_row.latest_support_close_ts_utc,
        as_of_utc=as_of_utc,
        cadence_config=cadence_config,
    )

    existing_maps_after = fetch_existing_maps(conn, key)
    existing_lifecycle_events_after = fetch_existing_lifecycle_events(
        conn, [item.map_id for item in existing_maps_after]
    )
    map_facts_after = _to_map_facts(existing_maps_after)
    lifecycle_facts_after = _to_lifecycle_event_facts(existing_lifecycle_events_after)
    map_after, map_lifecycle_state_after, _ = select_current_map(map_facts_after, lifecycle_facts_after, as_of_utc)

    lifecycle_event_id: int | None = None
    lifecycle_event_appended = False
    if map_after is not None:
        existing_types_for_map = frozenset(
            event.event_type for event in lifecycle_facts_after if event.map_id == map_after.map_id
        )
        transition = decide_genuine_lifecycle_transition(
            selected_map=map_after,
            context_row=context_row,
            existing_lifecycle_event_types_for_map=existing_types_for_map,
        )
        if transition is not None:
            lifecycle_event_id = _insert_lifecycle_event(
                conn, map_id=map_after.map_id, event_type=transition, event_ts_utc=as_of_utc
            )
            lifecycle_event_appended = True
            map_lifecycle_state_after = (
                {
                    NativeShortMapLifecycleEventType.COMPLETED: "MAP_COMPLETED",
                    NativeShortMapLifecycleEventType.INVALIDATED: "MAP_INVALIDATED",
                }[transition]
            )

    observation = build_normal_observation(
        key=key,
        run_id=run_id,
        run_uuid=run_uuid,
        observed_at_utc=as_of_utc,
        cadence_contract_version=cadence_config.cadence_contract_version,
        source_state=source_state,
        primary_source_freshness_limit_seconds=cadence_config.primary_source_freshness_limit_seconds,
        supporting_source_freshness_limit_seconds=cadence_config.supporting_source_freshness_limit_seconds,
        geometry_action=geometry_action,
        result=result,
        current_map_id_before=map_before.map_id if map_before is not None else None,
        current_map_id_after=map_after.map_id if map_after is not None else None,
        lifecycle_event_id=lifecycle_event_id,
        lifecycle_state_before=str(map_lifecycle_state_before),
        lifecycle_state_after=str(map_lifecycle_state_after),
        primary_latest_candle_ts_utc=context_row.latest_primary_close_ts_utc,
        supporting_latest_candle_ts_utc=context_row.latest_support_close_ts_utc,
        context_status=context_row.context_status,
        source_primary_candle_count=context_row.source_primary_candle_count,
        source_support_candle_count=context_row.source_support_candle_count,
    )
    _insert_observation(conn, observation)

    return ScopeEvaluationOutcome(
        key=key,
        skipped_not_supported=False,
        observation=observation,
        published_map=result.status == "published",
        lifecycle_event_appended=lifecycle_event_appended,
        failed=result.status == "failed",
    )


def run_native_short_scope_status_materializer(
    conn: Any,
    *,
    scopes: Sequence[NativeShortMapScopeKey],
    as_of_utc: datetime,
    trigger_type: str,
    fetch_context_row: Callable[[NativeShortMapScopeKey, datetime], NativeShortContextRow | None],
    fetch_existing_maps: Callable[[Any, NativeShortMapScopeKey], list[Any]],
    fetch_existing_generation_events: Callable[[Any, NativeShortMapScopeKey], list[Any]],
    fetch_existing_lifecycle_events: Callable[[Any, list[int]], list[Any]],
    fetch_primary_candle_close_timestamps: Callable[[NativeShortMapScopeKey, datetime], list[datetime]],
    fetch_supporting_candle_close_timestamps: Callable[[NativeShortMapScopeKey, datetime], list[datetime]],
    run_uuid: str | None = None,
    materialize_scope_symbol_fn: Callable[..., ScopeMaterializationResult] = materialize_scope_symbol,
) -> NativeShortMaterializerRunRecord:
    """Bounded run over an explicit scope list at one explicit as_of_utc.

    Exactly one native_short_materializer_run_v1 row is inserted at start and
    finalized once at the end. Every SUPPORTED scope gets exactly one
    append-only observation and, when SUPPORTED, one rebuilt/upserted
    projection row; NOT_APPLICABLE/UNKNOWN_AT_AS_OF scopes get neither.
    """
    builder = NativeShortRunBuilder(
        run_uuid=run_uuid or str(uuid.uuid4()),
        runner_name=RUNNER_NAME,
        runner_version=RUNNER_VERSION,
        contract_version=CONTRACT_VERSION,
        trigger_type=trigger_type,
        started_at_utc=as_of_utc,
        requested_scope_count=len(scopes),
    )
    run_id = _insert_run(conn, builder.started_record())

    for key in scopes:
        outcome = evaluate_scope(
            conn,
            key=key,
            as_of_utc=as_of_utc,
            run_id=run_id,
            run_uuid=builder.run_uuid,
            fetch_context_row=fetch_context_row,
            fetch_existing_maps=fetch_existing_maps,
            fetch_existing_generation_events=fetch_existing_generation_events,
            fetch_existing_lifecycle_events=fetch_existing_lifecycle_events,
            materialize_scope_symbol_fn=materialize_scope_symbol_fn,
        )
        if outcome.skipped_not_supported:
            continue

        builder.record_scope_outcome(
            published_map=outcome.published_map,
            lifecycle_event_appended=outcome.lifecycle_event_appended,
            failed=outcome.failed,
        )

        existing_maps = fetch_existing_maps(conn, key)
        existing_generation_events = fetch_existing_generation_events(conn, key)
        existing_lifecycle_events = fetch_existing_lifecycle_events(
            conn, [item.map_id for item in existing_maps]
        )
        rebuild_scope_projection(
            conn,
            key=key,
            as_of_utc=as_of_utc,
            rebuilt_at_utc=as_of_utc,
            existing_maps=existing_maps,
            existing_generation_events=existing_generation_events,
            existing_lifecycle_events=existing_lifecycle_events,
            primary_candle_close_timestamps=fetch_primary_candle_close_timestamps(key, as_of_utc),
            supporting_candle_close_timestamps=fetch_supporting_candle_close_timestamps(key, as_of_utc),
        )

    finished_record = builder.finish(finished_at_utc=as_of_utc)
    _finalize_run(conn, run_id, finished_record)
    return finished_record
