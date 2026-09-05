"""Issue #752: percentage-of-equity allocation fields on #279's strategy
bucket account config -- validation, backward compatibility, and the
capacity module built on top of it.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.decision_gate.strategy_bucket_account_config_contract_v1 import (
    StrategyBucketAccountConfigError,
    StrategyBucketAccountConfigRowV1,
    resolve_strategy_bucket_account_config_v1,
)
from src.decision_gate.strategy_bucket_capacity_v1 import (
    StrategyBucketCapacityError,
    compute_strategy_bucket_capacity_v1,
    validate_aggregate_sleeve_allocation_policy_v1,
    validate_new_entry_within_capacity_v1,
)

NOW = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)
ACCOUNT_A = 101
BUCKET_A = "SHORT_TERM_ROTATION"
BUCKET_B = "LONG_TERM_MOONSHOT"


def _row(**changes: object) -> StrategyBucketAccountConfigRowV1:
    values: dict[str, object] = dict(
        strategy_bucket_account_config_id=1,
        trading_account_id=ACCOUNT_A,
        strategy_bucket_id=BUCKET_A,
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


def _resolve(row: StrategyBucketAccountConfigRowV1, *, strategy_bucket_id: str = BUCKET_A):
    return resolve_strategy_bucket_account_config_v1(
        (row,), (), trading_account_id=ACCOUNT_A, strategy_bucket_id=strategy_bucket_id, at=NOW,
    )


# --- 1/2/3: config percentage validation, target <= max, max <= 100% -----


def test_allocation_target_pct_out_of_range_rejected():
    with pytest.raises(StrategyBucketAccountConfigError, match="INVALID_STRATEGY_BUCKET_ALLOCATION_TARGET_PCT"):
        _resolve(_row(allocation_target_pct=Decimal("1.5")))


def test_allocation_max_pct_out_of_range_rejected():
    with pytest.raises(StrategyBucketAccountConfigError, match="INVALID_STRATEGY_BUCKET_ALLOCATION_MAX_PCT"):
        _resolve(_row(allocation_max_pct=Decimal("-0.1")))


def test_allocation_target_exceeding_max_rejected():
    with pytest.raises(StrategyBucketAccountConfigError, match="STRATEGY_BUCKET_ALLOCATION_TARGET_EXCEEDS_MAX"):
        _resolve(_row(allocation_target_pct=Decimal("0.5"), allocation_max_pct=Decimal("0.3")))


def test_allocation_target_equal_to_max_permitted():
    config = _resolve(_row(allocation_target_pct=Decimal("0.3"), allocation_max_pct=Decimal("0.3")))
    assert config.allocation_target_pct == Decimal("0.3")
    assert config.allocation_max_pct == Decimal("0.3")


def test_allocation_max_pct_of_exactly_one_permitted_above_one_rejected():
    _resolve(_row(allocation_max_pct=Decimal("1")))  # 100% is the ceiling, permitted
    with pytest.raises(StrategyBucketAccountConfigError, match="INVALID_STRATEGY_BUCKET_ALLOCATION_MAX_PCT"):
        _resolve(_row(allocation_max_pct=Decimal("1.01")))


# --- 5: target below current allocation does NOT authorize/force BUY -----


def test_allocation_target_pct_is_never_consulted_by_new_entry_capacity_check():
    # A low target alongside a higher max must never narrow OR widen
    # permission by itself -- only max (and the absolute cap) bound the
    # effective ceiling; target is provenance only, never a floor or a cap.
    config = _resolve(_row(allocation_target_pct=Decimal("0.01"), allocation_max_pct=Decimal("0.1")))
    capacity = compute_strategy_bucket_capacity_v1(
        config, account_equity_eur=Decimal("1000"), owned_exposure_eur=Decimal("0"),
    )
    assert capacity.effective_bucket_ceiling_eur == Decimal("100")  # 10% of equity, not 1%
    validate_new_entry_within_capacity_v1(capacity, proposed_position_amount_eur=Decimal("50"))
    with pytest.raises(StrategyBucketCapacityError, match="STRATEGY_BUCKET_CAPACITY_EXCEEDED_FOR_NEW_ENTRY"):
        validate_new_entry_within_capacity_v1(capacity, proposed_position_amount_eur=Decimal("150"))


# --- 6: percentage ceiling scales with account equity ---------------------


def test_percentage_ceiling_scales_with_account_equity():
    config = _resolve(_row(allocation_max_pct=Decimal("0.25")))
    small = compute_strategy_bucket_capacity_v1(
        config, account_equity_eur=Decimal("1000"), owned_exposure_eur=Decimal("0"),
    )
    large = compute_strategy_bucket_capacity_v1(
        config, account_equity_eur=Decimal("4000"), owned_exposure_eur=Decimal("0"),
    )
    assert small.effective_bucket_ceiling_eur == Decimal("250")
    assert large.effective_bucket_ceiling_eur == Decimal("1000")


# --- 7: absolute EUR cap is stricter when lower ----------------------------


def test_absolute_cap_wins_when_stricter_than_percentage():
    config = _resolve(_row(allocation_max_pct=Decimal("0.5"), max_bucket_amount_eur=Decimal("100")))
    capacity = compute_strategy_bucket_capacity_v1(
        config, account_equity_eur=Decimal("1000"), owned_exposure_eur=Decimal("0"),
    )
    # 50% of 1000 = 500, but the absolute cap of 100 is stricter and wins.
    assert capacity.effective_bucket_ceiling_eur == Decimal("100")


def test_percentage_cap_wins_when_stricter_than_absolute():
    config = _resolve(_row(allocation_max_pct=Decimal("0.05"), max_bucket_amount_eur=Decimal("1000")))
    capacity = compute_strategy_bucket_capacity_v1(
        config, account_equity_eur=Decimal("1000"), owned_exposure_eur=Decimal("0"),
    )
    # 5% of 1000 = 50, stricter than the 1000 absolute cap.
    assert capacity.effective_bucket_ceiling_eur == Decimal("50")


# --- 8: existing #279 absolute-only behavior remains backward-compatible --


def test_pre_752_row_with_no_percentage_fields_behaves_as_absolute_only():
    config = _resolve(_row(max_bucket_amount_eur=Decimal("500")))
    assert config.allocation_target_pct is None
    assert config.allocation_max_pct is None
    capacity = compute_strategy_bucket_capacity_v1(
        config, account_equity_eur=Decimal("1000000"), owned_exposure_eur=Decimal("0"),
    )
    assert capacity.effective_bucket_ceiling_eur == Decimal("500")


def test_no_ceiling_configured_at_all_does_not_block_new_entry():
    config = _resolve(_row())
    capacity = compute_strategy_bucket_capacity_v1(
        config, account_equity_eur=Decimal("1000"), owned_exposure_eur=Decimal("0"),
    )
    assert capacity.remaining_capacity_eur is None
    validate_new_entry_within_capacity_v1(capacity, proposed_position_amount_eur=Decimal("999999"))


# --- 4: aggregate hard maxima policy fail closed --------------------------


def test_aggregate_allocation_max_pct_within_policy_permitted():
    bucket_a = _resolve(_row(allocation_max_pct=Decimal("0.4")), strategy_bucket_id=BUCKET_A)
    bucket_b = _resolve(
        _row(strategy_bucket_id=BUCKET_B, allocation_max_pct=Decimal("0.4")), strategy_bucket_id=BUCKET_B,
    )
    validate_aggregate_sleeve_allocation_policy_v1((bucket_a, bucket_b))


def test_aggregate_allocation_max_pct_over_policy_fails_closed():
    bucket_a = _resolve(_row(allocation_max_pct=Decimal("0.7")), strategy_bucket_id=BUCKET_A)
    bucket_b = _resolve(
        _row(strategy_bucket_id=BUCKET_B, allocation_max_pct=Decimal("0.4")), strategy_bucket_id=BUCKET_B,
    )
    with pytest.raises(
        StrategyBucketCapacityError, match="AGGREGATE_SLEEVE_ALLOCATION_MAX_PCT_EXCEEDS_ACCOUNT_POLICY",
    ):
        validate_aggregate_sleeve_allocation_policy_v1((bucket_a, bucket_b))


def test_aggregate_policy_never_renormalizes_or_ignores_disabled_buckets():
    bucket_a = _resolve(_row(allocation_max_pct=Decimal("0.7")), strategy_bucket_id=BUCKET_A)
    disabled_bucket_b = _resolve(
        _row(strategy_bucket_id=BUCKET_B, is_enabled=False, allocation_max_pct=Decimal("0.5")),
        strategy_bucket_id=BUCKET_B,
    )
    # Disabled bucket's 0.5 is excluded from the sum -- 0.7 alone is fine.
    validate_aggregate_sleeve_allocation_policy_v1((bucket_a, disabled_bucket_b))


# --- 22 (capacity-module scope): invalid/missing equity fails closed for NEW exposure --


def test_invalid_account_equity_fails_closed():
    config = _resolve(_row(allocation_max_pct=Decimal("0.5")))
    with pytest.raises(StrategyBucketCapacityError, match="INVALID_ACCOUNT_EQUITY"):
        compute_strategy_bucket_capacity_v1(
            config, account_equity_eur=Decimal("-1"), owned_exposure_eur=Decimal("0"),
        )
