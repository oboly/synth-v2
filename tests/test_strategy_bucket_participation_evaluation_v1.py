from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.decision_gate.strategy_bucket_account_config_contract_v1 import StrategyBucketAccountConfigRowV1
from src.decision_gate.strategy_bucket_participation_evaluation_v1 import (
    DECISION_BLOCKED,
    DECISION_PERMITTED,
    REASON_ASSET_EXPOSURE_CEILING_EXCEEDED,
    REASON_BUCKET_AMOUNT_CEILING_EXCEEDED,
    REASON_BUCKET_DISABLED,
    REASON_CONFIGURATION_UNRESOLVED,
    REASON_NEW_ENTRIES_NOT_ALLOWED,
    REASON_OPEN_POSITIONS_CEILING_EXCEEDED,
    REASON_POSITION_AMOUNT_CEILING_EXCEEDED,
    REASON_REDUCE_REVIEWS_NOT_ALLOWED,
    REQUEST_KIND_NEW_ENTRY,
    REQUEST_KIND_REDUCE_REVIEW,
    StrategyBucketParticipationEvaluationError,
    StrategyBucketParticipationRequestV1,
    evaluate_strategy_bucket_participation_v1,
)


NOW = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)
ACCOUNT_A = 101
ACCOUNT_B = 202
BUCKET = "SHORT_TERM_ROTATION"


def _row(**changes: object) -> StrategyBucketAccountConfigRowV1:
    values: dict[str, object] = dict(
        strategy_bucket_account_config_id=1,
        trading_account_id=ACCOUNT_A,
        strategy_bucket_id=BUCKET,
        config_version="1",
        is_enabled=True,
        risk_profile="MODERATE",
        max_position_amount_eur=None,
        max_bucket_amount_eur=None,
        max_asset_exposure_pct=None,
        max_open_positions=None,
        allow_new_entries=True,
        allow_reduce_reviews=True,
        effective_from_ts_utc=NOW - timedelta(days=1),
        effective_until_ts_utc=None,
        source_provenance="manual_review",
    )
    values.update(changes)
    return StrategyBucketAccountConfigRowV1(**values)  # type: ignore[arg-type]


def _request(**changes: object) -> StrategyBucketParticipationRequestV1:
    values: dict[str, object] = dict(
        trading_account_id=ACCOUNT_A,
        strategy_bucket_id=BUCKET,
        request_kind=REQUEST_KIND_NEW_ENTRY,
        proposed_position_amount_eur=Decimal("100"),
        current_bucket_amount_eur=Decimal("0"),
        current_open_positions=0,
        current_asset_exposure_pct=Decimal("0"),
        evaluation_ts_utc=NOW,
    )
    values.update(changes)
    return StrategyBucketParticipationRequestV1(**values)  # type: ignore[arg-type]


def test_missing_configuration_blocks_and_fails_closed():
    decision = evaluate_strategy_bucket_participation_v1((), (), request=_request())
    assert decision.decision_state == DECISION_BLOCKED
    assert decision.reason_code == REASON_CONFIGURATION_UNRESOLVED


def test_disabled_bucket_blocks():
    decision = evaluate_strategy_bucket_participation_v1((_row(is_enabled=False),), (), request=_request())
    assert decision.decision_state == DECISION_BLOCKED
    assert decision.reason_code == REASON_BUCKET_DISABLED


def test_new_entry_blocked_when_not_allowed():
    decision = evaluate_strategy_bucket_participation_v1(
        (_row(allow_new_entries=False),), (), request=_request(request_kind=REQUEST_KIND_NEW_ENTRY),
    )
    assert decision.decision_state == DECISION_BLOCKED
    assert decision.reason_code == REASON_NEW_ENTRIES_NOT_ALLOWED


def test_reduce_review_blocked_when_not_allowed():
    decision = evaluate_strategy_bucket_participation_v1(
        (_row(allow_reduce_reviews=False),), (), request=_request(request_kind=REQUEST_KIND_REDUCE_REVIEW),
    )
    assert decision.decision_state == DECISION_BLOCKED
    assert decision.reason_code == REASON_REDUCE_REVIEWS_NOT_ALLOWED


def test_position_amount_ceiling_exceeded_blocks():
    decision = evaluate_strategy_bucket_participation_v1(
        (_row(max_position_amount_eur=Decimal("50")),), (),
        request=_request(proposed_position_amount_eur=Decimal("100")),
    )
    assert decision.decision_state == DECISION_BLOCKED
    assert decision.reason_code == REASON_POSITION_AMOUNT_CEILING_EXCEEDED


def test_bucket_amount_ceiling_exceeded_blocks():
    decision = evaluate_strategy_bucket_participation_v1(
        (_row(max_bucket_amount_eur=Decimal("150")),), (),
        request=_request(current_bucket_amount_eur=Decimal("100"), proposed_position_amount_eur=Decimal("100")),
    )
    assert decision.decision_state == DECISION_BLOCKED
    assert decision.reason_code == REASON_BUCKET_AMOUNT_CEILING_EXCEEDED


def test_asset_exposure_ceiling_exceeded_blocks():
    decision = evaluate_strategy_bucket_participation_v1(
        (_row(max_asset_exposure_pct=Decimal("20")),), (),
        request=_request(current_asset_exposure_pct=Decimal("25")),
    )
    assert decision.decision_state == DECISION_BLOCKED
    assert decision.reason_code == REASON_ASSET_EXPOSURE_CEILING_EXCEEDED


def test_open_positions_ceiling_exceeded_blocks_new_entry_only():
    decision = evaluate_strategy_bucket_participation_v1(
        (_row(max_open_positions=2),), (),
        request=_request(request_kind=REQUEST_KIND_NEW_ENTRY, current_open_positions=2),
    )
    assert decision.decision_state == DECISION_BLOCKED
    assert decision.reason_code == REASON_OPEN_POSITIONS_CEILING_EXCEEDED

    # A reduce-review is never blocked by the open-positions ceiling.
    decision = evaluate_strategy_bucket_participation_v1(
        (_row(max_open_positions=2, allow_reduce_reviews=True),), (),
        request=_request(request_kind=REQUEST_KIND_REDUCE_REVIEW, current_open_positions=5),
    )
    assert decision.decision_state == DECISION_PERMITTED


def test_within_all_ceilings_is_permitted():
    row = _row(
        max_position_amount_eur=Decimal("500"), max_bucket_amount_eur=Decimal("2000"),
        max_asset_exposure_pct=Decimal("30"), max_open_positions=5,
    )
    decision = evaluate_strategy_bucket_participation_v1(
        (row,), (),
        request=_request(
            proposed_position_amount_eur=Decimal("100"), current_bucket_amount_eur=Decimal("300"),
            current_open_positions=1, current_asset_exposure_pct=Decimal("10"),
        ),
    )
    assert decision.decision_state == DECISION_PERMITTED


def test_multi_account_isolation_two_distinct_accounts():
    """Account A enabled+permitted; Account B disabled+blocked, from the same
    row set -- proves #279's multi-account isolation at the evaluation seam."""
    rows = (
        _row(strategy_bucket_account_config_id=1, trading_account_id=ACCOUNT_A, is_enabled=True),
        _row(strategy_bucket_account_config_id=2, trading_account_id=ACCOUNT_B, is_enabled=False),
    )
    decision_a = evaluate_strategy_bucket_participation_v1(
        rows, (), request=_request(trading_account_id=ACCOUNT_A),
    )
    decision_b = evaluate_strategy_bucket_participation_v1(
        rows, (), request=_request(trading_account_id=ACCOUNT_B),
    )
    assert decision_a.decision_state == DECISION_PERMITTED
    assert decision_b.decision_state == DECISION_BLOCKED
    assert decision_b.reason_code == REASON_BUCKET_DISABLED


def test_invalid_request_raises_instead_of_silently_blocking():
    with pytest.raises(StrategyBucketParticipationEvaluationError):
        evaluate_strategy_bucket_participation_v1(
            (_row(),), (), request=_request(request_kind="UNKNOWN_KIND"),
        )
    with pytest.raises(StrategyBucketParticipationEvaluationError):
        evaluate_strategy_bucket_participation_v1(
            (_row(),), (), request=_request(proposed_position_amount_eur=Decimal("-1")),
        )
