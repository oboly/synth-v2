from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.context.execution_context_policy import resolve_execution_context
from src.decision_gate.models import DecisionResult
from src.execution_planner.models import (
    PLANNABLE_DECISION_STATES,
    PLANNABLE_EXECUTION_INTENTS,
    ExecutionPlannerConfig,
    OpenPositionForExit,
    PlannedExecution,
)


def build_execution_plan(
    decision: DecisionResult,
    config: ExecutionPlannerConfig,
    reference_price_eur=None,
) -> PlannedExecution | None:
    if decision.decision_state not in PLANNABLE_DECISION_STATES and decision.decision_state != "WATCHLIST_PREPLAN_ALLOWED":
        return None

    if decision.execution_intent not in PLANNABLE_EXECUTION_INTENTS:
        return None

    now_utc = datetime.now(UTC).replace(tzinfo=None)

    regime = decision.regime_label_4h
    fib = None
    volatility = "MID"

    policy = resolve_execution_context(
        regime=regime,
        fib=fib,
        volatility=volatility,
    )

    if not policy["enabled"]:
        return None

    profile = policy["execution_profile"]

    if profile == "TREND_UP_MID_VOL":
        max_reprices = 4
        max_wait_seconds = 900
        max_chase_bps = Decimal("18")
    elif profile == "TREND_UP_HIGH_VOL":
        max_reprices = 5
        max_wait_seconds = 600
        max_chase_bps = Decimal("28")
    elif profile == "TREND_UP_LOW_VOL":
        max_reprices = 3
        max_wait_seconds = 1200
        max_chase_bps = Decimal("12")
    elif profile == "RANGE_MID_VOL":
        max_reprices = 4
        max_wait_seconds = 800
        max_chase_bps = Decimal("14")
    elif profile == "RANGE_HIGH_VOL":
        max_reprices = 5
        max_wait_seconds = 500
        max_chase_bps = Decimal("22")
    elif profile == "RANGE_LOW_VOL":
        max_reprices = 3
        max_wait_seconds = 1000
        max_chase_bps = Decimal("10")
    else:
        max_reprices = 2
        max_wait_seconds = 300
        max_chase_bps = Decimal("8")

    # === PREPARE / PREPLAN PATH ===
    if decision.execution_intent == "PREPARE_PLAN":
        if decision.decision_state == "WATCHLIST_PREPLAN_ALLOWED":
            target_fraction = config.watchlist_preplan_target_fraction
            plan_state = "IDLE"
        else:
            target_fraction = config.prepare_target_fraction
            plan_state = "IDLE"

        return PlannedExecution(
            account_id=decision.account_id,
            asset_id=decision.asset_id,
            sleeve_code=decision.sleeve_code,
            venue=decision.venue,
            side="BUY",
            desired_action="PREPARE_PLAN",
            execution_mode=config.execution_mode,
            plan_ts_utc=now_utc,
            valid_until_ts_utc=None,
            target_fraction=target_fraction,
            max_notional_eur=config.max_notional_eur,
            reference_price_eur=reference_price_eur,
            passive_price_eur=None,
            urgent_limit_price_eur=None,
            max_reprices=max_reprices,
            max_wait_seconds=max_wait_seconds,
            max_chase_bps=max_chase_bps,
            min_spread_bps_for_capture=config.min_spread_bps_for_capture,
            escalation_to_urgent_limit=False,
            abort_if_signal_invalidates=config.abort_if_signal_invalidates,
            plan_state=plan_state,
            notes=(
                f"profile={profile} "
                f"regime={regime} "
                f"planner={config.planner_name}:{config.planner_version}; "
                f"decision_state={decision.decision_state}; "
                f"execution_intent={decision.execution_intent}; "
                f"decision_reason={decision.decision_reason}"
            ),
        )

    # === EXECUTION PATH ===
    if decision.execution_intent == "PLACE_PASSIVE_LIMIT":
        return PlannedExecution(
            account_id=decision.account_id,
            asset_id=decision.asset_id,
            sleeve_code=decision.sleeve_code,
            venue=decision.venue,
            side="BUY",
            desired_action="SPREAD_CAPTURE_PASSIVE",
            execution_mode=config.execution_mode,
            plan_ts_utc=now_utc,
            valid_until_ts_utc=None,
            target_fraction=config.execute_target_fraction,
            max_notional_eur=config.max_notional_eur,
            reference_price_eur=reference_price_eur,
            passive_price_eur=None,
            urgent_limit_price_eur=None,
            max_reprices=max_reprices,
            max_wait_seconds=max_wait_seconds,
            max_chase_bps=max_chase_bps,
            min_spread_bps_for_capture=config.min_spread_bps_for_capture,
            escalation_to_urgent_limit=config.escalation_to_urgent_limit,
            abort_if_signal_invalidates=config.abort_if_signal_invalidates,
            plan_state="PLANNED",
            notes=(
                f"profile={profile} "
                f"regime={regime} "
                f"planner={config.planner_name}:{config.planner_version}; "
                f"decision_state={decision.decision_state}; "
                f"execution_intent={decision.execution_intent}; "
                f"decision_reason={decision.decision_reason}"
            ),
        )

    return None


def build_exit_plan_from_position(
    position: OpenPositionForExit,
    config: ExecutionPlannerConfig,
    reference_price_eur=None,
) -> PlannedExecution:
    now_utc = datetime.now(UTC).replace(tzinfo=None)

    return PlannedExecution(
        account_id=position.account_id,
        asset_id=position.asset_id,
        sleeve_code=position.sleeve_code,
        venue=position.venue,
        side="SELL",
        desired_action="CLOSE_POSITION_MARKET_PAPER",
        execution_mode=config.execution_mode,
        plan_ts_utc=now_utc,
        valid_until_ts_utc=None,
        target_fraction=position.qty,
        max_notional_eur=position.market_value_eur,
        reference_price_eur=reference_price_eur,
        passive_price_eur=None,
        urgent_limit_price_eur=None,
        max_reprices=config.max_reprices,
        max_wait_seconds=config.max_wait_seconds,
        max_chase_bps=config.max_chase_bps,
        min_spread_bps_for_capture=config.min_spread_bps_for_capture,
        escalation_to_urgent_limit=False,
        abort_if_signal_invalidates=False,
        plan_state="PLANNED",
        notes=(
            f"planner={config.planner_name}:{config.planner_version}; "
            f"exit_from_position=1; "
            f"portfolio_position_qty={position.qty}; "
            f"avg_entry_price={position.avg_entry_price}; "
            f"market_value_eur={position.market_value_eur}"
        ),
    )
