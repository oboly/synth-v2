from __future__ import annotations

import dataclasses
import html as _html
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Mapping

from src.reporting.dashboard_style_v1 import synth_favicon_head_html
from src.reporting.dashboard_time_v1 import format_ui_now
from src.reporting.current_price_snapshot_v1 import DEFAULT_CURRENT_PRICE_FRESH_AFTER
from src.reporting.market_rotation_profit_plan_projection_v1 import (
    RotationProfitPlanProjection,
    get_market_projection,
    market_projection_to_json_dict,
    to_json_dict as rotation_projection_to_json_dict,
    unavailable_projection as unavailable_rotation_projection,
)


REPORT_NAME = "manual_short_trader_profit_plan_v1"
REPORT_VERSION = "0.1"
DATA_UNAVAILABLE = "DATA_UNAVAILABLE"

# Breathline / Breath Curve is research context only until separately validated and
# promoted. It contributes zero selection/action/decision weight and must never affect
# primary action, sorting, PPP, urgency, setup state or ladder state.
BREATHLINE_DISPLAY_STATE = "RESEARCH_ONLY_DISABLED"
BREATHLINE_DISABLED_SHORT = "Research context only — disabled"
BREATHLINE_DISABLED_NOTE = "Breathline: research context only — disabled for actions"
BREATHLINE_SELECTION_WEIGHT = 0
BREATHLINE_ACTION_WEIGHT = 0
BREATHLINE_DECISION_WEIGHT = 0

ORDER_MATCH_TOLERANCE_PCT = Decimal("3")
TAKE_PROFIT_WAITING_THRESHOLD_PCT = Decimal("3")
RELOAD_ZONE_APPROACHING_THRESHOLD_PCT = Decimal("3")
INVALIDATION_NEAR_THRESHOLD_PCT = Decimal("3")
PRICE_RAN_AWAY_THRESHOLD_PCT = Decimal("12")
ORDER_STALE_DISTANCE_PCT = Decimal("12")
TARGET_LEVEL_NEAR_THRESHOLD_PCT = Decimal("1")

# Keep order authority on the same 15-minute reporting freshness window as the
# current-price snapshot. A small future allowance tolerates bounded clock skew
# without accepting a snapshot that cannot be authoritative for this render.
ORDER_SNAPSHOT_FRESH_AFTER = DEFAULT_CURRENT_PRICE_FRESH_AFTER
ORDER_SNAPSHOT_MAX_FUTURE_SKEW = timedelta(seconds=30)

# Canonical 4h market-only context (Issue #210). A card reaches this class only
# when native-short lifecycle truth is unavailable AND the short-context
# coverage bridge reports a canonical_fib_zone_map_latest_v1 row was used
# (short_context_coverage_status == CANONICAL_4H_CONTEXT_AVAILABLE, defined in
# src/reporting/run_manual_short_trader_profit_plan_v1.py). This class is
# explicitly read-only navigation reference and must never be confused with
# a native-short lifecycle-verified scenario/state/action.
SHORT_CONTEXT_COVERAGE_CANONICAL_4H_AVAILABLE = "CANONICAL_4H_CONTEXT_AVAILABLE"
SCENARIO_CANONICAL_MARKET_CONTEXT = "CANONICAL_MARKET_CONTEXT"
PRIMARY_STATE_CANONICAL_NAVIGATION_ONLY = "CANONICAL_NAVIGATION_ONLY"
ACTION_LABEL_CANONICAL_NAVIGATION_ONLY = "CANONICAL_NAVIGATION_ONLY"

# Issue #223: canonical 4h navigation context is a distinct short_context_display_state
# from both native fib context and the generic transient/non-canonical bridge state --
# it must render its own truthful map-context/quality wording, never "No fib context"
# or the transient/non-canonical bridge label.
SHORT_CONTEXT_DISPLAY_CANONICAL_NAVIGATION_AVAILABLE = "CANONICAL_NAVIGATION_CONTEXT_AVAILABLE"
CANONICAL_MAP_CONTEXT_LABEL = (
    "Canonical 4h market reference — navigation only, not lifecycle-verified"
)

# state_model_discipline_v1.md: source_health (STALE_PRIMARY_4H / STALE_SUPPORT_1H)
# is a temporary data-health condition, orthogonal to scope/lifecycle state. A
# SUPPORTED scope with a stale canonical source stays visible and degraded/blocked,
# labeled truthfully instead of the generic "Context unavailable" wording. This is a
# display-only label; it introduces no new machine status code.
_NATIVE_SOURCE_STALE_FRESHNESS_STATES = frozenset({"STALE_PRIMARY_4H", "STALE_SUPPORT_1H"})
MISSING_CANDLES_DISPLAY_LABEL = "MISSING CANDLES"

STATE_LABELS: dict[str, str] = {
    "CONTEXT_UNAVAILABLE": "Context unavailable",
    "TRANSIENT_NON_CANONICAL_SHORT_CONTEXT": "Transient SHORT context (non-canonical reference)",
    "STALE_CURRENT_PRICE": "Stale current price",
    "HAS_NATIVE_SHORT_FIB_CONTEXT": "Native SHORT fib context available",
    "NO_NATIVE_SHORT_FIB_CONTEXT": "No native SHORT fib context",
    "MARKET_DATA_MISSING": "Market data missing",
    "CONTEXT_INVALID_OR_STALE": "Context invalid or stale",
    "TAKE_PROFIT_WAITING": "Sell order already waiting",
    "RELOAD_ZONE_APPROACHING": "Reload zone approaching",
    "PRICE_RAN_AWAY": "Price ran away",
    "INVALIDATION_NEAR": "Invalidation zone near",
    "ORDER_TOO_FAR_OR_STALE": "Order too far or stale",
    "POST_EXTENSION_PULLBACK": "Post-extension pullback",
    "MAP_RECOMPUTE_NEEDED": "Map recompute needed",
    "DO_NOTHING": "Do nothing",
    "INSUFFICIENT_DATA": "Insufficient data",
    PRIMARY_STATE_CANONICAL_NAVIGATION_ONLY: "Canonical 4h map (navigation only, not lifecycle-verified)",
    SHORT_CONTEXT_DISPLAY_CANONICAL_NAVIGATION_AVAILABLE: CANONICAL_MAP_CONTEXT_LABEL,
}

RELEVANT_STATES: frozenset[str] = frozenset({
    "NO_NATIVE_SHORT_FIB_CONTEXT",
    "MARKET_DATA_MISSING",
    "CONTEXT_INVALID_OR_STALE",
    "TAKE_PROFIT_NEAR",
    "REBUY_ZONE_NEAR",
    "BUY_DIP",
    "BREAKOUT_WATCH",
    "REENTRY_WAIT",
    "RANGE_BOUNCE",
    "BREAKOUT_RETEST",
    "TAKE_PROFIT_WAITING",
    "RELOAD_ZONE_APPROACHING",
    "PRICE_RAN_AWAY",
    "INVALIDATION_NEAR",
    "ORDER_TOO_FAR_OR_STALE",
    "POST_EXTENSION_PULLBACK",
    "MAP_RECOMPUTE_NEEDED",
    "MAP_COMPLETED",
})

# ---------------------------------------------------------------------------
# Canonical semantic state enumerations (v2 redesign)
# ---------------------------------------------------------------------------

SETUP_STATE_FROM_SCENARIO: dict[str, str] = {
    "CONTEXT_UNAVAILABLE": "MINIMAL_CONTEXT",
    "EXTENSION_RUNNER": "EXTENSION_SETUP",
    "BREAKOUT_RETEST": "BREAKOUT_SETUP",
    "REENTRY_WAIT": "REENTRY_SETUP",
    "RANGE_BOUNCE": "RANGE_SETUP",
    "MAP_COMPLETED": "MAP_COMPLETED",
    "LEGACY_CONTEXT_REFERENCE_ONLY": "MINIMAL_CONTEXT",
    "NO_CLEAR_PLAN": "MINIMAL_CONTEXT",
    "NO_SHORT_FIB_CONTEXT": "MINIMAL_CONTEXT",
    "NO_CURRENT_PRICE": "MINIMAL_CONTEXT",
    SCENARIO_CANONICAL_MARKET_CONTEXT: "MINIMAL_CONTEXT",
}

EVENT_STATE_FROM_PRIMARY: dict[str, str] = {
    "CONTEXT_UNAVAILABLE": "CONTEXT_UNAVAILABLE",
    PRIMARY_STATE_CANONICAL_NAVIGATION_ONLY: "BETWEEN_LEVELS",
    "RELOAD_ZONE_APPROACHING": "RELOAD_ZONE_APPROACHING",
    "TAKE_PROFIT_WAITING": "TARGET_APPROACHING",
    "MAP_RECOMPUTE_NEEDED": "MAP_EXPIRED",
    "POST_EXTENSION_PULLBACK": "MAP_EXPIRED",
    "INVALIDATION_NEAR": "INVALIDATION_NEAR",
    "DO_NOTHING": "BETWEEN_LEVELS",
    "PRICE_RAN_AWAY": "BETWEEN_LEVELS",
    "ORDER_TOO_FAR_OR_STALE": "BETWEEN_LEVELS",
    "INSUFFICIENT_DATA": "CONTEXT_UNAVAILABLE",
    "NO_NATIVE_SHORT_FIB_CONTEXT": "CONTEXT_UNAVAILABLE",
    "HAS_NATIVE_SHORT_FIB_CONTEXT": "BETWEEN_LEVELS",
    "MARKET_DATA_MISSING": "CONTEXT_UNAVAILABLE",
    "CONTEXT_INVALID_OR_STALE": "CONTEXT_UNAVAILABLE",
    "STALE_CURRENT_PRICE": "CONTEXT_UNAVAILABLE",
}

RELEVANT_EVENT_STATES: frozenset[str] = frozenset({
    "RELOAD_ZONE_APPROACHING",
    "TARGET_APPROACHING",
    "TARGET_HIT",
    "MAP_EXPIRED",
    "INVALIDATION_NEAR",
    "CONTEXT_UNAVAILABLE",
})

RELEVANT_LADDER_STATES: frozenset[str] = frozenset({
    "LADDER_MISSING",
    "LADDER_INCOMPLETE",
    "STALE_ORDERS_PRESENT",
    "ORDER_DATA_UNAVAILABLE",
})

_ACTION_DISPLAY_MAP: dict[str, str] = {
    "REVIEW_CONTEXT": "REVIEW CONTEXT",
    "WAIT": "BETWEEN LEVELS",
    "NO_ACTION": "BETWEEN LEVELS",
    "DO_NOTHING": "BETWEEN LEVELS",
    "WAIT_FOR_SHORT_CONTEXT": "CONTEXT UNAVAILABLE",
    "WAIT_FOR_NEW_MAP": "MAP EXPIRED",
    "NAVIGATION_ONLY": "NAVIGATION MAP",
    ACTION_LABEL_CANONICAL_NAVIGATION_ONLY: "CANONICAL NAVIGATION ONLY",
    "NO_CURRENT_PRICE": "PRICE UNAVAILABLE",
    "PLACE_LADDER": "SETUP LADDER",
    "REPAIR_LADDER": "REVIEW LADDER",
    "FAR_MOONBAG_ONLY": "MOONBAG ONLY",
}

CARD_ACTIONABILITY_ACTIVE = "ACTIVE_TRADE_SETUP"
CARD_ACTIONABILITY_NAVIGATION_ONLY = "NAVIGATION_ONLY"
CARD_ACTIONABILITY_HISTORICAL_REFERENCE = "HISTORICAL_REFERENCE"
CARD_ACTIONABILITY_NEEDS_RECOMPUTE = "NEEDS_RECOMPUTE"
CARD_ACTIONABILITY_INVALIDATED = "INVALIDATED"
CARD_ACTIONABILITY_CONTEXT_UNAVAILABLE = "CONTEXT_UNAVAILABLE"

# Visibility/grouping classification (Issue #212). Distinct from is_relevant:
# is_relevant means "actionable, counts toward attention"; visibility_class means
# "how the default rendered view should group/label this card". A card can be
# fully present and discoverable while still being non-relevant/non-actionable
# (CANONICAL_NAVIGATION_REFERENCE) -- that combination must never be reported
# as "filtered".
# Issue #223: "ACTIONABLE" was semantically misleading -- this bucket also holds
# native cards that are attention/navigation-only (e.g. completed maps), not just
# ones with a live tradeable action. VISIBILITY_NATIVE_ATTENTION is the correct
# name: "any native lifecycle-verified card, regardless of moment-to-moment
# actionability". VISIBILITY_ACTIONABLE is kept as a same-value alias so existing
# imports/tests continue to resolve without silently reintroducing the old,
# misleading string value.
VISIBILITY_NATIVE_ATTENTION = "NATIVE_ATTENTION"
VISIBILITY_ACTIONABLE = VISIBILITY_NATIVE_ATTENTION
VISIBILITY_CANONICAL_NAVIGATION_REFERENCE = "CANONICAL_NAVIGATION_REFERENCE"
VISIBILITY_CONTEXT_UNAVAILABLE = "CONTEXT_UNAVAILABLE"

CARD_MODE_POSITION_HELD = "POSITION_HELD"
CARD_MODE_ACCOUNT_ORDER_ONLY = "ACCOUNT_ORDER_ONLY"
CARD_MODE_ACCOUNT_PLAN_ENABLED = "ACCOUNT_PLAN_ENABLED"
CARD_MODE_WATCH_ONLY_ROTATION = "WATCH_ONLY_ROTATION"
CARD_MODE_MARKET_SELECTED = "MARKET_SELECTED_NO_ACCOUNT_STATE"

_NO_ACCOUNT_STATE_MODES: frozenset[str] = frozenset({
    CARD_MODE_WATCH_ONLY_ROTATION,
    CARD_MODE_MARKET_SELECTED,
})

# Canonical action filter options — always rendered in this order, regardless of card set.
# Zero-count options remain visible (may be muted); unknown render-derived values appended after.
CANONICAL_ACTION_FILTER: tuple[tuple[str, str], ...] = (
    ("fix_ladder", "Fix ladder"),
    ("review_context", "Review context"),
    ("map_switch_review", "Map switch review"),
    ("wait_for_entry", "Wait for entry"),
    ("take_profit_near", "Take profit"),
    ("between_levels", "Between levels"),
    ("map_expired", "Map expired"),
    ("navigation_map", "Navigation Map"),
    ("manual_review", "Manual review"),
    ("breakout_watch", "Breakout Watch"),
    ("invalidated", "Invalidated"),
)

SHORT_CONTEXT_DISPLAY_LABELS: dict[str, str] = {
    "TRANSIENT_NON_CANONICAL_SHORT_CONTEXT": "Transient SHORT context (non-canonical reference)",
    "HAS_NATIVE_SHORT_FIB_CONTEXT": "Native SHORT fib context available",
    "NO_NATIVE_SHORT_FIB_CONTEXT": "No native SHORT fib context",
    "MARKET_DATA_MISSING": "Market data missing",
    "CONTEXT_INVALID_OR_STALE": "Context invalid or stale",
    SHORT_CONTEXT_DISPLAY_CANONICAL_NAVIGATION_AVAILABLE: CANONICAL_MAP_CONTEXT_LABEL,
}


SCENARIO_DISPLAY_LABELS: dict[str, str] = {
    "REENTRY_WAIT": "REENTRY SETUP",
}

SEARCH_TEXT_TOKEN_OVERRIDES: dict[str, str] = {
    "REENTRY_WAIT": "REENTRY_SETUP",
    "WAIT": "",
}
LEGACY_SHORT_REFERENCE_SCENARIO = "LEGACY_CONTEXT_REFERENCE_ONLY"
LEGACY_SHORT_REFERENCE_ACTION = "MANUAL_REVIEW"


# ---------------------------------------------------------------------------
# Context inputs (populated by runner, no research/broker imports here)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FibExtContext:
    """HTF fib extension snapshot for one symbol."""
    ext_1_272: Decimal
    ext_1_618: Decimal
    ext_2_000: Decimal
    breakout_gate: Decimal
    local_reaction_price: Decimal | None
    anchor_end_ts_utc: datetime | None
    price_band: str
    ext_1_272_touched_and_rejected: bool
    retesting_breakout_gate: bool


@dataclass(frozen=True)
class ReentryContext:
    """Fib retrace ladder snapshot for one symbol."""
    r382_price: Decimal
    r500_price: Decimal
    r618_price: Decimal
    r786_price: Decimal
    deepest_touched_label: str | None
    missed_main_rebuy_by_pct: Decimal | None


@dataclass(frozen=True)
class FibNavContext:
    """
    Navigation map context extracted from FibNavigationMap.

    Populated by the runner when the primary map is exhausted.
    The card builder uses these levels for display when all sell targets
    have been historically passed. No fib builder imports — plain Decimals only.
    """
    nav_sell_levels: tuple[Decimal, ...]   # extension levels above current price (ascending)
    nav_buy_levels: tuple[Decimal, ...]    # retracement levels below current price (descending)
    nav_invalidation: Decimal | None       # r_1000 price (anchor_low for bullish)
    map_state: str                         # EMERGENCY_REBUILT / FALLBACK / FRESH / etc.
    rebuild_trigger: str
    anchor_low: Decimal
    anchor_high: Decimal
    direction: str


@dataclass(frozen=True)
class ActiveOrderSummary:
    open_buy_orders: int
    open_sell_orders: int
    matching_buys: int
    matching_sells: int
    nearest_buy_price: Decimal | None
    nearest_sell_price: Decimal | None
    nearest_buy_distance_pct: Decimal | None
    nearest_sell_distance_pct: Decimal | None
    nearest_open_buy_distance_pct: Decimal | None
    nearest_open_sell_distance_pct: Decimal | None
    max_open_order_distance_pct: Decimal | None
    missing_suggested: tuple[str, ...]
    existing_open_orders_summary: str


@dataclass(frozen=True)
class TargetLevelStatus:
    level: Decimal
    lifecycle_state: str
    coverage_state: str
    human_label: str
    retest_context: str | None
    first_cross_ts_utc: datetime | None
    distance_pct: Decimal | None
    matching_open_sell_orders: int
    nearest_open_sell_price: Decimal | None
    nearest_open_sell_distance_pct: Decimal | None
    is_active_target: bool


@dataclass(frozen=True)
class CardEvidence:
    map_cycle_id: str = DATA_UNAVAILABLE
    native_map_id: str = DATA_UNAVAILABLE
    native_map_status: str = DATA_UNAVAILABLE
    selected_map_reason: str = DATA_UNAVAILABLE
    selected_map_tier: str = DATA_UNAVAILABLE
    lifecycle_state: str = DATA_UNAVAILABLE
    rollover_state: str = DATA_UNAVAILABLE
    previous_map_cycle_id: str = DATA_UNAVAILABLE
    previous_map_lifecycle_state: str = DATA_UNAVAILABLE
    # Account/order snapshot freshness for this card. Until Lane A plumbs a fresh
    # per-account snapshot, this stays DATA_UNAVAILABLE and account-specific repair
    # actions (FIX LADDER) fail closed.
    account_order_snapshot_status: str = DATA_UNAVAILABLE
    # Per-authority account evidence (P1 evidence-card normalization). Distinct from
    # the combined account_order_snapshot_status above so wallet/position/order truth
    # can be displayed independently and never compressed into one generic label.
    # Stays DATA_UNAVAILABLE until Lane A plumbs a real per-authority snapshot.
    wallet_snapshot_status: str = DATA_UNAVAILABLE
    position_snapshot_status: str = DATA_UNAVAILABLE
    # Portfolio composition fields (Issue #238). Populated from
    # trading_account_balance_snapshot / account_position_snapshot read-only
    # snapshots. Stay DATA_UNAVAILABLE when the source snapshot has no row for
    # this symbol — never fabricated.
    held_amount: str = DATA_UNAVAILABLE
    held_eur_value: str = DATA_UNAVAILABLE
    cost_basis_price_eur: str = DATA_UNAVAILABLE
    map_age_min: str = DATA_UNAVAILABLE
    anchor_start_ts_utc: str = DATA_UNAVAILABLE
    anchor_end_ts_utc: str = DATA_UNAVAILABLE
    anchor_low_price: str = DATA_UNAVAILABLE
    anchor_high_price: str = DATA_UNAVAILABLE
    price_ts_utc: str = DATA_UNAVAILABLE
    price_freshness_state: str = DATA_UNAVAILABLE
    order_snapshot_ts_utc: str = DATA_UNAVAILABLE
    order_coverage_ts_utc: str = DATA_UNAVAILABLE
    context_ts_utc: str = DATA_UNAVAILABLE
    generation_ts_utc: str = DATA_UNAVAILABLE
    update_ts_utc: str = DATA_UNAVAILABLE
    # Raw canonical native_short_fib_context_v1 context_freshness_status passthrough
    # (FRESH / STALE_PRIMARY_4H / STALE_SUPPORT_1H). Truthful evidence only -- never
    # inferred from timestamps here. Used solely to select a truthful degraded
    # display label (state_model_discipline_v1.md); does not change
    # short_context_display_state, actionability_state, or any other machine state.
    native_context_freshness_status: str = DATA_UNAVAILABLE


@dataclass(frozen=True)
class CardDelta:
    delta_status: str = "NO_PREVIOUS_SNAPSHOT"
    material_delta_types: tuple[str, ...] = ()
    changed_fields: tuple[str, ...] = ()
    comparison_key: str = DATA_UNAVAILABLE


@dataclass(frozen=True)
class EvidenceRow:
    """One normalized, independently-owned evidence authority row (P1 evidence-card
    semantic normalization). Each row carries exactly one authority owner and one
    canonical status, and must not infer its status from unrelated rows. The same
    rows drive card HTML, sidebar/detail HTML, and the JSON snapshot."""
    key: str
    label: str
    authority: str
    status: str
    observed_ts: str | None = None
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProfitPlanCard:
    symbol: str
    market: str
    fib_trading_horizon: str
    short_context_input_status: str
    short_context_coverage_status: str
    short_context_display_state: str
    current_price: Decimal | None
    current_price_status: str | None
    current_price_age_min: Decimal | None
    history_high_since_activation: Decimal | None
    history_low_since_activation: Decimal | None
    all_sell_targets_completed: bool
    scenario_type: str
    action_label: str
    timeframe_label: str
    buy_zone: tuple[Decimal, ...]
    sell_zone: tuple[Decimal, ...]
    invalidation_level: Decimal | None
    reasons: tuple[str, ...]
    order_summary: ActiveOrderSummary
    target_exit_zone: tuple[Decimal, ...]
    active_target: Decimal | None
    target_level_statuses: tuple[TargetLevelStatus, ...]
    reload_reentry_zone: tuple[Decimal, ...]
    invalidation_risk_zone: Decimal | None
    distance_to_target_pct: Decimal | None
    distance_to_reload_pct: Decimal | None
    distance_to_invalidation_pct: Decimal | None
    primary_state: str
    secondary_state: str | None
    suggested_manual_attention_label: str
    setup_state: str
    event_state: str
    ladder_states: tuple[str, ...]
    relevance_reasons: tuple[str, ...]
    is_relevant: bool
    actionability_state: str = CARD_ACTIONABILITY_ACTIVE
    visibility_class: str = VISIBILITY_NATIVE_ATTENTION
    presentation_mode: str = CARD_MODE_MARKET_SELECTED
    # Two independent, never-conflated facts (GUI terminology correction):
    # is_portfolio_asset = configured strategic portfolio/rotation membership
    # (asset.is_portfolio), independent of current balance. is_wallet_held =
    # the latest persisted wallet snapshot has a positive amount for this
    # symbol. A zero-balance portfolio asset has is_portfolio_asset=True and
    # is_wallet_held=False; both may be True at once.
    is_portfolio_asset: bool = False
    is_wallet_held: bool = False
    fib_nav_context: FibNavContext | None = None
    render_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    breath_curve: dict[str, Any] | None = None
    evidence: CardEvidence = field(default_factory=CardEvidence)
    delta: CardDelta = field(default_factory=CardDelta)


@dataclass(frozen=True)
class TargetHistoryCandle:
    close_ts_utc: datetime
    high_price: Decimal
    low_price: Decimal


@dataclass(frozen=True)
class OrderRow:
    """One selectable row in the order ladder display."""
    row_id: str         # stable UUID4 within a render
    render_id: str      # parent card render_id
    state: str          # MISSING | ARMED | STALE | HISTORICAL | DATA_UNAVAILABLE
    reason_code: str    # machine code for tooltip/filtering
    reason_label: str   # human-readable tooltip text
    side: str           # buy | sell
    price: Decimal | None
    distance_pct: Decimal | None
    zone_role: str      # zone description e.g. "sell target 1.272" or "buy zone r382"


# ---------------------------------------------------------------------------
# Scenario classification
# ---------------------------------------------------------------------------

def _is_nan_or_inf(v: Decimal) -> bool:
    return v.is_nan() or v.is_infinite()


def _strip_decimal_zeros(v: Decimal) -> str:
    # format(v, "f") always renders fixed-point (never scientific notation).
    text = format(v, "f")
    if "." not in text:
        return text
    text = text.rstrip("0").rstrip(".")
    if text in {"", "-0"}:
        return "0"
    return text


def _price_decimal_places(v: Decimal) -> int:
    """Deterministic magnitude-based decimal-place fallback for prices with no
    exchange/tick metadata (see src/market_rules/price_tick_normalization_v1.py
    for the tick-aware path used upstream when a market's tick rule is known).

    Never inferred from a real tick size — this is only the display fallback
    for values that reach here without one (e.g. MISSING_TICK_RULE). Chosen to
    always cover at least the canonical tick precisions used across markets
    (2/4/5/6/8 dp) so no meaningful digit is lost; trailing zeros are stripped
    by the caller.
    """
    if v == 0:
        return 2
    exponent = v.adjusted()  # position of the most significant digit
    if exponent >= 2:
        return 2
    if exponent >= 0:
        return 4
    return max(6, -exponent + 4)


def _fmt_p(v: Decimal | None) -> str:
    if v is None:
        return "?"
    if _is_nan_or_inf(v):
        return "?"
    if v == 0:
        return "0"
    dp = _price_decimal_places(v)
    quantizer = Decimal(1).scaleb(-dp)
    return _strip_decimal_zeros(v.quantize(quantizer, rounding=ROUND_HALF_UP))


def _format_percent_value(v: Decimal) -> str:
    """Max 2 decimals, no fixed-width zero padding; extends precision only far
    enough to avoid a non-zero value misleadingly rendering as 0%."""
    quantized = v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if quantized != 0 or v == 0:
        return _strip_decimal_zeros(quantized)
    for dp in range(3, 11):
        finer = v.quantize(Decimal(1).scaleb(-dp), rounding=ROUND_HALF_UP)
        if finer != 0:
            return _strip_decimal_zeros(finer)
    return _strip_decimal_zeros(v.quantize(Decimal(1).scaleb(-10), rounding=ROUND_HALF_UP))


def _pct(v: Decimal | None) -> str:
    if v is None:
        return "?"
    if _is_nan_or_inf(v):
        return "?"
    return f"{_format_percent_value(v)}%"


def _price_display(v: Decimal | None) -> str:
    """JSON display companion for a price field. DATA_UNAVAILABLE for missing,
    matching the evidence-row convention used elsewhere in this snapshot."""
    if v is None or _is_nan_or_inf(v):
        return DATA_UNAVAILABLE
    return _fmt_p(v)


def _pct_display(v: Decimal | None) -> str:
    """JSON display companion for a percent field. DATA_UNAVAILABLE for missing."""
    if v is None or _is_nan_or_inf(v):
        return DATA_UNAVAILABLE
    return _pct(v)


def _fmt_pct_number(v: Any) -> str:
    try:
        return f"{float(v):.1f}%"
    except (TypeError, ValueError):
        return "—"


def _value_or_data_unavailable(value: Any) -> str:
    if value is None:
        return DATA_UNAVAILABLE
    text = str(value).strip()
    return text if text else DATA_UNAVAILABLE


def _evidence_json(evidence: CardEvidence) -> dict[str, str]:
    return dataclasses.asdict(evidence)


def _delta_json(delta: CardDelta) -> dict[str, Any]:
    return {
        "delta_status": delta.delta_status,
        "material_delta_types": list(delta.material_delta_types),
        "changed_fields": list(delta.changed_fields),
        "comparison_key": delta.comparison_key,
    }


def card_identity_key(card_json: dict[str, Any]) -> str:
    symbol = _value_or_data_unavailable(card_json.get("symbol"))
    market = _value_or_data_unavailable(card_json.get("market"))
    horizon = _value_or_data_unavailable(card_json.get("fib_trading_horizon"))
    return "|".join((symbol, market, horizon))


def _extract_previous_symbol_rows(previous_snapshot: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not previous_snapshot:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in previous_snapshot.get("symbols") or []:
        if not isinstance(row, dict):
            continue
        out[card_identity_key(row)] = row
    return out


_DELTA_FIELD_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "MAP_CHANGED",
        (
            "evidence.map_cycle_id",
            "evidence.native_map_id",
            "evidence.native_map_status",
            "evidence.selected_map_reason",
            "evidence.selected_map_tier",
            "evidence.rollover_state",
            "evidence.previous_map_cycle_id",
            "evidence.previous_map_lifecycle_state",
        ),
    ),
    ("MAP_LIFECYCLE_CHANGED", ("evidence.lifecycle_state", "actionability_state", "all_sell_targets_completed")),
    ("TARGET_CHANGED", ("target_exit_zone", "active_target", "target_level_statuses")),
    ("RELOAD_ZONE_CHANGED", ("reload_reentry_zone", "buy_zone")),
    ("INVALIDATION_CHANGED", ("invalidation_level", "invalidation_risk_zone")),
    ("PRICE_MATERIAL_CHANGE", ("current_price",)),
    (
        "ORDER_COVERAGE_CHANGED",
        (
            "order_summary.matching_buys",
            "order_summary.matching_sells",
            "order_summary.missing_suggested",
            "order_summary.existing_open_orders_summary",
            "ladder_states",
        ),
    ),
    (
        "SIGNAL_CONTEXT_CHANGED",
        (
            "short_context_input_status",
            "short_context_coverage_status",
            "short_context_display_state",
            "scenario_type",
            "setup_state",
            "event_state",
            "primary_state",
            "secondary_state",
        ),
    ),
    (
        "DATA_FRESHNESS_CHANGED",
        (
            "current_price_status",
            "current_price_age_min",
            "evidence.price_ts_utc",
            "evidence.price_freshness_state",
            "evidence.order_snapshot_ts_utc",
            "evidence.order_coverage_ts_utc",
            "evidence.context_ts_utc",
            "evidence.generation_ts_utc",
            "evidence.update_ts_utc",
        ),
    ),
)


def _semantic_field_value(card_json: dict[str, Any], field_path: str) -> Any:
    value: Any = card_json
    for part in field_path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def compare_card_delta(
    *,
    current_card_json: dict[str, Any],
    previous_card_json: dict[str, Any] | None,
) -> CardDelta:
    comparison_key = card_identity_key(current_card_json)
    if previous_card_json is None:
        return CardDelta(delta_status="NO_PREVIOUS_SNAPSHOT", comparison_key=comparison_key)

    material_types: list[str] = []
    changed_fields: list[str] = []
    for delta_type, field_paths in _DELTA_FIELD_GROUPS:
        group_changed: list[str] = []
        for field_path in field_paths:
            if _semantic_field_value(current_card_json, field_path) != _semantic_field_value(previous_card_json, field_path):
                group_changed.append(field_path)
        if group_changed:
            material_types.append(delta_type)
            changed_fields.extend(group_changed)

    if not material_types:
        return CardDelta(delta_status="UNCHANGED", comparison_key=comparison_key)
    return CardDelta(
        delta_status="UPDATED_NOW",
        material_delta_types=tuple(material_types),
        changed_fields=tuple(dict.fromkeys(changed_fields)),
        comparison_key=comparison_key,
    )


def _card_delta_payload(card: "ProfitPlanCard") -> dict[str, Any]:
    return {
        "symbol": card.symbol,
        "market": card.market,
        "fib_trading_horizon": card.fib_trading_horizon,
        "short_context_input_status": card.short_context_input_status,
        "short_context_coverage_status": card.short_context_coverage_status,
        "short_context_display_state": card.short_context_display_state,
        "current_price": str(card.current_price) if card.current_price is not None else None,
        "current_price_status": card.current_price_status,
        "current_price_age_min": str(card.current_price_age_min) if card.current_price_age_min is not None else None,
        "all_sell_targets_completed": card.all_sell_targets_completed,
        "scenario_type": card.scenario_type,
        "actionability_state": card.actionability_state,
        "buy_zone": [str(p) for p in card.buy_zone],
        "invalidation_level": str(card.invalidation_level) if card.invalidation_level is not None else None,
        "target_exit_zone": [str(p) for p in card.target_exit_zone],
        "active_target": str(card.active_target) if card.active_target is not None else None,
        "target_level_statuses": [
            {
                "level": str(level.level),
                "lifecycle_state": level.lifecycle_state,
                "coverage_state": level.coverage_state,
                "is_active_target": level.is_active_target,
            }
            for level in card.target_level_statuses
        ],
        "reload_reentry_zone": [str(p) for p in card.reload_reentry_zone],
        "invalidation_risk_zone": str(card.invalidation_risk_zone) if card.invalidation_risk_zone is not None else None,
        "primary_state": card.primary_state,
        "secondary_state": card.secondary_state,
        "setup_state": card.setup_state,
        "event_state": card.event_state,
        "ladder_states": list(card.ladder_states),
        "order_summary": {
            "matching_buys": card.order_summary.matching_buys,
            "matching_sells": card.order_summary.matching_sells,
            "missing_suggested": list(card.order_summary.missing_suggested),
            "existing_open_orders_summary": card.order_summary.existing_open_orders_summary,
        },
        "evidence": _evidence_json(card.evidence),
    }


def apply_card_deltas(
    cards: list["ProfitPlanCard"],
    *,
    previous_snapshot: dict[str, Any] | None,
) -> list["ProfitPlanCard"]:
    previous_rows = _extract_previous_symbol_rows(previous_snapshot)
    out: list[ProfitPlanCard] = []
    for card in cards:
        current_payload = _card_delta_payload(card)
        delta = compare_card_delta(
            current_card_json=current_payload,
            previous_card_json=previous_rows.get(card_identity_key(current_payload)),
        )
        out.append(dataclasses.replace(card, delta=delta))
    return out


def _breath_curve_availability(payload: dict[str, Any] | None) -> str:
    return str((payload or {}).get("availability_state") or "UNAVAILABLE").upper()


def _breath_curve_phase_marker_text(payload: dict[str, Any] | None) -> str:
    availability = _breath_curve_availability(payload)
    if availability != "AVAILABLE":
        return availability
    return str((payload or {}).get("phase_marker") or "UNAVAILABLE").upper()


def _breath_curve_offset_band_text(payload: dict[str, Any] | None) -> str:
    availability = _breath_curve_availability(payload)
    if availability != "AVAILABLE":
        return "—"
    return str((payload or {}).get("phase_offset_band") or "—").upper()


def _breath_curve_match_score_text(payload: dict[str, Any] | None) -> str:
    availability = _breath_curve_availability(payload)
    if availability != "AVAILABLE":
        return "—"
    score = (payload or {}).get("template_match_score")
    try:
        return _fmt_pct_number(float(score) * 100.0)
    except (TypeError, ValueError):
        return "—"


def _breath_curve_data_coverage_text(payload: dict[str, Any] | None) -> str:
    coverage = (payload or {}).get("data_coverage") or {}
    ratio = coverage.get("coverage_ratio")
    count = coverage.get("closed_candle_count")
    if ratio is None and count is None:
        return "—"
    ratio_text = _fmt_pct_number(float(ratio) * 100.0) if ratio is not None else "—"
    count_text = f"{count} candles" if count is not None else "unknown candles"
    return f"{ratio_text} · {count_text}"


def _breath_curve_freshness_text(payload: dict[str, Any] | None) -> str:
    return str((payload or {}).get("freshness_label") or "UNAVAILABLE").upper()


def _breath_curve_current_checkpoint_text(payload: dict[str, Any] | None) -> str:
    availability = _breath_curve_availability(payload)
    if availability != "AVAILABLE":
        return availability.replace("_", " ")
    return str((payload or {}).get("current_checkpoint") or "UNAVAILABLE").upper()


def _breath_curve_next_checkpoint_text(payload: dict[str, Any] | None) -> str:
    availability = _breath_curve_availability(payload)
    if availability != "AVAILABLE":
        return "—"
    return str((payload or {}).get("next_checkpoint") or "—").upper()


def _breath_curve_next_timing_text(payload: dict[str, Any] | None) -> str:
    availability = _breath_curve_availability(payload)
    if availability != "AVAILABLE":
        return "—"
    next_ts = str((payload or {}).get("next_target_expected_ts_utc") or "").strip()
    if not next_ts:
        return "—"
    return next_ts


def _breath_curve_btc_relation_text(payload: dict[str, Any] | None) -> str:
    relation = (payload or {}).get("lead_lag_vs_btc")
    if not relation:
        return "UNAVAILABLE"
    rel = str(relation.get("relation") or "UNAVAILABLE").upper()
    delta_days = relation.get("delta_days")
    if delta_days is None:
        return rel
    try:
        return f"{rel} ({float(delta_days):+.1f}d)"
    except (TypeError, ValueError):
        return rel


def _breath_curve_compact_summary(payload: dict[str, Any] | None) -> str:
    availability = _breath_curve_availability(payload)
    if availability != "AVAILABLE":
        return availability.replace("_", " ")
    return (
        f"{_breath_curve_current_checkpoint_text(payload)}"
        f" · {_breath_curve_offset_band_text(payload)}"
    )


def _breath_curve_detail_html(payload: dict[str, Any] | None) -> str:
    payload = payload or {}
    source_ts = str(payload.get("source_candle_ts_utc") or "—")
    warnings = payload.get("warnings") or []
    warnings_text = " · ".join(str(v) for v in warnings if v) or "none"
    blocks = (
        _metric_block("Current checkpoint", _breath_curve_current_checkpoint_text(payload)),
        _metric_block("Offset band", _breath_curve_offset_band_text(payload)),
        _metric_block("Match quality", _breath_curve_match_score_text(payload)),
        _metric_block("Next checkpoint", _breath_curve_next_checkpoint_text(payload)),
        _metric_block("Expected timing", _breath_curve_next_timing_text(payload)),
        _metric_block("BTC relation", _breath_curve_btc_relation_text(payload)),
        _metric_block("Source candle", source_ts),
        _metric_block("Freshness", _breath_curve_freshness_text(payload)),
        _metric_block("Data coverage", _breath_curve_data_coverage_text(payload)),
    )
    # Demoted: research-only, muted/greyed, zero action weight.
    return (
        "<div class='market-breath-section breath-curve-section breath-curve-disabled disabled muted'>"
        "<div class='market-breath-header'>Breathline context"
        f" <span class='breath-disabled-tag'>{esc(BREATHLINE_DISPLAY_STATE)}</span></div>"
        f"<div class='market-breath-note muted small'>{esc(BREATHLINE_DISABLED_NOTE)}</div>"
        f"<div class='market-breath-grid'>{''.join(blocks)}</div>"
        f"<div class='market-breath-note muted small'>Warnings: {esc(warnings_text)}."
        " Research context only — selection_weight=0 · action_weight=0 · decision_weight=0."
        " Not a forecast or execution input.</div>"
        "</div>"
    )


def _distance_to_level_pct(current_price: Decimal | None, level: Decimal | None) -> Decimal | None:
    if current_price is None or current_price <= 0 or level is None or level <= 0:
        return None
    return (level - current_price) / current_price * Decimal("100")


def _distance_to_zone_pct(current_price: Decimal | None, levels: tuple[Decimal, ...]) -> Decimal | None:
    if current_price is None or current_price <= 0 or not levels:
        return None
    distances = [_distance_to_level_pct(current_price, level) for level in levels]
    valid = [dist for dist in distances if dist is not None]
    if not valid:
        return None
    return min(valid, key=lambda dist: abs(dist))


def _profit_plan_potential_pct_from_levels(
    entry_levels: tuple[Decimal, ...],
    target_levels: tuple[Decimal, ...],
) -> Decimal | None:
    """Return PPP: lowest entry/reload level to highest active target."""
    if not entry_levels or not target_levels:
        return None
    entry = min(entry_levels)
    target = max(target_levels)
    if entry <= 0:
        return None
    return (target - entry) / entry * Decimal("100")


def _profit_plan_target_levels(card: ProfitPlanCard) -> tuple[Decimal, ...]:
    """Return the full planned Profit Plan target set for PPP display/sort."""
    levels: list[Decimal] = list(card.target_exit_zone)
    for target_status in card.target_level_statuses:
        if target_status.level is not None and target_status.level > 0:
            levels.append(target_status.level)
    return _unique_levels(tuple(levels))


def _profit_plan_potential_pct(card: ProfitPlanCard) -> Decimal | None:
    """Planning PPP: lowest planned entry to highest planned target.

    Theoretical map potential / plan reference quality. Reference display only —
    must never promote a card into the actionable bucket.
    """
    return _profit_plan_potential_pct_from_levels(
        card.reload_reentry_zone or card.buy_zone,
        _profit_plan_target_levels(card),
    )


# Public alias — user-facing terminology is "Planning PPP".
def _planning_ppp(card: ProfitPlanCard) -> Decimal | None:
    return _profit_plan_potential_pct(card)


# ---------------------------------------------------------------------------
# Actionable PPP eligibility (v2)
#
# Actionable PPP = (highest active target - current price) / current price * 100
# but only when canonical evidence proves the current setup was activated inside
# the current map cycle. Otherwise actionable_ppp is None (fail closed).
# ---------------------------------------------------------------------------

_UNAVAILABLE_TOKENS: frozenset[str] = frozenset({"", DATA_UNAVAILABLE, "NONE", "NULL"})

# Target lifecycle states that constitute canonical, map-cycle-scoped proof that
# the setup advanced (a target was reached/passed/filled within the current
# cycle), which necessarily means the entry was activated earlier in the cycle.
_ACTIVATED_TARGET_LIFECYCLE: frozenset[str] = frozenset({
    "PASSED",
    "REACHED",
    "REACHED_FILLED",
    "COMPLETED",
})

# Previous-map lifecycle states that prove a rollover completion.
_COMPLETED_ROLLOVER_LIFECYCLE: frozenset[str] = frozenset({
    "MAP_COMPLETED",
    "COMPLETED",
    "TARGET_REACHED_OR_PASSED",
    "PASSED",
    "INVALIDATED",
    "MAP_INVALIDATED",
})

# Explicit rollover_state values that indicate a map switch to a newer/other map.
_ROLLOVER_INDICATING_STATES: frozenset[str] = frozenset({
    "CASE_A_NEWER_ACTIVE_SELECTED",
    "CASE_C_INVALIDATED_FALLBACK",
})

# Selected-map reason tokens that imply a newer map / rollover / replacement / switch.
_ROLLOVER_REASON_TOKENS: tuple[str, ...] = (
    "newer",
    "rollover",
    "roll over",
    "rolled over",
    "replace",
    "replacement",
    "map switch",
    "switched",
    "supersed",
)

# Lifecycle / actionability states that mean the map is expired, completed or
# invalidated and therefore cannot support an actionable claim.
_ACTION_BLOCKING_PRIMARY_STATES: frozenset[str] = frozenset({
    "MAP_RECOMPUTE_NEEDED",
    "POST_EXTENSION_PULLBACK",
    "INVALIDATED",
    "MAP_COMPLETED",
})
_ACTION_BLOCKING_LIFECYCLE_STATES: frozenset[str] = frozenset({
    "MAP_COMPLETED",
    "MAP_EXPIRED",
    "MAP_INVALIDATED",
    "COMPLETED",
    "INVALIDATED",
    "EXPIRED",
})


def _is_unavailable(value: Any) -> bool:
    return str(value or "").strip().upper() in _UNAVAILABLE_TOKENS


def _native_map_status(card: ProfitPlanCard) -> str:
    """Native scope-status projection availability for this card.

    Requires the explicit Lane B ``native_map_status`` evidence field. A map ID
    alone cannot prove that the canonical scope-status projection is available.
    """
    status = str(card.evidence.native_map_status or "").strip().upper()
    if status and status not in _UNAVAILABLE_TOKENS:
        return status
    return DATA_UNAVAILABLE


def _canonical_native_map_truth_available(evidence: CardEvidence) -> bool:
    """True only when Lane B provides a coherent canonical map identity.

    The transient SHORT bridge may carry a reporting cycle, selected tier, and
    rollover text. None of those fields is canonical map/scope-status truth.
    Reporting may use lifecycle semantics only when Lane B supplies an explicit
    AVAILABLE projection plus real map and cycle identifiers.
    """
    return (
        str(evidence.native_map_status or "").strip().upper() == "AVAILABLE"
        and not _is_unavailable(evidence.native_map_id)
        and not _is_unavailable(evidence.map_cycle_id)
    )


def _price_is_fresh_enough(card: ProfitPlanCard) -> bool:
    if card.current_price is None or card.current_price <= 0:
        return False
    return card.current_price_status not in {"STALE_CURRENT_PRICE", "MISSING_CURRENT_PRICE"}


def _map_lifecycle_blocks_action(card: ProfitPlanCard) -> bool:
    """True when the map is expired/completed/invalidated (no actionable claim)."""
    if card.all_sell_targets_completed:
        return True
    if card.actionability_state in {
        CARD_ACTIONABILITY_CONTEXT_UNAVAILABLE,
        CARD_ACTIONABILITY_NEEDS_RECOMPUTE,
        CARD_ACTIONABILITY_INVALIDATED,
        CARD_ACTIONABILITY_HISTORICAL_REFERENCE,
        CARD_ACTIONABILITY_NAVIGATION_ONLY,
    }:
        return True
    if card.primary_state in _ACTION_BLOCKING_PRIMARY_STATES:
        return True
    if str(card.evidence.lifecycle_state or "").strip().upper() in _ACTION_BLOCKING_LIFECYCLE_STATES:
        return True
    return False


def _selected_map_indicates_rollover(card: ProfitPlanCard) -> bool:
    """True when the selected-map reason/state implies a newer map / rollover."""
    if str(card.evidence.rollover_state or "").strip().upper() in _ROLLOVER_INDICATING_STATES:
        return True
    reason = str(card.evidence.selected_map_reason or "").lower()
    return any(token in reason for token in _ROLLOVER_REASON_TOKENS)


def _rollover_verified(card: ProfitPlanCard) -> bool:
    """A rollover is verified only when canonical previous/current cycle evidence exists."""
    if not _canonical_native_map_truth_available(card.evidence):
        return False
    if _is_unavailable(card.evidence.map_cycle_id):
        return False
    if _is_unavailable(card.evidence.previous_map_cycle_id):
        return False
    prev_lifecycle = str(card.evidence.previous_map_lifecycle_state or "").strip().upper()
    if prev_lifecycle in _UNAVAILABLE_TOKENS:
        return False
    # Completion evidence: the previous map must be completed/passed/invalidated.
    return prev_lifecycle in _COMPLETED_ROLLOVER_LIFECYCLE


def _map_switch_review_required(card: ProfitPlanCard) -> bool:
    """True when a map switch is indicated but not verifiable from evidence.

    Fails closed: an indicated rollover with a DATA_UNAVAILABLE native projection
    or missing previous/current cycle evidence must be reviewed, not repaired.
    """
    if card.presentation_mode in _NO_ACCOUNT_STATE_MODES:
        return False
    if not _canonical_native_map_truth_available(card.evidence):
        return False
    if not _selected_map_indicates_rollover(card):
        return False
    return not _rollover_verified(card)


def _highest_active_target(card: ProfitPlanCard) -> Decimal | None:
    levels = [level for level in card.target_exit_zone if level is not None and level > 0]
    return max(levels) if levels else None


def _entry_activation_proof(card: ProfitPlanCard) -> bool:
    """Canonical proof that the setup was activated inside the current map cycle.

    Proof = a reached/passed target lifecycle corroborated by the current-cycle
    ``history_high_since_activation`` summary, or a timestamped target crossing
    at or after the map anchor. A lifecycle inferred from the current price alone
    is not proof.
    """
    history_high = card.history_high_since_activation
    anchor_start = _parse_canonical_utc_timestamp(card.evidence.anchor_start_ts_utc)
    for level in card.target_level_statuses:
        if level.lifecycle_state not in _ACTIVATED_TARGET_LIFECYCLE:
            continue
        if history_high is not None and history_high >= level.level:
            return True
        if (
            level.first_cross_ts_utc is not None
            and anchor_start is not None
            and level.first_cross_ts_utc >= anchor_start
        ):
            return True
    return False


def _actionable_ppp_eligible(card: ProfitPlanCard) -> bool:
    if not _price_is_fresh_enough(card):
        return False
    if card.actionability_state != CARD_ACTIONABILITY_ACTIVE:
        return False
    if _is_unavailable(card.evidence.map_cycle_id):
        return False
    if _map_lifecycle_blocks_action(card):
        return False
    if _highest_active_target(card) is None:
        return False
    if _map_switch_review_required(card):
        return False
    if not _entry_activation_proof(card):
        return False
    return True


def _actionable_ppp(card: ProfitPlanCard) -> Decimal | None:
    """Actionable PPP: current price to highest active target, gated by evidence."""
    if not _actionable_ppp_eligible(card):
        return None
    target = _highest_active_target(card)
    if target is None or card.current_price is None or card.current_price <= 0:
        return None
    return (target - card.current_price) / card.current_price * Decimal("100")


def _entry_wait_label(card: ProfitPlanCard) -> str:
    """Human-readable reason Actionable PPP is unavailable for an active-ish card."""
    if _map_switch_review_required(card):
        return "Review map"
    entry_levels = tuple(level for level in (card.reload_reentry_zone or card.buy_zone) if level is not None)
    if entry_levels and card.current_price is not None:
        highest_entry = max(entry_levels)
        if highest_entry > card.current_price:
            return "Entry above current — wait for reclaim"
    return "WAIT FOR ENTRY"


def _planning_ppp_unavailable_reason(card: ProfitPlanCard) -> str | None:
    """Precise, truthful reason Planning PPP has no numeric value.

    Planning PPP only needs a reference entry (reload/buy zone) and a
    reference target (target_exit_zone / target_level_statuses); it must
    never require native SHORT lifecycle proof.
    """
    if _planning_ppp(card) is not None:
        return None
    if card.current_price is None or card.current_price <= 0:
        return "Current price snapshot unavailable."
    if not (card.reload_reentry_zone or card.buy_zone):
        return "No reference re-entry/buy zone available (no canonical 4h or native context)."
    if not _profit_plan_target_levels(card):
        return "No reference target level available (no canonical 4h or native context)."
    return "Planning PPP inputs unavailable."


def _format_planning_ppp(card: ProfitPlanCard) -> str:
    ppp = _planning_ppp(card)
    if ppp is not None:
        return _pct(ppp)
    reason = _planning_ppp_unavailable_reason(card)
    return f"— · {reason}" if reason else "—"


def _format_actionable_ppp(card: ProfitPlanCard) -> str:
    ppp = _actionable_ppp(card)
    if ppp is not None:
        return _pct(ppp)
    if card.actionability_state == CARD_ACTIONABILITY_ACTIVE:
        return f"— · {_entry_wait_label(card)}"
    return "—"


def apply_portfolio_account_evidence(
    cards: list[ProfitPlanCard],
    *,
    held_amount_by_symbol: Mapping[str, Decimal],
    held_eur_value_by_symbol: Mapping[str, Decimal | None],
    cost_basis_by_symbol: Mapping[str, Decimal],
    balance_freshness_status: str = DATA_UNAVAILABLE,
    portfolio_asset_markets: Any = frozenset(),
) -> list[ProfitPlanCard]:
    """Compose account-aware portfolio fields onto held-token cards (Issue #238).

    Read-only composition: holdings, EUR value and cost basis are account-aware
    inputs supplied by the caller from persisted DB snapshots. This function
    never queries a broker or a database itself, and never fabricates a value
    for a symbol absent from the supplied maps — those stay DATA_UNAVAILABLE.

    Sets two independent, never-conflated booleans (GUI terminology
    correction): ``is_wallet_held`` from ``held_amount_by_symbol`` (a
    positive amount in the latest persisted wallet snapshot), and
    ``is_portfolio_asset`` from ``portfolio_asset_markets`` (configured
    strategic portfolio/rotation membership, e.g. ``asset.is_portfolio`` via
    the ``PORTFOLIO_MARKER`` inclusion reason) — independent of balance. A
    zero-balance portfolio asset keeps ``is_portfolio_asset=True`` and
    ``is_wallet_held=False``; both may be True at once.
    """
    out: list[ProfitPlanCard] = []
    for card in cards:
        is_portfolio_asset = card.market in portfolio_asset_markets
        held_amount = held_amount_by_symbol.get(card.symbol)
        if held_amount is None:
            if is_portfolio_asset != card.is_portfolio_asset:
                out.append(dataclasses.replace(card, is_portfolio_asset=is_portfolio_asset))
            else:
                out.append(card)
            continue
        eur_value = held_eur_value_by_symbol.get(card.symbol)
        cost_basis = cost_basis_by_symbol.get(card.symbol)
        new_evidence = dataclasses.replace(
            card.evidence,
            held_amount=_strip_decimal_zeros(held_amount),
            held_eur_value=(_strip_decimal_zeros(eur_value) if eur_value is not None else DATA_UNAVAILABLE),
            cost_basis_price_eur=(_strip_decimal_zeros(cost_basis) if cost_basis is not None else DATA_UNAVAILABLE),
            wallet_snapshot_status=balance_freshness_status,
            position_snapshot_status=(balance_freshness_status if cost_basis is not None else DATA_UNAVAILABLE),
        )
        out.append(
            dataclasses.replace(
                card,
                evidence=new_evidence,
                is_wallet_held=True,
                is_portfolio_asset=is_portfolio_asset,
            )
        )
    return out


def _short_context_display_label(state: str) -> str:
    return SHORT_CONTEXT_DISPLAY_LABELS.get(state, state.replace("_", " "))


def _derive_card_actionability_state(
    *,
    scenario_type: str,
    action_label: str,
    short_context_display_state: str,
    primary_state: str,
    current_price: Decimal | None,
    invalidation_level: Decimal | None,
    canonical_native_map_truth_available: bool,
    canonical_market_context_available: bool = False,
) -> str:
    if not canonical_native_map_truth_available:
        # Native lifecycle truth is unavailable. A canonical_fib_zone_map_latest_v1
        # row (market-only, not lifecycle-verified) still earns a read-only
        # navigation state instead of collapsing to CONTEXT_UNAVAILABLE -- it
        # must never be promoted further than that (Issue #210).
        if canonical_market_context_available:
            return CARD_ACTIONABILITY_NAVIGATION_ONLY
        return CARD_ACTIONABILITY_CONTEXT_UNAVAILABLE
    if primary_state == "INVALIDATED":
        return CARD_ACTIONABILITY_INVALIDATED
    if (
        current_price is not None
        and invalidation_level is not None
        and current_price <= invalidation_level
    ):
        return CARD_ACTIONABILITY_INVALIDATED
    if action_label == "NAVIGATION_ONLY":
        return CARD_ACTIONABILITY_NAVIGATION_ONLY
    if scenario_type in {"MAP_COMPLETED", LEGACY_SHORT_REFERENCE_SCENARIO}:
        if primary_state in {"MAP_RECOMPUTE_NEEDED", "POST_EXTENSION_PULLBACK"}:
            return CARD_ACTIONABILITY_NEEDS_RECOMPUTE
        return CARD_ACTIONABILITY_HISTORICAL_REFERENCE
    if short_context_display_state != "HAS_NATIVE_SHORT_FIB_CONTEXT":
        return CARD_ACTIONABILITY_NEEDS_RECOMPUTE
    return CARD_ACTIONABILITY_ACTIVE


def build_card_search_text(card: ProfitPlanCard) -> str:
    parts = (
        card.symbol,
        card.market,
        card.scenario_type,
        card.primary_state,
        card.action_label,
        card.fib_trading_horizon,
        card.short_context_input_status,
        card.short_context_coverage_status,
        card.short_context_display_state,
        _breath_curve_phase_marker_text(card.breath_curve),
        _breath_curve_current_checkpoint_text(card.breath_curve),
        str((card.breath_curve or {}).get("phase_offset_band") or ""),
    )
    tokens: list[str] = []
    for part in parts:
        if not part:
            continue
        token = SEARCH_TEXT_TOKEN_OVERRIDES.get(part, part)
        if token:
            tokens.append(token.lower())
    return " ".join(tokens)


def filter_cards_for_view(cards: list[ProfitPlanCard], *, mode: str, query: str) -> list[ProfitPlanCard]:
    """Return cards matching search text.

    The mode argument is retained for caller compatibility only. Profit Plan
    visibility is controlled by asset selection, not by a "relevant" gate.
    """
    _ = mode
    query_norm = query.strip().lower()
    out: list[ProfitPlanCard] = []
    for card in cards:
        if query_norm and query_norm not in build_card_search_text(card):
            continue
        out.append(card)
    return out


def _nearest_distance(card: ProfitPlanCard) -> Decimal | None:
    """Return the smallest absolute distance to any actionable level (target or reload)."""
    candidates: list[Decimal] = []
    if card.distance_to_target_pct is not None:
        candidates.append(abs(card.distance_to_target_pct))
    if card.distance_to_reload_pct is not None:
        candidates.append(abs(card.distance_to_reload_pct))
    return min(candidates) if candidates else None


def _most_recent_event_ts(card: ProfitPlanCard) -> datetime | None:
    """Return the latest first_cross_ts_utc among PASSED/COMPLETED target levels."""
    timestamps = [
        level.first_cross_ts_utc
        for level in card.target_level_statuses
        if level.first_cross_ts_utc is not None
        and level.lifecycle_state in {"PASSED", "COMPLETED", "HISTORICAL"}
    ]
    return max(timestamps) if timestamps else None


def sort_cards_two_timeline(cards: list[ProfitPlanCard]) -> list[ProfitPlanCard]:
    """
    Sort cards into two timelines followed by a residual group:

    1. Upcoming Events — has a nearest_distance; sorted by ascending absolute distance.
    2. Recent/Passed — no upcoming distance but has event timestamp; sorted by descending ts.
    3. Minimal Context — no usable distance or timestamp.
    """
    upcoming: list[tuple[Decimal, ProfitPlanCard]] = []
    recent: list[tuple[datetime, ProfitPlanCard]] = []
    minimal: list[ProfitPlanCard] = []

    for card in cards:
        dist = _nearest_distance(card)
        if dist is not None:
            upcoming.append((dist, card))
        else:
            ts = _most_recent_event_ts(card)
            if ts is not None:
                recent.append((ts, card))
            else:
                minimal.append(card)

    sorted_upcoming = [c for _, c in sorted(upcoming, key=lambda x: x[0])]
    sorted_recent = [c for _, c in sorted(recent, key=lambda x: x[0], reverse=True)]
    return sorted_upcoming + sorted_recent + minimal




def _order_ladder_sort_priority(ladder_states: tuple[str, ...]) -> int:
    states = set(ladder_states)
    if "LADDER_MISSING" in states:
        return 0
    if "LADDER_INCOMPLETE" in states:
        return 1
    if "STALE_ORDERS_PRESENT" in states:
        return 2
    if "ORDER_DATA_UNAVAILABLE" in states:
        return 3
    if "LADDER_ARMED" in states:
        return 5
    if "LADDER_NOT_REQUIRED" in states:
        return 7
    return 8


def _event_sort_priority(card: ProfitPlanCard) -> int:
    if card.primary_state == "INVALIDATION_NEAR":
        return 0
    if card.primary_state == "RELOAD_ZONE_APPROACHING":
        return 1
    if card.event_state == "MAP_EXPIRED" or card.primary_state in {"MAP_RECOMPUTE_NEEDED", "POST_EXTENSION_PULLBACK"}:
        return 2
    if card.primary_state == "TAKE_PROFIT_WAITING" or card.event_state == "TARGET_APPROACHING":
        return 3
    if card.event_state == "CONTEXT_UNAVAILABLE":
        return 6
    return 5


def _setup_sort_priority(card: ProfitPlanCard) -> int:
    order = {
        "REENTRY_SETUP": 0,
        "EXTENSION_SETUP": 1,
        "BREAKOUT_SETUP": 2,
        "RANGE_SETUP": 3,
        "MAP_COMPLETED": 4,
        "MINIMAL_CONTEXT": 8,
    }
    return order.get(card.setup_state, 9)


_PRESENTATION_MODE_SORT_RANK: dict[str, int] = {
    CARD_MODE_POSITION_HELD: 0,
    CARD_MODE_ACCOUNT_ORDER_ONLY: 1,
    CARD_MODE_ACCOUNT_PLAN_ENABLED: 2,
    CARD_MODE_WATCH_ONLY_ROTATION: 3,
    CARD_MODE_MARKET_SELECTED: 4,
}


def _card_action_sort_value(card: ProfitPlanCard) -> int:
    if not card.is_relevant:
        return 999
    return (_order_ladder_sort_priority(card.ladder_states) * 100) + (_event_sort_priority(card) * 10)


def sort_cards_action_priority(cards: list[ProfitPlanCard]) -> list[ProfitPlanCard]:
    """Default UI sort: portfolio position cards first, then watch-only rotation cards last."""
    def key(card: ProfitPlanCard) -> tuple[int, bool, int, Decimal, Decimal, str]:
        dist = _nearest_distance(card)
        # Actionable PPP (not Planning PPP) is the only PPP allowed to influence ranking.
        ppp = _actionable_ppp(card)
        return (
            _PRESENTATION_MODE_SORT_RANK.get(card.presentation_mode, 99),
            not card.is_relevant,
            _card_action_sort_value(card),
            dist if dist is not None else Decimal("999999"),
            -(ppp if ppp is not None else Decimal("-999999")),
            card.symbol,
        )

    return sorted(cards, key=key)


def _presentation_mode_sort_rank(card: ProfitPlanCard) -> int:
    return _PRESENTATION_MODE_SORT_RANK.get(card.presentation_mode, 99)




_FILTER_LABEL_OVERRIDES: dict[str, str] = {
    "TAKE_PROFIT_NEAR": "Take profit near",
    "REBUY_ZONE_NEAR": "Rebuy zone near",
    "WAIT_FOR_NEW_MAP": "Wait for new map",
    "NAVIGATION_ONLY": "Navigation only",
    "MANUAL_REVIEW": "Manual review",
    "BREAKOUT_WATCH": "Breakout watch",
    "FIX LADDER": "Fix ladder",
    "TAKE PROFIT NEAR": "Take profit near",
    "WAIT FOR NEW MAP": "Wait for new map",
    "NAVIGATION ONLY": "Navigation only",
    "MANUAL REVIEW": "Manual review",
    "MAP EXPIRED": "Map expired",
    "BETWEEN LEVELS": "Between levels",
    "REVIEW CONTEXT": "Review context",
    "MAP SWITCH REVIEW": "Map switch review",
    "WAIT FOR ENTRY": "Wait for entry",
    "REENTRY_SETUP": "Re-entry setup",
    "EXTENSION_SETUP": "Extension setup",
    "BREAKOUT_SETUP": "Breakout setup",
    "RANGE_SETUP": "Range setup",
    "MAP_COMPLETED": "Map completed",
    "MINIMAL_CONTEXT": "Minimal context",
    CARD_ACTIONABILITY_ACTIVE: "Active trade setup",
    CARD_ACTIONABILITY_NAVIGATION_ONLY: "Navigation only",
    CARD_ACTIONABILITY_HISTORICAL_REFERENCE: "Historical reference",
    CARD_ACTIONABILITY_NEEDS_RECOMPUTE: "Needs recompute",
    CARD_ACTIONABILITY_INVALIDATED: "Invalidated",
    CARD_ACTIONABILITY_CONTEXT_UNAVAILABLE: "Context unavailable",
}


@dataclass(frozen=True)
class _FilterOption:
    value: str
    label: str


def _filter_value_from_label(label: str) -> str:
    raw = str(label or "").strip().lower()
    out: list[str] = []
    previous_was_separator = False
    for ch in raw:
        if ch.isalnum():
            out.append(ch)
            previous_was_separator = False
        elif not previous_was_separator:
            out.append("_")
            previous_was_separator = True
    return "".join(out).strip("_")


def _filter_display_label(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw in _FILTER_LABEL_OVERRIDES:
        return _FILTER_LABEL_OVERRIDES[raw]
    if raw in STATE_LABELS:
        return STATE_LABELS[raw]
    return raw.replace("_", " ").title()


def _collect_filter_options(items: list[tuple[str, str]]) -> tuple[_FilterOption, ...]:
    labels_by_value: dict[str, str] = {}
    for value, label in items:
        if not value:
            continue
        labels_by_value.setdefault(value, label)
    return tuple(
        _FilterOption(value=value, label=labels_by_value[value])
        for value in sorted(labels_by_value, key=lambda key: labels_by_value[key].lower())
    )


_LADDER_ATTENTION_STATES: frozenset[str] = frozenset({
    "LADDER_MISSING",
    "LADDER_INCOMPLETE",
    "STALE_ORDERS_PRESENT",
})

# Strong workflow overrides — the single primary action for the card.
_STRONG_OVERRIDE_ACTIONS: frozenset[str] = frozenset({
    "FIX LADDER",
    "REVIEW CONTEXT",
    "MAP SWITCH REVIEW",
    "WAIT FOR ENTRY",
})

# Weak no-op market states that must not coexist with a strong override action.
_WEAK_NOOP_PRIMARY_STATES: frozenset[str] = frozenset({
    "DO_NOTHING",
    "INSUFFICIENT_DATA",
})


def _card_has_loaded_entry(card: ProfitPlanCard) -> bool:
    return bool(card.buy_zone or card.reload_reentry_zone)


def _ladder_needs_attention(card: ProfitPlanCard) -> bool:
    return any(state in _LADDER_ATTENTION_STATES for state in card.ladder_states)


def _parse_canonical_utc_timestamp(value: str) -> datetime | None:
    """Parse the runner's canonical ``...Z`` UTC timestamp without guessing."""
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    if parsed.tzinfo != UTC:
        return None
    canonical = parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return parsed if canonical == value else None


def _order_snapshot_authority_status(evidence: CardEvidence) -> str:
    """Return FRESH, STALE, or DATA_UNAVAILABLE using deterministic evidence.

    Freshness is evaluated against the card generation timestamp, never the
    renderer's wall clock.
    """
    snapshot_ts = _parse_canonical_utc_timestamp(evidence.order_snapshot_ts_utc)
    generation_ts = _parse_canonical_utc_timestamp(evidence.generation_ts_utc)
    if snapshot_ts is None or generation_ts is None:
        return DATA_UNAVAILABLE if evidence.order_snapshot_ts_utc == DATA_UNAVAILABLE else "STALE"
    if snapshot_ts - generation_ts > ORDER_SNAPSHOT_MAX_FUTURE_SKEW:
        return "STALE"
    if generation_ts - snapshot_ts > ORDER_SNAPSHOT_FRESH_AFTER:
        return "STALE"
    return "FRESH"


def _fix_ladder_allowed(card: ProfitPlanCard) -> bool:
    """Reporting-only guard: FIX LADDER may claim a broken account ladder only
    when the evidence available to the renderer proves it is safe.

    Fails closed whenever native scope-status, price freshness, current map
    identity, per-level truth, rollover verification or a loaded entry is
    missing. Account/order freshness requires both a FRESH status and canonical
    snapshot/generation timestamps.
    """
    if card.presentation_mode in _NO_ACCOUNT_STATE_MODES:
        return False
    if card.actionability_state != CARD_ACTIONABILITY_ACTIVE:
        return False
    if not _price_is_fresh_enough(card):
        return False
    # Placeholder / stale / unavailable account+order truth suppresses account-specific
    # repair claims (the wallet/position/order panels are placeholders until Lane A).
    if str(card.evidence.account_order_snapshot_status or "").strip().upper() != "FRESH":
        return False
    if _order_snapshot_authority_status(card.evidence) != "FRESH":
        return False
    if _native_map_status(card) != "AVAILABLE":
        return False
    if _is_unavailable(card.evidence.map_cycle_id):
        return False
    if str(card.evidence.selected_map_tier or "").strip().upper() != "CURRENT_ACTIVE_MAP":
        return False
    if _map_lifecycle_blocks_action(card):
        return False
    if _map_switch_review_required(card):
        return False
    # A target without a loaded entry is not a broken ladder — it is wait-for-entry.
    if not _card_has_loaded_entry(card) and card.target_exit_zone:
        return False
    # Only an activated setup can have a broken ladder to repair. Without proof the
    # entry was activated in the current cycle, this is wait-for-entry, not a fix.
    if not _entry_activation_proof(card):
        return False
    if not _ladder_needs_attention(card):
        return False
    return True


def _effective_workflow_action(card: ProfitPlanCard) -> str:
    """
    Single source of truth for the rendered workflow action.

    Used by:
    - card action header
    - data-filter-action
    - data-filter-action-label
    - canonical Action filter counts
    - selector action label

    Reference-only/historical remains actionability context, not a workflow action.
    Action claims fail closed: FIX LADDER only appears when evidence proves it.
    """
    if not _canonical_native_map_truth_available(card.evidence):
        if card.actionability_state == CARD_ACTIONABILITY_NAVIGATION_ONLY:
            # Issue #223: canonical 4h navigation context (no native lifecycle truth)
            # is a truthful read-only reference, not a "review" prompt -- it must
            # never be collapsed into the generic REVIEW CONTEXT action label.
            return _ACTION_DISPLAY_MAP.get(
                card.action_label,
                card.action_label.replace("_", " "),
            )
        return "REVIEW CONTEXT"

    if card.actionability_state == CARD_ACTIONABILITY_CONTEXT_UNAVAILABLE:
        return "REVIEW CONTEXT"

    if card.actionability_state == CARD_ACTIONABILITY_INVALIDATED:
        return "INVALIDATED"

    if _map_switch_review_required(card):
        return "MAP SWITCH REVIEW"

    if _fix_ladder_allowed(card):
        return "FIX LADDER"

    # Ladder attention exists but the fix claim is not proven safe: fail closed.
    if (
        card.presentation_mode not in _NO_ACCOUNT_STATE_MODES
        and card.actionability_state == CARD_ACTIONABILITY_ACTIVE
        and _ladder_needs_attention(card)
    ):
        # No loaded entry, or no proof the entry was activated → wait for entry/reclaim.
        if not _card_has_loaded_entry(card) and card.target_exit_zone:
            return "WAIT FOR ENTRY"
        if not _entry_activation_proof(card):
            return "WAIT FOR ENTRY"
        return "REVIEW CONTEXT"

    return _ACTION_DISPLAY_MAP.get(
        card.action_label,
        card.action_label.replace("_", " "),
    )


# ---------------------------------------------------------------------------
# P1 — Evidence-card semantic normalization
#
# One normalized row per independent authority. No row infers its status from
# another row: a DATA_UNAVAILABLE projection must never be paired with a
# confirmed CURRENT_ACTIVE_MAP current-map-selection status. Reporting/display
# only — does not alter the fail-closed action resolver above.
# ---------------------------------------------------------------------------

def _action_gate_blocking_reason_codes(card: ProfitPlanCard) -> tuple[str, ...]:
    """Read-only explanatory reason codes for the action-gate evidence row.

    Mirrors the existing fail-closed checks (_fix_ladder_allowed /
    _map_switch_review_required / _effective_workflow_action, PR #75) without
    altering their precedence or outcome. Returns the complete, untruncated set
    of reasons the action gate is not ACTIONABLE/FIX_LADDER.
    """
    if card.presentation_mode in _NO_ACCOUNT_STATE_MODES:
        return ()
    if card.actionability_state == CARD_ACTIONABILITY_CONTEXT_UNAVAILABLE:
        return ("NATIVE_MAP_DATA_UNAVAILABLE", "NON_CANONICAL_REFERENCE_ONLY")
    if card.actionability_state == CARD_ACTIONABILITY_INVALIDATED:
        return ("CONTEXT_INVALIDATED",)
    if _map_switch_review_required(card):
        codes = ["MAP_SWITCH_UNVERIFIED"]
        if _native_map_status(card) != "AVAILABLE":
            codes.append("NATIVE_MAP_DATA_UNAVAILABLE")
        return tuple(codes)
    if _fix_ladder_allowed(card):
        return ()
    if not (card.actionability_state == CARD_ACTIONABILITY_ACTIVE and _ladder_needs_attention(card)):
        return ()
    codes: list[str] = []
    if not _price_is_fresh_enough(card):
        codes.append("STALE_CURRENT_PRICE")
    if str(card.evidence.account_order_snapshot_status or "").strip().upper() != "FRESH":
        codes.append("ACCOUNT_ORDER_DATA_UNAVAILABLE")
    if _order_snapshot_authority_status(card.evidence) != "FRESH":
        codes.append("STALE_OR_UNAVAILABLE_ORDER_SNAPSHOT")
    if _native_map_status(card) != "AVAILABLE":
        codes.append("NATIVE_MAP_DATA_UNAVAILABLE")
    if _is_unavailable(card.evidence.map_cycle_id):
        codes.append("MAP_CYCLE_UNAVAILABLE")
    if str(card.evidence.selected_map_tier or "").strip().upper() != "CURRENT_ACTIVE_MAP":
        codes.append("MAP_TIER_NOT_CONFIRMED_CURRENT")
    if _map_lifecycle_blocks_action(card):
        codes.append("MAP_LIFECYCLE_BLOCKS_ACTION")
    if not _card_has_loaded_entry(card) and card.target_exit_zone:
        codes.append("ENTRY_LEVELS_UNAVAILABLE")
    if not _entry_activation_proof(card):
        codes.append("ENTRY_ACTIVATION_UNPROVEN")
    return tuple(codes)


def _evidence_observed_ts(value: str | None) -> str | None:
    return value if value is not None and not _is_unavailable(value) else None


def _projection_status_row(card: ProfitPlanCard) -> EvidenceRow:
    status = _native_map_status(card)
    reason_codes = () if status == "AVAILABLE" else ("NATIVE_MAP_DATA_UNAVAILABLE",)
    return EvidenceRow(
        key="projection_status",
        label="Projection status",
        authority="Native scope-status projection (Lane B)",
        status=status,
        reason_codes=reason_codes,
    )


def _current_map_selection_row(card: ProfitPlanCard) -> EvidenceRow:
    raw_tier = str(card.evidence.selected_map_tier or "").strip().upper()
    authority = "Selected-map tier (map-selection authority)"
    if raw_tier in _UNAVAILABLE_TOKENS:
        return EvidenceRow(
            key="current_map_selection",
            label="Current map selection",
            authority=authority,
            status="UNKNOWN",
            reason_codes=("MAP_SELECTION_UNAVAILABLE",),
        )
    if _native_map_status(card) == "AVAILABLE":
        return EvidenceRow(
            key="current_map_selection",
            label="Current map selection",
            authority=authority,
            status=raw_tier,
            reason_codes=(),
        )
    # Native projection truth is unavailable: a reported tier must never be shown
    # as confirmed CURRENT_ACTIVE_MAP truth. Fail closed to an explicit fallback
    # status while preserving the underlying reported value as a reason code.
    return EvidenceRow(
        key="current_map_selection",
        label="Current map selection",
        authority=authority,
        status="REPORTING_FALLBACK",
        reason_codes=("NATIVE_MAP_DATA_UNAVAILABLE", f"REPORTED_TIER_{raw_tier}"),
    )


def _map_lifecycle_row(card: ProfitPlanCard) -> EvidenceRow:
    if not _canonical_native_map_truth_available(card.evidence):
        return EvidenceRow(
            key="map_lifecycle",
            label="Map lifecycle",
            authority="Canonical native map lifecycle authority (Lane B)",
            status=DATA_UNAVAILABLE,
            reason_codes=("NATIVE_MAP_DATA_UNAVAILABLE", "TRANSIENT_LIFECYCLE_NOT_CANONICAL"),
        )
    status = str(card.evidence.lifecycle_state or "").strip().upper() or DATA_UNAVAILABLE
    if status in _UNAVAILABLE_TOKENS:
        status = DATA_UNAVAILABLE
    reason_codes = () if status != DATA_UNAVAILABLE else ("MAP_LIFECYCLE_UNAVAILABLE",)
    return EvidenceRow(
        key="map_lifecycle",
        label="Map lifecycle",
        authority="Map-cycle lifecycle authority",
        status=status,
        reason_codes=reason_codes,
    )


_PER_LEVEL_COMPLETED_STATES: frozenset[str] = frozenset({"COMPLETED", "REACHED_FILLED"})
_PER_LEVEL_HISTORICAL_STATES: frozenset[str] = frozenset({"PASSED", "COMPLETED", "REACHED_FILLED"})


def _per_level_status_row(card: ProfitPlanCard) -> EvidenceRow:
    # Locally derived from reporting-side target-level history, not a native Lane B0
    # per-level authority. Always disclosed via reason code so this row is never
    # mistaken for canonical native level-status evidence.
    authority = "Reporting reference levels (not native canonical)"
    if not _canonical_native_map_truth_available(card.evidence):
        return EvidenceRow(
            key="per_level_status",
            label="Per-level status",
            authority=authority,
            status="NON_CANONICAL_REFERENCE" if card.sell_zone or card.buy_zone else DATA_UNAVAILABLE,
            reason_codes=("NATIVE_LEVEL_STATUS_UNAVAILABLE", "TRANSIENT_LEVELS_REFERENCE_ONLY"),
        )
    statuses = card.target_level_statuses
    if not statuses:
        return EvidenceRow(
            key="per_level_status",
            label="Per-level status",
            authority=authority,
            status=DATA_UNAVAILABLE,
            reason_codes=("LEVEL_STATUS_UNAVAILABLE",),
        )
    if any(level.is_active_target for level in statuses):
        status = "CURRENT"
    elif all(level.lifecycle_state in _PER_LEVEL_COMPLETED_STATES for level in statuses):
        status = "COMPLETED"
    elif all(level.lifecycle_state in _PER_LEVEL_HISTORICAL_STATES for level in statuses):
        status = "HISTORICAL"
    else:
        status = "CURRENT"
    return EvidenceRow(
        key="per_level_status",
        label="Per-level status",
        authority=authority,
        status=status,
        reason_codes=("REPORTING_DERIVED_NOT_NATIVE_CANONICAL",),
    )


def _price_snapshot_row(card: ProfitPlanCard) -> EvidenceRow:
    if card.current_price is None or card.current_price_status == "MISSING_CURRENT_PRICE":
        status = "MISSING"
    elif card.current_price_status == "STALE_CURRENT_PRICE":
        status = "STALE"
    else:
        status = "FRESH"
    reason_codes = () if status == "FRESH" else ("STALE_OR_MISSING_CURRENT_PRICE",)
    return EvidenceRow(
        key="price_snapshot",
        label="Price snapshot",
        authority="Current-price snapshot",
        status=status,
        observed_ts=_evidence_observed_ts(card.evidence.price_ts_utc),
        reason_codes=reason_codes,
    )


def _wallet_snapshot_row(card: ProfitPlanCard) -> EvidenceRow:
    status = str(card.evidence.wallet_snapshot_status or "").strip().upper() or DATA_UNAVAILABLE
    reason_codes = () if status == "FRESH" else (
        ("WALLET_DATA_UNAVAILABLE",) if status == DATA_UNAVAILABLE else ("STALE_WALLET_DATA",)
    )
    return EvidenceRow(
        key="wallet_snapshot",
        label="Wallet snapshot",
        authority="Wallet balance snapshot (Lane A)",
        status=status,
        reason_codes=reason_codes,
    )


def _position_snapshot_row(card: ProfitPlanCard) -> EvidenceRow:
    status = str(card.evidence.position_snapshot_status or "").strip().upper() or DATA_UNAVAILABLE
    reason_codes = () if status == "FRESH" else (
        ("POSITION_DATA_UNAVAILABLE",) if status == DATA_UNAVAILABLE else ("STALE_POSITION_DATA",)
    )
    return EvidenceRow(
        key="position_snapshot",
        label="Position snapshot",
        authority="Position snapshot (Lane A)",
        status=status,
        reason_codes=reason_codes,
    )


def _open_order_snapshot_row(card: ProfitPlanCard) -> EvidenceRow:
    status = _order_snapshot_authority_status(card.evidence)
    reason_codes = () if status == "FRESH" else (
        ("STALE_OPEN_ORDER_SNAPSHOT",) if status == "STALE" else ("OPEN_ORDER_DATA_UNAVAILABLE",)
    )
    return EvidenceRow(
        key="open_order_snapshot",
        label="Open-order snapshot",
        authority="Open-order snapshot (Lane A)",
        status=status,
        observed_ts=_evidence_observed_ts(card.evidence.order_snapshot_ts_utc),
        reason_codes=reason_codes,
    )


def _dashboard_render_row(card: ProfitPlanCard) -> EvidenceRow:
    return EvidenceRow(
        key="dashboard_render",
        label="Dashboard render",
        authority="Dashboard renderer (this process, read-only)",
        status="RENDERED",
        observed_ts=_evidence_observed_ts(card.evidence.generation_ts_utc),
        reason_codes=(),
    )


def _action_gate_row(card: ProfitPlanCard) -> EvidenceRow:
    # Authority description is operator-facing text; internal implementation
    # references (e.g. PR numbers) must not appear here. See PR #75 in git
    # history for the fail-closed precedence rule this row displays.
    authority = "Action-gate resolver (fail-closed precedence)"
    if card.presentation_mode in _NO_ACCOUNT_STATE_MODES:
        return EvidenceRow(
            key="action_gate",
            label="Action gate",
            authority=authority,
            status="NOT_APPLICABLE",
            reason_codes=(),
        )
    status = _effective_workflow_action(card).strip().upper().replace(" ", "_")
    return EvidenceRow(
        key="action_gate",
        label="Action gate",
        authority=authority,
        status=status,
        reason_codes=_action_gate_blocking_reason_codes(card),
    )


def build_card_evidence_rows(card: ProfitPlanCard) -> tuple[EvidenceRow, ...]:
    """Single source of truth for normalized evidence authority rows.

    Produces the ten required independent authority rows in fixed order. The
    same tuple must drive card HTML, sidebar/detail HTML, and the JSON
    snapshot — no renderer may re-derive a status independently.
    """
    return (
        _projection_status_row(card),
        _current_map_selection_row(card),
        _map_lifecycle_row(card),
        _per_level_status_row(card),
        _price_snapshot_row(card),
        _wallet_snapshot_row(card),
        _position_snapshot_row(card),
        _open_order_snapshot_row(card),
        _dashboard_render_row(card),
        _action_gate_row(card),
    )


def evidence_rows_to_json(rows: tuple[EvidenceRow, ...]) -> list[dict[str, Any]]:
    return [
        {
            "key": row.key,
            "label": row.label,
            "authority": row.authority,
            "status": row.status,
            "observed_ts": row.observed_ts,
            "reason_codes": list(row.reason_codes),
        }
        for row in rows
    ]


def _card_displayed_action_for_filter(card: ProfitPlanCard) -> str:
    return _effective_workflow_action(card)


def _card_filter_action_option(card: ProfitPlanCard) -> tuple[str, str]:
    if card.presentation_mode in _NO_ACCOUNT_STATE_MODES:
        return "", ""
    label = _filter_display_label(_effective_workflow_action(card))
    return _filter_value_from_label(label), label


def _workflow_sort_bucket(card: ProfitPlanCard) -> int:
    """
    Explicit workflow bucket used by PPP sort (v2 ordering):

      0 actionable setups with a valid Actionable PPP
      1 waiting-for-entry / waiting-for-reclaim (active setup, no Actionable PPP)
      2 map-switch review (unverified rollover)
      3 needs recompute / map expired / post-extension
      4 navigation-only / historical / completed
      8 no native short context / minimal
      9 not relevant

    Planning PPP (theoretical map potential) must never promote a card into an
    earlier bucket.
    """
    if not card.is_relevant:
        return 9
    if _map_switch_review_required(card):
        return 2
    active_setup = (
        card.actionability_state == CARD_ACTIONABILITY_ACTIVE
        and card.setup_state in {"REENTRY_SETUP", "EXTENSION_SETUP", "BREAKOUT_SETUP", "RANGE_SETUP"}
    )
    if active_setup:
        return 0 if _actionable_ppp(card) is not None else 1
    if (
        card.actionability_state == CARD_ACTIONABILITY_NEEDS_RECOMPUTE
        or card.action_label == "WAIT_FOR_NEW_MAP"
        or card.primary_state in {"MAP_RECOMPUTE_NEEDED", "POST_EXTENSION_PULLBACK"}
    ):
        return 3
    if (
        card.actionability_state in {CARD_ACTIONABILITY_NAVIGATION_ONLY, CARD_ACTIONABILITY_HISTORICAL_REFERENCE}
        or card.setup_state == "MAP_COMPLETED"
        or card.action_label == "NAVIGATION_ONLY"
    ):
        return 4
    if card.short_context_display_state != "HAS_NATIVE_SHORT_FIB_CONTEXT":
        return 8
    return 5


def build_profit_plan_filter_reference_lists(cards: list[ProfitPlanCard]) -> dict[str, tuple[_FilterOption, ...]]:
    """Build filter reference lists from the rendered card set only."""
    action_items: list[tuple[str, str]] = []
    setup_items: list[tuple[str, str]] = []
    primary_items: list[tuple[str, str]] = []
    order_items: list[tuple[str, str]] = []

    for card in cards:
        action_items.append(_card_filter_action_option(card))
        setup_items.append((card.setup_state, _filter_display_label(card.setup_state)))
        primary_items.append((card.primary_state, _filter_display_label(card.primary_state)))
        if card.presentation_mode in _NO_ACCOUNT_STATE_MODES:
            order_items.append(("not_applicable", "Not applicable"))
        else:
            order_status = _order_ladder_display_status(card.ladder_states)
            order_items.append((_filter_value_from_label(order_status), _filter_display_label(order_status)))

    return {
        "action": _collect_filter_options(action_items),
        "setup": _collect_filter_options(setup_items),
        "primary": _collect_filter_options(primary_items),
        "orders": _collect_filter_options(order_items),
    }


def _filter_select_options(options: tuple[_FilterOption, ...]) -> str:
    return "".join(
        f"<option value='{esc(option.value)}'>{esc(option.label)}</option>"
        for option in options
    )


def _canonical_action_filter_options_html(cards: list[ProfitPlanCard]) -> str:
    """Render action filter options using the canonical list, always in fixed order.

    Canonical options are always visible with their count (may be zero).
    Non-canonical action values found in rendered cards are appended after.
    """
    canonical_values = {value for value, _ in CANONICAL_ACTION_FILTER}
    counts: dict[str, int] = {}
    extra: dict[str, str] = {}

    for card in cards:
        value, label = _card_filter_action_option(card)
        if not value:
            continue
        counts[value] = counts.get(value, 0) + 1
        if value not in canonical_values:
            extra.setdefault(value, label)

    parts: list[str] = []
    for value, label in CANONICAL_ACTION_FILTER:
        count = counts.get(value, 0)
        parts.append(f"<option value='{esc(value)}'>{esc(label)} ({count})</option>")
    for value in sorted(extra, key=lambda v: extra[v].lower()):
        count = counts.get(value, 0)
        label = extra[value]
        parts.append(f"<option value='{esc(value)}'>{esc(label)} ({count})</option>")
    return "".join(parts)


def _unique_levels(levels: tuple[Decimal | None, ...]) -> tuple[Decimal, ...]:
    seen: set[Decimal] = set()
    out: list[Decimal] = []
    for level in levels:
        if level is None:
            continue
        if level in seen:
            continue
        seen.add(level)
        out.append(level)
    return tuple(sorted(out))


def _classify_scenario(
    current_price: Decimal | None,
    fib_ext: FibExtContext | None,
    reentry: ReentryContext | None,
    profile_classification: str | None,
    preferred_retrace_level: str | None,
) -> tuple[str, str, str, tuple[Decimal, ...], tuple[Decimal, ...], Decimal | None, tuple[str, ...]]:
    """
    Returns: (scenario_type, action_label, timeframe_label,
              buy_zone, sell_zone, invalidation_level, reasons)
    """
    if fib_ext is not None:
        band = fib_ext.price_band

        if band == "ABOVE_2000":
            return (
                "EXTENSION_RUNNER",
                "FAR_MOONBAG_ONLY",
                "1d swing",
                (),
                (fib_ext.ext_2_000,),
                fib_ext.ext_1_618,
                (
                    "Price has passed the 2.000 extension — well above all main targets.",
                    "Only existing moonbag sell orders are relevant here.",
                    "No new buys at this level — wait for a significant pullback.",
                ),
            )

        if band == "BETWEEN_1618_2000":
            return (
                "EXTENSION_RUNNER",
                "TAKE_PROFIT_NEAR",
                "4h bounce",
                (),
                (fib_ext.ext_1_618, fib_ext.ext_2_000),
                fib_ext.ext_1_272,
                (
                    f"Price between 1.618 ({_fmt_p(fib_ext.ext_1_618)}) and 2.000 ({_fmt_p(fib_ext.ext_2_000)}) extension.",
                    "Primary sell zone — scale out of positions here.",
                    "Invalidates below 1.272 extension.",
                ),
            )

        if band == "BETWEEN_1272_1618":
            return (
                "EXTENSION_RUNNER",
                "TAKE_PROFIT_NEAR",
                "4h bounce",
                (),
                (fib_ext.ext_1_272, fib_ext.ext_1_618),
                fib_ext.ext_1_272,
                (
                    f"First sell level at 1.272 extension ({_fmt_p(fib_ext.ext_1_272)}) is already in play.",
                    f"Main target at 1.618 extension ({_fmt_p(fib_ext.ext_1_618)}).",
                    f"Momentum supports continuation toward the target / sell zone at {_fmt_p(fib_ext.ext_1_618)}.",
                ),
            )

        if fib_ext.retesting_breakout_gate:
            return (
                "BREAKOUT_RETEST",
                "BUY_DIP",
                "4h bounce",
                (fib_ext.breakout_gate,),
                (fib_ext.ext_1_272, fib_ext.ext_1_618),
                fib_ext.breakout_gate * Decimal("0.97"),
                (
                    f"Price retesting the breakout gate ({_fmt_p(fib_ext.breakout_gate)}) — classic re-entry.",
                    f"Target: 1.272 extension at {_fmt_p(fib_ext.ext_1_272)} then 1.618.",
                    "Invalidates on a close below the breakout gate.",
                ),
            )

        if fib_ext.ext_1_272_touched_and_rejected:
            buy_zone: tuple[Decimal, ...]
            reasons_list: list[str]
            if reentry is not None:
                buy_zone = (reentry.r382_price, reentry.r500_price)
                reasons_list = [
                    f"1.272 extension touched then rejected — pullback now in progress.",
                    f"First-touch re-entry ({_fmt_p(reentry.r382_price)}) and main re-buy ({_fmt_p(reentry.r500_price)}) are the key ladder levels.",
                ]
                if reentry.missed_main_rebuy_by_pct is not None:
                    reasons_list.append(
                        f"Last dip missed the main re-buy by {_pct(reentry.missed_main_rebuy_by_pct)} — tighten the ladder."
                    )
                else:
                    reasons_list.append("Set limit orders at the re-entry levels to catch the next dip.")
            else:
                buy_zone = ()
                reasons_list = [
                    "1.272 extension touched then rejected — pullback now in progress.",
                    "Watch for re-entry near the breakout gate area.",
                    "No re-entry ladder loaded — add swing anchors to see levels.",
                ]
            return (
                "REENTRY_WAIT",
                "REBUY_ZONE_NEAR",
                "1d swing",
                buy_zone,
                (fib_ext.ext_1_272, fib_ext.ext_1_618),
                fib_ext.breakout_gate,
                tuple(reasons_list[:3]),
            )

        if band == "ABOVE_GATE_APPROACHING_1272":
            return (
                "EXTENSION_RUNNER",
                "BREAKOUT_WATCH",
                "4h bounce",
                (),
                (fib_ext.ext_1_272,),
                fib_ext.breakout_gate,
                (
                    f"Above the breakout gate — watching first target at 1.272 ({_fmt_p(fib_ext.ext_1_272)}).",
                    "No action needed yet — let the breakout play out.",
                    "Existing sell orders near 1.272 are well-positioned.",
                ),
            )

        # BELOW_BREAKOUT_GATE — fall through to reentry / range logic below
        if reentry is not None:
            return _classify_reentry(reentry, profile_classification, preferred_retrace_level, fib_ext)

    if reentry is not None:
        return _classify_reentry(reentry, profile_classification, preferred_retrace_level, None)

    # Profile-only path (no fib_ext, no reentry)
    if profile_classification == "RANGE_BOUNCE":
        return (
            "RANGE_BOUNCE",
            "WAIT",
            "4h bounce",
            (),
            (),
            None,
            (
                "Historical profile: price typically bounces in a range.",
                "No fib extension or re-entry context loaded.",
                "Add swing anchors to see specific levels.",
            ),
        )

    return (
        "NO_CLEAR_PLAN",
        "WAIT",
        "1d swing",
        (),
        (),
        None,
        (
            "No fib extension or re-entry context available for this symbol.",
            "Add HTF swing anchors to unlock scenario classification.",
        ),
    )


def _classify_reentry(
    reentry: ReentryContext,
    profile_classification: str | None,
    preferred_retrace_level: str | None,
    fib_ext: FibExtContext | None,
) -> tuple[str, str, str, tuple[Decimal, ...], tuple[Decimal, ...], Decimal | None, tuple[str, ...]]:
    sell_zone: tuple[Decimal, ...]
    if fib_ext is not None:
        sell_zone = (fib_ext.ext_1_272, fib_ext.ext_1_618)
    else:
        sell_zone = ()

    if reentry.missed_main_rebuy_by_pct is not None:
        miss_pct = _pct(reentry.missed_main_rebuy_by_pct)
        return (
            "REENTRY_WAIT",
            "REBUY_ZONE_NEAR",
            "1d swing",
            (reentry.r382_price, reentry.r500_price),
            sell_zone,
            reentry.r786_price,
            (
                f"Last dip missed the main re-buy by {miss_pct} — tighten the ladder.",
                f"First-touch level ({_fmt_p(reentry.r382_price)}) would have caught the dip.",
                f"Main re-buy is at {_fmt_p(reentry.r500_price)} — set a limit order there.",
            ),
        )

    if reentry.deepest_touched_label in ("retrace_0_500", "retrace_0_618", "retrace_0_786"):
        return (
            "REENTRY_WAIT",
            "BUY_DIP",
            "1d swing",
            (reentry.r500_price, reentry.r618_price),
            sell_zone,
            reentry.r786_price,
            (
                f"Price touched the re-entry zone — active re-buy opportunity.",
                f"Main re-buy level: {_fmt_p(reentry.r500_price)}.",
                f"Deep support: {_fmt_p(reentry.r618_price)}.",
            ),
        )

    if reentry.deepest_touched_label == "retrace_0_382":
        return (
            "REENTRY_WAIT",
            "REBUY_ZONE_NEAR",
            "1d swing",
            (reentry.r382_price, reentry.r500_price),
            sell_zone,
            reentry.r786_price,
            (
                f"First-touch re-entry ({_fmt_p(reentry.r382_price)}) reached.",
                f"Main re-buy at {_fmt_p(reentry.r500_price)} is the stronger support.",
                "Set limit orders at both levels to capture the range.",
            ),
        )

    # profile context
    if profile_classification == "DEEP_RETRACE":
        return (
            "RANGE_BOUNCE",
            "BUY_DIP",
            "1d swing",
            (reentry.r618_price, reentry.r786_price),
            sell_zone,
            reentry.r786_price,
            (
                "This asset historically retraces deeply before bouncing.",
                f"Deep re-buy zones: {_fmt_p(reentry.r618_price)} and {_fmt_p(reentry.r786_price)}.",
                "Shallow buys at 38.2% often stop out — wait for the deeper level.",
            ),
        )

    return (
        "REENTRY_WAIT",
        "WAIT",
        "1d swing",
        (reentry.r382_price, reentry.r500_price),
        sell_zone,
        reentry.r786_price,
        (
            f"Re-entry ladder loaded: first touch {_fmt_p(reentry.r382_price)}, main {_fmt_p(reentry.r500_price)}.",
            "Maintain the pre-planned re-entry ladder; no live wait signal is required.",
        ),
    )


# ---------------------------------------------------------------------------
# Order summary
# ---------------------------------------------------------------------------

def _near(price_a: Decimal, price_b: Decimal, tolerance_pct: Decimal) -> bool:
    if price_b <= 0:
        return False
    dist = abs(price_a - price_b) / price_b * Decimal("100")
    return dist <= tolerance_pct


def _level_match_stats(
    *,
    current_price: Decimal | None,
    level: Decimal,
    sell_orders: tuple[Any, ...],
) -> tuple[int, Decimal | None, Decimal | None, tuple[Any, ...]]:
    matching_orders = tuple(
        order
        for order in sell_orders
        if _near(order.limit_price, level, ORDER_MATCH_TOLERANCE_PCT)
    )
    if not matching_orders:
        return 0, None, None, ()
    nearest_price = min((order.limit_price for order in matching_orders), key=lambda price: abs(price - level))
    nearest_dist = _distance_to_level_pct(current_price, nearest_price)
    return len(matching_orders), nearest_price, nearest_dist, matching_orders


def _build_target_level_statuses(
    *,
    current_price: Decimal | None,
    target_levels: tuple[Decimal, ...],
    sell_orders: tuple[Any, ...],
    history_high_since_activation: Decimal | None,
    history_low_since_activation: Decimal | None,
    history_candles_since_activation: tuple[TargetHistoryCandle, ...] = (),
    filled_sell_levels: tuple[Decimal, ...] = (),
    completed_sell_levels: tuple[Decimal, ...] = (),
) -> tuple[tuple[TargetLevelStatus, ...], Decimal | None]:
    statuses: list[TargetLevelStatus] = []
    active_target: Decimal | None = None
    for level in target_levels:
        distance_pct = _distance_to_level_pct(current_price, level)
        matching_orders, nearest_open_sell_price, nearest_open_sell_distance_pct, matching_order_rows = _level_match_stats(
            current_price=current_price,
            level=level,
            sell_orders=sell_orders,
        )
        first_cross_ts_utc = next(
            (
                candle.close_ts_utc
                for candle in history_candles_since_activation
                if candle.high_price >= level
            ),
            None,
        )
        retest_context: str | None = None
        if any(_near(filled_level, level, ORDER_MATCH_TOLERANCE_PCT) for filled_level in completed_sell_levels):
            lifecycle_state = "COMPLETED"
            coverage_state = "COMPLETED"
            human_label = "completed sell level"
        elif any(_near(filled_level, level, ORDER_MATCH_TOLERANCE_PCT) for filled_level in filled_sell_levels):
            lifecycle_state = "REACHED_FILLED"
            coverage_state = "REACHED_FILLED"
            human_label = "filled sell level"
        elif current_price is None:
            lifecycle_state = "UPCOMING"
            coverage_state = "ORDER_ABSENT" if matching_orders == 0 else "ORDER_WAITING"
            human_label = "upcoming sell level"
        elif history_high_since_activation is not None and history_high_since_activation > level:
            lifecycle_state = "PASSED"
            if matching_orders > 0:
                if first_cross_ts_utc is not None and any(
                    getattr(order, "created_at_ms", None) is not None
                    and int(order.created_at_ms) <= int(first_cross_ts_utc.timestamp() * 1000)
                    for order in matching_order_rows
                ):
                    coverage_state = "MISSED_ORDER"
                    human_label = "missed sell level"
                else:
                    coverage_state = "OPEN_ORDER_AFTER_PASSED_LEVEL"
                    human_label = "open order after passed level"
            else:
                coverage_state = "PASSED_UNFILLED"
                human_label = "missed sell level"
            if current_price is not None and current_price < level:
                retest_context = "PULLBACK_BELOW_PASSED_LEVEL"
            elif current_price is not None and abs(current_price - level) <= (level * TARGET_LEVEL_NEAR_THRESHOLD_PCT / Decimal("100")):
                retest_context = "RETEST_AT_PASSED_LEVEL"
        elif first_cross_ts_utc is not None or (history_high_since_activation is not None and history_high_since_activation == level):
            lifecycle_state = "REACHED"
            coverage_state = "ORDER_WAITING" if matching_orders > 0 else "ORDER_ABSENT"
            human_label = "reached sell level"
        elif current_price == level:
            lifecycle_state = "REACHED"
            coverage_state = "ORDER_WAITING" if matching_orders > 0 else "ORDER_ABSENT"
            human_label = "reached sell level"
        elif current_price > level:
            lifecycle_state = "PASSED"
            if matching_orders > 0:
                coverage_state = "PASSED_OPEN_ORDER"
                human_label = "passed sell level with open order"
            else:
                coverage_state = "PASSED_UNFILLED"
                human_label = "missed sell level"
        elif distance_pct is not None and abs(distance_pct) <= TARGET_LEVEL_NEAR_THRESHOLD_PCT:
            lifecycle_state = "NEAR"
            coverage_state = "ORDER_WAITING" if matching_orders > 0 else "ORDER_ABSENT"
            human_label = "sell level near"
        else:
            lifecycle_state = "UPCOMING"
            coverage_state = "ORDER_WAITING" if matching_orders > 0 else "ORDER_ABSENT"
            human_label = "upcoming sell level"

        is_active_target = lifecycle_state in {"UPCOMING", "NEAR"} and active_target is None
        if is_active_target:
            active_target = level

        statuses.append(
            TargetLevelStatus(
                level=level,
                lifecycle_state=lifecycle_state,
                coverage_state=coverage_state,
                human_label=human_label,
                retest_context=retest_context,
                first_cross_ts_utc=first_cross_ts_utc,
                distance_pct=distance_pct,
                matching_open_sell_orders=matching_orders,
                nearest_open_sell_price=nearest_open_sell_price,
                nearest_open_sell_distance_pct=nearest_open_sell_distance_pct,
                is_active_target=is_active_target,
            )
        )
    return tuple(statuses), active_target


def _target_retest_notes(target_levels: tuple[TargetLevelStatus, ...]) -> tuple[str, ...]:
    notes: list[str] = []
    for level in target_levels:
        if level.retest_context == "PULLBACK_BELOW_PASSED_LEVEL":
            notes.append(f"Pullback below previously passed sell level {_fmt_p(level.level)}.")
        elif level.retest_context == "RETEST_AT_PASSED_LEVEL":
            notes.append(f"Retesting previously passed sell level {_fmt_p(level.level)}.")
    return tuple(notes)


def _completed_map_override(
    *,
    canonical_lifecycle_authoritative: bool,
    current_price: Decimal | None,
    sell_zone: tuple[Decimal, ...],
    target_level_statuses: tuple[TargetLevelStatus, ...],
    scenario_type: str,
    action_label: str,
    reasons: tuple[str, ...],
) -> tuple[bool, str, str, str | None, str, tuple[str, ...]]:
    if not canonical_lifecycle_authoritative:
        return False, scenario_type, action_label, None, "", reasons
    sell_level_statuses = tuple(level for level in target_level_statuses if level.level in sell_zone)
    if not sell_level_statuses:
        return False, scenario_type, action_label, None, "", reasons
    if not all(level.lifecycle_state in {"REACHED", "PASSED", "COMPLETED", "REACHED_FILLED"} for level in sell_level_statuses):
        return False, scenario_type, action_label, None, "", reasons
    max_sell_level = max(level.level for level in sell_level_statuses)
    if current_price is not None and current_price < max_sell_level:
        primary_state = "POST_EXTENSION_PULLBACK"
        attention_label = STATE_LABELS[primary_state]
        extra_reason = f"All mapped sell targets are historically passed. Current price is pulling back below final passed target {_fmt_p(max_sell_level)}."
    else:
        primary_state = "MAP_RECOMPUTE_NEEDED"
        attention_label = STATE_LABELS[primary_state]
        extra_reason = "All mapped sell targets are historically passed. Refresh the fib map before relying on a new active target."
    # Replace scenario reasons entirely — scenario classification reasons reference active targets
    # that no longer apply once all sell levels have been reached or passed.
    return (
        True,
        "MAP_COMPLETED",
        "WAIT_FOR_NEW_MAP",
        primary_state,
        attention_label,
        (extra_reason,),
    )


def build_order_summary(
    current_price: Decimal | None,
    buy_zone: tuple[Decimal, ...],
    sell_zone: tuple[Decimal, ...],
    buy_orders: tuple[Any, ...],
    sell_orders: tuple[Any, ...],
    *,
    target_level_statuses: tuple[TargetLevelStatus, ...] = (),
) -> ActiveOrderSummary:
    def _nearest_open_distance(orders: tuple[Any, ...]) -> Decimal | None:
        if current_price is None or current_price <= 0:
            return None
        distances = [
            (o.limit_price - current_price) / current_price * Decimal("100")
            for o in orders
        ]
        if not distances:
            return None
        return min(distances, key=lambda dist: abs(dist))

    def _max_open_distance(orders: tuple[Any, ...]) -> Decimal | None:
        if current_price is None or current_price <= 0:
            return None
        distances = [
            abs((o.limit_price - current_price) / current_price * Decimal("100"))
            for o in orders
        ]
        if not distances:
            return None
        return max(distances)

    def _nearest(orders: tuple[Any, ...], zone_prices: tuple[Decimal, ...]) -> tuple[int, Decimal | None, Decimal | None]:
        matching = 0
        nearest_price: Decimal | None = None
        nearest_dist: Decimal | None = None
        for o in orders:
            for zone_p in zone_prices:
                if _near(o.limit_price, zone_p, ORDER_MATCH_TOLERANCE_PCT):
                    matching += 1
                    if current_price is not None and current_price > 0:
                        dist = (o.limit_price - current_price) / current_price * Decimal("100")
                        if nearest_dist is None or abs(dist) < abs(nearest_dist):
                            nearest_dist = dist
                            nearest_price = o.limit_price
                    break
        return matching, nearest_price, nearest_dist

    buy_matching, nearest_buy, nearest_buy_dist = _nearest(buy_orders, buy_zone) if buy_zone else (0, None, None)
    sell_matching, nearest_sell, nearest_sell_dist = _nearest(sell_orders, sell_zone) if sell_zone else (0, None, None)

    missing: list[str] = []
    for zone_p in buy_zone:
        if current_price is not None and zone_p >= current_price:
            continue  # above-current buy reload is not an actionable missing entry
        if not any(_near(o.limit_price, zone_p, ORDER_MATCH_TOLERANCE_PCT) for o in buy_orders):
            missing.append(f"buy @ {_fmt_p(zone_p)}")
    if target_level_statuses:
        for level_status in target_level_statuses:
            if level_status.lifecycle_state in {"PASSED", "REACHED_FILLED", "COMPLETED"}:
                if level_status.coverage_state in {"PASSED_UNFILLED", "MISSED_ORDER"}:
                    missing.append(f"missed sell level @ {_fmt_p(level_status.level)}")
                continue
            if level_status.matching_open_sell_orders == 0:
                missing.append(f"sell @ {_fmt_p(level_status.level)}")
    else:
        for zone_p in sell_zone:
            if not any(_near(o.limit_price, zone_p, ORDER_MATCH_TOLERANCE_PCT) for o in sell_orders):
                missing.append(f"sell @ {_fmt_p(zone_p)}")

    open_buy_orders = len(buy_orders)
    open_sell_orders = len(sell_orders)
    open_parts: list[str] = []
    if open_buy_orders:
        open_parts.append(f"{open_buy_orders} buy open")
    if open_sell_orders:
        open_parts.append(f"{open_sell_orders} sell open")
    existing_open_orders_summary = " · ".join(open_parts) if open_parts else "No open orders linked"

    return ActiveOrderSummary(
        open_buy_orders=open_buy_orders,
        open_sell_orders=open_sell_orders,
        matching_buys=buy_matching,
        matching_sells=sell_matching,
        nearest_buy_price=nearest_buy,
        nearest_sell_price=nearest_sell,
        nearest_buy_distance_pct=nearest_buy_dist,
        nearest_sell_distance_pct=nearest_sell_dist,
        nearest_open_buy_distance_pct=_nearest_open_distance(buy_orders),
        nearest_open_sell_distance_pct=_nearest_open_distance(sell_orders),
        max_open_order_distance_pct=_max_open_distance(buy_orders + sell_orders),
        missing_suggested=tuple(missing),
        existing_open_orders_summary=existing_open_orders_summary,
    )


def _evaluate_display_states(
    *,
    current_price: Decimal | None,
    target_exit_zone: tuple[Decimal, ...],
    active_target: Decimal | None,
    target_level_statuses: tuple[TargetLevelStatus, ...],
    reload_reentry_zone: tuple[Decimal, ...],
    invalidation_risk_zone: Decimal | None,
    order_summary: ActiveOrderSummary,
) -> tuple[str, str | None, str, Decimal | None, Decimal | None, Decimal | None]:
    distance_to_target_pct = _distance_to_level_pct(current_price, active_target)
    distance_to_reload_pct = _distance_to_zone_pct(current_price, reload_reentry_zone)
    distance_to_invalidation_pct = _distance_to_level_pct(current_price, invalidation_risk_zone)

    if current_price is None or (
        not target_exit_zone and not reload_reentry_zone and invalidation_risk_zone is None
    ):
        primary_state = "INSUFFICIENT_DATA"
        return (
            primary_state,
            None,
            STATE_LABELS[primary_state],
            distance_to_target_pct,
            distance_to_reload_pct,
            distance_to_invalidation_pct,
        )

    state_candidates: list[str] = []

    # Primary event priority is market/risk first.
    # A waiting sell order is positive order coverage, not a reason to hide
    # nearby invalidation/reload work or missing ladder rows.
    if (
        distance_to_invalidation_pct is not None
        and abs(distance_to_invalidation_pct) <= INVALIDATION_NEAR_THRESHOLD_PCT
    ):
        state_candidates.append("INVALIDATION_NEAR")

    if (
        distance_to_reload_pct is not None
        and abs(distance_to_reload_pct) <= RELOAD_ZONE_APPROACHING_THRESHOLD_PCT
    ):
        state_candidates.append("RELOAD_ZONE_APPROACHING")

    if (
        distance_to_target_pct is not None
        and abs(distance_to_target_pct) <= TAKE_PROFIT_WAITING_THRESHOLD_PCT
        and any(level.is_active_target and level.matching_open_sell_orders > 0 for level in target_level_statuses)
    ):
        state_candidates.append("TAKE_PROFIT_WAITING")

    if active_target is None and target_level_statuses:
        state_candidates.append("PRICE_RAN_AWAY")
    elif target_exit_zone and distance_to_target_pct is not None and distance_to_target_pct <= -PRICE_RAN_AWAY_THRESHOLD_PCT:
        state_candidates.append("PRICE_RAN_AWAY")

    order_overlay_state = None
    if (
        order_summary.max_open_order_distance_pct is not None
        and order_summary.max_open_order_distance_pct >= ORDER_STALE_DISTANCE_PCT
    ):
        order_overlay_state = "ORDER_TOO_FAR_OR_STALE"

    if not state_candidates:
        state_candidates.append("DO_NOTHING")

    primary_state = state_candidates[0]
    secondary_state = next((state for state in state_candidates[1:] if state != primary_state), None)
    if secondary_state is None and order_overlay_state is not None and order_overlay_state != primary_state:
        secondary_state = order_overlay_state
    return (
        primary_state,
        secondary_state,
        STATE_LABELS[primary_state],
        distance_to_target_pct,
        distance_to_reload_pct,
        distance_to_invalidation_pct,
    )


def _short_context_gap_card(
    *,
    symbol: str,
    market: str,
    fib_trading_horizon: str,
    short_context_input_status: str,
    short_context_coverage_status: str,
    short_context_display_state: str,
    current_price: Decimal | None,
    current_price_status: str | None,
    current_price_age_min: Decimal | None,
    history_high_since_activation: Decimal | None,
    history_low_since_activation: Decimal | None,
    presentation_mode: str = CARD_MODE_MARKET_SELECTED,
    breath_curve: dict[str, Any] | None = None,
    evidence: CardEvidence | None = None,
) -> ProfitPlanCard:
    order_summary = build_order_summary(
        current_price,
        (),
        (),
        (),
        (),
    )
    reasons = [
        f"SHORT context coverage: {short_context_coverage_status}.",
        f"Profit Plan does not currently have usable native SHORT 4h/1h context for {symbol}.",
    ]
    if short_context_coverage_status == "INSUFFICIENT_4H_HISTORY":
        reasons.append("The native 4h candle window is insufficient to build a canonical SHORT map.")
    elif short_context_coverage_status == "INSUFFICIENT_1H_HISTORY":
        reasons.append("The native 1h supporting window is insufficient, so the canonical SHORT bridge remains unavailable.")
    elif short_context_coverage_status == "FIB_MAP_SYMBOL_MISSING":
        reasons.append("Market price exists, but this symbol has no fib-map row in the current source.")
    elif short_context_coverage_status == "FIB_MAP_SOURCE_MISSING":
        reasons.append("The fib-map source is unavailable, so native SHORT context cannot be audited.")
    elif short_context_coverage_status == "MARKET_DATA_MISSING":
        reasons.append("Market candle history is missing for this symbol in the current fib-map source.")
    elif short_context_coverage_status == "CONTEXT_INVALID_OR_STALE":
        reasons.append("The current source row exists but is not valid enough to expose as SHORT context.")
    return ProfitPlanCard(
        symbol=symbol,
        market=market,
        fib_trading_horizon=fib_trading_horizon,
        short_context_input_status=short_context_input_status,
        short_context_coverage_status=short_context_coverage_status,
        short_context_display_state=short_context_display_state,
        current_price=current_price,
        current_price_status=current_price_status,
        current_price_age_min=current_price_age_min,
        history_high_since_activation=history_high_since_activation,
        history_low_since_activation=history_low_since_activation,
        all_sell_targets_completed=False,
        scenario_type="CONTEXT_UNAVAILABLE",
        action_label="REVIEW_CONTEXT",
        actionability_state=CARD_ACTIONABILITY_CONTEXT_UNAVAILABLE,
        timeframe_label="SHORT 4h/1h",
        buy_zone=(),
        sell_zone=(),
        invalidation_level=None,
        reasons=tuple(reasons),
        order_summary=order_summary,
        target_exit_zone=(),
        active_target=None,
        target_level_statuses=(),
        reload_reentry_zone=(),
        invalidation_risk_zone=None,
        distance_to_target_pct=None,
        distance_to_reload_pct=None,
        distance_to_invalidation_pct=None,
        primary_state="CONTEXT_UNAVAILABLE",
        secondary_state=None,
        suggested_manual_attention_label=_short_context_display_label(short_context_display_state),
        setup_state="MINIMAL_CONTEXT",
        event_state="CONTEXT_UNAVAILABLE",
        ladder_states=("ORDER_DATA_UNAVAILABLE",),
        relevance_reasons=("MINIMAL_CONTEXT",),
        is_relevant=True,
        visibility_class=VISIBILITY_CONTEXT_UNAVAILABLE,
        presentation_mode=presentation_mode,
        breath_curve=breath_curve,
        evidence=evidence or CardEvidence(),
    )


def _legacy_short_reference_override(
    *,
    current_price: Decimal | None,
    short_context_display_state: str,
    scenario_type: str,
    action_label: str,
    reasons: tuple[str, ...],
    target_level_statuses: tuple[TargetLevelStatus, ...],
    active_target: Decimal | None,
) -> tuple[str, str, str, str | None, tuple[str, ...], bool]:
    notes = list(reasons)
    notes.append(
        "Legacy 1d fib-map levels are shown as reference only and must not be treated as native SHORT 4h/1h setup context."
    )
    if active_target is not None:
        notes.append(f"Next legacy reference target remains visible at {_fmt_p(active_target)} for manual review only.")
    if any(level.lifecycle_state in {"REACHED", "PASSED", "COMPLETED", "REACHED_FILLED"} for level in target_level_statuses):
        notes.append("Target lifecycle and order coverage remain visible for audit/reference only.")
    deduped: list[str] = []
    for note in notes:
        if note not in deduped:
            deduped.append(note)
    return (
        LEGACY_SHORT_REFERENCE_SCENARIO,
        LEGACY_SHORT_REFERENCE_ACTION,
        short_context_display_state,
        None,
        tuple(deduped),
        False,
    )


# ---------------------------------------------------------------------------
# Semantic state derivation helpers
# ---------------------------------------------------------------------------

def _derive_setup_state(scenario_type: str) -> str:
    return SETUP_STATE_FROM_SCENARIO.get(scenario_type, "MINIMAL_CONTEXT")


def _derive_event_state(primary_state: str) -> str:
    return EVENT_STATE_FROM_PRIMARY.get(primary_state, "BETWEEN_LEVELS")


def _classify_order_for_zone_coverage(
    order_price: Decimal,
    target_level_statuses: tuple[TargetLevelStatus, ...],
    buy_zone: tuple[Decimal, ...],
) -> str:
    """Classify one order relative to known zones.

    Returns ARMED when the order is near an active zone, HISTORICAL when near a
    passed/completed zone, or STALE when no zone match exists.  Moonbag sell
    orders that sit far above current price but match an active zone are
    classified ARMED (not STALE), fixing the aggregate-max bug.
    """
    for level in target_level_statuses:
        if _near(order_price, level.level, ORDER_MATCH_TOLERANCE_PCT):
            if level.lifecycle_state in {"UPCOMING", "NEAR"}:
                return "ARMED"
            return "HISTORICAL"
    for buy_level in buy_zone:
        if _near(order_price, buy_level, ORDER_MATCH_TOLERANCE_PCT):
            return "ARMED"
    return "STALE"


def _derive_ladder_states(
    buy_zone: tuple[Decimal, ...],
    target_level_statuses: tuple[TargetLevelStatus, ...],
    buy_orders: tuple[Any, ...],
    sell_orders: tuple[Any, ...],
    current_price: Decimal | None = None,
) -> tuple[str, ...]:
    active_levels = [
        lv for lv in target_level_statuses
        if lv.lifecycle_state in {"UPCOMING", "NEAR"}
    ]
    has_buy_zone = bool(buy_zone)
    if not active_levels and not has_buy_zone:
        return ("LADDER_NOT_REQUIRED",)
    states: list[str] = []
    if active_levels:
        covered_count = sum(1 for lv in active_levels if lv.matching_open_sell_orders > 0)
        if covered_count == 0:
            states.append("LADDER_MISSING")
        elif covered_count < len(active_levels):
            states.append("LADDER_INCOMPLETE")
        else:
            states.append("LADDER_ARMED")
    if has_buy_zone:
        # Exclude buy reload levels that are at or above current price — those are
        # missed entries (not dip-catches) and must not trigger LADDER_MISSING.
        actionable_buy_zone = tuple(
            lv for lv in buy_zone
            if current_price is None or lv < current_price
        )
        if actionable_buy_zone:
            buy_covered = sum(
                1 for buy_level in actionable_buy_zone
                if any(_near(o.limit_price, buy_level, ORDER_MATCH_TOLERANCE_PCT) for o in buy_orders)
            )
            if buy_covered == 0 and "LADDER_MISSING" not in states:
                states.append("LADDER_MISSING")
            elif 0 < buy_covered < len(actionable_buy_zone) and "LADDER_MISSING" not in states and "LADDER_INCOMPLETE" not in states:
                states.append("LADDER_INCOMPLETE")
    all_orders = list(buy_orders) + list(sell_orders)
    stale_found = any(
        _classify_order_for_zone_coverage(o.limit_price, target_level_statuses, buy_zone) == "STALE"
        for o in all_orders
    )
    if stale_found:
        states.append("STALE_ORDERS_PRESENT")
    if not states:
        states.append("LADDER_ARMED")
    return tuple(dict.fromkeys(states))


def _order_ladder_display_status(ladder_states: tuple[str, ...]) -> str:
    """Collapse internal ladder states into one user-facing order-ladder status."""
    states = set(ladder_states)
    if not states:
        return "unknown"
    if "ORDER_DATA_UNAVAILABLE" in states:
        return "unknown"
    if "LADDER_NOT_REQUIRED" in states:
        return "not required"
    if "LADDER_MISSING" in states and ("LADDER_ARMED" in states or "LADDER_INCOMPLETE" in states):
        return "incomplete orders"
    if "LADDER_MISSING" in states:
        return "missing orders"
    if "LADDER_INCOMPLETE" in states:
        return "incomplete orders"
    if "STALE_ORDERS_PRESENT" in states:
        return "review stale orders"
    if "LADDER_ARMED" in states:
        return "armed"
    return "unknown"


def _derive_relevance_with_reasons(
    event_state: str,
    ladder_states: tuple[str, ...],
    setup_state: str,
    *,
    force_not_relevant: bool = False,
) -> tuple[bool, tuple[str, ...]]:
    if force_not_relevant:
        return False, ()
    reasons: list[str] = []
    if event_state in RELEVANT_EVENT_STATES:
        reasons.append(event_state)
    for ls in ladder_states:
        if ls in RELEVANT_LADDER_STATES:
            reasons.append(ls)
    if not reasons and setup_state == "MINIMAL_CONTEXT" and event_state == "CONTEXT_UNAVAILABLE":
        reasons.append("MINIMAL_CONTEXT")
    return bool(reasons), tuple(reasons)


def _display_action_label(action_label: str) -> str:
    return _ACTION_DISPLAY_MAP.get(action_label, action_label.replace("_", " "))


_NON_ACTIVE_DISPLAY_LABELS: dict[str, str] = {
    CARD_ACTIONABILITY_CONTEXT_UNAVAILABLE: "REVIEW CONTEXT",
    CARD_ACTIONABILITY_INVALIDATED: "INVALIDATED",
    CARD_ACTIONABILITY_NEEDS_RECOMPUTE: "REVIEW MAP",
    CARD_ACTIONABILITY_NAVIGATION_ONLY: "NAVIGATION ONLY",
    CARD_ACTIONABILITY_HISTORICAL_REFERENCE: "REFERENCE ONLY",
}


# ---------------------------------------------------------------------------
# Quality state aggregation (replaces FRESH_CURRENT_PRICE / NATIVE_SHORT display)
# ---------------------------------------------------------------------------

_QUALITY_PRICE_STALE_STATES = {"STALE_CURRENT_PRICE", "MISSING_CURRENT_PRICE"}
_FIB_CTX_PASS_STATE = "HAS_NATIVE_SHORT_FIB_CONTEXT"
_PRICE_WARN_AGE_MIN = Decimal("5")


def derive_quality_state(
    *,
    current_price: "Decimal | None",
    current_price_status: "str | None",
    current_price_age_min: "Decimal | None",
    short_context_display_state: str,
) -> "tuple[str, str | None]":
    """
    Aggregate data quality into a single display state.
    Returns (quality_state, quality_reason).
    quality_state: PASS | WARN | FAIL | NAV
    quality_reason: None on PASS, human-readable explanation on WARN/FAIL/NAV
    """
    if current_price is None or current_price_status in _QUALITY_PRICE_STALE_STATES:
        reason = "No current price" if current_price is None else "Stale price data"
        return "FAIL", reason
    if short_context_display_state == SHORT_CONTEXT_DISPLAY_CANONICAL_NAVIGATION_AVAILABLE:
        # Issue #223: canonical navigation context is a real, read-only reference --
        # it must never be reported as a fib-context failure.
        return "NAV", "Canonical navigation reference (not lifecycle-verified)"
    if short_context_display_state != _FIB_CTX_PASS_STATE:
        return "FAIL", "No fib context"
    if current_price_age_min is not None and current_price_age_min >= _PRICE_WARN_AGE_MIN:
        return "WARN", f"Price {float(current_price_age_min):.1f} min old"
    return "PASS", None


def _card_quality_state(card: "ProfitPlanCard") -> "tuple[str, str | None]":
    return derive_quality_state(
        current_price=card.current_price,
        current_price_status=card.current_price_status,
        current_price_age_min=card.current_price_age_min,
        short_context_display_state=card.short_context_display_state,
    )


# ---------------------------------------------------------------------------
# Merged value+distance display helpers
# ---------------------------------------------------------------------------

def _eur(price: "Decimal | None") -> str:
    return f"€{_fmt_p(price)}" if price is not None else "?"


def format_current_price_line(
    price: "Decimal | None",
    age_min: "Decimal | None",
    quote: str,
) -> str:
    """Merged current price display: €0.675670 · 0.3 min ago"""
    if price is None:
        return "—"
    price_str = f"€{_fmt_p(price)}" if quote == "EUR" else f"{_fmt_p(price)} {quote}".strip()
    if age_min is not None:
        return f"{price_str} · {float(age_min):.1f} min ago"
    return price_str


def _format_zone_endpoint(price: "Decimal", current_price: "Decimal | None") -> str:
    """Format one zone price as '€0.96 (-4.00%)' or '€0.96' when current_price is unavailable."""
    price_str = _eur(price)
    if current_price is None or current_price <= 0:
        return price_str
    pct = (price - current_price) / current_price * Decimal("100")
    sign = "+" if pct >= 0 else ""
    return f"{price_str} ({sign}{_pct(pct)})"


def _format_zone_range(zone: "tuple[Decimal, ...]", current_price: "Decimal | None") -> str:
    """Format tuple[0] – tuple[-1] with signed percentages. Single endpoint if length 1 or identical."""
    if not zone:
        return ""
    first = _format_zone_endpoint(zone[0], current_price)
    if len(zone) == 1 or zone[0] == zone[-1]:
        return first
    last = _format_zone_endpoint(zone[-1], current_price)
    return f"{first} – {last}"


def format_reentry_zone_line(
    reload_zone: "tuple[Decimal, ...]",
    current_price: "Decimal | None",
) -> str:
    """Re-entry zone: €0.675991 (-0.00%) – €0.669810 (-0.91%)"""
    if not reload_zone:
        return "No levels loaded"
    return _format_zone_range(reload_zone, current_price)


def format_target_zone_line(
    target_exit_zone: "tuple[Decimal, ...]",
    current_price: "Decimal | None",
) -> str:
    """Target zone: €0.696000 (+2.99%) – €0.728371 (+7.77%)"""
    if not target_exit_zone:
        return "No upcoming levels"
    return _format_zone_range(target_exit_zone, current_price)


def format_invalidation_line(
    invalidation_risk_zone: "Decimal | None",
    distance_to_invalidation_pct: "Decimal | None",
) -> str:
    """Merged invalidation: Below €0.654829 · -3.08%"""
    if invalidation_risk_zone is None:
        return "—"
    price_str = f"Below {_eur(invalidation_risk_zone)}"
    if distance_to_invalidation_pct is not None:
        return f"{price_str} · {_pct(distance_to_invalidation_pct)}"
    return price_str


def _actionability_display_bundle(card: ProfitPlanCard) -> tuple[str, str, str, str, str, str]:
    reentry_label = "Re-entry zone"
    target_label = "Target zone"
    order_ladder_label = "Order ladder"
    open_orders_label = "Existing open orders:"
    reentry_line = format_reentry_zone_line(card.reload_reentry_zone, card.current_price)
    target_line = format_target_zone_line(card.target_exit_zone, card.current_price)

    if card.presentation_mode in _NO_ACCOUNT_STATE_MODES:
        return "Entry zone", target_label, "Market zones", "", reentry_line, target_line

    if card.actionability_state == CARD_ACTIONABILITY_ACTIVE:
        return reentry_label, target_label, order_ladder_label, open_orders_label, reentry_line, target_line

    reentry_label = "Reference re-entry zone"
    open_orders_label = "Existing open orders to review:"
    order_ladder_label = "Order review"

    if card.actionability_state == CARD_ACTIONABILITY_CONTEXT_UNAVAILABLE:
        reentry_label = "Non-canonical reference re-entry zone"
        target_label = "Non-canonical reference target zone"
        target_line = format_target_zone_line(card.sell_zone, card.current_price)
        if not card.sell_zone:
            target_line = "Canonical map context unavailable"
    elif card.actionability_state == CARD_ACTIONABILITY_NAVIGATION_ONLY:
        target_label = "Navigation target zone"
        if not card.target_exit_zone:
            target_line = "Navigation only"
    elif card.actionability_state == CARD_ACTIONABILITY_HISTORICAL_REFERENCE:
        target_label = "Historical target zone"
        if not card.target_exit_zone:
            target_line = "Historical targets already completed"
    elif card.actionability_state == CARD_ACTIONABILITY_NEEDS_RECOMPUTE:
        target_label = "Historical target zone"
        target_line = "Fresh map required before new orders"
    elif card.actionability_state == CARD_ACTIONABILITY_INVALIDATED:
        reentry_label = "Invalidated re-entry zone"
        target_label = "Historical target zone"
        target_line = "Context invalidated — review existing orders if applicable"

    return reentry_label, target_label, order_ladder_label, open_orders_label, reentry_line, target_line


def _evidence_state_class(card: ProfitPlanCard) -> str:
    if card.actionability_state == CARD_ACTIONABILITY_INVALIDATED or card.primary_state in {"INVALIDATED", "MAP_COMPLETED", "MAP_RECOMPUTE_NEEDED"}:
        return "evidence-red"
    missing_values = {
        card.evidence.map_cycle_id,
        card.evidence.price_ts_utc,
        card.evidence.price_freshness_state,
    }
    if DATA_UNAVAILABLE in missing_values or card.current_price_status in {"STALE_CURRENT_PRICE", "MISSING_CURRENT_PRICE"}:
        return "evidence-amber"
    if card.delta.delta_status == "UPDATED_NOW":
        return "evidence-green"
    return "evidence-neutral"


def _delta_summary_text(delta: CardDelta) -> str:
    if delta.delta_status == "NO_PREVIOUS_SNAPSHOT":
        return "NO_PREVIOUS_SNAPSHOT"
    if delta.delta_status == "UNCHANGED":
        return "UNCHANGED"
    changed = ", ".join(delta.changed_fields[:4])
    suffix = "…" if len(delta.changed_fields) > 4 else ""
    return f"UPDATED NOW · {changed}{suffix}" if changed else "UPDATED NOW"


_EVIDENCE_ROW_WARN_STATUSES: frozenset[str] = frozenset({
    DATA_UNAVAILABLE, "UNKNOWN", "MISSING", "STALE", "REPORTING_FALLBACK",
})


def _evidence_authority_row_class(row: EvidenceRow) -> str:
    if row.reason_codes or row.status in _EVIDENCE_ROW_WARN_STATUSES:
        return "evidence-authority-row-warn"
    return "evidence-authority-row-ok"


def _evidence_authority_row_html(row: EvidenceRow) -> str:
    observed_html = f" · {esc(row.observed_ts)}" if row.observed_ts else ""
    reasons_html = (
        f"<div class='evidence-row-reasons muted small'>Reasons: {esc(', '.join(row.reason_codes))}</div>"
        if row.reason_codes
        else ""
    )
    return (
        f"<div class='evidence-authority-row {_evidence_authority_row_class(row)}'>"
        "<div class='evidence-row-head'>"
        f"<span class='evidence-row-label'>{esc(row.label)}</span>"
        f"<code class='evidence-row-status'>{esc(row.status)}</code>"
        "</div>"
        f"<div class='evidence-row-authority muted small'>{esc(row.authority)}{observed_html}</div>"
        f"{reasons_html}"
        "</div>"
    )


# ---------------------------------------------------------------------------
# Operator-facing evidence presentation (Issue #347 — pure display reorg).
#
# These maps translate internal row/reason-code identifiers into plain
# operator language and group the fixed evidence-row tuple from
# build_card_evidence_rows() by domain for HTML display only. They never
# alter EvidenceRow.key/label/status/reason_codes themselves (those remain
# the JSON-schema-facing values returned by evidence_rows_to_json) — only the
# HTML rendering path substitutes a friendlier display label/heading.
# ---------------------------------------------------------------------------

_EVIDENCE_ROW_DISPLAY_LABELS: dict[str, str] = {
    "projection_status": "Fibonacci map projection",
    "current_map_selection": "Selected Fibonacci map",
    "map_lifecycle": "Fibonacci map lifecycle",
    "per_level_status": "Fibonacci level status",
    "price_snapshot": "Market price snapshot",
    "wallet_snapshot": "Wallet snapshot",
    "position_snapshot": "Position-tracking snapshot",
    "open_order_snapshot": "Open-order snapshot",
    "dashboard_render": "Dashboard render",
    "action_gate": "Action / permission gate",
}

# Evidence-row key -> (domain group heading, group sort order). Any row key
# absent from this map falls into a trailing "Other" group rather than being
# dropped, so a future new evidence row is never silently hidden.
_EVIDENCE_ROW_DOMAIN_GROUPS: dict[str, tuple[str, int]] = {
    "projection_status": ("Fibonacci / map", 0),
    "current_map_selection": ("Fibonacci / map", 0),
    "map_lifecycle": ("Fibonacci / map", 0),
    "per_level_status": ("Fibonacci / map", 0),
    "price_snapshot": ("Market data", 1),
    "wallet_snapshot": ("Account / position / wallet / orders", 2),
    "position_snapshot": ("Account / position / wallet / orders", 2),
    "open_order_snapshot": ("Account / position / wallet / orders", 2),
    "dashboard_render": ("Reporting / render", 3),
    "action_gate": ("Action / permission", 4),
}

# Raw reason codes / status tokens -> plain operator language. Used only for
# the human-readable secondary line; the raw code stays available in a
# <details> block so nothing is deleted, only made secondary.
_REASON_CODE_OPERATOR_LABELS: dict[str, str] = {
    "NATIVE_MAP_DATA_UNAVAILABLE": "Native Fibonacci map data unavailable",
    "MAP_TIER_NOT_CONFIRMED_CURRENT": "Selected Fibonacci map — NOT CONFIRMED",
    "MAP_SELECTION_UNAVAILABLE": "Fibonacci map selection unavailable",
    "MAP_LIFECYCLE_UNAVAILABLE": "Fibonacci map lifecycle unavailable",
    "MAP_LIFECYCLE_BLOCKS_ACTION": "Fibonacci map lifecycle blocks action",
    "MAP_CYCLE_UNAVAILABLE": "Fibonacci map cycle unavailable",
    "MAP_SWITCH_UNVERIFIED": "Fibonacci map switch not yet verified",
    "TRANSIENT_LIFECYCLE_NOT_CANONICAL": "Map lifecycle is a non-canonical reference only",
    "TRANSIENT_LEVELS_REFERENCE_ONLY": "Levels shown are a non-canonical reference only",
    "NATIVE_LEVEL_STATUS_UNAVAILABLE": "Native level status unavailable",
    "LEVEL_STATUS_UNAVAILABLE": "Level status unavailable",
    "REPORTING_DERIVED_NOT_NATIVE_CANONICAL": "Derived by reporting, not native canonical truth",
    "STALE_OR_MISSING_CURRENT_PRICE": "Current price stale or missing",
    "STALE_CURRENT_PRICE": "Current price is stale",
    "WALLET_DATA_UNAVAILABLE": "Wallet data unavailable",
    "STALE_WALLET_DATA": "Wallet data is stale",
    "POSITION_DATA_UNAVAILABLE": "Position-tracking data unavailable",
    "STALE_POSITION_DATA": "Position-tracking data is stale",
    "OPEN_ORDER_DATA_UNAVAILABLE": "Open-order data unavailable",
    "STALE_OPEN_ORDER_SNAPSHOT": "Open-order snapshot is stale",
    "ACCOUNT_ORDER_DATA_UNAVAILABLE": "Account order data unavailable",
    "STALE_OR_UNAVAILABLE_ORDER_SNAPSHOT": "Order snapshot stale or unavailable",
    "NON_CANONICAL_REFERENCE_ONLY": "Only a non-canonical reference is available",
    "CONTEXT_INVALIDATED": "Fibonacci context invalidated",
    "ENTRY_LEVELS_UNAVAILABLE": "Entry levels unavailable",
    "ENTRY_ACTIVATION_UNPROVEN": "Entry activation not yet proven",
}


_MAP_SELECTION_STATUS_OPERATOR_TEXT: dict[str, str] = {
    "CURRENT_ACTIVE_MAP": "CONFIRMED CURRENT",
    "REPORTING_FALLBACK": "NOT CONFIRMED",
    "UNKNOWN": "UNKNOWN",
}


def _operator_map_selection_text(row: EvidenceRow) -> str:
    """Translate the current_map_selection evidence row into the operator
    wording required by Issue #347, e.g. REPORTING_FALLBACK ->
    'NOT CONFIRMED'. Reads the already-computed row status only; does not
    recompute map-selection truth."""
    return _MAP_SELECTION_STATUS_OPERATOR_TEXT.get(row.status, row.status)


def _operator_map_lifecycle_text(row: EvidenceRow) -> str:
    """Plain-language lifecycle status for the Fibonacci Levels section.
    Reads the already-computed map_lifecycle evidence row status only."""
    if row.status == DATA_UNAVAILABLE:
        return "UNAVAILABLE"
    return row.status


def _reason_code_operator_label(code: str) -> str:
    if code in _REASON_CODE_OPERATOR_LABELS:
        return _REASON_CODE_OPERATOR_LABELS[code]
    if code.startswith("REPORTED_TIER_"):
        return f"Reported (unconfirmed) map selection: {code[len('REPORTED_TIER_'):]}"
    return code.replace("_", " ").title()


def _evidence_row_operator_reasons_html(row: EvidenceRow) -> str:
    """Operator-readable reason summary with the raw codes preserved in a
    collapsible <details> block, per Issue #347 (technical codes may remain
    in expandable/secondary detail, not as primary copy)."""
    if not row.reason_codes:
        return ""
    plain = ", ".join(_reason_code_operator_label(code) for code in row.reason_codes)
    raw = ", ".join(row.reason_codes)
    return (
        f"<div class='evidence-row-reasons muted small'>{esc(plain)}</div>"
        "<details class='evidence-row-raw-codes'>"
        "<summary class='muted small'>Technical codes</summary>"
        f"<code class='muted small'>{esc(raw)}</code>"
        "</details>"
    )


def _evidence_authority_row_html_grouped(row: EvidenceRow) -> str:
    """Same visual row as _evidence_authority_row_html, but with an
    operator-facing display label and reason codes demoted to secondary/
    expandable detail. Row.key/status/authority/observed_ts are unchanged."""
    observed_html = f" · {esc(row.observed_ts)}" if row.observed_ts else ""
    display_label = _EVIDENCE_ROW_DISPLAY_LABELS.get(row.key, row.label)
    return (
        f"<div class='evidence-authority-row {_evidence_authority_row_class(row)}'>"
        "<div class='evidence-row-head'>"
        f"<span class='evidence-row-label'>{esc(display_label)}</span>"
        f"<code class='evidence-row-status'>{esc(row.status)}</code>"
        "</div>"
        f"<div class='evidence-row-authority muted small'>{esc(row.authority)}{observed_html}</div>"
        f"{_evidence_row_operator_reasons_html(row)}"
        "</div>"
    )


def _grouped_evidence_html(rows: tuple[EvidenceRow, ...]) -> str:
    """Group the fixed evidence-row tuple by domain for card display only.
    Grouping is presentation-only: it does not reorder, drop, invent, or
    recompute any evidence row. Rows retain their original relative order
    within each group."""
    groups: dict[str, list[EvidenceRow]] = {}
    order: dict[str, int] = {}
    for row in rows:
        heading, sort_order = _EVIDENCE_ROW_DOMAIN_GROUPS.get(row.key, ("Other", 99))
        groups.setdefault(heading, []).append(row)
        order[heading] = sort_order
    parts: list[str] = []
    for heading in sorted(groups, key=lambda h: order[h]):
        rows_html = "".join(_evidence_authority_row_html_grouped(r) for r in groups[heading])
        parts.append(
            "<div class='evidence-domain-group'>"
            f"<div class='evidence-domain-heading'>{esc(heading)}</div>"
            f"{rows_html}"
            "</div>"
        )
    return "".join(parts)


def _card_evidence_html(rows: tuple[EvidenceRow, ...], card: ProfitPlanCard) -> str:
    """Render the normalized evidence-authority rows (P1). Each row has exactly
    one authority owner and one canonical status — no row is inferred from, or
    visually compressed with, an unrelated row (e.g. a DATA_UNAVAILABLE
    projection is never paired with a confirmed CURRENT_ACTIVE_MAP claim)."""
    rows_html = _grouped_evidence_html(rows)
    delta_types = ", ".join(card.delta.material_delta_types) or "none"
    changed = ", ".join(card.delta.changed_fields) or "none"
    return (
        f"<div class='card-evidence {_evidence_state_class(card)}'>"
        f"<div class='evidence-header'><span>Evidence</span><strong>{esc(_delta_summary_text(card.delta))}</strong></div>"
        f"<div class='evidence-authority-rows'>{rows_html}</div>"
        f"<div class='evidence-delta muted small'>Delta: {esc(delta_types)} · Fields: {esc(changed)}</div>"
        "</div>"
    )


# ---------------------------------------------------------------------------
# User action override: FIX LADDER beats WAIT when orders need attention
# ---------------------------------------------------------------------------

_WAIT_LIKE_DISPLAY_LABELS = {"BETWEEN LEVELS", "CONTEXT UNAVAILABLE", "WAIT", "DO NOTHING"}


def _displayed_user_action(
    action_label: str,
    order_rows: "tuple[OrderRow, ...]",
    actionability_state: str = CARD_ACTIONABILITY_ACTIVE,
) -> str:
    """
    Returns the display user action label.
    Overrides WAIT-like labels with 'FIX LADDER' when actionable orders exist.
    market_state and user_action remain independent; this only affects the display label.
    """
    base = _display_action_label(action_label)
    if actionability_state != CARD_ACTIONABILITY_ACTIVE:
        return _NON_ACTIVE_DISPLAY_LABELS.get(actionability_state, actionability_state.replace("_", " "))
    if base.upper() in _WAIT_LIKE_DISPLAY_LABELS:
        if any(r.state in {"MISSING", "STALE"} for r in order_rows):
            return "FIX LADDER"
    return base


# ---------------------------------------------------------------------------
# Card builder
# ---------------------------------------------------------------------------

def build_profit_plan_card(
    symbol: str,
    market: str,
    current_price: Decimal | None,
    *,
    fib_trading_horizon: str = "SHORT",
    short_context_input_status: str = "MISSING_ZONE_CONTEXT",
    short_context_coverage_status: str = "CONTEXT_INVALID_OR_STALE",
    short_context_display_state: str = "NO_NATIVE_SHORT_FIB_CONTEXT",
    fib_ext: FibExtContext | None = None,
    reentry: ReentryContext | None = None,
    profile_classification: str | None = None,
    preferred_retrace_level: str | None = None,
    buy_orders: tuple[Any, ...] = (),
    sell_orders: tuple[Any, ...] = (),
    filled_sell_levels: tuple[Decimal, ...] = (),
    completed_sell_levels: tuple[Decimal, ...] = (),
    history_high_since_activation: Decimal | None = None,
    history_low_since_activation: Decimal | None = None,
    history_candles_since_activation: tuple[TargetHistoryCandle, ...] = (),
    current_price_status: str | None = None,
    current_price_age_min: Decimal | None = None,
    fib_nav_context: FibNavContext | None = None,
    presentation_mode: str = CARD_MODE_MARKET_SELECTED,
    breath_curve: dict[str, Any] | None = None,
    evidence: CardEvidence | None = None,
) -> ProfitPlanCard:
    card_evidence = evidence or CardEvidence()
    canonical_native_map_truth_available = _canonical_native_map_truth_available(card_evidence)
    if not canonical_native_map_truth_available and (fib_ext is not None or reentry is not None):
        short_context_display_state = "TRANSIENT_NON_CANONICAL_SHORT_CONTEXT"
        if short_context_coverage_status == "NATIVE_SHORT_CONTEXT_AVAILABLE":
            short_context_coverage_status = "TRANSIENT_NON_CANONICAL_CONTEXT_AVAILABLE"
        if short_context_input_status == "NATIVE_SHORT_CONTEXT_AVAILABLE":
            short_context_input_status = "TRANSIENT_NON_CANONICAL_CONTEXT_AVAILABLE"

    unusable_price_status = current_price_status
    if current_price is None and unusable_price_status not in {"STALE_CURRENT_PRICE", "MISSING_CURRENT_PRICE"}:
        unusable_price_status = "MISSING_CURRENT_PRICE"
    if unusable_price_status in {"STALE_CURRENT_PRICE", "MISSING_CURRENT_PRICE"}:
        order_summary = build_order_summary(
            None,
            (),
            (),
            buy_orders,
            sell_orders,
        )
        return ProfitPlanCard(
            symbol=symbol,
            market=market,
            fib_trading_horizon=fib_trading_horizon,
            short_context_input_status=short_context_input_status,
            short_context_coverage_status=short_context_coverage_status,
            short_context_display_state=short_context_display_state,
            current_price=None,
            current_price_status=unusable_price_status,
            current_price_age_min=current_price_age_min,
            history_high_since_activation=history_high_since_activation,
            history_low_since_activation=history_low_since_activation,
            all_sell_targets_completed=False,
            scenario_type=("NO_CURRENT_PRICE" if canonical_native_map_truth_available else "CONTEXT_UNAVAILABLE"),
            action_label=("NO_CURRENT_PRICE" if canonical_native_map_truth_available else "REVIEW_CONTEXT"),
            actionability_state=(
                CARD_ACTIONABILITY_NEEDS_RECOMPUTE
                if canonical_native_map_truth_available
                else CARD_ACTIONABILITY_CONTEXT_UNAVAILABLE
            ),
            timeframe_label="review blocked",
            buy_zone=(),
            sell_zone=(),
            invalidation_level=None,
            reasons=(
                (
                    "Current public price snapshot is stale."
                    if unusable_price_status == "STALE_CURRENT_PRICE"
                    else "Current public price snapshot is missing."
                ),
                "Do not use percentage distance, action labels, or scenario recommendation until price refresh succeeds.",
            ),
            order_summary=order_summary,
            target_exit_zone=(),
            active_target=None,
            target_level_statuses=(),
            reload_reentry_zone=(),
            invalidation_risk_zone=None,
            distance_to_target_pct=None,
            distance_to_reload_pct=None,
            distance_to_invalidation_pct=None,
            primary_state=(unusable_price_status if canonical_native_map_truth_available else "CONTEXT_UNAVAILABLE"),
            secondary_state=None,
            suggested_manual_attention_label=STATE_LABELS.get(
                unusable_price_status,
                unusable_price_status.replace("_", " "),
            ),
            setup_state="MINIMAL_CONTEXT",
            event_state="CONTEXT_UNAVAILABLE",
            ladder_states=("ORDER_DATA_UNAVAILABLE",),
            relevance_reasons=(),
            is_relevant=False,
            visibility_class=(
                VISIBILITY_NATIVE_ATTENTION
                if canonical_native_map_truth_available
                else VISIBILITY_CONTEXT_UNAVAILABLE
            ),
            presentation_mode=presentation_mode,
            breath_curve=breath_curve,
            evidence=dataclasses.replace(
                card_evidence,
                price_freshness_state=unusable_price_status,
            ),
        )
    if (
        fib_ext is None
        and reentry is None
        and short_context_display_state in {
            "NO_NATIVE_SHORT_FIB_CONTEXT",
            "MARKET_DATA_MISSING",
            "CONTEXT_INVALID_OR_STALE",
        }
        and (current_price is not None or short_context_display_state == "MARKET_DATA_MISSING")
    ):
        return _short_context_gap_card(
            symbol=symbol,
            market=market,
            fib_trading_horizon=fib_trading_horizon,
            short_context_input_status=short_context_input_status,
            short_context_coverage_status=short_context_coverage_status,
            short_context_display_state=short_context_display_state,
            current_price=current_price,
            current_price_status=current_price_status,
            current_price_age_min=current_price_age_min,
            history_high_since_activation=history_high_since_activation,
            history_low_since_activation=history_low_since_activation,
            presentation_mode=presentation_mode,
            breath_curve=breath_curve,
            evidence=evidence,
        )
    (
        scenario_type,
        action_label,
        timeframe_label,
        buy_zone,
        sell_zone,
        invalidation_level,
        reasons,
    ) = _classify_scenario(
        current_price,
        fib_ext,
        reentry,
        profile_classification,
        preferred_retrace_level,
    )

    lifecycle_target_levels = _unique_levels(
        (
            fib_ext.local_reaction_price if fib_ext is not None else None,
            *sell_zone,
        )
    )

    target_level_statuses, active_target = _build_target_level_statuses(
        current_price=current_price,
        target_levels=lifecycle_target_levels,
        sell_orders=sell_orders,
        history_high_since_activation=history_high_since_activation,
        history_low_since_activation=history_low_since_activation,
        history_candles_since_activation=history_candles_since_activation,
        filled_sell_levels=filled_sell_levels,
        completed_sell_levels=completed_sell_levels,
    )
    active_target_exit_zone = tuple(
        level.level
        for level in target_level_statuses
        if level.lifecycle_state in {"UPCOMING", "NEAR"}
    )

    retest_notes = _target_retest_notes(target_level_statuses)

    order_summary = build_order_summary(
        current_price,
        buy_zone,
        active_target_exit_zone,
        buy_orders,
        sell_orders,
        target_level_statuses=target_level_statuses,
    )

    (
        all_sell_targets_completed,
        scenario_type,
        action_label,
        completed_map_primary_state,
        completed_map_attention_label,
        reasons,
    ) = _completed_map_override(
        canonical_lifecycle_authoritative=canonical_native_map_truth_available,
        current_price=current_price,
        sell_zone=sell_zone,
        target_level_statuses=target_level_statuses,
        scenario_type=scenario_type,
        action_label=action_label,
        reasons=tuple(list(reasons) + [note for note in retest_notes if note not in reasons]),
    )

    # When all old targets are passed and a nav map is available, surface its levels
    # for display instead of showing empty zones. The primary_state stays MAP_RECOMPUTE_NEEDED
    # because a formal recompute is still warranted — these are navigation reference levels.
    if all_sell_targets_completed and fib_nav_context is not None:
        _nav_sell = tuple(
            p for p in fib_nav_context.nav_sell_levels
            if current_price is None or p > current_price
        )
        if _nav_sell:
            active_target_exit_zone = _nav_sell
            active_target = _nav_sell[0]
            if fib_nav_context.nav_buy_levels:
                buy_zone = fib_nav_context.nav_buy_levels
            invalidation_level = fib_nav_context.nav_invalidation
            action_label = "NAVIGATION_ONLY"
            reasons = (
                "Old sell targets are historically completed. Navigation levels from the extended cycle map are shown for reference.",
                *reasons,
            )

    (
        primary_state,
        secondary_state,
        suggested_manual_attention_label,
        distance_to_target_pct,
        distance_to_reload_pct,
        distance_to_invalidation_pct,
    ) = _evaluate_display_states(
        current_price=current_price,
        target_exit_zone=active_target_exit_zone,
        active_target=active_target,
        target_level_statuses=target_level_statuses,
        reload_reentry_zone=buy_zone,
        invalidation_risk_zone=invalidation_level,
        order_summary=order_summary,
    )

    if all_sell_targets_completed:
        primary_state = completed_map_primary_state or primary_state
        secondary_state = None
        suggested_manual_attention_label = completed_map_attention_label or suggested_manual_attention_label

    # For completed maps, old re-entry levels are historical only — suppress from ladder.
    # This prevents LADDER_MISSING on old reload zones after all sell targets have passed.
    _ladder_buy_zone = () if all_sell_targets_completed else buy_zone

    if short_context_coverage_status in {
        "LEGACY_1D_CONTEXT_ONLY",
        "INSUFFICIENT_4H_HISTORY",
        "INSUFFICIENT_1H_HISTORY",
        "CONTEXT_INVALID_OR_STALE",
    }:
        legacy_reason = (
            "Displayed levels come from the current legacy 1d fib-map bridge or partial fallback context. "
            "No usable native SHORT 4h/1h context is available yet."
        )
        if legacy_reason not in reasons:
            reasons = tuple(list(reasons) + [legacy_reason])
        (
            scenario_type,
            action_label,
            primary_state,
            secondary_state,
            reasons,
            is_relevant,
        ) = _legacy_short_reference_override(
            current_price=current_price,
            short_context_display_state=short_context_display_state,
            scenario_type=scenario_type,
            action_label=action_label,
            reasons=reasons,
            target_level_statuses=target_level_statuses,
            active_target=active_target,
        )
        suggested_manual_attention_label = _short_context_display_label(short_context_display_state)
        setup_state = _derive_setup_state(scenario_type)
        event_state = _derive_event_state(primary_state)
        ladder_states = _derive_ladder_states(_ladder_buy_zone, target_level_statuses, buy_orders, sell_orders, current_price)
        is_relevant, relevance_reasons = _derive_relevance_with_reasons(
            event_state, ladder_states, setup_state, force_not_relevant=True
        )
    else:
        setup_state = _derive_setup_state(scenario_type)
        event_state = _derive_event_state(primary_state)
        ladder_states = _derive_ladder_states(_ladder_buy_zone, target_level_statuses, buy_orders, sell_orders, current_price)
        is_relevant, relevance_reasons = _derive_relevance_with_reasons(event_state, ladder_states, setup_state)

    # Issue #210: a canonical_fib_zone_map_latest_v1 row (market-only, never
    # lifecycle-verified) must not collapse to CONTEXT_UNAVAILABLE just
    # because native-short truth is absent -- but it must also never be
    # relabeled with a native-lifecycle scenario/state/action. This flag is
    # derived only from the short-context coverage bridge classification
    # (src/reporting/run_manual_short_trader_profit_plan_v1.py), never from
    # native evidence, so it cannot fabricate promoted native-short state.
    canonical_market_context_available = (
        not canonical_native_map_truth_available
        and short_context_coverage_status == SHORT_CONTEXT_COVERAGE_CANONICAL_4H_AVAILABLE
    )

    if canonical_market_context_available:
        # Navigation levels (buy_zone/sell_zone/active_target/order_summary/
        # distances) are left exactly as already computed above from the
        # real canonical fib_ext/reentry context -- only the scenario/state/
        # action labels and relevance/ladder semantics are relabeled as
        # explicitly read-only, non-lifecycle, non-actionable reference.
        scenario_type = SCENARIO_CANONICAL_MARKET_CONTEXT
        action_label = ACTION_LABEL_CANONICAL_NAVIGATION_ONLY
        primary_state = PRIMARY_STATE_CANONICAL_NAVIGATION_ONLY
        secondary_state = None
        short_context_display_state = SHORT_CONTEXT_DISPLAY_CANONICAL_NAVIGATION_AVAILABLE
        suggested_manual_attention_label = STATE_LABELS[PRIMARY_STATE_CANONICAL_NAVIGATION_ONLY]
        reasons = (
            "Native lifecycle SHORT context is unavailable for this symbol.",
            "Canonical 4h navigation context is available: displayed levels come from "
            "the market-only canonical_fib_zone_map_latest_v1 bridge, not the native "
            "SHORT lifecycle bridge.",
            "Displayed levels are read-only navigation reference; no lifecycle, "
            "promotion, or successor state is inferred.",
        )
        setup_state = _derive_setup_state(scenario_type)
        event_state = _derive_event_state(primary_state)
        ladder_states = _derive_ladder_states(
            _ladder_buy_zone, target_level_statuses, buy_orders, sell_orders, current_price
        )
        is_relevant, relevance_reasons = _derive_relevance_with_reasons(
            event_state, ladder_states, setup_state, force_not_relevant=True
        )
    elif not canonical_native_map_truth_available:
        all_sell_targets_completed = False
        scenario_type = "CONTEXT_UNAVAILABLE"
        action_label = "REVIEW_CONTEXT"
        primary_state = "CONTEXT_UNAVAILABLE"
        secondary_state = None
        suggested_manual_attention_label = (
            MISSING_CANDLES_DISPLAY_LABEL
            if card_evidence.native_context_freshness_status in _NATIVE_SOURCE_STALE_FRESHNESS_STATES
            else STATE_LABELS["CONTEXT_UNAVAILABLE"]
        )
        setup_state = "MINIMAL_CONTEXT"
        event_state = "CONTEXT_UNAVAILABLE"
        ladder_states = ()
        is_relevant = True
        relevance_reasons = ("CONTEXT_UNAVAILABLE",)
        reasons = (
            "Canonical native SHORT map and scope-status truth is unavailable. No map lifecycle or successor state is inferred.",
            "Displayed bridge levels are transient non-canonical reference context only.",
        )
        active_target_exit_zone = ()
        active_target = None
        target_level_statuses = ()
        order_summary = build_order_summary(
            current_price,
            (),
            (),
            buy_orders,
            sell_orders,
        )
        distance_to_target_pct = None
        distance_to_reload_pct = None
        distance_to_invalidation_pct = None

    actionability_state = _derive_card_actionability_state(
        scenario_type=scenario_type,
        action_label=action_label,
        short_context_display_state=short_context_display_state,
        primary_state=primary_state,
        current_price=current_price,
        invalidation_level=invalidation_level,
        canonical_native_map_truth_available=canonical_native_map_truth_available,
        canonical_market_context_available=canonical_market_context_available,
    )

    # Issue #212: visibility_class is a grouping/display concern, independent of
    # is_relevant (attention/actionability). A canonical-bridge card is always
    # CANONICAL_NAVIGATION_REFERENCE regardless of its (always-False) is_relevant
    # value; a native lifecycle-verified card is always ACTIONABLE regardless of
    # its moment-to-moment is_relevant value; everything else (no native truth,
    # no canonical bridge) is CONTEXT_UNAVAILABLE. Native relevance derivation
    # above is untouched by this classification.
    if canonical_market_context_available:
        visibility_class = VISIBILITY_CANONICAL_NAVIGATION_REFERENCE
    elif canonical_native_map_truth_available:
        visibility_class = VISIBILITY_NATIVE_ATTENTION
    else:
        visibility_class = VISIBILITY_CONTEXT_UNAVAILABLE

    return ProfitPlanCard(
        symbol=symbol,
        market=market,
        fib_trading_horizon=fib_trading_horizon,
        short_context_input_status=short_context_input_status,
        short_context_coverage_status=short_context_coverage_status,
        short_context_display_state=short_context_display_state,
        current_price=current_price,
        current_price_status=current_price_status,
        current_price_age_min=current_price_age_min,
        history_high_since_activation=history_high_since_activation,
        history_low_since_activation=history_low_since_activation,
        all_sell_targets_completed=all_sell_targets_completed,
        scenario_type=scenario_type,
        action_label=action_label,
        actionability_state=actionability_state,
        timeframe_label=timeframe_label,
        buy_zone=buy_zone,
        sell_zone=sell_zone,
        invalidation_level=invalidation_level,
        reasons=reasons,
        order_summary=order_summary,
        target_exit_zone=active_target_exit_zone,
        active_target=active_target,
        target_level_statuses=target_level_statuses,
        reload_reentry_zone=buy_zone,
        invalidation_risk_zone=invalidation_level,
        distance_to_target_pct=distance_to_target_pct,
        distance_to_reload_pct=distance_to_reload_pct,
        distance_to_invalidation_pct=distance_to_invalidation_pct,
        primary_state=primary_state,
        secondary_state=secondary_state,
        suggested_manual_attention_label=suggested_manual_attention_label,
        setup_state=setup_state,
        event_state=event_state,
        ladder_states=ladder_states,
        relevance_reasons=relevance_reasons,
        is_relevant=is_relevant,
        visibility_class=visibility_class,
        fib_nav_context=fib_nav_context,
        presentation_mode=presentation_mode,
        breath_curve=breath_curve,
        evidence=card_evidence,
    )


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

_CSS = """
    :root {
      --bg: #080d18; --panel: #111a2e; --panel2: #17223b;
      --text: #ecf2ff; --muted: #93a4c2; --line: #293957;
      --bad: #ff7171; --warn: #ffd166; --ok: #66dfb2; --blue: #8fb3ff;
      --accent: #b48aff;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: radial-gradient(circle at top left, #172345, var(--bg) 45%);
      color: var(--text);
      font-family: system-ui, -apple-system, Segoe UI, sans-serif;
      font-size: 14px;
    }
    header {
      padding: 10px 16px 8px; border-bottom: 1px solid var(--line);
      background: rgba(8,13,24,.92);
    }
    .cockpit-nav {
      display: flex; flex-wrap: wrap; gap: 14px; margin: 6px 0 0;
    }
    .cockpit-nav a {
      color: var(--blue); text-decoration: none; font-size: 14px;
    }
    .cockpit-nav a:hover { text-decoration: underline; }
    h1 { margin: 0 0 2px; font-size: 18px; }
    h2 { margin: 0 0 6px; font-size: 19px; }
    h3 { margin: 0 0 6px; font-size: 11px; text-transform: uppercase;
         letter-spacing: .07em; color: var(--blue); }
    main { padding: 16px; }
    #profit-plan-cockpit {
      display: grid; grid-template-columns: 220px 1fr 280px; gap: 12px;
    }
    #profit-plan-selector {
      background: rgba(17,26,46,.94); border: 1px solid var(--line);
      border-radius: 12px; overflow-y: auto; max-height: calc(100vh - 140px);
    }
    .pp-selector-item {
      padding: 8px 12px; cursor: pointer;
      border-bottom: 1px solid var(--line); font-size: 13px;
    }
    .pp-selector-item:hover { background: rgba(255,255,255,.05); }
    .pp-selector-item.active {
      background: rgba(139,179,255,.12); border-left: 3px solid var(--blue);
    }
    .pp-selector-symbol { font-weight: 700; font-family: ui-monospace, monospace; }
    .pp-selector-meta { font-size: 11px; color: var(--muted); margin-top: 2px; }
    .pp-selector-breath { font-size: 11px; color: var(--blue); margin-top: 3px; }
    .pp-selector-held { border-left: 2px solid var(--blue); }
    .pp-selector-tag {
      font-size: 9px; font-weight: 700; color: var(--blue); border: 1px solid var(--blue);
      border-radius: 3px; padding: 0 3px; margin-left: 4px;
    }
    .pp-selector-tag-asset {
      font-size: 9px; font-weight: 700; color: var(--blue); border: 1px solid var(--blue);
      border-radius: 3px; padding: 0 3px; margin-left: 4px;
    }
    #profit-plan-main { min-width: 0; }
    #profit-plan-main .plan-card { display: none; }
    #profit-plan-main .plan-card.pp-active { display: block; }
    #profit-plan-detail-panel {
      background: rgba(17,26,46,.94); border: 1px solid var(--line);
      border-radius: 12px; padding: 16px; font-size: 13px;
      overflow-y: auto; max-height: calc(100vh - 140px);
    }
    @media (max-width: 900px) {
      #profit-plan-cockpit { grid-template-columns: 1fr; }
      #profit-plan-selector { max-height: 180px; }
    }
    .muted { color: var(--muted); } .small { font-size: 12px; }
    .watch-only-badge {
      font-size: 11px; font-weight: 700; letter-spacing: .06em;
      color: var(--muted); border: 1px solid var(--line);
      border-radius: 6px; padding: 4px 10px; display: inline-block; margin-bottom: 6px;
    }
    .watch-only-zone-notice { font-size: 11px; color: var(--muted); }
    .pipeline-warn { background:#fff3cd; border:1px solid #ffc107; border-radius:8px; padding:10px 16px; margin:8px 0; font-size:13px; font-weight:600; color:#856404; }
    .ok { color: var(--ok); } .warn { color: var(--warn); } .bad { color: var(--bad); }
    .accent { color: var(--accent); }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
    .card {
      background: rgba(17,26,46,.94); border: 1px solid var(--line);
      border-radius: 16px; padding: 16px;
      box-shadow: 0 12px 32px rgba(0,0,0,.22);
    }
    .card-head {
      display: flex; justify-content: space-between; align-items: flex-start;
      gap: 12px; padding-bottom: 10px; margin-bottom: 10px;
      border-bottom: 1px solid var(--line);
    }
    .card-head-left { display: flex; flex-direction: column; gap: 4px; min-width: 0; flex: 1 1 0; }
    .card-row1 { display: flex; align-items: baseline; gap: 6px; flex-wrap: wrap; }
    .card-symbol { font-size: 15px; font-weight: 700; }
    .scenario-badge {
      font-size: 12px; font-weight: 600; letter-spacing: .04em;
      padding: 4px 10px; border-radius: 8px; white-space: nowrap;
    }
    .badge-ext    { background: rgba(139,179,255,.15); color: var(--blue); border: 1px solid rgba(139,179,255,.3); }
    .badge-reentry{ background: rgba(255,209,102,.12); color: var(--warn); border: 1px solid rgba(255,209,102,.3); }
    .badge-range  { background: rgba(102,223,178,.12); color: var(--ok);  border: 1px solid rgba(102,223,178,.3); }
    .badge-bkout  { background: rgba(180,138,255,.12); color: var(--accent); border: 1px solid rgba(180,138,255,.3); }
    .badge-none   { background: rgba(147,164,194,.1);  color: var(--muted);  border: 1px solid var(--line); }
    .action-label {
      font-size: 13px; font-weight: 700; margin-top: 3px;
    }
    .action-tp   { color: var(--warn); }
    .action-buy  { color: var(--ok); }
    .action-watch{ color: var(--blue); }
    .action-wait { color: var(--muted); }
    .action-dont { color: var(--bad); }
    .tf-label { font-size: 11px; color: var(--muted); margin-top: 2px; }
    .wallet-held-badge {
      margin-left: auto; font-size: 10px; font-weight: 700; letter-spacing: .04em;
      color: var(--blue); border: 1px solid var(--blue); border-radius: 4px; padding: 2px 6px;
    }
    .portfolio-asset-badge {
      font-size: 10px; font-weight: 700; letter-spacing: .04em;
      color: var(--blue); border: 1px solid var(--blue); border-radius: 4px; padding: 2px 6px;
    }
    .card[data-wallet-held='true'] { border-left: 3px solid var(--blue); }
    .card[data-portfolio-asset='true'][data-wallet-held='false'] { border-left: 3px solid var(--blue); }
    /* Market rotation pressure — read-only projection (Issue #255). Kept
       visually distinct from wallet-held/portfolio-asset badges and from
       action/scenario metrics: its own group, its own colors. */
    .rotation-badge {
      display: inline-flex; align-items: center; gap: 6px; margin-top: 4px;
      font-size: 10px; font-weight: 700; letter-spacing: .04em;
      border-radius: 4px; padding: 2px 6px; width: fit-content;
    }
    .rotation-badge-in     { color: var(--ok);   border: 1px solid var(--ok); }
    .rotation-badge-out    { color: var(--bad);  border: 1px solid var(--bad); }
    .rotation-badge-mixed  { color: var(--warn); border: 1px solid var(--warn); }
    .rotation-badge-unavailable { color: var(--muted); border: 1px dashed var(--line); }
    .rotation-badge-score { font-variant-numeric: tabular-nums; }
    .rotation-strip {
      display: grid; grid-template-columns: minmax(200px,1fr) auto minmax(200px,1.2fr) auto auto;
      gap: 14px; align-items: center; margin: 10px 0; padding: 10px 14px;
      border: 1px solid var(--line); border-radius: 10px; background: rgba(0,0,0,.16);
    }
    .rotation-eyebrow { font-size: 10px; letter-spacing: .1em; color: var(--muted); }
    .rotation-headline { margin-top: 2px; font-size: 15px; font-weight: 700; }
    .rotation-score { margin-left: 6px; font-variant-numeric: tabular-nums; }
    .rotation-lights { display: flex; gap: 5px; }
    .rotation-light { width: 11px; height: 11px; border-radius: 50%; border: 1px solid var(--line); background: rgba(0,0,0,.2); }
    .rotation-light.active.light-in    { background: var(--ok); }
    .rotation-light.active.light-out   { background: var(--bad); }
    .rotation-light.active.light-mixed { background: var(--warn); }
    .rotation-metrics { display: flex; flex-wrap: wrap; gap: 6px; font-size: 11px; color: var(--muted); }
    .rotation-freshness-badge { font-size: 10px; padding: 3px 8px; border-radius: 999px; border: 1px solid var(--line); }
    .rotation-freshness-fresh { color: var(--ok); }
    .rotation-freshness-stale, .rotation-freshness-future_timestamp { color: var(--bad); }
    .rotation-source-ts { white-space: nowrap; }
    .rotation-degraded-note { grid-column: 1 / -1; font-size: 10px; color: var(--bad); }
    .rotation-unavailable { grid-template-columns: auto 1fr auto; }
    .rotation-unavailable-label { font-weight: 700; color: var(--muted); }
    .rotation-unavailable-reason { font-size: 10px; color: var(--muted); text-align: right; }
    .state-label { margin-top: 6px; font-size: 14px; font-weight: 700; }
    .state-secondary { margin-top: 3px; font-size: 11px; color: var(--muted); }
    .field-grid {
      display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px;
      margin: 10px 0;
    }
    .field-block {
      background: rgba(0,0,0,.16); border: 1px solid var(--line);
      border-radius: 10px; padding: 8px 10px;
    }
    .field-label {
      font-size: 10px; text-transform: uppercase; letter-spacing: .07em; color: var(--muted);
      margin-bottom: 3px;
    }
    .field-value { font-size: 13px; color: var(--text); }
    .plan-section { margin: 10px 0; }
    .section-heading {
      font-size: 10px; text-transform: uppercase; letter-spacing: .08em; color: var(--blue);
      font-weight: 700; margin-bottom: 6px;
    }
    .section-note { font-size: 11px; color: var(--muted); margin: 2px 0 6px; }
    .section-note.section-note-warn { color: var(--warn); }
    .evidence-domain-group { margin-bottom: 8px; }
    .evidence-domain-heading {
      font-size: 9px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted);
      margin: 6px 0 3px;
    }
    .market-breath-section {
      margin: 12px 0 10px;
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 10px;
      background: rgba(0,0,0,.18);
    }
    .market-breath-header {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: .08em;
      color: var(--blue);
      margin-bottom: 8px;
      font-weight: 700;
    }
    .market-breath-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      margin-bottom: 8px;
    }
    .market-breath-note { line-height: 1.4; }
    .breath-curve-disabled {
      opacity: .55; filter: grayscale(1);
      border-style: dashed;
    }
    .breath-curve-disabled .market-breath-header { color: var(--muted); }
    .breath-disabled-tag {
      font-size: 10px; font-weight: 700; letter-spacing: .05em;
      color: var(--muted); border: 1px solid var(--line); border-radius: 5px;
      padding: 1px 6px; margin-left: 6px; text-transform: none;
    }
    .zones {
      display: grid; grid-template-columns: 1fr 1fr; gap: 10px;
      margin: 10px 0;
    }
    .zone-block { background: rgba(0,0,0,.2); border-radius: 10px; padding: 8px 10px; }
    .zone-price { font-family: ui-monospace, monospace; font-size: 13px; margin: 2px 0; }
    .zone-buy  { border-left: 3px solid var(--ok); }
    .zone-sell { border-left: 3px solid var(--warn); }
    .zone-empty { color: var(--muted); font-size: 12px; }
    .reasons { margin: 8px 0; padding-left: 0; list-style: none; }
    .reasons li { font-size: 13px; color: var(--text); padding: 3px 0;
                  padding-left: 14px; position: relative; }
    .reasons li::before { content: "→"; position: absolute; left: 0; color: var(--muted); }
    .invalidation { font-size: 12px; color: var(--bad); margin-top: 4px; }
    .order-summary {
      border-top: 1px solid var(--line); margin-top: 10px; padding-top: 8px;
      font-size: 12px; color: var(--muted);
    }
    .order-row { display: flex; gap: 10px; margin-top: 3px; flex-wrap: wrap; }
    .order-chip {
      background: rgba(255,255,255,.04); border: 1px solid var(--line);
      border-radius: 6px; padding: 2px 7px; font-size: 11px; white-space: nowrap;
    }
    .order-chip.ok   { border-color: rgba(102,223,178,.35); color: var(--ok); }
    .order-chip.warn { border-color: rgba(255,209,102,.35); color: var(--warn); }
    .order-chip.miss { border-color: rgba(255,113,113,.3);  color: var(--bad); }
    .order-chip.muted{ color: var(--muted); }
    .monitor-link { font-size: 12px; color: var(--blue); margin-top: 6px; }
    .manual-only { font-size: 11px; color: var(--muted); margin-top: 4px; }
    .view-toggle {
      display: flex; gap: 6px; margin-top: 6px; align-items: center; flex-wrap: wrap;
    }
    .sticky-controls {
      position: sticky; top: 0; z-index: 10;
      background: rgba(8,13,24,.96); backdrop-filter: blur(10px);
      border-bottom: 1px solid var(--line); box-shadow: 0 2px 8px rgba(0,0,0,.3);
      padding: 6px 16px 8px;
    }
    .search-shell { display: none; align-items: center; gap: 8px; margin-top: 8px; flex-wrap: wrap; }
    .search-input {
      min-width: 260px; flex: 1 1 320px; background: rgba(255,255,255,.05); color: var(--text);
      border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; font-size: 13px;
    }
    .search-meta { font-size: 12px; color: var(--muted); }
    .filter-controls {
      display: flex; gap: 8px; margin-top: 6px; align-items: end; flex-wrap: wrap;
    }
    .filter-control {
      display: flex; flex-direction: column; gap: 3px;
      font-size: 10px; text-transform: uppercase; letter-spacing: .07em; color: var(--muted);
    }
    .filter-select {
      background: rgba(255,255,255,.05); color: var(--text);
      border: 1px solid var(--line); border-radius: 8px; padding: 6px 8px;
      font-size: 12px; min-width: 138px;
    }
    .filter-select option {
      background: #ffffff;
      color: #111827;
    }
    .filter-select option:checked {
      background: #2563eb;
      color: #ffffff;
    }

    .no-results {
      display: none; padding: 18px; border: 1px dashed var(--line); border-radius: 12px;
      color: var(--muted); grid-column: 1 / -1;
    }
    .toggle-btn {
      background: rgba(255,255,255,.06); border: 1px solid var(--line);
      color: var(--muted); border-radius: 8px; padding: 5px 14px;
      font-size: 13px; cursor: pointer; transition: all .15s;
    }
    .toggle-btn.active {
      background: rgba(139,179,255,.15); border-color: rgba(139,179,255,.4);
      color: var(--blue); font-weight: 600;
    }
    .toggle-btn:hover:not(.active) { background: rgba(255,255,255,.1); color: var(--text); }
    .quality-block { display: flex; align-items: center; gap: 6px; }
    .quality-badge {
      font-size: 10px; font-weight: 700; letter-spacing: .06em;
      padding: 2px 7px; border-radius: 6px; white-space: nowrap;
    }
    .quality-pass { background: rgba(102,223,178,.12); color: var(--ok);  border: 1px solid rgba(102,223,178,.3); }
    .quality-warn { background: rgba(255,209,102,.12); color: var(--warn); border: 1px solid rgba(255,209,102,.3); }
    .quality-fail { background: rgba(255,113,113,.12); color: var(--bad);  border: 1px solid rgba(255,113,113,.3); }
    .quality-nav  { background: rgba(122,171,255,.12); color: var(--accent, #7aabff); border: 1px solid rgba(122,171,255,.3); }
    .quality-reason { font-size: 11px; color: var(--muted); }
    .card-evidence {
      border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px;
      margin-top: 10px; font-size: 11px; background: rgba(255,255,255,.025);
    }
    .card-evidence.evidence-green { border-color: rgba(102,223,178,.35); background: rgba(102,223,178,.08); }
    .card-evidence.evidence-red { border-color: rgba(255,113,113,.40); background: rgba(255,113,113,.08); }
    .card-evidence.evidence-amber { border-color: rgba(255,209,102,.42); background: rgba(255,209,102,.08); }
    .card-evidence.evidence-neutral { border-color: var(--line); }
    .evidence-header { display:flex; justify-content:space-between; gap:10px; margin-bottom:6px; }
    .evidence-header strong { color: var(--ok); font-size: 11px; text-align:right; }
    .evidence-red .evidence-header strong { color: var(--bad); }
    .evidence-amber .evidence-header strong { color: var(--warn); }
    .evidence-grid {
      display:grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap:4px 10px;
    }
    .evidence-row { display:flex; justify-content:space-between; gap:8px; min-width:0; }
    .evidence-row span { color: var(--muted); }
    .evidence-row code { color: var(--text); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .evidence-delta { margin-top:6px; overflow-wrap:anywhere; }
    .evidence-authority-rows { display:flex; flex-direction:column; gap:6px; }
    .evidence-authority-row {
      border: 1px solid var(--line); border-radius: 6px; padding: 5px 7px;
      background: rgba(255,255,255,.02);
    }
    .evidence-authority-row-warn { border-color: rgba(255,209,102,.35); background: rgba(255,209,102,.06); }
    .evidence-authority-row-ok { border-color: rgba(102,223,178,.25); }
    .evidence-row-head { display:flex; justify-content:space-between; gap:8px; align-items:baseline; }
    .evidence-row-label { color: var(--muted); }
    .evidence-row-status { color: var(--text); overflow-wrap:anywhere; white-space:normal; text-align:right; }
    .evidence-row-authority { overflow-wrap:anywhere; white-space:normal; margin-top:2px; }
    .evidence-row-reasons { overflow-wrap:anywhere; white-space:normal; margin-top:2px; }
    .order-section { margin-top: 10px; }
    .order-section-header {
      display: flex; gap: 14px; align-items: baseline; flex-wrap: wrap;
      padding: 6px 0 6px; border-top: 1px solid var(--line); margin-bottom: 4px;
      font-size: 12px; color: var(--muted);
    }
    .order-section-header .event-label { font-weight: 600; color: var(--text); }
    .order-ladder { margin-top: 2px; }
    .order-ladder-label {
      font-size: 10px; text-transform: uppercase; letter-spacing: .07em;
      color: var(--muted); margin-bottom: 4px;
    }
    .order-ladder-row {
      display: grid;
      grid-template-columns: 18px 42px 1fr 64px 74px 1fr;
      align-items: center; gap: 6px;
      padding: 5px 8px; margin: 3px 0;
      border-radius: 8px; cursor: pointer; font-size: 12px;
    }
    .order-row-missing  { background: rgba(0,0,0,.14); border: 1px dashed rgba(147,164,194,.2); }
    .order-row-missing .order-row-side,
    .order-row-missing .order-row-price,
    .order-row-missing .order-row-dist { color: var(--muted); font-style: italic; }
    .order-row-armed    { background: rgba(102,223,178,.07); border: 1px solid rgba(102,223,178,.22); }
    .order-row-stale    { background: rgba(255,209,102,.07); border: 1px solid rgba(255,209,102,.2); }
    .order-row-historical{ background: rgba(0,0,0,.1);       border: 1px solid var(--line); opacity: .65; }
    .order-row-unavailable{ background: rgba(0,0,0,.1);      border: 1px dashed var(--line); opacity: .55; }
    .order-row-check { width: 14px; height: 14px; cursor: pointer; accent-color: var(--blue); }
    .order-row-side  { font-weight: 600; font-size: 11px; text-transform: uppercase; }
    .order-row-price { font-family: ui-monospace, monospace; }
    .order-row-dist  { font-family: ui-monospace, monospace; text-align: right; }
    .order-row-status{ font-size: 10px; font-weight: 700; letter-spacing: .04em; }
    .order-row-status.armed    { color: var(--ok); }
    .order-row-status.missing  { color: var(--muted); font-style: italic; }
    .order-row-status.stale    { color: var(--warn); }
    .order-row-status.historical{ color: var(--muted); }
    .order-row-status.unavailable{ color: var(--muted); }
    .order-row-status.above_current { color: var(--muted); font-style: italic; }
    .order-row-above-current { background: rgba(0,0,0,.1); border: 1px dashed var(--line); opacity: .6; }
    .order-row-reason { font-size: 11px; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .order-ladder-menu { display: flex; gap: 8px; margin-top: 6px; flex-wrap: wrap; }
    .disabled { opacity: .45; cursor: not-allowed; pointer-events: none; }
"""

def _build_client_js(storage_scope: str) -> str:
    storage_scope = esc(storage_scope or "default")
    return f"""
  var PP_QUERY_KEY = 'ppQuery:{storage_scope}';
  var PP_FILTER_KEY = 'ppFilters:{storage_scope}';

  function selectedValue(id) {{
    var el = document.getElementById(id);
    return el ? (el.value || '') : '';
  }}

  function setSelectedValue(id, value) {{
    var el = document.getElementById(id);
    if (el) el.value = value || '';
  }}

  function numericDataset(card, key, fallback) {{
    var v = parseFloat(card.dataset[key] || fallback);
    return isNaN(v) ? parseFloat(fallback) : v;
  }}

  function hasUsablePpp(card) {{
    return (card.dataset.sortPpp || '-999999') !== '-999999';
  }}

  function cardMatchesFilters(card, query) {{
    var hay = (card.dataset.search || '').toLowerCase();
    if (query && hay.indexOf(query) === -1) return false;

    var action = selectedValue('filter-action');
    var setup = selectedValue('filter-setup');
    var primary = selectedValue('filter-primary');
    var orders = selectedValue('filter-orders');

    if (action && card.dataset.filterAction !== action) return false;
    if (setup && card.dataset.filterSetup !== setup) return false;
    if (primary && card.dataset.filterPrimary !== primary) return false;
    if (orders && card.dataset.filterOrders !== orders) return false;

    return true;
  }}

  function sortCardsInDom(mode) {{
    var main = document.getElementById('profit-plan-main');
    if (!main) return;
    var cards = Array.prototype.slice.call(main.querySelectorAll('.plan-card'));
    var noResults = document.getElementById('no-results');

    cards.sort(function(a, b) {{
      if (mode === 'symbol_za') {{
        return (b.dataset.sortSymbol || '').localeCompare(a.dataset.sortSymbol || '');
      }}

      if (mode === 'symbol_az') {{
        return (a.dataset.sortSymbol || '').localeCompare(b.dataset.sortSymbol || '');
      }}

      if (mode === 'setup') {{
        var setupDelta = numericDataset(a, 'sortSetup', '999') - numericDataset(b, 'sortSetup', '999');
        if (setupDelta !== 0) return setupDelta;
        return (a.dataset.sortSymbol || '').localeCompare(b.dataset.sortSymbol || '');
      }}

      if (mode === 'ppp_asc' || mode === 'ppp_desc') {{
        var bucketDelta = numericDataset(a, 'workflowBucket', '999') - numericDataset(b, 'workflowBucket', '999');
        if (bucketDelta !== 0) return bucketDelta;

        var aHasPpp = hasUsablePpp(a);
        var bHasPpp = hasUsablePpp(b);
        if (aHasPpp !== bHasPpp) return aHasPpp ? -1 : 1;

        var aPpp = numericDataset(a, 'sortPpp', '-999999');
        var bPpp = numericDataset(b, 'sortPpp', '-999999');
        var pppDelta = mode === 'ppp_asc' ? (aPpp - bPpp) : (bPpp - aPpp);
        if (pppDelta !== 0) return pppDelta;

        return (a.dataset.sortSymbol || '').localeCompare(b.dataset.sortSymbol || '');
      }}

      var presentationDelta = numericDataset(a, 'sortPresentation', '999') - numericDataset(b, 'sortPresentation', '999');
      if (presentationDelta !== 0) return presentationDelta;

      var actionDelta = numericDataset(a, 'sortAction', '999') - numericDataset(b, 'sortAction', '999');
      if (actionDelta !== 0) return actionDelta;
      return (a.dataset.sortSymbol || '').localeCompare(b.dataset.sortSymbol || '');
    }});

    cards.forEach(function(card) {{ main.appendChild(card); }});
    if (noResults) main.appendChild(noResults);
  }}

  function applyFiltersAndSort() {{
    var queryInput = document.getElementById('candidate-search');
    var query = queryInput ? (queryInput.value || '').trim().toLowerCase() : '';
    var sortMode = selectedValue('sort-mode') || 'action';

    try {{ localStorage.setItem(PP_QUERY_KEY, query); }} catch(e) {{}}
    try {{
      localStorage.setItem(PP_FILTER_KEY, JSON.stringify({{
        action: selectedValue('filter-action'),
        setup: selectedValue('filter-setup'),
        primary: selectedValue('filter-primary'),
        orders: selectedValue('filter-orders'),
        sort: sortMode
      }}));
    }} catch(e) {{}}

    sortCardsInDom(sortMode);

    var total = 0;
    var matches = 0;
    document.querySelectorAll('.plan-card').forEach(function(card) {{
      total += 1;
      var match = cardMatchesFilters(card, query);
      card.style.display = match ? '' : 'none';
      if (match) matches += 1;
    }});

    var matching = document.getElementById('matching-count');
    if (matching) matching.textContent = 'Matching ' + matches + ' of ' + total;

    var noResults = document.getElementById('no-results');
    if (noResults) noResults.style.display = matches === 0 ? '' : 'none';

    syncProfitPlanCockpit();
  }}

  function setView(_mode) {{
    var btn = document.getElementById('btn-all');
    if (btn) btn.classList.add('active');
    var shell = document.getElementById('search-shell');
    if (shell) shell.style.display = 'flex';
    applyFiltersAndSort();
  }}

  function updateSearch() {{
    applyFiltersAndSort();
  }}

  function clearSearch() {{
    var queryInput = document.getElementById('candidate-search');
    if (queryInput) queryInput.value = '';
    applyFiltersAndSort();
  }}

  function resetProfitPlanFilters() {{
    setSelectedValue('filter-action', '');
    setSelectedValue('filter-setup', '');
    setSelectedValue('filter-primary', '');
    setSelectedValue('filter-orders', '');
    setSelectedValue('sort-mode', 'action');
    clearSearch();
  }}

  function buildProfitPlanSelector() {{
    var sel = document.getElementById('profit-plan-selector');
    if (!sel) return;
    var cards = Array.prototype.slice.call(
      document.querySelectorAll('#profit-plan-main .plan-card')
    );
    sel.innerHTML = '';
    var visible = cards.filter(function(c) {{ return c.style.display !== 'none'; }});
    if (visible.length === 0) {{
      sel.innerHTML = "<div class='pp-selector-item muted'>No matching cards</div>";
      return;
    }}
    // Wallet-held-first grouping is an action-priority-view convenience only.
    // For every other explicit sort mode (PPP asc/desc, symbol, setup) the
    // rail must stay in the exact DOM order sortCardsInDom already produced,
    // otherwise the rail silently disagrees with the card grid it mirrors.
    var sortMode = selectedValue('sort-mode') || 'action';
    if (sortMode === 'action') {{
      visible.sort(function(a, b) {{
        var aHeld = a.dataset.walletHeld === 'true' ? 0 : 1;
        var bHeld = b.dataset.walletHeld === 'true' ? 0 : 1;
        return aHeld - bHeld;
      }});
    }}
    visible.forEach(function(card) {{
      var item = document.createElement('div');
      var isWalletHeld = card.dataset.walletHeld === 'true';
      var isPortfolioAsset = card.dataset.portfolioAsset === 'true';
      item.className = 'pp-selector-item' + (isWalletHeld ? ' pp-selector-held' : '');
      item.dataset.renderId = card.dataset.renderId || '';
      var symbol = (card.dataset.sortSymbol || '?').toUpperCase();
      var action = card.dataset.filterActionLabel || card.dataset.filterAction || '';
      // Actionable PPP when eligible; otherwise fall back to Planning PPP so every
      // held token still shows a reference number (or its unavailable reason).
      var ppp = card.dataset.sortPpp && card.dataset.sortPpp !== '-999999'
        ? card.dataset.actionablePpp
        : card.dataset.planningPpp || '';
      var breath = card.dataset.bcCurrentCheckpoint || 'UNAVAILABLE';
      var trajectory = card.dataset.bcNextCheckpoint || 'UNAVAILABLE';
      var tags = (isWalletHeld ? " <span class='pp-selector-tag'>WALLET</span>" : '') +
        (isPortfolioAsset ? " <span class='pp-selector-tag-asset'>PORTFOLIO</span>" : '');
      item.innerHTML =
        "<div class='pp-selector-symbol'>" + symbol + tags + "</div>" +
        "<div class='pp-selector-meta'>" + action + (ppp ? ' \xb7 ' + ppp : '') + "</div>";
      item.addEventListener('click', function() {{
        selectProfitPlanCard(item.dataset.renderId);
      }});
      sel.appendChild(item);
    }});
  }}

  function _ppParseEvidenceRows(card) {{
    var raw = card.dataset.evidenceRows || '[]';
    try {{ return JSON.parse(raw) || []; }} catch(e) {{ return []; }}
  }}

  function _ppEvidenceRowByKey(rows, key) {{
    for (var i = 0; i < rows.length; i++) {{
      if (rows[i].key === key) return rows[i];
    }}
    return null;
  }}

  function _ppEscapeHtml(value) {{
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }}

  // Renders one normalized evidence-authority row in full: label, canonical
  // status, authority owner, observed timestamp (if any) and the COMPLETE
  // reason-code list — never truncated, per the P1 evidence-normalization rule.
  function _ppEvidenceRowHtml(row) {{
    if (!row) {{
      return "<div class='muted small' style='margin-bottom:10px'>DATA_UNAVAILABLE</div>";
    }}
    var observed = row.observed_ts ? (" \xb7 " + _ppEscapeHtml(row.observed_ts)) : "";
    var reasons = (row.reason_codes && row.reason_codes.length)
      ? "<div class='muted small'>Reasons: " + row.reason_codes.map(_ppEscapeHtml).join(', ') + "</div>"
      : "";
    return (
      "<div style='margin-bottom:2px'><strong>" + _ppEscapeHtml(row.status) + "</strong>" +
      "<span class='muted small'> \xb7 " + _ppEscapeHtml(row.authority) + observed + "</span></div>" +
      reasons
    );
  }}

  function _ppEvidenceSectionHtml(rows) {{
    return rows.map(function(row) {{
      return (
        "<div style='margin-bottom:10px'>" +
        "<div class='muted small'>" + _ppEscapeHtml(row.label) + "</div>" +
        _ppEvidenceRowHtml(row) +
        "</div>"
      );
    }}).join('');
  }}

  function _ppUpdateDetailPanel(card) {{
    var panel = document.getElementById('profit-plan-detail-panel');
    if (!panel) return;
    var symbol = (card.dataset.sortSymbol || '?').toUpperCase();
    var action = card.dataset.filterActionLabel || card.dataset.filterAction || '—';
    var setup = card.dataset.filterSetup || '—';
    var planningPpp = card.dataset.planningPpp || '—';
    var actionablePpp = card.dataset.actionablePpp || '—';
    var marketEl = card.querySelector('.card-row1 .muted.small');
    var market = marketEl ? marketEl.textContent.trim() : '';
    var evidenceRows = _ppParseEvidenceRows(card);
    panel.innerHTML =
      "<h3>" + symbol + "</h3>" +
      "<div class='small muted' style='margin-bottom:10px'>" + market + "</div>" +
      "<div style='margin-bottom:6px'><span class='muted small'>Action: </span>" + action + "</div>" +
      "<div style='margin-bottom:6px'><span class='muted small'>Setup: </span>" + setup + "</div>" +
      "<div style='margin-bottom:6px'><span class='muted small'>Planning PPP: </span>" + planningPpp + "</div>" +
      "<div style='margin-bottom:14px'><span class='muted small'>Actionable PPP: </span>" + actionablePpp + "</div>" +
      "<h3>Evidence</h3>" +
      "<div style='margin-bottom:6px'>" + _ppEvidenceSectionHtml(evidenceRows) + "</div>" +
      "<h3>Wallet</h3>" + _ppEvidenceRowHtml(_ppEvidenceRowByKey(evidenceRows, 'wallet_snapshot')) +
      "<h3>Position</h3>" + _ppEvidenceRowHtml(_ppEvidenceRowByKey(evidenceRows, 'position_snapshot')) +
      "<h3>Orders</h3>" + _ppEvidenceRowHtml(_ppEvidenceRowByKey(evidenceRows, 'open_order_snapshot')) +
      "<h3>Context</h3>" + _ppEvidenceRowHtml(_ppEvidenceRowByKey(evidenceRows, 'map_lifecycle'));
  }}

  function selectProfitPlanCard(renderId) {{
    document.querySelectorAll('#profit-plan-main .plan-card').forEach(function(card) {{
      card.classList.remove('pp-active');
    }});
    var active = document.querySelector(
      '#profit-plan-main .plan-card[data-render-id="' + renderId + '"]'
    );
    if (active) {{
      active.classList.add('pp-active');
      _ppUpdateDetailPanel(active);
    }}
    document.querySelectorAll('#profit-plan-selector .pp-selector-item').forEach(function(item) {{
      item.classList.toggle('active', item.dataset.renderId === renderId);
    }});
    try {{ localStorage.setItem('ppCard:' + PP_QUERY_KEY, renderId); }} catch(e) {{}}
  }}

  function syncProfitPlanCockpit() {{
    buildProfitPlanSelector();
    var cards = Array.prototype.slice.call(
      document.querySelectorAll('#profit-plan-main .plan-card')
    );
    var visible = cards.filter(function(c) {{ return c.style.display !== 'none'; }});
    var activeCard = document.querySelector('#profit-plan-main .plan-card.pp-active');
    if (activeCard && activeCard.style.display !== 'none') {{
      selectProfitPlanCard(activeCard.dataset.renderId || '');
      return;
    }}
    if (visible.length > 0) {{
      var savedId = '';
      try {{ savedId = localStorage.getItem('ppCard:' + PP_QUERY_KEY) || ''; }} catch(e) {{}}
      var target = savedId
        ? visible.filter(function(c) {{ return c.dataset.renderId === savedId; }})[0]
        : null;
      selectProfitPlanCard((target || visible[0]).dataset.renderId || '');
    }} else {{
      var panel = document.getElementById('profit-plan-detail-panel');
      if (panel) panel.innerHTML =
        "<div class='muted small'>No cards match the current filter.</div>" +
        "<h3>Wallet</h3><div class='muted small' style='margin-bottom:10px'>— placeholder —</div>" +
        "<h3>Position</h3><div class='muted small' style='margin-bottom:10px'>— placeholder —</div>" +
        "<h3>Orders</h3><div class='muted small' style='margin-bottom:10px'>— placeholder —</div>" +
        "<h3>Context</h3><div class='muted small' style='margin-bottom:10px'>— placeholder —</div>";
    }}
  }}

  function sortCards(mode) {{
    setSelectedValue('sort-mode', mode || 'action');
    applyFiltersAndSort();
  }}

  function selectLadderRows(renderIdStr, mode) {{
    var checks = document.querySelectorAll(
      '.order-ladder-row[data-render-id="' + renderIdStr + '"] .order-row-check'
    );
    checks.forEach(function(cb) {{
      var state = cb.dataset.state || '';
      if (mode === 'clear') {{
        cb.checked = false;
      }} else if (mode === 'actionable') {{
        cb.checked = (state === 'MISSING' || state === 'STALE');
      }}
    }});
  }}

  document.addEventListener('DOMContentLoaded', function() {{
    var shell = document.getElementById('search-shell');
    if (shell) shell.style.display = 'flex';

    var savedQuery = '';
    try {{ savedQuery = localStorage.getItem(PP_QUERY_KEY) || ''; }} catch(e) {{}}
    var queryInput = document.getElementById('candidate-search');
    if (queryInput) queryInput.value = savedQuery;

    try {{
      var saved = JSON.parse(localStorage.getItem(PP_FILTER_KEY) || '{{}}');
      setSelectedValue('filter-action', saved.action || '');
      setSelectedValue('filter-setup', saved.setup || '');
      setSelectedValue('filter-primary', saved.primary || '');
      setSelectedValue('filter-orders', saved.orders || '');
      setSelectedValue('sort-mode', saved.sort || 'action');
    }} catch(e) {{}}

    setView('all');
    syncProfitPlanCockpit();
  }});
"""

def esc(value: Any) -> str:
    if value is None:
        return ""
    return _html.escape(str(value))


def _scenario_display_label(scenario_type: str) -> str:
    return SCENARIO_DISPLAY_LABELS.get(scenario_type, scenario_type.replace("_", " "))


def _scenario_badge(scenario_type: str) -> str:
    cls_map = {
        "EXTENSION_RUNNER": "badge-ext",
        "REENTRY_WAIT":     "badge-reentry",
        "RANGE_BOUNCE":     "badge-range",
        "BREAKOUT_RETEST":  "badge-bkout",
    }
    cls = cls_map.get(scenario_type, "badge-none")
    return f"<span class='scenario-badge {cls}'>{esc(_scenario_display_label(scenario_type))}</span>"


def _action_class(action_label: str) -> str:
    if action_label in ("TAKE_PROFIT_NEAR", "REBUY_ZONE_NEAR"):
        return "action-tp"
    if action_label in ("BUY_DIP",):
        return "action-buy"
    if action_label in ("BREAKOUT_WATCH",):
        return "action-watch"
    if action_label in ("DO_NOT_TOUCH",):
        return "action-dont"
    return "action-wait"


def _state_class(state: str) -> str:
    if state in {"TAKE_PROFIT_WAITING", "RELOAD_ZONE_APPROACHING"}:
        return "action-tp"
    if state in {"INVALIDATION_NEAR", "ORDER_TOO_FAR_OR_STALE"}:
        return "action-dont"
    if state == "PRICE_RAN_AWAY":
        return "action-watch"
    return "action-wait"


def _zone_html(prices: tuple[Decimal, ...], side: str) -> str:
    if not prices:
        return "<div class='zone-empty'>No levels loaded</div>"
    cls = "zone-sell" if side == "sell" else "zone-buy"
    lines = "".join(
        f"<div class='zone-price mono'>{esc(_fmt_p(p))}</div>"
        for p in prices
    )
    return f"<div class='zone-block {cls}'>{lines}</div>"


def _target_lifecycle_html(target_levels: tuple[TargetLevelStatus, ...]) -> str:
    if not target_levels:
        return "<div class='zone-empty'>No target lifecycle loaded</div>"
    lines = []
    for level in target_levels:
        active_marker = " · active next target" if level.is_active_target else ""
        lines.append(
            "<div class='zone-price mono'>"
            f"{esc(_fmt_p(level.level))} — {esc(level.lifecycle_state)} / {esc(level.coverage_state)}{esc(active_marker)}"
            "</div>"
        )
        if level.retest_context:
            lines.append(
                f"<div class='small muted'>{esc(level.retest_context)}</div>"
            )
    return "<div class='zone-block zone-sell'>" + "".join(lines) + "</div>"


def _order_summary_html(
    summary: ActiveOrderSummary,
    monitor_link: str | None,
    *,
    open_orders_label: str,
    actionability_state: str,
) -> str:
    parts: list[str] = []
    summary_prefix = summary.existing_open_orders_summary
    if actionability_state != CARD_ACTIONABILITY_ACTIVE and summary_prefix != "No open orders linked":
        summary_prefix = f"Review only · {summary_prefix}"
    parts.append(f"<span class='order-chip muted'>{esc(summary_prefix)}</span>")
    if summary.matching_buys > 0:
        _buy_suffix = "near zone" if actionability_state == CARD_ACTIONABILITY_ACTIVE else "to review"
        parts.append(f"<span class='order-chip ok'>{summary.matching_buys} buy order{'s' if summary.matching_buys != 1 else ''} {_buy_suffix}</span>")
    if summary.matching_sells > 0:
        _sell_suffix = "near zone" if actionability_state == CARD_ACTIONABILITY_ACTIVE else "to review"
        parts.append(f"<span class='order-chip warn'>{summary.matching_sells} sell order{'s' if summary.matching_sells != 1 else ''} {_sell_suffix}</span>")
    for missing in summary.missing_suggested:
        label = missing if missing.startswith("missed sell level @ ") else f"missing: {missing}"
        parts.append(f"<span class='order-chip miss'>{esc(label)}</span>")
    if not parts:
        parts.append("<span class='order-chip muted'>No matching orders</span>")
    chips = " ".join(parts)
    link_html = ""
    if monitor_link:
        link_html = f"<div class='monitor-link'><a href='{esc(monitor_link)}' style='color:inherit'>→ Open Orders Monitor</a></div>"
    return (
        f"<div class='order-summary'>"
        f"<div style='margin-bottom:4px'>{esc(open_orders_label)}</div>"
        f"<div class='order-row'>{chips}</div>"
        f"{link_html}"
        f"</div>"
    )


def _metric_block(label: str, value: str) -> str:
    return (
        "<div class='field-block'>"
        f"<div class='field-label'>{esc(label)}</div>"
        f"<div class='field-value mono'>{esc(value)}</div>"
        "</div>"
    )


# ---------------------------------------------------------------------------
# Market rotation pressure — read-only projection rendering (Issue #255).
# This section never recomputes rotation score/direction/evidence-lights/
# breadth/rank/confirmation; it only displays verbatim persisted values
# already carried on RotationProfitPlanProjection / RotationMarketProjection.
# ---------------------------------------------------------------------------

_ROTATION_DIRECTION_LABELS: dict[str, str] = {
    "ROTATION_IN": "ROTATION IN",
    "ROTATION_OUT": "ROTATION OUT",
    "MIXED": "MIXED",
}


def _rotation_direction_label(direction: str | None) -> str:
    if direction is None:
        return "ROTATION DATA UNAVAILABLE"
    return _ROTATION_DIRECTION_LABELS.get(direction, direction.replace("_", " "))


def _rotation_lights_html(evidence_light_count: int | None, direction: str | None) -> str:
    # Mirrors market_rotation_pressure_dashboard_v1._lights_html rendering
    # convention (5 dots, active count = persisted evidence_light_count).
    # Never recomputes the count; renders it verbatim.
    direction_class = {
        "ROTATION_IN": "light-in",
        "ROTATION_OUT": "light-out",
        "MIXED": "light-mixed",
    }.get(direction or "", "light-mixed")
    count = evidence_light_count if evidence_light_count is not None else 0
    lights = []
    for index in range(5):
        active = index < count
        classes = f"rotation-light {'active ' + direction_class if active else ''}".strip()
        lights.append(f"<span class='{classes}' aria-label='rotation evidence light {index + 1}'></span>")
    return "".join(lights)


def _rotation_strip_html(projection: RotationProfitPlanProjection | None) -> str:
    if projection is None or not projection.available:
        reason = (projection.reason if projection is not None else None) or "NO_ROTATION_PROJECTION"
        state = "STALE" if projection is not None and projection.freshness == "STALE" else "UNAVAILABLE"
        label = "ROTATION DATA STALE" if state == "STALE" else "ROTATION DATA UNAVAILABLE"
        return (
            "<section class='rotation-strip rotation-unavailable'>"
            "<div class='rotation-eyebrow'>MARKET ROTATION PRESSURE</div>"
            f"<div class='rotation-unavailable-label'>{esc(label)}</div>"
            f"<div class='rotation-unavailable-reason'>{esc(reason)}</div>"
            "</section>"
        )
    freshness_class = f"rotation-freshness-{projection.freshness.lower()}"
    direction_class = f"rotation-direction-{(projection.aggregate_direction or 'unknown').lower()}"
    score_text = (
        f"{projection.aggregate_score:+.1f}" if projection.aggregate_score is not None else "—"
    )
    source_ts_text = (
        projection.source_ts_utc.isoformat(timespec="seconds") + "Z"
        if projection.source_ts_utc is not None
        else "—"
    )
    metrics = []
    if projection.positive_breadth_ratio is not None:
        metrics.append(f"<span>IN {projection.positive_breadth_ratio:.0%}</span>")
    if projection.negative_breadth_ratio is not None:
        metrics.append(f"<span>OUT {projection.negative_breadth_ratio:.0%}</span>")
    if projection.acceleration_state:
        metrics.append(f"<span>{esc(projection.acceleration_state.replace('_', ' '))}</span>")
    if projection.confirmation_state:
        metrics.append(f"<span>{esc(projection.confirmation_state)}</span>")
    if projection.concentration_state:
        metrics.append(f"<span>{esc(projection.concentration_state)}</span>")
    degraded_note = (
        f"<div class='rotation-degraded-note'>{esc(projection.freshness)}: {esc(projection.reason or '')}</div>"
        if projection.freshness != "FRESH"
        else ""
    )
    return (
        f"<section class='rotation-strip {direction_class}'>"
        "<div class='rotation-head'>"
        "<div class='rotation-eyebrow'>MARKET ROTATION PRESSURE — market-only, account-agnostic, not verified fund flow</div>"
        f"<div class='rotation-headline'>{esc(_rotation_direction_label(projection.aggregate_direction))}"
        f" <span class='rotation-score'>{esc(score_text)}</span></div>"
        "</div>"
        f"<div class='rotation-lights' aria-label='evidence lights'>{_rotation_lights_html(projection.evidence_light_count, projection.aggregate_direction)}</div>"
        f"<div class='rotation-metrics'>{''.join(metrics)}</div>"
        f"<div class='rotation-freshness-badge {esc(freshness_class)}'>{esc(projection.freshness)}</div>"
        f"<div class='rotation-source-ts muted small'>Snapshot {esc(source_ts_text)}</div>"
        f"{degraded_note}"
        "</section>"
    )


def _rotation_card_badge_html(market_projection: Any) -> str:
    if market_projection is None or not market_projection.available:
        label = "ROTATION DATA STALE" if (
            market_projection is not None and market_projection.freshness == "STALE"
        ) else "ROTATION DATA UNAVAILABLE"
        title = (market_projection.reason if market_projection is not None else None) or "No rotation context"
        return (
            f"<div class='rotation-badge rotation-badge-unavailable' title='{esc(title)}'>{esc(label)}</div>"
        )
    direction = market_projection.pressure_state
    label = _rotation_direction_label(direction)
    freshness_suffix = "" if market_projection.freshness == "FRESH" else f" · {esc(market_projection.freshness)}"
    score_text = (
        f"{market_projection.score_total:+.1f}" if market_projection.score_total is not None else "—"
    )
    direction_css = {
        "ROTATION_IN": "rotation-badge-in",
        "ROTATION_OUT": "rotation-badge-out",
        "MIXED": "rotation-badge-mixed",
    }.get(direction or "", "rotation-badge-mixed")
    return (
        f"<div class='rotation-badge {direction_css}' title='Persisted market rotation pressure context, read-only'>"
        f"{esc(label)} <span class='rotation-badge-score'>{esc(score_text)}</span>{esc(freshness_suffix)}"
        "</div>"
    )


# ---------------------------------------------------------------------------
# Order ladder rows (Commit 3)
# ---------------------------------------------------------------------------

_ORDER_ROW_STATE_CSS: dict[str, str] = {
    "MISSING": "order-row-missing",
    "ARMED": "order-row-armed",
    "STALE": "order-row-stale",
    "HISTORICAL": "order-row-historical",
    "DATA_UNAVAILABLE": "order-row-unavailable",
    "ABOVE_CURRENT_BUY": "order-row-above-current",
}


def build_order_rows(
    *,
    card_render_id: str,
    actionability_state: str = CARD_ACTIONABILITY_ACTIVE,
    current_price: Decimal | None,
    buy_zone: tuple[Decimal, ...],
    target_level_statuses: tuple[TargetLevelStatus, ...],
    buy_orders: tuple[Any, ...],
    sell_orders: tuple[Any, ...],
) -> tuple[OrderRow, ...]:
    rows: list[OrderRow] = []
    covered_sell_order_prices: set[str] = set()
    covered_buy_order_prices: set[str] = set()

    # One row per active sell target level
    for level in target_level_statuses:
        if level.lifecycle_state not in {"UPCOMING", "NEAR"}:
            continue
        matching = [
            o for o in sell_orders
            if _near(o.limit_price, level.level, ORDER_MATCH_TOLERANCE_PCT)
        ]
        dist = _distance_to_level_pct(current_price, level.level)
        zone_role = f"sell target {_fmt_p(level.level)} ({level.lifecycle_state})"
        if matching:
            for o in matching:
                covered_sell_order_prices.add(str(o.limit_price))
            state = "ARMED"
            reason_code = "SELL_ORDER_AT_ACTIVE_TARGET"
            reason_label = (
                f"Sell order at active target {_fmt_p(level.level)} "
                f"({level.lifecycle_state}); "
                f"distance {_pct(dist)} from {_fmt_p(current_price)}"
            )
        elif actionability_state == CARD_ACTIONABILITY_ACTIVE:
            state = "MISSING"
            reason_code = "NO_SELL_ORDER_AT_ACTIVE_TARGET"
            reason_label = (
                f"No sell order at active target {_fmt_p(level.level)} "
                f"({level.lifecycle_state}); "
                f"distance {_pct(dist)} from {_fmt_p(current_price)}"
            )
        else:
            state = "HISTORICAL"
            reason_code = "NO_ACTIVE_ORDER_REFERENCE_ONLY"
            reason_label = (
                f"No sell order at {_fmt_p(level.level)} ({level.lifecycle_state}) — "
                f"reference only; card is {actionability_state}"
            )
        rows.append(OrderRow(
            row_id=str(uuid.uuid4()),
            render_id=card_render_id,
            state=state,
            reason_code=reason_code,
            reason_label=reason_label,
            side="sell",
            price=level.level,
            distance_pct=dist,
            zone_role=zone_role,
        ))

    # One row per buy zone level
    for buy_level in buy_zone:
        matching = [
            o for o in buy_orders
            if _near(o.limit_price, buy_level, ORDER_MATCH_TOLERANCE_PCT)
        ]
        dist = _distance_to_level_pct(current_price, buy_level)
        zone_role = f"buy zone {_fmt_p(buy_level)}"
        if matching:
            for o in matching:
                covered_buy_order_prices.add(str(o.limit_price))
            state = "ARMED"
            reason_code = "BUY_ORDER_AT_ZONE"
            reason_label = (
                f"Buy order at reload zone {_fmt_p(buy_level)}; "
                f"distance {_pct(dist)} from {_fmt_p(current_price)}"
            )
        elif actionability_state == CARD_ACTIONABILITY_ACTIVE and current_price is not None and buy_level >= current_price:
            state = "ABOVE_CURRENT_BUY"
            reason_code = "BUY_ABOVE_CURRENT_PRICE"
            reason_label = (
                f"Buy reload level is above current price — reference only. "
                f"Level {_fmt_p(buy_level)} is at or above current {_fmt_p(current_price)}"
            )
        elif actionability_state == CARD_ACTIONABILITY_ACTIVE:
            state = "MISSING"
            reason_code = "NO_BUY_ORDER_AT_ZONE"
            reason_label = (
                f"No buy order at reload zone {_fmt_p(buy_level)}; "
                f"distance {_pct(dist)} from {_fmt_p(current_price)}"
            )
        else:
            state = "HISTORICAL"
            reason_code = "NO_ACTIVE_ORDER_REFERENCE_ONLY"
            reason_label = (
                f"No buy order at reload zone {_fmt_p(buy_level)} — "
                f"reference only; card is {actionability_state}"
            )
        rows.append(OrderRow(
            row_id=str(uuid.uuid4()),
            render_id=card_render_id,
            state=state,
            reason_code=reason_code,
            reason_label=reason_label,
            side="buy",
            price=buy_level,
            distance_pct=dist,
            zone_role=zone_role,
        ))

    # Remaining sell orders not at any active target → HISTORICAL or STALE
    for o in sell_orders:
        if str(o.limit_price) in covered_sell_order_prices:
            continue
        classification = _classify_order_for_zone_coverage(
            o.limit_price, target_level_statuses, buy_zone
        )
        dist = _distance_to_level_pct(current_price, o.limit_price)
        if classification == "HISTORICAL":
            state = "HISTORICAL"
            if actionability_state == CARD_ACTIONABILITY_ACTIVE:
                reason_code = "SELL_ORDER_AT_PASSED_TARGET"
                reason_label = (
                    f"Sell order at {_fmt_p(o.limit_price)} is at a passed/completed target; "
                    f"distance {_pct(dist)} from {_fmt_p(current_price)}"
                )
            else:
                reason_code = "MAP_COMPLETED_ORDER_REVIEW_NEEDED"
                reason_label = (
                    f"Review existing sell order at {_fmt_p(o.limit_price)} against a historical/passed target; "
                    f"distance {_pct(dist)} from {_fmt_p(current_price)}"
                )
            zone_role = "passed sell target"
        else:
            state = "STALE"
            if actionability_state == CARD_ACTIONABILITY_ACTIVE:
                reason_code = "SELL_ORDER_NOT_AT_ANY_ZONE"
                reason_label = (
                    f"Sell order at {_fmt_p(o.limit_price)} does not match any active zone "
                    f"(tolerance {ORDER_MATCH_TOLERANCE_PCT}%); "
                    f"distance {_pct(dist)} from {_fmt_p(current_price)}"
                )
                zone_role = "unmatched sell order"
            else:
                reason_code = "STALE_FOR_ACTIVE_SHORT_SWING"
                reason_label = (
                    f"Review existing sell order at {_fmt_p(o.limit_price)} — it does not match the current "
                    f"active short-swing map and is reference only here."
                )
                zone_role = "review unmatched sell order"
        rows.append(OrderRow(
            row_id=str(uuid.uuid4()),
            render_id=card_render_id,
            state=state,
            reason_code=reason_code,
            reason_label=reason_label,
            side="sell",
            price=o.limit_price,
            distance_pct=dist,
            zone_role=zone_role,
        ))

    # Remaining buy orders not at any zone → STALE
    for o in buy_orders:
        if str(o.limit_price) in covered_buy_order_prices:
            continue
        dist = _distance_to_level_pct(current_price, o.limit_price)
        if actionability_state == CARD_ACTIONABILITY_ACTIVE:
            reason_code = "BUY_ORDER_NOT_AT_ANY_ZONE"
            reason_label = (
                f"Buy order at {_fmt_p(o.limit_price)} does not match any reload zone "
                f"(tolerance {ORDER_MATCH_TOLERANCE_PCT}%); "
                f"distance {_pct(dist)} from {_fmt_p(current_price)}"
            )
            zone_role = "unmatched buy order"
        else:
            reason_code = "RUNNER_REFERENCE_ONLY"
            reason_label = (
                f"Review existing buy order at {_fmt_p(o.limit_price)} — reference only until a fresh active map exists."
            )
            zone_role = "review unmatched buy order"
        rows.append(OrderRow(
            row_id=str(uuid.uuid4()),
            render_id=card_render_id,
            state="STALE",
            reason_code=reason_code,
            reason_label=reason_label,
            side="buy",
            price=o.limit_price,
            distance_pct=dist,
            zone_role=zone_role,
        ))

    return tuple(rows)


_ORDER_ROW_STATUS_LABEL: dict[str, str] = {
    "ARMED":             "Armed",
    "MISSING":           "No order",
    "STALE":             "Stale",
    "HISTORICAL":        "Past level",
    "DATA_UNAVAILABLE":  "Unavailable",
    "ABOVE_CURRENT_BUY": "Above current",
}

_ORDER_ROW_STATUS_CSS_CLASS: dict[str, str] = {
    "ARMED":             "armed",
    "MISSING":           "missing",
    "STALE":             "stale",
    "HISTORICAL":        "historical",
    "DATA_UNAVAILABLE":  "unavailable",
    "ABOVE_CURRENT_BUY": "above_current",
}


def _order_rows_html(
    order_rows: tuple[OrderRow, ...],
    *,
    card_render_id: str,
    actionability_state: str = CARD_ACTIONABILITY_ACTIVE,
) -> str:
    if not order_rows:
        return ""
    has_actionable = (
        actionability_state == CARD_ACTIONABILITY_ACTIVE
        and any(r.state in {"MISSING", "STALE"} for r in order_rows)
    )
    rows_html = []
    for row in order_rows:
        css = _ORDER_ROW_STATE_CSS.get(row.state, "order-row-unavailable")
        price_str = _eur(row.price) if row.price else "?"
        dist_str = _pct(row.distance_pct)
        status_label = _ORDER_ROW_STATUS_LABEL.get(row.state, row.state.replace("_", " ").title())
        status_cls = _ORDER_ROW_STATUS_CSS_CLASS.get(row.state, "unavailable")
        tooltip = esc(row.reason_label)
        rows_html.append(
            f"<label class='order-ladder-row {css}'"
            f" title='{tooltip}'"
            f" data-row-id='{esc(row.row_id)}'"
            f" data-state='{esc(row.state)}'"
            f" data-render-id='{esc(card_render_id)}'>"
            f"<input type='checkbox' class='order-row-check'"
            f" data-row-id='{esc(row.row_id)}' data-state='{esc(row.state)}'>"
            f"<span class='order-row-side'>{esc(row.side.upper())}</span>"
            f"<span class='order-row-price mono'>{esc(price_str)}</span>"
            f"<span class='order-row-dist'>{esc(dist_str)}</span>"
            f"<span class='order-row-status {status_cls}'>{esc(status_label)}</span>"
            f"<span class='order-row-reason'>{esc(row.zone_role)}</span>"
            f"</label>"
        )
    select_menu = (
        "<div class='order-ladder-menu'>"
        f"<button class='toggle-btn small' onclick='selectLadderRows(\"{esc(card_render_id)}\",\"actionable\")'>Select missing / stale</button>"
        f"<button class='toggle-btn small' onclick='selectLadderRows(\"{esc(card_render_id)}\",\"clear\")'>Clear selection</button>"
        f"<button class='toggle-btn small disabled' disabled title='Read-only snapshot — no broker calls'>Fix selected (offline)</button>"
        "</div>"
        if has_actionable else ""
    )
    return (
        "<div class='order-ladder'>"
        "<div class='order-ladder-label'>Order ladder</div>"
        + "".join(rows_html)
        + select_menu
        + "</div>"
    )


def render_plan_card(
    card: ProfitPlanCard,
    *,
    monitor_link: str | None = None,
    buy_orders: tuple[Any, ...] = (),
    sell_orders: tuple[Any, ...] = (),
    rotation_market_projection: Any | None = None,
) -> str:
    quote = card.market.split("-")[-1] if "-" in card.market else ""
    search_text = build_card_search_text(card)
    rotation_badge_html = _rotation_card_badge_html(rotation_market_projection)
    breath_curve_payload = card.breath_curve or {}

    # Quality aggregation (replaces separate FRESH_CURRENT_PRICE / NATIVE_SHORT display)
    quality_state, quality_reason = _card_quality_state(card)
    quality_css = f"quality-{quality_state.lower()}"
    quality_html = (
        f"<div class='quality-block'>"
        f"<span class='quality-badge {quality_css}'>{esc(quality_state)}</span>"
        + (f"<span class='quality-reason'>{esc(quality_reason)}</span>" if quality_reason else "")
        + "</div>"
    )

    # Merged value + distance fields
    price_line = format_current_price_line(card.current_price, card.current_price_age_min, quote)
    reentry_label, target_label, order_ladder_label, open_orders_label, reentry_line, target_line = (
        _actionability_display_bundle(card)
    )
    invalidation_line = format_invalidation_line(card.invalidation_risk_zone, card.distance_to_invalidation_pct)
    planning_ppp_text = _format_planning_ppp(card)
    actionable_ppp_text = _format_actionable_ppp(card)
    # Two independent facts, both may render at once: is_wallet_held = a
    # positive amount in the latest persisted wallet snapshot;
    # is_portfolio_asset = configured strategic portfolio/rotation
    # membership, independent of current balance.
    badge_html_parts = []
    if card.is_wallet_held:
        badge_html_parts.append(
            "<span class='wallet-held-badge' title='Positive amount in the latest persisted wallet snapshot'>WALLET</span>"
        )
    if card.is_portfolio_asset:
        badge_html_parts.append(
            "<span class='portfolio-asset-badge' title='Configured strategic portfolio/rotation asset'>PORTFOLIO</span>"
        )
    portfolio_badge_html = "".join(badge_html_parts)

    event_label = STATE_LABELS.get(card.event_state, card.event_state.replace("_", " "))

    # Single source of truth for map/account/order evidence status text used
    # both by the grouped Evidence section below and by the domain-labeled
    # summary lines in Fibonacci Levels / Account & Position (Issue #347).
    # This is a pure display reorganization — no status is recomputed here,
    # only read from the already-built evidence rows.
    evidence_rows = build_card_evidence_rows(card)
    _evidence_by_key = {row.key: row for row in evidence_rows}
    _map_selection_row = _evidence_by_key.get("current_map_selection")
    _map_lifecycle_row = _evidence_by_key.get("map_lifecycle")
    _position_row = _evidence_by_key.get("position_snapshot")
    _wallet_row = _evidence_by_key.get("wallet_snapshot")

    # --- Summary (compact, top-level) ---------------------------------
    summary_blocks = [
        _metric_block("Current price", price_line),
        _metric_block("Setup", card.setup_state),
        _metric_block("Actionability", card.actionability_state),
    ]
    if card.short_context_display_state in {
        "TRANSIENT_NON_CANONICAL_SHORT_CONTEXT",
        SHORT_CONTEXT_DISPLAY_CANONICAL_NAVIGATION_AVAILABLE,
    }:
        summary_blocks.append(
            _metric_block("Map context", _short_context_display_label(card.short_context_display_state))
        )
    if card.presentation_mode in _NO_ACCOUNT_STATE_MODES:
        summary_blocks.append(_metric_block("Market event", event_label))
    summary_html = "".join(summary_blocks)

    # --- Fibonacci Levels (market/map fields only) ---------------------
    invalidation_label = (
        "Non-canonical reference invalidation"
        if card.actionability_state == CARD_ACTIONABILITY_CONTEXT_UNAVAILABLE
        else "Invalidation"
    )
    fib_blocks = [
        _metric_block(reentry_label, reentry_line),
        _metric_block(target_label, target_line),
        _metric_block(invalidation_label, invalidation_line),
        _metric_block("Planning PPP", planning_ppp_text),
        _metric_block("Actionable PPP", actionable_ppp_text),
    ]
    if _map_selection_row is not None:
        fib_blocks.append(
            _metric_block("Selected Fibonacci map", _operator_map_selection_text(_map_selection_row))
        )
    if _map_lifecycle_row is not None:
        fib_blocks.append(
            _metric_block("Fibonacci map lifecycle", _operator_map_lifecycle_text(_map_lifecycle_row))
        )
    fib_section_html = (
        "<div class='plan-section fib-levels-section'>"
        "<div class='section-heading'>Fibonacci Levels</div>"
        f"<div class='field-grid'>{''.join(fib_blocks)}</div>"
        "</div>"
    )

    # --- Account / Position (held amount/value/cost basis, wallet, ------
    # position-tracking freshness). Rendered whenever the card has an
    # account context at all (not for pure watch-only/market-selected
    # no-account cards), so the position-tracking-vs-wallet distinction is
    # visible even when nothing is held yet.
    account_blocks: list[str] = []
    if card.is_wallet_held:
        account_blocks.extend((
            _metric_block("Held amount", card.evidence.held_amount),
            _metric_block("Held value (EUR)", card.evidence.held_eur_value),
            _metric_block("Cost basis (EUR)", card.evidence.cost_basis_price_eur),
        ))
    if _wallet_row is not None:
        account_blocks.append(_metric_block("Wallet snapshot", _wallet_row.status))
    if _position_row is not None:
        account_blocks.append(_metric_block("Position snapshot", _position_row.status))
    account_section_html = ""
    if account_blocks:
        # Held amount/value/cost basis are sourced from the wallet balance
        # snapshot (trading_account_balance_snapshot / held_amount_by_symbol).
        # "Position snapshot" is a separate position-tracking authority
        # (account_position_snapshot) that can independently be unavailable —
        # the two facts are not in conflict, they come from different
        # upstream sources. Make that distinction explicit rather than
        # implying a contradiction.
        position_note_html = ""
        if (
            card.is_wallet_held
            and _position_row is not None
            and _position_row.status != "FRESH"
        ):
            position_note_html = (
                "<div class='section-note section-note-warn'>"
                "Held amount is from the wallet balance snapshot. Position-tracking "
                "snapshot (separate source) is unavailable — this is a known gap in "
                "the upstream position-tracking data, not a contradiction."
                "</div>"
            )
        account_section_html = (
            "<div class='plan-section account-section'>"
            "<div class='section-heading'>Account / Position</div>"
            f"{position_note_html}"
            f"<div class='field-grid'>{''.join(account_blocks)}</div>"
            "</div>"
        )

    # Build order rows (needed for FIX LADDER override).
    # Watch-only cards have no account orders; skip to avoid MISSING states on zone levels.
    # For completed maps, old re-entry levels are historical — omit from actionable order rows.
    _order_buy_zone = () if card.all_sell_targets_completed else card.buy_zone
    if card.presentation_mode in _NO_ACCOUNT_STATE_MODES:
        order_rows = ()
    else:
        order_rows = build_order_rows(
            card_render_id=card.render_id,
            actionability_state=card.actionability_state,
            current_price=card.current_price,
            buy_zone=_order_buy_zone,
            target_level_statuses=card.target_level_statuses,
            buy_orders=buy_orders,
            sell_orders=sell_orders,
        )
    displayed_action = "NO ACCOUNT ACTION" if card.presentation_mode in _NO_ACCOUNT_STATE_MODES else _effective_workflow_action(card)
    presentation_sort_value = _presentation_mode_sort_rank(card)
    action_sort_value = _card_action_sort_value(card)
    setup_sort_value = _setup_sort_priority(card)
    # data-sort-ppp carries Actionable PPP only — Planning PPP must never drive ranking.
    actionable_ppp_pct = _actionable_ppp(card)
    planning_ppp_pct = _planning_ppp(card)
    ppp_sort_value = actionable_ppp_pct if actionable_ppp_pct is not None else Decimal("-999999")
    planning_ppp_attr = _pct(planning_ppp_pct) if planning_ppp_pct is not None else "—"
    actionable_ppp_attr = _pct(actionable_ppp_pct) if actionable_ppp_pct is not None else "—"
    map_switch_review_attr = str(_map_switch_review_required(card)).lower()
    native_map_status_attr = _native_map_status(card)
    workflow_sort_bucket = _workflow_sort_bucket(card)

    # Event + order-ladder state above order ladder.
    # Keep internal ladder_states for data/tests, but render one deterministic user-facing status.
    if card.presentation_mode in _NO_ACCOUNT_STATE_MODES:
        filter_action_label = ""
        filter_action_value = ""
    else:
        filter_action_label = _filter_display_label(displayed_action)
        filter_action_value = _filter_value_from_label(filter_action_label)
    filter_setup_label = _filter_display_label(card.setup_state)
    filter_primary_label = _filter_display_label(card.primary_state)
    if card.presentation_mode in _NO_ACCOUNT_STATE_MODES:
        order_ladder_status = "NOT_APPLICABLE"
        filter_order_label = "Not applicable"
        filter_order_value = "not_applicable"
    else:
        order_ladder_status = _order_ladder_display_status(card.ladder_states)
        filter_order_label = _filter_display_label(order_ladder_status)
        filter_order_value = _filter_value_from_label(filter_order_label)

    # Order-domain secondary state ("Order too far or stale") belongs in the
    # Orders section, not in the top-level card summary (Issue #347). All
    # other secondary states are market/map-domain and stay in the compact
    # top summary as a concise high-level alert.
    secondary_state_html = ""
    order_secondary_state_html = ""
    if card.secondary_state is not None:
        secondary_state_label = esc(STATE_LABELS.get(card.secondary_state, card.secondary_state))
        if card.secondary_state == "ORDER_TOO_FAR_OR_STALE":
            order_secondary_state_html = f"<div class='state-secondary'>{secondary_state_label}</div>"
        else:
            secondary_state_html = f"<div class='state-secondary'>Secondary: {secondary_state_label}</div>"

    # Order section and open-orders summary: suppressed for no-account-state cards.
    if card.presentation_mode in _NO_ACCOUNT_STATE_MODES:
        if card.presentation_mode == CARD_MODE_WATCH_ONLY_ROTATION:
            _no_account_badge = "WATCH ONLY · NO POSITION · NO ACCOUNT ACTION"
        else:
            _no_account_badge = "MARKET SELECTED · NO POSITION · NO ACCOUNT ACTION"
        order_section_html = (
            "<div class='order-section'>"
            f"<div class='watch-only-badge'>{esc(_no_account_badge)}</div>"
            "<div class='watch-only-zone-notice'>Market zones are shown in the field grid above."
            " No account orders for this asset.</div>"
            "</div>"
        )
        open_orders_html = ""
    else:
        order_section_header = (
            "<div class='order-section-header'>"
            f"<span>Event: <span class='event-label'>{esc(event_label)}</span></span>"
            f"<span>Order ladder: {esc(order_ladder_status)}</span>"
            "</div>"
        )
        order_rows_html = _order_rows_html(
            order_rows,
            card_render_id=card.render_id,
            actionability_state=card.actionability_state,
        ).replace("Order ladder", order_ladder_label, 1)
        order_section_html = (
            f"<div class='order-section'>"
            f"{order_section_header}"
            f"{order_secondary_state_html}"
            f"{order_rows_html}"
            f"</div>"
        )
        open_orders_html = _order_summary_html(
            card.order_summary,
            monitor_link,
            open_orders_label=open_orders_label,
            actionability_state=card.actionability_state,
        )

    reasons_html = "".join(f"<li>{esc(r)}</li>" for r in card.reasons)
    # evidence_rows already built above (single source of truth for both the
    # Fibonacci/Account summary lines and the grouped Evidence section).
    evidence_html = _card_evidence_html(evidence_rows, card)
    evidence_rows_json_attr = json.dumps(evidence_rows_to_json(evidence_rows), separators=(",", ":"))

    # Primary-action consistency: a card has exactly one primary action. When a
    # stronger workflow override is shown, do not also render a weak no-op market
    # state ("Do nothing") that would read as a second, conflicting action.
    state_label_text = card.suggested_manual_attention_label
    if displayed_action == "MAP SWITCH REVIEW":
        state_label_text = "Review map"
    elif (
        displayed_action in _STRONG_OVERRIDE_ACTIONS
        and card.primary_state in _WEAK_NOOP_PRIMARY_STATES
    ):
        state_label_text = ""
    state_label_html = (
        f"<div class='state-label {_state_class(card.primary_state)}'>{esc(state_label_text)}</div>"
        if state_label_text
        else ""
    )

    return (
        f"<section class='card plan-card'"
        f" data-attention='{str(card.is_relevant).lower()}'"
        f" data-search='{esc(search_text)}'"
        f" data-filter-action='{esc(filter_action_value)}'"
        f" data-filter-action-label='{esc(filter_action_label)}'"
        f" data-filter-setup='{esc(card.setup_state)}'"
        f" data-filter-setup-label='{esc(filter_setup_label)}'"
        f" data-filter-primary='{esc(card.primary_state)}'"
        f" data-filter-primary-label='{esc(filter_primary_label)}'"
        f" data-filter-orders='{esc(filter_order_value)}'"
        f" data-filter-orders-label='{esc(filter_order_label)}'"
        f" data-presentation-mode='{esc(card.presentation_mode)}'"
        f" data-wallet-held='{str(card.is_wallet_held).lower()}'"
        f" data-portfolio-asset='{str(card.is_portfolio_asset).lower()}'"
        f" data-workflow-bucket='{esc(workflow_sort_bucket)}'"
        f" data-sort-presentation='{esc(presentation_sort_value)}'"
        f" data-sort-action='{esc(action_sort_value)}'"
        f" data-sort-setup='{esc(setup_sort_value)}'"
        f" data-sort-ppp='{esc(ppp_sort_value)}'"
        f" data-planning-ppp='{esc(planning_ppp_attr)}'"
        f" data-actionable-ppp='{esc(actionable_ppp_attr)}'"
        f" data-map-switch-review='{esc(map_switch_review_attr)}'"
        f" data-native-map-status='{esc(native_map_status_attr)}'"
        f" data-sort-symbol='{esc(card.symbol.lower())}'"
        f" data-bc-availability='{esc(_breath_curve_availability(breath_curve_payload))}'"
        f" data-bc-phase-marker='{esc(_breath_curve_phase_marker_text(breath_curve_payload))}'"
        f" data-bc-offset-band='{esc(_breath_curve_offset_band_text(breath_curve_payload))}'"
        f" data-bc-match-quality='{esc(_breath_curve_match_score_text(breath_curve_payload))}'"
        f" data-bc-current-checkpoint='{esc(_breath_curve_current_checkpoint_text(breath_curve_payload))}'"
        f" data-bc-next-checkpoint='{esc(_breath_curve_next_checkpoint_text(breath_curve_payload))}'"
        f" data-bc-next-timing='{esc(_breath_curve_next_timing_text(breath_curve_payload))}'"
        f" data-bc-btc-relation='{esc(_breath_curve_btc_relation_text(breath_curve_payload))}'"
        f" data-bc-source-ts='{esc(str(breath_curve_payload.get('source_candle_ts_utc') or '—'))}'"
        f" data-bc-freshness='{esc(_breath_curve_freshness_text(breath_curve_payload))}'"
        f" data-map-cycle-id='{esc(card.evidence.map_cycle_id)}'"
        f" data-native-map-id='{esc(card.evidence.native_map_id)}'"
        f" data-selected-map-reason='{esc(card.evidence.selected_map_reason)}'"
        f" data-selected-map-tier='{esc(card.evidence.selected_map_tier)}'"
        f" data-map-lifecycle-state='{esc(card.evidence.lifecycle_state)}'"
        f" data-price-source-ts='{esc(card.evidence.price_ts_utc)}'"
        f" data-price-freshness-state='{esc(card.evidence.price_freshness_state)}'"
        f" data-delta-status='{esc(card.delta.delta_status)}'"
        f" data-delta-types='{esc(','.join(card.delta.material_delta_types))}'"
        f" data-evidence-rows='{esc(evidence_rows_json_attr)}'"
        f" data-render-id='{esc(card.render_id)}'>"
        "<div class='card-head'>"
        "<div class='card-head-left'>"
        f"<div class='card-row1'>"
        f"<span class='mono card-symbol'>{esc(card.symbol)}</span>"
        f"<span class='muted small'>{esc(card.market)}</span>"
        f"<span class='muted small'>·</span>"
        f"<span class='muted small'>{esc(card.fib_trading_horizon)}</span>"
        f"<span class='muted small'>·</span>"
        f"<span class='mono small'>{esc(price_line)}</span>"
        f"{portfolio_badge_html}"
        f"</div>"
        f"<div class='card-row2'>{quality_html}{rotation_badge_html}</div>"
        "</div>"
        f"<div style='text-align:right'>"
        f"{_scenario_badge(card.scenario_type)}"
        f"{state_label_html}"
        f"{secondary_state_html}"
        f"<div class='action-label {'action-wait' if card.presentation_mode in _NO_ACCOUNT_STATE_MODES or card.actionability_state != CARD_ACTIONABILITY_ACTIVE else _action_class(card.action_label)}'>{esc(displayed_action)}</div>"
        f"<div class='tf-label'>{esc(card.timeframe_label)}</div>"
        f"</div>"
        "</div>"
        f"<div class='field-grid'>{summary_html}</div>"
        f"{fib_section_html}"
        f"{account_section_html}"
        f"{order_section_html}"
        f"{open_orders_html}"
        f"{evidence_html}"
        f"<ul class='reasons'>{reasons_html}</ul>"
        "<div class='manual-only muted'>MANUAL_ONLY — read-only snapshot, no automatic placement</div>"
        "</section>"
    )


def render_full_html(
    cards: list[ProfitPlanCard],
    *,
    rendered_at: str | None = None,
    broker_mode: str = "offline",
    monitor_link: str | None = None,
    nav_html: str | None = None,
    storage_scope: str = "default",
    sort: bool = True,
    render_id: str | None = None,
    writer_instance_id: str | None = None,
    pipeline_banner_html: str | None = None,
    rotation_projection: RotationProfitPlanProjection | None = None,
) -> str:
    if rendered_at is None:
        rendered_at = format_ui_now()
    snapshot_render_id = render_id or str(uuid.uuid4())
    snapshot_writer_id = writer_instance_id or str(uuid.uuid4())

    display_cards = sort_cards_action_priority(cards) if sort else list(cards)
    attention_count = sum(1 for c in cards if c.is_relevant)
    total_count = len(cards)
    cards_html = "\n".join(
        render_plan_card(
            c,
            monitor_link=monitor_link,
            rotation_market_projection=(
                get_market_projection(rotation_projection, c.market)
                if rotation_projection is not None
                else None
            ),
        )
        for c in display_cards
    )
    empty_note = "<div class='muted' style='padding:16px;grid-column:1/-1'>No symbols with a plan loaded.</div>" if not cards else ""
    filter_refs = build_profit_plan_filter_reference_lists(display_cards)
    action_filter_options_html = _canonical_action_filter_options_html(display_cards)
    setup_filter_options_html = _filter_select_options(filter_refs["setup"])
    primary_filter_options_html = _filter_select_options(filter_refs["primary"])
    order_filter_options_html = _filter_select_options(filter_refs["orders"])
    nav_section_html = "" if not nav_html else f"    {nav_html}\n"
    pipeline_banner_section_html = "" if not pipeline_banner_html else f"  {pipeline_banner_html}\n"
    rotation_strip_section_html = f"  {_rotation_strip_html(rotation_projection)}\n" if rotation_projection is not None else ""

    return (
        "<!doctype html>\n<html lang='en'>\n<head>\n"
        "  <meta charset='utf-8'>\n"
        "  <meta http-equiv='refresh' content='120'>\n"
        "  <meta name='viewport' content='width=device-width, initial-scale=1'>\n"
        f"  <meta name='synth-render-id' content='{esc(snapshot_render_id)}'>\n"
        f"  <meta name='synth-writer-instance-id' content='{esc(snapshot_writer_id)}'>\n"
        f"  <meta name='synth-attention-count' content='{attention_count}'>\n"
        f"  <meta name='synth-total-count' content='{total_count}'>\n"
        "  <title>Synth — Profit Plan</title>\n"
        f"{synth_favicon_head_html()}"
        f"  <style>{_CSS}</style>\n"
        "</head>\n<body>\n"
        "  <header>\n"
        "    <div style='display:flex;align-items:baseline;gap:12px;flex-wrap:wrap'>\n"
        "    <h1>Synth v2 — Profit Plan</h1>\n"
        f"    <span class='muted small'>Rendered: {esc(rendered_at)} · Mode: {esc(broker_mode)} · Cards: {total_count} · Attention: {attention_count}</span>\n"
        "    </div>\n"
        f"{nav_section_html}"
        "  </header>\n"
        f"{pipeline_banner_section_html}"
        f"{rotation_strip_section_html}"
        "  <div class='sticky-controls'>\n"
        "    <div class='filter-controls'>\n"
        "      <button id='btn-all' class='toggle-btn active' type='button' onclick='resetProfitPlanFilters()'>All selected assets</button>\n"
        "      <label class='filter-control'>Action\n"
        f"        <select id='filter-action' class='filter-select' onchange='applyFiltersAndSort()'><option value=''>All actions</option>{action_filter_options_html}</select>\n"
        "      </label>\n"
        "      <label class='filter-control'>Setup\n"
        f"        <select id='filter-setup' class='filter-select' onchange='applyFiltersAndSort()'><option value=''>All setups</option>{setup_filter_options_html}</select>\n"
        "      </label>\n"
        "      <label class='filter-control'>State\n"
        f"        <select id='filter-primary' class='filter-select' onchange='applyFiltersAndSort()'><option value=''>All states</option>{primary_filter_options_html}</select>\n"
        "      </label>\n"
        "      <label class='filter-control'>Orders\n"
        f"        <select id='filter-orders' class='filter-select' onchange='applyFiltersAndSort()'><option value=''>All order states</option>{order_filter_options_html}</select>\n"
        "      </label>\n"
        "      <label class='filter-control'>Sort\n"
        "        <select id='sort-mode' class='filter-select' onchange='applyFiltersAndSort()'>\n"
        "          <option value='action'>Action priority</option>\n"
        "          <option value='symbol_az'>Symbol A-Z</option>\n"
        "          <option value='symbol_za'>Symbol Z-A</option>\n"
        "          <option value='ppp_desc'>PPP high-low</option>\n"
        "          <option value='ppp_asc'>PPP low-high</option>\n"
        "          <option value='setup'>Setup</option>\n"
        "        </select>\n"
        "      </label>\n"
        "      <span class='muted small' style='margin-left:4px'>broker_writes=0 · order_submission=0</span>\n"
        "    </div>\n"
        "    <div id='search-shell' class='search-shell'>\n"
        "      <input id='candidate-search' class='search-input' type='search' placeholder='Search symbol, market, scenario, state, action, horizon, context…' oninput='updateSearch()'>\n"
        "      <button class='toggle-btn' type='button' onclick='clearSearch()'>Clear search</button>\n"
        "      <button class='toggle-btn' type='button' onclick='resetProfitPlanFilters()'>Reset filters</button>\n"
        "      <div id='matching-count' class='search-meta'>Matching 0 of 0</div>\n"
        "    </div>\n"
        "  </div>\n"
        "  <main>\n"
        "    <div id='profit-plan-cockpit'>\n"
        "      <div id='profit-plan-selector'>\n"
        "        <div class='pp-selector-item muted'>Loading…</div>\n"
        "      </div>\n"
        "      <div id='profit-plan-main'>\n"
        f"        {empty_note}\n"
        f"        {cards_html}\n"
        "        <div id='no-results' class='no-results'>No candidates match the current search.</div>\n"
        "      </div>\n"
        "      <div id='profit-plan-detail-panel'>\n"
        "        <div class='muted small'>Select a card to see details.</div>\n"
        "        <h3>Wallet</h3><div class='muted small' style='margin-bottom:10px'>— placeholder —</div>\n"
        "        <h3>Position</h3><div class='muted small' style='margin-bottom:10px'>— placeholder —</div>\n"
        "        <h3>Orders</h3><div class='muted small' style='margin-bottom:10px'>— placeholder —</div>\n"
        "        <h3>Context</h3><div class='muted small' style='margin-bottom:10px'>— placeholder —</div>\n"
        "      </div>\n"
        "    </div>\n"
        "  </main>\n"
        f"  <script>{_build_client_js(storage_scope)}</script>\n"
        "</body>\n</html>"
    )


# ---------------------------------------------------------------------------
# Price tick normalization integration
# ---------------------------------------------------------------------------

def apply_price_tick_normalization(
    cards: "list[ProfitPlanCard]",
    tick_rules_by_market: "dict[str, Any]",
    venue: str = "bitvavo",
) -> "tuple[list[ProfitPlanCard], dict[str, list[Any]]]":
    """Normalize all executable Profit Plan prices to market tick boundaries.

    Returns:
      (normalized_cards, normalization_audit_by_symbol)

    normalization_audit_by_symbol maps symbol → list of PriceNormalizationResult
    for inclusion in the JSON snapshot.

    Rounding: ROUND_UP for TARGET_SELL, ROUND_DOWN for REENTRY_BUY/INVALIDATION.
    Missing tick rule: raw price preserved, MISSING_TICK_RULE status surfaced.

    broker_private_calls=0
    """
    import dataclasses
    from src.market_rules.price_tick_normalization_v1 import (
        PRICE_ROLE_DISPLAY_ONLY,
        PRICE_ROLE_INVALIDATION,
        PRICE_ROLE_REENTRY_BUY,
        PRICE_ROLE_TARGET_SELL,
        TickRule,
        normalize_optional_price,
        normalize_prices,
        normalize_price_to_tick,
        resolve_tick_rule,
    )

    normalized_cards: list[ProfitPlanCard] = []
    audit_by_symbol: dict[str, list[Any]] = {}

    for card in cards:
        rule: TickRule = resolve_tick_rule(
            venue=venue,
            market=card.market,
            db_rules=tick_rules_by_market,
        )
        audits: list[Any] = []

        def _norm_tuple(prices: "tuple[Decimal, ...]", role: str) -> "tuple[Decimal, ...]":
            result_tuple, results = normalize_prices(prices, rule, role)
            audits.extend(results)
            return result_tuple

        def _norm_opt(price: "Decimal | None", role: str) -> "Decimal | None":
            v, result = normalize_optional_price(price, rule, role)
            if result is not None:
                audits.append(result)
            return v

        # Normalize executable price fields
        target_exit_zone = _norm_tuple(card.target_exit_zone, PRICE_ROLE_TARGET_SELL)
        reload_reentry_zone = _norm_tuple(card.reload_reentry_zone, PRICE_ROLE_REENTRY_BUY)
        buy_zone = _norm_tuple(card.buy_zone, PRICE_ROLE_REENTRY_BUY)
        sell_zone = _norm_tuple(card.sell_zone, PRICE_ROLE_TARGET_SELL)
        active_target = _norm_opt(card.active_target, PRICE_ROLE_TARGET_SELL)
        invalidation_level = _norm_opt(card.invalidation_level, PRICE_ROLE_INVALIDATION)
        invalidation_risk_zone = _norm_opt(card.invalidation_risk_zone, PRICE_ROLE_INVALIDATION)
        current_price = _norm_opt(card.current_price, PRICE_ROLE_DISPLAY_ONLY)

        # Normalize target level statuses (display levels only)
        normalized_statuses: list[TargetLevelStatus] = []
        for tls in card.target_level_statuses:
            result = normalize_price_to_tick(tls.level, rule, PRICE_ROLE_TARGET_SELL)
            audits.append(result)
            normalized_statuses.append(
                dataclasses.replace(tls, level=result.normalized_price)
            )

        normalized_card = dataclasses.replace(
            card,
            target_exit_zone=target_exit_zone,
            reload_reentry_zone=reload_reentry_zone,
            buy_zone=buy_zone,
            sell_zone=sell_zone,
            active_target=active_target,
            invalidation_level=invalidation_level,
            invalidation_risk_zone=invalidation_risk_zone,
            current_price=current_price,
            target_level_statuses=tuple(normalized_statuses),
        )
        normalized_cards.append(normalized_card)
        audit_by_symbol[card.symbol] = audits

    return normalized_cards, audit_by_symbol


# ---------------------------------------------------------------------------
# JSON snapshot helpers
# ---------------------------------------------------------------------------

def _build_normalization_audit_json(
    audits: "list[Any] | None",
) -> "dict[str, Any]":
    """Compact audit summary for price_normalization JSON field."""
    if not audits:
        return {"status": "NOT_APPLIED"}
    statuses = [a.price_rule_status for a in audits]
    applied = sum(1 for s in statuses if s == "TICK_RULE_APPLIED")
    missing = sum(1 for s in statuses if s == "MISSING_TICK_RULE")
    display_only = sum(1 for s in statuses if s == "DISPLAY_ONLY_NOT_EXECUTABLE")
    rule_sources = sorted({a.rule_source for a in audits})
    tick_sizes = sorted({
        str(a.tick_size) for a in audits if a.tick_size is not None
    })
    changed = [
        {
            "raw_price": str(a.raw_price),
            "normalized_price": str(a.normalized_price),
            "price_role": a.price_role,
            "price_rule_status": a.price_rule_status,
        }
        for a in audits
        if a.normalized_price != a.raw_price
    ]
    return {
        "status": "APPLIED" if applied > 0 else ("MISSING_TICK_RULE" if missing > 0 else "DISPLAY_ONLY"),
        "tick_rule_applied": applied,
        "missing_tick_rule": missing,
        "display_only": display_only,
        "rule_sources": rule_sources,
        "tick_sizes": tick_sizes,
        "changed_prices": changed,
    }


# ---------------------------------------------------------------------------
# JSON snapshot
# ---------------------------------------------------------------------------

def build_json_snapshot(
    cards: list[ProfitPlanCard],
    *,
    snapshot_ts: str | None = None,
    broker_mode: str = "offline",
    generated_ts_utc: str | None = None,
    account_snapshot_ts_utc: str | None = None,
    order_snapshot_ts_utc: str | None = None,
    market_price_snapshot_ts_utc: str | None = None,
    writer_instance_id: str | None = None,
    render_id: str | None = None,
    normalization_audit_by_symbol: dict[str, list[Any]] | None = None,
    pipeline_health: dict[str, Any] | None = None,
    market_context_by_symbol: dict[str, dict[str, Any]] | None = None,
    rotation_projection: RotationProfitPlanProjection | None = None,
) -> dict[str, Any]:
    now_ts = snapshot_ts or datetime.now(UTC).isoformat()
    relevant_count = sum(1 for c in cards if c.is_relevant)
    total_count = len(cards)
    wallet_held_count = sum(1 for c in cards if c.is_wallet_held)
    portfolio_asset_count = sum(1 for c in cards if c.is_portfolio_asset)
    _rotation_projection = rotation_projection or unavailable_rotation_projection()
    return {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "render_id": render_id or str(uuid.uuid4()),
        "writer_instance_id": writer_instance_id or str(uuid.uuid4()),
        "snapshot_ts": now_ts,
        "generated_ts_utc": generated_ts_utc or now_ts,
        "account_snapshot_ts_utc": account_snapshot_ts_utc,
        "order_snapshot_ts_utc": order_snapshot_ts_utc,
        "market_price_snapshot_ts_utc": market_price_snapshot_ts_utc,
        "relevant_count": relevant_count,
        "total_count": total_count,
        "card_count": total_count,
        "wallet_held_count": wallet_held_count,
        "portfolio_asset_count": portfolio_asset_count,
        # Deprecated compatibility alias only — this field always measured
        # wallet-driven inclusion, not strategic portfolio membership,
        # despite its old name. Canonical field is "wallet_held_count".
        "portfolio_held_count": wallet_held_count,
        "broker_mode": broker_mode,
        "broker_writes": 0,
        "order_submission": 0,
        "executor": "none",
        "pipeline_health": pipeline_health,
        "rotation": rotation_projection_to_json_dict(_rotation_projection),
        "symbols": [
            {
                "render_id": c.render_id,
                "symbol": c.symbol,
                "market": c.market,
                "fib_trading_horizon": c.fib_trading_horizon,
                "short_context_input_status": c.short_context_input_status,
                "short_context_coverage_status": c.short_context_coverage_status,
                "short_context_display_state": c.short_context_display_state,
                "evidence": _evidence_json(c.evidence),
                "evidence_rows": evidence_rows_to_json(build_card_evidence_rows(c)),
                "delta": _delta_json(c.delta),
                "current_price": str(c.current_price) if c.current_price is not None else None,
                "current_price_display": _price_display(c.current_price),
                "current_price_status": c.current_price_status,
                "current_price_age_min": str(c.current_price_age_min) if c.current_price_age_min is not None else None,
                "history_high_since_activation": str(c.history_high_since_activation) if c.history_high_since_activation is not None else None,
                "history_low_since_activation": str(c.history_low_since_activation) if c.history_low_since_activation is not None else None,
                "all_sell_targets_completed": c.all_sell_targets_completed,
                "scenario_type": c.scenario_type,
                "action_label": c.action_label,
                "actionability_state": c.actionability_state,
                "timeframe_label": c.timeframe_label,
                "buy_zone": [str(p) for p in c.buy_zone],
                "buy_zone_display": [_price_display(p) for p in c.buy_zone],
                "sell_zone": [str(p) for p in c.sell_zone],
                "sell_zone_display": [_price_display(p) for p in c.sell_zone],
                "invalidation_level": str(c.invalidation_level) if c.invalidation_level is not None else None,
                "invalidation_level_display": _price_display(c.invalidation_level),
                "target_exit_zone": [str(p) for p in c.target_exit_zone],
                "target_exit_zone_display": [_price_display(p) for p in c.target_exit_zone],
                "active_target": str(c.active_target) if c.active_target is not None else None,
                "active_target_display": _price_display(c.active_target),
                "target_level_statuses": [
                    {
                        "level": str(level.level),
                        "level_display": _price_display(level.level),
                        "lifecycle_state": level.lifecycle_state,
                        "coverage_state": level.coverage_state,
                        "human_label": level.human_label,
                        "retest_context": level.retest_context,
                        "first_cross_ts_utc": level.first_cross_ts_utc.isoformat() if level.first_cross_ts_utc is not None else None,
                        "distance_pct": str(level.distance_pct) if level.distance_pct is not None else None,
                        "distance_pct_display": _pct_display(level.distance_pct),
                        "matching_open_sell_orders": level.matching_open_sell_orders,
                        "nearest_open_sell_price": str(level.nearest_open_sell_price) if level.nearest_open_sell_price is not None else None,
                        "nearest_open_sell_distance_pct": str(level.nearest_open_sell_distance_pct) if level.nearest_open_sell_distance_pct is not None else None,
                        "is_active_target": level.is_active_target,
                    }
                    for level in c.target_level_statuses
                ],
                "reload_reentry_zone": [str(p) for p in c.reload_reentry_zone],
                "reload_reentry_zone_display": [_price_display(p) for p in c.reload_reentry_zone],
                "invalidation_risk_zone": str(c.invalidation_risk_zone) if c.invalidation_risk_zone is not None else None,
                "invalidation_risk_zone_display": _price_display(c.invalidation_risk_zone),
                "distance_to_target_pct": str(c.distance_to_target_pct) if c.distance_to_target_pct is not None else None,
                "distance_to_target_pct_display": _pct_display(c.distance_to_target_pct),
                "distance_to_reload_pct": str(c.distance_to_reload_pct) if c.distance_to_reload_pct is not None else None,
                "distance_to_reload_pct_display": _pct_display(c.distance_to_reload_pct),
                "distance_to_invalidation_pct": str(c.distance_to_invalidation_pct) if c.distance_to_invalidation_pct is not None else None,
                "distance_to_invalidation_pct_display": _pct_display(c.distance_to_invalidation_pct),
                "primary_state": c.primary_state,
                "secondary_state": c.secondary_state,
                "suggested_manual_attention_label": c.suggested_manual_attention_label,
                "setup_state": c.setup_state,
                "event_state": c.event_state,
                "ladder_states": list(c.ladder_states),
                "relevance_reasons": list(c.relevance_reasons),
                "reasons": list(c.reasons),
                "is_relevant": c.is_relevant,
                "planning_ppp_pct": (str(_planning_ppp(c)) if _planning_ppp(c) is not None else None),
                "planning_ppp_display": _pct_display(_planning_ppp(c)),
                "planning_ppp_unavailable_reason": _planning_ppp_unavailable_reason(c),
                "is_portfolio_asset": c.is_portfolio_asset,
                "is_wallet_held": c.is_wallet_held,
                # Deprecated compatibility alias only — always equal to
                # is_wallet_held, never strategic portfolio membership.
                # Canonical fields are is_portfolio_asset / is_wallet_held.
                "is_portfolio_held": c.is_wallet_held,
                "actionable_ppp_pct": (str(_actionable_ppp(c)) if _actionable_ppp(c) is not None else None),
                "actionable_ppp_display": _pct_display(_actionable_ppp(c)),
                "actionable_ppp_available": _actionable_ppp(c) is not None,
                "effective_action": _effective_workflow_action(c),
                "fix_ladder_allowed": _fix_ladder_allowed(c),
                "map_switch_review_required": _map_switch_review_required(c),
                "native_map_status": _native_map_status(c),
                "breathline_display_state": BREATHLINE_DISPLAY_STATE,
                "breathline_weights": {
                    "selection_weight": BREATHLINE_SELECTION_WEIGHT,
                    "action_weight": BREATHLINE_ACTION_WEIGHT,
                    "decision_weight": BREATHLINE_DECISION_WEIGHT,
                },
                "order_summary": {
                    "open_buy_orders": c.order_summary.open_buy_orders,
                    "open_sell_orders": c.order_summary.open_sell_orders,
                    "matching_buys": c.order_summary.matching_buys,
                    "matching_sells": c.order_summary.matching_sells,
                    "nearest_open_buy_distance_pct": str(c.order_summary.nearest_open_buy_distance_pct) if c.order_summary.nearest_open_buy_distance_pct is not None else None,
                    "nearest_open_sell_distance_pct": str(c.order_summary.nearest_open_sell_distance_pct) if c.order_summary.nearest_open_sell_distance_pct is not None else None,
                    "max_open_order_distance_pct": str(c.order_summary.max_open_order_distance_pct) if c.order_summary.max_open_order_distance_pct is not None else None,
                    "existing_open_orders_summary": c.order_summary.existing_open_orders_summary,
                    "missing_suggested": list(c.order_summary.missing_suggested),
                },
                "price_normalization": _build_normalization_audit_json(
                    normalization_audit_by_symbol.get(c.symbol) if normalization_audit_by_symbol else None
                ),
                "fib_nav_context": {
                    "map_state": c.fib_nav_context.map_state,
                    "rebuild_trigger": c.fib_nav_context.rebuild_trigger,
                    "direction": c.fib_nav_context.direction,
                    "anchor_low": str(c.fib_nav_context.anchor_low),
                    "anchor_high": str(c.fib_nav_context.anchor_high),
                    "nav_sell_levels": [str(p) for p in c.fib_nav_context.nav_sell_levels],
                    "nav_buy_levels": [str(p) for p in c.fib_nav_context.nav_buy_levels],
                    "nav_invalidation": str(c.fib_nav_context.nav_invalidation) if c.fib_nav_context.nav_invalidation is not None else None,
                } if c.fib_nav_context is not None else None,
                "breath_curve": c.breath_curve,
                "market_context": (market_context_by_symbol or {}).get(c.symbol),
                "rotation": market_projection_to_json_dict(get_market_projection(_rotation_projection, c.market)),
            }
            for c in cards
        ],
    }
