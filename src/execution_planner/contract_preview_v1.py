from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN
from typing import Any, Final

from src.decision_gate import manual_execution_approval_v1 as approval_authority
from src.decision_gate.manual_execution_approval_v1 import (
    APPROVAL_STATE_APPROVED,
    APPROVAL_TTL_SECONDS,
    ManualExecutionApprovalRecord,
)
from src.execution_planner.canonical_rounding_v1 import round_price_for_side
from src.execution_planner.sell_authority_guard_v1 import (
    UnauthorizedManualExecutionCallError,
)
from src.manual_execution.manual_execution_request_v1 import (
    MODE_PAPER,
    QUANTITY_POLICY_LADDER_LEVELS,
    ManualExecutionRequest,
)
from src.market_rules.venue_execution_constraints_v1 import (
    STATUS_FRESH,
    VenueExecutionConstraints,
)
from src.manual_execution import _trusted_clock_v1 as trusted_clock


VALID_SIDES: Final[set[str]] = {"BUY", "SELL"}

VALID_INTENT_TYPES: Final[set[str]] = {
    "PREPARE_PLAN",
    "PLACE_PASSIVE_LIMIT",
    "PLACE_LADDER",
    "EXIT_PASSIVE_LIMIT",
    "EXIT_LADDER",
}

_MANUAL_EXECUTION_INTENT_TYPES: Final[frozenset[str]] = frozenset(
    {"EXIT_PASSIVE_LIMIT", "EXIT_LADDER"}
)


class MissingOrInvalidApprovalError(PermissionError):
    """Raised when persisted manual approval resolution fails closed."""


@dataclass(frozen=True)
class ManualSellPlanningInputs:
    market_context: "ExecutionMarketContextPreview"
    venue_constraints: VenueExecutionConstraints
    sleeve_code: str


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


def _quantize_to_tick(price: Decimal, tick_size: Decimal, side: str) -> Decimal:
    """Side-aware tick rounding, delegating to the single canonical rounding
    service (src.execution_planner.canonical_rounding_v1). This used to be
    an unconditional ROUND_DOWN regardless of side, which rounded SELL
    prices below the analytical target — see
    docs/architecture/manual_execution_ladder_future_readiness_audit_v1.md
    finding F3. Do not reintroduce a local, side-unaware quantizer here."""
    return round_price_for_side(price, tick_size, side)


def _passive_price_for_side(side: str, context: ExecutionMarketContextPreview) -> Decimal:
    if side == "BUY":
        return _quantize_to_tick(context.best_bid_eur + context.tick_size, context.tick_size, side)

    if side == "SELL":
        return _quantize_to_tick(context.best_ask_eur - context.tick_size, context.tick_size, side)

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

    if fraction_sum != Decimal("1"):
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
        target_price = _quantize_to_tick(price, tick_size, side)
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


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _reject_mismatch(condition: bool, message: str) -> None:
    if condition:
        raise MissingOrInvalidApprovalError(message)


def _validate_persisted_manual_execution_approval(
    *,
    request: ManualExecutionRequest,
    approval: ManualExecutionApprovalRecord,
) -> Decimal:
    """Validate every persisted approval, request, reservation, and snapshot binding."""
    _reject_mismatch(request.request_id is None, "manual request is not persisted")
    _reject_mismatch(approval.request_id != request.request_id, "approval request mismatch")
    _reject_mismatch(
        approval.idempotency_key
        != f"manual_execution_approval:{request.idempotency_key}",
        "approval idempotency binding mismatch",
    )
    _reject_mismatch(
        approval.trading_account_id != request.trading_account_id,
        "approval account mismatch",
    )
    _reject_mismatch(approval.account_code != request.account_code, "approval account_code mismatch")
    _reject_mismatch(approval.venue != request.venue, "approval venue mismatch")
    _reject_mismatch(approval.asset_id != request.asset_id, "approval asset mismatch")
    _reject_mismatch(approval.base_asset != request.base_asset, "approval base_asset mismatch")
    _reject_mismatch(approval.quote_asset != request.quote_asset, "approval quote_asset mismatch")
    _reject_mismatch(approval.side != request.side, "approval side mismatch")
    _reject_mismatch(approval.mode != request.mode, "approval mode mismatch")
    _reject_mismatch(request.mode != MODE_PAPER, "manual SELL planner only supports PAPER")
    _reject_mismatch(request.side != "SELL", "manual SELL planner requires side=SELL")
    _reject_mismatch(
        request.provenance_id is None or approval.provenance_id != request.provenance_id,
        "approval provenance binding is missing or mismatched",
    )
    _reject_mismatch(
        approval.approval_state != APPROVAL_STATE_APPROVED,
        "approval state is not APPROVED",
    )
    _reject_mismatch(
        approval.approved_quantity_base <= 0,
        "approved quantity must be positive",
    )

    _reject_mismatch(
        approval.reservation_id <= 0,
        "approval reservation binding is missing",
    )
    _reject_mismatch(
        approval.reservation_id != approval.persisted_reservation_id,
        "approval reservation ID mismatch",
    )
    _reject_mismatch(
        approval.reservation_request_id != request.request_id,
        "reservation request mismatch",
    )
    _reject_mismatch(
        approval.reservation_trading_account_id != request.trading_account_id,
        "reservation account mismatch",
    )
    _reject_mismatch(approval.reservation_venue != request.venue, "reservation venue mismatch")
    _reject_mismatch(
        approval.reservation_asset_id != request.asset_id,
        "reservation asset mismatch",
    )
    _reject_mismatch(
        approval.reservation_symbol != request.base_asset,
        "reservation base asset mismatch",
    )
    _reject_mismatch(
        approval.reservation_quantity_base != approval.approved_quantity_base,
        "reservation quantity mismatch",
    )
    _reject_mismatch(
        approval.reservation_state != "APPROVED_NOT_SUBMITTED",
        "reservation state is not planner-eligible",
    )

    _reject_mismatch(approval.wallet_snapshot_id <= 0, "wallet snapshot binding is missing")
    _reject_mismatch(
        approval.wallet_snapshot_id != approval.persisted_snapshot_id,
        "approval wallet snapshot ID mismatch",
    )
    _reject_mismatch(
        approval.snapshot_trading_account_id != request.trading_account_id,
        "wallet snapshot account mismatch",
    )
    _reject_mismatch(approval.snapshot_venue != request.venue, "wallet snapshot venue mismatch")
    _reject_mismatch(
        approval.snapshot_asset_id != request.asset_id,
        "wallet snapshot asset mismatch",
    )
    _reject_mismatch(
        _aware(approval.wallet_snapshot_version_ts_utc)
        != _aware(approval.snapshot_ts_utc),
        "wallet snapshot version mismatch",
    )

    approved_ts = _aware(approval.approved_ts_utc)
    expires_ts = _aware(approval.expires_ts_utc)
    checked_at_utc = _aware(trusted_clock.utc_now())
    _reject_mismatch(expires_ts <= approved_ts, "approval expiry boundary is invalid")
    _reject_mismatch(
        expires_ts - approved_ts > timedelta(seconds=APPROVAL_TTL_SECONDS),
        "approval expiry exceeds the canonical freshness window",
    )
    _reject_mismatch(approved_ts > checked_at_utc, "approval timestamp is in the future")
    _reject_mismatch(checked_at_utc >= expires_ts, "approval has expired")

    return approval.approved_quantity_base


def _build_buy_execution_plan_preview(
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
    if side != "BUY":
        raise UnauthorizedManualExecutionCallError(
            "generic private plan construction is BUY-only"
        )

    if intent_type not in VALID_INTENT_TYPES:
        raise ValueError(f"intent_type must be one of {sorted(VALID_INTENT_TYPES)}")

    if execution_mode != "PAPER":
        raise ValueError("contract preview only supports execution_mode=paper")

    if sleeve_code not in SLEEVE_PROFILES:
        raise ValueError(f"unsupported sleeve_code: {sleeve_code}")

    if (
        intent_type != "PREPARE_PLAN"
        and intent.max_notional_eur is None
        and intent.quantity_base is None
    ):
        raise ValueError("non-PREPARE_PLAN intents require max_notional_eur or quantity_base")

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
        execution_mode="PAPER",
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


def build_execution_plan_preview(
    *,
    intent: ExecutionIntentPreview,
    context: ExecutionMarketContextPreview,
) -> ExecutionPlanPreview:
    """Generic BUY-only contract preview.

    Every SELL spelling, including legacy PLACE_* aliases and EXIT_* names,
    fails before private plan construction. Manual SELL must use
    ``build_manual_sell_execution_plan_preview``.
    """
    side = _normalize_upper(intent.side, "side")
    intent_type = _normalize_upper(intent.intent_type, "intent_type")
    if side == "SELL" or intent_type in _MANUAL_EXECUTION_INTENT_TYPES:
        raise UnauthorizedManualExecutionCallError(
            "generic execution planner does not accept SELL/EXIT intents; "
            "route through manual_execution_service_v1.process()"
        )
    return _build_buy_execution_plan_preview(intent=intent, context=context)


def build_manual_sell_execution_plan_preview(
    *,
    request_id: int,
    approval_id: int,
    planning_inputs: ManualSellPlanningInputs,
) -> ExecutionPlanPreview:
    """Canonical manual SELL planner boundary.

    The caller supplies persisted identities and non-authoritative planning
    inputs only. Request, approval, reservation, snapshot, quantity,
    provenance, mode, and freshness are resolved through the decision-gate
    subsystem's non-substitutable production authority.
    """
    if request_id <= 0:
        raise MissingOrInvalidApprovalError("request_id must be a persisted positive ID")
    if approval_id <= 0:
        raise MissingOrInvalidApprovalError("approval_id must be a persisted positive ID")

    try:
        persisted_authority = (
            approval_authority.resolve_persisted_manual_execution_authority(
                request_id=request_id,
                approval_id=approval_id,
            )
        )
    except LookupError as exc:
        raise MissingOrInvalidApprovalError(str(exc)) from exc

    request = persisted_authority.request
    approval = persisted_authority.approval
    _reject_mismatch(
        request.request_id != request_id,
        "persisted manual execution request identity mismatch",
    )
    _reject_mismatch(
        approval.approval_id != approval_id,
        "persisted manual execution approval identity mismatch",
    )

    approved_quantity = _validate_persisted_manual_execution_approval(
        request=request,
        approval=approval,
    )

    constraints = planning_inputs.venue_constraints
    if constraints.status != STATUS_FRESH:
        raise ValueError("venue execution constraints are not FRESH")
    if constraints.venue.strip().lower() != request.venue:
        raise ValueError("venue execution constraints venue mismatch")
    expected_market = f"{request.base_asset}-{request.quote_asset}"
    normalized_market = constraints.market.strip().upper().replace("/", "-")
    if normalized_market != expected_market:
        raise ValueError("venue execution constraints pair mismatch")

    context = replace(
        planning_inputs.market_context,
        tick_size=constraints.tick_size,
    )
    intent_type = (
        "EXIT_LADDER"
        if request.quantity_policy == QUANTITY_POLICY_LADDER_LEVELS
        else "EXIT_PASSIVE_LIMIT"
    )
    sleeve_code = _normalize_upper(planning_inputs.sleeve_code, "sleeve_code")
    if sleeve_code not in SLEEVE_PROFILES:
        raise ValueError(f"unsupported sleeve_code: {sleeve_code}")
    profile = SLEEVE_PROFILES[sleeve_code]
    total_target_fraction = _target_fraction_for_intent(intent_type)
    if intent_type == "EXIT_LADDER":
        legs = _build_ladder_legs(
            side="SELL",
            levels=request.ladder_levels,
            max_notional_eur=None,
            quantity_base=approved_quantity,
            tick_size=context.tick_size,
            profile=profile,
        )
    else:
        legs = [
            _build_single_leg(
                side="SELL",
                intent_type=intent_type,
                target_fraction=total_target_fraction,
                max_notional_eur=None,
                quantity_base=approved_quantity,
                context=context,
                profile=profile,
            )
        ]

    return ExecutionPlanPreview(
        account_id=request.trading_account_id,
        sleeve_code=sleeve_code,
        asset_id=request.asset_id,
        symbol=request.base_asset,
        venue=request.venue,
        side="SELL",
        plan_type=_plan_type_for_intent(intent_type, "SELL"),
        execution_mode=MODE_PAPER,
        plan_state="PREVIEW_ONLY",
        source_decision_state=APPROVAL_STATE_APPROVED,
        source_decision_reason=approval.decision_reason,
        regime_label=context.regime_label,
        volatility_bucket=context.volatility_bucket,
        asset_exit_profile_hint=context.asset_exit_profile_hint,
        total_target_fraction=total_target_fraction,
        max_notional_eur=None,
        quantity_base=approved_quantity,
        reference_price_eur=context.reference_price_eur,
        best_bid_eur=context.best_bid_eur,
        best_ask_eur=context.best_ask_eur,
        tick_size=context.tick_size,
        notes=(
            f"preview_only=1; "
            f"execution_style={profile['execution_style']}; "
            f"intent_type={intent_type}; "
            f"persisted_approval_id={approval.approval_id}; "
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
