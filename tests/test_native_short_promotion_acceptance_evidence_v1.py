from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.market_data.native_short_promotion_acceptance_evidence_v1 import (
    ACCEPTED_RESULT_CODES,
    CANONICAL_SCOPE_EXPECTED,
    REASON_AMBIGUOUS_EVIDENCE,
    REASON_DIGEST_MISSING_OR_INVALID,
    REASON_EVIDENCE_ABSENT,
    REASON_EVIDENCE_ACCEPTED,
    REASON_NOT_TERMINAL_SUCCESS,
    REASON_NO_ACCEPTANCE_PINNED,
    REASON_WRONG_OPERATION_TYPE,
    REASON_WRONG_SCHEMA_VERSION,
    REASON_WRONG_SCOPE,
    REQUIRED_ADMINISTRATION_SCHEMA_VERSION,
    evaluate_promotion_acceptance_evidence,
)


ACCEPTED_UUID = "11111111-1111-1111-1111-111111111111"
VALID_DIGEST = "a" * 64


def valid_row(**overrides: object) -> dict:
    row = {
        "operation_uuid": ACCEPTED_UUID,
        "operation_type": "PROMOTE_SCOPE",
        "venue": CANONICAL_SCOPE_EXPECTED["venue"],
        "symbol": "SOL",
        "quote_currency": CANONICAL_SCOPE_EXPECTED["quote_currency"],
        "fib_trading_horizon": CANONICAL_SCOPE_EXPECTED["fib_trading_horizon"],
        "primary_interval": CANONICAL_SCOPE_EXPECTED["primary_interval"],
        "supporting_interval": CANONICAL_SCOPE_EXPECTED["supporting_interval"],
        "schema_version": REQUIRED_ADMINISTRATION_SCHEMA_VERSION,
        "metadata_digest": VALID_DIGEST,
        "completed_at_utc": datetime(2026, 7, 30, 12, 0, tzinfo=UTC),
        "result_class": "SUCCESS",
        "result_code": "PROMOTED_NEW_SCOPE",
    }
    row.update(overrides)
    return row


def test_no_pinned_operation_uuid_fails_closed() -> None:
    result = evaluate_promotion_acceptance_evidence(
        [valid_row()], accepted_operation_uuid=None
    )
    assert result.accepted is False
    assert result.reason == REASON_NO_ACCEPTANCE_PINNED


def test_missing_evidence_fails_closed() -> None:
    result = evaluate_promotion_acceptance_evidence(
        [], accepted_operation_uuid=ACCEPTED_UUID
    )
    assert result.accepted is False
    assert result.reason == REASON_EVIDENCE_ABSENT


def test_ambiguous_duplicate_evidence_fails_closed() -> None:
    result = evaluate_promotion_acceptance_evidence(
        [valid_row(), valid_row()], accepted_operation_uuid=ACCEPTED_UUID
    )
    assert result.accepted is False
    assert result.reason == REASON_AMBIGUOUS_EVIDENCE


def test_unrelated_operation_uuid_is_not_evidence() -> None:
    other = valid_row(operation_uuid="22222222-2222-2222-2222-222222222222")
    result = evaluate_promotion_acceptance_evidence(
        [other], accepted_operation_uuid=ACCEPTED_UUID
    )
    assert result.accepted is False
    assert result.reason == REASON_EVIDENCE_ABSENT


def test_wrong_operation_type_fails_closed() -> None:
    row = valid_row(operation_type="REMOVE_SCOPE")
    result = evaluate_promotion_acceptance_evidence(
        [row], accepted_operation_uuid=ACCEPTED_UUID
    )
    assert result.accepted is False
    assert result.reason == REASON_WRONG_OPERATION_TYPE


def test_incomplete_non_terminal_operation_fails_closed() -> None:
    row = valid_row(completed_at_utc=None, result_class=None, result_code=None)
    result = evaluate_promotion_acceptance_evidence(
        [row], accepted_operation_uuid=ACCEPTED_UUID
    )
    assert result.accepted is False
    assert result.reason == REASON_NOT_TERMINAL_SUCCESS


@pytest.mark.parametrize(
    "result_class,result_code",
    [
        ("CONFLICT", "SCOPE_ALREADY_SUPPORTED"),
        ("SUCCESS", "ADOPTED_LEGACY_SCOPE"),
        ("RETRYABLE", "LOCK_TIMEOUT"),
    ],
)
def test_non_accepted_result_fails_closed(result_class: str, result_code: str) -> None:
    row = valid_row(result_class=result_class, result_code=result_code)
    result = evaluate_promotion_acceptance_evidence(
        [row], accepted_operation_uuid=ACCEPTED_UUID
    )
    assert result.accepted is False
    assert result.reason == REASON_NOT_TERMINAL_SUCCESS


def test_wrong_scope_fails_closed() -> None:
    row = valid_row(symbol="BTC", venue="kraken")
    result = evaluate_promotion_acceptance_evidence(
        [row], accepted_operation_uuid=ACCEPTED_UUID
    )
    assert result.accepted is False
    assert result.reason == REASON_WRONG_SCOPE


def test_missing_symbol_fails_closed() -> None:
    row = valid_row(symbol=None)
    result = evaluate_promotion_acceptance_evidence(
        [row], accepted_operation_uuid=ACCEPTED_UUID
    )
    assert result.accepted is False
    assert result.reason == REASON_WRONG_SCOPE


def test_wrong_schema_version_fails_closed() -> None:
    row = valid_row(schema_version="stale_schema_v0")
    result = evaluate_promotion_acceptance_evidence(
        [row], accepted_operation_uuid=ACCEPTED_UUID
    )
    assert result.accepted is False
    assert result.reason == REASON_WRONG_SCHEMA_VERSION


@pytest.mark.parametrize(
    "digest",
    [None, "", "not-hex", "a" * 63, "A" * 64, 12345],
)
def test_malformed_digest_fails_closed(digest: object) -> None:
    row = valid_row(metadata_digest=digest)
    result = evaluate_promotion_acceptance_evidence(
        [row], accepted_operation_uuid=ACCEPTED_UUID
    )
    assert result.accepted is False
    assert result.reason == REASON_DIGEST_MISSING_OR_INVALID


def test_valid_synthetic_evidence_accepts() -> None:
    result = evaluate_promotion_acceptance_evidence(
        [valid_row()], accepted_operation_uuid=ACCEPTED_UUID
    )
    assert result.accepted is True
    assert result.reason == REASON_EVIDENCE_ACCEPTED
    assert result.operation_uuid == ACCEPTED_UUID
    assert result.scope_symbol == "SOL"


def test_valid_evidence_among_unrelated_rows_still_accepts() -> None:
    unrelated = valid_row(
        operation_uuid="33333333-3333-3333-3333-333333333333", symbol="ETH"
    )
    rows = [unrelated, valid_row()]
    result = evaluate_promotion_acceptance_evidence(
        rows, accepted_operation_uuid=ACCEPTED_UUID
    )
    assert result.accepted is True


def test_accepted_result_codes_constant_matches_evaluated_set() -> None:
    for code in ACCEPTED_RESULT_CODES:
        row = valid_row(result_code=code)
        result = evaluate_promotion_acceptance_evidence(
            [row], accepted_operation_uuid=ACCEPTED_UUID
        )
        assert result.accepted is True
