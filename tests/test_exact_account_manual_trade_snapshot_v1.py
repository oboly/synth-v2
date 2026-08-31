from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from src.account.exact_account_position_snapshot_v1 import (
    AssetIdentityV1,
    build_exact_position_rows,
)
from src.execution_capability.execution_capability_v1 import EXECUTION_MODE_MANUAL_RFQ
from src.operations.run_broker_account_position_snapshot_writer_v1 import BalanceRow, TradingAccount


def test_manual_asset_without_market_can_become_position_evidence() -> None:
    account = TradingAccount(
        trading_account_id=5,
        account_code="bitvavo_joost_live",
        venue="bitvavo",
        account_mode="live",
        enabled=1,
        live_trading_enabled=1,
    )
    balances = {
        "MDT": BalanceRow(
            currency_code="MDT",
            available_amount=Decimal("42"),
            reserved_amount=Decimal("0"),
            total_amount=Decimal("42"),
            snapshot_ts_utc="2026-08-31 15:00:00",
        )
    }
    assets = {
        "MDT": AssetIdentityV1(
            asset_id=999,
            symbol="MDT",
            execution_mode=EXECUTION_MODE_MANUAL_RFQ,
        )
    }

    rows, missing = build_exact_position_rows(
        balances=balances,
        assets=assets,
        prices={},
        account=account,
        balance_snapshot_ts_utc="2026-08-31 15:00:00",
    )

    assert missing == []
    assert len(rows) == 1
    assert rows[0].mark_price_eur is None
    payload = json.loads(rows[0].raw_json)
    assert payload["execution_mode"] == "MANUAL_RFQ"
    assert payload["manual_trade"] is True
    assert payload["automated_execution_eligible"] is False
    assert payload["execution_disposition"] == "MANUAL_ACTION_REQUIRED"
    assert payload["broker_submission"] is False
    assert payload["live_trading_enabled"] is True


def test_missing_canonical_identity_still_fails_closed_at_derivation_boundary() -> None:
    account = TradingAccount(5, "live", "bitvavo", "live", 1, 1)
    balances = {
        "UNKNOWN": BalanceRow("UNKNOWN", Decimal("1"), Decimal("0"), Decimal("1"), "ts")
    }
    rows, missing = build_exact_position_rows(
        balances=balances,
        assets={},
        prices={},
        account=account,
        balance_snapshot_ts_utc="ts",
    )
    assert rows == []
    assert missing == ["UNKNOWN"]


def test_manual_registration_does_not_create_venue_market() -> None:
    src = Path("src/market/run_manual_trade_asset_registration_v1.py").read_text()
    assert "INSERT INTO venue_market" not in src
    assert "UPDATE venue_market" not in src
    assert "venue_market_writes=0" in src


def test_schema_defaults_existing_assets_to_automated() -> None:
    migration = Path("db/migrations/20260831_asset_execution_mode_v1.sql").read_text()
    assert "DEFAULT 'AUTOMATED'" in migration
    assert "'MANUAL_RFQ'" in migration
    assert "'MANUAL'" in migration
    assert "'NONE'" in migration
