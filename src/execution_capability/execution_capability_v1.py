"""Generic instrument execution capability contract (Issue #638).

Analysis eligibility and execution eligibility are deliberately separate.
An instrument may participate in holdings, valuation, signals, risk and exit
reasoning without being reachable by an automated executor.

This module is pure: no DB, broker, planner or executor imports.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

EXECUTION_MODE_AUTOMATED: Final[str] = "AUTOMATED"
EXECUTION_MODE_MANUAL_RFQ: Final[str] = "MANUAL_RFQ"
EXECUTION_MODE_MANUAL: Final[str] = "MANUAL"
EXECUTION_MODE_NONE: Final[str] = "NONE"

EXECUTION_MODES: Final[frozenset[str]] = frozenset(
    {
        EXECUTION_MODE_AUTOMATED,
        EXECUTION_MODE_MANUAL_RFQ,
        EXECUTION_MODE_MANUAL,
        EXECUTION_MODE_NONE,
    }
)

DISPOSITION_AUTOMATED_ELIGIBLE: Final[str] = "AUTOMATED_ELIGIBLE"
DISPOSITION_MANUAL_ACTION_REQUIRED: Final[str] = "MANUAL_ACTION_REQUIRED"
DISPOSITION_NOT_EXECUTABLE: Final[str] = "NOT_EXECUTABLE"


class ExecutionCapabilityError(ValueError):
    pass


@dataclass(frozen=True)
class ExecutionCapabilityV1:
    execution_mode: str
    manual_trade: bool
    automated_execution_eligible: bool
    execution_disposition: str


def normalize_execution_mode(value: object) -> str:
    mode = str(value or "").strip().upper()
    if mode not in EXECUTION_MODES:
        raise ExecutionCapabilityError(f"UNSUPPORTED_EXECUTION_MODE:{mode or 'EMPTY'}")
    return mode


def capability_for_mode(execution_mode: object) -> ExecutionCapabilityV1:
    mode = normalize_execution_mode(execution_mode)
    if mode == EXECUTION_MODE_AUTOMATED:
        return ExecutionCapabilityV1(
            execution_mode=mode,
            manual_trade=False,
            automated_execution_eligible=True,
            execution_disposition=DISPOSITION_AUTOMATED_ELIGIBLE,
        )
    if mode in {EXECUTION_MODE_MANUAL_RFQ, EXECUTION_MODE_MANUAL}:
        return ExecutionCapabilityV1(
            execution_mode=mode,
            manual_trade=True,
            automated_execution_eligible=False,
            execution_disposition=DISPOSITION_MANUAL_ACTION_REQUIRED,
        )
    return ExecutionCapabilityV1(
        execution_mode=mode,
        manual_trade=False,
        automated_execution_eligible=False,
        execution_disposition=DISPOSITION_NOT_EXECUTABLE,
    )
