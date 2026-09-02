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
- native_short_map_scope_v1 (scope registration/inventory only)
- native_short_scope_status_v1 (the canonical rebuildable projection)

PR A3 correction: this report used to derive current freshness and
operational health from independent joins across native_short_map_v1,
native_short_map_generation_event_v1, native_short_map_lifecycle_event_v1,
and obs_market_candle. It no longer reads any of those tables. Every
freshness/lifecycle/actionability/status field now comes verbatim from the
persisted `native_short_scope_status_v1` row for the canonical scope key, per
docs/architecture/native_short_scope_status_contract_v1.md. This report does
not recompute projection precedence, freshness, or lifecycle logic; it only
reads and presents the already-rebuilt projection.

The only cross-package imports are:
- `src.market_data.native_short_map_lifecycle_v1`: shared, DB-free scope-key
  dataclass and canonical scope defaults.
- `src.market_data.native_short_scope_status_v1`: shared, DB-free projection
  contract (dataclasses, enums, and validation). Neither module performs DB
  access or writes; depending on them does not pull any ledger writer into
  this reporting lane.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.market_data.native_short_map_lifecycle_v1 import (
    DEFAULT_FIB_TRADING_HORIZON,
    DEFAULT_PRIMARY_INTERVAL,
    DEFAULT_QUOTE_CURRENCY,
    DEFAULT_SUPPORTING_INTERVAL,
    NativeShortMapScopeKey,
)
from src.market_data.native_short_scope_status_v1 import (
    NativeShortScopeStatusRecord,
    NativeShortScopeStatusValidationError,
)

DEFAULT_VENUE = "bitvavo"

SCOPE_STATUS_MISSING = "MISSING"
SCOPE_STATUS_SUPPORTED = "SUPPORTED"
SCOPE_STATUS_NOT_APPLICABLE = "NOT_APPLICABLE"
SCOPE_STATUS_AMBIGUOUS = "AMBIGUOUS"
SCOPE_STATUS_CONFLICTING = "CONFLICTING"

# Report-only state: a SUPPORTED scope with no native_short_scope_status_v1
# row at all. This is not a value the persistence contract defines, because
# the contract requires exactly one row per SUPPORTED scope; its absence is
# an operational anomaly for this report to surface explicitly, never to
# paper over as healthy.
PROJECTION_STATUS_FOUND = "FOUND"
PROJECTION_STATUS_MISSING = "MISSING"
PROJECTION_STATUS_INVALID = "INVALID"
PROJECTION_STATUS_NOT_EVALUATED = "NOT_EVALUATED"

OVERALL_HEALTH_HEALTHY = "HEALTHY"
OVERALL_HEALTH_NEEDS_REVIEW = "NEEDS_REVIEW"
OVERALL_HEALTH_NOT_APPLICABLE = "NOT_APPLICABLE"

STATUS_REPORTED = "reported"
STATUS_FAILED = "failed"

REASON_PROJECTION_ROW_MISSING = "PROJECTION_ROW_MISSING"
REASON_PROJECTION_ROW_INVALID = "PROJECTION_ROW_INVALID"


def _ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


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

    # Whether a native_short_scope_status_v1 lookup was attempted at all, and
    # what it found. Lookup is only attempted for SCOPE_STATUS_SUPPORTED.
    projection_status: str = PROJECTION_STATUS_NOT_EVALUATED

    # Canonical projection fields, forwarded verbatim -- never recomputed.
    scope_status_code: str | None = None
    scope_status_reason_code: str | None = None
    map_lifecycle_state: str | None = None
    observation_freshness_state: str | None = None
    source_freshness_state: str | None = None
    actionability_state: str | None = None

    # Map geometry vintage -- descriptive identity only, not a freshness input.
    current_map_id: int | None = None
    current_map_cycle_id: str | None = None
    current_map_published_at_utc: datetime | None = None
    current_map_structure_hash: str | None = None

    # Latest materializer evaluation.
    latest_run_id: int | None = None
    latest_observation_id: int | None = None
    latest_observed_at_utc: datetime | None = None
    next_expected_evaluation_at_utc: datetime | None = None
    observation_overdue_after_utc: datetime | None = None

    # Current source freshness inputs, as resolved by the projection.
    primary_latest_candle_ts_utc: datetime | None = None
    supporting_latest_candle_ts_utc: datetime | None = None
    primary_source_freshness_limit_seconds: int | None = None
    supporting_source_freshness_limit_seconds: int | None = None
    cadence_contract_version: str | None = None

    # Projection provenance/audit metadata.
    projection_as_of_utc: datetime | None = None
    projection_rebuilt_at_utc: datetime | None = None
    status_payload_json: str | None = None

    # Issue #681 Amendment 2: orthogonal healthy-wait vs overdue evidence for
    # a terminal selected map. NOT_APPLICABLE when the selected map is not
    # terminal. Forwarded verbatim, never recomputed here; #688 attention
    # triage may consume this without adding reporting-side lifecycle logic.
    recompute_transition_state: str | None = None

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


def parse_scope_status_row(row: dict[str, Any], key: NativeShortMapScopeKey) -> NativeShortScopeStatusRecord:
    """Parse one native_short_scope_status_v1 row into the validated pure
    contract type. Applies naive-datetime-to-UTC normalization (pymysql
    returns naive DATETIME columns); performs no other transformation --
    every value is forwarded exactly as persisted."""
    return NativeShortScopeStatusRecord(
        key=key,
        scope_support_state=row["scope_support_state"],
        scope_status_code=row["scope_status_code"],
        scope_status_reason_code=row.get("scope_status_reason_code"),
        map_lifecycle_state=row["map_lifecycle_state"],
        observation_freshness_state=row["observation_freshness_state"],
        source_freshness_state=row.get("source_freshness_state"),
        actionability_state=row["actionability_state"],
        current_map_id=row.get("current_map_id"),
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
        primary_source_freshness_limit_seconds=row.get("primary_source_freshness_limit_seconds"),
        supporting_source_freshness_limit_seconds=row.get("supporting_source_freshness_limit_seconds"),
        cadence_contract_version=row.get("cadence_contract_version"),
        projection_as_of_utc=_ensure_utc(row["projection_as_of_utc"]),
        rebuilt_at_utc=_ensure_utc(row["rebuilt_at_utc"]),
        status_payload_json=row.get("status_payload_json"),
        recompute_transition_state=row.get("recompute_transition_state"),
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
    scope_status_row: dict[str, Any] | None,
) -> LedgerHealthReport:
    """Build the deterministic health report from already-fetched rows.

    `scope_status_row` must be the raw native_short_scope_status_v1 row for
    this canonical scope key (or None if no such row exists), fetched only
    when scope registration resolves to exactly SCOPE_STATUS_SUPPORTED. This
    function performs no additional DB reads and recomputes no projection
    precedence/freshness logic -- it only maps the persisted projection row
    (or its absence) onto report fields.
    """
    scope_status, single_scope_row, scope_status_detail = resolve_scope_status(scope_rows)
    scope_support_state = str(single_scope_row["scope_support_state"]) if single_scope_row else None
    scope_reason_code = single_scope_row.get("scope_reason_code") if single_scope_row else None
    scope_reason_detail = single_scope_row.get("scope_reason_detail") if single_scope_row else None

    key = NativeShortMapScopeKey(
        venue=venue,
        symbol=symbol,
        quote_currency=quote_currency,
        fib_trading_horizon=fib_trading_horizon,
        primary_interval=primary_interval,
        supporting_interval=supporting_interval,
    )

    reasons: set[str] = set()
    if scope_status == SCOPE_STATUS_MISSING:
        reasons.add("SCOPE_MISSING")
    elif scope_status == SCOPE_STATUS_AMBIGUOUS:
        reasons.add("SCOPE_AMBIGUOUS")
    elif scope_status == SCOPE_STATUS_CONFLICTING:
        reasons.add("SCOPE_CONFLICTING")

    projection_fields: dict[str, Any] = {}
    projection_status = PROJECTION_STATUS_NOT_EVALUATED

    if scope_status == SCOPE_STATUS_SUPPORTED:
        if scope_status_row is None:
            projection_status = PROJECTION_STATUS_MISSING
            reasons.add(REASON_PROJECTION_ROW_MISSING)
        else:
            try:
                record = parse_scope_status_row(scope_status_row, key)
            except NativeShortScopeStatusValidationError as exc:
                projection_status = PROJECTION_STATUS_INVALID
                reasons.add(REASON_PROJECTION_ROW_INVALID)
                projection_fields["detail"] = str(exc)
            else:
                projection_status = PROJECTION_STATUS_FOUND
                projection_fields = {
                    "scope_status_code": str(record.scope_status_code),
                    "scope_status_reason_code": record.scope_status_reason_code,
                    "map_lifecycle_state": str(record.map_lifecycle_state),
                    "observation_freshness_state": str(record.observation_freshness_state),
                    "source_freshness_state": (
                        str(record.source_freshness_state) if record.source_freshness_state else None
                    ),
                    "actionability_state": str(record.actionability_state),
                    "current_map_id": record.current_map_id,
                    "current_map_cycle_id": record.current_map_cycle_id,
                    "current_map_published_at_utc": record.current_map_published_at_utc,
                    "current_map_structure_hash": record.current_map_structure_hash,
                    "latest_run_id": record.latest_run_id,
                    "latest_observation_id": record.latest_observation_id,
                    "latest_observed_at_utc": record.latest_observed_at_utc,
                    "next_expected_evaluation_at_utc": record.next_expected_evaluation_at_utc,
                    "observation_overdue_after_utc": record.observation_overdue_after_utc,
                    "primary_latest_candle_ts_utc": record.primary_latest_candle_ts_utc,
                    "supporting_latest_candle_ts_utc": record.supporting_latest_candle_ts_utc,
                    "primary_source_freshness_limit_seconds": record.primary_source_freshness_limit_seconds,
                    "supporting_source_freshness_limit_seconds": (
                        record.supporting_source_freshness_limit_seconds
                    ),
                    "cadence_contract_version": record.cadence_contract_version,
                    "projection_as_of_utc": record.projection_as_of_utc,
                    "projection_rebuilt_at_utc": record.rebuilt_at_utc,
                    "status_payload_json": record.status_payload_json,
                    "recompute_transition_state": (
                        str(record.recompute_transition_state)
                        if record.recompute_transition_state is not None
                        else None
                    ),
                }
                scope_status_code_value = str(record.scope_status_code)
                if scope_status_code_value != "CURRENT_EVALUATION":
                    reasons.add(f"SCOPE_STATUS_{scope_status_code_value}")

    if reasons:
        overall_health_status = OVERALL_HEALTH_NEEDS_REVIEW
    elif scope_status == SCOPE_STATUS_NOT_APPLICABLE:
        overall_health_status = OVERALL_HEALTH_NOT_APPLICABLE
    elif scope_status == SCOPE_STATUS_SUPPORTED and projection_status == PROJECTION_STATUS_FOUND:
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
        projection_status=projection_status,
        overall_health_status=overall_health_status,
        overall_health_reason_codes=sorted(reasons),
        **projection_fields,
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


def fetch_scope_status_row(
    conn: Any,
    key: NativeShortMapScopeKey,
) -> dict[str, Any] | None:
    """Single read-only SELECT of the canonical current row from
    native_short_scope_status_v1, keyed on the full canonical scope key. This
    is the sole market-data-adjacent read this report performs for
    freshness/lifecycle/status; it never joins native_short_map_v1,
    native_short_map_generation_event_v1, native_short_map_lifecycle_event_v1,
    or obs_market_candle."""
    sql = """
    SELECT
        scope_status_id, venue, symbol, quote_currency, fib_trading_horizon,
        primary_interval, supporting_interval,
        scope_support_state, scope_status_code, scope_status_reason_code,
        map_lifecycle_state, observation_freshness_state, source_freshness_state,
        actionability_state,
        current_map_id, current_map_cycle_id, current_map_published_at_utc,
        current_map_structure_hash,
        latest_generation_event_id, latest_lifecycle_event_id,
        latest_observation_id, latest_run_id, latest_observed_at_utc,
        next_expected_evaluation_at_utc, observation_overdue_after_utc,
        primary_latest_candle_ts_utc, supporting_latest_candle_ts_utc,
        primary_source_freshness_limit_seconds, supporting_source_freshness_limit_seconds,
        cadence_contract_version, projection_as_of_utc, status_payload_json, rebuilt_at_utc,
        recompute_transition_state
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
        rows = list(cur.fetchall())
    if not rows:
        return None
    return dict(rows[0])


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
    """Read-only orchestration: resolve scope registration, then (only for a
    SUPPORTED scope) read the one canonical native_short_scope_status_v1 row
    and build the deterministic health report. Never mutates state."""
    key = NativeShortMapScopeKey(
        venue=venue,
        symbol=symbol,
        quote_currency=quote_currency,
        fib_trading_horizon=fib_trading_horizon,
        primary_interval=primary_interval,
        supporting_interval=supporting_interval,
    )
    scope_rows = fetch_scope_rows(conn, key)
    scope_status, _, _ = resolve_scope_status(scope_rows)
    scope_status_row = fetch_scope_status_row(conn, key) if scope_status == SCOPE_STATUS_SUPPORTED else None
    return build_ledger_health_report(
        venue=venue,
        symbol=symbol,
        quote_currency=quote_currency,
        fib_trading_horizon=fib_trading_horizon,
        primary_interval=primary_interval,
        supporting_interval=supporting_interval,
        generated_at_utc=generated_at_utc,
        scope_rows=scope_rows,
        scope_status_row=scope_status_row,
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
