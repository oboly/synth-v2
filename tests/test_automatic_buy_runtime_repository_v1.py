from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.decision_gate.automatic_buy_gate_v1 import (
    REASON_ACCOUNT_MODE_EVIDENCE_INCONSISTENT,
    STATE_APPROVED,
    STATE_NON_ACTIONABLE,
    AutomaticBuyGateContextV1,
    evaluate_automatic_buy_candidate_permission_v1,
)
from src.entry_policy.automatic_buy_candidate_v1 import POLICY_NAME, POLICY_VERSION, AutomaticBuyCandidateV1
from src.entry_policy.automatic_buy_runtime_contract_v1 import AutomaticBuyRuntimeInputV1
from src.entry_policy.automatic_buy_runtime_repository_v1 import (
    AutomaticBuyRuntimeRepositoryError,
    _row_to_input,
    build_runtime_item_v1,
)
from tests.automatic_buy_account_allocation_evidence_fixtures_v1 import (
    TS,
    FakeConnection,
    insert_trading_account,
    seed_happy_path,
)


def test_runtime_input_row_mapping_preserves_evaluation_instant() -> None:
    now = datetime(2026, 8, 19, 16, 0, tzinfo=UTC)
    row = {
        "automatic_buy_runtime_input_id": 1,
        "source_snapshot_key": "a" * 64,
        "input_contract_version": "1",
        "evaluation_ts_utc": now.replace(tzinfo=None),
        "trading_account_id": 101,
        "venue": "bitvavo",
        "asset_id": 42,
        "market": "BTC-EUR",
        "strategy_bucket_id": "SHORT_TERM_ROTATION",
        "strategy_id": "strategy-a",
        "strategy_version": "1",
        "setup_id": "setup-1",
        "setup_ready": 1,
        "current_price": Decimal("100"),
        "entry_zone_low": Decimal("99"),
        "entry_zone_high": Decimal("101"),
        "re_entry_zone_low": None,
        "re_entry_zone_high": None,
        "setup_evidence_id": "ev-1",
        "setup_observed_ts_utc": now.replace(tzinfo=None),
        "account_observed_ts_utc": now.replace(tzinfo=None),
        "account_enabled": 1,
        "account_mode": "paper",
        "automatic_buy_execution_enabled": 1,
        "free_quote_balance_eur": Decimal("1000"),
        "free_quote_balance_observed_ts_utc": now.replace(tzinfo=None),
        "blocking_conflict": 0,
        "proposed_position_amount_eur": Decimal("100"),
        "current_bucket_amount_eur": Decimal("0"),
        "current_open_positions": 0,
        "current_asset_exposure_pct": Decimal("0"),
        "max_automatic_buy_notional_eur": Decimal("50"),
        "source_provenance": "test",
    }
    value = _row_to_input(row)
    assert value.evaluation_ts_utc == now
    assert value.trading_account_id == 101
    assert value.account_mode == "paper"


def _runtime_input(**overrides: object) -> AutomaticBuyRuntimeInputV1:
    """A runtime_input row that, prior to Issue #474, would have driven the
    gate directly from these caller-supplied account-owned fields. Every test
    below either seeds the opposite canonical DB truth to prove it is
    ignored, or holds these fields at safe defaults to isolate one failure
    mode."""
    base = dict(
        automatic_buy_runtime_input_id=1,
        source_snapshot_key="a" * 64,
        input_contract_version="1",
        evaluation_ts_utc=TS,
        trading_account_id=7,
        venue="bitvavo",
        asset_id=101,
        market="BTC-EUR",
        strategy_bucket_id="SHORT_TERM_ROTATION",
        strategy_id="strategy-a",
        strategy_version="1",
        setup_id="setup-1",
        setup_ready=True,
        current_price=Decimal("100"),
        entry_zone_low=None,
        entry_zone_high=None,
        re_entry_zone_low=None,
        re_entry_zone_high=None,
        setup_evidence_id="ev-1",
        setup_observed_ts_utc=TS,
        account_observed_ts_utc=TS,
        account_enabled=True,
        account_mode="paper",
        automatic_buy_execution_enabled=True,
        free_quote_balance_eur=Decimal("1000"),
        free_quote_balance_observed_ts_utc=TS,
        blocking_conflict=False,
        proposed_position_amount_eur=Decimal("250"),
        current_bucket_amount_eur=Decimal("0"),
        current_open_positions=0,
        current_asset_exposure_pct=Decimal("0"),
        max_automatic_buy_notional_eur=None,
        source_provenance="test",
        live_trading_enabled=False,
    )
    base.update(overrides)
    return AutomaticBuyRuntimeInputV1(**base)  # type: ignore[arg-type]


def test_build_runtime_item_v1_account_state_fields_are_not_caller_overridable() -> None:
    """A malicious/stale runtime_input row claims account_disabled,
    execution-disabled, an inflated free balance, an inflated proposed
    amount, nonzero bucket exposure, and a blocking conflict. The composed
    item must reflect the seeded canonical DB truth instead, not one word of
    the row's own account-owned columns."""
    conn = FakeConnection()
    seed_happy_path(conn)
    hostile_input = _runtime_input(
        account_enabled=False,
        automatic_buy_execution_enabled=False,
        free_quote_balance_eur=Decimal("999999"),
        proposed_position_amount_eur=Decimal("999999"),
        current_bucket_amount_eur=Decimal("12345"),
        current_open_positions=99,
        current_asset_exposure_pct=Decimal("77"),
        blocking_conflict=True,
    )
    item = build_runtime_item_v1(conn, runtime_input=hostile_input)
    assert item.runtime_input.account_enabled is True
    assert item.runtime_input.automatic_buy_execution_enabled is True
    assert item.runtime_input.free_quote_balance_eur == Decimal("1000")
    assert item.runtime_input.proposed_position_amount_eur == Decimal("250")
    assert item.runtime_input.current_bucket_amount_eur == Decimal("0")
    assert item.runtime_input.current_open_positions == 0
    assert item.runtime_input.current_asset_exposure_pct == Decimal("0")
    assert item.runtime_input.blocking_conflict is False


def test_build_runtime_item_v1_account_mode_and_live_flag_are_not_caller_overridable() -> None:
    """A runtime_input row claims LIVE + live_trading_enabled=True while the
    real trading_account is PAPER. The composed item must reflect PAPER."""
    conn = FakeConnection()
    seed_happy_path(conn)
    hostile_input = _runtime_input(
        input_contract_version="2",
        account_mode="live",
        live_trading_enabled=True,
    )
    item = build_runtime_item_v1(conn, runtime_input=hostile_input)
    assert item.runtime_input.account_mode == "paper"
    assert item.runtime_input.live_trading_enabled is False


def test_build_runtime_item_v1_missing_bucket_config_fails_closed() -> None:
    conn = FakeConnection()
    insert_trading_account(conn)
    with pytest.raises(AutomaticBuyRuntimeRepositoryError):
        build_runtime_item_v1(conn, runtime_input=_runtime_input())


def test_build_runtime_item_v1_missing_account_state_fails_closed() -> None:
    from tests.automatic_buy_account_allocation_evidence_fixtures_v1 import (
        bind_account_market,
        insert_bucket_config,
        insert_buy_permission,
        insert_venue_market,
    )

    conn = FakeConnection()
    insert_trading_account(conn)
    venue_market_id = insert_venue_market(conn)
    bind_account_market(conn, venue_market_id=venue_market_id)
    insert_bucket_config(conn)
    insert_buy_permission(conn)
    with pytest.raises(AutomaticBuyRuntimeRepositoryError):
        build_runtime_item_v1(conn, runtime_input=_runtime_input())


def test_build_runtime_item_v1_paper_account_reaches_approved_gate_decision_end_to_end() -> None:
    """The composed item's canonical evidence, fed into the real
    automatic_buy_gate_v1 with no operator/caller involvement in any
    account-owned field, reaches APPROVED for a properly configured PAPER
    account."""
    conn = FakeConnection()
    seed_happy_path(conn)
    item = build_runtime_item_v1(conn, runtime_input=_runtime_input())
    candidate = AutomaticBuyCandidateV1(
        venue=item.runtime_input.venue,
        asset_id=item.runtime_input.asset_id,
        market=item.runtime_input.market,
        strategy_id=item.runtime_input.strategy_id,
        strategy_version=item.runtime_input.strategy_version,
        setup_id=item.runtime_input.setup_id,
        candidate_action="ENTER",
        reason_code="OK",
        evidence_id=item.runtime_input.setup_evidence_id,
        entry_zone_low=None,
        entry_zone_high=None,
        observed_ts_utc=item.runtime_input.setup_observed_ts_utc,
        policy_name=POLICY_NAME,
        policy_version=POLICY_VERSION,
    )
    context = AutomaticBuyGateContextV1(
        trading_account_id=item.runtime_input.trading_account_id,
        venue=item.runtime_input.venue,
        asset_id=item.runtime_input.asset_id,
        market=item.runtime_input.market,
        strategy_bucket_id=item.runtime_input.strategy_bucket_id,
        account_observed_ts_utc=item.runtime_input.account_observed_ts_utc,
        account_enabled=item.runtime_input.account_enabled,
        account_mode=item.runtime_input.account_mode,
        automatic_buy_execution_enabled=item.runtime_input.automatic_buy_execution_enabled,
        free_quote_balance_eur=item.runtime_input.free_quote_balance_eur,
        free_quote_balance_observed_ts_utc=item.runtime_input.free_quote_balance_observed_ts_utc,
        blocking_conflict=item.runtime_input.blocking_conflict,
        proposed_position_amount_eur=item.runtime_input.proposed_position_amount_eur,
        current_bucket_amount_eur=item.runtime_input.current_bucket_amount_eur,
        current_open_positions=item.runtime_input.current_open_positions,
        current_asset_exposure_pct=item.runtime_input.current_asset_exposure_pct,
        evaluation_ts_utc=item.runtime_input.evaluation_ts_utc,
        max_automatic_buy_notional_eur=item.runtime_input.max_automatic_buy_notional_eur,
        strategy_bucket_config_rows=item.strategy_bucket_config_rows,
        strategy_bucket_config_revocations=item.strategy_bucket_config_revocations,
        account_protection_evaluation=item.account_protection_evaluation,
        live_trading_enabled=item.runtime_input.live_trading_enabled,
        automatic_buy_live_permission_evaluation=item.automatic_buy_live_permission_evaluation,
    )
    decision = evaluate_automatic_buy_candidate_permission_v1(candidate=candidate, context=context)
    assert decision.state == STATE_APPROVED


def test_build_runtime_item_v1_live_account_flag_false_still_rejected_by_gate_end_to_end() -> None:
    """Production account-3 shape: account_mode=live, live_trading_enabled=0.
    The composed evidence reflects this faithfully; automatic_buy_gate_v1 is
    the layer that rejects it -- proving no LIVE flag weakening anywhere in
    this composition."""
    from tests.automatic_buy_account_allocation_evidence_fixtures_v1 import (
        bind_account_market,
        insert_balance,
        insert_bucket_config,
        insert_buy_permission,
        insert_complete_bundle,
        insert_venue_constraint,
        insert_venue_market,
    )

    conn = FakeConnection()
    insert_trading_account(conn, account_mode="live", live_trading_enabled=False)
    insert_complete_bundle(conn)
    venue_market_id = insert_venue_market(conn)
    bind_account_market(conn, venue_market_id=venue_market_id)
    insert_balance(conn)
    insert_bucket_config(conn)
    insert_buy_permission(conn)
    insert_venue_constraint(conn)

    item = build_runtime_item_v1(
        conn, runtime_input=_runtime_input(input_contract_version="2"),
    )
    assert item.runtime_input.account_mode == "live"
    assert item.runtime_input.live_trading_enabled is False

    candidate = AutomaticBuyCandidateV1(
        venue=item.runtime_input.venue,
        asset_id=item.runtime_input.asset_id,
        market=item.runtime_input.market,
        strategy_id=item.runtime_input.strategy_id,
        strategy_version=item.runtime_input.strategy_version,
        setup_id=item.runtime_input.setup_id,
        candidate_action="ENTER",
        reason_code="OK",
        evidence_id=item.runtime_input.setup_evidence_id,
        entry_zone_low=None,
        entry_zone_high=None,
        observed_ts_utc=item.runtime_input.setup_observed_ts_utc,
        policy_name=POLICY_NAME,
        policy_version=POLICY_VERSION,
    )
    context = AutomaticBuyGateContextV1(
        trading_account_id=item.runtime_input.trading_account_id,
        venue=item.runtime_input.venue,
        asset_id=item.runtime_input.asset_id,
        market=item.runtime_input.market,
        strategy_bucket_id=item.runtime_input.strategy_bucket_id,
        account_observed_ts_utc=item.runtime_input.account_observed_ts_utc,
        account_enabled=item.runtime_input.account_enabled,
        account_mode=item.runtime_input.account_mode,
        automatic_buy_execution_enabled=item.runtime_input.automatic_buy_execution_enabled,
        free_quote_balance_eur=item.runtime_input.free_quote_balance_eur,
        free_quote_balance_observed_ts_utc=item.runtime_input.free_quote_balance_observed_ts_utc,
        blocking_conflict=item.runtime_input.blocking_conflict,
        proposed_position_amount_eur=item.runtime_input.proposed_position_amount_eur,
        current_bucket_amount_eur=item.runtime_input.current_bucket_amount_eur,
        current_open_positions=item.runtime_input.current_open_positions,
        current_asset_exposure_pct=item.runtime_input.current_asset_exposure_pct,
        evaluation_ts_utc=item.runtime_input.evaluation_ts_utc,
        max_automatic_buy_notional_eur=item.runtime_input.max_automatic_buy_notional_eur,
        strategy_bucket_config_rows=item.strategy_bucket_config_rows,
        strategy_bucket_config_revocations=item.strategy_bucket_config_revocations,
        account_protection_evaluation=item.account_protection_evaluation,
        live_trading_enabled=item.runtime_input.live_trading_enabled,
        automatic_buy_live_permission_evaluation=item.automatic_buy_live_permission_evaluation,
    )
    decision = evaluate_automatic_buy_candidate_permission_v1(candidate=candidate, context=context)
    assert decision.state == STATE_NON_ACTIONABLE
    assert decision.reason_code == REASON_ACCOUNT_MODE_EVIDENCE_INCONSISTENT
