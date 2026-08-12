"""Tests for src/executor/manual_execution_live_authority_v1.py — the
persisted LIVE permission layer (Issue #369 review follow-up)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from src.executor.manual_execution_handoff_v1 import (
    CLAIM_STATE_CLAIMED,
    ManualExecutionExecutorHandoff,
)
from src.executor.manual_execution_live_authority_v1 import (
    LiveAuthorityConflictError,
    LiveAuthorityDeniedError,
    ManualExecutionLiveAuthorityRepository,
)
from src.manual_execution import _trusted_clock_v1 as trusted_clock


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


class _FakeCursor:
    def __init__(self, backend: "_FakeBackend") -> None:
        self.backend = backend
        self._result: list[dict] = []
        self.lastrowid: int | None = None

    def execute(self, sql: str, params: list) -> None:
        sql_norm = " ".join(sql.split())
        backend = self.backend

        if sql_norm.startswith("INSERT INTO manual_execution_live_authority"):
            (
                handoff_id, request_id, approval_id, plan_snapshot_id, trading_account_id,
                venue, executor_identity, runtime_owner, executor_credential_binding_id,
                authorized_by, authorized_ts_utc,
            ) = params
            existing = next((r for r in backend.rows if r["manual_execution_executor_handoff_id"] == handoff_id), None)
            if existing is not None:
                self.lastrowid = existing["manual_execution_live_authority_id"]
                return
            new_id = backend.next_id
            backend.next_id += 1
            row = {
                "manual_execution_live_authority_id": new_id,
                "manual_execution_executor_handoff_id": handoff_id,
                "manual_execution_request_id": request_id,
                "manual_execution_approval_id": approval_id,
                "manual_execution_plan_snapshot_id": plan_snapshot_id,
                "trading_account_id": trading_account_id,
                "venue": venue,
                "executor_identity": executor_identity,
                "runtime_owner": runtime_owner,
                "executor_credential_binding_id": executor_credential_binding_id,
                "authorized_by": authorized_by,
                "authorized_ts_utc": authorized_ts_utc,
                "created_ts_utc": NOW,
            }
            backend.rows.append(row)
            self.lastrowid = new_id
            return

        if sql_norm.startswith("SELECT * FROM manual_execution_live_authority WHERE manual_execution_live_authority_id"):
            (authority_id,) = params
            self._result = [dict(r) for r in backend.rows if r["manual_execution_live_authority_id"] == authority_id]
            return

        if sql_norm.startswith("SELECT * FROM manual_execution_live_authority WHERE manual_execution_executor_handoff_id"):
            (handoff_id,) = params
            self._result = [dict(r) for r in backend.rows if r["manual_execution_executor_handoff_id"] == handoff_id]
            return

        raise AssertionError(f"unexpected SQL in fake live authority cursor: {sql_norm}")

    def fetchone(self):
        return self._result[0] if self._result else None


class _FakeSession:
    def __init__(self, backend: "_FakeBackend") -> None:
        self.backend = backend

    def __enter__(self) -> _FakeCursor:
        return _FakeCursor(self.backend)

    def __exit__(self, *exc: Any) -> bool:
        return False


class _FakeBackend:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.next_id = 1


def _repo(backend: _FakeBackend | None = None) -> tuple[ManualExecutionLiveAuthorityRepository, _FakeBackend]:
    backend = backend or _FakeBackend()
    return ManualExecutionLiveAuthorityRepository(cursor_factory=lambda **_: _FakeSession(backend)), backend


class TestGrant:
    def test_grant_creates_one_row_bound_to_exact_handoff_identity(self) -> None:
        repo, backend = _repo()
        handoff = _handoff()
        authority = repo.grant(handoff=handoff, authorized_by="joost")
        assert authority.handoff_id == handoff.handoff_id
        assert authority.request_id == handoff.request_id
        assert authority.plan_snapshot_id == handoff.plan_snapshot_id
        assert authority.trading_account_id == handoff.trading_account_id
        assert authority.venue == handoff.venue
        assert authority.executor_identity == handoff.executor_identity
        assert authority.runtime_owner == handoff.runtime_owner
        assert authority.executor_credential_binding_id == handoff.executor_credential_binding_id
        assert authority.authorized_by == "joost"
        assert len(backend.rows) == 1

    def test_grant_is_idempotent_for_the_same_handoff(self) -> None:
        repo, backend = _repo()
        handoff = _handoff()
        first = repo.grant(handoff=handoff, authorized_by="joost")
        second = repo.grant(handoff=handoff, authorized_by="joost")
        assert first.authority_id == second.authority_id
        assert len(backend.rows) == 1

    def test_grant_requires_authorized_by(self) -> None:
        repo, _backend = _repo()
        with pytest.raises(ValueError):
            repo.grant(handoff=_handoff(), authorized_by="   ")


class TestRequireMatching:
    def test_absent_authority_denied_by_default(self) -> None:
        repo, _backend = _repo()
        with pytest.raises(LiveAuthorityDeniedError):
            repo.require_matching(_handoff())

    def test_granted_authority_satisfies_require_matching(self) -> None:
        repo, _backend = _repo()
        handoff = _handoff()
        repo.grant(handoff=handoff, authorized_by="joost")
        authority = repo.require_matching(handoff)
        assert authority.handoff_id == handoff.handoff_id

    def test_authority_for_a_different_handoff_does_not_satisfy_this_one(self) -> None:
        repo, _backend = _repo()
        repo.grant(handoff=_handoff(handoff_id=1), authorized_by="joost")
        with pytest.raises(LiveAuthorityDeniedError):
            repo.require_matching(_handoff(handoff_id=2))

    def test_mismatched_identity_on_lookup_fails_closed(self) -> None:
        repo, backend = _repo()
        handoff = _handoff()
        repo.grant(handoff=handoff, authorized_by="joost")
        # Simulate a corrupted/forged row whose venue disagrees with the handoff.
        backend.rows[0]["venue"] = "kraken"
        with pytest.raises(LiveAuthorityConflictError):
            repo.require_matching(handoff)
