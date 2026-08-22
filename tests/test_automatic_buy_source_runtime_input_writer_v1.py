from __future__ import annotations

import sqlite3
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.entry_policy.automatic_buy_runtime_contract_v1 import RUNTIME_INPUT_LIVE_CONTRACT_VERSION
from src.entry_policy.automatic_buy_source_runtime_input_writer_v1 import (
    AutomaticBuySourceRuntimeInputConflictError,
    AutomaticBuySourceRuntimeInputRequestV1,
    AutomaticBuySourceRuntimeInputWriterError,
    derive_source_snapshot_key_v1,
    write_automatic_buy_source_runtime_input_v1,
)

TS = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)

# Substrings this contract must never carry as a field name: it is source
# evidence only. trading_account_id/asset_id/venue/market/strategy_bucket_id
# ARE permitted -- they are identity used to locate canonical account
# evidence, never account permission/allocation state itself.
FORBIDDEN_ACCOUNT_FIELD_SUBSTRINGS = (
    "account_enabled",
    "account_mode",
    "live_trading",
    "execution_enabled",
    "balance",
    "wallet",
    "exposure",
    "blocking_conflict",
    "proposed_position",
    "bucket_amount",
    "open_positions",
    "protection",
    "credential",
    "broker",
)


class _Cursor:
    def __init__(self, conn: "_Conn") -> None:
        self.conn = conn
        self.lastrowid = 0
        self._row: dict[str, object] | None = None

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        if sql.lstrip().startswith("SELECT"):
            self._row = self.conn.rows.get(str(params[0]))
            return
        assert sql.lstrip().startswith("INSERT")
        snapshot_key = str(params[0])
        if snapshot_key in self.conn.rows:
            raise sqlite3.IntegrityError("duplicate source_snapshot_key")
        self.conn.next_id += 1
        row = {
            "automatic_buy_runtime_input_id": self.conn.next_id,
            "source_snapshot_key": params[0],
            "input_contract_version": params[1],
            "evaluation_ts_utc": params[2],
            "trading_account_id": params[3],
            "venue": params[4],
            "asset_id": params[5],
            "market": params[6],
            "strategy_bucket_id": params[7],
            "strategy_id": params[8],
            "strategy_version": params[9],
            "setup_id": params[10],
            "setup_ready": params[11],
            "current_price": params[12],
            "entry_zone_low": params[13],
            "entry_zone_high": params[14],
            "re_entry_zone_low": params[15],
            "re_entry_zone_high": params[16],
            "setup_evidence_id": params[17],
            "setup_observed_ts_utc": params[18],
            "source_provenance": params[32],
        }
        self.conn.rows[snapshot_key] = row
        self.lastrowid = self.conn.next_id

    def fetchone(self) -> dict[str, object] | None:
        return self._row


class _Conn:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, object]] = {}
        self.next_id = 0

    def cursor(self) -> _Cursor:
        return _Cursor(self)


class _RaceCursor:
    """Simulates a concurrent writer landing between our SELECT and INSERT."""

    def __init__(self, conn: "_RaceConn") -> None:
        self.conn = conn
        self.lastrowid = 0
        self._row: dict[str, object] | None = None

    def __enter__(self) -> "_RaceCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        if sql.lstrip().startswith("SELECT"):
            self.conn.select_calls += 1
            self._row = None if self.conn.select_calls == 1 else self.conn.existing_row
            return
        raise sqlite3.IntegrityError("duplicate source_snapshot_key (race)")

    def fetchone(self) -> dict[str, object] | None:
        return self._row


class _RaceConn:
    def __init__(self, existing_row: dict[str, object]) -> None:
        self.existing_row = existing_row
        self.select_calls = 0

    def cursor(self) -> _RaceCursor:
        return _RaceCursor(self)


def _request(**overrides: object) -> AutomaticBuySourceRuntimeInputRequestV1:
    base = dict(
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
        entry_zone_low=Decimal("95"),
        entry_zone_high=Decimal("105"),
        re_entry_zone_low=None,
        re_entry_zone_high=None,
        setup_evidence_id="ev-1",
        setup_observed_ts_utc=TS,
        source_provenance="test",
    )
    base.update(overrides)
    return AutomaticBuySourceRuntimeInputRequestV1(**base)  # type: ignore[arg-type]


def test_request_contract_carries_no_account_permission_field() -> None:
    field_names = {f.name.lower() for f in fields(AutomaticBuySourceRuntimeInputRequestV1)}
    for forbidden in FORBIDDEN_ACCOUNT_FIELD_SUBSTRINGS:
        assert not any(forbidden in name for name in field_names), forbidden


def test_snapshot_key_is_deterministic_and_content_sensitive() -> None:
    first = derive_source_snapshot_key_v1(_request())
    second = derive_source_snapshot_key_v1(_request())
    assert first == second
    assert len(first) == 64
    changed = derive_source_snapshot_key_v1(_request(current_price=Decimal("101")))
    assert changed != first


def test_write_is_idempotent_for_identical_source_snapshot() -> None:
    conn = _Conn()
    first = write_automatic_buy_source_runtime_input_v1(conn, request=_request())
    second = write_automatic_buy_source_runtime_input_v1(conn, request=_request())
    assert first.automatic_buy_runtime_input_id == second.automatic_buy_runtime_input_id
    assert first.source_snapshot_key == second.source_snapshot_key
    assert len(conn.rows) == 1
    assert first.input_contract_version == RUNTIME_INPUT_LIVE_CONTRACT_VERSION


def test_write_persists_placeholder_account_fields_that_are_always_overwritten_downstream() -> None:
    conn = _Conn()
    written = write_automatic_buy_source_runtime_input_v1(conn, request=_request())
    assert written.account_enabled is False
    assert written.account_mode == "paper"
    assert written.automatic_buy_execution_enabled is False
    assert written.live_trading_enabled is False
    assert written.blocking_conflict is True
    assert written.proposed_position_amount_eur > 0


def test_different_snapshot_produces_a_new_row() -> None:
    conn = _Conn()
    write_automatic_buy_source_runtime_input_v1(conn, request=_request())
    write_automatic_buy_source_runtime_input_v1(conn, request=_request(current_price=Decimal("102")))
    assert len(conn.rows) == 2


def test_race_insert_recovers_idempotently_when_existing_content_matches() -> None:
    request = _request()
    matching_row = {
        "automatic_buy_runtime_input_id": 9,
        "source_snapshot_key": derive_source_snapshot_key_v1(request),
        "input_contract_version": RUNTIME_INPUT_LIVE_CONTRACT_VERSION,
        "evaluation_ts_utc": request.evaluation_ts_utc,
        "trading_account_id": request.trading_account_id,
        "venue": request.venue,
        "asset_id": request.asset_id,
        "market": request.market,
        "strategy_bucket_id": request.strategy_bucket_id,
        "strategy_id": request.strategy_id,
        "strategy_version": request.strategy_version,
        "setup_id": request.setup_id,
        "setup_ready": request.setup_ready,
        "current_price": request.current_price,
        "entry_zone_low": request.entry_zone_low,
        "entry_zone_high": request.entry_zone_high,
        "re_entry_zone_low": request.re_entry_zone_low,
        "re_entry_zone_high": request.re_entry_zone_high,
        "setup_evidence_id": request.setup_evidence_id,
        "setup_observed_ts_utc": request.setup_observed_ts_utc,
        "source_provenance": request.source_provenance,
    }
    conn = _RaceConn(matching_row)
    result = write_automatic_buy_source_runtime_input_v1(conn, request=request)
    assert result.automatic_buy_runtime_input_id == 9


def test_conflicting_replay_under_same_key_fails_closed() -> None:
    request = _request()
    mismatched_row = {
        "automatic_buy_runtime_input_id": 9,
        "source_snapshot_key": derive_source_snapshot_key_v1(request),
        "input_contract_version": RUNTIME_INPUT_LIVE_CONTRACT_VERSION,
        "evaluation_ts_utc": request.evaluation_ts_utc,
        "trading_account_id": request.trading_account_id,
        "venue": request.venue,
        "asset_id": request.asset_id,
        "market": request.market,
        "strategy_bucket_id": request.strategy_bucket_id,
        "strategy_id": request.strategy_id,
        "strategy_version": request.strategy_version,
        "setup_id": request.setup_id,
        "setup_ready": request.setup_ready,
        "current_price": Decimal("999"),  # mismatched vs. request.current_price
        "entry_zone_low": request.entry_zone_low,
        "entry_zone_high": request.entry_zone_high,
        "re_entry_zone_low": request.re_entry_zone_low,
        "re_entry_zone_high": request.re_entry_zone_high,
        "setup_evidence_id": request.setup_evidence_id,
        "setup_observed_ts_utc": request.setup_observed_ts_utc,
        "source_provenance": request.source_provenance,
    }
    conn = _RaceConn(mismatched_row)
    with pytest.raises(AutomaticBuySourceRuntimeInputConflictError):
        write_automatic_buy_source_runtime_input_v1(conn, request=request)


@pytest.mark.parametrize(
    "overrides",
    [
        {"trading_account_id": 0},
        {"asset_id": -1},
        {"current_price": Decimal("0")},
        {"venue": ""},
        {"entry_zone_low": Decimal("-1")},
        {"entry_zone_low": Decimal("110"), "entry_zone_high": Decimal("100")},
    ],
)
def test_invalid_requests_are_rejected_before_any_db_write(overrides: dict[str, object]) -> None:
    conn = _Conn()
    with pytest.raises(AutomaticBuySourceRuntimeInputWriterError):
        write_automatic_buy_source_runtime_input_v1(conn, request=_request(**overrides))
    assert conn.rows == {}


def test_stale_setup_observation_is_rejected() -> None:
    conn = _Conn()
    stale_request = _request(setup_observed_ts_utc=TS - timedelta(hours=1))
    with pytest.raises(AutomaticBuySourceRuntimeInputWriterError):
        write_automatic_buy_source_runtime_input_v1(conn, request=stale_request)


def test_future_setup_observation_is_rejected() -> None:
    conn = _Conn()
    future_request = _request(setup_observed_ts_utc=TS + timedelta(minutes=5))
    with pytest.raises(AutomaticBuySourceRuntimeInputWriterError):
        write_automatic_buy_source_runtime_input_v1(conn, request=future_request)


def test_naive_timestamps_are_rejected() -> None:
    conn = _Conn()
    with pytest.raises(AutomaticBuySourceRuntimeInputWriterError):
        write_automatic_buy_source_runtime_input_v1(
            conn, request=_request(evaluation_ts_utc=datetime(2026, 8, 22, 12, 0)),
        )
