from __future__ import annotations

"""Native SHORT current map-level status materializer (V1).

Safety markers:
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none

Boundary:
- Market-only, account-agnostic, rebuildable current level-status materializer,
  implementing docs/architecture/native_short_map_level_status_contract_v1.md.
- Reads exactly one native_short_scope_status_v1 row by full scope key, reads
  immutable native_short_map_v1 geometry by that row's current_map_id, reads
  persisted closed primary-interval candles only when the active-evaluation
  gate holds, resolves public tick metadata, and atomically rebuilds
  native_short_map_level_status_v1 for that scope via the persistence layer
  in native_short_map_level_status_v1.py.
- Does not select a map by timestamp/generation/lifecycle-ledger heuristics,
  does not append map/generation/lifecycle heartbeat rows, does not read
  wall-clock time internally (the caller supplies `operational_clock`), and
  does not import reporting/account/broker/decision/execution/executor/
  selection_engine code.

Two layers, per the contract's "Materialization Ownership" section:
  pure layer    - select_gate_decision, extract_v1_sell_geometry,
                  select_eligible_primary_candles, classify_level_state,
                  build_level_status_rows
  MariaDB layer - fetch_scope_status_projection, fetch_map_geometry_by_id,
                  fetch_eligible_primary_candles, resolve_scope_tick_rule,
                  materialize_native_short_map_level_status_for_scope
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Callable, Iterable, Sequence

from src.market_data.native_short_fib_context_v1 import Candle
from src.market_data.native_short_map_level_status_v1 import (
    NativeShortMapLevelEvaluationReference,
    NativeShortMapLevelRole,
    NativeShortMapLevelSide,
    NativeShortMapLevelState,
    NativeShortMapLevelStatusRecord,
    REASON_MAP_COMPLETED,
    REASON_MAP_EXPIRED,
    REASON_MAP_INVALIDATED,
    REASON_NO_PRIMARY_HIGH_REACHED_LEVEL,
    REASON_PRIMARY_CLOSE_PASSED_LEVEL,
    REASON_PRIMARY_HIGH_REACHED_WITHOUT_CLOSE_ABOVE,
    V1_NATIVE_SHORT_SELL_LEVEL_ROLES,
    delete_native_short_map_level_status_for_scope,
    replace_native_short_map_level_status_for_scope,
)
from src.market_data.native_short_map_lifecycle_v1 import NativeShortMapRecord, NativeShortMapScopeKey
from src.market_data.native_short_scope_status_v1 import (
    NativeShortObservationFreshnessState,
    NativeShortScopeActionabilityState,
    NativeShortScopeMapLifecycleState,
    NativeShortScopeSourceState,
    NativeShortScopeStatusCode,
    NativeShortScopeStatusRecord,
    NativeShortScopeStatusValidationError,
    validate_native_short_scope_key,
)
from src.market_rules.price_tick_normalization_v1 import (
    NORM_STATUS_MISSING,
    PRICE_ROLE_TARGET_SELL,
    TickRule,
    load_tick_rules_from_db,
    normalize_price_to_tick,
    resolve_tick_rule,
)

__all__ = [
    "BLOCKED",
    "ACTIVE_EVALUATION",
    "TERMINAL_COMPLETED",
    "TERMINAL_HISTORICAL",
    "GEOMETRY_INVALID",
    "NO_CURRENT_MAP",
    "PROJECTION_INVALID",
    "PROJECTION_MISSING",
    "MapLevelStatusMaterializationOutcome",
    "NativeShortMapLevelStatusMaterializerError",
    "build_level_status_rows",
    "classify_level_state",
    "extract_v1_sell_geometry",
    "fetch_eligible_primary_candles",
    "fetch_map_geometry_by_id",
    "fetch_scope_status_projection",
    "materialize_native_short_map_level_status_for_scope",
    "resolve_scope_tick_rule",
    "select_eligible_primary_candles",
    "select_gate_decision",
]

_V1_ROLE_TO_GEOMETRY_KEY: dict[NativeShortMapLevelRole, str] = {
    NativeShortMapLevelRole.SELL_EXT_1_272: "ext_1_272",
    NativeShortMapLevelRole.SELL_EXT_1_618: "ext_1_618",
    NativeShortMapLevelRole.SELL_EXT_2_000: "ext_2_000",
}

# Fail-closed / gate outcome reason codes not already defined as scope-status
# enum values (those are reused verbatim as reason codes when they apply).
PROJECTION_MISSING = "PROJECTION_MISSING"
PROJECTION_INVALID = "PROJECTION_INVALID"
GEOMETRY_INVALID = "GEOMETRY_INVALID"
NO_CURRENT_MAP = "NO_CURRENT_MAP"

# Gate decision branches.
ACTIVE_EVALUATION = "ACTIVE_EVALUATION"
TERMINAL_COMPLETED = "TERMINAL_COMPLETED"
TERMINAL_HISTORICAL = "TERMINAL_HISTORICAL"
BLOCKED = "BLOCKED"


class NativeShortMapLevelStatusMaterializerError(RuntimeError):
    pass


@dataclass(frozen=True)
class MapLevelStatusMaterializationOutcome:
    key: NativeShortMapScopeKey
    branch: str
    reason_code: str | None
    row_count: int
    current_map_id: int | None
    map_cycle_id: str | None
    level_status_as_of_utc: datetime | None


def _ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _dec(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


# ---------------------------------------------------------------------------
# Pure layer
# ---------------------------------------------------------------------------


def select_gate_decision(projection: NativeShortScopeStatusRecord) -> tuple[str, str | None]:
    """Pure decision from an already-validated projection row's fields only.

    Returns (branch, reason_code). branch is one of ACTIVE_EVALUATION,
    TERMINAL_COMPLETED, TERMINAL_HISTORICAL, or BLOCKED. Every terminal branch
    requires the full triple of map_lifecycle_state / scope_status_code /
    actionability_state to agree (where a matching scope_status_code exists);
    any disagreement fails closed to BLOCKED rather than fabricating a
    terminal row, since native_short_scope_status_v1's own dataclass does not
    independently enforce that cross-field consistency for terminal states.
    """
    if projection.current_map_id is None or not projection.current_map_cycle_id:
        return (BLOCKED, NO_CURRENT_MAP)

    scope_status = NativeShortScopeStatusCode(str(projection.scope_status_code))
    map_lifecycle = NativeShortScopeMapLifecycleState(str(projection.map_lifecycle_state))
    actionability = NativeShortScopeActionabilityState(str(projection.actionability_state))
    observation_freshness = NativeShortObservationFreshnessState(str(projection.observation_freshness_state))
    source_freshness = (
        NativeShortScopeSourceState(str(projection.source_freshness_state))
        if projection.source_freshness_state is not None
        else None
    )

    if (
        scope_status == NativeShortScopeStatusCode.CURRENT_EVALUATION
        and source_freshness == NativeShortScopeSourceState.SOURCE_CURRENT
        and observation_freshness == NativeShortObservationFreshnessState.OBSERVATION_CURRENT
        and actionability == NativeShortScopeActionabilityState.ACTIONABLE_ACTIVE_MAP
        and map_lifecycle == NativeShortScopeMapLifecycleState.MAP_ACTIVE
    ):
        return (ACTIVE_EVALUATION, None)

    if (
        map_lifecycle == NativeShortScopeMapLifecycleState.MAP_COMPLETED
        and scope_status == NativeShortScopeStatusCode.MAP_COMPLETED
        and actionability == NativeShortScopeActionabilityState.TERMINAL_MAP
    ):
        return (TERMINAL_COMPLETED, REASON_MAP_COMPLETED)

    if (
        map_lifecycle == NativeShortScopeMapLifecycleState.MAP_INVALIDATED
        and scope_status == NativeShortScopeStatusCode.MAP_INVALIDATED
        and actionability == NativeShortScopeActionabilityState.TERMINAL_MAP
    ):
        return (TERMINAL_HISTORICAL, REASON_MAP_INVALIDATED)

    if (
        map_lifecycle == NativeShortScopeMapLifecycleState.MAP_EXPIRED
        and actionability == NativeShortScopeActionabilityState.TERMINAL_MAP
    ):
        # No native_short_scope_status_v1 scope_status_code exists yet for
        # MAP_EXPIRED (see that module's own docstring) so only map lifecycle
        # and actionability are cross-checked here.
        return (TERMINAL_HISTORICAL, REASON_MAP_EXPIRED)

    return (BLOCKED, str(scope_status))


def extract_v1_sell_geometry(map_record: NativeShortMapRecord) -> dict[NativeShortMapLevelRole, Decimal]:
    """Extract the three named V1 SELL extension prices from immutable geometry.

    Fails closed (raises) on malformed, missing, or non-positive geometry, or
    a missing anchor_high_ts_utc, per the contract's Integrity Rules.
    """
    try:
        parsed = json.loads(map_record.fib_ratios_json or "")
    except (TypeError, ValueError) as exc:
        raise NativeShortMapLevelStatusMaterializerError(
            f"GEOMETRY_INVALID malformed_fib_ratios_json map_id={map_record.map_id}"
        ) from exc
    if not isinstance(parsed, dict):
        raise NativeShortMapLevelStatusMaterializerError(
            f"GEOMETRY_INVALID fib_ratios_json_not_object map_id={map_record.map_id}"
        )

    geometry: dict[NativeShortMapLevelRole, Decimal] = {}
    for role, geometry_key in _V1_ROLE_TO_GEOMETRY_KEY.items():
        raw = parsed.get(geometry_key)
        if raw is None:
            raise NativeShortMapLevelStatusMaterializerError(
                f"GEOMETRY_INVALID missing_level role={role.value} map_id={map_record.map_id}"
            )
        try:
            price = Decimal(str(raw))
        except Exception as exc:
            raise NativeShortMapLevelStatusMaterializerError(
                f"GEOMETRY_INVALID unparseable_level role={role.value} map_id={map_record.map_id}"
            ) from exc
        if price <= 0:
            raise NativeShortMapLevelStatusMaterializerError(
                f"GEOMETRY_INVALID non_positive_level role={role.value} map_id={map_record.map_id}"
            )
        geometry[role] = price

    if map_record.anchor_high_ts_utc is None:
        raise NativeShortMapLevelStatusMaterializerError(
            f"GEOMETRY_INVALID missing_anchor_high_ts_utc map_id={map_record.map_id}"
        )
    return geometry


def select_eligible_primary_candles(
    candles: Iterable[Candle],
    *,
    anchor_high_ts_utc: datetime,
    projection_as_of_utc: datetime,
) -> tuple[Candle, ...]:
    """Candle domain per contract: anchor_high_ts_utc <= close_ts_utc <= as_of."""
    return tuple(c for c in candles if anchor_high_ts_utc <= c.close_ts_utc <= projection_as_of_utc)


def classify_level_state(
    level_price: Decimal,
    eligible_candles: Sequence[Candle],
) -> tuple[NativeShortMapLevelState, str]:
    """V1 SELL-level lifecycle predicate (deterministic, monotonic).

    PASSED  = at least one eligible closed 4h candle has close_price > L
    REACHED = at least one eligible closed 4h candle has high_price >= L
              AND no eligible closed 4h candle has close_price > L
    ACTIVE  = no eligible closed 4h candle has high_price >= L
    """
    if any(c.close_price > level_price for c in eligible_candles):
        return (NativeShortMapLevelState.PASSED, REASON_PRIMARY_CLOSE_PASSED_LEVEL)
    if any(c.high_price >= level_price for c in eligible_candles):
        return (NativeShortMapLevelState.REACHED, REASON_PRIMARY_HIGH_REACHED_WITHOUT_CLOSE_ABOVE)
    return (NativeShortMapLevelState.ACTIVE, REASON_NO_PRIMARY_HIGH_REACHED_LEVEL)


def _normalize_level_price(price: Decimal, tick_rule: TickRule) -> tuple[Decimal | None, str, str]:
    result = normalize_price_to_tick(price, tick_rule, PRICE_ROLE_TARGET_SELL)
    rounded = None if result.price_rule_status == NORM_STATUS_MISSING else result.normalized_price
    return rounded, result.price_rule_status, result.rule_source


def build_level_status_rows(
    *,
    key: NativeShortMapScopeKey,
    projection: NativeShortScopeStatusRecord,
    map_record: NativeShortMapRecord,
    geometry: dict[NativeShortMapLevelRole, Decimal],
    tick_rule: TickRule,
    branch: str,
    terminal_reason_code: str | None,
    eligible_candles: Sequence[Candle],
    rebuilt_at_utc: datetime,
) -> tuple[NativeShortMapLevelStatusRecord, ...]:
    if branch not in (ACTIVE_EVALUATION, TERMINAL_COMPLETED, TERMINAL_HISTORICAL):
        raise NativeShortMapLevelStatusMaterializerError(f"UNEXPECTED_ROW_BUILD_BRANCH branch={branch}")

    rows: list[NativeShortMapLevelStatusRecord] = []
    for role in V1_NATIVE_SHORT_SELL_LEVEL_ROLES:
        price = geometry[role]
        rounded, tick_status, tick_source = _normalize_level_price(price, tick_rule)

        if branch == ACTIVE_EVALUATION:
            state, reason_code = classify_level_state(price, eligible_candles)
            evaluation_reference = NativeShortMapLevelEvaluationReference.PRIMARY_4H_CLOSED_CANDLES
        elif branch == TERMINAL_COMPLETED:
            state = NativeShortMapLevelState.COMPLETED
            reason_code = REASON_MAP_COMPLETED
            evaluation_reference = NativeShortMapLevelEvaluationReference.MAP_LIFECYCLE_EVENT
        else:
            state = NativeShortMapLevelState.HISTORICAL
            reason_code = terminal_reason_code or REASON_MAP_INVALIDATED
            evaluation_reference = NativeShortMapLevelEvaluationReference.MAP_LIFECYCLE_EVENT

        rows.append(
            NativeShortMapLevelStatusRecord(
                key=key,
                current_map_id=map_record.map_id,
                map_cycle_id=map_record.map_cycle_id or "",
                canonical_map_level_role=role,
                side=NativeShortMapLevelSide.SELL,
                canonical_unrounded_price=price,
                canonical_tick_rounded_price=rounded,
                tick_rule_status=tick_status,
                tick_rule_source=tick_source,
                level_lifecycle_state=state,
                level_status_as_of_utc=projection.projection_as_of_utc,
                evaluation_reference=evaluation_reference,
                reason_code=reason_code,
                projection_scope_status_code=projection.scope_status_code,
                projection_map_lifecycle_state=projection.map_lifecycle_state,
                projection_actionability_state=projection.actionability_state,
                rebuilt_at_utc=rebuilt_at_utc,
            )
        )
    return tuple(rows)


# ---------------------------------------------------------------------------
# MariaDB layer
# ---------------------------------------------------------------------------


def fetch_scope_status_projection(
    conn: Any,
    key: NativeShortMapScopeKey,
) -> NativeShortScopeStatusRecord | None:
    sql = """
    SELECT scope_support_state, scope_status_code, scope_status_reason_code, map_lifecycle_state,
           observation_freshness_state, source_freshness_state, actionability_state,
           current_map_id, current_map_cycle_id, current_map_published_at_utc, current_map_structure_hash,
           latest_generation_event_id, latest_lifecycle_event_id, latest_observation_id, latest_run_id,
           latest_observed_at_utc, next_expected_evaluation_at_utc, observation_overdue_after_utc,
           primary_latest_candle_ts_utc, supporting_latest_candle_ts_utc,
           primary_source_freshness_limit_seconds, supporting_source_freshness_limit_seconds,
           cadence_contract_version, projection_as_of_utc, status_payload_json, rebuilt_at_utc
    FROM native_short_scope_status_v1
    WHERE venue = %s AND symbol = %s AND quote_currency = %s
      AND fib_trading_horizon = %s AND primary_interval = %s AND supporting_interval = %s
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
        row = cur.fetchone()
    if row is None:
        return None

    return NativeShortScopeStatusRecord(
        key=key,
        scope_support_state=row["scope_support_state"],
        scope_status_code=row["scope_status_code"],
        map_lifecycle_state=row["map_lifecycle_state"],
        observation_freshness_state=row["observation_freshness_state"],
        actionability_state=row["actionability_state"],
        projection_as_of_utc=_ensure_utc(row["projection_as_of_utc"]),
        rebuilt_at_utc=_ensure_utc(row["rebuilt_at_utc"]),
        source_freshness_state=row.get("source_freshness_state"),
        primary_source_freshness_limit_seconds=row.get("primary_source_freshness_limit_seconds"),
        supporting_source_freshness_limit_seconds=row.get("supporting_source_freshness_limit_seconds"),
        cadence_contract_version=row.get("cadence_contract_version"),
        scope_status_reason_code=row.get("scope_status_reason_code"),
        current_map_id=(int(row["current_map_id"]) if row.get("current_map_id") is not None else None),
        current_map_cycle_id=row.get("current_map_cycle_id"),
        current_map_published_at_utc=_ensure_utc(row.get("current_map_published_at_utc")),
        current_map_structure_hash=row.get("current_map_structure_hash"),
        latest_generation_event_id=row.get("latest_generation_event_id"),
        latest_lifecycle_event_id=row.get("latest_lifecycle_event_id"),
        latest_observation_id=row.get("latest_observation_id"),
        latest_run_id=row.get("latest_run_id"),
        latest_observed_at_utc=_ensure_utc(row.get("latest_observed_at_utc")),
        next_expected_evaluation_at_utc=_ensure_utc(row.get("next_expected_evaluation_at_utc")),
        observation_overdue_after_utc=_ensure_utc(row.get("observation_overdue_after_utc")),
        primary_latest_candle_ts_utc=_ensure_utc(row.get("primary_latest_candle_ts_utc")),
        supporting_latest_candle_ts_utc=_ensure_utc(row.get("supporting_latest_candle_ts_utc")),
        status_payload_json=row.get("status_payload_json"),
    )


def fetch_map_geometry_by_id(
    conn: Any,
    key: NativeShortMapScopeKey,
    map_id: int,
) -> NativeShortMapRecord | None:
    """Read immutable map geometry by exactly projection.current_map_id + full scope key."""
    sql = """
    SELECT map_id, structure_hash, generator_name, generator_version,
           fib_model_name, fib_model_version, published_generation_attempt_id,
           previous_map_id, previous_map_cycle_id, map_cycle_id,
           market_snapshot_ts_utc, published_at_utc,
           anchor_low_ts_utc, anchor_low_price, anchor_high_ts_utc, anchor_high_price,
           retrace_ratio, retrace_price, fib_ratios_json, target_levels_json,
           invalidation_price, invalidation_rule,
           source_primary_candle_ts_utc, source_support_candle_ts_utc,
           source_primary_ref, source_support_ref,
           source_primary_candle_count, source_support_candle_count,
           map_payload_json
    FROM native_short_map_v1
    WHERE map_id = %s AND venue = %s AND symbol = %s AND quote_currency = %s
      AND fib_trading_horizon = %s AND primary_interval = %s AND supporting_interval = %s
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                map_id,
                key.venue,
                key.symbol,
                key.quote_currency,
                key.fib_trading_horizon,
                key.primary_interval,
                key.supporting_interval,
            ),
        )
        row = cur.fetchone()
    if row is None:
        return None

    return NativeShortMapRecord(
        map_id=int(row["map_id"]),
        key=key,
        published_at_utc=_ensure_utc(row["published_at_utc"]),
        structure_hash=str(row["structure_hash"]),
        generator_name=str(row["generator_name"]),
        generator_version=str(row["generator_version"]),
        fib_model_name=str(row["fib_model_name"]),
        fib_model_version=str(row["fib_model_version"]),
        published_generation_attempt_id=str(row["published_generation_attempt_id"]),
        previous_map_id=(int(row["previous_map_id"]) if row.get("previous_map_id") is not None else None),
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


def fetch_eligible_primary_candles(
    conn: Any,
    key: NativeShortMapScopeKey,
    *,
    since_utc: datetime,
    until_utc: datetime,
) -> tuple[Candle, ...]:
    sql = """
    SELECT c.close_ts_utc, c.open_price, c.high_price, c.low_price, c.close_price
    FROM obs_market_candle c
    JOIN asset a ON a.asset_id = c.asset_id
    WHERE c.venue = %s AND c.interval_code = %s AND a.symbol = %s
      AND c.close_ts_utc >= %s AND c.close_ts_utc <= %s
    ORDER BY c.close_ts_utc ASC
    """
    with conn.cursor() as cur:
        cur.execute(sql, (key.venue, key.primary_interval, key.symbol, since_utc, until_utc))
        rows = list(cur.fetchall())
    return tuple(
        Candle(
            close_ts_utc=_ensure_utc(row["close_ts_utc"]),
            open_price=_dec(row["open_price"]),
            high_price=_dec(row["high_price"]),
            low_price=_dec(row["low_price"]),
            close_price=_dec(row["close_price"]),
        )
        for row in rows
    )


def resolve_scope_tick_rule(conn: Any, key: NativeShortMapScopeKey) -> TickRule:
    market = f"{key.symbol}-{key.quote_currency}"
    db_rules = load_tick_rules_from_db(conn, venue=key.venue, markets=[market])
    return resolve_tick_rule(venue=key.venue, market=market, db_rules=db_rules)


def materialize_native_short_map_level_status_for_scope(
    conn: Any,
    *,
    key: NativeShortMapScopeKey,
    operational_clock: Callable[[], datetime],
) -> MapLevelStatusMaterializationOutcome:
    """Bounded, single-scope rebuild. The caller owns the transaction boundary.

    Uses only the current native_short_scope_status_v1 row's own
    projection_as_of_utc as the semantic clock (no independent wall-clock
    read, no as_of_utc parameter). `operational_clock` supplies only the
    row-level `rebuilt_at_utc` operational metadata field, never a lifecycle
    input, mirroring the existing scope-status materializer's convention.
    """
    validate_native_short_scope_key(key)

    try:
        projection = fetch_scope_status_projection(conn, key)
    except NativeShortScopeStatusValidationError:
        delete_native_short_map_level_status_for_scope(conn, key=key)
        return MapLevelStatusMaterializationOutcome(
            key=key,
            branch=BLOCKED,
            reason_code=PROJECTION_INVALID,
            row_count=0,
            current_map_id=None,
            map_cycle_id=None,
            level_status_as_of_utc=None,
        )

    if projection is None:
        delete_native_short_map_level_status_for_scope(conn, key=key)
        return MapLevelStatusMaterializationOutcome(
            key=key,
            branch=BLOCKED,
            reason_code=PROJECTION_MISSING,
            row_count=0,
            current_map_id=None,
            map_cycle_id=None,
            level_status_as_of_utc=None,
        )

    branch, reason_code = select_gate_decision(projection)

    if branch == BLOCKED:
        delete_native_short_map_level_status_for_scope(conn, key=key)
        return MapLevelStatusMaterializationOutcome(
            key=key,
            branch=branch,
            reason_code=reason_code,
            row_count=0,
            current_map_id=projection.current_map_id,
            map_cycle_id=projection.current_map_cycle_id,
            level_status_as_of_utc=None,
        )

    map_record = fetch_map_geometry_by_id(conn, key, projection.current_map_id)
    identity_ok = map_record is not None and map_record.map_cycle_id == projection.current_map_cycle_id
    if not identity_ok:
        delete_native_short_map_level_status_for_scope(conn, key=key)
        return MapLevelStatusMaterializationOutcome(
            key=key,
            branch=BLOCKED,
            reason_code=PROJECTION_INVALID,
            row_count=0,
            current_map_id=projection.current_map_id,
            map_cycle_id=projection.current_map_cycle_id,
            level_status_as_of_utc=None,
        )

    try:
        geometry = extract_v1_sell_geometry(map_record)
    except NativeShortMapLevelStatusMaterializerError:
        delete_native_short_map_level_status_for_scope(conn, key=key)
        return MapLevelStatusMaterializationOutcome(
            key=key,
            branch=BLOCKED,
            reason_code=GEOMETRY_INVALID,
            row_count=0,
            current_map_id=projection.current_map_id,
            map_cycle_id=projection.current_map_cycle_id,
            level_status_as_of_utc=None,
        )

    if branch == ACTIVE_EVALUATION:
        eligible_candles = fetch_eligible_primary_candles(
            conn,
            key,
            since_utc=map_record.anchor_high_ts_utc,
            until_utc=projection.projection_as_of_utc,
        )
    else:
        eligible_candles = ()

    tick_rule = resolve_scope_tick_rule(conn, key)
    rebuilt_at_utc = operational_clock()

    rows = build_level_status_rows(
        key=key,
        projection=projection,
        map_record=map_record,
        geometry=geometry,
        tick_rule=tick_rule,
        branch=branch,
        terminal_reason_code=reason_code,
        eligible_candles=eligible_candles,
        rebuilt_at_utc=rebuilt_at_utc,
    )

    written = replace_native_short_map_level_status_for_scope(
        conn,
        key=key,
        current_map_id=map_record.map_id,
        map_cycle_id=map_record.map_cycle_id,
        level_status_as_of_utc=projection.projection_as_of_utc,
        rows=rows,
    )

    return MapLevelStatusMaterializationOutcome(
        key=key,
        branch=branch,
        reason_code=reason_code,
        row_count=written,
        current_map_id=map_record.map_id,
        map_cycle_id=map_record.map_cycle_id,
        level_status_as_of_utc=projection.projection_as_of_utc,
    )
