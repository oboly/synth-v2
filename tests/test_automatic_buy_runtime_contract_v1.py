from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.entry_policy.automatic_buy_runtime_contract_v1 import (
    AutomaticBuyRuntimeContractError,
    AutomaticBuyRuntimeInputV1,
    automatic_buy_idempotency_key_v1,
    validate_runtime_input_v1,
)


def _runtime_input(now: datetime) -> AutomaticBuyRuntimeInputV1:
    return AutomaticBuyRuntimeInputV1(
        automatic_buy_runtime_input_id=1,
        source_snapshot_key="a" * 64,
        input_contract_version="1",
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
        setup_observed_ts_utc=now - timedelta(seconds=5),
        account_observed_ts_utc=now - timedelta(seconds=4),
        account_enabled=True,
        account_mode="paper",
        automatic_buy_execution_enabled=True,
        free_quote_balance_eur=Decimal("1000"),
        free_quote_balance_observed_ts_utc=now - timedelta(seconds=3),
        blocking_conflict=False,
        proposed_position_amount_eur=Decimal("100"),
        current_bucket_amount_eur=Decimal("0"),
        current_open_positions=0,
        current_asset_exposure_pct=Decimal("0"),
        max_automatic_buy_notional_eur=Decimal("75"),
        source_provenance="test",
    )


def test_runtime_input_validation_accepts_fresh_bound_snapshot() -> None:
    now = datetime(2026, 8, 19, 16, 0, tzinfo=UTC)
    validate_runtime_input_v1(_runtime_input(now), evaluation_ts_utc=now)


def test_runtime_input_validation_fails_closed_on_stale_snapshot() -> None:
    now = datetime(2026, 8, 19, 16, 0, tzinfo=UTC)
    value = _runtime_input(now)
    stale = AutomaticBuyRuntimeInputV1(
        **{**value.__dict__, "setup_observed_ts_utc": now - timedelta(hours=1)}
    )
    with pytest.raises(AutomaticBuyRuntimeContractError, match="STALE_OR_FUTURE"):
        validate_runtime_input_v1(stale, evaluation_ts_utc=now)


def test_idempotency_key_is_order_independent_and_source_bound() -> None:
    evidence = {
        "source_snapshot_key": "a" * 64,
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
        "venue_constraint_identity": {"market": "BTC-EUR", "metadata_synced_ts_utc": "2026-08-19T15:00:00Z"},
    }
    reversed_evidence = dict(reversed(tuple(evidence.items())))
    assert automatic_buy_idempotency_key_v1(evidence) == automatic_buy_idempotency_key_v1(reversed_evidence)

    changed = dict(evidence)
    changed["source_snapshot_key"] = "c" * 64
    assert automatic_buy_idempotency_key_v1(evidence) != automatic_buy_idempotency_key_v1(changed)
