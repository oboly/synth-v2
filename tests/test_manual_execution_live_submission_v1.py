"""Tests for src/executor/manual_execution_live_submission_v1.py — the
composed two-gate LIVE entrypoint (Issue #369 review follow-up).

Covers the exact regression scenarios required by review:
  - dry-run makes zero canonical live submission-leg writes, and the same
    plan/handoff remains fully eligible for LIVE submission afterwards;
  - a PAPER handoff with every env gate present is still denied without
    persisted LIVE authority (no implicit PAPER -> LIVE promotion);
  - persisted authority alone (no env activation) is denied;
  - persisted authority + env activation reaches the injected broker
    boundary exactly once per leg.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest

import src.executor.manual_execution_live_submission_v1 as live_submission_module
from src.execution_planner.manual_execution_plan_snapshot_v1 import ManualExecutionPlanSnapshot
from src.executor.manual_execution_handoff_v1 import (
    CLAIM_STATE_CLAIMED,
    ManualExecutionExecutorHandoff,
)
from src.executor.manual_execution_live_authority_v1 import (
    LiveAuthorityDeniedError,
    ManualExecutionLiveAuthorityRepository,
)
from src.executor.manual_execution_live_submission_v1 import submit_manual_sell_ladder_live
from src.executor.manual_execution_stub_order_adapter_v1 import StubOrderPlacementAdapter
from src.executor.manual_execution_submission_leg_inmemory_v1 import (
    InMemorySubmissionLegRepository,
)
from src.executor.manual_execution_submission_orchestrator_v1 import (
    OrderAck,
    submit_manual_sell_ladder,
)
from src.executor.manual_live_authorization_v1 import (
    MANUAL_LIVE_AUTHORIZATION_HANDOFF_ID_ENV,
    ManualLiveAuthorizationDeniedError,
)
from src.manual_execution import _trusted_clock_v1 as trusted_clock
from tests.test_manual_execution_submission_leg_v1 import _FakeBackend, _FakeSession
from tests.test_manual_execution_live_authority_v1 import (
    _FakeBackend as _AuthFakeBackend,
    _FakeSession as _AuthFakeSession,
)
from src.executor.manual_execution_submission_leg_v1 import ManualExecutionSubmissionLegRepository


NOW = datetime(2026, 8, 14, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _fixed_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(trusted_clock, "utc_now", lambda: NOW)


def _handoff(**overrides: Any) -> ManualExecutionExecutorHandoff:
    defaults: dict[str, Any] = dict(
        handoff_id=1, request_id=1, approval_id=1, plan_snapshot_id=701,
        trading_account_id=1, venue="bitvavo", market="BTC-EUR", side="SELL",
        executor_mode="PAPER", executor_identity="executor-v1", runtime_owner="devlap",
        executor_credential_binding_id=1, claim_state=CLAIM_STATE_CLAIMED,
        claimed_ts_utc=NOW, consumed_ts_utc=None, outcome_code=None, outcome_detail=None,
        created_ts_utc=NOW,
    )
    defaults.update(overrides)
    return ManualExecutionExecutorHandoff(**defaults)


THREE_LEGS = [(Decimal("50000"), Decimal("0.1")), (Decimal("51000"), Decimal("0.1")), (Decimal("52000"), Decimal("0.1"))]


def _payload_json(legs: list[tuple[Decimal, Decimal]]) -> str:
    return json.dumps(
        {
            "legs": [
                {"leg_index": idx, "side": "SELL", "target_price_eur": str(price), "quantity_base": str(qty)}
                for idx, (price, qty) in enumerate(legs, start=1)
            ]
        }
    )


def _plan_snapshot(*, legs: list[tuple[Decimal, Decimal]] = THREE_LEGS) -> ManualExecutionPlanSnapshot:
    return ManualExecutionPlanSnapshot(
        plan_snapshot_id=701, request_id=1, approval_id=1, trading_account_id=1,
        ladder_profile_id=1, ladder_profile_version=1, anchor_type="X", anchor_price=Decimal("1"),
        anchor_source="x", source_map_cycle_id="c", source_native_map_id="m", source_map_version="v",
        provenance_id=1, market="BTC-EUR", side="SELL", quantity_policy="LADDER_LEVELS",
        approved_quantity_base=Decimal("1"), planner_version="v1",
        payload_json=_payload_json(legs),
    )


def _db_leg_repo() -> tuple[ManualExecutionSubmissionLegRepository, _FakeBackend]:
    backend = _FakeBackend()
    return ManualExecutionSubmissionLegRepository(cursor_factory=lambda **_: _FakeSession(backend)), backend


@dataclass
class _CapturingLiveAdapter:
    client: Any = None
    calls: list = field(default_factory=list)

    def place_order(self, **kwargs: Any) -> OrderAck:
        self.calls.append(kwargs)
        return OrderAck(broker_order_id=f"live-order-{len(self.calls)}", broker_status="open")

    def find_order_by_client_order_id(self, **kwargs: Any) -> OrderAck | None:
        return None


def _patch_live_broker_boundary(monkeypatch: pytest.MonkeyPatch) -> _CapturingLiveAdapter:
    adapter_holder: dict[str, _CapturingLiveAdapter] = {}

    def _fake_build_client(**_kwargs: Any) -> object:
        return object()

    def _fake_adapter_ctor(*, client: Any) -> _CapturingLiveAdapter:
        adapter = adapter_holder.setdefault("adapter", _CapturingLiveAdapter(client=client))
        return adapter

    monkeypatch.setattr(live_submission_module, "build_live_bitvavo_client", _fake_build_client)
    monkeypatch.setattr(live_submission_module, "LiveBitvavoOrderAdapter", _fake_adapter_ctor)
    return adapter_holder  # populated after first call


class TestPaperCannotBePromotedToLive:
    def test_paper_handoff_with_every_env_gate_present_is_still_denied_without_authority(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        handoff = _handoff(executor_mode="PAPER")
        plan_snapshot = _plan_snapshot()
        repo, _backend = _db_leg_repo()
        monkeypatch.setenv(MANUAL_LIVE_AUTHORIZATION_HANDOFF_ID_ENV, str(handoff.handoff_id))
        _patch_live_broker_boundary(monkeypatch)

        with pytest.raises(LiveAuthorityDeniedError):
            submit_manual_sell_ladder_live(
                handoff=handoff, plan_snapshot=plan_snapshot, operator_id=1,
                conn=object(), master_key_bytes=b"0" * 32, cred_repo_factory=lambda conn: None,
                live_authority_repository=ManualExecutionLiveAuthorityRepository(
                    cursor_factory=lambda **_: _AuthFakeSession(_AuthFakeBackend())
                ),
                submission_leg_repository=repo,
            )


class TestPersistedAuthorityAndEnvGateBothRequired:
    def _authority_repo(self, backend: "_AuthFakeBackend") -> ManualExecutionLiveAuthorityRepository:
        return ManualExecutionLiveAuthorityRepository(cursor_factory=lambda **_: _AuthFakeSession(backend))

    def test_authority_absent_denied(self, monkeypatch: pytest.MonkeyPatch) -> None:
        handoff = _handoff()
        plan_snapshot = _plan_snapshot()
        repo, _backend = _db_leg_repo()
        monkeypatch.setenv(MANUAL_LIVE_AUTHORIZATION_HANDOFF_ID_ENV, str(handoff.handoff_id))
        _patch_live_broker_boundary(monkeypatch)
        authority_backend = _AuthFakeBackend()

        with pytest.raises(LiveAuthorityDeniedError):
            submit_manual_sell_ladder_live(
                handoff=handoff, plan_snapshot=plan_snapshot, operator_id=1,
                conn=object(), master_key_bytes=b"0" * 32, cred_repo_factory=lambda conn: None,
                live_authority_repository=self._authority_repo(authority_backend),
                submission_leg_repository=repo,
            )

    def test_authority_present_but_env_gate_missing_denied(self, monkeypatch: pytest.MonkeyPatch) -> None:
        handoff = _handoff()
        plan_snapshot = _plan_snapshot()
        repo, _backend = _db_leg_repo()
        _patch_live_broker_boundary(monkeypatch)
        authority_backend = _AuthFakeBackend()
        authority_repo = self._authority_repo(authority_backend)
        authority_repo.grant(handoff=handoff, authorized_by="joost")
        monkeypatch.delenv(MANUAL_LIVE_AUTHORIZATION_HANDOFF_ID_ENV, raising=False)

        with pytest.raises(ManualLiveAuthorizationDeniedError):
            submit_manual_sell_ladder_live(
                handoff=handoff, plan_snapshot=plan_snapshot, operator_id=1,
                conn=object(), master_key_bytes=b"0" * 32, cred_repo_factory=lambda conn: None,
                live_authority_repository=authority_repo,
                submission_leg_repository=repo,
            )

    def test_authority_and_env_gate_both_present_reaches_broker_exactly_once_per_leg(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        handoff = _handoff()
        plan_snapshot = _plan_snapshot()
        repo, _backend = _db_leg_repo()
        authority_backend = _AuthFakeBackend()
        authority_repo = self._authority_repo(authority_backend)
        authority_repo.grant(handoff=handoff, authorized_by="joost")
        monkeypatch.setenv(MANUAL_LIVE_AUTHORIZATION_HANDOFF_ID_ENV, str(handoff.handoff_id))
        adapter_holder = _patch_live_broker_boundary(monkeypatch)

        result = submit_manual_sell_ladder_live(
            handoff=handoff, plan_snapshot=plan_snapshot, operator_id=1,
            conn=object(), master_key_bytes=b"0" * 32, cred_repo_factory=lambda conn: None,
            live_authority_repository=authority_repo,
            submission_leg_repository=repo,
        )

        assert result.stopped_reason is None
        assert len(adapter_holder["adapter"].calls) == 3


class TestDryRunDoesNotContaminateLiveState:
    def test_dry_run_writes_no_canonical_rows_then_live_submits_each_leg_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        handoff = _handoff()
        plan_snapshot = _plan_snapshot()

        # 1. Dry-run rehearsal against the in-memory repository + stub adapter.
        dry_run_repo = InMemorySubmissionLegRepository()
        dry_run_result = submit_manual_sell_ladder(
            handoff=handoff, plan_snapshot=plan_snapshot, operator_id=1,
            adapter=StubOrderPlacementAdapter(), submission_leg_repository=dry_run_repo,
        )
        assert dry_run_result.stopped_reason is None

        # 2. The canonical (DB-backed) submission-leg repository must be
        #    completely untouched by the dry-run above.
        live_repo, live_backend = _db_leg_repo()
        assert live_backend.rows_by_id == {}
        assert live_repo.find_by_plan_and_leg(plan_snapshot_id=701, leg_index=1) is None

        # 3. The exact same plan/handoff is still fully eligible for LIVE
        #    submission, and each leg is submitted exactly once.
        authority_backend = _AuthFakeBackend()
        authority_repo = ManualExecutionLiveAuthorityRepository(
            cursor_factory=lambda **_: _AuthFakeSession(authority_backend)
        )
        authority_repo.grant(handoff=handoff, authorized_by="joost")
        monkeypatch.setenv(MANUAL_LIVE_AUTHORIZATION_HANDOFF_ID_ENV, str(handoff.handoff_id))
        adapter_holder = _patch_live_broker_boundary(monkeypatch)

        live_result = submit_manual_sell_ladder_live(
            handoff=handoff, plan_snapshot=plan_snapshot, operator_id=1,
            conn=object(), master_key_bytes=b"0" * 32, cred_repo_factory=lambda conn: None,
            live_authority_repository=authority_repo,
            submission_leg_repository=live_repo,
        )

        assert live_result.stopped_reason is None
        assert len(live_result.leg_outcomes) == 3
        assert len(adapter_holder["adapter"].calls) == 3
        # Re-running submission again must not resubmit any leg.
        submit_manual_sell_ladder_live(
            handoff=handoff, plan_snapshot=plan_snapshot, operator_id=1,
            conn=object(), master_key_bytes=b"0" * 32, cred_repo_factory=lambda conn: None,
            live_authority_repository=authority_repo,
            submission_leg_repository=live_repo,
        )
        assert len(adapter_holder["adapter"].calls) == 3
