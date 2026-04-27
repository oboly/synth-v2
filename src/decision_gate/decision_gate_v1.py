from __future__ import annotations

# Synth v2 — decision_gate engine
# Layer: decision_gate
# Responsibility: account-aware permission checks.
# Boundary: consumes selection/setup-filter state; does not recompute market logic.

from src.decision_gate.models import (
    ACCOUNT_GATED_SELECTION_STATES,
    ACTIVE_SLEEVE_STATUSES,
    DecisionGateConfig,
    DecisionResult,
    DuplicateState,
    STATE_ALLOWED_SLEEVES,
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
        setup_filter_state=row.setup_filter_state,
        setup_filter_reason=row.setup_filter_reason,
        setup_filter_target_horizon=row.setup_filter_target_horizon,
        setup_filter_context_ts_utc=row.setup_filter_context_ts_utc,
        setup_filter_name=row.setup_filter_name,
        setup_filter_version=row.setup_filter_version,
        asset_suitability_mode=row.asset_suitability_mode,
    )


def _is_sleeve_allowed_for_state(selection_state: str, sleeve_code: str) -> bool:
    allowed = STATE_ALLOWED_SLEEVES.get(selection_state, set())
    return sleeve_code in allowed


def _setup_filter_passed(row: SelectionInputRow) -> bool:
    return (row.setup_filter_state or "").upper() == "PASS"


def _setup_filter_block_reason(row: SelectionInputRow) -> str:
    if row.setup_filter_state is None:
        return "TRADE_SETUP_FILTER_MISSING"
    if row.setup_filter_reason:
        return f"TRADE_SETUP_FILTER_{row.setup_filter_reason}"
    return f"TRADE_SETUP_FILTER_{row.setup_filter_state}"


def _pass_account_checks(
    row: SelectionInputRow,
    *,
    account_id: int,
    sleeve_code: str,
    sleeve_state: SleeveState | None,
    duplicate_state: DuplicateState,
    config: DecisionGateConfig,
    has_open_order: bool,
) -> DecisionResult | None:
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

    if not _is_sleeve_allowed_for_state(row.selection_state, sleeve_code):
        return _build_result(
            row,
            account_id=account_id,
            sleeve_code=sleeve_code,
            decision_state="BLOCKED_SLEEVE",
            decision_reason="SLEEVE_NOT_ALLOWED_FOR_SELECTION_STATE",
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

    return None


def evaluate_selection_for_account(
    row: SelectionInputRow,
    account_id: int,
    sleeve_code: str,
    sleeve_state: SleeveState | None,
    duplicate_state: DuplicateState,
    config: DecisionGateConfig,
    has_open_order: bool = False,
) -> DecisionResult:
    if row.selection_state not in ACCOUNT_GATED_SELECTION_STATES:
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

    if row.selection_state == "WATCHLIST" and not _setup_filter_passed(row):
        return _build_result(
            row,
            account_id=account_id,
            sleeve_code=sleeve_code,
            decision_state="NO_ACTION",
            decision_reason=_setup_filter_block_reason(row),
            execution_intent="NONE",
            config=config,
            duplicate_state=duplicate_state,
            available_equity_eur=None if sleeve_state is None else sleeve_state.available_equity_eur,
        )

    blocked = _pass_account_checks(
        row,
        account_id=account_id,
        sleeve_code=sleeve_code,
        sleeve_state=sleeve_state,
        duplicate_state=duplicate_state,
        config=config,
        has_open_order=has_open_order,
    )
    if blocked is not None:
        return blocked

    assert sleeve_state is not None

    if row.selection_state == "WATCHLIST":
        return _build_result(
            row,
            account_id=account_id,
            sleeve_code=sleeve_code,
            decision_state="WATCHLIST_PREPLAN_ALLOWED",
            decision_reason="TRADE_SETUP_FILTER_PASS",
            execution_intent="PREPARE_PLAN",
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
