from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from src.execution_capability.execution_capability_v1 import (
    DISPOSITION_AUTOMATED_ELIGIBLE,
    DISPOSITION_MANUAL_ACTION_REQUIRED,
    DISPOSITION_NOT_EXECUTABLE,
    EXECUTION_MODE_AUTOMATED,
    EXECUTION_MODE_MANUAL,
    EXECUTION_MODE_MANUAL_RFQ,
    EXECUTION_MODE_NONE,
    ExecutionCapabilityError,
    capability_for_mode,
)
from src.execution_capability.manual_action_router_v1 import (
    route_action_by_execution_capability_v1,
)


def test_automated_mode_preserves_current_behavior() -> None:
    capability = capability_for_mode(EXECUTION_MODE_AUTOMATED)
    assert capability.manual_trade is False
    assert capability.automated_execution_eligible is True
    assert capability.execution_disposition == DISPOSITION_AUTOMATED_ELIGIBLE


@pytest.mark.parametrize("mode", [EXECUTION_MODE_MANUAL_RFQ, EXECUTION_MODE_MANUAL])
def test_manual_modes_require_manual_action_and_never_automated_execution(mode: str) -> None:
    capability = capability_for_mode(mode)
    assert capability.manual_trade is True
    assert capability.automated_execution_eligible is False
    assert capability.execution_disposition == DISPOSITION_MANUAL_ACTION_REQUIRED


def test_none_mode_is_monitor_only() -> None:
    capability = capability_for_mode(EXECUTION_MODE_NONE)
    assert capability.manual_trade is False
    assert capability.automated_execution_eligible is False
    assert capability.execution_disposition == DISPOSITION_NOT_EXECUTABLE


def test_unknown_execution_mode_fails_closed() -> None:
    with pytest.raises(ExecutionCapabilityError, match="UNSUPPORTED_EXECUTION_MODE"):
        capability_for_mode("TELEPATHIC_BROKER")


def test_mdt_rfq_sell_becomes_manual_action_required() -> None:
    routed = route_action_by_execution_capability_v1(
        action="SELL",
        execution_mode=EXECUTION_MODE_MANUAL_RFQ,
        instrument="MDT",
        quantity=Decimal("123.45"),
        reason="EXIT_POLICY_TARGET_REACHED",
    )
    assert routed.action == "SELL"
    assert routed.execution_disposition == DISPOSITION_MANUAL_ACTION_REQUIRED
    assert routed.manual_trade is True
    assert routed.automated_order_submission is False
    assert routed.execution_mode == EXECUTION_MODE_MANUAL_RFQ


def test_non_crypto_manual_instrument_uses_identical_generic_contract() -> None:
    # A hypothetical broker-assisted bond proves the contract is not crypto/RFQ-specific.
    routed = route_action_by_execution_capability_v1(
        action="BUY",
        execution_mode=EXECUTION_MODE_MANUAL,
        instrument="NL-GOV-BOND-2035",
        notional_eur=Decimal("1000"),
        reason="PORTFOLIO_ALLOCATION",
    )
    assert routed.instrument == "NL-GOV-BOND-2035"
    assert routed.execution_disposition == DISPOSITION_MANUAL_ACTION_REQUIRED
    assert routed.manual_trade is True
    assert routed.automated_order_submission is False


def test_capability_modules_do_not_import_executor_or_broker() -> None:
    for path in (
        Path("src/execution_capability/execution_capability_v1.py"),
        Path("src/execution_capability/manual_action_router_v1.py"),
    ):
        src = path.read_text()
        assert "src.executor" not in src
        assert "BitvavoClient" not in src
        assert "submit_order" not in src
