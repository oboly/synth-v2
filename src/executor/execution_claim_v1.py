"""Executor-owned claim-control signals, distinct from broker failures."""
from __future__ import annotations


class ExecutionClaimLostError(RuntimeError):
    """A persisted handoff lease was lost before a broker operation."""

    reason_code = "EXECUTION_HANDOFF_CLAIM_LOST"
