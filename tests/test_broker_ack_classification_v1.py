"""Tests for src/executor/broker_ack_classification_v1.py (Issue #206, P0-A)."""
from __future__ import annotations

import pytest

from src.executor.broker_ack_classification_v1 import (
    ACCEPTED_ACK_STATES,
    ACK_STATE_ACTIVE,
    ACK_STATE_AMBIGUOUS,
    ACK_STATE_CANCELED,
    ACK_STATE_FILLED,
    ACK_STATE_PARTIALLY_FILLED,
    ACK_STATE_REJECTED,
    BrokerAckClassificationError,
    CLOSED_ACK_STATES,
    is_accepted,
    is_closed,
    resolve_canonical_state,
)


BITVAVO_MAP = {
    "new": ACK_STATE_ACTIVE,
    "partiallyFilled": ACK_STATE_PARTIALLY_FILLED,
    "filled": ACK_STATE_FILLED,
    "canceled": ACK_STATE_CANCELED,
    "canceledPostOnly": ACK_STATE_CANCELED,
    "rejected": ACK_STATE_REJECTED,
}


class TestResolveCanonicalState:
    def test_known_status_maps_to_canonical_state(self) -> None:
        assert resolve_canonical_state(raw_status="new", venue_status_map=BITVAVO_MAP) == ACK_STATE_ACTIVE

    def test_post_only_immediate_cancellation_classifies_canceled_not_active(self) -> None:
        # Issue #206 P0-A: this is the named failure mode -- an immediate
        # post-only self-cross cancellation must never read as ACTIVE.
        result = resolve_canonical_state(raw_status="canceledPostOnly", venue_status_map=BITVAVO_MAP)
        assert result == ACK_STATE_CANCELED
        assert result not in ACCEPTED_ACK_STATES

    def test_missing_status_is_ambiguous(self) -> None:
        assert resolve_canonical_state(raw_status=None, venue_status_map=BITVAVO_MAP) == ACK_STATE_AMBIGUOUS

    def test_empty_status_is_ambiguous(self) -> None:
        assert resolve_canonical_state(raw_status="  ", venue_status_map=BITVAVO_MAP) == ACK_STATE_AMBIGUOUS

    def test_unrecognized_status_is_ambiguous_never_guessed_active(self) -> None:
        result = resolve_canonical_state(raw_status="someNewVenueStatus", venue_status_map=BITVAVO_MAP)
        assert result == ACK_STATE_AMBIGUOUS

    def test_malformed_venue_map_target_raises(self) -> None:
        with pytest.raises(BrokerAckClassificationError):
            resolve_canonical_state(raw_status="x", venue_status_map={"x": "NOT_A_CANONICAL_STATE"})


class TestStateSetMembership:
    def test_accepted_states_are_exactly_active_partial_filled(self) -> None:
        assert ACCEPTED_ACK_STATES == {ACK_STATE_ACTIVE, ACK_STATE_PARTIALLY_FILLED, ACK_STATE_FILLED}

    def test_closed_states_exclude_ambiguous_and_accepted(self) -> None:
        assert CLOSED_ACK_STATES.isdisjoint(ACCEPTED_ACK_STATES)
        assert ACK_STATE_AMBIGUOUS not in CLOSED_ACK_STATES
        assert ACK_STATE_AMBIGUOUS not in ACCEPTED_ACK_STATES

    def test_is_accepted_and_is_closed_helpers(self) -> None:
        assert is_accepted(ACK_STATE_FILLED) is True
        assert is_accepted(ACK_STATE_CANCELED) is False
        assert is_closed(ACK_STATE_REJECTED) is True
        assert is_closed(ACK_STATE_ACTIVE) is False
        assert is_accepted(ACK_STATE_AMBIGUOUS) is False
        assert is_closed(ACK_STATE_AMBIGUOUS) is False
