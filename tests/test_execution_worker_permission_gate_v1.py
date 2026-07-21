from __future__ import annotations

import threading
import base64
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.decision_gate.permission_evidence_v1 import (
    EVIDENCE_PRIVATE_KEY_ENV,
    EVIDENCE_PUBLIC_KEY_ENV,
    PRODUCER_NAME,
    build_provenance_payload,
    sign_provenance,
)
from src.execution import worker
from src.execution.permission_gate_v1 import (
    BROKER_WRITE_PERMISSION_ENV,
    BROKER_WRITE_PERMISSION_GRANTED_VALUE,
    LIVE_EXECUTION_PERMISSION_ENV,
    LIVE_EXECUTION_PERMISSION_GRANTED_VALUE,
    ExecutionClaim,
    LiveExecutionPermissionError,
    _validate_exact_scope,
)


NOW = datetime(2026, 7, 21, 12, 0, 0)
PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
PRIVATE_KEY_B64 = base64.b64encode(
    PRIVATE_KEY.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
).decode("ascii")
PUBLIC_KEY_B64 = base64.b64encode(
    PRIVATE_KEY.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
).decode("ascii")


def _env() -> dict[str, str]:
    return {
        LIVE_EXECUTION_PERMISSION_ENV: LIVE_EXECUTION_PERMISSION_GRANTED_VALUE,
        BROKER_WRITE_PERMISSION_ENV: BROKER_WRITE_PERMISSION_GRANTED_VALUE,
        EVIDENCE_PUBLIC_KEY_ENV: PUBLIC_KEY_B64,
    }


def _producer_env() -> dict[str, str]:
    return {EVIDENCE_PRIVATE_KEY_ENV: PRIVATE_KEY_B64}


def _scope_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "execution_plan_id": 100,
        "plan_trading_account_id": 7,
        "plan_permission_evidence_id": 11,
        "evidence_permission_evidence_id": 11,
        "plan_asset_id": 42,
        "plan_venue": "bitvavo",
        "plan_market": "BTC-EUR",
        "plan_side": "BUY",
        "plan_execution_intent": "PLACE_PASSIVE_LIMIT",
        "plan_action_type": "PLACE_ORDER",
        "plan_requested_side": "BUY",
        "plan_execution_mode": "LIVE",
        "plan_state": "IDLE",
        "plan_valid_until_ts_utc": NOW + timedelta(minutes=5),
        "reference_price_eur": Decimal("100"),
        "passive_price_eur": Decimal("99"),
        "target_fraction": Decimal("0.10"),
        "decision_gate_audit_log_id": 9,
        "audit_row_id": 9,
        "producer_name": PRODUCER_NAME,
        "evidence_trading_account_id": 7,
        "evidence_venue": "bitvavo",
        "evidence_asset_id": 42,
        "evidence_market": "BTC-EUR",
        "evidence_execution_intent": "PLACE_PASSIVE_LIMIT",
        "evidence_action_type": "PLACE_ORDER",
        "evidence_requested_side": "BUY",
        "permission_state": "EXECUTION_PERMITTED",
        "decision_state": "EXECUTION_ALLOWED",
        "evidence_state": "ACTIVE",
        "permitted_ts_utc": NOW - timedelta(minutes=1),
        "valid_until_ts_utc": NOW + timedelta(minutes=5),
        "revoked_ts_utc": None,
        "superseded_by_evidence_id": None,
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
        "account_trading_account_id": 7,
        "account_venue": "bitvavo",
        "account_enabled": 1,
        "account_live_trading_enabled": 1,
    }
    row.update(overrides)
    payload = build_provenance_payload(
        decision_gate_audit_log_id=int(row["decision_gate_audit_log_id"] or 0),
        trading_account_id=int(row["evidence_trading_account_id"]),
        venue=str(row["evidence_venue"]),
        asset_id=int(row["evidence_asset_id"]),
        market=str(row["evidence_market"]),
        execution_intent=str(row["evidence_execution_intent"]),
        action_type=str(row["evidence_action_type"]),
        requested_side=str(row["evidence_requested_side"]),
        permission_state=str(row["permission_state"]),
        decision_state=str(row["decision_state"]),
        permitted_ts_utc=row["permitted_ts_utc"],
        valid_until_ts_utc=row["valid_until_ts_utc"],
    )
    row.setdefault("provenance_signature", sign_provenance(payload, _producer_env()))
    return row


def _assert_scope_error(code: str, **overrides: Any) -> None:
    with pytest.raises(LiveExecutionPermissionError) as exc_info:
        _validate_exact_scope(
            _scope_row(**overrides),
            action_type="PLACE_ORDER",
            now=NOW,
            env=_env(),
        )
    assert exc_info.value.code == code


def test_exact_canonical_scope_and_signed_provenance_pass() -> None:
    _validate_exact_scope(_scope_row(), action_type="PLACE_ORDER", now=NOW, env=_env())


@pytest.mark.parametrize("side", [None, "", "buy", "Buy", "HOLD"])
def test_noncanonical_plan_side_blocks(side: str | None) -> None:
    code = "REQUESTED_SIDE_MISMATCH" if side in {None, ""} else "REQUESTED_SIDE_MISMATCH"
    _assert_scope_error(code, plan_requested_side=side)


def test_matching_lowercase_side_is_still_rejected() -> None:
    _assert_scope_error(
        "REQUESTED_SIDE_NOT_CANONICAL",
        plan_side="buy",
        plan_requested_side="buy",
        evidence_requested_side="buy",
        audit_requested_side="buy",
    )


def test_evidence_plan_side_mismatch_blocks() -> None:
    _assert_scope_error("REQUESTED_SIDE_MISMATCH", evidence_requested_side="SELL")


def test_action_mismatch_blocks() -> None:
    _assert_scope_error("ACTION_TYPE_MISMATCH", evidence_action_type="CANCEL_ORDER")


@pytest.mark.parametrize("field", ["reference_price_eur", "passive_price_eur", "target_fraction"])
def test_invalid_placement_values_block_before_claim(field: str) -> None:
    _assert_scope_error("PLACEMENT_VALUES_INVALID", **{field: None})


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"decision_gate_audit_log_id": None}, "PERMISSION_AUDIT_PROVENANCE_MISSING"),
        ({"audit_row_id": None}, "PERMISSION_AUDIT_ROW_NOT_FOUND"),
        ({"decision_state": "EXECUTION_DENIED"}, "DECISION_STATE_DENIED"),
        ({"producer_name": "manual_sql"}, "PERMISSION_PRODUCER_INVALID"),
        ({"audit_trading_account_id": 8}, "AUDIT_ACCOUNT_MISMATCH"),
        ({"audit_venue": "other"}, "AUDIT_VENUE_MISMATCH"),
        ({"audit_asset_id": 99}, "AUDIT_ASSET_MISMATCH"),
        ({"audit_market": "ETH-EUR"}, "AUDIT_MARKET_MISMATCH"),
        ({"provenance_signature": "0" * 88}, "PERMISSION_PROVENANCE_INVALID"),
    ],
)
def test_untrusted_or_mismatched_provenance_blocks(
    overrides: dict[str, Any], code: str
) -> None:
    _assert_scope_error(code, **overrides)


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"plan_trading_account_id": None}, "PLAN_TRADING_ACCOUNT_ID_MISSING"),
        ({"plan_trading_account_id": 8}, "PLAN_EVIDENCE_ACCOUNT_MISMATCH"),
        ({"account_trading_account_id": 8}, "PLAN_ACCOUNT_ROW_MISMATCH"),
        ({"account_venue": "other"}, "ACCOUNT_VENUE_MISMATCH"),
        ({"account_enabled": 0}, "TRADING_ACCOUNT_DISABLED"),
        ({"account_live_trading_enabled": 0}, "TRADING_ACCOUNT_LIVE_DISABLED"),
    ],
)
def test_explicit_trading_account_binding(overrides: dict[str, Any], code: str) -> None:
    _assert_scope_error(code, **overrides)


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"evidence_state": "REVOKED", "revoked_ts_utc": NOW}, "PERMISSION_REVOKED"),
        ({"evidence_state": "SUPERSEDED", "superseded_by_evidence_id": 12}, "PERMISSION_SUPERSEDED"),
        ({"evidence_state": "SUPERSEDED", "superseded_by_evidence_id": 11}, "PERMISSION_SELF_SUPERSEDED"),
        ({"account_enabled": 0}, "TRADING_ACCOUNT_DISABLED"),
        ({"plan_state": "CANCELLED"}, "PLAN_NOT_ACTIONABLE"),
    ],
)
def test_toctou_values_are_revalidated_at_claim(
    overrides: dict[str, Any], code: str
) -> None:
    _assert_scope_error(code, **overrides)


def _plan(**overrides: Any) -> worker.PlanRuntime:
    plan = worker.PlanRuntime(
        execution_plan_id=100,
        trading_account_id=7,
        decision_gate_permission_evidence_id=11,
        asset_id=42,
        symbol="BTC",
        sleeve_code="CORE",
        venue="bitvavo",
        market="BTC-EUR",
        side="BUY",
        desired_action="SPREAD_CAPTURE_PASSIVE",
        execution_intent="PLACE_PASSIVE_LIMIT",
        action_type="PLACE_ORDER",
        requested_side="BUY",
        execution_mode="LIVE",
        target_fraction=Decimal("0.10"),
        reference_price_eur=Decimal("100"),
        passive_price_eur=Decimal("99"),
        urgent_limit_price_eur=Decimal("101"),
        max_reprices=2,
        max_wait_seconds=1800,
        max_chase_bps=Decimal("15"),
        min_spread_bps_for_capture=Decimal("3"),
        escalation_to_urgent_limit=True,
        abort_if_signal_invalidates=True,
        plan_state="IDLE",
        notes="test",
        plan_ts_utc=NOW,
        valid_until_ts_utc=NOW + timedelta(minutes=5),
    )
    return replace(plan, **overrides)


def _claim(**overrides: Any) -> ExecutionClaim:
    claim = ExecutionClaim(
        execution_attempt_id=1,
        execution_plan_id=100,
        decision_gate_permission_evidence_id=11,
        trading_account_id=7,
        asset_id=42,
        venue="bitvavo",
        market="BTC-EUR",
        execution_intent="PLACE_PASSIVE_LIMIT",
        action_type="PLACE_ORDER",
        requested_side="BUY",
        reference_price_eur=Decimal("100"),
        passive_price_eur=Decimal("99"),
        target_fraction=Decimal("0.10"),
        claim_token="claim-token",
        claim_owner="worker-1",
        claimed_ts_utc=NOW,
        authorization_snapshot_ts_utc=NOW,
        idempotency_key="a" * 64,
        broker_client_order_id="b1a7b1a7-b1a7-41a7-81a7-b1a7b1a7b1a7",
    )
    return replace(claim, **overrides)


class Broker:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.orders: list[Any] = []

    def place_order(self, order: Any) -> dict[str, str]:
        self.orders.append(order)
        if self.fail:
            raise TimeoutError("unknown broker outcome")
        return {"orderId": "order-1"}


class AtomicClaimRepo:
    def __init__(self, claim: ExecutionClaim | None = None) -> None:
        self.claim = claim or _claim()
        self.lock = threading.Lock()
        self.claimed = False
        self.confirmed: list[tuple[ExecutionClaim, str]] = []
        self.uncertain: list[tuple[ExecutionClaim, str]] = []
        self.failed: list[tuple[ExecutionClaim, str]] = []

    def claim_live_action(self, **_: Any) -> ExecutionClaim:
        with self.lock:
            if self.claimed:
                raise LiveExecutionPermissionError("EXECUTION_ATTEMPT_ALREADY_CLAIMED")
            self.claimed = True
            return self.claim

    def confirm_attempt(self, claim: ExecutionClaim, order_id: str) -> None:
        self.confirmed.append((claim, order_id))

    def mark_attempt_uncertain(self, claim: ExecutionClaim, code: str) -> None:
        self.uncertain.append((claim, code))

    def mark_attempt_failed(self, claim: ExecutionClaim, code: str) -> None:
        self.failed.append((claim, code))


def _patch_worker_io(monkeypatch: pytest.MonkeyPatch, plan: worker.PlanRuntime) -> None:
    monkeypatch.setattr(worker, "_fetch_actionable_plans", lambda: [plan])
    monkeypatch.setattr(worker, "_fetch_latest_events_for_plans", lambda _: {})
    monkeypatch.setattr(worker, "_write_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(worker, "_update_plan_state", lambda *args, **kwargs: None)


def test_persisted_paper_plan_cannot_construct_live_client_or_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_worker_io(monkeypatch, _plan(execution_mode="PAPER"))

    class ForbiddenRepo:
        def claim_live_action(self, **_: Any) -> ExecutionClaim:
            raise AssertionError("paper must not consume permission")

    result = worker.process_execution_plans(
        execution_mode="live",
        broker_client_factory=lambda: (_ for _ in ()).throw(AssertionError("live client")),
        market_data_client_factory=lambda: (_ for _ in ()).throw(AssertionError("auth polling")),
        permission_repo=ForbiddenRepo(),
    )
    assert result["paper_placed"] == 1
    assert result["live_placed"] == 0


def test_sell_claim_submits_exactly_one_sell_and_never_buy() -> None:
    broker = Broker()
    order_id = worker._place_claimed_order_live(_claim(requested_side="SELL"), broker)
    assert order_id == "order-1"
    assert [order.side for order in broker.orders] == ["SELL"]


def test_buy_claim_submits_exactly_one_buy() -> None:
    broker = Broker()
    worker._place_claimed_order_live(_claim(requested_side="BUY"), broker)
    assert [order.side for order in broker.orders] == ["BUY"]


def test_two_workers_can_produce_only_one_broker_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_worker_io(monkeypatch, _plan())
    repo = AtomicClaimRepo()
    broker = Broker()

    threads = [
        threading.Thread(
            target=worker.process_execution_plans,
            kwargs={
                "execution_mode": "live",
                "broker_client_factory": lambda: broker,
                "permission_repo": repo,
            },
        )
        for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(broker.orders) == 1
    assert len(repo.confirmed) == 1


def test_uncertain_submission_blocks_automatic_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_worker_io(monkeypatch, _plan())
    repo = AtomicClaimRepo()
    broker = Broker(fail=True)
    first = worker.process_execution_plans(
        execution_mode="live", broker_client_factory=lambda: broker, permission_repo=repo
    )
    second = worker.process_execution_plans(
        execution_mode="live", broker_client_factory=lambda: broker, permission_repo=repo
    )
    assert first["failed"] == 1
    assert second["failed"] == 1
    assert len(broker.orders) == 1
    assert repo.uncertain == [(repo.claim, "BROKER_SUBMISSION_OUTCOME_UNKNOWN")]


def test_client_construction_failure_records_failed_and_calls_no_broker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_worker_io(monkeypatch, _plan())
    repo = AtomicClaimRepo()
    result = worker.process_execution_plans(
        execution_mode="live",
        broker_client_factory=lambda: (_ for _ in ()).throw(RuntimeError("no credentials")),
        permission_repo=repo,
    )
    assert result["failed"] == 1
    assert repo.failed == [(repo.claim, "BROKER_CLIENT_CONSTRUCTION_FAILED")]


def test_stable_claim_identifier_is_passed_unchanged() -> None:
    broker = Broker()
    claim = _claim(broker_client_order_id="018f47ee-312a-7b25-8000-000000000001")
    worker._place_claimed_order_live(claim, broker)
    assert broker.orders[0].client_order_id == claim.broker_client_order_id
