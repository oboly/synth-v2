from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.entry_policy.automatic_buy_runtime_repository_v1 import _row_to_input


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
