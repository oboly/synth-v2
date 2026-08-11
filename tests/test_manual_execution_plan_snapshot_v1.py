from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from dataclasses import replace

from src.execution_planner.contract_preview_v1 import ExecutionPlanPreview
from src.execution_planner.manual_execution_plan_snapshot_v1 import (
    ManualExecutionPlanSnapshotError,
    build_manual_execution_plan_snapshot,
)
from src.manual_execution.manual_execution_request_v1 import (
    MODE_PAPER,
    QUANTITY_POLICY_FULL_AVAILABLE_BASE,
    SOURCE_OPERATOR_CLI,
    build_manual_execution_request,
)


NOW = datetime(2026, 8, 11, tzinfo=timezone.utc)
MIGRATION = Path("db/migrations/20260811_manual_execution_plan_snapshot_idempotency_v1.sql").read_text(encoding="utf-8")


def _request(**overrides):
    values = dict(
        idempotency_key="operator-request-1", operator_request_nonce="nonce-1",
        created_ts_utc=NOW, source=SOURCE_OPERATOR_CLI, requested_by="operator",
        mode=MODE_PAPER, trading_account_id=1, account_code="paper", venue="bitvavo",
        asset_id=42, base_asset="BTC", quote_asset="EUR", side="SELL",
        quantity_policy=QUANTITY_POLICY_FULL_AVAILABLE_BASE, provenance_id=7,
        ladder_profile_id=9, ladder_profile_version=2,
        anchor_type="NATIVE_SHORT_ANCHOR_HIGH", anchor_price=Decimal("51000"),
        anchor_source="native_short_context_v1", source_map_cycle_id="cycle-1",
        source_native_map_id="map-1", source_map_version="native_short_v1",
    )
    values.update(overrides)
    return build_manual_execution_request(**values)


def _plan(**overrides):
    values = dict(
        account_id=1, sleeve_code="CORE_STRUCTURAL", asset_id=42, symbol="BTC",
        venue="bitvavo", side="SELL", plan_type="EXIT", execution_mode="PAPER",
        plan_state="PREVIEW_ONLY", source_decision_state="APPROVED", source_decision_reason="OK",
        regime_label="RANGE", volatility_bucket="NORMAL", asset_exit_profile_hint=None,
        total_target_fraction=Decimal("1"), max_notional_eur=None, quantity_base=Decimal("2"),
        reference_price_eur=Decimal("50000"), best_bid_eur=Decimal("49999"),
        best_ask_eur=Decimal("50001"), tick_size=Decimal("1"), notes="preview_only=1", legs=[],
    )
    values.update(overrides)
    return ExecutionPlanPreview(**values)


def test_same_nonce_is_stable_and_different_nonce_is_distinct_per_account() -> None:
    first = _request()
    assert first.dedupe_key == _request().dedupe_key
    assert first.dedupe_key != _request(operator_request_nonce="nonce-2").dedupe_key
    assert first.dedupe_key != _request(trading_account_id=2).dedupe_key
    assert "DROP INDEX uq_manual_execution_request_idempotency" in MIGRATION


def test_snapshot_binds_required_reproducibility_fields() -> None:
    snapshot = build_manual_execution_plan_snapshot(
        request=__import__("dataclasses").replace(_request(), request_id=101),
        approval_id=501, plan=_plan(),
    )
    assert snapshot.request_id == 101
    assert snapshot.ladder_profile_id == 9
    assert snapshot.anchor_price == Decimal("51000")
    assert snapshot.source_map_cycle_id == "cycle-1"
    assert snapshot.source_native_map_id == "map-1"
    assert '"quantity_base":"2"' in snapshot.payload_json


def test_snapshot_rejects_missing_binding_and_non_approved_plan() -> None:
    with pytest.raises(ManualExecutionPlanSnapshotError, match="binding"):
        build_manual_execution_plan_snapshot(
            request=replace(replace(_request(), ladder_profile_id=None), request_id=1),
            approval_id=1, plan=_plan(),
        )
    with pytest.raises(ManualExecutionPlanSnapshotError, match="decision_gate-approved"):
        build_manual_execution_plan_snapshot(
            request=replace(_request(), request_id=1),
            approval_id=1, plan=_plan(source_decision_state="BLOCKED"),
        )


def test_schema_enforces_concurrent_dedupe_and_snapshot_immutability() -> None:
    assert "UNIQUE KEY uq_manual_execution_request_dedupe_key" in MIGRATION
    assert "UNIQUE KEY uq_manual_execution_plan_snapshot_request" in MIGRATION
    assert "ON DUPLICATE KEY UPDATE" not in MIGRATION
    assert "BEFORE UPDATE ON manual_execution_plan_snapshot" in MIGRATION
    assert "MANUAL_EXECUTION_PLAN_SNAPSHOT_IS_IMMUTABLE" in MIGRATION
    assert "DROP TABLE manual_execution_plan_snapshot" in MIGRATION


def test_snapshot_schema_has_no_broker_order_state() -> None:
    table_sql = MIGRATION.split("CREATE TABLE manual_execution_plan_snapshot", 1)[1].split("DELIMITER", 1)[0].lower()
    column_sql = table_sql.split("comment=", 1)[0]
    forbidden = ("broker_order", "fill_state", "cancel", "order_id")
    assert all(item not in column_sql for item in forbidden)
