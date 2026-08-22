"""Issue #471 writer tests: immutability, idempotency, and fail-closed replay.

Uses the shared Issue #474 sqlite fixtures (already model
``automatic_buy_runtime_input_v1``). No executor/broker import.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from src.entry_policy.automatic_buy_runtime_contract_v1 import RUNTIME_INPUT_LIVE_CONTRACT_VERSION
from src.entry_policy.automatic_buy_runtime_input_writer_v1 import (
    AutomaticBuyRuntimeInputWriteError,
    AutomaticBuySourceEvidenceV1,
    write_automatic_buy_runtime_input_v1,
)
from tests.automatic_buy_account_allocation_evidence_fixtures_v1 import TS, FakeConnection


def _source(**overrides: object) -> AutomaticBuySourceEvidenceV1:
    base = dict(
        source_snapshot_key="a" * 64,
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
        current_price=Decimal("50000"),
        entry_zone_low=Decimal("49000"),
        entry_zone_high=Decimal("51000"),
        re_entry_zone_low=None,
        re_entry_zone_high=None,
        setup_evidence_id="ev-1",
        setup_observed_ts_utc=TS,
        source_provenance="test_producer",
    )
    base.update(overrides)
    return AutomaticBuySourceEvidenceV1(**base)


def test_source_evidence_dataclass_has_no_account_owned_field() -> None:
    forbidden = {
        "account_enabled", "account_mode", "live_trading_enabled",
        "automatic_buy_execution_enabled", "free_quote_balance_eur",
        "proposed_position_amount_eur", "current_bucket_amount_eur",
        "current_open_positions", "current_asset_exposure_pct",
        "max_automatic_buy_notional_eur", "account_observed_ts_utc",
        "free_quote_balance_observed_ts_utc", "blocking_conflict",
    }
    field_names = {f.name for f in AutomaticBuySourceEvidenceV1.__dataclass_fields__.values()}
    assert field_names.isdisjoint(forbidden)


def test_write_inserts_new_snapshot_and_binds_contract_v2() -> None:
    conn = FakeConnection()
    result = write_automatic_buy_runtime_input_v1(conn, source=_source())
    assert result.outcome == "inserted"
    assert result.runtime_input.automatic_buy_runtime_input_id > 0
    assert result.runtime_input.input_contract_version == RUNTIME_INPUT_LIVE_CONTRACT_VERSION
    assert result.runtime_input.source_snapshot_key == "a" * 64
    # Account-owned columns are placeholders only; never trusted by callers.
    assert result.runtime_input.account_mode == "paper"
    assert result.runtime_input.automatic_buy_execution_enabled is True
    assert result.runtime_input.live_trading_enabled is False


def test_replay_with_identical_source_is_idempotent_no_duplicate_row() -> None:
    conn = FakeConnection()
    first = write_automatic_buy_runtime_input_v1(conn, source=_source())
    second = write_automatic_buy_runtime_input_v1(conn, source=_source())
    assert second.outcome == "idempotent_existing"
    assert second.runtime_input.automatic_buy_runtime_input_id == first.runtime_input.automatic_buy_runtime_input_id
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM automatic_buy_runtime_input_v1")
        row = cur.fetchone()
    assert row["n"] == 1


def test_conflicting_replay_with_same_key_different_evidence_fails_closed() -> None:
    conn = FakeConnection()
    write_automatic_buy_runtime_input_v1(conn, source=_source())
    with pytest.raises(AutomaticBuyRuntimeInputWriteError, match="AUTOMATIC_BUY_RUNTIME_INPUT_IDENTITY_CONFLICT"):
        write_automatic_buy_runtime_input_v1(
            conn, source=_source(current_price=Decimal("60000")),
        )
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM automatic_buy_runtime_input_v1")
        row = cur.fetchone()
    assert row["n"] == 1


def test_different_source_snapshot_key_writes_a_second_row() -> None:
    conn = FakeConnection()
    write_automatic_buy_runtime_input_v1(conn, source=_source())
    second = write_automatic_buy_runtime_input_v1(conn, source=_source(source_snapshot_key="b" * 64))
    assert second.outcome == "inserted"
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM automatic_buy_runtime_input_v1")
        row = cur.fetchone()
    assert row["n"] == 2


def test_stale_setup_evidence_is_rejected_before_any_write() -> None:
    conn = FakeConnection()
    with pytest.raises(AutomaticBuyRuntimeInputWriteError):
        write_automatic_buy_runtime_input_v1(
            conn, source=_source(setup_observed_ts_utc=TS - timedelta(hours=1)),
        )
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM automatic_buy_runtime_input_v1")
        row = cur.fetchone()
    assert row["n"] == 0


def test_non_positive_price_is_rejected() -> None:
    conn = FakeConnection()
    with pytest.raises(AutomaticBuyRuntimeInputWriteError):
        write_automatic_buy_runtime_input_v1(conn, source=_source(current_price=Decimal("0")))
