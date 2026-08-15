from src.executor.broker_ack_classification_v1 import (
    ACCEPTED_ACK_STATES,
    CLOSED_ACK_STATES,
    BrokerAckStateV1,
)


def test_neutral_ack_classes_are_complete_and_disjoint() -> None:
    assert ACCEPTED_ACK_STATES == {
        BrokerAckStateV1.ACTIVE,
        BrokerAckStateV1.PARTIALLY_FILLED,
        BrokerAckStateV1.FILLED,
    }
    assert CLOSED_ACK_STATES == {
        BrokerAckStateV1.CANCELED,
        BrokerAckStateV1.EXPIRED,
        BrokerAckStateV1.REJECTED,
    }
    assert ACCEPTED_ACK_STATES.isdisjoint(CLOSED_ACK_STATES)
    assert BrokerAckStateV1.AMBIGUOUS not in ACCEPTED_ACK_STATES | CLOSED_ACK_STATES


def test_vocabulary_is_venue_neutral_and_exact() -> None:
    assert {state.value for state in BrokerAckStateV1} == {
        "ACTIVE",
        "PARTIALLY_FILLED",
        "FILLED",
        "CANCELED",
        "EXPIRED",
        "REJECTED",
        "AMBIGUOUS",
    }
