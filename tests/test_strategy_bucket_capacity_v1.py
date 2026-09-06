from decimal import Decimal

import pytest

from src.decision_gate.strategy_bucket_account_config_contract_v1 import StrategyBucketAccountConfigV1
from src.decision_gate.strategy_bucket_capacity_v1 import (
    StrategyBucketCapacityError,
    StrategyBucketCapacityInputV1,
    compute_strategy_bucket_capacity_v1,
)


def _config(**changes):
    values = dict(
        trading_account_id=7,
        strategy_bucket_id="AUTO_SHORTTF_FIB",
        is_enabled=True,
        risk_profile="standard",
        max_position_amount_eur=Decimal("250"),
        max_bucket_amount_eur=Decimal("4000"),
        max_asset_exposure_pct=None,
        max_open_positions=None,
        allow_new_entries=True,
        allow_reduce_reviews=True,
        allocation_target_pct=Decimal("0.30"),
        allocation_max_pct=Decimal("0.40"),
    )
    values.update(changes)
    return StrategyBucketAccountConfigV1(**values)


def _evidence(**changes):
    values = dict(
        account_equity_eur=Decimal("10000"),
        strategy_owned_exposure_eur=Decimal("2500"),
        entry_reservations_eur=Decimal("300"),
        open_buy_order_remaining_eur=Decimal("200"),
    )
    values.update(changes)
    return StrategyBucketCapacityInputV1(**values)


def test_capacity_counts_owned_reservations_and_open_buy_remainder():
    result = compute_strategy_bucket_capacity_v1(_config(), evidence=_evidence())
    assert result.hard_ceiling_eur == Decimal("4000")
    assert result.committed_capital_eur == Decimal("3000")
    assert result.remaining_capacity_eur == Decimal("1000")
    assert result.allocation_target_eur == Decimal("3000.00")
    assert result.new_exposure_allowed is True
    assert result.reducing_exit_allowed is True


def test_stricter_absolute_ceiling_wins_over_percentage():
    result = compute_strategy_bucket_capacity_v1(
        _config(max_bucket_amount_eur=Decimal("2500")),
        evidence=_evidence(strategy_owned_exposure_eur=Decimal("2000"), entry_reservations_eur=Decimal("0"), open_buy_order_remaining_eur=Decimal("0")),
    )
    assert result.hard_ceiling_eur == Decimal("2500")
    assert result.remaining_capacity_eur == Decimal("500")


def test_at_or_over_ceiling_blocks_new_exposure_but_not_reductions():
    result = compute_strategy_bucket_capacity_v1(
        _config(), evidence=_evidence(strategy_owned_exposure_eur=Decimal("3900"), entry_reservations_eur=Decimal("100"), open_buy_order_remaining_eur=Decimal("50")),
    )
    assert result.remaining_capacity_eur == Decimal("0")
    assert result.new_exposure_allowed is False
    assert result.reducing_exit_allowed is True


def test_below_target_does_not_create_demand_or_override_entry_disable():
    result = compute_strategy_bucket_capacity_v1(
        _config(allow_new_entries=False),
        evidence=_evidence(strategy_owned_exposure_eur=Decimal("500"), entry_reservations_eur=Decimal("0"), open_buy_order_remaining_eur=Decimal("0")),
    )
    assert result.allocation_target_eur == Decimal("3000.00")
    assert result.remaining_capacity_eur == Decimal("3500")
    assert result.new_exposure_allowed is False


def test_unresolved_hard_ceiling_fails_closed():
    with pytest.raises(StrategyBucketCapacityError, match="STRATEGY_BUCKET_CEILING_UNRESOLVED"):
        compute_strategy_bucket_capacity_v1(
            _config(max_bucket_amount_eur=None, allocation_max_pct=None), evidence=_evidence(),
        )


def test_negative_capacity_component_fails_closed():
    with pytest.raises(StrategyBucketCapacityError, match="INVALID_STRATEGY_BUCKET_CAPACITY_EVIDENCE"):
        compute_strategy_bucket_capacity_v1(
            _config(), evidence=_evidence(entry_reservations_eur=Decimal("-1")),
        )
