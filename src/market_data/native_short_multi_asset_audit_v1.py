from __future__ import annotations

"""Deterministic, market-only native SHORT expansion readiness audit."""

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Callable, Iterable, Mapping, Sequence

from src.market_data.native_short_fib_context_v1 import (
    STATUS_AVAILABLE,
    Candle,
    build_native_short_context_row,
)
from src.market_data.native_short_promotion_acceptance_evidence_v1 import (
    PROMOTION_ACCEPTANCE_CONTRACT_VERSION,
    evaluate_promotion_acceptance_evidence,
)
from src.market_data.native_short_bootstrap_no_current_map_evidence_v1 import (
    evaluate_bootstrap_no_current_map_evidence,
)
from src.market_data.native_short_runtime_isolation_evidence_v1 import (
    evaluate_multi_scope_failure_isolation_evidence,
)
from src.market_data.native_short_writer_provenance_v1 import (
    NativeShortWriterExecutionMode,
    NativeShortWriterProvenanceState,
    classify_persisted_native_short_writer_provenance,
)
from src.market_rules.price_tick_normalization_v1 import resolve_tick_rule_from_static
from src.market_rules.venue_execution_constraints_v1 import load_constraints_from_db


AUDIT_VERSION = "0.2"
VENUE = "bitvavo"
QUOTE_CURRENCY = "EUR"
FIB_TRADING_HORIZON = "SHORT"
PRIMARY_INTERVAL = "4h"
SUPPORTING_INTERVAL = "1h"
# The reviewed, operationally accepted attributable production run
# (docs/ops/native_short_writer_provenance_operational_acceptance_20260717.md,
# run_id=52, 2026-07-17T13:56:30Z). Not the legacy pre-contract run_id=30
# (b5d9ca6b-ff24-46eb-8155-4e663b948ebc, started 2026-07-15, predates the
# provenance-contract migration and is used elsewhere only as a
# LEGACY_UNATTRIBUTED classification fixture).
PROVENANCE_AUDIT_RUN_UUID = "b07d897d-6574-4380-98c3-8145c5c41b30"
PRIMARY_LOOKBACK = timedelta(days=60)
SUPPORTING_LOOKBACK = timedelta(days=21)
VOLUME_LOOKBACK = timedelta(days=30)

READY_EXISTING_CANARY = "READY_EXISTING_CANARY"
READY_FOR_SEQUENTIAL_CANARY_REVIEW = "READY_FOR_SEQUENTIAL_CANARY_REVIEW"
MARKET_INELIGIBLE = "MARKET_INELIGIBLE"
ASSET_DISABLED = "ASSET_DISABLED"
MARKET_DATA_DISABLED = "MARKET_DATA_DISABLED"
MARKET_NOT_TRADEABLE = "MARKET_NOT_TRADEABLE"
PRIMARY_CONTEXT_UNAVAILABLE = "PRIMARY_CONTEXT_UNAVAILABLE"
SUPPORTING_CONTEXT_UNAVAILABLE = "SUPPORTING_CONTEXT_UNAVAILABLE"
PRIMARY_SOURCE_STALE = "PRIMARY_SOURCE_STALE"
SUPPORTING_SOURCE_STALE = "SUPPORTING_SOURCE_STALE"
TICK_RULE_MISSING = "TICK_RULE_MISSING"
TICK_RULE_AMBIGUOUS = "TICK_RULE_AMBIGUOUS"
SCOPE_AMBIGUOUS = "SCOPE_AMBIGUOUS"
SCOPE_CONFLICT = "SCOPE_CONFLICT"
MAP_STATE_REQUIRES_REVIEW = "MAP_STATE_REQUIRES_REVIEW"
GENERATION_CHAIN_INVALID = "GENERATION_CHAIN_INVALID"
WRITER_PROVENANCE_UNATTRIBUTED = "WRITER_PROVENANCE_UNATTRIBUTED"
PROMOTION_CONTRACT_MISSING = "PROMOTION_CONTRACT_MISSING"
REMOVAL_CONTRACT_MISSING = "REMOVAL_CONTRACT_MISSING"
BOOTSTRAP_ORCHESTRATION_BLOCKED = "BOOTSTRAP_ORCHESTRATION_BLOCKED"
MULTI_SCOPE_FAILURE_ISOLATION_MISSING = "MULTI_SCOPE_FAILURE_ISOLATION_MISSING"

GLOBAL_BLOCKERS = (
    WRITER_PROVENANCE_UNATTRIBUTED,
    PROMOTION_CONTRACT_MISSING,
    REMOVAL_CONTRACT_MISSING,
    BOOTSTRAP_ORCHESTRATION_BLOCKED,
    MULTI_SCOPE_FAILURE_ISOLATION_MISSING,
)
"""Fail-closed default: assume every blocker remains active unless a caller
explicitly supplies an evaluated blocker tuple (see ``evaluate_global_blockers``).
"""

# Evidence-classification reason codes for the per-blocker diagnostic map.
# These explain *why* a blocker is active/closed without changing the
# existing ``global_blocker_codes`` / ``writer_provenance_blocker_active`` /
# ``operational_acceptance_completed`` field shapes.
BLOCKER_REASON_EVIDENCE_CONFIRMS_CLOSED = "EVIDENCE_CONFIRMS_CLOSED"
BLOCKER_REASON_EVIDENCE_ABSENT_OR_INVALID = "EVIDENCE_ABSENT_OR_INVALID"
BLOCKER_REASON_NO_CANONICAL_EVIDENCE_SOURCE = "NO_CANONICAL_EVIDENCE_SOURCE"
BLOCKER_REASON_IMPLEMENTATION_PENDING_SEPARATE_LANE = "IMPLEMENTATION_PENDING_SEPARATE_LANE"
# BOOTSTRAP_ORCHESTRATION_BLOCKED's separate implementation lane (the
# generalized bootstrap manifest and the rollout orchestrator) has landed, so
# "implementation pending" is no longer an accurate reason for it. What
# remains is one exact, named, unproven runtime property -- see
# docs/ops/native_short_bootstrap_orchestration_blocked_evidence_v1.md.
BLOCKER_REASON_EXACT_PROOF_REQUIRED = "EXACT_PROOF_REQUIRED"

# Canonical per-scope rollout outcome vocabulary (Issue #276). These are
# review/reporting labels describing a scope's current rollout disposition;
# they are never an authorization to act, and they never bypass the
# administration transaction's own gate.
ROLLOUT_STATUS_READY = "READY"
ROLLOUT_STATUS_ALREADY_SUPPORTED = "ALREADY_SUPPORTED"
ROLLOUT_STATUS_SKIPPED_NOT_READY = "SKIPPED_NOT_READY"
ROLLOUT_STATUS_BLOCKED = "BLOCKED"


def evaluate_global_blockers(
    *,
    provenance_attributed: bool,
    promotion_accepted: bool = False,
    promotion_evidence_reason: str | None = None,
    isolation_evidence_confirmed: bool = False,
    isolation_evidence_reason: str | None = None,
    bootstrap_evidence_confirmed: bool = False,
    bootstrap_evidence_reason: str | None = None,
) -> tuple[tuple[str, ...], Mapping[str, str]]:
    """Derive active global blockers from explicit evaluated evidence only.

    Fail-closed: any blocker lacking a canonical, machine-readable, explicitly
    owned evidence source stays active. Code/tests existing for a contract
    is never treated as acceptance, and narrative documentation is never
    treated as runtime acceptance state.

    ``promotion_accepted`` / ``promotion_evidence_reason`` come from
    ``native_short_promotion_acceptance_evidence_v1.evaluate_promotion_acceptance_evidence``.
    Leaving both at their defaults preserves prior behavior (no canonical
    evidence source wired) for callers that do not evaluate promotion
    evidence.

    ``isolation_evidence_confirmed`` / ``isolation_evidence_reason`` come from
    ``native_short_runtime_isolation_evidence_v1.evaluate_multi_scope_failure_isolation_evidence``
    (Issue #276). Same fail-closed shape: leaving both at their defaults keeps
    ``MULTI_SCOPE_FAILURE_ISOLATION_MISSING`` active exactly as before for any
    caller that does not evaluate isolation evidence.

    ``bootstrap_evidence_confirmed`` / ``bootstrap_evidence_reason`` come from
    ``native_short_bootstrap_no_current_map_evidence_v1.evaluate_bootstrap_no_current_map_evidence``
    (Issue #298). Same fail-closed shape: leaving both at their defaults keeps
    ``BOOTSTRAP_ORCHESTRATION_BLOCKED`` active exactly as before for any caller
    that does not evaluate bootstrap evidence.

    Returns ``(active_blocker_codes, reason_by_code)`` where
    ``reason_by_code`` covers all of ``GLOBAL_BLOCKERS`` (active or not).
    """
    reasons: dict[str, str] = {}
    active: list[str] = []

    # WRITER_PROVENANCE_UNATTRIBUTED: wired to the existing canonical
    # provenance evaluation (classify_persisted_native_short_writer_provenance
    # applied to the reviewed accepted run row). Absent/invalid/ambiguous
    # evidence fails closed.
    if provenance_attributed:
        reasons[WRITER_PROVENANCE_UNATTRIBUTED] = BLOCKER_REASON_EVIDENCE_CONFIRMS_CLOSED
    else:
        active.append(WRITER_PROVENANCE_UNATTRIBUTED)
        reasons[WRITER_PROVENANCE_UNATTRIBUTED] = BLOCKER_REASON_EVIDENCE_ABSENT_OR_INVALID

    # PROMOTION_CONTRACT_MISSING: now wired to the canonical, machine-readable
    # PROMOTE_SCOPE operational-acceptance evidence contract in
    # native_short_promotion_acceptance_evidence_v1.py (reusing the existing
    # native_short_scope_admin_operation_v1 ledger as the evidence store).
    # Absent, invalid, ambiguous, wrong-version, or wrong-scope evidence fails
    # closed. A caller that does not evaluate promotion evidence (the default)
    # preserves the pre-existing NO_CANONICAL_EVIDENCE_SOURCE reason exactly.
    if promotion_accepted:
        reasons[PROMOTION_CONTRACT_MISSING] = BLOCKER_REASON_EVIDENCE_CONFIRMS_CLOSED
    else:
        active.append(PROMOTION_CONTRACT_MISSING)
        reasons[PROMOTION_CONTRACT_MISSING] = (
            BLOCKER_REASON_NO_CANONICAL_EVIDENCE_SOURCE
            if promotion_evidence_reason is None
            else BLOCKER_REASON_EVIDENCE_ABSENT_OR_INVALID
        )

    # REMOVAL_CONTRACT_MISSING: the removal transaction is implemented and
    # unit-tested in native_short_scope_administration_transaction_v1.py, but
    # no canonical, explicitly owned, machine-readable production-operational-
    # acceptance evidence source exists for it yet. Implementation/tests are
    # not accepted as evidence, so this blocker remains unconditionally active
    # until such a source exists (out of scope for this lane; see AGENTS.md
    # task boundary).
    active.append(REMOVAL_CONTRACT_MISSING)
    reasons[REMOVAL_CONTRACT_MISSING] = BLOCKER_REASON_NO_CANONICAL_EVIDENCE_SOURCE

    # BOOTSTRAP_ORCHESTRATION_BLOCKED: now wired to the canonical,
    # machine-readable bootstrap-classification evidence contract in
    # native_short_bootstrap_no_current_map_evidence_v1.py (prerequisite #200
    # isolation-commit ancestry plus live structural inspection of the
    # bootstrap branch, the ledger predicate parameter, the per-scope
    # bootstrap_pending evidence field, and the BOOTSTRAP_PENDING runtime
    # status). The exact runtime property it previously waited on -- a newly
    # promoted scope's expected, transient NO_CURRENT_MAP state classifying as
    # BLOCKED and thereby halting unrelated later scopes -- was resolved in
    # #298 by splitting that state into its own explicit branch, without
    # weakening BLOCKED anywhere else. Absent, unavailable, or regressed
    # evidence fails closed, and a caller that does not evaluate bootstrap
    # evidence (the default) keeps the pre-existing EXACT_PROOF_REQUIRED
    # reason exactly. Full trace:
    # docs/ops/native_short_bootstrap_orchestration_blocked_evidence_v1.md
    if bootstrap_evidence_confirmed:
        reasons[BOOTSTRAP_ORCHESTRATION_BLOCKED] = BLOCKER_REASON_EVIDENCE_CONFIRMS_CLOSED
    else:
        active.append(BOOTSTRAP_ORCHESTRATION_BLOCKED)
        reasons[BOOTSTRAP_ORCHESTRATION_BLOCKED] = (
            BLOCKER_REASON_EXACT_PROOF_REQUIRED
            if bootstrap_evidence_reason is None
            else BLOCKER_REASON_EVIDENCE_ABSENT_OR_INVALID
        )

    # MULTI_SCOPE_FAILURE_ISOLATION_MISSING: now wired to the canonical,
    # machine-readable per-scope runtime isolation evidence contract in
    # native_short_runtime_isolation_evidence_v1.py (reviewed implementation
    # commit ancestry plus live runtime-contract structural inspection).
    # Absent, unavailable, or regressed evidence fails closed.
    if isolation_evidence_confirmed:
        reasons[MULTI_SCOPE_FAILURE_ISOLATION_MISSING] = BLOCKER_REASON_EVIDENCE_CONFIRMS_CLOSED
    else:
        active.append(MULTI_SCOPE_FAILURE_ISOLATION_MISSING)
        reasons[MULTI_SCOPE_FAILURE_ISOLATION_MISSING] = (
            BLOCKER_REASON_IMPLEMENTATION_PENDING_SEPARATE_LANE
            if isolation_evidence_reason is None
            else BLOCKER_REASON_EVIDENCE_ABSENT_OR_INVALID
        )

    ordered_active = tuple(code for code in GLOBAL_BLOCKERS if code in active)
    return ordered_active, reasons

Progress = Callable[[str, int, float], None]


@dataclass(frozen=True, order=True)
class CanonicalScopeKey:
    venue: str = VENUE
    symbol: str = ""
    quote_currency: str = QUOTE_CURRENCY
    fib_trading_horizon: str = FIB_TRADING_HORIZON
    primary_interval: str = PRIMARY_INTERVAL
    supporting_interval: str = SUPPORTING_INTERVAL

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.strip().upper())

    def as_tuple(self) -> tuple[str, str, str, str, str, str]:
        return (
            self.venue,
            self.symbol,
            self.quote_currency,
            self.fib_trading_horizon,
            self.primary_interval,
            self.supporting_interval,
        )


@dataclass(frozen=True)
class MarketMetadata:
    asset_id: int
    venue_market_id: int
    market: str
    asset_enabled: bool | None
    market_data_enabled: bool | None
    market_tradeable: bool | None
    db_price_precisions: tuple[int, ...] = ()


@dataclass(frozen=True)
class CandleWindow:
    count: int = 0
    latest_close_ts_utc: datetime | None = None
    latest_close_price: Decimal | None = None
    candles: tuple[Candle, ...] = ()


@dataclass(frozen=True)
class LedgerState:
    scope_states: tuple[str, ...] = ()
    map_ids: tuple[int, ...] = ()
    active_map_ids: tuple[int, ...] = ()
    generation_events: tuple[tuple[str, str, int | None], ...] = ()
    published_attempt_by_map: tuple[tuple[int, str], ...] = ()
    lifecycle_event_count: int = 0
    latest_lifecycle_by_map: tuple[tuple[int, str], ...] = ()
    current_status_map_ids: tuple[int, ...] = ()
    scope_status_codes: tuple[str, ...] = ()
    source_freshness_states: tuple[str, ...] = ()
    actionability_states: tuple[str, ...] = ()
    scope_key_conflict_count: int = 0
    map_key_conflict_count: int = 0


@dataclass(frozen=True)
class CandidateInput:
    symbol: str
    markets: tuple[MarketMetadata, ...]
    primary: CandleWindow = CandleWindow()
    supporting: CandleWindow = CandleWindow()
    trailing_30d_quote_volume: Decimal | None = None
    ledger: LedgerState = LedgerState()
    context_status: str | None = None
    # Decimal-place tick precision(s) derived from the canonical
    # venue_execution_constraint.tick_size (see _decimal_places_from_tick_size).
    # Populated by run_audit from src.market_rules.venue_execution_constraints_v1
    # -- the same table execution_planner/canonical_rounding_v1 already trust.
    # venue_market.price_precision alone is stale: Bitvavo's /v2/markets no
    # longer populates pricePrecision (see bitvavo_venue_adapter_v1 docstring),
    # so any market synced since then has NULL price_precision even though its
    # execution-constraint tick size is fresh.
    execution_constraint_decimal_places: tuple[int, ...] = ()


@dataclass(frozen=True)
class CandidateResult:
    canonical_key: CanonicalScopeKey
    readiness_status: str
    market_readiness_status: str
    market_reason_codes: tuple[str, ...]
    ledger_readiness_status: str
    ledger_reason_codes: tuple[str, ...]
    global_rollout_status: str
    global_blocker_codes: tuple[str, ...]
    production_promotable: bool
    sequential_review_rank: int | None
    market_eligible: bool
    context_available: bool
    primary_candle_count: int
    primary_latest_close_ts_utc: datetime | None
    primary_latest_close_price: Decimal | None
    supporting_candle_count: int
    supporting_latest_close_ts_utc: datetime | None
    supporting_latest_close_price: Decimal | None
    primary_source_freshness: str
    supporting_source_freshness: str
    tick_rule_state: str
    tick_decimal_places: int | None
    tick_rule_sources: tuple[str, ...]
    scope_row_count: int
    map_count: int
    active_map_count: int
    lifecycle_event_count: int
    latest_lifecycle_by_map: tuple[tuple[int, str], ...]
    generation_attempt_count: int
    generation_chain_valid: bool
    scope_states: tuple[str, ...]
    map_ids: tuple[int, ...]
    active_map_ids: tuple[int, ...]
    current_status_map_ids: tuple[int, ...]
    scope_status_codes: tuple[str, ...]
    source_freshness_states: tuple[str, ...]
    actionability_states: tuple[str, ...]
    materializer_validate_only_possible: bool
    trailing_30d_quote_volume: Decimal | None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["canonical_key"] = list(self.canonical_key.as_tuple())
        for field in (
            "primary_latest_close_ts_utc",
            "supporting_latest_close_ts_utc",
        ):
            item = value[field]
            value[field] = None if item is None else _as_utc(item).isoformat().replace("+00:00", "Z")
        for field in (
            "primary_latest_close_price",
            "supporting_latest_close_price",
            "trailing_30d_quote_volume",
        ):
            decimal_value = value[field]
            value[field] = None if decimal_value is None else format(decimal_value, "f")
        return value


@dataclass(frozen=True)
class AuditReport:
    as_of_utc: datetime
    results: tuple[CandidateResult, ...]
    proposed_sequential_queue: tuple[str, ...]
    counts: Mapping[str, int]
    writer_run_count: int
    attributable_writer_run_count: int
    legacy_unattributed_writer_run_count: int
    invalid_provenance_writer_run_count: int
    provenance_audit_run_found: bool
    provenance_audit_run_attributed: bool
    provenance_contract_implemented: bool
    attributable_production_run_observed: bool
    operational_acceptance_completed: bool
    writer_provenance_blocker_active: bool
    global_blocker_codes: tuple[str, ...]
    global_blocker_evidence: Mapping[str, str] = ()  # type: ignore[assignment]
    promotion_acceptance_contract_version: str = PROMOTION_ACCEPTANCE_CONTRACT_VERSION
    promotion_accepted_operation_uuid: str | None = None
    promotion_acceptance_accepted: bool = False
    promotion_acceptance_evaluation_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "audit_version": AUDIT_VERSION,
            "as_of_utc": _as_utc(self.as_of_utc).isoformat().replace("+00:00", "Z"),
            "canonical_contract": [
                VENUE,
                "<SYMBOL>",
                QUOTE_CURRENCY,
                FIB_TRADING_HORIZON,
                PRIMARY_INTERVAL,
                SUPPORTING_INTERVAL,
            ],
            "counts": dict(self.counts),
            "writer_run_count": self.writer_run_count,
            "attributable_writer_run_count": self.attributable_writer_run_count,
            "legacy_unattributed_writer_run_count": self.legacy_unattributed_writer_run_count,
            "invalid_provenance_writer_run_count": self.invalid_provenance_writer_run_count,
            "provenance_audit_run_uuid": PROVENANCE_AUDIT_RUN_UUID,
            "provenance_audit_run_found": self.provenance_audit_run_found,
            "provenance_audit_run_attributed": self.provenance_audit_run_attributed,
            "provenance_contract_implemented": self.provenance_contract_implemented,
            "attributable_production_run_observed": self.attributable_production_run_observed,
            "operational_acceptance_completed": self.operational_acceptance_completed,
            "writer_provenance_blocker_active": self.writer_provenance_blocker_active,
            "global_blocker_codes": list(self.global_blocker_codes),
            "global_blocker_evidence": dict(self.global_blocker_evidence),
            "promotion_acceptance_contract_version": self.promotion_acceptance_contract_version,
            "promotion_accepted_operation_uuid": self.promotion_accepted_operation_uuid,
            "promotion_acceptance_accepted": self.promotion_acceptance_accepted,
            "promotion_acceptance_evaluation_reason": self.promotion_acceptance_evaluation_reason,
            "safe_max_simultaneous_cohort_size": 1,
            "proposed_sequential_queue": list(self.proposed_sequential_queue),
            "results": [item.to_dict() for item in self.results],
        }


def summarize_writer_provenance(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[int, int, int, bool]:
    states = [classify_persisted_native_short_writer_provenance(row) for row in rows]
    attributable = sum(state == NativeShortWriterProvenanceState.ATTRIBUTABLE for state in states)
    legacy = sum(state == NativeShortWriterProvenanceState.LEGACY_UNATTRIBUTED for state in states)
    invalid = sum(state == NativeShortWriterProvenanceState.INVALID_PROVENANCE for state in states)
    production_observed = any(
        state == NativeShortWriterProvenanceState.ATTRIBUTABLE
        and str(row.get("execution_mode"))
        in {
            NativeShortWriterExecutionMode.CHAIN.value,
            NativeShortWriterExecutionMode.MANUAL.value,
        }
        for row, state in zip(rows, states, strict=True)
    )
    return attributable, legacy, invalid, production_observed


def expected_closed_candle(as_of_utc: datetime, interval_hours: int) -> datetime:
    value = _as_utc(as_of_utc)
    hour = value.hour - (value.hour % interval_hours)
    return value.replace(hour=hour, minute=0, second=0, microsecond=0)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _decimal_places_from_tick_size(tick_size: Decimal) -> int | None:
    """Convert a venue_execution_constraint tick_size to a decimal-place count,
    or ``None`` if it is not a clean power of ten. The existing tick-rule model
    (``price_tick_normalization_v1.TickRule``) represents every tick purely as
    a decimal-place count, so a non-power-of-ten tick_size cannot be expressed
    in it and must fail closed rather than be silently rounded."""
    if tick_size <= 0:
        return None
    normalized = tick_size.normalize()
    _sign, digits, exponent = normalized.as_tuple()
    if digits != (1,) or not isinstance(exponent, int):
        return None
    return -exponent if exponent < 0 else 0


def _tick_state(
    markets: Sequence[MarketMetadata],
    symbol: str,
    execution_constraint_decimal_places: Sequence[int] = (),
) -> tuple[str, int | None, tuple[str, ...]]:
    """Resolve tick precision with the same DB-first-then-static precedence
    ``price_tick_normalization_v1.resolve_tick_rule`` already uses, with
    ``venue_execution_constraint`` (the canonical, currently-synced source --
    see ``bitvavo_venue_adapter_v1``) standing in front of the older
    ``venue_market.price_precision`` column as the new authoritative "DB"
    step.

    This is deliberately a precedence chain, not a multi-source consensus
    vote: ``venue_market.price_precision`` is permanently NULL for any market
    synced since Bitvavo stopped returning ``pricePrecision``, and the static
    fallback table is documented stale (confirmed wrong for BTC-EUR). Voting
    a fresh, correct value against sources already known to be dead/stale
    would misclassify every currently-supported scope whose static entry has
    drifted as ``TICK_RULE_AMBIGUOUS`` -- a regression, not a fix. When the
    canonical source has an answer, it wins outright; the legacy sources are
    consulted, with their existing internal-conflict check, only when it does
    not.
    """
    constraint_values = sorted(set(execution_constraint_decimal_places))
    if constraint_values:
        sources = ("venue_execution_constraint.tick_size",)
        if len(constraint_values) != 1:
            return TICK_RULE_AMBIGUOUS, None, sources
        return "TICK_RULE_AVAILABLE", constraint_values[0], sources

    db_values = sorted({value for row in markets for value in row.db_price_precisions})
    static = resolve_tick_rule_from_static(VENUE, f"{symbol}-{QUOTE_CURRENCY}")
    static_value = None if static is None else static.decimal_places
    sources_list: list[str] = []
    if db_values:
        sources_list.append("venue_market.price_precision")
    if static_value is not None:
        sources_list.append("static_bitvavo_eur")
    values = set(db_values)
    if static_value is not None:
        values.add(static_value)
    if not values:
        return TICK_RULE_MISSING, None, tuple(sources_list)
    if len(values) != 1 or len(db_values) > 1:
        return TICK_RULE_AMBIGUOUS, None, tuple(sources_list)
    return "TICK_RULE_AVAILABLE", next(iter(values)), tuple(sources_list)


def generation_chain_is_valid(ledger: LedgerState) -> bool:
    if not ledger.generation_events:
        return not ledger.map_ids
    grouped: dict[str, list[tuple[str, int | None]]] = defaultdict(list)
    for attempt_id, event_type, map_id in ledger.generation_events:
        grouped[attempt_id].append((event_type, map_id))
    published_by_map = dict(ledger.published_attempt_by_map)
    allowed_events = {"ATTEMPT_STARTED", "PUBLISHED", "REJECTED", "SKIPPED", "FAILED"}
    for attempt_id, events in grouped.items():
        types = [event_type for event_type, _ in events]
        if any(event_type not in allowed_events for event_type in types):
            return False
        terminals = [event for event in events if event[0] in {"PUBLISHED", "REJECTED", "SKIPPED", "FAILED"}]
        if types.count("ATTEMPT_STARTED") != 1 or len(terminals) != 1:
            return False
        terminal_type, map_id = terminals[0]
        if terminal_type == "PUBLISHED":
            if map_id is None or published_by_map.get(map_id) != attempt_id:
                return False
        elif map_id is not None:
            return False
    return all(map_id in published_by_map for map_id in ledger.map_ids)


def evaluate_candidate(
    candidate: CandidateInput,
    *,
    as_of_utc: datetime,
    global_blockers: Sequence[str] = GLOBAL_BLOCKERS,
) -> CandidateResult:
    symbol = candidate.symbol.strip().upper()
    market_reasons: list[str] = []
    canonical_market = f"{symbol}-{QUOTE_CURRENCY}"
    if len(candidate.markets) != 1 or any(row.market.upper() != canonical_market for row in candidate.markets):
        market_reasons.append(MARKET_INELIGIBLE)
    if not candidate.markets or any(row.asset_enabled is not True for row in candidate.markets):
        market_reasons.append(ASSET_DISABLED)
    if not candidate.markets or any(row.market_data_enabled is not True for row in candidate.markets):
        market_reasons.append(MARKET_DATA_DISABLED)
    if not candidate.markets or any(row.market_tradeable is not True for row in candidate.markets):
        market_reasons.append(MARKET_NOT_TRADEABLE)

    expected_primary = expected_closed_candle(as_of_utc, 4)
    expected_supporting = expected_closed_candle(as_of_utc, 1)
    primary_current = (
        candidate.primary.latest_close_ts_utc is not None
        and _as_utc(candidate.primary.latest_close_ts_utc) == expected_primary
    )
    supporting_current = (
        candidate.supporting.latest_close_ts_utc is not None
        and _as_utc(candidate.supporting.latest_close_ts_utc) == expected_supporting
    )
    if candidate.primary.count < 24:
        market_reasons.append(PRIMARY_CONTEXT_UNAVAILABLE)
    if candidate.supporting.count < 48:
        market_reasons.append(SUPPORTING_CONTEXT_UNAVAILABLE)
    if candidate.primary.count >= 24 and not primary_current:
        market_reasons.append(PRIMARY_SOURCE_STALE)
    if candidate.supporting.count >= 48 and not supporting_current:
        market_reasons.append(SUPPORTING_SOURCE_STALE)

    context_available = candidate.context_status == STATUS_AVAILABLE
    if (
        candidate.context_status is None
        and not market_reasons
        and candidate.primary.candles
        and candidate.supporting.candles
    ):
        context = build_native_short_context_row(
            symbol=symbol,
            primary_candles=list(candidate.primary.candles),
            support_candles=list(candidate.supporting.candles),
            now_utc=_as_utc(as_of_utc),
            venue=VENUE,
        )
        context_available = context.context_status == STATUS_AVAILABLE
        if not context_available:
            market_reasons.append(PRIMARY_CONTEXT_UNAVAILABLE)

    tick_state, tick_places, tick_sources = _tick_state(
        candidate.markets, symbol, candidate.execution_constraint_decimal_places
    )
    if tick_state != "TICK_RULE_AVAILABLE":
        market_reasons.append(tick_state)

    ledger = candidate.ledger
    ledger_reasons: list[str] = []
    if ledger.scope_key_conflict_count:
        ledger_reasons.append(SCOPE_CONFLICT)
    elif len(ledger.scope_states) > 1:
        ledger_reasons.append(SCOPE_AMBIGUOUS)
    elif ledger.scope_states and ledger.scope_states[0] != "SUPPORTED":
        ledger_reasons.append(SCOPE_CONFLICT)
    # A single SUPPORTED scope row is a legitimate existing production scope
    # for any symbol (not just one hardcoded canary); the checks above already
    # reject conflicting keys, ambiguous multi-row state, and any non-SUPPORTED
    # single state, so no further symbol-specific check is needed here.

    has_existing_supported_scope = ledger.scope_states == ("SUPPORTED",)

    generation_valid = generation_chain_is_valid(ledger)
    if not generation_valid:
        ledger_reasons.append(GENERATION_CHAIN_INVALID)
    if ledger.map_key_conflict_count:
        ledger_reasons.append(MAP_STATE_REQUIRES_REVIEW)
    if has_existing_supported_scope:
        if (
            len(ledger.active_map_ids) != 1
            or len(ledger.current_status_map_ids) != 1
            or ledger.active_map_ids != ledger.current_status_map_ids
            or len(ledger.scope_status_codes) != 1
            or ledger.source_freshness_states != ("SOURCE_CURRENT",)
            or ledger.actionability_states != ("ACTIONABLE_ACTIVE_MAP",)
            or {map_id for map_id, _ in ledger.latest_lifecycle_by_map}
            != set(ledger.map_ids)
        ):
            ledger_reasons.append(MAP_STATE_REQUIRES_REVIEW)
    elif ledger.map_ids or ledger.active_map_ids or ledger.current_status_map_ids or ledger.scope_status_codes:
        ledger_reasons.append(MAP_STATE_REQUIRES_REVIEW)

    market_reasons = list(dict.fromkeys(market_reasons))
    ledger_reasons = list(dict.fromkeys(ledger_reasons))
    if not market_reasons and context_available:
        market_status = "MARKET_READY"
    else:
        market_status = market_reasons[0] if market_reasons else PRIMARY_CONTEXT_UNAVAILABLE
    ledger_status = "LEDGER_READY" if not ledger_reasons else ledger_reasons[0]
    if market_status == "MARKET_READY" and ledger_status == "LEDGER_READY":
        readiness_status = (
            READY_EXISTING_CANARY
            if has_existing_supported_scope
            else READY_FOR_SEQUENTIAL_CANARY_REVIEW
        )
    else:
        readiness_status = market_status if market_status != "MARKET_READY" else ledger_status

    blocker_tuple = tuple(dict.fromkeys(global_blockers))
    return CandidateResult(
        canonical_key=CanonicalScopeKey(symbol=symbol),
        readiness_status=readiness_status,
        market_readiness_status=market_status,
        market_reason_codes=tuple(market_reasons),
        ledger_readiness_status=ledger_status,
        ledger_reason_codes=tuple(ledger_reasons),
        global_rollout_status="GLOBAL_ROLLOUT_BLOCKED" if blocker_tuple else "GLOBAL_ROLLOUT_READY",
        global_blocker_codes=blocker_tuple,
        production_promotable=(
            readiness_status
            in {READY_EXISTING_CANARY, READY_FOR_SEQUENTIAL_CANARY_REVIEW}
            and not blocker_tuple
        ),
        sequential_review_rank=None,
        market_eligible=not any(
            code in market_reasons
            for code in (
                MARKET_INELIGIBLE,
                ASSET_DISABLED,
                MARKET_DATA_DISABLED,
                MARKET_NOT_TRADEABLE,
            )
        ),
        context_available=context_available,
        primary_candle_count=candidate.primary.count,
        primary_latest_close_ts_utc=candidate.primary.latest_close_ts_utc,
        primary_latest_close_price=candidate.primary.latest_close_price,
        supporting_candle_count=candidate.supporting.count,
        supporting_latest_close_ts_utc=candidate.supporting.latest_close_ts_utc,
        supporting_latest_close_price=candidate.supporting.latest_close_price,
        primary_source_freshness="CURRENT" if primary_current else "STALE_OR_UNAVAILABLE",
        supporting_source_freshness="CURRENT" if supporting_current else "STALE_OR_UNAVAILABLE",
        tick_rule_state=tick_state,
        tick_decimal_places=tick_places,
        tick_rule_sources=tick_sources,
        scope_row_count=len(ledger.scope_states),
        map_count=len(ledger.map_ids),
        active_map_count=len(ledger.active_map_ids),
        lifecycle_event_count=ledger.lifecycle_event_count,
        latest_lifecycle_by_map=ledger.latest_lifecycle_by_map,
        generation_attempt_count=len({row[0] for row in ledger.generation_events}),
        generation_chain_valid=generation_valid,
        scope_states=ledger.scope_states,
        map_ids=ledger.map_ids,
        active_map_ids=ledger.active_map_ids,
        current_status_map_ids=ledger.current_status_map_ids,
        scope_status_codes=ledger.scope_status_codes,
        source_freshness_states=ledger.source_freshness_states,
        actionability_states=ledger.actionability_states,
        materializer_validate_only_possible=(
            has_existing_supported_scope
            and market_status == "MARKET_READY"
            and ledger_status == "LEDGER_READY"
        ),
        trailing_30d_quote_volume=(
            candidate.trailing_30d_quote_volume
            if readiness_status in {READY_EXISTING_CANARY, READY_FOR_SEQUENTIAL_CANARY_REVIEW}
            else None
        ),
    )


def rank_sequential_candidates(results: Iterable[CandidateResult]) -> tuple[CandidateResult, ...]:
    ordered = sorted(results, key=lambda item: item.canonical_key.symbol)
    qualified = sorted(
        (item for item in ordered if item.readiness_status == READY_FOR_SEQUENTIAL_CANARY_REVIEW),
        key=lambda item: (
            -(item.trailing_30d_quote_volume or Decimal("0")),
            item.canonical_key.symbol,
        ),
    )
    ranks = {item.canonical_key.symbol: index for index, item in enumerate(qualified, start=1)}
    return tuple(replace(item, sequential_review_rank=ranks.get(item.canonical_key.symbol)) for item in ordered)


def classify_rollout_status(result: CandidateResult) -> str:
    """Map one already-evaluated candidate onto the canonical per-scope
    rollout vocabulary (Issue #276). Pure function of ``result``; no I/O.

    This is a *reporting* classification derived from the existing market-only
    readiness evaluation. It grants nothing: the administration transaction's
    own unchanged gate remains the only thing that decides whether a
    PROMOTE_SCOPE may execute.

    Precedence is deliberate and fail-closed:

    1. ``ALREADY_SUPPORTED`` -- the scope already has exactly one SUPPORTED
       scope row. This is a fact about existing state, so it wins outright:
       promotion blockers are irrelevant to a scope that needs no promotion.
    2. ``BLOCKED`` -- an active global blocker applies. This deliberately
       outranks per-scope readiness for anything not already supported,
       because no promotion primitive can execute at all while a blocker is
       active. Reporting ``READY`` for a scope the gate would refuse is the
       dangerous direction; reporting ``BLOCKED`` for a scope that is also
       market-ineligible is the safe one. The candidate's own
       ``market_reason_codes`` / ``ledger_reason_codes`` retain the full
       per-scope detail either way.
    3. ``READY`` -- market and ledger criteria are satisfied and no global
       blocker stands in the way.
    4. ``SKIPPED_NOT_READY`` -- everything else: market or ledger
       ineligibility.
    """
    if result.scope_states == ("SUPPORTED",) or result.readiness_status == READY_EXISTING_CANARY:
        return ROLLOUT_STATUS_ALREADY_SUPPORTED
    if result.global_rollout_status == "GLOBAL_ROLLOUT_BLOCKED":
        return ROLLOUT_STATUS_BLOCKED
    if result.readiness_status == READY_FOR_SEQUENTIAL_CANARY_REVIEW:
        return ROLLOUT_STATUS_READY
    return ROLLOUT_STATUS_SKIPPED_NOT_READY


def bucket_by_rollout_status(
    results: Iterable[CandidateResult],
) -> Mapping[str, tuple[str, ...]]:
    """Group candidate symbols by ``classify_rollout_status``, deterministically
    ordered. Reporting convenience only -- it re-derives nothing and adds no
    criteria of its own."""
    buckets: dict[str, list[str]] = {
        ROLLOUT_STATUS_READY: [],
        ROLLOUT_STATUS_ALREADY_SUPPORTED: [],
        ROLLOUT_STATUS_SKIPPED_NOT_READY: [],
        ROLLOUT_STATUS_BLOCKED: [],
    }
    for item in results:
        buckets[classify_rollout_status(item)].append(item.canonical_key.symbol)
    return {status: tuple(sorted(symbols)) for status, symbols in buckets.items()}


def _fetch_all(conn: Any, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        return [dict(row) for row in cur.fetchall()]


_WRITER_PROVENANCE_ROWS_SQL = """
    SELECT run_uuid, runner_name, runner_version, trigger_type, trigger_ref,
           host_name, process_id, provenance_contract_version,
           writer_entrypoint, repository_writer_owner, execution_mode,
           repository_commit_sha
    FROM native_short_materializer_run_v1
    ORDER BY run_id
"""

_PROMOTE_OPERATION_ROWS_SQL = """
    SELECT operation_uuid, operation_type, venue, symbol, quote_currency,
           fib_trading_horizon, primary_interval, supporting_interval,
           schema_version, metadata_digest, completed_at_utc,
           result_class, result_code
    FROM native_short_scope_admin_operation_v1
    WHERE operation_type = 'PROMOTE_SCOPE'
    ORDER BY scope_admin_operation_id
"""


def fetch_writer_provenance_rows(conn: Any) -> list[dict[str, Any]]:
    """Read-only fetch of every persisted native SHORT writer run row."""
    return _fetch_all(conn, _WRITER_PROVENANCE_ROWS_SQL)


def fetch_promote_operation_rows(conn: Any) -> list[dict[str, Any]]:
    """Read-only fetch of every persisted PROMOTE_SCOPE operation-ledger row."""
    return _fetch_all(conn, _PROMOTE_OPERATION_ROWS_SQL)


def evaluate_global_blockers_from_rows(
    writer_rows: Sequence[Mapping[str, Any]],
    admin_operation_rows: Sequence[Mapping[str, Any]],
) -> tuple[tuple[str, ...], Mapping[str, str]]:
    """Pure evaluation of the canonical global blockers from already-fetched
    writer-provenance and PROMOTE_SCOPE operation-ledger rows. This is the
    single non-duplicated blocker-evaluation path shared by ``run_audit`` and
    ``evaluate_current_global_blockers``; no caller should re-derive
    ``provenance_attributed`` or ``promotion_accepted`` independently.
    """
    provenance_rows = [
        row for row in writer_rows if str(row["run_uuid"]) == PROVENANCE_AUDIT_RUN_UUID
    ]
    provenance_attributed = bool(provenance_rows) and all(
        classify_persisted_native_short_writer_provenance(row)
        == NativeShortWriterProvenanceState.ATTRIBUTABLE
        for row in provenance_rows
    )
    promotion_evaluation = evaluate_promotion_acceptance_evidence(admin_operation_rows)
    # Repository/import-only evidence: needs no rows and no connection, so it
    # is evaluated here rather than threaded through every caller's fetch.
    isolation_evaluation = evaluate_multi_scope_failure_isolation_evidence()
    bootstrap_evaluation = evaluate_bootstrap_no_current_map_evidence()
    return evaluate_global_blockers(
        provenance_attributed=provenance_attributed,
        promotion_accepted=promotion_evaluation.accepted,
        promotion_evidence_reason=promotion_evaluation.reason,
        isolation_evidence_confirmed=isolation_evaluation.confirmed,
        isolation_evidence_reason=isolation_evaluation.reason,
        bootstrap_evidence_confirmed=bootstrap_evaluation.confirmed,
        bootstrap_evidence_reason=bootstrap_evaluation.reason,
    )


def evaluate_current_global_blockers(conn: Any) -> tuple[tuple[str, ...], Mapping[str, str]]:
    """Read minimal current evidence from ``conn`` and evaluate the canonical
    global blockers. This is the single reusable, read-only entrypoint for any
    caller (audit reporting, scope-administration transaction enforcement)
    that needs the current blocker state; it must never be duplicated with a
    second blocker-evaluation implementation. Performs no mutation.
    """
    writer_rows = fetch_writer_provenance_rows(conn)
    admin_operation_rows = fetch_promote_operation_rows(conn)
    return evaluate_global_blockers_from_rows(writer_rows, admin_operation_rows)


def _phase(progress: Progress | None, name: str, rows: int, started: datetime) -> None:
    if progress:
        progress(name, rows, (datetime.now(UTC) - started).total_seconds())


def run_audit(
    conn: Any,
    *,
    as_of_utc: datetime,
    progress: Progress | None = None,
    symbols: Sequence[str] | None = None,
) -> AuditReport:
    """Run the full canonical readiness audit, or -- when ``symbols`` is
    given -- the identical evaluation narrowed to exactly those canonical
    base symbols. ``symbols=None`` (the default) is byte-for-byte the
    original full-universe behavior; every existing caller is unaffected.

    The narrowed form exists for cheap, fresh, single-scope (or small-batch)
    revalidation immediately before a ``PROMOTE_SCOPE`` transaction -- see
    ``native_short_scope_administration_rollout_v1``'s ``revalidate`` hook --
    without duplicating this function's evaluation logic or query shape.
    """
    as_of = _as_utc(as_of_utc)
    started = datetime.now(UTC)
    symbol_filter = (
        None if symbols is None else tuple(dict.fromkeys(s.strip().upper() for s in symbols))
    )
    if symbol_filter is not None and not symbol_filter:
        raise RuntimeError("CANONICAL_MARKET_UNIVERSE_EMPTY")
    symbol_clause = ""
    symbol_params: tuple[Any, ...] = ()
    if symbol_filter is not None:
        symbol_clause = f" AND a.symbol IN ({','.join(['%s'] * len(symbol_filter))})"
        symbol_params = symbol_filter
    market_rows = _fetch_all(
        conn,
        f"""
        SELECT vm.venue_market_id, vm.base_asset_id AS asset_id, vm.market,
               vm.is_tradeable, vm.is_market_data_enabled, vm.price_precision,
               a.symbol, a.is_enabled
        FROM venue_market vm
        JOIN asset a ON a.asset_id = vm.base_asset_id
        WHERE vm.venue = %s AND vm.quote_currency = %s{symbol_clause}
        ORDER BY a.symbol, vm.market, vm.venue_market_id
        """,
        (VENUE, QUOTE_CURRENCY, *symbol_params),
    )
    _phase(progress, "market_metadata", len(market_rows), started)
    asset_ids = sorted({int(row["asset_id"]) for row in market_rows})
    if not asset_ids:
        raise RuntimeError("CANONICAL_MARKET_UNIVERSE_EMPTY")
    placeholders = ",".join(["%s"] * len(asset_ids))

    # venue_execution_constraint is the canonical, currently-synced source of
    # tick precision (venue_market.price_precision alone is stale: Bitvavo's
    # /v2/markets stopped populating pricePrecision -- see
    # bitvavo_venue_adapter_v1 docstring). Reused read-only via the existing
    # loader; no new table, no new tick model.
    constraint_markets = sorted({str(row["market"]) for row in market_rows})
    execution_constraints = load_constraints_from_db(conn, venue=VENUE, markets=constraint_markets)
    constraint_decimal_places_by_symbol: dict[str, list[int]] = defaultdict(list)
    for market_name, constraint in execution_constraints.items():
        symbol = market_name[: -len(f"-{QUOTE_CURRENCY}")] if market_name.endswith(f"-{QUOTE_CURRENCY}") else None
        if symbol is None:
            continue
        dp = _decimal_places_from_tick_size(constraint.tick_size)
        if dp is not None:
            constraint_decimal_places_by_symbol[symbol].append(dp)
    _phase(progress, "venue_execution_constraint", len(execution_constraints), started)

    candle_started = datetime.now(UTC)
    candle_stats_rows = _fetch_all(
        conn,
        f"""
        SELECT asset_id, interval_code, COUNT(*) AS candle_count,
               MAX(close_ts_utc) AS latest_close_ts_utc
        FROM obs_market_candle
        WHERE venue = %s AND asset_id IN ({placeholders})
          AND interval_code IN (%s, %s) AND close_ts_utc <= %s
        GROUP BY asset_id, interval_code
        ORDER BY asset_id, interval_code
        """,
        (VENUE, *asset_ids, PRIMARY_INTERVAL, SUPPORTING_INTERVAL, as_of),
    )
    candle_rows = _fetch_all(
        conn,
        f"""
        SELECT asset_id, interval_code, close_ts_utc, open_price, high_price,
               low_price, close_price, volume_quote_eur
        FROM obs_market_candle
        WHERE venue = %s AND asset_id IN ({placeholders})
          AND (
              (interval_code = %s AND close_ts_utc >= %s)
              OR (interval_code = %s AND close_ts_utc >= %s)
          )
          AND close_ts_utc <= %s
        ORDER BY asset_id, interval_code, close_ts_utc
        """,
        (
            VENUE,
            *asset_ids,
            PRIMARY_INTERVAL,
            as_of - PRIMARY_LOOKBACK,
            SUPPORTING_INTERVAL,
            as_of - SUPPORTING_LOOKBACK,
            as_of,
        ),
    )
    _phase(progress, "candles", len(candle_rows) + len(candle_stats_rows), candle_started)

    scope_rows = _fetch_all(
        conn,
        """
        SELECT venue, symbol, quote_currency, fib_trading_horizon,
               primary_interval, supporting_interval, scope_support_state
        FROM native_short_map_scope_v1
        ORDER BY symbol, scope_id
        """,
    )
    map_rows = _fetch_all(
        conn,
        """
        SELECT map_id, venue, symbol, quote_currency, fib_trading_horizon,
               primary_interval, supporting_interval,
               published_generation_attempt_id
        FROM native_short_map_v1
        ORDER BY symbol, map_id
        """,
    )
    generation_rows = _fetch_all(
        conn,
        """
        SELECT generation_attempt_id, event_type, map_id, venue, symbol,
               quote_currency, fib_trading_horizon, primary_interval,
               supporting_interval
        FROM native_short_map_generation_event_v1
        ORDER BY symbol, generation_event_id
        """,
    )
    lifecycle_rows = _fetch_all(
        conn,
        """
        SELECT e.map_id, e.lifecycle_event_type, m.venue, m.symbol,
               m.quote_currency, m.fib_trading_horizon, m.primary_interval,
               m.supporting_interval
        FROM native_short_map_lifecycle_event_v1 e
        JOIN native_short_map_v1 m ON m.map_id = e.map_id
        ORDER BY m.symbol, e.lifecycle_event_id
        """,
    )
    status_rows = _fetch_all(
        conn,
        """
        SELECT venue, symbol, quote_currency, fib_trading_horizon,
               primary_interval, supporting_interval, current_map_id,
               scope_status_code, source_freshness_state, actionability_state
        FROM native_short_scope_status_v1
        ORDER BY symbol, scope_status_id
        """,
    )
    writer_rows = fetch_writer_provenance_rows(conn)
    admin_operation_rows = fetch_promote_operation_rows(conn)
    ledger_row_count = sum(
        map(
            len,
            (
                scope_rows,
                map_rows,
                generation_rows,
                lifecycle_rows,
                status_rows,
                writer_rows,
                admin_operation_rows,
            ),
        )
    )
    _phase(progress, "native_short_ledger", ledger_row_count, started)

    def exact(row: Mapping[str, Any]) -> bool:
        return (
            str(row["venue"]).lower() == VENUE
            and str(row["quote_currency"]).upper() == QUOTE_CURRENCY
            and str(row["fib_trading_horizon"]).upper() == FIB_TRADING_HORIZON
            and str(row["primary_interval"]) == PRIMARY_INTERVAL
            and str(row["supporting_interval"]) == SUPPORTING_INTERVAL
        )

    markets_by_symbol: dict[str, list[MarketMetadata]] = defaultdict(list)
    symbols_by_asset: dict[int, str] = {}
    for row in market_rows:
        symbol = str(row["symbol"]).upper()
        symbols_by_asset[int(row["asset_id"])] = symbol
        precision = () if row["price_precision"] is None else (int(row["price_precision"]),)
        markets_by_symbol[symbol].append(MarketMetadata(
            asset_id=int(row["asset_id"]), venue_market_id=int(row["venue_market_id"]),
            market=str(row["market"]), asset_enabled=row["is_enabled"] == 1,
            market_data_enabled=row["is_market_data_enabled"] == 1,
            market_tradeable=row["is_tradeable"] == 1, db_price_precisions=precision,
        ))

    candles: dict[tuple[str, str], list[Candle]] = defaultdict(list)
    candle_stats: dict[tuple[str, str], tuple[int, datetime | None]] = {}
    volumes: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for row in candle_stats_rows:
        symbol = symbols_by_asset[int(row["asset_id"])]
        latest = row["latest_close_ts_utc"]
        candle_stats[(symbol, str(row["interval_code"]))] = (
            int(row["candle_count"]),
            None if latest is None else _as_utc(latest),
        )
    for row in candle_rows:
        symbol = symbols_by_asset[int(row["asset_id"])]
        close_ts = _as_utc(row["close_ts_utc"])
        interval = str(row["interval_code"])
        candles[(symbol, interval)].append(Candle(
            close_ts_utc=close_ts, open_price=Decimal(str(row["open_price"])),
            high_price=Decimal(str(row["high_price"])), low_price=Decimal(str(row["low_price"])),
            close_price=Decimal(str(row["close_price"])),
        ))
        if interval == PRIMARY_INTERVAL and close_ts > as_of - VOLUME_LOOKBACK:
            volumes[symbol] += Decimal(str(row["volume_quote_eur"] or 0))

    def keyed(rows: Sequence[Mapping[str, Any]], symbol: str) -> list[Mapping[str, Any]]:
        return [row for row in rows if str(row["symbol"]).upper() == symbol and exact(row)]

    attributable, legacy_unattributed, invalid_provenance, production_observed = (
        summarize_writer_provenance(writer_rows)
    )
    provenance_rows = [row for row in writer_rows if str(row["run_uuid"]) == PROVENANCE_AUDIT_RUN_UUID]
    provenance_attributed = bool(provenance_rows) and all(
        classify_persisted_native_short_writer_provenance(row)
        == NativeShortWriterProvenanceState.ATTRIBUTABLE
        for row in provenance_rows
    )
    active_blockers, blocker_evidence = evaluate_global_blockers_from_rows(
        writer_rows, admin_operation_rows
    )
    # Recomputed for the report's promotion-specific fields; the underlying
    # evaluator is pure and was already invoked once inside
    # evaluate_global_blockers_from_rows above, so this is not a second
    # blocker-logic implementation, only a second read of its cheap result.
    promotion_evaluation = evaluate_promotion_acceptance_evidence(admin_operation_rows)

    evaluated: list[CandidateResult] = []
    for symbol in sorted(markets_by_symbol):
        primary = tuple(candles[(symbol, PRIMARY_INTERVAL)])
        supporting = tuple(candles[(symbol, SUPPORTING_INTERVAL)])
        primary_count, primary_latest = candle_stats.get((symbol, PRIMARY_INTERVAL), (0, None))
        supporting_count, supporting_latest = candle_stats.get((symbol, SUPPORTING_INTERVAL), (0, None))
        smaps = keyed(map_rows, symbol)
        slifecycle = keyed(lifecycle_rows, symbol)
        latest_by_map: dict[int, str] = {}
        for row in slifecycle:
            latest_by_map[int(row["map_id"])] = str(row["lifecycle_event_type"])
        active = tuple(sorted(map_id for map_id, event in latest_by_map.items() if event == "ACTIVATED"))
        sgeneration = keyed(generation_rows, symbol)
        sstatus = keyed(status_rows, symbol)
        ledger = LedgerState(
            scope_states=tuple(str(row["scope_support_state"]) for row in keyed(scope_rows, symbol)),
            map_ids=tuple(int(row["map_id"]) for row in smaps), active_map_ids=active,
            generation_events=tuple(
                (
                    str(row["generation_attempt_id"]),
                    str(row["event_type"]),
                    None if row["map_id"] is None else int(row["map_id"]),
                )
                for row in sgeneration
            ),
            published_attempt_by_map=tuple(
                (int(row["map_id"]), str(row["published_generation_attempt_id"]))
                for row in smaps
            ),
            lifecycle_event_count=len(slifecycle),
            latest_lifecycle_by_map=tuple(sorted(latest_by_map.items())),
            current_status_map_ids=tuple(
                int(row["current_map_id"])
                for row in sstatus
                if row["current_map_id"] is not None
            ),
            scope_status_codes=tuple(str(row["scope_status_code"]) for row in sstatus),
            source_freshness_states=tuple(str(row["source_freshness_state"]) for row in sstatus),
            actionability_states=tuple(str(row["actionability_state"]) for row in sstatus),
            scope_key_conflict_count=sum(
                str(row["symbol"]).upper() == symbol and not exact(row)
                for row in scope_rows
            ),
            map_key_conflict_count=sum(
                str(row["symbol"]).upper() == symbol and not exact(row)
                for row in map_rows
            ),
        )
        evaluated.append(evaluate_candidate(CandidateInput(
            symbol=symbol, markets=tuple(markets_by_symbol[symbol]),
            primary=CandleWindow(
                primary_count,
                primary_latest,
                primary[-1].close_price if primary else None,
                primary,
            ),
            supporting=CandleWindow(
                supporting_count,
                supporting_latest,
                supporting[-1].close_price if supporting else None,
                supporting,
            ),
            trailing_30d_quote_volume=volumes.get(symbol), ledger=ledger,
            execution_constraint_decimal_places=tuple(constraint_decimal_places_by_symbol.get(symbol, ())),
        ), as_of_utc=as_of, global_blockers=active_blockers))

    ranked = rank_sequential_candidates(evaluated)
    sequential = sorted(
        (row for row in ranked if row.sequential_review_rank is not None),
        key=lambda row: row.sequential_review_rank or 0,
    )
    queue = tuple(item.canonical_key.symbol for item in sequential[:3])
    status_counts = Counter(item.readiness_status for item in ranked)
    counts = {
        "market_row_count": len(market_rows),
        "candidate_count": len(ranked),
        "market_eligible_count": sum(item.market_eligible for item in ranked),
        "readiness_qualified_count": sum(
            item.readiness_status
            in {READY_EXISTING_CANARY, READY_FOR_SEQUENTIAL_CANARY_REVIEW}
            for item in ranked
        ),
        "existing_canary_count": status_counts[READY_EXISTING_CANARY],
        "sequential_review_candidate_count": status_counts[READY_FOR_SEQUENTIAL_CANARY_REVIEW],
        "excluded_count": (
            len(ranked)
            - status_counts[READY_EXISTING_CANARY]
            - status_counts[READY_FOR_SEQUENTIAL_CANARY_REVIEW]
        ),
        "tick_rule_missing_count": sum(item.tick_rule_state == TICK_RULE_MISSING for item in ranked),
        "eligible_tick_rule_missing_count": sum(
            item.market_eligible and item.tick_rule_state == TICK_RULE_MISSING
            for item in ranked
        ),
        "tick_rule_ambiguous_count": sum(item.tick_rule_state == TICK_RULE_AMBIGUOUS for item in ranked),
    }
    _phase(progress, "evaluation", len(ranked), started)
    return AuditReport(
        as_of,
        ranked,
        queue,
        counts,
        len(writer_rows),
        attributable,
        legacy_unattributed,
        invalid_provenance,
        bool(provenance_rows),
        provenance_attributed,
        True,
        production_observed,
        not active_blockers,
        WRITER_PROVENANCE_UNATTRIBUTED in active_blockers,
        active_blockers,
        blocker_evidence,
        PROMOTION_ACCEPTANCE_CONTRACT_VERSION,
        promotion_evaluation.operation_uuid,
        promotion_evaluation.accepted,
        promotion_evaluation.reason,
    )
