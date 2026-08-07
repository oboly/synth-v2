"""
operator_intent.contracts_v1 — canonical operator-intent identity, enums, and records.

Phase 1 of Issue #254 (Operator Intent). Scope per Issue #262:

  operator-intent command/service layer
  -> canonical persistence + append-only revision/audit history
  -> authorized read model

Operator intent expresses preference, never permission. Nothing here grants
trading permission, creates a ladder preview, creates execution intent, or
touches broker/order state.

Canonical identity is reused, not reinvented:
  - operator identity: AuthenticatedProfileIdentity (app_user_id, app_profile_id),
    same type used by src.account_provisioning.account_provisioning_service_v1.
  - trading account identity: trading_account_id (BIGINT, MariaDB) /
    app_profile_trading_account_link for authorization.
  - venue: validated string code, src.account_provisioning.contracts_v1.SUPPORTED_VENUES.
  - canonical market: composite SYMBOL-QUOTE string, validated structurally here.

Safety:
  broker_private_calls=0
  broker_writes=0
  order_submission=0
  decision_gate=none
  execution_planner=none
  executor=none
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from src.account_provisioning.contracts_v1 import SUPPORTED_VENUES

# Re-exported so callers of this package use one canonical operator-identity type
# rather than a parallel one. Defined in account_provisioning because it is
# server-derived from a validated web session, not something this package owns.
from src.account_provisioning.account_provisioning_service_v1 import AuthenticatedProfileIdentity

__all__ = [
    "AuthenticatedProfileIdentity",
    "IntentType",
    "IntentStatus",
    "OPEN_STATUSES",
    "TERMINAL_STATUSES",
    "OperatorIntentError",
    "UnauthorizedOperatorIntentAccess",
    "UnresolvedCanonicalIdentity",
    "DuplicateActiveIntent",
    "OptimisticConcurrencyConflict",
    "InvalidLifecycleTransition",
    "OperatorIntentRecord",
    "OperatorIntentRevisionRecord",
    "validate_canonical_market",
    "validate_venue",
]


class IntentType(str, Enum):
    BUY_PRIORITY = "BUY_PRIORITY"
    REENTRY_WATCH = "REENTRY_WATCH"
    BUY_LADDER_REQUESTED = "BUY_LADDER_REQUESTED"
    SELL_LADDER_REQUESTED = "SELL_LADDER_REQUESTED"
    HOLD_ONLY = "HOLD_ONLY"
    DO_NOT_ADD = "DO_NOT_ADD"
    MANUAL_REVIEW_PRIORITY = "MANUAL_REVIEW_PRIORITY"


class IntentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WAITING_FOR_MARKET_CONTEXT = "WAITING_FOR_MARKET_CONTEXT"
    WAITING_FOR_PERMISSION = "WAITING_FOR_PERMISSION"
    READY_FOR_PLANNING = "READY_FOR_PLANNING"
    PLANNED_PREVIEW_AVAILABLE = "PLANNED_PREVIEW_AVAILABLE"
    BLOCKED = "BLOCKED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


# Statuses that count as "the current open intent" for one-active-per-scope
# enforcement. Later phases (decision_gate / execution_planner) own moving an
# intent between these open states; Phase 1 only persists them.
OPEN_STATUSES: frozenset[IntentStatus] = frozenset(
    {
        IntentStatus.ACTIVE,
        IntentStatus.WAITING_FOR_MARKET_CONTEXT,
        IntentStatus.WAITING_FOR_PERMISSION,
        IntentStatus.READY_FOR_PLANNING,
        IntentStatus.PLANNED_PREVIEW_AVAILABLE,
        IntentStatus.BLOCKED,
    }
)

TERMINAL_STATUSES: frozenset[IntentStatus] = frozenset(
    {IntentStatus.EXPIRED, IntentStatus.CANCELLED, IntentStatus.SUPERSEDED}
)

_CANONICAL_MARKET_RE = re.compile(r"^[A-Z0-9]{1,20}-[A-Z0-9]{2,10}$")


class OperatorIntentError(Exception):
    """Base class for operator-intent command/read failures. Fail closed."""


class UnauthorizedOperatorIntentAccess(OperatorIntentError):
    """Identity is not authorized for the requested account/venue scope."""


class UnresolvedCanonicalIdentity(OperatorIntentError):
    """Account, venue, or market identity could not be resolved/validated."""


class DuplicateActiveIntent(OperatorIntentError):
    """An open intent already exists for this (account, venue, market, type) scope."""


class OptimisticConcurrencyConflict(OperatorIntentError):
    """expected_version did not match the current stored version."""


class InvalidLifecycleTransition(OperatorIntentError):
    """Requested mutation is not valid for the intent's current lifecycle state."""


def validate_venue(venue: str) -> str:
    normalized = (venue or "").strip().lower()
    if normalized not in SUPPORTED_VENUES:
        raise UnresolvedCanonicalIdentity(f"UNSUPPORTED_VENUE: {venue!r}")
    return normalized


def validate_canonical_market(canonical_market: str) -> str:
    """Structural validation only (SYMBOL-QUOTE shape). No decision semantics."""
    normalized = (canonical_market or "").strip().upper()
    if not _CANONICAL_MARKET_RE.match(normalized):
        raise UnresolvedCanonicalIdentity(f"INVALID_CANONICAL_MARKET: {canonical_market!r}")
    return normalized


@dataclass(frozen=True)
class OperatorIntentRecord:
    operator_intent_id: int
    trading_account_id: int
    venue: str
    canonical_market: str
    intent_type: str
    priority: int
    status: str
    reason: str | None
    source: str
    created_by_app_user_id: int
    created_by_app_profile_id: int
    created_ts_utc: datetime
    updated_by_app_user_id: int
    updated_by_app_profile_id: int
    updated_ts_utc: datetime
    expires_ts_utc: datetime | None
    version: int
    supersedes_intent_id: int | None
    superseded_by_intent_id: int | None


@dataclass(frozen=True)
class OperatorIntentRevisionRecord:
    operator_intent_revision_id: int
    operator_intent_id: int
    revision_version: int
    event_type: str
    trading_account_id: int
    venue: str
    canonical_market: str
    intent_type: str
    priority: int
    status: str
    reason: str | None
    source: str
    actor_app_user_id: int
    actor_app_profile_id: int
    event_ts_utc: datetime
    expires_ts_utc: datetime | None
