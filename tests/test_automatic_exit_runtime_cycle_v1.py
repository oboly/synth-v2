from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.account.account_state_snapshot_alignment_v1 import AccountStateSnapshotRunV1
from src.decision_gate.automatic_exit_gate_v1 import (
    REASON_BLOCKING_CONFLICT,
    REASON_EXECUTION_PERMISSION_DISABLED,
    STATE_APPROVED,
    STATE_DENIED,
)
from src.decision_gate.free_base_quantity_v1 import WalletAvailableSnapshot
from src.exit_policy.automatic_exit_candidate_v1 import STATE_CANDIDATE, STATE_NO_ACTION, STATE_NON_ACTIONABLE
from src.exit_policy.automatic_exit_runtime_contract_v1 import (
    AutomaticExitPlanningPermissionV1,
    AutomaticExitProfileV1,
)
from src.exit_policy.automatic_exit_runtime_evidence_v1 import (
    PLANNER_STATE_NOT_ATTEMPTED,
    PLANNER_STATE_PLANNED,
    PLANNER_STATE_REJECTED,
    REASON_ACCOUNT_STATE_SNAPSHOT_STALE,
    REASON_MARKET_PRICE_STALE,
    REASON_RESERVATION_RECONCILIATION_PENDING,
    AutomaticExitRuntimeCycleError,
    AutomaticExitRuntimeEvidenceV1,
    build_automatic_exit_audit_payload_v1,
    run_automatic_exit_runtime_cycle_v1,
)
from src.market_rules.venue_execution_constraints_v1 import STATUS_FRESH, VenueExecutionConstraints


NOW = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)


def _account_state_snapshot(**overrides: object) -> AccountStateSnapshotRunV1:
    values: dict[str, object] = dict(
        account_state_snapshot_run_id=555, trading_account_id=7, venue="bitvavo",
        source_name="account_wallet_refresh_v1", snapshot_ts_utc=NOW,
        position_source_name="broker_position_snapshot_v1", position_snapshot_count=1,
        balance_source_name="broker_balance_snapshot_v1", balance_snapshot_count=1,
        account_open_order_snapshot_run_id=777,
    )
    values.update(overrides)
    return AccountStateSnapshotRunV1(**values)  # type: ignore[arg-type]


def _wallet_snapshot(**overrides: object) -> WalletAvailableSnapshot:
    values: dict[str, object] = dict(
        trading_account_id=7, venue="bitvavo", asset_id=42, symbol="SOL",
        available_base_quantity=Decimal("10"), total_base_quantity=Decimal("10"),
        source_name="broker_position_snapshot_v1", snapshot_ts_utc=NOW, snapshot_id=901,
    )
    values.update(overrides)
    return WalletAvailableSnapshot(**values)  # type: ignore[arg-type]


def _permission(**overrides: object) -> AutomaticExitPlanningPermissionV1:
    values: dict[str, object] = dict(
        permission_id=1, trading_account_id=7, planning_enabled=True,
        effective_from_ts_utc=NOW - timedelta(days=1), effective_until_ts_utc=None,
        permission_version="1", source_provenance="operator-policy",
    )
    values.update(overrides)
    return AutomaticExitPlanningPermissionV1(**values)  # type: ignore[arg-type]


def _profile(**overrides: object) -> AutomaticExitProfileV1:
    values: dict[str, object] = dict(
        profile_id="profile-sol-1", profile_version="1", venue="bitvavo", asset_id=42, market="SOL-EUR",
        active_target_price=Decimal("100"), invalidation_price=Decimal("80"), evidence_id="evidence-1",
        evidence_provenance="canonical-map", observed_ts_utc=NOW, effective_from_ts_utc=NOW - timedelta(days=1),
        effective_until_ts_utc=None,
    )
    values.update(overrides)
    return AutomaticExitProfileV1(**values)  # type: ignore[arg-type]


def _venue_constraints(**overrides: object) -> VenueExecutionConstraints:
    values: dict[str, object] = dict(
        venue="bitvavo", market="SOL-EUR", tick_size=Decimal("0.05"), qty_step_size=Decimal("0.1"),
        min_base_quantity=Decimal("0.1"), min_quote_notional=Decimal("5"), supported_order_types=("limit",),
        supported_time_in_force=("GTC",), source_provenance="PUBLIC", metadata_synced_ts_utc=NOW,
        status=STATUS_FRESH,
    )
    values.update(overrides)
    return VenueExecutionConstraints(**values)  # type: ignore[arg-type]


def _evidence(**overrides: object) -> AutomaticExitRuntimeEvidenceV1:
    values: dict[str, object] = dict(
        trading_account_id=7, venue="bitvavo", asset_id=42, symbol="SOL", market="SOL-EUR",
        position_reference="account_position_snapshot:7:bitvavo:42:SOL", evaluation_ts_utc=NOW,
        permissions=(_permission(),), profiles=(_profile(),),
        account_state_snapshot=_account_state_snapshot(), wallet_snapshot=_wallet_snapshot(),
        balance_snapshot_id=902, blocking_conflict=False,
        approved_not_submitted_reservation_base=Decimal("0"), reconciliation_pending_reservation_count=0,
        account_enabled=True, live_trading_enabled=False, account_mode="paper",
        current_price=Decimal("100.01"), market_price_snapshot_id=903, price_observed_ts_utc=NOW,
        venue_constraints=_venue_constraints(), venue_constraint_id=904,
    )
    values.update(overrides)
    return AutomaticExitRuntimeEvidenceV1(**values)  # type: ignore[arg-type]


def test_end_to_end_dry_run_candidate_gate_planner_path_is_recorded() -> None:
    result = run_automatic_exit_runtime_cycle_v1(_evidence())
    assert result.candidate_state == STATE_CANDIDATE
    assert result.gate_state == STATE_APPROVED
    assert result.planner_state == PLANNER_STATE_PLANNED
    assert result.plan is not None
    assert result.plan.final_quantity_base == Decimal("2.5")
    assert result.auditable
    assert result.idempotency_key is not None

    payload = build_automatic_exit_audit_payload_v1(_evidence(), result)
    assert payload["planner_state"] == PLANNER_STATE_PLANNED
    assert payload["immutable_plan_json"] is not None
    # Must be JSON-serializable (matches the migration's JSON_VALID check).
    json.dumps(payload["immutable_plan_json"])
    json.dumps(payload["source_evidence_json"])


def test_same_evidence_yields_identical_result_and_idempotency_key() -> None:
    first = run_automatic_exit_runtime_cycle_v1(_evidence())
    second = run_automatic_exit_runtime_cycle_v1(_evidence())
    assert first == second
    assert first.idempotency_key == second.idempotency_key


def test_stale_account_state_snapshot_fails_closed() -> None:
    result = run_automatic_exit_runtime_cycle_v1(
        _evidence(account_state_snapshot=_account_state_snapshot(snapshot_ts_utc=NOW - timedelta(minutes=16)))
    )
    assert result.candidate_state == STATE_NON_ACTIONABLE
    assert result.candidate_reason_code == REASON_ACCOUNT_STATE_SNAPSHOT_STALE
    assert not result.auditable
    assert result.idempotency_key is None


def test_stale_market_price_fails_closed() -> None:
    result = run_automatic_exit_runtime_cycle_v1(
        _evidence(price_observed_ts_utc=NOW - timedelta(minutes=16))
    )
    assert (result.candidate_state, result.candidate_reason_code) == (STATE_NON_ACTIONABLE, REASON_MARKET_PRICE_STALE)
    assert not result.auditable


def test_reconciliation_pending_reservation_fails_closed() -> None:
    result = run_automatic_exit_runtime_cycle_v1(
        _evidence(reconciliation_pending_reservation_count=1)
    )
    assert (result.candidate_state, result.candidate_reason_code) == (
        STATE_NON_ACTIONABLE, REASON_RESERVATION_RECONCILIATION_PENDING,
    )


def test_conflicting_permission_history_fails_closed() -> None:
    result = run_automatic_exit_runtime_cycle_v1(
        _evidence(permissions=(_permission(), _permission(permission_id=2, planning_enabled=False)))
    )
    assert result.candidate_state == STATE_NON_ACTIONABLE
    assert "CONFLICTING" in result.candidate_reason_code
    assert not result.auditable


def test_missing_permission_row_still_evaluates_but_is_not_auditable() -> None:
    result = run_automatic_exit_runtime_cycle_v1(_evidence(permissions=()))
    assert result.candidate_state == STATE_CANDIDATE
    assert result.gate_state == STATE_DENIED
    assert result.gate_reason_code == REASON_EXECUTION_PERMISSION_DISABLED
    assert result.planner_state == PLANNER_STATE_NOT_ATTEMPTED
    assert not result.auditable
    assert result.idempotency_key is None
    assert result.non_auditable_reason is not None
    with pytest.raises(AutomaticExitRuntimeCycleError):
        build_automatic_exit_audit_payload_v1(_evidence(permissions=()), result)


def test_blocking_conflict_denies_at_gate_without_bypassing_it() -> None:
    result = run_automatic_exit_runtime_cycle_v1(_evidence(blocking_conflict=True))
    assert result.candidate_state == STATE_CANDIDATE
    assert (result.gate_state, result.gate_reason_code) == (STATE_DENIED, REASON_BLOCKING_CONFLICT)
    assert result.planner_state == PLANNER_STATE_NOT_ATTEMPTED
    assert result.plan is None
    assert result.auditable


def test_no_exit_condition_is_no_action_and_still_auditable() -> None:
    result = run_automatic_exit_runtime_cycle_v1(_evidence(current_price=Decimal("90")))
    assert result.candidate_state == STATE_NO_ACTION
    assert result.gate_state is None
    assert result.planner_state == PLANNER_STATE_NOT_ATTEMPTED
    assert result.auditable
    assert result.idempotency_key is not None


def test_planner_rejection_is_recorded_without_a_plan() -> None:
    result = run_automatic_exit_runtime_cycle_v1(
        _evidence(venue_constraints=_venue_constraints(min_quote_notional=Decimal("1000")))
    )
    assert result.gate_state == STATE_APPROVED
    assert result.planner_state == PLANNER_STATE_REJECTED
    assert result.planner_reason_code is not None
    assert result.plan is None
    assert result.auditable
    payload = build_automatic_exit_audit_payload_v1(
        _evidence(venue_constraints=_venue_constraints(min_quote_notional=Decimal("1000"))), result,
    )
    assert payload["immutable_plan_json"] is None
    assert payload["planner_state"] == PLANNER_STATE_REJECTED


def test_naive_evaluation_timestamp_fails_closed() -> None:
    result = run_automatic_exit_runtime_cycle_v1(_evidence(evaluation_ts_utc=NOW.replace(tzinfo=None)))
    assert result.candidate_state == STATE_NON_ACTIONABLE
    assert not result.auditable
