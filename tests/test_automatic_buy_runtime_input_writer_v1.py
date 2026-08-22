from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.entry_policy.automatic_buy_runtime_input_writer_v1 import (
    AutomaticBuyRuntimeInputSourceV1,
    AutomaticBuyRuntimeInputWriteError,
    write_automatic_buy_runtime_input_v1,
)


def _source(**changes: object) -> AutomaticBuyRuntimeInputSourceV1:
    now = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
    values: dict[str, object] = {
        "source_snapshot_key": "a" * 64, "input_contract_version": "2", "evaluation_ts_utc": now,
        "trading_account_id": 3, "venue": "bitvavo", "asset_id": 42, "market": "BTC-EUR",
        "strategy_bucket_id": "SHORT_TERM_ROTATION", "strategy_id": "strategy-a", "strategy_version": "1",
        "setup_id": "setup-1", "setup_ready": True, "current_price": Decimal("100"),
        "entry_zone_low": Decimal("99"), "entry_zone_high": Decimal("101"), "re_entry_zone_low": None,
        "re_entry_zone_high": None, "setup_evidence_id": "evidence-1", "setup_observed_ts_utc": now,
        "account_observed_ts_utc": now, "account_enabled": True, "account_mode": "live",
        "automatic_buy_execution_enabled": True, "free_quote_balance_eur": Decimal("1000"),
        "free_quote_balance_observed_ts_utc": now, "blocking_conflict": False,
        "proposed_position_amount_eur": Decimal("100"), "current_bucket_amount_eur": Decimal("0"),
        "current_open_positions": 0, "current_asset_exposure_pct": Decimal("0"),
        "max_automatic_buy_notional_eur": Decimal("75"), "source_provenance": "test",
        "live_trading_enabled": False,
    }
    values.update(changes)
    return AutomaticBuyRuntimeInputSourceV1(**values)  # type: ignore[arg-type]


class Cursor:
    def __init__(self, conn: "Conn") -> None:
        self.conn, self.lastrowid, self.row = conn, 0, None

    def __enter__(self) -> "Cursor":
        return self

    def __exit__(self, *args: object) -> bool:
        return False

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        if sql.startswith("SELECT"):
            self.row = self.conn.rows.get(str(params[0]))
            return
        source = self.conn.pending_source
        assert sql.startswith("INSERT INTO automatic_buy_runtime_input_v1") and source is not None
        self.lastrowid = 1
        self.conn.rows[source.source_snapshot_key] = source.as_runtime_input(
            automatic_buy_runtime_input_id=1,
        ).__dict__

    def fetchone(self):
        return self.row


class Conn:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, object]] = {}
        self.pending_source: AutomaticBuyRuntimeInputSourceV1 | None = None

    def cursor(self) -> Cursor:
        return Cursor(self)


def _write(conn: Conn, source: AutomaticBuyRuntimeInputSourceV1):
    conn.pending_source = source
    return write_automatic_buy_runtime_input_v1(conn, source=source)


def test_v2_source_writer_is_immutable_idempotent_and_conflict_safe() -> None:
    conn = Conn()
    source = _source()
    first = _write(conn, source)
    second = _write(conn, source)
    assert first.outcome == "inserted"
    assert first.runtime_input.input_contract_version == "2"
    assert first.runtime_input.live_trading_enabled is False
    assert second.outcome == "idempotent_existing"
    assert second.runtime_input == first.runtime_input
    with pytest.raises(AutomaticBuyRuntimeInputWriteError, match="IDENTITY_CONFLICT"):
        _write(conn, _source(current_price=Decimal("101")))
