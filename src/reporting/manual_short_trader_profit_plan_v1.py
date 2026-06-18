from __future__ import annotations

import html as _html
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from src.reporting.dashboard_style_v1 import synth_favicon_head_html
from src.reporting.dashboard_time_v1 import format_ui_now


REPORT_NAME = "manual_short_trader_profit_plan_v1"
REPORT_VERSION = "0.1"

ORDER_MATCH_TOLERANCE_PCT = Decimal("3")
TAKE_PROFIT_WAITING_THRESHOLD_PCT = Decimal("3")
RELOAD_ZONE_APPROACHING_THRESHOLD_PCT = Decimal("3")
INVALIDATION_NEAR_THRESHOLD_PCT = Decimal("3")
PRICE_RAN_AWAY_THRESHOLD_PCT = Decimal("12")
ORDER_STALE_DISTANCE_PCT = Decimal("12")
TARGET_LEVEL_NEAR_THRESHOLD_PCT = Decimal("1")

STATE_LABELS: dict[str, str] = {
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
    "EXTENSION_RUNNER": "EXTENSION_SETUP",
    "BREAKOUT_RETEST": "BREAKOUT_SETUP",
    "REENTRY_WAIT": "REENTRY_SETUP",
    "RANGE_BOUNCE": "RANGE_SETUP",
    "MAP_COMPLETED": "MAP_COMPLETED",
    "LEGACY_CONTEXT_REFERENCE_ONLY": "MINIMAL_CONTEXT",
    "NO_CLEAR_PLAN": "MINIMAL_CONTEXT",
    "NO_SHORT_FIB_CONTEXT": "MINIMAL_CONTEXT",
    "NO_CURRENT_PRICE": "MINIMAL_CONTEXT",
}

EVENT_STATE_FROM_PRIMARY: dict[str, str] = {
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
    "WAIT": "BETWEEN LEVELS",
    "NO_ACTION": "BETWEEN LEVELS",
    "DO_NOTHING": "BETWEEN LEVELS",
    "WAIT_FOR_SHORT_CONTEXT": "CONTEXT UNAVAILABLE",
    "WAIT_FOR_NEW_MAP": "MAP EXPIRED",
    "NAVIGATION_ONLY": "NAVIGATION MAP",
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

SHORT_CONTEXT_DISPLAY_LABELS: dict[str, str] = {
    "HAS_NATIVE_SHORT_FIB_CONTEXT": "Native SHORT fib context available",
    "NO_NATIVE_SHORT_FIB_CONTEXT": "No native SHORT fib context",
    "MARKET_DATA_MISSING": "Market data missing",
    "CONTEXT_INVALID_OR_STALE": "Context invalid or stale",
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
    fib_nav_context: FibNavContext | None = None
    render_id: str = field(default_factory=lambda: str(uuid.uuid4()))


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

def _strip_decimal_zeros(v: Decimal) -> str:
    text = format(v, "f")
    if "." not in text:
        return text
    text = text.rstrip("0").rstrip(".")
    if text in {"", "-0"}:
        return "0"
    return text


def _fmt_p(v: Decimal | None) -> str:
    if v is None:
        return "?"
    # Preserve useful small-price precision, but strip display-only zero noise.
    _sign, _digits, exponent = v.as_tuple()
    native_dp = -exponent if exponent < 0 else 0
    if native_dp > 6:
        return _strip_decimal_zeros(v)
    if abs(v) < Decimal("1"):
        return _strip_decimal_zeros(v.quantize(Decimal("0.000001")))
    return _strip_decimal_zeros(v.quantize(Decimal("0.01")))


def _pct(v: Decimal | None) -> str:
    if v is None:
        return "?"
    return f"{v.quantize(Decimal('0.01'))}%"


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
    return _profit_plan_potential_pct_from_levels(
        card.reload_reentry_zone or card.buy_zone,
        _profit_plan_target_levels(card),
    )


def _format_ppp_ppt_ppv_line(card: ProfitPlanCard) -> str:
    ppp = _profit_plan_potential_pct(card)
    if ppp is None:
        return "— / — = —"
    # PPT/PPV require a deterministic time-to-target source; do not fake it.
    return f"{_pct(ppp)} / — = —"


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
) -> str:
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


def _card_action_sort_value(card: ProfitPlanCard) -> int:
    if not card.is_relevant:
        return 999
    return (_order_ladder_sort_priority(card.ladder_states) * 100) + (_event_sort_priority(card) * 10)


def sort_cards_action_priority(cards: list[ProfitPlanCard]) -> list[ProfitPlanCard]:
    """Default UI sort: user-actionable cards first, then market/risk urgency."""
    def key(card: ProfitPlanCard) -> tuple[bool, int, Decimal, Decimal, str]:
        dist = _nearest_distance(card)
        ppp = _profit_plan_potential_pct(card)
        return (
            not card.is_relevant,
            _card_action_sort_value(card),
            dist if dist is not None else Decimal("999999"),
            -(ppp if ppp is not None else Decimal("-999999")),
            card.symbol,
        )

    return sorted(cards, key=key)




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


def _card_displayed_action_for_filter(card: ProfitPlanCard) -> str:
    """
    Return the user-facing action category for filtering.

    Contract:
    - Uses only existing card fields.
    - Does not introduce a new hidden category.
    - Mirrors the UI rule that missing/incomplete/stale active ladders are FIX LADDER work.
    """
    if (
        card.actionability_state == CARD_ACTIONABILITY_ACTIVE
        and any(
            state in {"LADDER_MISSING", "LADDER_INCOMPLETE", "STALE_ORDERS_PRESENT"}
            for state in card.ladder_states
        )
    ):
        return "FIX LADDER"
    return _ACTION_DISPLAY_MAP.get(card.action_label, card.action_label)


def _card_filter_action_option(card: ProfitPlanCard) -> tuple[str, str]:
    label = _filter_display_label(_card_displayed_action_for_filter(card))
    return _filter_value_from_label(label), label


def _workflow_sort_bucket(card: ProfitPlanCard) -> int:
    """
    Explicit workflow bucket used by PPP sort.

    This prevents completed/navigation-only maps with large theoretical PPP from
    outranking active trade setups.
    """
    if not card.is_relevant:
        return 9
    if (
        card.actionability_state == CARD_ACTIONABILITY_ACTIVE
        and card.setup_state in {"REENTRY_SETUP", "EXTENSION_SETUP", "BREAKOUT_SETUP", "RANGE_SETUP"}
    ):
        return 0
    if (
        card.actionability_state == CARD_ACTIONABILITY_NEEDS_RECOMPUTE
        or card.action_label == "WAIT_FOR_NEW_MAP"
        or card.primary_state in {"MAP_RECOMPUTE_NEEDED", "POST_EXTENSION_PULLBACK"}
    ):
        return 1
    if (
        card.actionability_state in {CARD_ACTIONABILITY_NAVIGATION_ONLY, CARD_ACTIONABILITY_HISTORICAL_REFERENCE}
        or card.setup_state == "MAP_COMPLETED"
        or card.action_label == "NAVIGATION_ONLY"
    ):
        return 2
    if card.short_context_display_state != "HAS_NATIVE_SHORT_FIB_CONTEXT":
        return 8
    return 4


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
    current_price: Decimal | None,
    sell_zone: tuple[Decimal, ...],
    target_level_statuses: tuple[TargetLevelStatus, ...],
    scenario_type: str,
    action_label: str,
    reasons: tuple[str, ...],
) -> tuple[bool, str, str, str | None, str, tuple[str, ...]]:
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
        scenario_type="NO_SHORT_FIB_CONTEXT",
        action_label="WAIT_FOR_SHORT_CONTEXT",
        actionability_state=CARD_ACTIONABILITY_NEEDS_RECOMPUTE,
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
        primary_state=short_context_display_state,
        secondary_state=None,
        suggested_manual_attention_label=_short_context_display_label(short_context_display_state),
        setup_state="MINIMAL_CONTEXT",
        event_state="CONTEXT_UNAVAILABLE",
        ladder_states=("ORDER_DATA_UNAVAILABLE",),
        relevance_reasons=("MINIMAL_CONTEXT",),
        is_relevant=True,
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
        buy_covered = sum(
            1 for buy_level in buy_zone
            if any(_near(o.limit_price, buy_level, ORDER_MATCH_TOLERANCE_PCT) for o in buy_orders)
        )
        if buy_covered == 0 and "LADDER_MISSING" not in states:
            states.append("LADDER_MISSING")
        elif 0 < buy_covered < len(buy_zone) and "LADDER_MISSING" not in states and "LADDER_INCOMPLETE" not in states:
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
    quality_state: PASS | WARN | FAIL
    quality_reason: None on PASS, human-readable explanation on WARN/FAIL
    """
    if current_price is None or current_price_status in _QUALITY_PRICE_STALE_STATES:
        reason = "No current price" if current_price is None else "Stale price data"
        return "FAIL", reason
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
    return f"{price_str} ({sign}{pct.quantize(Decimal('0.01'))}%)"


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

    if card.actionability_state == CARD_ACTIONABILITY_ACTIVE:
        return reentry_label, target_label, order_ladder_label, open_orders_label, reentry_line, target_line

    reentry_label = "Reference re-entry zone"
    open_orders_label = "Existing open orders to review:"
    order_ladder_label = "Order review"

    if card.actionability_state == CARD_ACTIONABILITY_NAVIGATION_ONLY:
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
) -> ProfitPlanCard:
    if current_price_status == "STALE_CURRENT_PRICE":
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
            current_price_status=current_price_status,
            current_price_age_min=current_price_age_min,
            history_high_since_activation=history_high_since_activation,
            history_low_since_activation=history_low_since_activation,
            all_sell_targets_completed=False,
        scenario_type="NO_CURRENT_PRICE",
        action_label="NO_CURRENT_PRICE",
        actionability_state=CARD_ACTIONABILITY_NEEDS_RECOMPUTE,
        timeframe_label="review blocked",
            buy_zone=(),
            sell_zone=(),
            invalidation_level=None,
            reasons=(
                "Current public price snapshot is stale.",
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
            primary_state="STALE_CURRENT_PRICE",
            secondary_state=None,
            suggested_manual_attention_label=STATE_LABELS["STALE_CURRENT_PRICE"],
            setup_state="MINIMAL_CONTEXT",
            event_state="CONTEXT_UNAVAILABLE",
            ladder_states=("ORDER_DATA_UNAVAILABLE",),
            relevance_reasons=(),
            is_relevant=False,
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
        ladder_states = _derive_ladder_states(_ladder_buy_zone, target_level_statuses, buy_orders, sell_orders)
        is_relevant, relevance_reasons = _derive_relevance_with_reasons(
            event_state, ladder_states, setup_state, force_not_relevant=True
        )
    else:
        setup_state = _derive_setup_state(scenario_type)
        event_state = _derive_event_state(primary_state)
        ladder_states = _derive_ladder_states(_ladder_buy_zone, target_level_statuses, buy_orders, sell_orders)
        is_relevant, relevance_reasons = _derive_relevance_with_reasons(event_state, ladder_states, setup_state)

    actionability_state = _derive_card_actionability_state(
        scenario_type=scenario_type,
        action_label=action_label,
        short_context_display_state=short_context_display_state,
        primary_state=primary_state,
        current_price=current_price,
        invalidation_level=invalidation_level,
    )

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
        fib_nav_context=fib_nav_context,
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
    main { padding: 16px; display: grid; gap: 16px;
           grid-template-columns: repeat(auto-fill, minmax(440px, 1fr)); }
    .muted { color: var(--muted); } .small { font-size: 12px; }
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
    .quality-reason { font-size: 11px; color: var(--muted); }
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
    var main = document.querySelector('main');
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
# Order ladder rows (Commit 3)
# ---------------------------------------------------------------------------

_ORDER_ROW_STATE_CSS: dict[str, str] = {
    "MISSING": "order-row-missing",
    "ARMED": "order-row-armed",
    "STALE": "order-row-stale",
    "HISTORICAL": "order-row-historical",
    "DATA_UNAVAILABLE": "order-row-unavailable",
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
    "ARMED":          "Armed",
    "MISSING":        "No order",
    "STALE":          "Stale",
    "HISTORICAL":     "Past level",
    "DATA_UNAVAILABLE": "Unavailable",
}

_ORDER_ROW_STATUS_CSS_CLASS: dict[str, str] = {
    "ARMED":          "armed",
    "MISSING":        "missing",
    "STALE":          "stale",
    "HISTORICAL":     "historical",
    "DATA_UNAVAILABLE": "unavailable",
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
) -> str:
    quote = card.market.split("-")[-1] if "-" in card.market else ""
    search_text = build_card_search_text(card)

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
    ppp_line = _format_ppp_ppt_ppv_line(card)

    metrics_html = "".join((
        _metric_block("Current price", price_line),
        _metric_block("Setup", card.setup_state),
        _metric_block("Actionability", card.actionability_state),
        _metric_block(reentry_label, reentry_line),
        _metric_block(target_label, target_line),
        _metric_block("Invalidation", invalidation_line),
        _metric_block("PPP / PPT = PPV", ppp_line),
    ))

    # Build order rows first (needed for FIX LADDER override).
    # For completed maps, old re-entry levels are historical — omit from actionable order rows.
    _order_buy_zone = () if card.all_sell_targets_completed else card.buy_zone
    order_rows = build_order_rows(
        card_render_id=card.render_id,
        actionability_state=card.actionability_state,
        current_price=card.current_price,
        buy_zone=_order_buy_zone,
        target_level_statuses=card.target_level_statuses,
        buy_orders=buy_orders,
        sell_orders=sell_orders,
    )
    displayed_action = _displayed_user_action(card.action_label, order_rows, card.actionability_state)
    action_sort_value = _card_action_sort_value(card)
    setup_sort_value = _setup_sort_priority(card)
    ppp_pct = _profit_plan_potential_pct(card)
    ppp_sort_value = ppp_pct if ppp_pct is not None else Decimal("-999999")
    workflow_sort_bucket = _workflow_sort_bucket(card)

    # Event + order-ladder state above order ladder.
    # Keep internal ladder_states for data/tests, but render one deterministic user-facing status.
    event_label = STATE_LABELS.get(card.event_state, card.event_state.replace("_", " "))
    order_ladder_status = _order_ladder_display_status(card.ladder_states)
    filter_action_label = _filter_display_label(displayed_action)
    filter_action_value = _filter_value_from_label(filter_action_label)
    filter_setup_label = _filter_display_label(card.setup_state)
    filter_primary_label = _filter_display_label(card.primary_state)
    filter_order_label = _filter_display_label(order_ladder_status)
    filter_order_value = _filter_value_from_label(filter_order_label)
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

    secondary_state_html = ""
    if card.secondary_state is not None:
        secondary_state_html = (
            f"<div class='state-secondary'>Secondary: {esc(STATE_LABELS.get(card.secondary_state, card.secondary_state))}</div>"
        )

    reasons_html = "".join(f"<li>{esc(r)}</li>" for r in card.reasons)

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
        f" data-workflow-bucket='{esc(workflow_sort_bucket)}'"
        f" data-sort-action='{esc(action_sort_value)}'"
        f" data-sort-setup='{esc(setup_sort_value)}'"
        f" data-sort-ppp='{esc(ppp_sort_value)}'"
        f" data-sort-symbol='{esc(card.symbol.lower())}'"
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
        f"</div>"
        f"<div class='card-row2'>{quality_html}</div>"
        "</div>"
        f"<div style='text-align:right'>"
        f"{_scenario_badge(card.scenario_type)}"
        f"<div class='state-label {_state_class(card.primary_state)}'>{esc(card.suggested_manual_attention_label)}</div>"
        f"{secondary_state_html}"
        f"<div class='action-label {_action_class(card.action_label) if card.actionability_state == CARD_ACTIONABILITY_ACTIVE else 'action-wait'}'>{esc(displayed_action)}</div>"
        f"<div class='tf-label'>{esc(card.timeframe_label)}</div>"
        f"</div>"
        "</div>"
        f"<div class='field-grid'>{metrics_html}</div>"
        f"<div class='order-section'>"
        f"{order_section_header}"
        f"{order_rows_html}"
        f"</div>"
        f"<ul class='reasons'>{reasons_html}</ul>"
        f"{_order_summary_html(card.order_summary, monitor_link, open_orders_label=open_orders_label, actionability_state=card.actionability_state)}"
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
) -> str:
    if rendered_at is None:
        rendered_at = format_ui_now()
    snapshot_render_id = render_id or str(uuid.uuid4())
    snapshot_writer_id = writer_instance_id or str(uuid.uuid4())

    display_cards = sort_cards_action_priority(cards) if sort else list(cards)
    attention_count = sum(1 for c in cards if c.is_relevant)
    total_count = len(cards)
    cards_html = "\n".join(render_plan_card(c, monitor_link=monitor_link) for c in display_cards)
    empty_note = "<div class='muted' style='padding:16px;grid-column:1/-1'>No symbols with a plan loaded.</div>" if not cards else ""
    filter_refs = build_profit_plan_filter_reference_lists(display_cards)
    action_filter_options_html = _filter_select_options(filter_refs["action"])
    setup_filter_options_html = _filter_select_options(filter_refs["setup"])
    primary_filter_options_html = _filter_select_options(filter_refs["primary"])
    order_filter_options_html = _filter_select_options(filter_refs["orders"])
    clean_nav_html = "" if not nav_html else nav_html.replace("\\n", "\n")
    clean_pipeline_banner_html = "" if not pipeline_banner_html else pipeline_banner_html.replace("\\n", "\n")

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
        f"{'' if not clean_nav_html else f'    {clean_nav_html}\\n'}"
        "  </header>\n"
        f"{'' if not clean_pipeline_banner_html else f'  {clean_pipeline_banner_html}\\n'}"
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
        f"    {empty_note}\n"
        f"    {cards_html}\n"
        "    <div id='no-results' class='no-results'>No candidates match the current search.</div>\n"
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
) -> dict[str, Any]:
    now_ts = snapshot_ts or datetime.now(UTC).isoformat()
    relevant_count = sum(1 for c in cards if c.is_relevant)
    total_count = len(cards)
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
        "broker_mode": broker_mode,
        "broker_writes": 0,
        "order_submission": 0,
        "executor": "none",
        "pipeline_health": pipeline_health,
        "symbols": [
            {
                "render_id": c.render_id,
                "symbol": c.symbol,
                "market": c.market,
                "fib_trading_horizon": c.fib_trading_horizon,
                "short_context_input_status": c.short_context_input_status,
                "short_context_coverage_status": c.short_context_coverage_status,
                "short_context_display_state": c.short_context_display_state,
                "current_price": str(c.current_price) if c.current_price is not None else None,
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
                "sell_zone": [str(p) for p in c.sell_zone],
                "invalidation_level": str(c.invalidation_level) if c.invalidation_level is not None else None,
                "target_exit_zone": [str(p) for p in c.target_exit_zone],
                "active_target": str(c.active_target) if c.active_target is not None else None,
                "target_level_statuses": [
                    {
                        "level": str(level.level),
                        "lifecycle_state": level.lifecycle_state,
                        "coverage_state": level.coverage_state,
                        "human_label": level.human_label,
                        "retest_context": level.retest_context,
                        "first_cross_ts_utc": level.first_cross_ts_utc.isoformat() if level.first_cross_ts_utc is not None else None,
                        "distance_pct": str(level.distance_pct) if level.distance_pct is not None else None,
                        "matching_open_sell_orders": level.matching_open_sell_orders,
                        "nearest_open_sell_price": str(level.nearest_open_sell_price) if level.nearest_open_sell_price is not None else None,
                        "nearest_open_sell_distance_pct": str(level.nearest_open_sell_distance_pct) if level.nearest_open_sell_distance_pct is not None else None,
                        "is_active_target": level.is_active_target,
                    }
                    for level in c.target_level_statuses
                ],
                "reload_reentry_zone": [str(p) for p in c.reload_reentry_zone],
                "invalidation_risk_zone": str(c.invalidation_risk_zone) if c.invalidation_risk_zone is not None else None,
                "distance_to_target_pct": str(c.distance_to_target_pct) if c.distance_to_target_pct is not None else None,
                "distance_to_reload_pct": str(c.distance_to_reload_pct) if c.distance_to_reload_pct is not None else None,
                "distance_to_invalidation_pct": str(c.distance_to_invalidation_pct) if c.distance_to_invalidation_pct is not None else None,
                "primary_state": c.primary_state,
                "secondary_state": c.secondary_state,
                "suggested_manual_attention_label": c.suggested_manual_attention_label,
                "setup_state": c.setup_state,
                "event_state": c.event_state,
                "ladder_states": list(c.ladder_states),
                "relevance_reasons": list(c.relevance_reasons),
                "reasons": list(c.reasons),
                "is_relevant": c.is_relevant,
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
                "market_context": (market_context_by_symbol or {}).get(c.symbol),
            }
            for c in cards
        ],
    }
