"""Focused CLI mode-boundary tests for manual execution submission."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

import src.executor.run_manual_execution_submission_v1 as submission_cli
from src.execution_planner.manual_execution_plan_snapshot_v1 import ManualExecutionPlanSnapshot
from src.executor.manual_execution_handoff_v1 import (
    CLAIM_STATE_CLAIMED,
    ManualExecutionExecutorHandoff,
)
from src.executor.manual_execution_operator_identity_v1 import BITVAVO_OPERATOR_ID_ENV
from src.executor.manual_execution_submission_leg_inmemory_v1 import (
    InMemorySubmissionLegRepository,
)
from src.executor.manual_execution_stub_order_adapter_v1 import StubOrderPlacementAdapter


NOW = datetime(2026, 8, 14, tzinfo=timezone.utc)


def _handoff() -> ManualExecutionExecutorHandoff:
    return ManualExecutionExecutorHandoff(
        handoff_id=1,
        request_id=1,
        approval_id=1,
        plan_snapshot_id=701,
        trading_account_id=1,
        venue="bitvavo",
        market="BTC-EUR",
        side="SELL",
        executor_mode="PAPER",
        executor_identity="executor-v1",
        runtime_owner="devlap",
        executor_credential_binding_id=1,
        claim_state=CLAIM_STATE_CLAIMED,
        claimed_ts_utc=NOW,
        consumed_ts_utc=None,
        outcome_code=None,
        outcome_detail=None,
        created_ts_utc=NOW,
    )


def _plan_snapshot() -> ManualExecutionPlanSnapshot:
    return ManualExecutionPlanSnapshot(
        plan_snapshot_id=701,
        request_id=1,
        approval_id=1,
        trading_account_id=1,
        ladder_profile_id=1,
        ladder_profile_version=1,
        anchor_type="X",
        anchor_price=Decimal("1"),
        anchor_source="x",
        source_map_cycle_id="c",
        source_native_map_id="m",
        source_map_version="v",
        provenance_id=1,
        market="BTC-EUR",
        side="SELL",
        quantity_policy="LADDER_LEVELS",
        approved_quantity_base=Decimal("1"),
        planner_version="v1",
        payload_json=(
            '{"legs":[{"leg_index":1,"side":"SELL",'
            '"target_price_eur":"50000","quantity_base":"0.1"}]}'
        ),
    )


def _wire_canonical_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    handoff = _handoff()
    plan_snapshot = _plan_snapshot()
    monkeypatch.setattr(
        submission_cli,
        "ExecutorHandoffRepository",
        lambda: SimpleNamespace(find_by_id=lambda handoff_id: handoff if handoff_id == handoff.handoff_id else None),
    )
    monkeypatch.setattr(
        submission_cli,
        "ManualExecutionPlanSnapshotRepository",
        lambda: SimpleNamespace(
            find_by_id=lambda plan_snapshot_id: plan_snapshot if plan_snapshot_id == plan_snapshot.plan_snapshot_id else None
        ),
    )


def _successful_result() -> SimpleNamespace:
    return SimpleNamespace(leg_outcomes=(), stopped_reason=None)


def test_dry_run_without_operator_id_uses_non_live_adapters_and_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _wire_canonical_inputs(monkeypatch)
    monkeypatch.delenv(BITVAVO_OPERATOR_ID_ENV, raising=False)
    captured: dict[str, Any] = {}

    def submit(**kwargs: Any) -> SimpleNamespace:
        captured.update(kwargs)
        return _successful_result()

    monkeypatch.setattr(submission_cli, "submit_manual_sell_ladder", submit)

    assert submission_cli.main(["--handoff-id", "1", "--runtime-owner", "devlap", "--assume-yes"]) == 0
    assert captured["operator_id"] == submission_cli.DRY_RUN_NON_LIVE_OPERATOR_ID
    assert isinstance(captured["adapter"], StubOrderPlacementAdapter)
    assert isinstance(captured["submission_leg_repository"], InMemorySubmissionLegRepository)


def test_dry_run_never_resolves_bitvavo_operator_id(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire_canonical_inputs(monkeypatch)
    monkeypatch.setattr(
        submission_cli,
        "resolve_operator_id",
        lambda: pytest.fail("dry-run must not resolve Bitvavo operator identity"),
    )
    monkeypatch.setattr(submission_cli, "submit_manual_sell_ladder", lambda **_: _successful_result())

    assert submission_cli.main(["--handoff-id", "1", "--runtime-owner", "devlap", "--assume-yes"]) == 0


def test_live_without_operator_id_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire_canonical_inputs(monkeypatch)
    monkeypatch.delenv(BITVAVO_OPERATOR_ID_ENV, raising=False)
    monkeypatch.setattr(submission_cli, "_run_live", lambda **_: pytest.fail("LIVE must not run"))

    assert submission_cli.main(["--handoff-id", "1", "--runtime-owner", "devlap", "--mode", "live"]) == 2


def test_live_with_operator_id_uses_existing_live_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire_canonical_inputs(monkeypatch)
    monkeypatch.setenv(BITVAVO_OPERATOR_ID_ENV, "12345")
    captured: dict[str, Any] = {}

    def run_live(**kwargs: Any) -> int:
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(submission_cli, "_run_live", run_live)

    assert submission_cli.main(["--handoff-id", "1", "--runtime-owner", "devlap", "--mode", "live"]) == 0
    assert captured["operator_id"] == 12345


def test_grant_live_authority_does_not_resolve_bitvavo_operator_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _wire_canonical_inputs(monkeypatch)
    monkeypatch.setattr(
        submission_cli,
        "resolve_operator_id",
        lambda: pytest.fail("authority grant must retain separate operator identity semantics"),
    )
    monkeypatch.setattr(submission_cli, "_grant_live_authority", lambda **_: 0)

    assert submission_cli.main(
        ["--handoff-id", "1", "--runtime-owner", "devlap", "--grant-live-authority"]
    ) == 0
