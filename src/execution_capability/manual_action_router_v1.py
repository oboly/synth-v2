"""Pure routing from analytical action to execution disposition.

Manual-trade instruments preserve the analytical BUY/SELL/REDUCE/EXIT result
but can never produce an automated executor handoff from this contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from src.execution_capability.execution_capability_v1 import (
    DISPOSITION_AUTOMATED_ELIGIBLE,
    DISPOSITION_MANUAL_ACTION_REQUIRED,
    DISPOSITION_NOT_EXECUTABLE,
    capability_for_mode,
)


class ManualActionRouterError(ValueError):
    pass


@dataclass(frozen=True)
class RoutedActionV1:
    action: str
    execution_disposition: str
    execution_mode: str
    manual_trade: bool
    automated_order_submission: bool
    instrument: str
    quantity: Decimal | None = None
    notional_eur: Decimal | None = None
    reason: str | None = None
    target: Decimal | None = None
    invalidation: Decimal | None = None


def route_action_by_execution_capability_v1(
    *,
    action: str,
    execution_mode: object,
    instrument: str,
    quantity: Decimal | None = None,
    notional_eur: Decimal | None = None,
    reason: str | None = None,
    target: Decimal | None = None,
    invalidation: Decimal | None = None,
) -> RoutedActionV1:
    normalized_action = str(action or "").strip().upper()
    if not normalized_action:
        raise ManualActionRouterError("ACTION_EMPTY")
    normalized_instrument = str(instrument or "").strip().upper()
    if not normalized_instrument:
        raise ManualActionRouterError("INSTRUMENT_EMPTY")

    capability = capability_for_mode(execution_mode)
    if capability.execution_disposition == DISPOSITION_AUTOMATED_ELIGIBLE:
        automated_order_submission = True
    elif capability.execution_disposition in {
        DISPOSITION_MANUAL_ACTION_REQUIRED,
        DISPOSITION_NOT_EXECUTABLE,
    }:
        automated_order_submission = False
    else:  # pragma: no cover - defensive against future contract drift
        raise ManualActionRouterError("UNKNOWN_EXECUTION_DISPOSITION")

    return RoutedActionV1(
        action=normalized_action,
        execution_disposition=capability.execution_disposition,
        execution_mode=capability.execution_mode,
        manual_trade=capability.manual_trade,
        automated_order_submission=automated_order_submission,
        instrument=normalized_instrument,
        quantity=quantity,
        notional_eur=notional_eur,
        reason=reason,
        target=target,
        invalidation=invalidation,
    )
