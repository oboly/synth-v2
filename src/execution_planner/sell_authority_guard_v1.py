"""Shared fail-closed error for non-canonical SELL execution surfaces."""
from __future__ import annotations


class UnauthorizedManualExecutionCallError(PermissionError):
    """A generic planner/persistence/executor surface received manual SELL."""
