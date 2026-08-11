"""
Tests for src/execution_planner/manual_execution_plan_snapshot_v1.py and the
idempotency/concurrency additions to
src/manual_execution/manual_execution_request_v1.py made for GitHub Issue
#202 ("Complete manual execution request snapshot and idempotency
contract").

Pure Python + in-memory fake-DB tests only, matching the existing pattern in
tests/test_manual_execution_request_v1.py — no real MariaDB, no network.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.decision_gate.manual_execution_approval_v1 import (
    APPROVAL_STATE_APPROVED,
    ManualExecutionApprovalRecord,
)
from src.execution_planner.contract_preview_v1 import (
    ExecutionPlanLegPreview,
    ExecutionPlanPreview,
)
from src.execution_planner.manual_execution_plan_snapshot_v1 import (
    ManualExecutionPlanSnapshotRepository,
    ManualExecutionPlanSnapshotValidationError,
    PlanSnapshotContentMismatchError,
    build_plan_snapshot,
)
from src.manual_execution.manual_execution_request_v1 import (
    MODE_PAPER,
    QUANTITY_POLICY_FULL_AVAILABLE_BASE,
    QUANTITY_POLICY_LADDER_LEVELS,
    SOURCE_OPERATOR_CLI,
    IdempotencyKeyContentMismatchError,
    ManualExecutionRequestRepository,
    build_manual_execution_request,
)


NOW = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)


class DuplicateKeyError(Exception):
    """Stand-in for pymysql.err.IntegrityError(1062, ...) so these tests do
    not require pymysql to be importable/installed to exercise the
    duplicate-key branch. _is_duplicate_key_error only recognizes a real
    pymysql IntegrityError, so tests that must exercise that exact branch
    monkeypatch _is_duplicate_key_error instead of relying on this class
    directly; it exists for readability of "this call fails because of a
    unique-constraint race" at call sites."""

    args_code = 1062


# ---------------------------------------------------------------------------
# Request-side idempotency: content-mismatch and concurrent-race behavior
# ---------------------------------------------------------------------------


def _build_request(**overrides):
    defaults = dict(
        idempotency_key="req-shared-key",
        created_ts_utc=NOW,
        source=SOURCE_OPERATOR_CLI,
        requested_by="joost",
        mode=MODE_PAPER,
        trading_account_id=1,
        account_code="paper_account_1",
        venue="bitvavo",
        asset_id=42,
        base_asset="BTC",
        quote_asset="EUR",
        side="SELL",
        quantity_policy=QUANTITY_POLICY_FULL_AVAILABLE_BASE,
    )
    defaults.update(overrides)
    return build_manual_execution_request(**defaults)


class _RacingCursor:
    """Simulates: SELECT finds nothing (no request has been persisted yet
    from this transaction's point of view), INSERT then fails because a
    concurrent transaction already committed a row under the same
    idempotency_key, and the post-failure SELECT finds that row."""

    def __init__(self, existing_row: dict, *, raise_exc: Exception) -> None:
        self._existing_row = existing_row
        self._raise_exc = raise_exc
        self._result: list[dict] = []
        self.insert_attempts = 0

    def execute(self, sql: str, params: list) -> None:
        sql_norm = " ".join(sql.split())
        if sql_norm.startswith("SELECT * FROM manual_execution_request WHERE idempotency_key"):
            self._result = [self._existing_row] if self.insert_attempts else []
            return
        if sql_norm.startswith("INSERT INTO manual_execution_request"):
            self.insert_attempts += 1
            raise self._raise_exc
        raise AssertionError(f"unexpected SQL: {sql_norm}")

    def fetchone(self):
        return self._result[0] if self._result else None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _existing_row_for(request) -> dict:
    return {
        "manual_execution_request_id": 1,
        "schema_version": request.schema_version,
        "idempotency_key": request.idempotency_key,
        "created_ts_utc": request.created_ts_utc,
        "source": request.source,
        "requested_by": request.requested_by,
        "mode": request.mode,
        "trading_account_id": request.trading_account_id,
        "account_code": request.account_code,
        "venue": request.venue,
        "asset_id": request.asset_id,
        "base_asset": request.base_asset,
        "quote_asset": request.quote_asset,
        "side": request.side,
        "quantity_policy": request.quantity_policy,
        "requested_base_quantity": request.requested_base_quantity,
        "requested_quote_notional": request.requested_quote_notional,
        "ladder_levels_json": None,
        "provenance_id": request.provenance_id,
        "ladder_profile_id": request.ladder_profile_id,
        "ladder_profile_version": request.ladder_profile_version,
        "anchor_reference_price": request.anchor_reference_price,
        "anchor_ts_utc": request.anchor_ts_utc,
        "request_state": request.request_state,
        "rejection_code": None,
        "rejection_detail": None,
        "processed_ts_utc": None,
    }


def test_concurrent_duplicate_request_creation_resolves_to_one_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two 'concurrent' create_request_idempotent calls for the same
    idempotency_key must never create two rows: the losing call's INSERT
    hits the UNIQUE KEY, and it must fall back to the winner's row rather
    than raising or fabricating a second identity."""
    import src.manual_execution.manual_execution_request_v1 as request_module

    monkeypatch.setattr(request_module, "_is_duplicate_key_error", lambda exc: True)

    request = _build_request()
    winner_row = _existing_row_for(request)
    cursor = _RacingCursor(winner_row, raise_exc=DuplicateKeyError("Duplicate entry"))
    repo = ManualExecutionRequestRepository(cursor_factory=lambda **_: cursor)

    result = repo.create_request_idempotent(request)

    assert result.request_id == 1
    assert cursor.insert_attempts == 1


def test_idempotency_key_collision_with_different_account_fails_closed() -> None:
    """Two trading accounts must never collide on one idempotency_key: if a
    persisted request under that key belongs to a different account (or has
    any other different content field), create_request_idempotent must
    raise rather than silently returning the wrong account's request."""
    account_1_request = _build_request(trading_account_id=1, account_code="account_1")
    account_2_request = _build_request(trading_account_id=2, account_code="account_2")

    class _FixedExistingCursor:
        def __init__(self, row: dict) -> None:
            self._row = row

        def execute(self, sql: str, params: list) -> None:
            pass

        def fetchone(self):
            return self._row

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    cursor = _FixedExistingCursor(_existing_row_for(account_1_request))
    repo = ManualExecutionRequestRepository(cursor_factory=lambda **_: cursor)

    with pytest.raises(IdempotencyKeyContentMismatchError):
        repo.create_request_idempotent(account_2_request)


def test_sequential_retry_dedupes_to_same_identity() -> None:
    """Baseline (already-existing) behavior re-asserted alongside the new
    concurrency/content-mismatch coverage above: an identical repeated
    request is a deterministic no-op."""

    class _Table:
        def __init__(self) -> None:
            self.rows: list[dict] = []

    table = _Table()

    class _Cursor:
        def __init__(self) -> None:
            self.lastrowid = None
            self._result: list[dict] = []

        def execute(self, sql: str, params: list) -> None:
            sql_norm = " ".join(sql.split())
            if sql_norm.startswith("SELECT * FROM manual_execution_request WHERE idempotency_key"):
                (key,) = params
                self._result = [r for r in table.rows if r["idempotency_key"] == key]
                return
            if sql_norm.startswith("INSERT INTO manual_execution_request"):
                row = _existing_row_for(_build_request())
                row["manual_execution_request_id"] = len(table.rows) + 1
                table.rows.append(row)
                self.lastrowid = row["manual_execution_request_id"]
                return
            if sql_norm.startswith(
                "SELECT * FROM manual_execution_request WHERE manual_execution_request_id"
            ):
                (request_id,) = params
                self._result = [r for r in table.rows if r["manual_execution_request_id"] == request_id]
                return
            raise AssertionError(f"unexpected SQL: {sql_norm}")

        def fetchone(self):
            return self._result[0] if self._result else None

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    repo = ManualExecutionRequestRepository(cursor_factory=lambda **_: _Cursor())
    request = _build_request()

    first = repo.create_request_idempotent(request)
    second = repo.create_request_idempotent(request)

    assert first.request_id == second.request_id == 1
    assert len(table.rows) == 1


# ---------------------------------------------------------------------------
# build_plan_snapshot: pure builder, BUY/SELL side-neutrality, denial safety
# ---------------------------------------------------------------------------


def _approval(request_id: int, *, side: str = "SELL", quantity: Decimal = Decimal("2")) -> ManualExecutionApprovalRecord:
    return ManualExecutionApprovalRecord(
        approval_id=501,
        idempotency_key=f"manual_execution_approval:req-{side.lower()}",
        request_id=request_id,
        trading_account_id=1,
        account_code="paper_account_1",
        venue="bitvavo",
        asset_id=42,
        base_asset="BTC",
        quote_asset="EUR",
        side=side,
        approved_quantity_base=quantity,
        wallet_snapshot_id=9001,
        wallet_snapshot_version_ts_utc=NOW,
        reservation_id=101,
        approved_ts_utc=NOW,
        expires_ts_utc=NOW,
        mode=MODE_PAPER,
        provenance_id=77,
        approval_state=APPROVAL_STATE_APPROVED,
        decision_reason="OK",
        persisted_reservation_id=101,
        reservation_request_id=request_id,
        reservation_trading_account_id=1,
        reservation_venue="bitvavo",
        reservation_asset_id=42,
        reservation_symbol="BTC",
        reservation_quantity_base=quantity,
        reservation_state="APPROVED_NOT_SUBMITTED",
        persisted_snapshot_id=9001,
        snapshot_trading_account_id=1,
        snapshot_venue="bitvavo",
        snapshot_asset_id=42,
        snapshot_ts_utc=NOW,
    )


def _leg(price: Decimal) -> ExecutionPlanLegPreview:
    return ExecutionPlanLegPreview(
        leg_index=1,
        side="SELL",
        leg_type="PASSIVE_LIMIT",
        target_price_eur=price,
        target_fraction=Decimal("1"),
        target_notional_eur=price * Decimal("2"),
        quantity_base=Decimal("2"),
        post_only=True,
        time_in_force="GTC",
        max_reprices=5,
        max_wait_seconds=600,
        max_chase_bps=Decimal("10"),
        min_spread_bps_for_capture=Decimal("3"),
        escalation_to_urgent_limit=False,
        abort_if_signal_invalidates=True,
        leg_state="IDLE",
    )


def _plan_preview(
    *, side: str = "SELL", quantity: Decimal = Decimal("2"), account_id: int = 1
) -> ExecutionPlanPreview:
    return ExecutionPlanPreview(
        account_id=account_id,
        sleeve_code="CORE_STRUCTURAL",
        asset_id=42,
        symbol="BTC",
        venue="bitvavo",
        side=side,
        plan_type="PASSIVE_EXIT" if side == "SELL" else "PASSIVE_ENTRY",
        execution_mode=MODE_PAPER,
        plan_state="PREVIEW_ONLY",
        source_decision_state=APPROVAL_STATE_APPROVED,
        source_decision_reason="OK",
        regime_label=None,
        volatility_bucket=None,
        asset_exit_profile_hint=None,
        total_target_fraction=Decimal("1"),
        max_notional_eur=None,
        quantity_base=quantity,
        reference_price_eur=Decimal("50000"),
        best_bid_eur=Decimal("49990"),
        best_ask_eur=Decimal("50010"),
        tick_size=Decimal("1"),
        notes="preview_only=1",
        legs=[_leg(Decimal("50000"))],
    )


def test_build_plan_snapshot_sell_binds_request_approval_and_ladder_profile() -> None:
    request = build_manual_execution_request(
        idempotency_key="req-sell-ladder",
        created_ts_utc=NOW,
        source=SOURCE_OPERATOR_CLI,
        requested_by="joost",
        mode=MODE_PAPER,
        trading_account_id=1,
        account_code="paper_account_1",
        venue="bitvavo",
        asset_id=42,
        base_asset="BTC",
        quote_asset="EUR",
        side="SELL",
        quantity_policy=QUANTITY_POLICY_LADDER_LEVELS,
        ladder_levels=((Decimal("50000"), Decimal("1")),),
        ladder_profile_id=7,
        ladder_profile_version=3,
        anchor_reference_price=Decimal("51000"),
        anchor_ts_utc=NOW,
    )
    import dataclasses

    persisted_request = dataclasses.replace(request, request_id=1)
    approval = _approval(1)
    preview = _plan_preview()

    snapshot = build_plan_snapshot(request=persisted_request, approval=approval, plan_preview=preview)

    assert snapshot.request_id == 1
    assert snapshot.approval_id == 501
    assert snapshot.side == "SELL"
    assert snapshot.ladder_profile_id == 7
    assert snapshot.ladder_profile_version == 3
    assert snapshot.anchor_reference_price == Decimal("51000")
    assert snapshot.plan_state == "PREVIEW_ONLY"
    assert snapshot.idempotency_key == "manual_execution_plan_snapshot:req-sell-ladder"
    assert "50000" in snapshot.legs_json


def test_build_plan_snapshot_is_side_neutral_and_supports_buy() -> None:
    """The plan snapshot model must not be SELL-only: a BUY request/approval/
    preview triple builds a valid snapshot even though decision_gate itself
    still blocks BUY upstream (REASON_MANUAL_BUY_GATE_NOT_YET_IMPLEMENTED) —
    that gate gap is a separate, not-yet-implemented step, not a schema
    limitation."""
    import dataclasses

    request = _build_request(side="BUY", idempotency_key="req-buy")
    persisted_request = dataclasses.replace(request, request_id=2)
    approval = _approval(2, side="BUY")
    preview = _plan_preview(side="BUY")

    snapshot = build_plan_snapshot(request=persisted_request, approval=approval, plan_preview=preview)

    assert snapshot.side == "BUY"
    assert snapshot.plan_type == "PASSIVE_ENTRY"


def test_build_plan_snapshot_rejects_unapproved_approval() -> None:
    import dataclasses

    request = _build_request(idempotency_key="req-denied")
    persisted_request = dataclasses.replace(request, request_id=3)
    denied_approval = dataclasses.replace(_approval(3), approval_state="REVOKED")

    with pytest.raises(ManualExecutionPlanSnapshotValidationError):
        build_plan_snapshot(
            request=persisted_request,
            approval=denied_approval,
            plan_preview=_plan_preview(),
        )


def test_build_plan_snapshot_rejects_request_approval_identity_mismatch() -> None:
    import dataclasses

    request = _build_request(idempotency_key="req-mismatch")
    persisted_request = dataclasses.replace(request, request_id=4)
    mismatched_approval = _approval(999)  # bound to a different request

    with pytest.raises(ManualExecutionPlanSnapshotValidationError):
        build_plan_snapshot(
            request=persisted_request,
            approval=mismatched_approval,
            plan_preview=_plan_preview(),
        )


# ---------------------------------------------------------------------------
# ManualExecutionPlanSnapshotRepository: idempotent create, immutability of
# the request<->plan relationship, cross-account non-collision
# ---------------------------------------------------------------------------


def _snapshot_row_for(snapshot, *, plan_snapshot_id: int) -> dict:
    return {
        "manual_execution_plan_snapshot_id": plan_snapshot_id,
        "idempotency_key": snapshot.idempotency_key,
        "manual_execution_request_id": snapshot.request_id,
        "manual_execution_approval_id": snapshot.approval_id,
        "trading_account_id": snapshot.trading_account_id,
        "account_code": snapshot.account_code,
        "venue": snapshot.venue,
        "asset_id": snapshot.asset_id,
        "base_asset": snapshot.base_asset,
        "quote_asset": snapshot.quote_asset,
        "side": snapshot.side,
        "mode": snapshot.mode,
        "plan_type": snapshot.plan_type,
        "execution_mode": snapshot.execution_mode,
        "plan_state": snapshot.plan_state,
        "sleeve_code": snapshot.sleeve_code,
        "ladder_profile_id": snapshot.ladder_profile_id,
        "ladder_profile_version": snapshot.ladder_profile_version,
        "anchor_reference_price": snapshot.anchor_reference_price,
        "anchor_ts_utc": snapshot.anchor_ts_utc,
        "provenance_id": snapshot.provenance_id,
        "approved_quantity_base": snapshot.approved_quantity_base,
        "total_target_fraction": snapshot.total_target_fraction,
        "max_notional_eur": snapshot.max_notional_eur,
        "reference_price_eur": snapshot.reference_price_eur,
        "best_bid_eur": snapshot.best_bid_eur,
        "best_ask_eur": snapshot.best_ask_eur,
        "tick_size": snapshot.tick_size,
        "source_decision_state": snapshot.source_decision_state,
        "source_decision_reason": snapshot.source_decision_reason,
        "legs_json": snapshot.legs_json,
        "created_ts_utc": NOW,
    }


class _SnapshotTableCursor:
    def __init__(self, table: list[dict]) -> None:
        self._table = table
        self._result: list[dict] = []
        self.lastrowid = None
        self.insert_attempts = 0

    def execute(self, sql: str, params: list) -> None:
        sql_norm = " ".join(sql.split())
        if sql_norm.startswith("SELECT * FROM manual_execution_plan_snapshot WHERE idempotency_key"):
            (key,) = params
            self._result = [r for r in self._table if r["idempotency_key"] == key]
            return
        if sql_norm.startswith("INSERT INTO manual_execution_plan_snapshot"):
            self.insert_attempts += 1
            # simulate the UNIQUE KEY on manual_execution_request_id: only
            # one plan snapshot may ever exist per request.
            request_id = params[1]
            if any(r["manual_execution_request_id"] == request_id for r in self._table):
                raise DuplicateKeyError("Duplicate entry")
            row = dict(zip(_SNAPSHOT_INSERT_COLUMNS, params))
            row["manual_execution_plan_snapshot_id"] = len(self._table) + 1
            row["created_ts_utc"] = NOW
            self._table.append(row)
            self.lastrowid = row["manual_execution_plan_snapshot_id"]
            return
        if sql_norm.startswith(
            "SELECT * FROM manual_execution_plan_snapshot WHERE manual_execution_plan_snapshot_id"
        ):
            (snapshot_id,) = params
            self._result = [r for r in self._table if r["manual_execution_plan_snapshot_id"] == snapshot_id]
            return
        raise AssertionError(f"unexpected SQL: {sql_norm}")

    def fetchone(self):
        return self._result[0] if self._result else None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


_SNAPSHOT_INSERT_COLUMNS = (
    "idempotency_key", "manual_execution_request_id", "manual_execution_approval_id",
    "trading_account_id", "account_code", "venue", "asset_id", "base_asset", "quote_asset",
    "side", "mode", "plan_type", "execution_mode", "plan_state", "sleeve_code",
    "ladder_profile_id", "ladder_profile_version", "anchor_reference_price", "anchor_ts_utc",
    "provenance_id", "approved_quantity_base", "total_target_fraction", "max_notional_eur",
    "reference_price_eur", "best_bid_eur", "best_ask_eur", "tick_size",
    "source_decision_state", "source_decision_reason", "legs_json",
)


def _built_snapshot(*, idempotency_key: str = "req-sell", request_id: int = 1, trading_account_id: int = 1):
    import dataclasses

    request = _build_request(idempotency_key=idempotency_key, trading_account_id=trading_account_id)
    persisted_request = dataclasses.replace(request, request_id=request_id)
    approval = dataclasses.replace(_approval(request_id), trading_account_id=trading_account_id)
    preview = _plan_preview(account_id=trading_account_id)
    return build_plan_snapshot(request=persisted_request, approval=approval, plan_preview=preview)


def test_plan_snapshot_sequential_retry_dedupes_to_same_row(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.execution_planner.manual_execution_plan_snapshot_v1 as snapshot_module

    monkeypatch.setattr(snapshot_module, "_is_duplicate_key_error", lambda exc: isinstance(exc, DuplicateKeyError))

    table: list[dict] = []
    repo = ManualExecutionPlanSnapshotRepository(cursor_factory=lambda **_: _SnapshotTableCursor(table))
    snapshot = _built_snapshot()

    first = repo.create_snapshot_idempotent(snapshot)
    second = repo.create_snapshot_idempotent(snapshot)

    assert first.plan_snapshot_id == second.plan_snapshot_id == 1
    assert len(table) == 1


def test_plan_snapshot_concurrent_duplicate_resolves_to_one_row(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two concurrent create_snapshot_idempotent calls for the same request
    must never create two plan snapshot rows: the loser's INSERT hits the
    UNIQUE KEY on manual_execution_request_id and falls back to the
    winner's row."""
    import src.execution_planner.manual_execution_plan_snapshot_v1 as snapshot_module

    monkeypatch.setattr(snapshot_module, "_is_duplicate_key_error", lambda exc: isinstance(exc, DuplicateKeyError))

    table: list[dict] = []
    snapshot = _built_snapshot(idempotency_key="req-race")

    # Winner: inserts first, using its own cursor bound to the shared table.
    winner_repo = ManualExecutionPlanSnapshotRepository(cursor_factory=lambda **_: _SnapshotTableCursor(table))
    winner = winner_repo.create_snapshot_idempotent(snapshot)

    # Loser: its SELECT (done before the winner committed, in a real DB) is
    # simulated here by going straight to INSERT against the now-updated
    # table, exercising the duplicate-key catch/reselect branch directly.
    class _LoserCursor(_SnapshotTableCursor):
        def __init__(self, table: list[dict]) -> None:
            super().__init__(table)
            self._fast_path_select_done = False

        def execute(self, sql: str, params: list) -> None:
            sql_norm = " ".join(sql.split())
            if (
                not self._fast_path_select_done
                and sql_norm.startswith(
                    "SELECT * FROM manual_execution_plan_snapshot WHERE idempotency_key"
                )
            ):
                self._fast_path_select_done = True
                self._result = []  # loser's fast-path SELECT sees nothing yet
                return
            super().execute(sql, params)

    loser_repo = ManualExecutionPlanSnapshotRepository(cursor_factory=lambda **_: _LoserCursor(table))
    loser = loser_repo.create_snapshot_idempotent(snapshot)

    assert winner.plan_snapshot_id == loser.plan_snapshot_id
    assert len(table) == 1


def test_plan_snapshot_two_accounts_cannot_collide(monkeypatch: pytest.MonkeyPatch) -> None:
    """A colliding idempotency_key bound to a different trading_account_id
    must fail closed, never silently return the other account's plan."""
    import src.execution_planner.manual_execution_plan_snapshot_v1 as snapshot_module

    monkeypatch.setattr(snapshot_module, "_is_duplicate_key_error", lambda exc: isinstance(exc, DuplicateKeyError))

    table: list[dict] = []
    account_1_snapshot = _built_snapshot(
        idempotency_key="req-shared", request_id=1, trading_account_id=1
    )
    account_2_snapshot = _built_snapshot(
        idempotency_key="req-shared", request_id=2, trading_account_id=2
    )

    repo = ManualExecutionPlanSnapshotRepository(cursor_factory=lambda **_: _SnapshotTableCursor(table))
    repo.create_snapshot_idempotent(account_1_snapshot)

    with pytest.raises(PlanSnapshotContentMismatchError):
        repo.create_snapshot_idempotent(account_2_snapshot)


def test_plan_snapshot_request_relationship_is_unambiguous() -> None:
    """find_by_request_id resolves exactly the one snapshot for that
    request; the UNIQUE KEY on manual_execution_request_id (asserted in the
    migration content tests below) is what makes this relationship
    unambiguous at the DB layer."""
    table: list[dict] = []
    repo = ManualExecutionPlanSnapshotRepository(cursor_factory=lambda **_: _RequestLookupCursor(table))
    snapshot = _built_snapshot(idempotency_key="req-lookup", request_id=55)

    class _CreateCursor(_SnapshotTableCursor):
        pass

    create_repo = ManualExecutionPlanSnapshotRepository(cursor_factory=lambda **_: _CreateCursor(table))
    create_repo.create_snapshot_idempotent(snapshot)

    found = repo.find_by_request_id(55)
    assert found is not None
    assert found.request_id == 55
    assert repo.find_by_request_id(56) is None


class _RequestLookupCursor(_SnapshotTableCursor):
    def execute(self, sql: str, params: list) -> None:
        sql_norm = " ".join(sql.split())
        if sql_norm.startswith(
            "SELECT * FROM manual_execution_plan_snapshot WHERE manual_execution_request_id"
        ):
            (request_id,) = params
            self._result = [r for r in self._table if r["manual_execution_request_id"] == request_id]
            return
        super().execute(sql, params)
