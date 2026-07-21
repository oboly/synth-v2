from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

import pytest

from src.decision_gate.permission_evidence_v1 import PRODUCER_NAME
from src.execution_planner import repository as repository_module
from src.execution_planner.models import PlannedExecution
from src.execution_planner.repository import ExecutionPlannerRepository


def _plan(**overrides: Any) -> PlannedExecution:
    values: dict[str, Any] = {
        "account_id": 999,
        "asset_id": 42,
        "sleeve_code": "CORE",
        "venue": "bitvavo",
        "side": "BUY",
        "desired_action": "SPREAD_CAPTURE_PASSIVE",
        "execution_intent": "PLACE_PASSIVE_LIMIT",
        "execution_mode": "LIVE",
        "plan_ts_utc": datetime(2026, 7, 21, 12, 0, 0),
        "valid_until_ts_utc": datetime(2026, 7, 21, 12, 5, 0),
        "target_fraction": Decimal("0.10"),
        "max_notional_eur": Decimal("25"),
        "reference_price_eur": Decimal("100"),
        "passive_price_eur": Decimal("99"),
        "urgent_limit_price_eur": Decimal("101"),
        "max_reprices": 0,
        "max_wait_seconds": 300,
        "max_chase_bps": Decimal("0"),
        "min_spread_bps_for_capture": Decimal("3"),
        "escalation_to_urgent_limit": False,
        "abort_if_signal_invalidates": True,
        "plan_state": "IDLE",
        "notes": "test",
        "market": "BTC-EUR",
        "trading_account_id": 7,
        "decision_gate_permission_evidence_id": 11,
        "action_type": "PLACE_ORDER",
        "requested_side": "BUY",
    }
    values.update(overrides)
    return PlannedExecution(**values)


class Cursor:
    def __init__(self, found: bool) -> None:
        self.found = found
        self.params: tuple[Any, ...] | None = None

    def execute(self, _sql: str, params: tuple[Any, ...]) -> None:
        self.params = tuple(params)

    def fetchone(self) -> dict[str, Any] | None:
        if not self.found:
            return None
        return {
            "decision_gate_permission_evidence_id": 11,
            "decision_gate_audit_log_id": 9,
            "producer_name": PRODUCER_NAME,
            "provenance_signature": "signed",
            "trading_account_id": 7,
            "venue": "bitvavo",
            "asset_id": 42,
            "market": "BTC-EUR",
            "execution_intent": "PLACE_PASSIVE_LIMIT",
            "action_type": "PLACE_ORDER",
            "requested_side": "BUY",
            "permission_state": "EXECUTION_PERMITTED",
            "decision_state": "EXECUTION_ALLOWED",
            "permitted_ts_utc": datetime(2026, 7, 21, 11, 59, 0),
            "valid_until_ts_utc": datetime(2026, 7, 21, 12, 5, 0),
            "audit_trading_account_id": 7,
            "audit_venue": "bitvavo",
            "audit_asset_id": 42,
            "audit_market": "BTC-EUR",
            "audit_execution_intent": "PLACE_PASSIVE_LIMIT",
            "audit_action_type": "PLACE_ORDER",
            "audit_requested_side": "BUY",
            "audit_permission_state": "EXECUTION_PERMITTED",
            "audit_decision_state": "EXECUTION_ALLOWED",
            "audit_execution_mode": "LIVE",
        }


@pytest.fixture(autouse=True)
def _valid_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(repository_module, "verify_provenance_signature", lambda *_: True)


def test_planner_binds_exact_canonical_evidence_and_explicit_trading_account() -> None:
    cursor = Cursor(found=True)
    ExecutionPlannerRepository()._validate_permission_binding(cursor, _plan())
    assert cursor.params == (
        11,
        7,
        "bitvavo",
        42,
        "BTC-EUR",
        "PLACE_PASSIVE_LIMIT",
        "PLACE_ORDER",
        "BUY",
        PRODUCER_NAME,
    )
    assert 999 not in cursor.params


@pytest.mark.parametrize(
    "overrides",
    [
        {"trading_account_id": None},
        {"decision_gate_permission_evidence_id": None},
        {"execution_intent": None},
        {"execution_intent": ""},
        {"requested_side": None},
        {"requested_side": ""},
    ],
)
def test_live_plan_missing_exact_binding_fails_closed(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValueError) as exc_info:
        ExecutionPlannerRepository()._validate_permission_binding(Cursor(True), _plan(**overrides))
    assert str(exc_info.value) == "LIVE_PLAN_PERMISSION_BINDING_INCOMPLETE"


def test_planner_cannot_reference_fabricated_or_mismatched_evidence() -> None:
    with pytest.raises(ValueError) as exc_info:
        ExecutionPlannerRepository()._validate_permission_binding(Cursor(False), _plan())
    assert str(exc_info.value) == "LIVE_PLAN_PERMISSION_BINDING_NOT_CANONICAL"


def test_planner_rejects_evidence_without_valid_decision_gate_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(repository_module, "verify_provenance_signature", lambda *_: False)
    with pytest.raises(ValueError) as exc_info:
        ExecutionPlannerRepository()._validate_permission_binding(Cursor(True), _plan())
    assert str(exc_info.value) == "LIVE_PLAN_PERMISSION_PROVENANCE_INVALID"


def test_paper_plan_does_not_query_permission_evidence() -> None:
    class ForbiddenCursor:
        def execute(self, *_: Any) -> None:
            raise AssertionError("paper plan must not query permission evidence")

    ExecutionPlannerRepository()._validate_permission_binding(
        ForbiddenCursor(),
        _plan(
            execution_mode="PAPER",
            trading_account_id=None,
            decision_gate_permission_evidence_id=None,
            action_type=None,
        ),
    )
