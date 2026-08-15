"""
broker_ack_classification_v1 -- the canonical, venue-neutral broker
acknowledgement/state vocabulary for the shared algorithmic BUY/SELL
executor boundary (Issue #206, P0-A).

Layer: executor-only, pure/no DB access, no broker calls.

Problem this closes: the pre-#206 manual submission orchestrator
(src.executor.manual_execution_submission_orchestrator_v1) treats *any*
non-exception return from OrderPlacementAdapter.place_order as accepted --
it unconditionally calls ``resolve_accepted(new_state=STATE_SUBMITTED, ...)``
regardless of the broker's own returned status string. A venue response
whose create-order status is already a terminal non-active outcome (for
example Bitvavo's ``canceledPostOnly`` on an immediate post-only cross, or
``rejected``/``expired``) would therefore be persisted as a successful
active submission. That defect is not touched here (the manual lane is
being retired as the target workflow -- see AGENTS.md/#206 -- and its own
tests pin the existing behavior), but the new shared orchestrator
(src.executor.execution_submission_orchestrator_v1) MUST NOT repeat it: it
classifies every broker acknowledgement through this module before ever
treating a leg as accepted.

Canonical states (venue-agnostic; only these seven may ever be assigned by
a classifier):

    ACTIVE            -- broker confirmed the order exists and is live/open.
    PARTIALLY_FILLED   -- broker confirmed the order exists and has partial fills.
    FILLED             -- broker confirmed the order is completely filled.
    CANCELED           -- broker confirmed the order was canceled (including
                            an immediate post-only self-cross cancellation --
                            this must never be reported as ACTIVE).
    EXPIRED            -- broker confirmed the order expired (e.g. IOC/FOK/GTD).
    REJECTED           -- broker confirmed the order was never created.
    AMBIGUOUS          -- the broker's status vocabulary was missing, empty,
                            or not recognized. Fail closed: a classifier must
                            return AMBIGUOUS rather than guess, and callers
                            must never treat AMBIGUOUS as ACTIVE.

Venue-specific status vocabulary (Bitvavo's ``new``/``canceledPostOnly``/
etc.) belongs only in the venue adapter that calls
``classify_generic_broker_ack`` or defines its own venue status map passed
through ``resolve_canonical_state`` -- never here.

broker_private_calls=0
broker_writes=0
order_submission=0
"""
from __future__ import annotations

from typing import Final, Mapping


ACK_STATE_ACTIVE: Final[str] = "ACTIVE"
ACK_STATE_PARTIALLY_FILLED: Final[str] = "PARTIALLY_FILLED"
ACK_STATE_FILLED: Final[str] = "FILLED"
ACK_STATE_CANCELED: Final[str] = "CANCELED"
ACK_STATE_EXPIRED: Final[str] = "EXPIRED"
ACK_STATE_REJECTED: Final[str] = "REJECTED"
ACK_STATE_AMBIGUOUS: Final[str] = "AMBIGUOUS"

ALL_ACK_STATES: Final[frozenset[str]] = frozenset(
    {
        ACK_STATE_ACTIVE,
        ACK_STATE_PARTIALLY_FILLED,
        ACK_STATE_FILLED,
        ACK_STATE_CANCELED,
        ACK_STATE_EXPIRED,
        ACK_STATE_REJECTED,
        ACK_STATE_AMBIGUOUS,
    }
)

# A broker acknowledgement in one of these canonical states means the
# order genuinely exists at the broker right now (or was fully executed).
# Only these may ever be persisted as an executor_execution_leg ACCEPTED
# outcome; everything else stops the ladder or requires reconciliation.
ACCEPTED_ACK_STATES: Final[frozenset[str]] = frozenset(
    {ACK_STATE_ACTIVE, ACK_STATE_PARTIALLY_FILLED, ACK_STATE_FILLED}
)

# A broker acknowledgement in one of these canonical states is a
# definitive, non-active, non-retryable outcome: the broker gave a real
# answer and that answer was not success. Never persisted as ACCEPTED.
CLOSED_ACK_STATES: Final[frozenset[str]] = frozenset(
    {ACK_STATE_CANCELED, ACK_STATE_EXPIRED, ACK_STATE_REJECTED}
)


class BrokerAckClassificationError(ValueError):
    """A venue status map or resolution input violated this module's
    fail-closed contract (e.g. mapped to a value outside ALL_ACK_STATES)."""


def resolve_canonical_state(
    *,
    raw_status: str | None,
    venue_status_map: Mapping[str, str],
) -> str:
    """Classify one raw venue status string into a canonical ack state.

    Fails closed to ACK_STATE_AMBIGUOUS -- never guesses -- when raw_status
    is missing/empty or not present in venue_status_map. Raises
    BrokerAckClassificationError if the venue map itself is malformed (maps
    to something outside ALL_ACK_STATES); that is a venue-adapter bug, not
    an ambiguous broker response, and must not be silently swallowed.
    """
    if not raw_status or not raw_status.strip():
        return ACK_STATE_AMBIGUOUS
    normalized = raw_status.strip()
    canonical = venue_status_map.get(normalized)
    if canonical is None:
        return ACK_STATE_AMBIGUOUS
    if canonical not in ALL_ACK_STATES:
        raise BrokerAckClassificationError(
            f"VENUE_STATUS_MAP_INVALID_TARGET: raw_status={normalized!r} "
            f"mapped to unrecognized canonical state {canonical!r}"
        )
    return canonical


def is_accepted(ack_state: str) -> bool:
    return ack_state in ACCEPTED_ACK_STATES


def is_closed(ack_state: str) -> bool:
    return ack_state in CLOSED_ACK_STATES
