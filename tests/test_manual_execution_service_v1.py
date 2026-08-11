from __future__ import annotations

import dataclasses
import inspect
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.decision_gate import manual_execution_approval_v1 as approval_authority
from src.decision_gate.manual_execution_approval_v1 import (
    APPROVAL_STATE_APPROVED,
    ManualExecutionApprovalRecord,
    PersistedManualExecutionAuthority,
)
from src.decision_gate.manual_execution_gate_v1 import (
    GATE_DECISION_BLOCKED,
    GATE_DECISION_EXECUTION_ALLOWED,
    ManualExecutionApprovalOutcome,
    ManualExecutionGateResult,
)
from src.execution_planner.contract_preview_v1 import (
    ExecutionIntentPreview,
    ExecutionMarketContextPreview,
    ManualSellPlanningInputs,
    MissingOrInvalidApprovalError,
    UnauthorizedManualExecutionCallError,
    build_execution_plan_preview,
    build_manual_sell_execution_plan_preview,
)
from src.manual_execution import _trusted_clock_v1 as trusted_clock
from src.manual_execution import manual_execution_service_v1 as service
from src.manual_execution.manual_execution_request_v1 import (
    MODE_LIVE,
    MODE_PAPER,
    QUANTITY_POLICY_FULL_AVAILABLE_BASE,
    REQUEST_STATE_FAILED,
    REQUEST_STATE_GATE_BLOCKED,
    REQUEST_STATE_PLAN_REJECTED,
    REQUEST_STATE_PLANNED,
    SOURCE_OPERATOR_CLI,
    build_manual_execution_request,
)
from src.market_rules.venue_execution_constraints_v1 import (
    STATUS_FRESH,
    STATUS_STALE,
    VenueExecutionConstraints,
)


NOW = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _fixed_manual_execution_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(trusted_clock, "utc_now", lambda: NOW)


def _request(**overrides):
    values = {
        "idempotency_key": "request-1",
        "created_ts_utc": NOW,
        "source": SOURCE_OPERATOR_CLI,
        "requested_by": "operator",
        "mode": MODE_PAPER,
        "trading_account_id": 1,
        "account_code": "paper",
        "venue": "bitvavo",
        "asset_id": 42,
        "base_asset": "BTC",
        "quote_asset": "EUR",
        "side": "SELL",
        "quantity_policy": QUANTITY_POLICY_FULL_AVAILABLE_BASE,
        "provenance_id": 77,
        "operator_request_nonce": "process-1",
        "ladder_profile_id": 9,
        "ladder_profile_version": 2,
        "anchor_type": "NATIVE_SHORT_ANCHOR_HIGH",
        "anchor_price": Decimal("51000"),
        "anchor_source": "native_short_context_v1",
        "source_map_cycle_id": "cycle-1",
        "source_native_map_id": "map-1",
        "source_map_version": "native_short_v1",
    }
    values.update(overrides)
    return build_manual_execution_request(**values)


def _approval(**overrides) -> ManualExecutionApprovalRecord:
    values = {
        "approval_id": 501,
        "idempotency_key": "manual_execution_approval:request-1",
        "request_id": 1,
        "trading_account_id": 1,
        "account_code": "paper",
        "venue": "bitvavo",
        "asset_id": 42,
        "base_asset": "BTC",
        "quote_asset": "EUR",
        "side": "SELL",
        "approved_quantity_base": Decimal("2"),
        "wallet_snapshot_id": 9001,
        "wallet_snapshot_version_ts_utc": NOW - timedelta(minutes=1),
        "reservation_id": 101,
        "approved_ts_utc": NOW - timedelta(seconds=1),
        "expires_ts_utc": NOW + timedelta(minutes=4),
        "mode": MODE_PAPER,
        "provenance_id": 77,
        "approval_state": APPROVAL_STATE_APPROVED,
        "decision_reason": "OK",
        "persisted_reservation_id": 101,
        "reservation_request_id": 1,
        "reservation_trading_account_id": 1,
        "reservation_venue": "bitvavo",
        "reservation_asset_id": 42,
        "reservation_symbol": "BTC",
        "reservation_quantity_base": Decimal("2"),
        "reservation_state": "APPROVED_NOT_SUBMITTED",
        "persisted_snapshot_id": 9001,
        "snapshot_trading_account_id": 1,
        "snapshot_venue": "bitvavo",
        "snapshot_asset_id": 42,
        "snapshot_ts_utc": NOW - timedelta(minutes=1),
    }
    values.update(overrides)
    return ManualExecutionApprovalRecord(**values)


def _constraints(**overrides):
    values = {
        "venue": "bitvavo",
        "market": "BTC-EUR",
        "tick_size": Decimal("1"),
        "qty_step_size": Decimal("0.00000001"),
        "min_base_quantity": Decimal("0.0001"),
        "min_quote_notional": Decimal("5"),
        "supported_order_types": ("limit",),
        "supported_time_in_force": ("GTC",),
        "source_provenance": "TEST",
        "metadata_synced_ts_utc": NOW,
        "status": STATUS_FRESH,
    }
    values.update(overrides)
    return VenueExecutionConstraints(**values)


def _context():
    return ExecutionMarketContextPreview(
        reference_price_eur=Decimal("50000"),
        best_bid_eur=Decimal("49990"),
        best_ask_eur=Decimal("50010"),
        tick_size=Decimal("999"),
        spread_bps=Decimal("4"),
        volatility_bucket="NORMAL",
        regime_label="RANGE",
    )


def _planning_inputs() -> ManualSellPlanningInputs:
    return ManualSellPlanningInputs(_context(), _constraints(), "CORE_STRUCTURAL")


def _install_authority(
    monkeypatch: pytest.MonkeyPatch,
    *,
    request=None,
    approval=None,
) -> None:
    persisted_request = (
        dataclasses.replace(_request(), request_id=1)
        if request is None
        else request
    )
    persisted_approval = approval or _approval()

    def resolve(*, request_id: int, approval_id: int):
        if request_id != 1:
            raise LookupError("unknown manual execution request_id")
        if approval_id != 501:
            raise LookupError("unknown manual execution approval_id")
        return PersistedManualExecutionAuthority(
            request=persisted_request,
            approval=persisted_approval,
        )

    monkeypatch.setattr(
        approval_authority,
        "resolve_persisted_manual_execution_authority",
        resolve,
    )


class RequestRepository:
    def __init__(self):
        self.request = None
        self.updated = []

    def create_request_idempotent(self, request):
        self.request = dataclasses.replace(request, request_id=1)
        return self.request

    def update_request_state(self, request):
        self.updated.append(request)


class GateRepository:
    def __init__(self, *, blocked: bool = False):
        self.blocked = blocked
        self.calls = 0

    def approve_and_reserve(self, request):
        self.calls += 1
        if self.blocked:
            result = ManualExecutionGateResult(
                decision_state=GATE_DECISION_BLOCKED,
                decision_reason="ACCOUNT_DISABLED",
                blocking_reasons=("ACCOUNT_DISABLED",),
                approved_quantity_base=None,
                free_base_quantity_result=None,
            )
            return ManualExecutionApprovalOutcome(result, None)
        result = ManualExecutionGateResult(
            decision_state=GATE_DECISION_EXECUTION_ALLOWED,
            decision_reason="OK",
            blocking_reasons=(),
            approved_quantity_base=Decimal("2"),
            free_base_quantity_result=None,
        )
        return ManualExecutionApprovalOutcome(result, 501)


class SnapshotRepository:
    def __init__(self):
        self.snapshot = None

    def create_idempotent(self, snapshot):
        self.snapshot = dataclasses.replace(snapshot, plan_snapshot_id=701)
        return self.snapshot

    def find_by_request_id(self, _request_id):
        return self.snapshot


def _install_service_components(
    monkeypatch: pytest.MonkeyPatch,
    *,
    blocked: bool = False,
) -> tuple[RequestRepository, GateRepository]:
    request_repository = RequestRepository()
    gate_repository = GateRepository(blocked=blocked)
    snapshot_repository = SnapshotRepository()
    monkeypatch.setattr(
        service,
        "ManualExecutionRequestRepository",
        lambda: request_repository,
    )
    monkeypatch.setattr(
        service,
        "ManualExecutionGateRepository",
        lambda: gate_repository,
    )
    monkeypatch.setattr(
        service,
        "ManualExecutionPlanSnapshotRepository",
        lambda: snapshot_repository,
    )
    return request_repository, gate_repository


def test_paper_sell_service_uses_non_substitutable_persisted_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_authority(monkeypatch)
    _install_service_components(monkeypatch)

    outcome = service.process(
        _request(),
        market_context=_context(),
        venue_constraints=_constraints(),
        sleeve_code="CORE_STRUCTURAL",
    )

    assert outcome.request.request_state == REQUEST_STATE_PLANNED
    assert outcome.approval_id == 501
    assert outcome.plan_preview is not None
    assert outcome.plan_preview.quantity_base == Decimal("2")
    assert outcome.plan_preview.execution_mode == MODE_PAPER


def test_gate_block_and_stale_constraints_never_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_authority(monkeypatch)
    _install_service_components(monkeypatch, blocked=True)
    blocked = service.process(
        _request(),
        market_context=_context(),
        venue_constraints=_constraints(),
        sleeve_code="CORE_STRUCTURAL",
    )
    assert blocked.request.request_state == REQUEST_STATE_GATE_BLOCKED
    assert blocked.plan_preview is None

    _, gate = _install_service_components(monkeypatch)
    stale = service.process(
        _request(idempotency_key="stale"),
        market_context=_context(),
        venue_constraints=_constraints(status=STATUS_STALE),
        sleeve_code="CORE_STRUCTURAL",
    )
    assert stale.request.request_state == REQUEST_STATE_PLAN_REJECTED
    assert gate.calls == 0


def test_live_request_fails_before_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, gate = _install_service_components(monkeypatch)
    outcome = service.process(
        _request(mode=MODE_LIVE, idempotency_key="live"),
        market_context=_context(),
        venue_constraints=_constraints(),
        sleeve_code="CORE_STRUCTURAL",
    )
    assert outcome.request.request_state == REQUEST_STATE_FAILED
    assert gate.calls == 0


@pytest.mark.parametrize("intent_type", ["EXIT_PASSIVE_LIMIT", "EXIT_LADDER"])
def test_direct_exit_aliases_fail(intent_type: str) -> None:
    intent = ExecutionIntentPreview(
        account_id=1,
        sleeve_code="CORE_STRUCTURAL",
        asset_id=42,
        symbol="BTC",
        venue="bitvavo",
        side="SELL",
        intent_type=intent_type,
        max_notional_eur=None,
        quantity_base=Decimal("2"),
        decision_state="EXECUTION_ALLOWED",
        decision_reason="CALLER",
        ladder_levels=((Decimal("50000"), Decimal("1")),),
    )
    with pytest.raises(UnauthorizedManualExecutionCallError):
        build_execution_plan_preview(intent=intent, context=_context())


def test_guessed_approval_id_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_authority(monkeypatch)
    with pytest.raises(MissingOrInvalidApprovalError, match="unknown"):
        build_manual_sell_execution_plan_preview(
            request_id=1,
            approval_id=999,
            planning_inputs=_planning_inputs(),
        )


def test_caller_created_approval_and_fake_repository_cannot_reach_planner() -> None:
    class FakeApprovalRepository:
        def find_approval_by_id(self, _approval_id):
            return _approval()

    with pytest.raises(TypeError):
        build_manual_sell_execution_plan_preview(
            request_id=1,
            approval_id=501,
            planning_inputs=_planning_inputs(),
            approval=_approval(),  # type: ignore[call-arg]
        )
    with pytest.raises(TypeError):
        build_manual_sell_execution_plan_preview(
            request_id=1,
            approval_id=501,
            planning_inputs=_planning_inputs(),
            approval_repository=FakeApprovalRepository(),  # type: ignore[call-arg]
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"idempotency_key": "manual_execution_approval:other-request"},
        {"request_id": 2},
        {"trading_account_id": 2},
        {"account_code": "other"},
        {"venue": "other"},
        {"base_asset": "ETH"},
        {"quote_asset": "USD"},
        {"side": "BUY"},
        {"mode": MODE_LIVE},
        {"provenance_id": 78},
        {"approval_state": "REVOKED"},
        {"expires_ts_utc": NOW},
        {"expires_ts_utc": NOW + timedelta(minutes=20)},
        {"reservation_id": 102},
        {"reservation_request_id": 2},
        {"reservation_quantity_base": Decimal("1")},
        {"reservation_state": "OPEN"},
        {"wallet_snapshot_id": 9002},
        {"snapshot_trading_account_id": 2},
        {"snapshot_ts_utc": NOW - timedelta(minutes=2)},
    ],
)
def test_all_persisted_bindings_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    changes: dict[str, object],
) -> None:
    _install_authority(monkeypatch, approval=_approval(**changes))
    with pytest.raises(MissingOrInvalidApprovalError):
        build_manual_sell_execution_plan_preview(
            request_id=1,
            approval_id=501,
            planning_inputs=_planning_inputs(),
        )


def test_resolver_returned_identity_mismatch_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_authority(
        monkeypatch,
        request=dataclasses.replace(_request(), request_id=2),
        approval=_approval(approval_id=502),
    )
    with pytest.raises(MissingOrInvalidApprovalError, match="identity mismatch"):
        build_manual_sell_execution_plan_preview(
            request_id=1,
            approval_id=501,
            planning_inputs=_planning_inputs(),
        )


def test_caller_time_cannot_revive_expired_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_authority(
        monkeypatch,
        approval=_approval(
            approved_ts_utc=NOW - timedelta(minutes=10),
            expires_ts_utc=NOW - timedelta(minutes=5),
        ),
    )
    with pytest.raises(MissingOrInvalidApprovalError, match="expired"):
        build_manual_sell_execution_plan_preview(
            request_id=1,
            approval_id=501,
            planning_inputs=_planning_inputs(),
        )
    with pytest.raises(TypeError):
        build_manual_sell_execution_plan_preview(
            request_id=1,
            approval_id=501,
            planning_inputs=_planning_inputs(),
            now=NOW - timedelta(minutes=6),  # type: ignore[call-arg]
        )


def test_public_apis_expose_no_repository_or_authoritative_time_parameters() -> None:
    planner_parameters = inspect.signature(
        build_manual_sell_execution_plan_preview
    ).parameters
    assert set(planner_parameters) == {
        "request_id",
        "approval_id",
        "planning_inputs",
    }
    service_parameters = inspect.signature(service.process).parameters
    assert set(service_parameters) == {
        "request",
        "market_context",
        "venue_constraints",
        "sleeve_code",
    }

    forbidden = {
        "approval_repository",
        "request_repository",
        "gate_repository",
        "repository",
        "now",
        "current_time",
        "clock",
        "quantity_base",
        "decision_state",
        "approved",
        "approval",
    }
    assert forbidden.isdisjoint(planner_parameters)
    assert forbidden.isdisjoint(service_parameters)


@pytest.mark.parametrize(
    "keyword",
    ["approval_repository", "request_repository", "gate_repository", "now", "clock"],
)
def test_service_caller_cannot_select_authority_or_time(keyword: str) -> None:
    with pytest.raises(TypeError):
        service.process(
            _request(),
            market_context=_context(),
            venue_constraints=_constraints(),
            sleeve_code="CORE_STRUCTURAL",
            **{keyword: object()},  # type: ignore[arg-type]
        )


def test_buy_contract_preview_still_works() -> None:
    intent = ExecutionIntentPreview(
        1,
        "CORE_STRUCTURAL",
        42,
        "BTC",
        "bitvavo",
        "BUY",
        "PREPARE_PLAN",
        Decimal("100"),
        None,
        "ALLOWED",
        "OK",
    )
    assert build_execution_plan_preview(intent=intent, context=_context()).side == "BUY"
