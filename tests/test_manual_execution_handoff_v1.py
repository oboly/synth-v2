"""Tests for src/executor/manual_execution_handoff_v1.py — the explicit
immutable executor handoff identity (Issue #206)."""
from __future__ import annotations

import dataclasses
import threading
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest

from src.decision_gate.manual_execution_approval_v1 import (
    APPROVAL_STATE_APPROVED,
    ManualExecutionApprovalRecord,
    PersistedManualExecutionAuthority,
)
from src.execution_planner.manual_execution_plan_snapshot_v1 import ManualExecutionPlanSnapshot
from src.executor import manual_execution_handoff_v1 as handoff_module
from src.executor.manual_execution_credential_scope_v1 import (
    CredentialScopeBinding,
    CredentialScopeDeniedError,
)
from src.executor.manual_execution_handoff_v1 import (
    ALLOWED_EXECUTOR_INTAKE_MODES,
    CLAIM_STATE_CLAIMED,
    CLAIM_STATE_CONSUMED,
    CLAIM_STATE_FAILED,
    DuplicateExecutorHandoffClaimError,
    ExecutorHandoffDeniedError,
    ExecutorHandoffIdentityConflictError,
    ExecutorHandoffRepository,
    RUNTIME_MODE_DRY_RUN,
    RUNTIME_MODE_LIVE_DISABLED,
    RUNTIME_MODE_PAPER,
    acknowledge_dry_run_or_paper_handoff,
)
from src.manual_execution import _trusted_clock_v1 as trusted_clock
from src.manual_execution.manual_execution_request_v1 import (
    MODE_LIVE,
    MODE_PAPER,
    QUANTITY_POLICY_FULL_AVAILABLE_BASE,
    REQUEST_STATE_GATE_BLOCKED,
    REQUEST_STATE_PLANNED,
    SOURCE_OPERATOR_CLI,
    build_manual_execution_request,
)


NOW = datetime(2026, 8, 12, tzinfo=timezone.utc)
TRADING_ACCOUNT_ID = 1
VENUE = "bitvavo"
ASSET_ID = 42
EXECUTOR_IDENTITY = "executor-manual-sell-v1"
RUNTIME_OWNER = "devlap"


@pytest.fixture(autouse=True)
def _fixed_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(trusted_clock, "utc_now", lambda: NOW)


def _request(*, request_id: int = 1, request_state: str = REQUEST_STATE_PLANNED, mode: str = MODE_PAPER, **overrides: Any):
    defaults = dict(
        idempotency_key="req-206-1", operator_request_nonce="nonce-1",
        created_ts_utc=NOW, source=SOURCE_OPERATOR_CLI, requested_by="operator",
        mode=mode, trading_account_id=TRADING_ACCOUNT_ID, account_code="paper", venue=VENUE,
        asset_id=ASSET_ID, base_asset="BTC", quote_asset="EUR", side="SELL",
        quantity_policy=QUANTITY_POLICY_FULL_AVAILABLE_BASE, provenance_id=7,
        ladder_profile_id=9, ladder_profile_version=2,
        anchor_type="NATIVE_SHORT_ANCHOR_HIGH", anchor_price=Decimal("51000"),
        anchor_source="native_short_context_v1", source_map_cycle_id="cycle-1",
        source_native_map_id="map-1", source_map_version="native_short_v1",
    )
    defaults.update(overrides)
    request = build_manual_execution_request(**defaults)
    return dataclasses.replace(request, request_id=request_id, request_state=request_state)


def _approval(*, approval_id: int = 501, side: str = "SELL", venue: str = VENUE, approval_state: str = APPROVAL_STATE_APPROVED, trading_account_id: int = TRADING_ACCOUNT_ID) -> ManualExecutionApprovalRecord:
    return ManualExecutionApprovalRecord(
        approval_id=approval_id, idempotency_key="manual_execution_approval:1", request_id=1,
        trading_account_id=trading_account_id, account_code="paper", venue=venue, asset_id=ASSET_ID,
        base_asset="BTC", quote_asset="EUR", side=side, approved_quantity_base=Decimal("2"),
        wallet_snapshot_id=9001, wallet_snapshot_version_ts_utc=NOW, reservation_id=1,
        approved_ts_utc=NOW, expires_ts_utc=NOW, mode=MODE_PAPER, provenance_id=7,
        approval_state=approval_state, decision_reason="OK",
        persisted_reservation_id=1, reservation_request_id=1, reservation_trading_account_id=TRADING_ACCOUNT_ID,
        reservation_venue=venue, reservation_asset_id=ASSET_ID, reservation_symbol="BTC",
        reservation_quantity_base=Decimal("2"), reservation_state="APPROVED_NOT_SUBMITTED",
        persisted_snapshot_id=9001, snapshot_trading_account_id=TRADING_ACCOUNT_ID, snapshot_venue=venue,
        snapshot_asset_id=ASSET_ID, snapshot_ts_utc=NOW,
    )


def _plan_snapshot(*, plan_snapshot_id: int = 701, request_id: int = 1, approval_id: int = 501, market: str = "BTC-EUR", side: str = "SELL", trading_account_id: int = TRADING_ACCOUNT_ID) -> ManualExecutionPlanSnapshot:
    return ManualExecutionPlanSnapshot(
        plan_snapshot_id=plan_snapshot_id, request_id=request_id, approval_id=approval_id,
        trading_account_id=trading_account_id, ladder_profile_id=9, ladder_profile_version=2,
        anchor_type="NATIVE_SHORT_ANCHOR_HIGH", anchor_price=Decimal("51000"),
        anchor_source="native_short_context_v1", source_map_cycle_id="cycle-1",
        source_native_map_id="map-1", source_map_version="native_short_v1", provenance_id=7,
        market=market, side=side, quantity_policy=QUANTITY_POLICY_FULL_AVAILABLE_BASE,
        approved_quantity_base=Decimal("2"), planner_version="manual_execution_contract_preview_v1",
        payload_json="{}",
    )


class _StubPlanSnapshotRepository:
    def __init__(self, snapshot: ManualExecutionPlanSnapshot | None) -> None:
        self.snapshot = snapshot

    def find_by_id(self, plan_snapshot_id: int) -> ManualExecutionPlanSnapshot | None:
        if self.snapshot is None or self.snapshot.plan_snapshot_id != plan_snapshot_id:
            return None
        return self.snapshot


class _StubCredentialScopeRepository:
    def __init__(self, binding: CredentialScopeBinding | None = None, *, deny: bool = False) -> None:
        self.binding = binding or CredentialScopeBinding(
            executor_credential_binding_id=55, trading_account_credential_id=10,
            trading_account_id=TRADING_ACCOUNT_ID, venue=VENUE, permission_scope="TRADE_EXECUTION",
            executor_identity=EXECUTOR_IDENTITY, runtime_owner=RUNTIME_OWNER,
            credential_status="ACTIVE", credential_source="db_encrypted",
            allowed_order_write=True, allowed_withdrawal=False,
        )
        self.deny = deny
        self.calls: list[dict] = []

    def resolve(self, *, trading_account_id, venue, executor_identity, runtime_owner):
        self.calls.append(dict(trading_account_id=trading_account_id, venue=venue, executor_identity=executor_identity, runtime_owner=runtime_owner))
        if self.deny:
            raise CredentialScopeDeniedError("CREDENTIAL_SCOPE_NOT_BOUND: denied by stub")
        return self.binding


class _FakeHandoffCursor:
    def __init__(self, backend: "_FakeHandoffBackend") -> None:
        self.backend = backend
        self._result: list[dict] = []
        self.lastrowid: int | None = None
        self.rowcount = 0

    def execute(self, sql: str, params: list) -> None:
        sql_norm = " ".join(sql.split())
        backend = self.backend

        if sql_norm.startswith("INSERT INTO manual_execution_executor_handoff"):
            (
                request_id, approval_id, plan_snapshot_id, trading_account_id, venue,
                market, side, executor_mode, executor_identity, runtime_owner,
                executor_credential_binding_id, claim_state, claimed_ts_utc,
            ) = params
            with backend.lock:
                existing = next((r for r in backend.rows if r["manual_execution_plan_snapshot_id"] == plan_snapshot_id), None)
                if existing is not None:
                    self.lastrowid = existing["manual_execution_executor_handoff_id"]
                    return
                new_id = backend.next_id
                backend.next_id += 1
                row = {
                    "manual_execution_executor_handoff_id": new_id,
                    "manual_execution_request_id": request_id,
                    "manual_execution_approval_id": approval_id,
                    "manual_execution_plan_snapshot_id": plan_snapshot_id,
                    "trading_account_id": trading_account_id,
                    "venue": venue,
                    "market": market,
                    "side": side,
                    "executor_mode": executor_mode,
                    "executor_identity": executor_identity,
                    "runtime_owner": runtime_owner,
                    "executor_credential_binding_id": executor_credential_binding_id,
                    "claim_state": claim_state,
                    "claimed_ts_utc": claimed_ts_utc,
                    "consumed_ts_utc": None,
                    "outcome_code": None,
                    "outcome_detail": None,
                    "created_ts_utc": NOW,
                }
                backend.rows.append(row)
                self.lastrowid = new_id
            return

        if sql_norm.startswith("SELECT * FROM manual_execution_executor_handoff WHERE manual_execution_executor_handoff_id"):
            (handoff_id,) = params
            with backend.lock:
                self._result = [dict(r) for r in backend.rows if r["manual_execution_executor_handoff_id"] == handoff_id]
            return

        if sql_norm.startswith("UPDATE manual_execution_executor_handoff"):
            new_claim_state, consumed_ts_utc, outcome_code, outcome_detail, handoff_id, required_state = params
            with backend.lock:
                match = next(
                    (r for r in backend.rows if r["manual_execution_executor_handoff_id"] == handoff_id and r["claim_state"] == required_state),
                    None,
                )
                if match is None:
                    self.rowcount = 0
                else:
                    match["claim_state"] = new_claim_state
                    match["consumed_ts_utc"] = consumed_ts_utc
                    match["outcome_code"] = outcome_code
                    match["outcome_detail"] = outcome_detail
                    self.rowcount = 1
            return

        raise AssertionError(f"unexpected SQL in fake executor handoff cursor: {sql_norm}")

    def fetchone(self):
        return self._result[0] if self._result else None

    def fetchall(self):
        return self._result


class _FakeHandoffSession:
    def __init__(self, backend: "_FakeHandoffBackend") -> None:
        self.backend = backend

    def __enter__(self) -> _FakeHandoffCursor:
        return _FakeHandoffCursor(self.backend)

    def __exit__(self, *exc: Any) -> bool:
        return False


class _FakeHandoffBackend:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.next_id = 1
        self.lock = threading.Lock()


_UNSET = object()


def _repo(
    monkeypatch: pytest.MonkeyPatch,
    *,
    backend: _FakeHandoffBackend | None = None,
    request=None,
    approval=None,
    snapshot: Any = _UNSET,
    credential_repository: _StubCredentialScopeRepository | None = None,
    authority_lookup_error: Exception | None = None,
) -> tuple[ExecutorHandoffRepository, _FakeHandoffBackend]:
    backend = backend or _FakeHandoffBackend()
    snapshot = _plan_snapshot() if snapshot is _UNSET else snapshot
    request = request if request is not None else _request()
    approval = approval if approval is not None else _approval()

    def resolve(*, request_id: int, approval_id: int):
        if authority_lookup_error is not None:
            raise authority_lookup_error
        return PersistedManualExecutionAuthority(request=request, approval=approval)

    monkeypatch.setattr(handoff_module, "resolve_persisted_manual_execution_authority", resolve)

    repo = ExecutorHandoffRepository(
        cursor_factory=lambda **_: _FakeHandoffSession(backend),
        plan_snapshot_repository=_StubPlanSnapshotRepository(snapshot),
        credential_scope_repository=credential_repository or _StubCredentialScopeRepository(),
    )
    return repo, backend


class TestIntakeHappyPath:
    def test_valid_approved_plan_creates_one_executor_handoff(self, monkeypatch: pytest.MonkeyPatch) -> None:
        repo, backend = _repo(monkeypatch)

        handoff = repo.intake(
            plan_snapshot_id=701, executor_mode=RUNTIME_MODE_DRY_RUN,
            executor_identity=EXECUTOR_IDENTITY, runtime_owner=RUNTIME_OWNER,
        )

        assert handoff.handoff_id is not None
        assert handoff.claim_state == CLAIM_STATE_CLAIMED
        assert handoff.trading_account_id == TRADING_ACCOUNT_ID
        assert handoff.market == "BTC-EUR"
        assert handoff.side == "SELL"
        assert len(backend.rows) == 1

    def test_retry_intake_is_idempotent_not_duplicated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        repo, backend = _repo(monkeypatch)

        first = repo.intake(plan_snapshot_id=701, executor_mode=RUNTIME_MODE_DRY_RUN, executor_identity=EXECUTOR_IDENTITY, runtime_owner=RUNTIME_OWNER)
        second = repo.intake(plan_snapshot_id=701, executor_mode=RUNTIME_MODE_DRY_RUN, executor_identity=EXECUTOR_IDENTITY, runtime_owner=RUNTIME_OWNER)

        assert first.handoff_id == second.handoff_id
        assert len(backend.rows) == 1


class TestIntakeFailsClosed:
    def test_unapproved_plan_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        repo, backend = _repo(monkeypatch, approval=_approval(approval_state="EXPIRED"))
        with pytest.raises(ExecutorHandoffDeniedError, match="APPROVAL_NOT_APPROVED"):
            repo.intake(plan_snapshot_id=701, executor_mode=RUNTIME_MODE_DRY_RUN, executor_identity=EXECUTOR_IDENTITY, runtime_owner=RUNTIME_OWNER)
        assert backend.rows == []

    def test_request_not_planned_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        repo, backend = _repo(monkeypatch, request=_request(request_state=REQUEST_STATE_GATE_BLOCKED))
        with pytest.raises(ExecutorHandoffDeniedError, match="REQUEST_NOT_PLANNED"):
            repo.intake(plan_snapshot_id=701, executor_mode=RUNTIME_MODE_DRY_RUN, executor_identity=EXECUTOR_IDENTITY, runtime_owner=RUNTIME_OWNER)
        assert backend.rows == []

    def test_missing_plan_snapshot_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        repo, backend = _repo(monkeypatch, snapshot=None)
        with pytest.raises(ExecutorHandoffDeniedError, match="PLAN_SNAPSHOT_NOT_FOUND"):
            repo.intake(plan_snapshot_id=701, executor_mode=RUNTIME_MODE_DRY_RUN, executor_identity=EXECUTOR_IDENTITY, runtime_owner=RUNTIME_OWNER)
        assert backend.rows == []

    def test_account_mismatch_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        repo, backend = _repo(monkeypatch, snapshot=_plan_snapshot(trading_account_id=999))
        with pytest.raises(ExecutorHandoffDeniedError, match="TRADING_ACCOUNT_ID_MISMATCH"):
            repo.intake(plan_snapshot_id=701, executor_mode=RUNTIME_MODE_DRY_RUN, executor_identity=EXECUTOR_IDENTITY, runtime_owner=RUNTIME_OWNER)
        assert backend.rows == []

    def test_venue_mismatch_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        repo, backend = _repo(monkeypatch, approval=_approval(venue="kraken"))
        with pytest.raises(ExecutorHandoffDeniedError, match="VENUE_MISMATCH"):
            repo.intake(plan_snapshot_id=701, executor_mode=RUNTIME_MODE_DRY_RUN, executor_identity=EXECUTOR_IDENTITY, runtime_owner=RUNTIME_OWNER)
        assert backend.rows == []

    def test_market_mismatch_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        repo, backend = _repo(monkeypatch, snapshot=_plan_snapshot(market="ETH-EUR"))
        with pytest.raises(ExecutorHandoffDeniedError, match="MARKET_MISMATCH"):
            repo.intake(plan_snapshot_id=701, executor_mode=RUNTIME_MODE_DRY_RUN, executor_identity=EXECUTOR_IDENTITY, runtime_owner=RUNTIME_OWNER)
        assert backend.rows == []

    def test_request_approval_snapshot_id_mismatch_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        repo, backend = _repo(monkeypatch, snapshot=_plan_snapshot(approval_id=999))
        with pytest.raises(ExecutorHandoffDeniedError, match="PLAN_SNAPSHOT_APPROVAL_MISMATCH"):
            repo.intake(plan_snapshot_id=701, executor_mode=RUNTIME_MODE_DRY_RUN, executor_identity=EXECUTOR_IDENTITY, runtime_owner=RUNTIME_OWNER)
        assert backend.rows == []

    def test_wrong_credential_scope_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        repo, backend = _repo(monkeypatch, credential_repository=_StubCredentialScopeRepository(deny=True))
        with pytest.raises(ExecutorHandoffDeniedError, match="CREDENTIAL_SCOPE_NOT_BOUND"):
            repo.intake(plan_snapshot_id=701, executor_mode=RUNTIME_MODE_DRY_RUN, executor_identity=EXECUTOR_IDENTITY, runtime_owner=RUNTIME_OWNER)
        assert backend.rows == []

    def test_live_mode_remains_denied(self, monkeypatch: pytest.MonkeyPatch) -> None:
        repo, backend = _repo(monkeypatch)
        with pytest.raises(ExecutorHandoffDeniedError, match="EXECUTOR_MODE_NOT_PERMITTED_FOR_INTAKE"):
            repo.intake(plan_snapshot_id=701, executor_mode=RUNTIME_MODE_LIVE_DISABLED, executor_identity=EXECUTOR_IDENTITY, runtime_owner=RUNTIME_OWNER)
        assert backend.rows == []
        with pytest.raises(ExecutorHandoffDeniedError, match="UNKNOWN_EXECUTOR_MODE"):
            repo.intake(plan_snapshot_id=701, executor_mode="LIVE", executor_identity=EXECUTOR_IDENTITY, runtime_owner=RUNTIME_OWNER)
        assert backend.rows == []

    def test_live_mode_request_fails_closed_even_if_state_forged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        repo, backend = _repo(monkeypatch, request=_request(mode=MODE_LIVE))
        with pytest.raises(ExecutorHandoffDeniedError, match="LIVE_TRADING_NOT_GRANTED"):
            repo.intake(plan_snapshot_id=701, executor_mode=RUNTIME_MODE_DRY_RUN, executor_identity=EXECUTOR_IDENTITY, runtime_owner=RUNTIME_OWNER)
        assert backend.rows == []

    def test_wrong_executor_identity_binding_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        credential_repository = _StubCredentialScopeRepository(deny=True)
        repo, backend = _repo(monkeypatch, credential_repository=credential_repository)
        with pytest.raises(ExecutorHandoffDeniedError):
            repo.intake(plan_snapshot_id=701, executor_mode=RUNTIME_MODE_DRY_RUN, executor_identity="unbound-executor", runtime_owner=RUNTIME_OWNER)
        assert credential_repository.calls[0]["executor_identity"] == "unbound-executor"
        assert backend.rows == []

    def test_duplicate_intake_with_different_identity_conflicts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        repo, backend = _repo(monkeypatch)
        repo.intake(plan_snapshot_id=701, executor_mode=RUNTIME_MODE_DRY_RUN, executor_identity=EXECUTOR_IDENTITY, runtime_owner=RUNTIME_OWNER)

        other_credentials = _StubCredentialScopeRepository(
            CredentialScopeBinding(
                executor_credential_binding_id=99, trading_account_credential_id=11,
                trading_account_id=TRADING_ACCOUNT_ID, venue=VENUE, permission_scope="TRADE_EXECUTION",
                executor_identity="other-executor", runtime_owner=RUNTIME_OWNER,
                credential_status="ACTIVE", credential_source="db_encrypted",
                allowed_order_write=True, allowed_withdrawal=False,
            )
        )
        repo2, _ = _repo(monkeypatch, backend=backend, credential_repository=other_credentials)
        with pytest.raises(ExecutorHandoffIdentityConflictError):
            repo2.intake(plan_snapshot_id=701, executor_mode=RUNTIME_MODE_DRY_RUN, executor_identity="other-executor", runtime_owner=RUNTIME_OWNER)


class TestConsumption:
    def test_dry_run_and_paper_path_works_without_broker(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for mode, expected_outcome in ((RUNTIME_MODE_DRY_RUN, "DRY_RUN_ACKNOWLEDGED"), (RUNTIME_MODE_PAPER, "PAPER_ACKNOWLEDGED")):
            repo, backend = _repo(monkeypatch)
            handoff = repo.intake(plan_snapshot_id=701, executor_mode=mode, executor_identity=EXECUTOR_IDENTITY, runtime_owner=RUNTIME_OWNER)
            outcome = acknowledge_dry_run_or_paper_handoff(handoff, repo)
            assert outcome.claim_state == CLAIM_STATE_CONSUMED
            assert outcome.outcome_code == expected_outcome
            assert "broker_writes=0" in outcome.outcome_detail

    def test_duplicate_consumption_is_idempotent_for_same_outcome(self, monkeypatch: pytest.MonkeyPatch) -> None:
        repo, backend = _repo(monkeypatch)
        handoff = repo.intake(plan_snapshot_id=701, executor_mode=RUNTIME_MODE_DRY_RUN, executor_identity=EXECUTOR_IDENTITY, runtime_owner=RUNTIME_OWNER)
        first = repo.consume(handoff.handoff_id, outcome_code="DRY_RUN_ACKNOWLEDGED")
        second = repo.consume(handoff.handoff_id, outcome_code="DRY_RUN_ACKNOWLEDGED")
        assert first.claim_state == second.claim_state == CLAIM_STATE_CONSUMED

    def test_second_execution_with_different_outcome_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        repo, backend = _repo(monkeypatch)
        handoff = repo.intake(plan_snapshot_id=701, executor_mode=RUNTIME_MODE_DRY_RUN, executor_identity=EXECUTOR_IDENTITY, runtime_owner=RUNTIME_OWNER)
        repo.consume(handoff.handoff_id, outcome_code="DRY_RUN_ACKNOWLEDGED")
        with pytest.raises(DuplicateExecutorHandoffClaimError):
            repo.consume(handoff.handoff_id, outcome_code="SOMETHING_ELSE")

    def test_cannot_consume_after_failed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        repo, backend = _repo(monkeypatch)
        handoff = repo.intake(plan_snapshot_id=701, executor_mode=RUNTIME_MODE_DRY_RUN, executor_identity=EXECUTOR_IDENTITY, runtime_owner=RUNTIME_OWNER)
        repo.fail(handoff.handoff_id, outcome_code="PRECONDITION_LOST")
        with pytest.raises(DuplicateExecutorHandoffClaimError):
            repo.consume(handoff.handoff_id, outcome_code="DRY_RUN_ACKNOWLEDGED")

    def test_concurrent_claim_cannot_produce_two_owners(self, monkeypatch: pytest.MonkeyPatch) -> None:
        repo, backend = _repo(monkeypatch)
        handoff = repo.intake(plan_snapshot_id=701, executor_mode=RUNTIME_MODE_DRY_RUN, executor_identity=EXECUTOR_IDENTITY, runtime_owner=RUNTIME_OWNER)

        results: dict[str, Any] = {}

        def run(name: str, outcome_code: str) -> None:
            try:
                results[name] = repo.consume(handoff.handoff_id, outcome_code=outcome_code)
            except DuplicateExecutorHandoffClaimError as exc:
                results[name] = exc

        thread_a = threading.Thread(target=run, args=("a", "OUTCOME_A"))
        thread_b = threading.Thread(target=run, args=("b", "OUTCOME_B"))
        thread_a.start()
        thread_b.start()
        thread_a.join(timeout=10)
        thread_b.join(timeout=10)

        winners = [v for v in results.values() if not isinstance(v, Exception)]
        losers = [v for v in results.values() if isinstance(v, Exception)]
        assert len(winners) == 1
        assert len(losers) == 1
        assert sum(1 for r in backend.rows if r["claim_state"] == CLAIM_STATE_CONSUMED) == 1


def test_live_disabled_never_reaches_allowed_intake_modes() -> None:
    assert RUNTIME_MODE_LIVE_DISABLED not in ALLOWED_EXECUTOR_INTAKE_MODES
    assert ALLOWED_EXECUTOR_INTAKE_MODES == frozenset({RUNTIME_MODE_DRY_RUN, RUNTIME_MODE_PAPER})
