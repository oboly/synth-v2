from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from src.exit_policy.automatic_exit_runtime_contract_v1 import (
    AutomaticExitPlanningPermissionV1, AutomaticExitProfileV1, AutomaticExitRuntimeContractError,
    PERMISSION_CONTRACT_VERSION, PROFILE_CONTRACT_VERSION, automatic_exit_idempotency_key_v1,
    resolve_automatic_exit_planning_enabled, resolve_automatic_exit_profile,
)


NOW = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)


def _permission(**changes: object) -> AutomaticExitPlanningPermissionV1:
    values: dict[str, object] = dict(permission_id=1, trading_account_id=7, planning_enabled=True, effective_from_ts_utc=NOW - timedelta(days=1), effective_until_ts_utc=None, permission_version="1", source_provenance="operator-policy")
    values.update(changes)
    return AutomaticExitPlanningPermissionV1(**values)  # type: ignore[arg-type]


def _profile(**changes: object) -> AutomaticExitProfileV1:
    values: dict[str, object] = dict(profile_id="profile-sol-1", profile_version="1", venue="bitvavo", asset_id=42, market="SOL-EUR", active_target_price=Decimal("100"), invalidation_price=Decimal("80"), evidence_id="evidence-1", evidence_provenance="canonical-map", observed_ts_utc=NOW, effective_from_ts_utc=NOW - timedelta(days=1), effective_until_ts_utc=None)
    values.update(changes)
    return AutomaticExitProfileV1(**values)  # type: ignore[arg-type]


def _evidence(**changes: object) -> dict[str, object]:
    values: dict[str, object] = dict(trading_account_id=7, position_reference="position-1", venue="bitvavo", asset_id=42, market="SOL-EUR", position_snapshot_id=101, balance_snapshot_id=102, open_order_snapshot_run_id=103, market_price_snapshot_id=104, automatic_exit_permission_id=1, exit_profile_id="profile-sol-1", exit_profile_version="1", exit_profile_observed_ts_utc="2026-08-14T12:00:00Z", venue_constraint_id=105, venue_metadata_synced_ts_utc="2026-08-14T12:00:00Z")
    values.update(changes)
    return values


def test_permission_defaults_disabled_and_is_account_isolated() -> None:
    assert not resolve_automatic_exit_planning_enabled([], trading_account_id=7, at=NOW)
    assert resolve_automatic_exit_planning_enabled([_permission()], trading_account_id=7, at=NOW)
    assert not resolve_automatic_exit_planning_enabled([_permission()], trading_account_id=8, at=NOW)


def test_conflicting_permission_is_fail_closed() -> None:
    with pytest.raises(AutomaticExitRuntimeContractError, match="CONFLICTING"):
        resolve_automatic_exit_planning_enabled([_permission(), _permission(permission_id=2, planning_enabled=False)], trading_account_id=7, at=NOW)


@pytest.mark.parametrize("changes", [
    {"permission_id": 0}, {"permission_version": "2"}, {"source_provenance": ""},
    {"planning_enabled": 1}, {"effective_from_ts_utc": NOW.replace(tzinfo=None)},
    {"effective_until_ts_utc": NOW.replace(tzinfo=None)},
    {"effective_until_ts_utc": NOW - timedelta(days=2)},
])
def test_malformed_permission_fails_closed(changes: dict[str, object]) -> None:
    with pytest.raises(AutomaticExitRuntimeContractError, match="INVALID_OR_UNSUPPORTED"):
        resolve_automatic_exit_planning_enabled([_permission(**changes)], trading_account_id=7, at=NOW)


def test_one_valid_disabled_permission_returns_false() -> None:
    assert not resolve_automatic_exit_planning_enabled([_permission(planning_enabled=False)], trading_account_id=7, at=NOW)


def test_profile_requires_exactly_one_valid_v1_market_profile_and_preserves_provenance() -> None:
    profile = resolve_automatic_exit_profile([_profile()], venue="BITVAVO", asset_id=42, market="SOL/EUR", at=NOW)
    assert profile.evidence_id == "evidence-1"
    with pytest.raises(AutomaticExitRuntimeContractError, match="MISSING_OR_CONFLICTING"):
        resolve_automatic_exit_profile([], venue="bitvavo", asset_id=42, market="SOL-EUR", at=NOW)
    with pytest.raises(AutomaticExitRuntimeContractError, match="MISSING_OR_CONFLICTING"):
        resolve_automatic_exit_profile([_profile(), _profile(profile_id="two")], venue="bitvavo", asset_id=42, market="SOL-EUR", at=NOW)
    with pytest.raises(AutomaticExitRuntimeContractError, match="INVALID_OR_UNSUPPORTED"):
        resolve_automatic_exit_profile([_profile(profile_version="2")], venue="bitvavo", asset_id=42, market="SOL-EUR", at=NOW)
    with pytest.raises(AutomaticExitRuntimeContractError, match="INVALID_OR_UNSUPPORTED"):
        resolve_automatic_exit_profile([_profile(observed_ts_utc=NOW - timedelta(minutes=16))], venue="bitvavo", asset_id=42, market="SOL-EUR", at=NOW)


def test_idempotency_key_is_deterministic_and_evidence_scoped() -> None:
    assert automatic_exit_idempotency_key_v1(_evidence()) == automatic_exit_idempotency_key_v1(dict(_evidence()))
    assert automatic_exit_idempotency_key_v1(_evidence()) == automatic_exit_idempotency_key_v1({**_evidence(), "runtime_version": "ignored"})
    for changes in (
        {"position_snapshot_id": 999}, {"balance_snapshot_id": 999}, {"open_order_snapshot_run_id": 999},
        {"market_price_snapshot_id": 999}, {"automatic_exit_permission_id": 2},
        {"exit_profile_version": "2"}, {"exit_profile_observed_ts_utc": "2026-08-14T12:01:00Z"},
        {"venue_metadata_synced_ts_utc": "2026-08-14T12:01:00Z"}, {"trading_account_id": 8},
    ):
        assert automatic_exit_idempotency_key_v1(_evidence(**changes)) != automatic_exit_idempotency_key_v1(_evidence())
    with pytest.raises(AutomaticExitRuntimeContractError, match="INCOMPLETE"):
        automatic_exit_idempotency_key_v1({"trading_account_id": 7})


def test_contract_has_no_manual_executor_broker_credential_or_live_dependency() -> None:
    tree = ast.parse(Path("src/exit_policy/automatic_exit_runtime_contract_v1.py").read_text())
    imports = [alias.name for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom)) for alias in node.names]
    assert not any(any(word in name for word in ("manual", "executor", "broker", "credential", "live")) for name in imports)


def test_migration_versions_and_default_disabled_semantics_match_contract() -> None:
    migration = Path("db/migrations/20260814_automatic_exit_runtime_contract_v1.sql").read_text()
    assert f"permission_version VARCHAR(32) NOT NULL DEFAULT '{PERMISSION_CONTRACT_VERSION}'" in migration
    assert "profile_version VARCHAR(32) NOT NULL" in migration
    assert "No row means disabled" in migration
    assert PROFILE_CONTRACT_VERSION == "1"
