"""
Tests for src/manual_execution/manual_execution_request_v1.py.

Pure Python construction/validation/state-machine tests, plus an in-memory
fake-DB integration test for the repository (no real MariaDB, no network),
matching the pattern in tests/test_sell_reservation_v1.py.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.manual_execution.manual_execution_request_v1 import (
    MODE_LIVE,
    MODE_PAPER,
    QUANTITY_POLICY_FIXED_BASE_QUANTITY,
    QUANTITY_POLICY_FULL_AVAILABLE_BASE,
    QUANTITY_POLICY_LADDER_LEVELS,
    REQUEST_STATE_DRAFT,
    REQUEST_STATE_GATE_BLOCKED,
    REQUEST_STATE_PLANNED,
    SOURCE_OPERATOR_CLI,
    InvalidManualExecutionRequestTransitionError,
    ManualExecutionRequestRepository,
    ManualExecutionRequestValidationError,
    advance_manual_execution_request_state,
    build_manual_execution_request,
)


NOW = datetime(2026, 7, 26, 12, 0, 0, tzinfo=timezone.utc)


def _build(**overrides):
    defaults = dict(
        idempotency_key="req-btc-eur-sell-0001",
        created_ts_utc=NOW,
        source=SOURCE_OPERATOR_CLI,
        requested_by="joost",
        mode=MODE_PAPER,
        trading_account_id=1,
        account_code="paper_sell_only_preview",
        venue="bitvavo",
        asset_id=42,
        base_asset="BTC",
        quote_asset="EUR",
        side="SELL",
        quantity_policy=QUANTITY_POLICY_FULL_AVAILABLE_BASE,
    )
    defaults.update(overrides)
    return build_manual_execution_request(**defaults)


class TestConstructionGuardsIntent:
    def test_full_available_base_request_builds(self) -> None:
        request = _build()
        assert request.request_state == REQUEST_STATE_DRAFT
        assert request.request_id is None
        assert request.requested_base_quantity is None
        assert request.venue == "bitvavo"
        assert request.base_asset == "BTC"

    def test_fixed_base_quantity_request_builds(self) -> None:
        request = _build(
            quantity_policy=QUANTITY_POLICY_FIXED_BASE_QUANTITY,
            requested_base_quantity=Decimal("0.5"),
        )
        assert request.requested_base_quantity == Decimal("0.5")

    def test_ladder_levels_request_builds(self) -> None:
        request = _build(
            quantity_policy=QUANTITY_POLICY_LADDER_LEVELS,
            ladder_levels=((Decimal("50000"), Decimal("0.5")), (Decimal("52000"), Decimal("0.5"))),
            ladder_profile_id=7,
            ladder_profile_version=1,
            anchor_reference_price=Decimal("51000"),
            anchor_ts_utc=NOW,
        )
        assert len(request.ladder_levels) == 2
        assert request.ladder_profile_id == 7
        assert request.ladder_profile_version == 1

    def test_ladder_levels_without_profile_binding_rejected(self) -> None:
        with pytest.raises(ManualExecutionRequestValidationError):
            _build(
                quantity_policy=QUANTITY_POLICY_LADDER_LEVELS,
                ladder_levels=((Decimal("50000"), Decimal("1")),),
            )

    def test_non_ladder_policy_with_profile_binding_rejected(self) -> None:
        with pytest.raises(ManualExecutionRequestValidationError):
            _build(ladder_profile_id=7, ladder_profile_version=1)

    def test_unknown_source_rejected(self) -> None:
        with pytest.raises(ManualExecutionRequestValidationError):
            _build(source="SOME_RANDOM_SOURCE")

    def test_unknown_mode_rejected(self) -> None:
        with pytest.raises(ManualExecutionRequestValidationError):
            _build(mode="SANDBOX")

    def test_unknown_side_rejected(self) -> None:
        with pytest.raises(ManualExecutionRequestValidationError):
            _build(side="HOLD")

    def test_unknown_quantity_policy_rejected(self) -> None:
        with pytest.raises(ManualExecutionRequestValidationError):
            _build(quantity_policy="MARKET_ORDER_ALL")

    def test_full_available_base_with_quantity_rejected(self) -> None:
        with pytest.raises(ManualExecutionRequestValidationError):
            _build(
                quantity_policy=QUANTITY_POLICY_FULL_AVAILABLE_BASE,
                requested_base_quantity=Decimal("1"),
            )

    def test_fixed_base_quantity_without_quantity_rejected(self) -> None:
        with pytest.raises(ManualExecutionRequestValidationError):
            _build(quantity_policy=QUANTITY_POLICY_FIXED_BASE_QUANTITY)

    def test_fixed_base_quantity_nonpositive_rejected(self) -> None:
        with pytest.raises(ManualExecutionRequestValidationError):
            _build(
                quantity_policy=QUANTITY_POLICY_FIXED_BASE_QUANTITY,
                requested_base_quantity=Decimal("0"),
            )

    def test_ladder_levels_empty_rejected(self) -> None:
        with pytest.raises(ManualExecutionRequestValidationError):
            _build(quantity_policy=QUANTITY_POLICY_LADDER_LEVELS, ladder_levels=())

    def test_ladder_levels_nonpositive_price_rejected(self) -> None:
        with pytest.raises(ManualExecutionRequestValidationError):
            _build(
                quantity_policy=QUANTITY_POLICY_LADDER_LEVELS,
                ladder_levels=((Decimal("0"), Decimal("1")),),
            )

    def test_empty_idempotency_key_rejected(self) -> None:
        with pytest.raises(ManualExecutionRequestValidationError):
            _build(idempotency_key="   ")

    def test_zero_trading_account_id_rejected(self) -> None:
        with pytest.raises(ManualExecutionRequestValidationError):
            _build(trading_account_id=0)


class TestUntrustedFieldsCannotBeSupplied:
    """The dataclass/constructor has no field for any of these, so passing
    them raises TypeError before validation ever runs."""

    def test_free_base_quantity_kwarg_rejected(self) -> None:
        with pytest.raises(TypeError):
            _build(free_base_quantity=Decimal("999"))

    def test_decision_state_kwarg_rejected(self) -> None:
        with pytest.raises(TypeError):
            _build(decision_state="EXECUTION_ALLOWED")

    def test_approved_kwarg_rejected(self) -> None:
        with pytest.raises(TypeError):
            _build(approved=True)

    def test_tick_size_kwarg_rejected(self) -> None:
        with pytest.raises(TypeError):
            _build(tick_size=Decimal("0.01"))

    def test_amount_step_kwarg_rejected(self) -> None:
        with pytest.raises(TypeError):
            _build(amount_step=Decimal("0.00000001"))

    def test_min_notional_kwarg_rejected(self) -> None:
        with pytest.raises(TypeError):
            _build(min_notional=Decimal("5"))

    def test_broker_order_id_kwarg_rejected(self) -> None:
        with pytest.raises(TypeError):
            _build(broker_order_id="ORDER-123")


class TestStateMachine:
    def test_advance_from_draft_to_gate_blocked(self) -> None:
        request = _build()
        advanced = advance_manual_execution_request_state(
            request,
            new_state=REQUEST_STATE_GATE_BLOCKED,
            processed_ts_utc=NOW,
            rejection_code="ACCOUNT_DISABLED",
            rejection_detail="ACCOUNT_DISABLED",
        )
        assert advanced.request_state == REQUEST_STATE_GATE_BLOCKED
        assert advanced.rejection_code == "ACCOUNT_DISABLED"
        # content fields untouched
        assert advanced.idempotency_key == request.idempotency_key
        assert advanced.side == request.side
        assert advanced.trading_account_id == request.trading_account_id

    def test_advance_from_draft_to_planned(self) -> None:
        request = _build()
        advanced = advance_manual_execution_request_state(
            request, new_state=REQUEST_STATE_PLANNED, processed_ts_utc=NOW
        )
        assert advanced.request_state == REQUEST_STATE_PLANNED

    def test_double_advance_rejected(self) -> None:
        request = _build()
        advanced = advance_manual_execution_request_state(
            request, new_state=REQUEST_STATE_GATE_BLOCKED, processed_ts_utc=NOW
        )
        with pytest.raises(InvalidManualExecutionRequestTransitionError):
            advance_manual_execution_request_state(
                advanced, new_state=REQUEST_STATE_PLANNED, processed_ts_utc=NOW
            )

    def test_unknown_target_state_rejected(self) -> None:
        request = _build()
        with pytest.raises(InvalidManualExecutionRequestTransitionError):
            advance_manual_execution_request_state(
                request, new_state="SUBMITTED", processed_ts_utc=NOW
            )


class TestPaperAndLiveShareOneContract:
    def test_paper_and_live_requests_are_the_same_type_with_only_mode_differing(self) -> None:
        paper_request = _build(mode=MODE_PAPER, idempotency_key="req-mode-paper")
        live_request = _build(mode=MODE_LIVE, idempotency_key="req-mode-live")

        assert type(paper_request) is type(live_request)
        assert paper_request.mode == MODE_PAPER
        assert live_request.mode == MODE_LIVE
        # every other field constructed identically
        assert paper_request.side == live_request.side
        assert paper_request.trading_account_id == live_request.trading_account_id


class _FakeCursor:
    def __init__(self, table: list[dict]) -> None:
        self._table = table
        self.lastrowid: int | None = None
        self.rowcount: int = 0

    def execute(self, sql: str, params: list) -> None:
        sql_norm = " ".join(sql.split())

        if sql_norm.startswith("SELECT * FROM manual_execution_request WHERE idempotency_key"):
            (idempotency_key,) = params
            self._result = [dict(r) for r in self._table if r["idempotency_key"] == idempotency_key]
            return

        if sql_norm.startswith("INSERT INTO manual_execution_request"):
            (
                schema_version, idempotency_key, created_ts_utc, source, requested_by,
                mode, trading_account_id, account_code, venue, asset_id, base_asset,
                quote_asset, side, quantity_policy, requested_base_quantity,
                requested_quote_notional, ladder_levels_json, provenance_id,
                ladder_profile_id, ladder_profile_version, anchor_reference_price,
                anchor_ts_utc, request_state,
            ) = params
            new_id = len(self._table) + 1
            row = {
                "manual_execution_request_id": new_id,
                "schema_version": schema_version,
                "idempotency_key": idempotency_key,
                "created_ts_utc": created_ts_utc,
                "source": source,
                "requested_by": requested_by,
                "mode": mode,
                "trading_account_id": trading_account_id,
                "account_code": account_code,
                "venue": venue,
                "asset_id": asset_id,
                "base_asset": base_asset,
                "quote_asset": quote_asset,
                "side": side,
                "quantity_policy": quantity_policy,
                "requested_base_quantity": requested_base_quantity,
                "requested_quote_notional": requested_quote_notional,
                "ladder_levels_json": ladder_levels_json,
                "provenance_id": provenance_id,
                "ladder_profile_id": ladder_profile_id,
                "ladder_profile_version": ladder_profile_version,
                "anchor_reference_price": anchor_reference_price,
                "anchor_ts_utc": anchor_ts_utc,
                "request_state": request_state,
                "rejection_code": None,
                "rejection_detail": None,
                "processed_ts_utc": None,
            }
            self._table.append(row)
            self.lastrowid = new_id
            return

        if sql_norm.startswith("SELECT * FROM manual_execution_request WHERE manual_execution_request_id"):
            (request_id,) = params
            self._result = [
                dict(r) for r in self._table if r["manual_execution_request_id"] == request_id
            ]
            return

        if sql_norm.startswith("UPDATE manual_execution_request"):
            request_state, processed_ts_utc, rejection_code, rejection_detail, request_id = params
            self.rowcount = 0
            for r in self._table:
                if r["manual_execution_request_id"] == request_id:
                    r["request_state"] = request_state
                    r["processed_ts_utc"] = processed_ts_utc
                    r["rejection_code"] = rejection_code
                    r["rejection_detail"] = rejection_detail
                    self.rowcount = 1
            return

        raise AssertionError(f"unexpected SQL in fake cursor: {sql_norm}")

    def fetchone(self):
        return self._result[0] if self._result else None

    def fetchall(self):
        return self._result

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeCursorFactory:
    def __init__(self) -> None:
        self.table: list[dict] = []

    def __call__(self, *, commit: bool = False, database: str | None = None):
        return _FakeCursor(self.table)


class TestRepositoryFakeDb:
    def test_create_request_idempotent_then_retry_returns_same_row(self) -> None:
        factory = _FakeCursorFactory()
        repo = ManualExecutionRequestRepository(cursor_factory=factory)
        request = _build()

        first = repo.create_request_idempotent(request)
        assert first.request_id == 1
        assert first.request_state == REQUEST_STATE_DRAFT

        second = repo.create_request_idempotent(request)
        assert second.request_id == first.request_id
        assert len(factory.table) == 1

    def test_update_request_state_persists(self) -> None:
        factory = _FakeCursorFactory()
        repo = ManualExecutionRequestRepository(cursor_factory=factory)
        request = _build()
        persisted = repo.create_request_idempotent(request)

        blocked = advance_manual_execution_request_state(
            persisted,
            new_state=REQUEST_STATE_GATE_BLOCKED,
            processed_ts_utc=NOW,
            rejection_code="ACCOUNT_DISABLED",
            rejection_detail="ACCOUNT_DISABLED",
        )
        repo.update_request_state(blocked)

        assert factory.table[0]["request_state"] == REQUEST_STATE_GATE_BLOCKED
        assert factory.table[0]["rejection_code"] == "ACCOUNT_DISABLED"
