from __future__ import annotations

from src.decision_gate.models import (
    ACTIVE_SLEEVE_STATUSES,
    DecisionGateConfig,
    DecisionResult,
    DuplicateState,
    ELIGIBLE_SELECTION_STATES,
    SelectionInputRow,
    SleeveState,
)


def evaluate_selection_for_account(
    row: SelectionInputRow,
    account_id: int,
    sleeve_code: str,
    sleeve_state: SleeveState | None,
    duplicate_state: DuplicateState,
    config: DecisionGateConfig,
    has_open_order: bool = False,
) -> DecisionResult:
    if row.selection_state not in ELIGIBLE_SELECTION_STATES:
        return DecisionResult(
            account_id=account_id,
            sleeve_code=sleeve_code,
            selection_state_id=row.selection_state_id,
            asset_id=row.asset_id,
            symbol=row.symbol,
            venue=row.venue,
            asof_ts_utc=row.asof_ts_utc,
            selection_state=row.selection_state,
            decision_state="NO_ACTION",
            decision_reason="SELECTION_NOT_ELIGIBLE",
            execution_intent="NONE",
            min_available_equity_eur=config.min_available_equity_eur,
            available_equity_eur=None,
            has_active_plan=False,
            has_open_position=False,
            summary_text=row.summary_text,
        )

    if sleeve_state is None:
        return DecisionResult(
            account_id=account_id,
            sleeve_code=sleeve_code,
            selection_state_id=row.selection_state_id,
            asset_id=row.asset_id,
            symbol=row.symbol,
            venue=row.venue,
            asof_ts_utc=row.asof_ts_utc,
            selection_state=row.selection_state,
            decision_state="BLOCKED_SLEEVE",
            decision_reason="SLEEVE_NOT_FOUND",
            execution_intent="NONE",
            min_available_equity_eur=config.min_available_equity_eur,
            available_equity_eur=None,
            has_active_plan=duplicate_state.has_active_plan,
            has_open_position=duplicate_state.has_open_position,
            summary_text=row.summary_text,
        )

    if sleeve_state.sleeve_status not in ACTIVE_SLEEVE_STATUSES:
        return DecisionResult(
            account_id=account_id,
            sleeve_code=sleeve_code,
            selection_state_id=row.selection_state_id,
            asset_id=row.asset_id,
            symbol=row.symbol,
            venue=row.venue,
            asof_ts_utc=row.asof_ts_utc,
            selection_state=row.selection_state,
            decision_state="BLOCKED_SLEEVE",
            decision_reason="SLEEVE_NOT_ACTIVE",
            execution_intent="NONE",
            min_available_equity_eur=config.min_available_equity_eur,
            available_equity_eur=sleeve_state.available_equity_eur,
            has_active_plan=duplicate_state.has_active_plan,
            has_open_position=duplicate_state.has_open_position,
            summary_text=row.summary_text,
        )

    if has_open_order:
        return DecisionResult(
            account_id=account_id,
            sleeve_code=sleeve_code,
            selection_state_id=row.selection_state_id,
            asset_id=row.asset_id,
            symbol=row.symbol,
            venue=row.venue,
            asof_ts_utc=row.asof_ts_utc,
            selection_state=row.selection_state,
            decision_state="BLOCKED_OPEN_ORDER",
            decision_reason="OPEN_ORDER_EXISTS",
            execution_intent="NONE",
            min_available_equity_eur=config.min_available_equity_eur,
            available_equity_eur=sleeve_state.available_equity_eur,
            has_active_plan=duplicate_state.has_active_plan,
            has_open_position=duplicate_state.has_open_position,
            summary_text=row.summary_text,
        )

    if duplicate_state.has_active_plan:
        return DecisionResult(
            account_id=account_id,
            sleeve_code=sleeve_code,
            selection_state_id=row.selection_state_id,
            asset_id=row.asset_id,
            symbol=row.symbol,
            venue=row.venue,
            asof_ts_utc=row.asof_ts_utc,
            selection_state=row.selection_state,
            decision_state="BLOCKED_ACTIVE_PLAN",
            decision_reason="ACTIVE_PLAN_EXISTS",
            execution_intent="NONE",
            min_available_equity_eur=config.min_available_equity_eur,
            available_equity_eur=sleeve_state.available_equity_eur,
            has_active_plan=True,
            has_open_position=duplicate_state.has_open_position,
            summary_text=row.summary_text,
        )

    if duplicate_state.has_open_position:
        return DecisionResult(
            account_id=account_id,
            sleeve_code=sleeve_code,
            selection_state_id=row.selection_state_id,
            asset_id=row.asset_id,
            symbol=row.symbol,
            venue=row.venue,
            asof_ts_utc=row.asof_ts_utc,
            selection_state=row.selection_state,
            decision_state="BLOCKED_POSITION",
            decision_reason="POSITION_EXISTS",
            execution_intent="NONE",
            min_available_equity_eur=config.min_available_equity_eur,
            available_equity_eur=sleeve_state.available_equity_eur,
            has_active_plan=duplicate_state.has_active_plan,
            has_open_position=True,
            summary_text=row.summary_text,
        )

    if sleeve_state.available_equity_eur < config.min_available_equity_eur:
        return DecisionResult(
            account_id=account_id,
            sleeve_code=sleeve_code,
            selection_state_id=row.selection_state_id,
            asset_id=row.asset_id,
            symbol=row.symbol,
            venue=row.venue,
            asof_ts_utc=row.asof_ts_utc,
            selection_state=row.selection_state,
            decision_state="BLOCKED_BALANCE",
            decision_reason="INSUFFICIENT_BALANCE",
            execution_intent="NONE",
            min_available_equity_eur=config.min_available_equity_eur,
            available_equity_eur=sleeve_state.available_equity_eur,
            has_active_plan=duplicate_state.has_active_plan,
            has_open_position=duplicate_state.has_open_position,
            summary_text=row.summary_text,
        )

    if row.selection_state == "PREPARE":
        return DecisionResult(
            account_id=account_id,
            sleeve_code=sleeve_code,
            selection_state_id=row.selection_state_id,
            asset_id=row.asset_id,
            symbol=row.symbol,
            venue=row.venue,
            asof_ts_utc=row.asof_ts_utc,
            selection_state=row.selection_state,
            decision_state="PREPARE_ALLOWED",
            decision_reason="OK",
            execution_intent="PREPARE_PLAN",
            min_available_equity_eur=config.min_available_equity_eur,
            available_equity_eur=sleeve_state.available_equity_eur,
            has_active_plan=False,
            has_open_position=False,
            summary_text=row.summary_text,
        )

    if row.selection_state == "BUY_READY":
        return DecisionResult(
            account_id=account_id,
            sleeve_code=sleeve_code,
            selection_state_id=row.selection_state_id,
            asset_id=row.asset_id,
            symbol=row.symbol,
            venue=row.venue,
            asof_ts_utc=row.asof_ts_utc,
            selection_state=row.selection_state,
            decision_state="EXECUTION_ALLOWED",
            decision_reason="OK",
            execution_intent="PLACE_PASSIVE_LIMIT",
            min_available_equity_eur=config.min_available_equity_eur,
            available_equity_eur=sleeve_state.available_equity_eur,
            has_active_plan=False,
            has_open_position=False,
            summary_text=row.summary_text,
        )

    return DecisionResult(
        account_id=account_id,
        sleeve_code=sleeve_code,
        selection_state_id=row.selection_state_id,
        asset_id=row.asset_id,
        symbol=row.symbol,
        venue=row.venue,
        asof_ts_utc=row.asof_ts_utc,
        selection_state=row.selection_state,
        decision_state="NO_ACTION",
        decision_reason="FALLBACK",
        execution_intent="NONE",
        min_available_equity_eur=config.min_available_equity_eur,
        available_equity_eur=sleeve_state.available_equity_eur,
        has_active_plan=False,
        has_open_position=False,
        summary_text=row.summary_text,
    )
