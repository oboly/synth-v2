from __future__ import annotations

from decimal import Decimal

from src.decision_gate.models import (
    ACTIVE_SLEEVE_STATUSES,
    DecisionGateConfig,
    DecisionResult,
    DuplicateState,
    ELIGIBLE_SELECTION_STATES,
    SelectionInputRow,
    SleeveState,
)


def _build_result(
    row: SelectionInputRow,
    *,
    account_id: int,
    sleeve_code: str,
    decision_state: str,
    decision_reason: str,
    execution_intent: str,
    config: DecisionGateConfig,
    duplicate_state: DuplicateState,
    available_equity_eur=None,
) -> DecisionResult:
    return DecisionResult(
        account_id=account_id,
        sleeve_code=sleeve_code,
        selection_state_id=row.selection_state_id,
        asset_id=row.asset_id,
        symbol=row.symbol,
        venue=row.venue,
        asof_ts_utc=row.asof_ts_utc,
        selection_state=row.selection_state,
        decision_state=decision_state,
        decision_reason=decision_reason,
        execution_intent=execution_intent,
        min_available_equity_eur=config.min_available_equity_eur,
        available_equity_eur=available_equity_eur,
        has_active_plan=duplicate_state.has_active_plan,
        has_open_position=duplicate_state.has_open_position,
        summary_text=row.summary_text,
        regime_label_4h=row.regime_label_4h,
    )


def _passes_watchlist_preplan(row: SelectionInputRow) -> bool:
    score = row.effective_selection_score or Decimal("0")

    if score < Decimal("0.50"):
        return False

    if row.summary_text is None:
        return False

    # tijdelijke hack: sleeves uit summary_text
    if "SWING_STRUCTURAL" not in row.summary_text and \
       "TACTICAL_PULSE" not in row.summary_text and \
       "EXPERIMENTAL" not in row.summary_text:
        return False

    return True


def evaluate_selection_for_account(
    row: SelectionInputRow,
    account_id: int,
    sleeve_code: str,
    sleeve_state: SleeveState | None,
    duplicate_state: DuplicateState,
    config: DecisionGateConfig,
    has_open_order: bool = False,
) -> DecisionResult:

    # ========================================
    # 1. WATCHLIST PREPLAN (NEW PATH)
    # ========================================
    if row.selection_state == "WATCHLIST":
        if _passes_watchlist_preplan(row):
            return _build_result(
                row,
                account_id=account_id,
                sleeve_code=sleeve_code,
                decision_state="WATCHLIST_PREPLAN_ALLOWED",
                decision_reason="WATCHLIST_PREPLAN_OK",
                execution_intent="PREPARE_PLAN",
                config=config,
                duplicate_state=duplicate_state,
                available_equity_eur=None,
            )

        return _build_result(
            row,
            account_id=account_id,
            sleeve_code=sleeve_code,
            decision_state="NO_ACTION",
            decision_reason="WATCHLIST_NOT_STRONG_ENOUGH",
            execution_intent="NONE",
            config=config,
            duplicate_state=duplicate_state,
            available_equity_eur=None,
        )

    # ========================================
    # 2. NORMAL FLOW (UNCHANGED)
    # ========================================
    if row.selection_state not in ELIGIBLE_SELECTION_STATES:
        return _build_result(
            row,
            account_id=account_id,
            sleeve_code=sleeve_code,
            decision_state="NO_ACTION",
            decision_reason="SELECTION_NOT_ELIGIBLE",
            execution_intent="NONE",
            config=config,
            duplicate_state=duplicate_state,
            available_equity_eur=None,
        )

    if sleeve_state is None:
        return _build_result(
            row,
            account_id=account_id,
            sleeve_code=sleeve_code,
            decision_state="BLOCKED_SLEEVE",
            decision_reason="SLEEVE_NOT_FOUND",
            execution_intent="NONE",
            config=config,
            duplicate_state=duplicate_state,
            available_equity_eur=None,
        )

    if sleeve_state.sleeve_status not in ACTIVE_SLEEVE_STATUSES:
        return _build_result(
            row,
            account_id=account_id,
            sleeve_code=sleeve_code,
            decision_state="BLOCKED_SLEEVE",
            decision_reason="SLEEVE_NOT_ACTIVE",
            execution_intent="NONE",
            config=config,
            duplicate_state=duplicate_state,
            available_equity_eur=sleeve_state.available_equity_eur,
        )

    if has_open_order:
        return _build_result(
            row,
            account_id=account_id,
            sleeve_code=sleeve_code,
            decision_state="BLOCKED_OPEN_ORDER",
            decision_reason="OPEN_ORDER_EXISTS",
            execution_intent="NONE",
            config=config,
            duplicate_state=duplicate_state,
            available_equity_eur=sleeve_state.available_equity_eur,
        )

    if duplicate_state.has_active_plan:
        return _build_result(
            row,
            account_id=account_id,
            sleeve_code=sleeve_code,
            decision_state="BLOCKED_ACTIVE_PLAN",
            decision_reason="ACTIVE_PLAN_EXISTS",
            execution_intent="NONE",
            config=config,
            duplicate_state=duplicate_state,
            available_equity_eur=sleeve_state.available_equity_eur,
        )

    if duplicate_state.has_open_position:
        return _build_result(
            row,
            account_id=account_id,
            sleeve_code=sleeve_code,
            decision_state="BLOCKED_POSITION",
            decision_reason="POSITION_EXISTS",
            execution_intent="NONE",
            config=config,
            duplicate_state=duplicate_state,
            available_equity_eur=sleeve_state.available_equity_eur,
        )

    if sleeve_state.available_equity_eur < config.min_available_equity_eur:
        return _build_result(
            row,
            account_id=account_id,
            sleeve_code=sleeve_code,
            decision_state="BLOCKED_BALANCE",
            decision_reason="INSUFFICIENT_BALANCE",
            execution_intent="NONE",
            config=config,
            duplicate_state=duplicate_state,
            available_equity_eur=sleeve_state.available_equity_eur,
        )

    if row.selection_state == "PREPARE":
        return _build_result(
            row,
            account_id=account_id,
            sleeve_code=sleeve_code,
            decision_state="PREPARE_ALLOWED",
            decision_reason="OK",
            execution_intent="PREPARE_PLAN",
            config=config,
            duplicate_state=duplicate_state,
            available_equity_eur=sleeve_state.available_equity_eur,
        )

    if row.selection_state == "BUY_READY":
        return _build_result(
            row,
            account_id=account_id,
            sleeve_code=sleeve_code,
            decision_state="EXECUTION_ALLOWED",
            decision_reason="OK",
            execution_intent="PLACE_PASSIVE_LIMIT",
            config=config,
            duplicate_state=duplicate_state,
            available_equity_eur=sleeve_state.available_equity_eur,
        )

    return _build_result(
        row,
        account_id=account_id,
        sleeve_code=sleeve_code,
        decision_state="NO_ACTION",
        decision_reason="FALLBACK",
        execution_intent="NONE",
        config=config,
        duplicate_state=duplicate_state,
        available_equity_eur=sleeve_state.available_equity_eur,
    )
