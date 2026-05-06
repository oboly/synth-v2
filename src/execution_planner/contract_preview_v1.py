from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Any, Final


VALID_SIDES: Final[set[str]] = {"BUY", "SELL"}

VALID_INTENT_TYPES: Final[set[str]] = {
    "PREPARE_PLAN",
    "PLACE_PASSIVE_LIMIT",
    "PLACE_LADDER",
    "EXIT_PASSIVE_LIMIT",
    "EXIT_LADDER",
}

SLEEVE_PROFILES: Final[dict[str, dict[str, Any]]] = {
    "CORE_STRUCTURAL": {
        "execution_style": "PASSIVE_PATIENT",
        "max_reprices": 8,
        "max_wait_seconds": 3600,
        "max_chase_bps": Decimal("10"),
        "min_spread_bps_for_capture": Decimal("3"),
        "escalation_to_urgent_limit": False,
        "abort_if_signal_invalidates": True,
    },
    "SWING_STRUCTURAL": {
        "execution_style": "PASSIVE_SMART_REPRICE",
        "max_reprices": 5,
        "max_wait_seconds": 1800,
        "max_chase_bps": Decimal("15"),
        "min_spread_bps_for_capture": Decimal("3"),
        "escalation_to_urgent_limit": True,
        "abort_if_signal_invalidates": True,
    },
    "TACTICAL_PULSE": {
        "execution_style": "HYBRID_FAST_LIMIT",
        "max_reprices": 3,
        "max_wait_seconds": 600,
        "max_chase_bps": Decimal("25"),
        "min_spread_bps_for_capture": Decimal("2"),
        "escalation_to_urgent_limit": True,
        "abort_if_signal_invalidates": True,
    },
    "EXPERIMENTAL": {
        "execution_style": "CONFIG_REQUIRED",
        "max_reprices": 2,
        "max_wait_seconds": 300,
        "max_chase_bps": Decimal("10"),
        "min_spread_bps_for_capture": Decimal("3"),
        "escalation_to_urgent_limit": False,
        "abort_if_signal_invalidates": True,
    },
}


@dataclass(frozen=True)
class ExecutionIntentPreview:
    account_id: int
    sleeve_code: str
    asset_id: int
    symbol: str
    venue: str
    side: str
    intent_type: str
    max_notional_eur: Decimal | None
    quantity_base: Decimal | None
    decision_state: str
    decision_reason: str
    execution_mode: str = "paper"
    ladder_levels: tuple[tuple[Decimal, Decimal], ...] = ()


@dataclass(frozen=True)
class ExecutionMarketContextPreview:
    reference_price_eur: Decimal
    best_bid_eur: Decimal
    best_ask_eur: Decimal
    tick_size: Decimal
    spread_bps: Decimal | None
    volatility_bucket: str | None
    regime_label: str | None
    execution_zone_low: Decimal | None = None
    execution_zone_high: Decimal | None = None
    invalidation_price_eur: Decimal | None = None
    asset_exit_profile_hint: str | None = None
    context_asof_ts_utc: str | None = None


@dataclass(frozen=True)
class ExecutionPlanLegPreview:
    leg_index: int
    side: str
    leg_type: str
    target_price_eur: Decimal | None
    target_fraction: Decimal
    target_notional_eur: Decimal | None
    quantity_base: Decimal | None
    post_only: bool
    time_in_force: str
    max_reprices: int
    max_wait_seconds: int
    max_chase_bps: Decimal
    min_spread_bps_for_capture: Decimal
    escalation_to_urgent_limit: bool
    abort_if_signal_invalidates: bool
    leg_state: str


@dataclass(frozen=True)
class ExecutionPlanPreview:
    account_id: int
    sleeve_code: str
    asset_id: int
    symbol: str
    venue: str
    side: str
    plan_type: str
    execution_mode: str
    plan_state: str
    source_decision_state: str
    source_decision_reason: str
    regime_label: str | None
    volatility_bucket: str | None
    asset_exit_profile_hint: str | None
    total_target_fraction: Decimal
    max_notional_eur: Decimal | None
    quantity_base: Decimal | None
    reference_price_eur: Decimal
    best_bid_eur: Decimal
    best_ask_eur: Decimal
    tick_size: Decimal
    notes: str
    legs: list[ExecutionPlanLegPreview]


def _normalize_upper(value: str, field_name: str) -> str:
    normalized = value.strip().upper()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


def _quantize_to_tick(price: Decimal, tick_size: Decimal) -> Decimal:
    if tick_size <= Decimal("0"):
        raise ValueError("tick_size must be > 0")

    ticks = (price / tick_size).to_integral_value(rounding=ROUND_DOWN)
    return ticks * tick_size


def _passive_price_for_side(side: str, context: ExecutionMarketContextPreview) -> Decimal:
    if side == "BUY":
        return _quantize_to_tick(context.best_bid_eur + context.tick_size, context.tick_size)

    if side == "SELL":
        return _quantize_to_tick(context.best_ask_eur - context.tick_size, context.tick_size)

    raise ValueError(f"unsupported side: {side}")


def _plan_type_for_intent(intent_type: str, side: str) -> str:
    if intent_type == "PREPARE_PLAN":
        return "PREPARE_ACCUMULATION"

    if intent_type == "PLACE_PASSIVE_LIMIT":
        return "PASSIVE_ENTRY" if side == "BUY" else "PASSIVE_EXIT"

    if intent_type == "PLACE_LADDER":
        return "PASSIVE_ENTRY_LADDER" if side == "BUY" else "PASSIVE_EXIT_LADDER"

    if intent_type == "EXIT_PASSIVE_LIMIT":
        return "PASSIVE_EXIT"

    if intent_type == "EXIT_LADDER":
        return "PASSIVE_EXIT_LADDER"

    raise ValueError(f"unsupported intent_type: {intent_type}")


def _target_fraction_for_intent(intent_type: str) -> Decimal:
    if intent_type == "PREPARE_PLAN":
        return Decimal("0.03300000")
    return Decimal("1.00000000")


def _quantity_from_notional(
    *,
    notional_eur: Decimal,
    price_eur: Decimal,
) -> Decimal:
    if price_eur <= Decimal("0"):
        raise ValueError("price_eur must be > 0 for notional-to-quantity conversion")
    return (notional_eur / price_eur).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)


def _scaled_quantity(
    *,
    quantity_base: Decimal,
    fraction: Decimal,
) -> Decimal:
    return (quantity_base * fraction).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)


def _build_single_leg(
    *,
    side: str,
    intent_type: str,
    target_fraction: Decimal,
    max_notional_eur: Decimal | None,
    quantity_base: Decimal | None,
    context: ExecutionMarketContextPreview,
    profile: dict[str, Any],
) -> ExecutionPlanLegPreview:
    passive_price = None if intent_type == "PREPARE_PLAN" else _passive_price_for_side(side, context)

    target_notional_eur = None
    target_quantity_base = quantity_base

    if passive_price is not None:
        if side == "BUY" and max_notional_eur is not None:
            target_notional_eur = max_notional_eur * target_fraction
            target_quantity_base = _quantity_from_notional(
                notional_eur=target_notional_eur,
                price_eur=passive_price,
            )
        elif quantity_base is not None:
            target_quantity_base = _scaled_quantity(
                quantity_base=quantity_base,
                fraction=target_fraction,
            )
            target_notional_eur = target_quantity_base * passive_price

    return ExecutionPlanLegPreview(
        leg_index=1,
        side=side,
        leg_type="PREPARE_ONLY" if intent_type == "PREPARE_PLAN" else "PASSIVE_LIMIT",
        target_price_eur=passive_price,
        target_fraction=target_fraction,
        target_notional_eur=target_notional_eur,
        quantity_base=target_quantity_base,
        post_only=True,
        time_in_force="GTC",
        max_reprices=int(profile["max_reprices"]),
        max_wait_seconds=int(profile["max_wait_seconds"]),
        max_chase_bps=Decimal(str(profile["max_chase_bps"])),
        min_spread_bps_for_capture=Decimal(str(profile["min_spread_bps_for_capture"])),
        escalation_to_urgent_limit=bool(profile["escalation_to_urgent_limit"]),
        abort_if_signal_invalidates=bool(profile["abort_if_signal_invalidates"]),
        leg_state="IDLE",
    )


def _validate_ladder_levels(
    *,
    side: str,
    levels: tuple[tuple[Decimal, Decimal], ...],
) -> None:
    if not levels:
        raise ValueError("ladder intent requires at least one ladder level")

    fraction_sum = sum((fraction for _price, fraction in levels), Decimal("0"))

    if fraction_sum != Decimal("1") and fraction_sum != Decimal("1.00000000"):
        raise ValueError(f"ladder target fractions must sum to 1.0, got {fraction_sum}")

    previous_price: Decimal | None = None
    for price, fraction in levels:
        if price <= Decimal("0"):
            raise ValueError("ladder target prices must be > 0")
        if fraction <= Decimal("0"):
            raise ValueError("ladder target fractions must be > 0")

        if previous_price is not None:
            if side == "BUY" and price > previous_price:
                raise ValueError("BUY ladder prices must be descending or equal")
            if side == "SELL" and price < previous_price:
                raise ValueError("SELL ladder prices must be ascending or equal")

        previous_price = price


def _build_ladder_legs(
    *,
    side: str,
    levels: tuple[tuple[Decimal, Decimal], ...],
    max_notional_eur: Decimal | None,
    quantity_base: Decimal | None,
    tick_size: Decimal,
    profile: dict[str, Any],
) -> list[ExecutionPlanLegPreview]:
    _validate_ladder_levels(side=side, levels=levels)

    legs: list[ExecutionPlanLegPreview] = []

    for idx, (price, fraction) in enumerate(levels, start=1):
        target_price = _quantize_to_tick(price, tick_size)
        target_notional_eur = None
        target_quantity_base = None

        if side == "BUY" and max_notional_eur is not None:
            target_notional_eur = max_notional_eur * fraction
            target_quantity_base = _quantity_from_notional(
                notional_eur=target_notional_eur,
                price_eur=target_price,
            )
        elif quantity_base is not None:
            target_quantity_base = _scaled_quantity(
                quantity_base=quantity_base,
                fraction=fraction,
            )
            target_notional_eur = target_quantity_base * target_price

        legs.append(
            ExecutionPlanLegPreview(
                leg_index=idx,
                side=side,
                leg_type="PASSIVE_LIMIT",
                target_price_eur=target_price,
                target_fraction=fraction,
                target_notional_eur=target_notional_eur,
                quantity_base=target_quantity_base,
                post_only=True,
                time_in_force="GTC",
                max_reprices=int(profile["max_reprices"]),
                max_wait_seconds=int(profile["max_wait_seconds"]),
                max_chase_bps=Decimal(str(profile["max_chase_bps"])),
                min_spread_bps_for_capture=Decimal(str(profile["min_spread_bps_for_capture"])),
                escalation_to_urgent_limit=bool(profile["escalation_to_urgent_limit"]),
                abort_if_signal_invalidates=bool(profile["abort_if_signal_invalidates"]),
                leg_state="IDLE",
            )
        )

    return legs


def build_execution_plan_preview(
    *,
    intent: ExecutionIntentPreview,
    context: ExecutionMarketContextPreview,
) -> ExecutionPlanPreview:
    side = _normalize_upper(intent.side, "side")
    intent_type = _normalize_upper(intent.intent_type, "intent_type")
    sleeve_code = _normalize_upper(intent.sleeve_code, "sleeve_code")
    execution_mode = _normalize_upper(intent.execution_mode, "execution_mode")

    if side not in VALID_SIDES:
        raise ValueError(f"side must be one of {sorted(VALID_SIDES)}")

    if intent_type not in VALID_INTENT_TYPES:
        raise ValueError(f"intent_type must be one of {sorted(VALID_INTENT_TYPES)}")

    if execution_mode != "PAPER":
        raise ValueError("contract preview only supports execution_mode=paper")

    if sleeve_code not in SLEEVE_PROFILES:
        raise ValueError(f"unsupported sleeve_code: {sleeve_code}")

    if intent_type.startswith("EXIT") and side != "SELL":
        raise ValueError("EXIT intent requires side=SELL")

    if intent_type == "PLACE_LADDER" and side != "BUY":
        raise ValueError("PLACE_LADDER currently requires side=BUY; use EXIT_LADDER for SELL ladder exits")

    profile = SLEEVE_PROFILES[sleeve_code]
    plan_type = _plan_type_for_intent(intent_type, side)
    total_target_fraction = _target_fraction_for_intent(intent_type)

    if intent_type in {"PLACE_LADDER", "EXIT_LADDER"}:
        legs = _build_ladder_legs(
            side=side,
            levels=intent.ladder_levels,
            max_notional_eur=intent.max_notional_eur,
            quantity_base=intent.quantity_base,
            tick_size=context.tick_size,
            profile=profile,
        )
    else:
        legs = [
            _build_single_leg(
                side=side,
                intent_type=intent_type,
                target_fraction=total_target_fraction,
                max_notional_eur=intent.max_notional_eur,
                quantity_base=intent.quantity_base,
                context=context,
                profile=profile,
            )
        ]

    return ExecutionPlanPreview(
        account_id=intent.account_id,
        sleeve_code=sleeve_code,
        asset_id=intent.asset_id,
        symbol=intent.symbol,
        venue=intent.venue,
        side=side,
        plan_type=plan_type,
        execution_mode="paper",
        plan_state="PREVIEW_ONLY",
        source_decision_state=intent.decision_state,
        source_decision_reason=intent.decision_reason,
        regime_label=context.regime_label,
        volatility_bucket=context.volatility_bucket,
        asset_exit_profile_hint=context.asset_exit_profile_hint,
        total_target_fraction=total_target_fraction,
        max_notional_eur=intent.max_notional_eur,
        quantity_base=intent.quantity_base,
        reference_price_eur=context.reference_price_eur,
        best_bid_eur=context.best_bid_eur,
        best_ask_eur=context.best_ask_eur,
        tick_size=context.tick_size,
        notes=(
            f"preview_only=1; "
            f"execution_style={profile['execution_style']}; "
            f"intent_type={intent_type}; "
            f"asset_exit_profile_hint_is_metadata_only=1; "
            f"no_db_writes=1; no_executor=1"
        ),
        legs=legs,
    )


def preview_to_dict(plan: ExecutionPlanPreview) -> dict[str, Any]:
    raw = asdict(plan)

    def convert(value: Any) -> Any:
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, list):
            return [convert(item) for item in value]
        if isinstance(value, dict):
            return {key: convert(item) for key, item in value.items()}
        return value

    return convert(raw)
