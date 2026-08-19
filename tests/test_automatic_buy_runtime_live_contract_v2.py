from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.entry_policy.automatic_buy_runtime_contract_v1 import (
    AutomaticBuyRuntimeContractError,
    AutomaticBuyRuntimeInputV1,
    automatic_buy_idempotency_key_v1,
    automatic_buy_idempotency_key_v2,
    validate_runtime_input_v1,
)

NOW = datetime(2026, 8, 19, 20, 0, tzinfo=UTC)


def _input(**changes: object) -> AutomaticBuyRuntimeInputV1:
    values: dict[str, object] = dict(
        automatic_buy_runtime_input_id=1,
        source_snapshot_key="a" * 64,
        input_contract_version="1",
        evaluation_ts_utc=NOW,
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
        setup_evidence_id="setup-evidence-1",
        setup_observed_ts_utc=NOW - timedelta(seconds=5),
        account_observed_ts_utc=NOW - timedelta(seconds=4),
        account_enabled=True,
        account_mode="paper",
        automatic_buy_execution_enabled=True,
        free_quote_balance_eur=Decimal("1000"),
        free_quote_balance_observed_ts_utc=NOW - timedelta(seconds=3),
        blocking_conflict=False,
        proposed_position_amount_eur=Decimal("100"),
        current_bucket_amount_eur=Decimal("0"),
        current_open_positions=0,
        current_asset_exposure_pct=Decimal("0"),
        max_automatic_buy_notional_eur=Decimal("75"),
        source_provenance="test",
        live_trading_enabled=False,
    )
    values.update(changes)
    return AutomaticBuyRuntimeInputV1(**values)  # type: ignore[arg-type]


def _v1_evidence() -> dict[str, object]:
    return {
        "source_snapshot_key": "a" * 64,
        "evaluation_ts_utc": NOW,
        "trading_account_id": 101,
        "venue": "bitvavo",
        "asset_id": 42,
        "market": "BTC-EUR",
        "strategy_id": "strategy-a",
        "strategy_version": "1",
        "setup_id": "setup-1",
        "setup_evidence_id": "setup-evidence-1",
        "strategy_bucket_config_ids": (10, 11),
        "strategy_bucket_revocation_ids": (),
        "account_protection_fingerprint": "b" * 64,
        "venue_constraint_identity": {
            "market": "BTC-EUR",
            "metadata_synced_ts_utc": "2026-08-19T19:00:00Z",
        },
    }


def _v2_evidence(**changes: object) -> dict[str, object]:
    value = {
        **_v1_evidence(),
        "live_trading_enabled": True,
        "automatic_buy_live_permission_fingerprint": "c" * 64,
    }
    value.update(changes)
    return value


def test_v1_paper_snapshot_remains_valid() -> None:
    validate_runtime_input_v1(_input())


def test_v1_can_never_be_reinterpreted_as_live() -> None:
    for changes in (
        {"account_mode": "live"},
        {"live_trading_enabled": True},
        {"account_mode": "live", "live_trading_enabled": True},
    ):
        with pytest.raises(AutomaticBuyRuntimeContractError, match="LIVE_RUNTIME_INPUT_REQUIRES_CONTRACT_V2"):
            validate_runtime_input_v1(_input(**changes))


def test_v2_carries_live_evidence_without_requiring_activation_to_be_true() -> None:
    validate_runtime_input_v1(_input(input_contract_version="2", account_mode="live", live_trading_enabled=False))
    validate_runtime_input_v1(_input(input_contract_version="2", account_mode="live", live_trading_enabled=True))


def test_v1_idempotency_contract_is_unchanged() -> None:
    evidence = _v1_evidence()
    reversed_evidence = dict(reversed(tuple(evidence.items())))
    assert automatic_buy_idempotency_key_v1(evidence) == automatic_buy_idempotency_key_v1(reversed_evidence)


def test_v2_identity_binds_live_flag_and_permission_evidence() -> None:
    baseline = automatic_buy_idempotency_key_v2(_v2_evidence())
    assert baseline != automatic_buy_idempotency_key_v2(_v2_evidence(live_trading_enabled=False))
    assert baseline != automatic_buy_idempotency_key_v2(
        _v2_evidence(automatic_buy_live_permission_fingerprint="d" * 64)
    )


def test_v2_rejects_missing_live_identity_evidence() -> None:
    missing_flag = _v2_evidence()
    del missing_flag["live_trading_enabled"]
    with pytest.raises(AutomaticBuyRuntimeContractError, match="INCOMPLETE_IDEMPOTENCY_EVIDENCE"):
        automatic_buy_idempotency_key_v2(missing_flag)

    missing_permission = _v2_evidence()
    del missing_permission["automatic_buy_live_permission_fingerprint"]
    with pytest.raises(AutomaticBuyRuntimeContractError, match="INCOMPLETE_IDEMPOTENCY_EVIDENCE"):
        automatic_buy_idempotency_key_v2(missing_permission)
