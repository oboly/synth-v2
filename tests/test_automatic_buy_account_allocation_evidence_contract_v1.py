from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.decision_gate.automatic_buy_account_allocation_evidence_contract_v1 import (
    EVIDENCE_CONTRACT_VERSION,
    AutomaticBuyAccountAllocationEvidenceContractError,
    AutomaticBuyAccountAllocationEvidenceV1,
    validate_automatic_buy_account_allocation_evidence_v1,
)

TS = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


def _evidence(**overrides: object) -> AutomaticBuyAccountAllocationEvidenceV1:
    base = dict(
        evidence_contract_version=EVIDENCE_CONTRACT_VERSION,
        trading_account_id=7,
        venue="bitvavo",
        asset_id=101,
        market="BTC-EUR",
        strategy_bucket_id="SHORT_TERM_ROTATION",
        evaluation_ts_utc=TS,
        account_observed_ts_utc=TS,
        account_enabled=True,
        account_mode="paper",
        live_trading_enabled=False,
        automatic_buy_execution_enabled=True,
        free_quote_balance_eur=Decimal("1000"),
        free_quote_balance_observed_ts_utc=TS,
        blocking_conflict=False,
        proposed_position_amount_eur=Decimal("250"),
        current_bucket_amount_eur=Decimal("0"),
        current_open_positions=0,
        current_asset_exposure_pct=Decimal("0"),
        account_state_snapshot_run_id=1,
        trading_account_balance_snapshot_id=1,
    )
    base.update(overrides)
    return AutomaticBuyAccountAllocationEvidenceV1(**base)  # type: ignore[arg-type]


def test_valid_paper_evidence_passes() -> None:
    validate_automatic_buy_account_allocation_evidence_v1(_evidence())


def test_valid_live_evidence_passes() -> None:
    validate_automatic_buy_account_allocation_evidence_v1(
        _evidence(account_mode="live", live_trading_enabled=True)
    )


def test_live_mode_without_live_flag_binds_faithfully_not_a_contract_error() -> None:
    """account_mode=live + live_trading_enabled=False is a real, expected
    persisted trading_account state (e.g. production account 3): the
    projection binds it as-is. Rejecting it is automatic_buy_gate_v1's job
    (REASON_ACCOUNT_MODE_EVIDENCE_INCONSISTENT), not this contract's."""
    validate_automatic_buy_account_allocation_evidence_v1(
        _evidence(account_mode="live", live_trading_enabled=False)
    )


def test_stale_account_observation_fails_closed() -> None:
    with pytest.raises(AutomaticBuyAccountAllocationEvidenceContractError):
        validate_automatic_buy_account_allocation_evidence_v1(
            _evidence(account_observed_ts_utc=TS - timedelta(hours=1)),
            max_age_seconds=900,
        )


def test_stale_balance_observation_fails_closed() -> None:
    with pytest.raises(AutomaticBuyAccountAllocationEvidenceContractError):
        validate_automatic_buy_account_allocation_evidence_v1(
            _evidence(free_quote_balance_observed_ts_utc=TS - timedelta(hours=1)),
            max_age_seconds=900,
        )


def test_exposure_over_100_fails_closed() -> None:
    with pytest.raises(AutomaticBuyAccountAllocationEvidenceContractError):
        validate_automatic_buy_account_allocation_evidence_v1(
            _evidence(current_asset_exposure_pct=Decimal("101"))
        )


def test_negative_open_positions_fails_closed() -> None:
    with pytest.raises(AutomaticBuyAccountAllocationEvidenceContractError):
        validate_automatic_buy_account_allocation_evidence_v1(
            _evidence(current_open_positions=-1)
        )


def test_naive_timestamp_fails_closed() -> None:
    with pytest.raises(AutomaticBuyAccountAllocationEvidenceContractError):
        validate_automatic_buy_account_allocation_evidence_v1(
            _evidence(evaluation_ts_utc=datetime(2026, 8, 22, 12, 0))
        )


def test_zero_proposed_position_amount_is_structurally_valid() -> None:
    """An unresolved allocation policy yields 0, not an override; validity is
    a structural check only -- callers that require a positive amount enforce
    that themselves (see automatic_buy_runtime_repository_v1)."""
    validate_automatic_buy_account_allocation_evidence_v1(
        replace(_evidence(), proposed_position_amount_eur=Decimal("0"))
    )
