from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from src.decision_gate.account_protection_contract_v1 import (
    AccountProtectionContractError,
    AccountProtectionEvaluationV1,
    STATE_BLOCKED as PROTECTION_STATE_BLOCKED,
    validate_account_protection_evaluation_binding_v1,
)

from src.decision_gate.models import (
    ACTIVE_SLEEVE_STATUSES,
    BUY_READY_SELECTION_STATE,
    DecisionGateConfig,
    DecisionResult,
    DIRECT_SELECTION_STATES,
    DuplicateState,
    ELIGIBLE_SELECTION_STATES,
    PASS_SETUP_FILTER_STATE,
    PREPARE_SELECTION_STATE,
    SelectionInputRow,
    SleeveState,
    WATCHLIST_SELECTION_STATE,
)


def _available_equity(sleeve_state: SleeveState | None):
    if sleeve_state is None:
        return None
    return sleeve_state.available_equity_eur


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
    sleeve_state: SleeveState | None,
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
        available_equity_eur=_available_equity(sleeve_state),
        has_active_plan=duplicate_state.has_active_plan,
        has_open_position=duplicate_state.has_open_position,
        allowed_sleeves=row.allowed_sleeves,
        setup_filter_state=row.setup_filter_state,
        setup_filter_reason=row.setup_filter_reason,
        target_horizon=row.target_horizon,
        summary_text=row.summary_text,
        regime_label_4h=row.regime_label_4h,
    )


def _allowed_sleeve_set(allowed_sleeves: str | None) -> set[str]:
    if allowed_sleeves is None:
        return set()

    return {
        item.strip().upper()
        for item in allowed_sleeves.split(",")
        if item.strip()
    }


def _is_sleeve_allowed(row: SelectionInputRow, sleeve_code: str) -> bool:
    allowed = _allowed_sleeve_set(row.allowed_sleeves)
    return sleeve_code.upper() in allowed


def _watchlist_setup_passes(row: SelectionInputRow) -> bool:
    return str(row.setup_filter_state or "").upper() == PASS_SETUP_FILTER_STATE


def _watchlist_block_reason(row: SelectionInputRow) -> str:
    reason = row.setup_filter_reason or "MISSING_SETUP_FILTER"
    return f"TRADE_SETUP_FILTER_{reason}"


def _evaluate_selection_for_account_base(
    row: SelectionInputRow,
    account_id: int,
    sleeve_code: str,
    sleeve_state: SleeveState | None,
    duplicate_state: DuplicateState,
    config: DecisionGateConfig,
    has_open_order: bool = False,
) -> DecisionResult:
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
            sleeve_state=sleeve_state,
        )

    if row.selection_state == WATCHLIST_SELECTION_STATE and not _watchlist_setup_passes(row):
        return _build_result(
            row,
            account_id=account_id,
            sleeve_code=sleeve_code,
            decision_state="NO_ACTION",
            decision_reason=_watchlist_block_reason(row),
            execution_intent="NONE",
            config=config,
            duplicate_state=duplicate_state,
            sleeve_state=sleeve_state,
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
            sleeve_state=sleeve_state,
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
            sleeve_state=sleeve_state,
        )

    if not _is_sleeve_allowed(row, sleeve_code):
        return _build_result(
            row,
            account_id=account_id,
            sleeve_code=sleeve_code,
            decision_state="BLOCKED_SLEEVE",
            decision_reason="SLEEVE_NOT_ALLOWED",
            execution_intent="NONE",
            config=config,
            duplicate_state=duplicate_state,
            sleeve_state=sleeve_state,
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
            sleeve_state=sleeve_state,
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
            sleeve_state=sleeve_state,
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
            sleeve_state=sleeve_state,
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
            sleeve_state=sleeve_state,
        )

    if row.selection_state == WATCHLIST_SELECTION_STATE:
        return _build_result(
            row,
            account_id=account_id,
            sleeve_code=sleeve_code,
            decision_state="WATCHLIST_PREPLAN_ALLOWED",
            decision_reason="WATCHLIST_SETUP_FILTER_PASS",
            execution_intent="PREPARE_PLAN",
            config=config,
            duplicate_state=duplicate_state,
            sleeve_state=sleeve_state,
        )

    if row.selection_state == PREPARE_SELECTION_STATE:
        return _build_result(
            row,
            account_id=account_id,
            sleeve_code=sleeve_code,
            decision_state="PREPARE_ALLOWED",
            decision_reason="OK",
            execution_intent="PREPARE_PLAN",
            config=config,
            duplicate_state=duplicate_state,
            sleeve_state=sleeve_state,
        )

    if row.selection_state == BUY_READY_SELECTION_STATE:
        return _build_result(
            row,
            account_id=account_id,
            sleeve_code=sleeve_code,
            decision_state="EXECUTION_ALLOWED",
            decision_reason="OK",
            execution_intent="PLACE_PASSIVE_LIMIT",
            config=config,
            duplicate_state=duplicate_state,
            sleeve_state=sleeve_state,
        )

    if row.selection_state in DIRECT_SELECTION_STATES:
        return _build_result(
            row,
            account_id=account_id,
            sleeve_code=sleeve_code,
            decision_state="NO_ACTION",
            decision_reason="UNHANDLED_DIRECT_SELECTION_STATE",
            execution_intent="NONE",
            config=config,
            duplicate_state=duplicate_state,
            sleeve_state=sleeve_state,
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
        sleeve_state=sleeve_state,
    )


def _compose_protection(
    result: DecisionResult,
    protection: AccountProtectionEvaluationV1 | None,
    protection_evaluation_ts_utc: datetime | None,
) -> DecisionResult:
    """Logical-AND composition: protection can only remove permission."""
    if protection is None:
        return result
    try:
        validate_account_protection_evaluation_binding_v1(
            protection,
            trading_account_id=result.account_id,
            requested_action="BUY",
            sleeve_code=result.sleeve_code,
            asset_id=result.asset_id,
            evaluation_ts_utc=protection_evaluation_ts_utc,
        )
    except AccountProtectionContractError:
        if result.execution_intent == "NONE":
            return result
        return replace(
            result,
            protection_decision_state="BLOCKED",
            protection_reason_code="INVALID_PROTECTION_EVALUATION_BINDING",
            decision_state="BLOCKED_PROTECTION",
            decision_reason="INVALID_PROTECTION_EVALUATION_BINDING",
            execution_intent="NONE",
        )
    enriched = replace(
        result,
        protection_decision_state=protection.decision_state,
        protection_reason_code=protection.reason_code,
        protection_code=protection.protection_code,
    )
    if protection.decision_state != PROTECTION_STATE_BLOCKED or result.execution_intent == "NONE":
        return enriched
    return replace(
        enriched,
        decision_state="BLOCKED_PROTECTION",
        decision_reason=protection.reason_code,
        execution_intent="NONE",
    )


def evaluate_selection_for_account(
    row: SelectionInputRow,
    account_id: int,
    sleeve_code: str,
    sleeve_state: SleeveState | None,
    duplicate_state: DuplicateState,
    config: DecisionGateConfig,
    has_open_order: bool = False,
    protection_evaluation: AccountProtectionEvaluationV1 | None = None,
    protection_evaluation_ts_utc: datetime | None = None,
) -> DecisionResult:
    """Evaluate BUY selection permission plus an optional P2 protection result.

    Callers that enable account protections must first use the action-aware P2
    evaluator with ``BUY`` and pass its result here. Legacy callers remain
    unchanged until they supply that explicit permission evidence.
    """
    base = _evaluate_selection_for_account_base(
        row=row,
        account_id=account_id,
        sleeve_code=sleeve_code,
        sleeve_state=sleeve_state,
        duplicate_state=duplicate_state,
        config=config,
        has_open_order=has_open_order,
    )
    return _compose_protection(base, protection_evaluation, protection_evaluation_ts_utc)
