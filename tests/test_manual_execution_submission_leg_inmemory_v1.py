"""Tests for src/executor/manual_execution_submission_leg_inmemory_v1.py —
the never-persisted dry-run repository (Issue #369 review follow-up)."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.executor.manual_execution_submission_leg_inmemory_v1 import (
    InMemorySubmissionLegRepository,
)
from src.executor.manual_execution_submission_leg_v1 import (
    STATE_PREPARED,
    STATE_REJECTED,
    STATE_SUBMISSION_UNCERTAIN,
    STATE_SUBMITTED,
    SubmissionLegConflictError,
)
from src.manual_execution import _trusted_clock_v1 as trusted_clock

NOW = datetime(2026, 8, 14, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _fixed_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(trusted_clock, "utc_now", lambda: NOW)


def _claim(repo: InMemorySubmissionLegRepository, *, leg_index: int = 1, client_order_id: str = "cid-1"):
    return repo.claim_prepared(
        handoff_id=1, plan_snapshot_id=701, leg_index=leg_index, trading_account_id=1,
        venue="bitvavo", market="BTC-EUR", side="SELL", client_order_id=client_order_id,
        operator_id=777, immutable_price=Decimal("50000"), immutable_quantity=Decimal("0.1"),
    )


def test_claim_creates_then_is_idempotent() -> None:
    repo = InMemorySubmissionLegRepository()
    first, created_first = _claim(repo)
    second, created_second = _claim(repo)
    assert created_first is True
    assert created_second is False
    assert first.submission_leg_id == second.submission_leg_id


def test_conflicting_retry_fails_closed() -> None:
    repo = InMemorySubmissionLegRepository()
    _claim(repo)
    with pytest.raises(SubmissionLegConflictError):
        repo.claim_prepared(
            handoff_id=1, plan_snapshot_id=701, leg_index=1, trading_account_id=1,
            venue="bitvavo", market="BTC-EUR", side="SELL", client_order_id="cid-1",
            operator_id=777, immutable_price=Decimal("99"), immutable_quantity=Decimal("0.1"),
        )


def test_begin_attempt_transitions_and_single_winner() -> None:
    repo = InMemorySubmissionLegRepository()
    leg, _ = _claim(repo)
    updated, won = repo.begin_attempt(leg.submission_leg_id)
    assert won is True
    assert updated.submission_state == STATE_SUBMISSION_UNCERTAIN

    _again, won_again = repo.begin_attempt(leg.submission_leg_id)
    assert won_again is False


def test_resolve_accepted_and_rejected() -> None:
    repo = InMemorySubmissionLegRepository()
    leg, _ = _claim(repo)
    repo.begin_attempt(leg.submission_leg_id)
    resolved = repo.resolve_accepted(
        leg.submission_leg_id, new_state=STATE_SUBMITTED, broker_order_id="o-1", broker_status="open"
    )
    assert resolved.submission_state == STATE_SUBMITTED

    repo2 = InMemorySubmissionLegRepository()
    leg2, _ = _claim(repo2, leg_index=2, client_order_id="cid-2")
    repo2.begin_attempt(leg2.submission_leg_id)
    rejected = repo2.resolve_rejected(leg2.submission_leg_id, safe_error_code="X")
    assert rejected.submission_state == STATE_REJECTED


def test_reset_to_prepared_only_from_uncertain() -> None:
    repo = InMemorySubmissionLegRepository()
    leg, _ = _claim(repo)
    repo.begin_attempt(leg.submission_leg_id)
    reset_leg, won = repo.reset_to_prepared(leg.submission_leg_id)
    assert won is True
    assert reset_leg.submission_state == STATE_PREPARED


def test_never_touches_any_database_cursor_factory() -> None:
    # InMemorySubmissionLegRepository has no cursor_factory field/DB
    # dependency at all — a structural guarantee that it cannot write to
    # MariaDB no matter how it is called.
    repo = InMemorySubmissionLegRepository()
    assert not hasattr(repo, "cursor_factory")
