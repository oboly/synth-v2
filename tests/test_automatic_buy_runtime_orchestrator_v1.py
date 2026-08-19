from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from src.decision_gate.account_protection_contract_v1 import (
    EVALUATION_CONTRACT_VERSION,
    STATE_PERMITTED,
    AccountProtectionEvaluationV1,
)
from src.decision_gate.strategy_bucket_account_config_contract_v1 import StrategyBucketAccountConfigRowV1
from src.entry_policy.automatic_buy_runtime_contract_v1 import AutomaticBuyRuntimeInputV1
from src.entry_policy.automatic_buy_runtime_orchestrator_v1 import build_automatic_buy_source_evidence_v1
from src.entry_policy.automatic_buy_runtime_repository_v1 import RuntimeItemV1
from src.market_rules.venue_execution_constraints_v1 import STATUS_FRESH, VenueExecutionConstraints


def test_source_evidence_binds_config_protection_and_venue_identity() -> None:
    now = datetime(2026, 8, 19, 16, 0, tzinfo=UTC)
    runtime_input = AutomaticBuyRuntimeInputV1(
        automatic_buy_runtime_input_id=1,
        source_snapshot_key="a" * 64,
        input_contract_version="1",
        evaluation_ts_utc=now,
        trading_account_id=101,
        venue="bitvavo",
        asset_id=42,
        market="BTC-EUR",
        strategy_bucket_id="SHORT_TERM_ROTATION",
        strategy_id="strategy-a",
        strategy_version="1",
        setup_id="setup-1",
        setup_ready=True,
        current_price=Decimal("100"),
        entry_zone_low=Decimal("99"),
        entry_zone_high=Decimal("101"),
        re_entry_zone_low=None,
        re_entry_zone_high=None,
        setup_evidence_id="ev-1",
        setup_observed_ts_utc=now - timedelta(seconds=1),
        account_observed_ts_utc=now - timedelta(seconds=1),
        account_enabled=True,
        account_mode="paper",
        automatic_buy_execution_enabled=True,
        free_quote_balance_eur=Decimal("100"),
        free_quote_balance_observed_ts_utc=now - timedelta(seconds=1),
        blocking_conflict=False,
        proposed_position_amount_eur=Decimal("50"),
        current_bucket_amount_eur=Decimal("0"),
        current_open_positions=0,
        current_asset_exposure_pct=Decimal("0"),
        max_automatic_buy_notional_eur=None,
        source_provenance="test",
    )
    config = StrategyBucketAccountConfigRowV1(
        strategy_bucket_account_config_id=77,
        trading_account_id=101,
        strategy_bucket_id="SHORT_TERM_ROTATION",
        config_version="1",
        is_enabled=True,
        risk_profile="test",
        max_position_amount_eur=Decimal("100"),
        max_bucket_amount_eur=Decimal("1000"),
        max_asset_exposure_pct=Decimal("50"),
        max_open_positions=10,
        allow_new_entries=True,
        allow_reduce_reviews=True,
        effective_from_ts_utc=now - timedelta(days=1),
        effective_until_ts_utc=None,
        source_provenance="test",
    )
    protection = AccountProtectionEvaluationV1(
        evaluation_contract_version=EVALUATION_CONTRACT_VERSION,
        decision_state=STATE_PERMITTED,
        reason_code="NO_ACTIVE_PROTECTION",
        trading_account_id=101,
        protection_code=None,
        scope_type=None,
        scope_id=None,
        expires_ts_utc=None,
        contributing_lock_facts=(),
        evaluated_ts_utc=now,
        requested_action="BUY",
        sleeve_code=None,
        asset_id=42,
    )
    constraints = VenueExecutionConstraints(
        venue="bitvavo",
        market="BTC-EUR",
        tick_size=Decimal("0.01"),
        qty_step_size=Decimal("0.0001"),
        min_base_quantity=Decimal("0.0001"),
        min_quote_notional=Decimal("5"),
        supported_order_types=("limit",),
        supported_time_in_force=("gtc",),
        source_provenance="test",
        metadata_synced_ts_utc=now,
        status=STATUS_FRESH,
    )
    evidence = build_automatic_buy_source_evidence_v1(RuntimeItemV1(
        runtime_input=runtime_input,
        strategy_bucket_config_rows=(config,),
        strategy_bucket_config_revocations=(),
        account_protection_evaluation=protection,
        venue_constraints=constraints,
    ))
    assert evidence["evaluation_ts_utc"] == now
    assert evidence["strategy_bucket_config_ids"] == (77,)
    assert len(evidence["account_protection_fingerprint"]) == 64
    assert evidence["venue_constraint_identity"]["market"] == "BTC-EUR"
