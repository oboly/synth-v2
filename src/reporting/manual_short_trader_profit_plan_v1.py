from __future__ import annotations

import html as _html
from dataclasses import dataclass
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
    "TAKE_PROFIT_WAITING": "Take profit already waiting",
    "RELOAD_ZONE_APPROACHING": "Reload zone approaching",
    "PRICE_RAN_AWAY": "Price ran away",
    "INVALIDATION_NEAR": "Invalidation / risk zone near",
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
    "NO_CURRENT_PRICE": "PRICE UNAVAILABLE",
    "PLACE_LADDER": "SETUP LADDER",
    "REPAIR_LADDER": "REVIEW LADDER",
    "FAR_MOONBAG_ONLY": "MOONBAG ONLY",
}

SHORT_CONTEXT_DISPLAY_LABELS: dict[str, str] = {
    "HAS_NATIVE_SHORT_FIB_CONTEXT": "Native SHORT fib context available",
    "NO_NATIVE_SHORT_FIB_CONTEXT": "No native SHORT fib context",
    "MARKET_DATA_MISSING": "Market data missing",
    "CONTEXT_INVALID_OR_STALE": "Context invalid or stale",
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


@dataclass(frozen=True)
class TargetHistoryCandle:
    close_ts_utc: datetime
    high_price: Decimal
    low_price: Decimal


# ---------------------------------------------------------------------------
# Scenario classification
# ---------------------------------------------------------------------------

def _fmt_p(v: Decimal | None) -> str:
    if v is None:
        return "?"
    if abs(v) < Decimal("1"):
        return str(v.quantize(Decimal("0.000001")))
    return str(v.quantize(Decimal("0.01")))


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


def _short_context_display_label(state: str) -> str:
    return SHORT_CONTEXT_DISPLAY_LABELS.get(state, state.replace("_", " "))


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
    return " ".join(part.lower() for part in parts if part)


def filter_cards_for_view(cards: list[ProfitPlanCard], *, mode: str, query: str) -> list[ProfitPlanCard]:
    query_norm = query.strip().lower()
    out: list[ProfitPlanCard] = []
    for card in cards:
        if mode != "all" and not card.is_relevant:
            continue
        if query_norm and query_norm not in build_card_search_text(card):
            continue
        out.append(card)
    return out


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
            "No recent dip recorded — watching for a pull-back.",
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

    if (
        distance_to_target_pct is not None
        and abs(distance_to_target_pct) <= TAKE_PROFIT_WAITING_THRESHOLD_PCT
        and any(level.is_active_target and level.matching_open_sell_orders > 0 for level in target_level_statuses)
    ):
        state_candidates.append("TAKE_PROFIT_WAITING")

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

    if active_target is None and target_level_statuses:
        state_candidates.append("PRICE_RAN_AWAY")
    elif target_exit_zone and distance_to_target_pct is not None and distance_to_target_pct <= -PRICE_RAN_AWAY_THRESHOLD_PCT:
        state_candidates.append("PRICE_RAN_AWAY")

    if (
        order_summary.max_open_order_distance_pct is not None
        and order_summary.max_open_order_distance_pct >= ORDER_STALE_DISTANCE_PCT
    ):
        state_candidates.append("ORDER_TOO_FAR_OR_STALE")

    if not state_candidates:
        state_candidates.append("DO_NOTHING")

    primary_state = state_candidates[0]
    secondary_state = next((state for state in state_candidates[1:] if state != primary_state), None)
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
        ladder_states = _derive_ladder_states(buy_zone, target_level_statuses, buy_orders, sell_orders)
        is_relevant, relevance_reasons = _derive_relevance_with_reasons(
            event_state, ladder_states, setup_state, force_not_relevant=True
        )
    else:
        setup_state = _derive_setup_state(scenario_type)
        event_state = _derive_event_state(primary_state)
        ladder_states = _derive_ladder_states(buy_zone, target_level_statuses, buy_orders, sell_orders)
        is_relevant, relevance_reasons = _derive_relevance_with_reasons(event_state, ladder_states, setup_state)

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
      padding: 20px 24px; border-bottom: 1px solid var(--line);
      background: rgba(8,13,24,.88); position: sticky; top: 0;
      z-index: 10; backdrop-filter: blur(10px);
    }
    .cockpit-nav {
      display: flex; flex-wrap: wrap; gap: 14px; margin: 10px 0 0;
    }
    .cockpit-nav a {
      color: var(--blue); text-decoration: none; font-size: 14px;
    }
    .cockpit-nav a:hover { text-decoration: underline; }
    h1 { margin: 0 0 6px; font-size: 22px; }
    h2 { margin: 0 0 6px; font-size: 19px; }
    h3 { margin: 0 0 6px; font-size: 11px; text-transform: uppercase;
         letter-spacing: .07em; color: var(--blue); }
    main { padding: 16px; display: grid; gap: 16px;
           grid-template-columns: repeat(auto-fill, minmax(440px, 1fr)); }
    .muted { color: var(--muted); } .small { font-size: 12px; }
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
      display: flex; gap: 6px; margin-top: 10px; align-items: center; flex-wrap: wrap;
    }
    .sticky-controls {
      position: sticky; top: 0; z-index: 4; background: rgba(9,12,18,.96);
      backdrop-filter: blur(10px); padding: 10px 0 8px 0; margin-top: 6px;
    }
    .search-shell { display: none; align-items: center; gap: 8px; margin-top: 8px; flex-wrap: wrap; }
    .search-input {
      min-width: 260px; flex: 1 1 320px; background: rgba(255,255,255,.05); color: var(--text);
      border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; font-size: 13px;
    }
    .search-meta { font-size: 12px; color: var(--muted); }
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
"""

def _build_client_js(storage_scope: str) -> str:
    storage_scope = esc(storage_scope or "default")
    return f"""
  var PP_VIEW_KEY = 'ppView:{storage_scope}';
  var PP_QUERY_KEY = 'ppQuery:{storage_scope}';
  function applyFilters(mode, query) {{
    var total = 0;
    var matches = 0;
    document.querySelectorAll('.plan-card').forEach(function(card) {{
      total += 1;
      var rel = card.dataset.relevant === 'true';
      var hay = (card.dataset.search || '').toLowerCase();
      var queryMatch = !query || hay.indexOf(query) !== -1;
      var visible = queryMatch && (mode === 'all' || rel);
      card.style.display = visible ? '' : 'none';
      if (visible) matches += 1;
    }});
    var matching = document.getElementById('matching-count');
    if (matching) matching.textContent = 'Matching ' + matches + ' of ' + total;
    var noResults = document.getElementById('no-results');
    if (noResults) noResults.style.display = matches === 0 ? '' : 'none';
  }}
  function setView(mode) {{
    document.getElementById('btn-relevant').classList.toggle('active', mode === 'relevant');
    document.getElementById('btn-all').classList.toggle('active', mode === 'all');
    var shell = document.getElementById('search-shell');
    if (shell) shell.style.display = mode === 'all' ? 'flex' : 'none';
    var queryInput = document.getElementById('candidate-search');
    var query = mode === 'all' && queryInput ? (queryInput.value || '').trim().toLowerCase() : '';
    applyFilters(mode, query);
    try {{ localStorage.setItem(PP_VIEW_KEY, mode); }} catch(e) {{}}
  }}
  function updateSearch() {{
    var mode = document.getElementById('btn-all').classList.contains('active') ? 'all' : 'relevant';
    var queryInput = document.getElementById('candidate-search');
    var query = queryInput ? (queryInput.value || '').trim().toLowerCase() : '';
    try {{ localStorage.setItem(PP_QUERY_KEY, query); }} catch(e) {{}}
    applyFilters(mode, mode === 'all' ? query : '');
  }}
  function clearSearch() {{
    var queryInput = document.getElementById('candidate-search');
    if (queryInput) queryInput.value = '';
    updateSearch();
  }}
  document.addEventListener('DOMContentLoaded', function() {{
    var savedMode = 'relevant';
    var savedQuery = '';
    try {{
      savedMode = localStorage.getItem(PP_VIEW_KEY) || 'relevant';
      savedQuery = localStorage.getItem(PP_QUERY_KEY) || '';
    }} catch(e) {{}}
    var queryInput = document.getElementById('candidate-search');
    if (queryInput) queryInput.value = savedQuery;
    setView(savedMode === 'all' ? 'all' : 'relevant');
    updateSearch();
  }});
"""


def esc(value: Any) -> str:
    if value is None:
        return ""
    return _html.escape(str(value))


def _scenario_badge(scenario_type: str) -> str:
    cls_map = {
        "EXTENSION_RUNNER": "badge-ext",
        "REENTRY_WAIT":     "badge-reentry",
        "RANGE_BOUNCE":     "badge-range",
        "BREAKOUT_RETEST":  "badge-bkout",
    }
    cls = cls_map.get(scenario_type, "badge-none")
    return f"<span class='scenario-badge {cls}'>{esc(scenario_type.replace('_', ' '))}</span>"


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


def _order_summary_html(summary: ActiveOrderSummary, monitor_link: str | None) -> str:
    parts: list[str] = []
    parts.append(f"<span class='order-chip muted'>{esc(summary.existing_open_orders_summary)}</span>")
    if summary.matching_buys > 0:
        parts.append(f"<span class='order-chip ok'>{summary.matching_buys} buy order{'s' if summary.matching_buys != 1 else ''} near zone</span>")
    if summary.matching_sells > 0:
        parts.append(f"<span class='order-chip warn'>{summary.matching_sells} sell order{'s' if summary.matching_sells != 1 else ''} near zone</span>")
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
        f"<div style='margin-bottom:4px'>Existing open orders:</div>"
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


def render_plan_card(card: ProfitPlanCard, *, monitor_link: str | None = None) -> str:
    price_str = _fmt_p(card.current_price) if card.current_price else "—"
    quote = card.market.split("-")[-1] if "-" in card.market else ""
    search_text = build_card_search_text(card)

    reasons_html = "".join(f"<li>{esc(r)}</li>" for r in card.reasons)
    invalidation_html = ""
    if card.invalidation_level is not None:
        invalidation_html = f"<div class='invalidation'>✕ Invalidates below {esc(_fmt_p(card.invalidation_level))}</div>"

    ladder_states_str = " · ".join(card.ladder_states) if card.ladder_states else "—"
    metrics_html = "".join((
        _metric_block("Market", card.market),
        _metric_block("Horizon", card.fib_trading_horizon),
        _metric_block("Current price", f"{price_str} {quote}".strip()),
        _metric_block("Current price status", card.current_price_status or "FRESH_CURRENT_PRICE"),
        _metric_block("Price age (min)", "?" if card.current_price_age_min is None else _fmt_p(card.current_price_age_min)),
        _metric_block("Setup", card.setup_state),
        _metric_block("Event", card.event_state),
        _metric_block("Ladder", ladder_states_str),
        _metric_block("SHORT context", _short_context_display_label(card.short_context_display_state)),
        _metric_block("Active target / exit zone", ", ".join(_fmt_p(v) for v in card.target_exit_zone) or "No upcoming levels"),
        _metric_block("Reload / re-entry zone", ", ".join(_fmt_p(v) for v in card.reload_reentry_zone) or "No levels loaded"),
        _metric_block("Invalidation / risk zone", _fmt_p(card.invalidation_risk_zone)),
        _metric_block("Distance to target", _pct(card.distance_to_target_pct)),
        _metric_block("Distance to reload", _pct(card.distance_to_reload_pct)),
        _metric_block("Distance to invalidation", _pct(card.distance_to_invalidation_pct)),
    ))

    secondary_state_html = ""
    if card.secondary_state is not None:
        secondary_state_html = (
            f"<div class='state-secondary'>Secondary state: {esc(STATE_LABELS.get(card.secondary_state, card.secondary_state))}</div>"
        )

    return (
        f"<section class='card plan-card' data-relevant='{str(card.is_relevant).lower()}' data-search='{esc(search_text)}'>"
        "<div class='card-head'>"
        f"<div>"
        f"<h2><span class='mono'>{esc(card.symbol)}</span> "
        f"<span class='muted small'>{esc(card.market)}</span></h2>"
        f"<div><span class='mono'>{esc(price_str)}</span> <span class='muted small'>{esc(quote)}</span></div>"
        f"</div>"
        f"<div style='text-align:right'>"
        f"{_scenario_badge(card.scenario_type)}"
        f"<div class='state-label {_state_class(card.primary_state)}'>{esc(card.suggested_manual_attention_label)}</div>"
        f"{secondary_state_html}"
        f"<div class='action-label {_action_class(card.action_label)}'>{esc(_display_action_label(card.action_label))}</div>"
        f"<div class='tf-label'>{esc(card.timeframe_label)}</div>"
        f"</div>"
        "</div>"
        f"<div class='field-grid'>{metrics_html}</div>"
        "<div class='zones'>"
        f"<div><h3 style='color:var(--ok)'>Buy Zone</h3>{_zone_html(card.buy_zone, 'buy')}</div>"
        f"<div><h3 style='color:var(--warn)'>Sell Zone</h3>{_zone_html(card.sell_zone, 'sell')}</div>"
        f"<div><h3 style='color:var(--warn)'>Target Lifecycle</h3>{_target_lifecycle_html(card.target_level_statuses)}</div>"
        "</div>"
        f"<ul class='reasons'>{reasons_html}</ul>"
        f"{invalidation_html}"
        f"{_order_summary_html(card.order_summary, monitor_link)}"
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
) -> str:
    if rendered_at is None:
        rendered_at = format_ui_now()

    relevant_count = sum(1 for c in cards if c.is_relevant)
    total_count = len(cards)
    cards_html = "\n".join(render_plan_card(c, monitor_link=monitor_link) for c in cards)
    empty_note = "<div class='muted' style='padding:16px;grid-column:1/-1'>No symbols with a plan loaded.</div>" if not cards else ""

    return (
        "<!doctype html>\n<html lang='en'>\n<head>\n"
        "  <meta charset='utf-8'>\n"
        "  <meta http-equiv='refresh' content='120'>\n"
        "  <meta name='viewport' content='width=device-width, initial-scale=1'>\n"
        "  <title>Synth — Profit Plan</title>\n"
        f"{synth_favicon_head_html()}"
        f"  <style>{_CSS}</style>\n"
        "</head>\n<body>\n"
        "  <header>\n"
        "    <h1>Synth v2 — Profit Plan</h1>\n"
        f"    <div class='muted'>Rendered: {esc(rendered_at)} · Mode: {esc(broker_mode)}</div>\n"
        f"    <div class='muted small'>Relevant: {relevant_count} · Total: {total_count}</div>\n"
        f"{'' if not nav_html else f'    {nav_html}\\n'}"
        "    <div class='sticky-controls'>\n"
        "    <div class='view-toggle'>\n"
        "      <button id='btn-relevant' class='toggle-btn' onclick='setView(\"relevant\")'>Relevant candidates</button>\n"
        "      <button id='btn-all' class='toggle-btn' onclick='setView(\"all\")'>All candidates</button>\n"
        "    </div>\n"
        "    <div id='search-shell' class='search-shell'>\n"
        "      <input id='candidate-search' class='search-input' type='search' placeholder='Search symbol, market, scenario, state, action, horizon, context…' oninput='updateSearch()'>\n"
        "      <button class='toggle-btn' type='button' onclick='clearSearch()'>Clear</button>\n"
        "      <div id='matching-count' class='search-meta'>Matching 0 of 0</div>\n"
        "    </div>\n"
        "    </div>\n"
        "    <div class='muted small' style='margin-top:6px'>"
        "Human-readable scenario planning only. broker_writes=0. order_submission=0. No automatic placement."
        "</div>\n"
        "  </header>\n"
        "  <main>\n"
        f"    {empty_note}\n"
        f"    {cards_html}\n"
        "    <div id='no-results' class='no-results'>No candidates match the current search.</div>\n"
        "  </main>\n"
        f"  <script>{_build_client_js(storage_scope)}</script>\n"
        "</body>\n</html>"
    )


# ---------------------------------------------------------------------------
# JSON snapshot
# ---------------------------------------------------------------------------

def build_json_snapshot(
    cards: list[ProfitPlanCard],
    *,
    snapshot_ts: str | None = None,
    broker_mode: str = "offline",
) -> dict[str, Any]:
    return {
        "report": REPORT_NAME,
        "version": REPORT_VERSION,
        "snapshot_ts": snapshot_ts or datetime.now(UTC).isoformat(),
        "broker_mode": broker_mode,
        "broker_writes": 0,
        "order_submission": 0,
        "executor": "none",
        "symbols": [
            {
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
            }
            for c in cards
        ],
    }
