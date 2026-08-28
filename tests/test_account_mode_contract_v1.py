"""Issue #551: focused tests for the canonical trading_account.account_mode
contract shared by decision_gate, execution-handoff mode resolvers, and the
SELL LIVE readiness controller.
"""
from __future__ import annotations

from src.account.account_mode_contract_v1 import (
    ACCOUNT_MODE_LIVE,
    ACCOUNT_MODE_LIVE_READONLY,
    ACCOUNT_MODE_PAPER,
    EXECUTION_ELIGIBLE_ACCOUNT_MODES,
    SUPPORTED_ACCOUNT_MODES,
    is_account_mode_live_trading_enabled_consistent,
    is_execution_eligible_account_mode,
)


def test_supported_account_modes_are_exactly_three() -> None:
    assert SUPPORTED_ACCOUNT_MODES == {"paper", "live_readonly", "live"}
    assert ACCOUNT_MODE_PAPER == "paper"
    assert ACCOUNT_MODE_LIVE_READONLY == "live_readonly"
    assert ACCOUNT_MODE_LIVE == "live"


def test_only_live_is_execution_eligible() -> None:
    assert EXECUTION_ELIGIBLE_ACCOUNT_MODES == {ACCOUNT_MODE_LIVE}
    assert is_execution_eligible_account_mode(ACCOUNT_MODE_LIVE) is True
    assert is_execution_eligible_account_mode(ACCOUNT_MODE_PAPER) is False
    assert is_execution_eligible_account_mode(ACCOUNT_MODE_LIVE_READONLY) is False
    assert is_execution_eligible_account_mode("unsupported") is False


def test_paper_requires_live_trading_enabled_false() -> None:
    assert is_account_mode_live_trading_enabled_consistent(ACCOUNT_MODE_PAPER, False) is True
    assert is_account_mode_live_trading_enabled_consistent(ACCOUNT_MODE_PAPER, True) is False


def test_live_readonly_requires_live_trading_enabled_false() -> None:
    assert is_account_mode_live_trading_enabled_consistent(ACCOUNT_MODE_LIVE_READONLY, False) is True
    assert is_account_mode_live_trading_enabled_consistent(ACCOUNT_MODE_LIVE_READONLY, True) is False


def test_live_requires_live_trading_enabled_true() -> None:
    assert is_account_mode_live_trading_enabled_consistent(ACCOUNT_MODE_LIVE, True) is True
    assert is_account_mode_live_trading_enabled_consistent(ACCOUNT_MODE_LIVE, False) is False


def test_unsupported_account_mode_is_never_consistent() -> None:
    for live_trading_enabled in (True, False):
        assert is_account_mode_live_trading_enabled_consistent("sandbox", live_trading_enabled) is False
        assert is_account_mode_live_trading_enabled_consistent("", live_trading_enabled) is False
