"""
manual_live_authorization_v1 — the smallest explicit manual-live
authorization contract for the manual SELL ladder submission orchestrator
(Issue #369).

Layer: executor-only, pure/no DB access, no broker calls.

Live trading permission is NOT_GRANTED by default (AGENTS.md). This module
is a narrow, additive authorization boundary at the manual-execution
submission call site — it does not replace, weaken, or bypass:

  - src.execution.bitvavo_client.BROKER_WRITE_PERMISSION_ENV (the existing
    global broker-write env gate on BitvavoClient.place_order/cancel_order),
  - the #206 executor handoff intake denial of LIVE_DISABLED/any unknown
    executor_mode (src.executor.manual_execution_handoff_v1).

Both remain required. This module adds one more, independently explicit
gate: the operator must set an env var whose value is the *exact* handoff_id
about to be submitted, immediately before invoking the LIVE submission. This
binds authorization to one specific plan/handoff identity (no blanket
"live mode on" switch), requires a fresh explicit action per handoff (no
persisted approval an old export could replay), and is never inferred from
executor_mode — a handoff's executor_mode is always DRY_RUN or PAPER (#206
never allows LIVE_DISABLED through intake), so there is no implicit
PAPER/DRY_RUN -> LIVE upgrade path here: LIVE is only a submission-time
adapter choice the operator makes explicitly via this gate, on top of an
already-claimed DRY_RUN/PAPER handoff.

Default: env var unset -> denied.

broker_private_calls=0
broker_writes=0
order_submission=0
"""
from __future__ import annotations

import os
from typing import Final, Mapping

MANUAL_LIVE_AUTHORIZATION_HANDOFF_ID_ENV: Final[str] = (
    "SYNTH_MANUAL_LIVE_EXECUTION_AUTHORIZATION_HANDOFF_ID"
)


class ManualLiveAuthorizationDeniedError(PermissionError):
    """Fail-closed: no explicit, handoff-scoped manual-live authorization is
    present."""


def require_manual_live_authorization(
    *, handoff_id: int, env: Mapping[str, str] | None = None
) -> None:
    """Raise ManualLiveAuthorizationDeniedError unless the operator has set
    MANUAL_LIVE_AUTHORIZATION_HANDOFF_ID_ENV to exactly str(handoff_id).
    Never grants authority for a different handoff_id, and never grants any
    authority merely because the variable is set to a non-empty value."""
    source = env if env is not None else os.environ
    granted_value = (source.get(MANUAL_LIVE_AUTHORIZATION_HANDOFF_ID_ENV) or "").strip()
    if granted_value != str(handoff_id):
        raise ManualLiveAuthorizationDeniedError(
            "MANUAL_LIVE_AUTHORIZATION_DENIED: "
            f"{MANUAL_LIVE_AUTHORIZATION_HANDOFF_ID_ENV} does not exactly match "
            f"handoff_id={handoff_id}"
        )
