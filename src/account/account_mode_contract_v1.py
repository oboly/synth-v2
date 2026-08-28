"""Canonical ``trading_account.account_mode`` / ``live_trading_enabled``
semantics, shared by every consumer instead of each redefining its own copy.

Three supported ``account_mode`` values:

- ``paper``: simulated/non-live account context. Never execution-eligible.
  Requires ``live_trading_enabled=False``.
- ``live_readonly``: a real broker account used only as a read-only
  wallet/position snapshot source (e.g. ``READ_ONLY_PRIVATE`` credential
  bindings). Real broker data, but never execution-eligible under any
  circumstance. Requires ``live_trading_enabled=False``, same as ``paper``.
  Must never resolve to an executor LIVE runtime mode.
- ``live``: a real broker account that may become execution-eligible,
  subject separately to decision_gate permission, credential scope, LIVE
  authority, and kill-switch checks owned elsewhere. Requires
  ``live_trading_enabled=True``.

This module is pure (no DB, executor, broker, credential, or order imports)
and grants no permission, authority, or credential access on its own. It
only states the shared vocabulary and the shared, mechanical
account_mode/live_trading_enabled consistency check that every canonical
consumer (decision_gate gates, execution-handoff mode resolvers, the SELL
LIVE readiness controller) already independently enforced before this
module existed.
"""
from __future__ import annotations

from typing import Final

ACCOUNT_MODE_PAPER: Final[str] = "paper"
ACCOUNT_MODE_LIVE_READONLY: Final[str] = "live_readonly"
ACCOUNT_MODE_LIVE: Final[str] = "live"

SUPPORTED_ACCOUNT_MODES: Final[frozenset[str]] = frozenset(
    {ACCOUNT_MODE_PAPER, ACCOUNT_MODE_LIVE_READONLY, ACCOUNT_MODE_LIVE}
)

# The only account_mode that may ever become execution-eligible. Both
# ``paper`` (simulated) and ``live_readonly`` (real broker, read-only) are
# permanently excluded from execution eligibility.
EXECUTION_ELIGIBLE_ACCOUNT_MODES: Final[frozenset[str]] = frozenset({ACCOUNT_MODE_LIVE})

# The exact required live_trading_enabled value for each supported
# account_mode. Any account_mode not present here is unsupported.
_REQUIRED_LIVE_TRADING_ENABLED: Final[dict[str, bool]] = {
    ACCOUNT_MODE_PAPER: False,
    ACCOUNT_MODE_LIVE_READONLY: False,
    ACCOUNT_MODE_LIVE: True,
}


def is_execution_eligible_account_mode(account_mode: str) -> bool:
    """True only for the exact account_mode that may ever reach LIVE execution."""
    return account_mode in EXECUTION_ELIGIBLE_ACCOUNT_MODES


def is_account_mode_live_trading_enabled_consistent(account_mode: str, live_trading_enabled: bool) -> bool:
    """Canonical account_mode/live_trading_enabled agreement check.

    Returns ``False`` for any unsupported ``account_mode`` (fail closed) and
    for any supported ``account_mode`` whose required ``live_trading_enabled``
    value does not match. ``paper`` and ``live_readonly`` both require
    ``False``; ``live`` requires ``True``.
    """
    try:
        required = _REQUIRED_LIVE_TRADING_ENABLED[account_mode]
    except KeyError:
        return False
    return required == live_trading_enabled
