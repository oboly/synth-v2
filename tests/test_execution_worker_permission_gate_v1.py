from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from src.execution import worker
from src.execution.permission_gate_v1 import (
    BROKER_WRITE_PERMISSION_ENV,
    BROKER_WRITE_PERMISSION_GRANTED_VALUE,
    LIVE_EXECUTION_PERMISSION_ENV,
    LIVE_EXECUTION_PERMISSION_GRANTED_VALUE,
    LiveExecutionPermissionError,
    PermissionEvidence,
    TradingAccountState,
    validate_live_execution_permission,
)


NOW = datetime(2026, 7, 21, 12, 0, 0)
MIGRATION_PATH = Path("db/migrations/20260721_executor_permission_evidence_v1.sql")


class FakePermissionRepo:
    def __init__(
        self,
        *,
        account: TradingAccountState | None,
        evidence: list[PermissionEvidence],
        filter_current: bool = False,
    ) -> None:
        self.account = account
        self.evidence = evidence
        self.filter_current = filter_current

    def fetch_account_state(self, trading_account_id: int) -> TradingAccountState | None:
        return self.account

    def fetch_current_permission_evidence(
        self,
        execution_plan_id: int,
        evaluation_ts_utc: datetime,
    ) -> list[PermissionEvidence]:
        if not self.filter_current:
            return list(self.evidence)

        return [
            row
            for row in self.evidence
            if row.execution_plan_id == execution_plan_id
            and row.evidence_state == "ACTIVE"
            and row.revoked_ts_utc is None
            and row.superseded_by_evidence_id is None
            and row.permitted_ts_utc <= evaluation_ts_utc
            and row.valid_until_ts_utc is not None
            and row.valid_until_ts_utc >= evaluation_ts_utc
        ][:2]

    def fetch_permission_evidence_history(self, execution_plan_id: int) -> list[PermissionEvidence]:
        return [
            row
            for row in self.evidence
            if row.execution_plan_id == execution_plan_id
        ]


def _row_from_evidence(evidence: PermissionEvidence) -> dict[str, Any]:
    return {
        "execution_permission_evidence_id": evidence.execution_permission_evidence_id,
        "execution_plan_id": evidence.execution_plan_id,
        "trading_account_id": evidence.trading_account_id,
        "venue": evidence.venue,
        "asset_id": evidence.asset_id,
        "market": evidence.market,
        "execution_intent": evidence.execution_intent,
        "action_type": evidence.action_type,
        "requested_side": evidence.requested_side,
        "permission_state": evidence.permission_state,
        "decision_state": evidence.decision_state,
        "evidence_state": evidence.evidence_state,
        "permitted_ts_utc": evidence.permitted_ts_utc,
        "valid_until_ts_utc": evidence.valid_until_ts_utc,
        "revoked_ts_utc": evidence.revoked_ts_utc,
        "superseded_by_evidence_id": evidence.superseded_by_evidence_id,
    }


class CapturingCursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    def execute(self, sql: str, params: tuple[Any, ...]) -> None:
        self.executed.append((sql, params))

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self.rows)


class FakeDbCursor:
    def __init__(self, cursor: CapturingCursor) -> None:
        self.cursor = cursor

    def __enter__(self) -> tuple[None, CapturingCursor]:
        return None, self.cursor

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None


class FakeBrokerClient:
    def __init__(self) -> None:
        self.placed_orders: list[Any] = []
        self.cancelled_orders: list[tuple[str, str]] = []
        self.polled_orders: list[tuple[str, str]] = []

    def get_book(self, market: str, depth: int = 5) -> dict[str, Any]:
        return {"bids": [["99.00", "1"]], "asks": [["101.00", "1"]]}

    def place_order(self, order: Any) -> dict[str, str]:
        self.placed_orders.append(order)
        return {"orderId": "order-1"}

    def cancel_order(self, market: str, order_id: str) -> dict[str, str]:
        self.cancelled_orders.append((market, order_id))
        return {"orderId": order_id}

    def get_order(self, market: str, order_id: str) -> dict[str, str]:
        self.polled_orders.append((market, order_id))
        return {"orderId": order_id}


def _plan(**overrides: Any) -> worker.PlanRuntime:
    base = worker.PlanRuntime(
        execution_plan_id=100,
        trading_account_id=7,
        asset_id=42,
        symbol="BTC",
        sleeve_code="CORE",
        venue="bitvavo",
        side="buy",
        desired_action="SPREAD_CAPTURE_PASSIVE",
        execution_intent="PLACE_PASSIVE_LIMIT",
        execution_mode="live",
        target_fraction=Decimal("0.10"),
        reference_price_eur=Decimal("100.00"),
        passive_price_eur=Decimal("99.00"),
        urgent_limit_price_eur=Decimal("101.00"),
        max_reprices=2,
        max_wait_seconds=1800,
        max_chase_bps=Decimal("15"),
        min_spread_bps_for_capture=Decimal("3"),
        escalation_to_urgent_limit=True,
        abort_if_signal_invalidates=True,
        plan_state="IDLE",
        notes="test",
        plan_ts_utc=NOW,
        valid_until_ts_utc=NOW + timedelta(days=365),
    )
    return replace(base, **overrides)


def _account(**overrides: Any) -> TradingAccountState:
    base = TradingAccountState(
        trading_account_id=7,
        venue="bitvavo",
        enabled=True,
        live_trading_enabled=True,
    )
    return replace(base, **overrides)


def _evidence(**overrides: Any) -> PermissionEvidence:
    base = PermissionEvidence(
        execution_permission_evidence_id=1,
        execution_plan_id=100,
        trading_account_id=7,
        venue="bitvavo",
        asset_id=42,
        market="BTC-EUR",
        execution_intent="PLACE_PASSIVE_LIMIT",
        action_type="SPREAD_CAPTURE_PASSIVE",
        requested_side="BUY",
        permission_state="EXECUTION_PERMITTED",
        decision_state="EXECUTION_ALLOWED",
        evidence_state="ACTIVE",
        permitted_ts_utc=NOW - timedelta(days=365),
        valid_until_ts_utc=NOW + timedelta(days=365),
        revoked_ts_utc=None,
        superseded_by_evidence_id=None,
    )
    return replace(base, **overrides)


def _env(
    *,
    live_auth: bool = True,
    broker_write: bool = True,
) -> dict[str, str]:
    values: dict[str, str] = {}
    if live_auth:
        values[LIVE_EXECUTION_PERMISSION_ENV] = LIVE_EXECUTION_PERMISSION_GRANTED_VALUE
    if broker_write:
        values[BROKER_WRITE_PERMISSION_ENV] = BROKER_WRITE_PERMISSION_GRANTED_VALUE
    return values


def _assert_gate_blocks(
    *,
    plan: worker.PlanRuntime | None = None,
    account: TradingAccountState | None = None,
    evidence: list[PermissionEvidence] | None = None,
    env: dict[str, str] | None = None,
    filter_current: bool = False,
) -> None:
    with pytest.raises(LiveExecutionPermissionError):
        validate_live_execution_permission(
            plan=plan or _plan(),
            market="BTC-EUR",
            repo=FakePermissionRepo(
                account=_account() if account is None else account,
                evidence=[_evidence()] if evidence is None else evidence,
                filter_current=filter_current,
            ),
            env=_env() if env is None else env,
            now_utc=NOW,
        )


def test_one_current_active_evidence_row_passes_selection() -> None:
    evidence = validate_live_execution_permission(
        plan=_plan(),
        market="BTC-EUR",
        repo=FakePermissionRepo(
            account=_account(),
            evidence=[_evidence()],
            filter_current=True,
        ),
        env=_env(),
        now_utc=NOW,
    )

    assert evidence.execution_permission_evidence_id == 1


def test_missing_decision_gate_evidence_blocks() -> None:
    _assert_gate_blocks(evidence=[])


def test_zero_current_evidence_rows_block() -> None:
    _assert_gate_blocks(
        evidence=[_evidence(valid_until_ts_utc=NOW - timedelta(seconds=1))],
        filter_current=True,
    )


def test_multiple_current_evidence_rows_block() -> None:
    _assert_gate_blocks(
        evidence=[_evidence(), _evidence(execution_permission_evidence_id=2)],
        filter_current=True,
    )


def test_multiple_evidence_rows_block() -> None:
    _assert_gate_blocks(evidence=[_evidence(), _evidence(execution_permission_evidence_id=2)])


def test_historical_revoked_plus_current_selects_current_row() -> None:
    selected = validate_live_execution_permission(
        plan=_plan(),
        market="BTC-EUR",
        repo=FakePermissionRepo(
            account=_account(),
            evidence=[
                _evidence(
                    execution_permission_evidence_id=1,
                    evidence_state="REVOKED",
                    revoked_ts_utc=NOW - timedelta(seconds=1),
                ),
                _evidence(execution_permission_evidence_id=2),
            ],
            filter_current=True,
        ),
        env=_env(),
        now_utc=NOW,
    )

    assert selected.execution_permission_evidence_id == 2


def test_historical_superseded_plus_current_selects_current_row() -> None:
    selected = validate_live_execution_permission(
        plan=_plan(),
        market="BTC-EUR",
        repo=FakePermissionRepo(
            account=_account(),
            evidence=[
                _evidence(
                    execution_permission_evidence_id=1,
                    evidence_state="SUPERSEDED",
                    superseded_by_evidence_id=2,
                ),
                _evidence(execution_permission_evidence_id=2),
            ],
            filter_current=True,
        ),
        env=_env(),
        now_utc=NOW,
    )

    assert selected.execution_permission_evidence_id == 2


def test_expired_active_plus_current_selects_current_row() -> None:
    selected = validate_live_execution_permission(
        plan=_plan(),
        market="BTC-EUR",
        repo=FakePermissionRepo(
            account=_account(),
            evidence=[
                _evidence(
                    execution_permission_evidence_id=1,
                    valid_until_ts_utc=NOW - timedelta(seconds=1),
                ),
                _evidence(execution_permission_evidence_id=2),
            ],
            filter_current=True,
        ),
        env=_env(),
        now_utc=NOW,
    )

    assert selected.execution_permission_evidence_id == 2


def test_future_not_yet_valid_plus_current_selects_current_row() -> None:
    selected = validate_live_execution_permission(
        plan=_plan(),
        market="BTC-EUR",
        repo=FakePermissionRepo(
            account=_account(),
            evidence=[
                _evidence(
                    execution_permission_evidence_id=1,
                    permitted_ts_utc=NOW + timedelta(seconds=1),
                ),
                _evidence(execution_permission_evidence_id=2),
            ],
            filter_current=True,
        ),
        env=_env(),
        now_utc=NOW,
    )

    assert selected.execution_permission_evidence_id == 2


def test_active_row_with_revoked_timestamp_is_ignored_as_current() -> None:
    selected = validate_live_execution_permission(
        plan=_plan(),
        market="BTC-EUR",
        repo=FakePermissionRepo(
            account=_account(),
            evidence=[
                _evidence(
                    execution_permission_evidence_id=1,
                    revoked_ts_utc=NOW - timedelta(seconds=1),
                ),
                _evidence(execution_permission_evidence_id=2),
            ],
            filter_current=True,
        ),
        env=_env(),
        now_utc=NOW,
    )

    assert selected.execution_permission_evidence_id == 2


def test_active_row_with_superseded_by_is_ignored_as_current() -> None:
    selected = validate_live_execution_permission(
        plan=_plan(),
        market="BTC-EUR",
        repo=FakePermissionRepo(
            account=_account(),
            evidence=[
                _evidence(
                    execution_permission_evidence_id=1,
                    superseded_by_evidence_id=2,
                ),
                _evidence(execution_permission_evidence_id=2),
            ],
            filter_current=True,
        ),
        env=_env(),
        now_utc=NOW,
    )

    assert selected.execution_permission_evidence_id == 2


def test_historical_rows_remain_queryable_for_audit() -> None:
    repo = FakePermissionRepo(
        account=_account(),
        evidence=[
            _evidence(
                execution_permission_evidence_id=1,
                evidence_state="REVOKED",
                revoked_ts_utc=NOW - timedelta(seconds=1),
            ),
            _evidence(execution_permission_evidence_id=2),
        ],
        filter_current=True,
    )

    assert [
        row.execution_permission_evidence_id
        for row in repo.fetch_permission_evidence_history(100)
    ] == [1, 2]
    assert [
        row.execution_permission_evidence_id
        for row in repo.fetch_current_permission_evidence(100, NOW)
    ] == [2]


def test_repository_current_evidence_query_filters_only_current_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.execution import permission_gate_v1

    cursor = CapturingCursor([_row_from_evidence(_evidence())])
    monkeypatch.setattr(
        permission_gate_v1,
        "db_cursor",
        lambda commit=False: FakeDbCursor(cursor),
    )

    rows = permission_gate_v1.ExecutionPermissionRepository().fetch_current_permission_evidence(100, NOW)

    assert len(rows) == 1
    sql, params = cursor.executed[0]
    assert "WHERE execution_plan_id = %s" in sql
    assert "evidence_state = 'ACTIVE'" in sql
    assert "revoked_ts_utc IS NULL" in sql
    assert "superseded_by_evidence_id IS NULL" in sql
    assert "permitted_ts_utc <= %s" in sql
    assert "valid_until_ts_utc >= %s" in sql
    assert "LIMIT 1" not in sql
    assert params == (100, NOW, NOW)


def test_repository_history_query_keeps_historical_rows_auditable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.execution import permission_gate_v1

    cursor = CapturingCursor(
        [
            _row_from_evidence(
                _evidence(
                    execution_permission_evidence_id=1,
                    evidence_state="REVOKED",
                    revoked_ts_utc=NOW - timedelta(seconds=1),
                )
            ),
            _row_from_evidence(_evidence(execution_permission_evidence_id=2)),
        ]
    )
    monkeypatch.setattr(
        permission_gate_v1,
        "db_cursor",
        lambda commit=False: FakeDbCursor(cursor),
    )

    rows = permission_gate_v1.ExecutionPermissionRepository().fetch_permission_evidence_history(100)

    assert [row.execution_permission_evidence_id for row in rows] == [1, 2]
    sql, params = cursor.executed[0]
    assert "WHERE execution_plan_id = %s" in sql
    assert "evidence_state = 'ACTIVE'" not in sql
    assert params == (100,)


def test_denied_decision_blocks() -> None:
    _assert_gate_blocks(evidence=[_evidence(decision_state="BLOCKED_BALANCE")])


def test_wrong_execution_plan_id_blocks() -> None:
    _assert_gate_blocks(evidence=[_evidence(execution_plan_id=101)])


def test_wrong_trading_account_id_blocks() -> None:
    _assert_gate_blocks(evidence=[_evidence(trading_account_id=8)])


def test_wrong_venue_blocks() -> None:
    _assert_gate_blocks(evidence=[_evidence(venue="coinbase")])


def test_wrong_execution_intent_blocks() -> None:
    _assert_gate_blocks(evidence=[_evidence(execution_intent="PREPARE_PLAN")])


def test_missing_planner_execution_intent_blocks() -> None:
    _assert_gate_blocks(plan=_plan(execution_intent=None), evidence=[_evidence()])


def test_legacy_desired_action_without_explicit_intent_blocks() -> None:
    _assert_gate_blocks(
        plan=_plan(desired_action="SPREAD_CAPTURE_PASSIVE", execution_intent=None),
        evidence=[_evidence(execution_intent="PLACE_PASSIVE_LIMIT")],
    )


def test_executor_does_not_derive_intent_from_desired_action() -> None:
    _assert_gate_blocks(
        plan=_plan(desired_action="ENTER_LONG", execution_intent=None),
        evidence=[
            _evidence(
                execution_intent="PLACE_PASSIVE_LIMIT",
                action_type="ENTER_LONG",
            )
        ],
    )


def test_decision_gate_evidence_cannot_replace_planner_intent() -> None:
    _assert_gate_blocks(
        plan=_plan(execution_intent=None),
        evidence=[_evidence(execution_intent="PLACE_PASSIVE_LIMIT")],
    )


def test_planner_intent_cannot_replace_decision_gate_permission() -> None:
    _assert_gate_blocks(plan=_plan(execution_intent="PLACE_PASSIVE_LIMIT"), evidence=[])


def test_wrong_execution_action_blocks() -> None:
    _assert_gate_blocks(evidence=[_evidence(action_type="ENTER_LONG")])


def test_stale_evidence_blocks() -> None:
    _assert_gate_blocks(evidence=[_evidence(valid_until_ts_utc=NOW - timedelta(seconds=1))])


def test_revoked_evidence_blocks() -> None:
    _assert_gate_blocks(evidence=[_evidence(revoked_ts_utc=NOW - timedelta(minutes=1))])


def test_superseded_evidence_blocks() -> None:
    _assert_gate_blocks(evidence=[_evidence(superseded_by_evidence_id=2)])


def test_disabled_account_blocks() -> None:
    _assert_gate_blocks(account=_account(enabled=False))


def test_live_trading_enabled_false_blocks() -> None:
    _assert_gate_blocks(account=_account(live_trading_enabled=False))


def test_missing_production_authorization_blocks() -> None:
    _assert_gate_blocks(env=_env(live_auth=False, broker_write=True))


def test_missing_broker_write_permission_blocks() -> None:
    _assert_gate_blocks(env=_env(live_auth=True, broker_write=False))


def test_credentials_alone_do_not_authorize_execution() -> None:
    _assert_gate_blocks(evidence=[])


def test_all_exact_gates_present_reaches_mocked_broker_once(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = FakeBrokerClient()
    events: list[tuple[int, str, str]] = []
    states: list[tuple[int, str]] = []

    monkeypatch.setenv(LIVE_EXECUTION_PERMISSION_ENV, LIVE_EXECUTION_PERMISSION_GRANTED_VALUE)
    monkeypatch.setenv(BROKER_WRITE_PERMISSION_ENV, BROKER_WRITE_PERMISSION_GRANTED_VALUE)
    monkeypatch.setattr(worker, "_fetch_actionable_plans", lambda limit=50: [_plan()])
    monkeypatch.setattr(worker, "_fetch_latest_events_for_plans", lambda plan_ids: {})
    monkeypatch.setattr(worker, "_write_event", lambda plan_id, event_type, note, order_price=None: events.append((plan_id, event_type, note)))
    monkeypatch.setattr(worker, "_update_plan_state", lambda plan_id, state: states.append((plan_id, state)))

    result = worker.process_execution_plans(
        execution_mode="live",
        broker_client_factory=lambda: fake_client,
        permission_repo=FakePermissionRepo(account=_account(), evidence=[_evidence()]),
    )

    assert result["live_placed"] == 1
    assert len(fake_client.placed_orders) == 1
    assert fake_client.cancelled_orders == []
    assert fake_client.polled_orders == []
    assert events[0][1] == "LIVE_PLACE_PASSIVE"
    assert states == [(100, "MONITOR_QUEUE")]


def test_paper_execution_stays_broker_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = FakeBrokerClient()
    events: list[str] = []

    monkeypatch.delenv(LIVE_EXECUTION_PERMISSION_ENV, raising=False)
    monkeypatch.delenv(BROKER_WRITE_PERMISSION_ENV, raising=False)
    monkeypatch.setattr(
        worker,
        "_fetch_actionable_plans",
        lambda limit=50: [_plan(execution_mode="paper")],
    )
    monkeypatch.setattr(worker, "_fetch_latest_events_for_plans", lambda plan_ids: {})
    monkeypatch.setattr(worker, "_write_event", lambda plan_id, event_type, note, order_price=None: events.append(event_type))
    monkeypatch.setattr(worker, "_update_plan_state", lambda plan_id, state: None)

    result = worker.process_execution_plans(
        execution_mode="paper",
        broker_client_factory=lambda: pytest.fail("live broker client must not be constructed for paper"),
        market_data_client_factory=lambda: fake_client,
        permission_repo=FakePermissionRepo(account=None, evidence=[]),
    )

    assert result["paper_placed"] == 1
    assert events == ["PAPER_PLACE_PASSIVE"]
    assert fake_client.placed_orders == []
    assert fake_client.cancelled_orders == []
    assert fake_client.polled_orders == []


def test_live_permission_evidence_cannot_convert_paper_intent_to_live() -> None:
    paper_plan = _plan(
        execution_mode="paper",
        desired_action="PREPARE_PLAN",
        execution_intent="PREPARE_PLAN",
    )
    _assert_gate_blocks(plan=paper_plan, evidence=[_evidence(execution_intent="PLACE_PASSIVE_LIMIT")])


def test_executor_does_not_invoke_selection_engine_or_recalculate_decision_gate_policy() -> None:
    source = Path("src/execution/worker.py").read_text(encoding="utf-8")
    gate_source = Path("src/execution/permission_gate_v1.py").read_text(encoding="utf-8")
    joined = source + "\n" + gate_source

    assert "selection_engine" not in joined
    assert "evaluate_selection_for_account" not in joined
    assert "DecisionGateRepository" not in joined
    assert "decision_gate_v1" not in joined
    assert "INTENT_BY_DESIRED_ACTION" not in joined
    assert "expected_execution_intent" not in joined


def test_migration_defines_explicit_additive_evidence_contract() -> None:
    sql = MIGRATION_PATH.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS execution_permission_evidence" in sql
    for column in (
        "decision_gate_audit_log_id",
        "execution_plan_id",
        "trading_account_id",
        "venue",
        "asset_id",
        "market",
        "execution_intent",
        "action_type",
        "permission_state",
        "decision_state",
        "evidence_state",
        "permitted_ts_utc",
        "valid_until_ts_utc",
        "revoked_ts_utc",
        "superseded_by_evidence_id",
    ):
        assert column in sql

    assert "encrypted" not in sql.lower()
    assert "credential_id" not in sql.lower()
    assert "api_key" not in sql.lower()
    assert "api_secret" not in sql.lower()
    assert "REFERENCES decision_gate_audit_log" in sql
    assert "REFERENCES execution_plan" in sql
    assert "REFERENCES trading_account" in sql
    assert "ADD COLUMN IF NOT EXISTS execution_intent" in sql
    assert "chk_epe_valid_window_v1" in sql
    assert "chk_epe_active_not_revoked_v1" in sql
    assert "chk_epe_active_not_superseded_v1" in sql
