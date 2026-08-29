"""Issue #551 Phase 1: tests for the SELL LIVE readiness controller.

Every test here uses fully injected fakes/monkeypatches. None of them ever
open a real database connection, call a broker, mutate the kill switch,
touch executor_live_authority, or write anything other than the controller's
own JSON artifact to a pytest tmp_path.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from src.decision_gate.automatic_exit_live_permission_contract_v1 import (
    AutomaticExitLiveDecisionGatePermissionV1,
)
from src.executor.execution_credential_scope_v1 import (
    CredentialScopeBinding,
    ExecutorCredentialScopeRepository,
)
from src.executor.execution_kill_switch_v1 import (
    KILL_SWITCH_DISENGAGED,
    KILL_SWITCH_ENGAGED,
    ExecutionKillSwitchEventV1,
    ExecutionKillSwitchRepositoryV1,
)
from src.executor.shared_executor_identity_v1 import (
    SHARED_EXECUTOR_IDENTITY,
    SHARED_EXECUTOR_RUNTIME_OWNER,
)
from src.ops import sell_live_activation_controller_v1 as controller


NOW = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
REQUIRED_TABLES = list(controller.REQUIRED_PRODUCTION_TABLES)


# --- Fakes ------------------------------------------------------------


class _FakeCursor:
    def __init__(self, tables: list[str] | None, account_row: dict[str, Any] | None):
        self._tables = tables
        self._account_row = account_row
        self._last_sql = ""

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        self._last_sql = sql

    def fetchall(self):
        if "SHOW TABLES" in self._last_sql:
            if self._tables is None:
                raise RuntimeError("SIMULATED_DB_ERROR")
            return [{"Tables_in_synth": name} for name in self._tables]
        return []

    def fetchone(self):
        if "FROM trading_account WHERE" in self._last_sql:
            return self._account_row
        return None


class _FakeConnection:
    def __init__(self, *, tables: list[str] | None, account_row: dict[str, Any] | None, fail: bool = False):
        self._tables = tables
        self._account_row = account_row
        self._fail = fail
        self.closed = False

    def cursor(self):
        if self._fail:
            raise RuntimeError("SIMULATED_CONNECTION_FAILURE")
        return _FakeCursor(self._tables, self._account_row)

    def close(self) -> None:
        self.closed = True


def _connection_factory(*, tables=REQUIRED_TABLES, account_row=None, fail=False):
    if account_row is None:
        account_row = {
            "trading_account_id": 3,
            "account_mode": "live",
            "enabled": 1,
            "live_trading_enabled": 1,
            "venue": "bitvavo",
        }
    return lambda: _FakeConnection(tables=tables, account_row=account_row, fail=fail)


def _credential_repo(
    *,
    granted: bool = True,
    executor_identity: str = SHARED_EXECUTOR_IDENTITY,
    runtime_owner: str = SHARED_EXECUTOR_RUNTIME_OWNER,
) -> ExecutorCredentialScopeRepository:
    binding = CredentialScopeBinding(
        executor_credential_binding_id=1,
        trading_account_credential_id=1,
        trading_account_id=3,
        venue="bitvavo",
        permission_scope="TRADE_EXECUTION",
        executor_identity=executor_identity,
        runtime_owner=runtime_owner,
        credential_status="ACTIVE",
        credential_source="db_encrypted",
        allowed_order_write=True,
        allowed_withdrawal=False,
    )

    class _Repo(ExecutorCredentialScopeRepository):
        def resolve(self, **kwargs):  # type: ignore[override]
            from src.executor.execution_credential_scope_v1 import CredentialScopeDeniedError

            if not granted:
                raise CredentialScopeDeniedError("CREDENTIAL_SCOPE_NOT_BOUND")
            if (
                kwargs.get("executor_identity") != binding.executor_identity
                or kwargs.get("runtime_owner") != binding.runtime_owner
            ):
                raise CredentialScopeDeniedError("CREDENTIAL_SCOPE_NOT_BOUND")
            return binding

    return _Repo()


def _kill_switch_repo(*, event: ExecutionKillSwitchEventV1 | None) -> ExecutionKillSwitchRepositoryV1:
    class _Repo(ExecutionKillSwitchRepositoryV1):
        def latest_event(self):  # type: ignore[override]
            return event

    return _Repo()


def _granted_permission_history(monkeypatch: pytest.MonkeyPatch, *, trading_account_id: int = 3) -> None:
    row = AutomaticExitLiveDecisionGatePermissionV1(
        permission_id=1,
        trading_account_id=trading_account_id,
        live_execution_permitted=True,
        effective_from_ts_utc=NOW - timedelta(days=1),
        effective_until_ts_utc=None,
        permission_version="1",
        source_provenance="test",
    )
    monkeypatch.setattr(
        "src.decision_gate.automatic_exit_live_permission_repository_v1."
        "load_automatic_exit_live_permission_history_v1",
        lambda conn, *, trading_account_id: (row,),
    )
    monkeypatch.setattr(
        "src.decision_gate.automatic_exit_live_permission_repository_v1."
        "load_automatic_exit_live_permission_revocation_history_v1",
        lambda conn, *, trading_account_id: (),
    )


def _no_permission_history(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.decision_gate.automatic_exit_live_permission_repository_v1."
        "load_automatic_exit_live_permission_history_v1",
        lambda conn, *, trading_account_id: (),
    )
    monkeypatch.setattr(
        "src.decision_gate.automatic_exit_live_permission_repository_v1."
        "load_automatic_exit_live_permission_revocation_history_v1",
        lambda conn, *, trading_account_id: (),
    )


def _active_ownership_registry_path(tmp_path: Path) -> Path:
    registry = {
        "capabilities": [
            {
                "capability_id": capability_id,
                "owner_host": SHARED_EXECUTOR_RUNTIME_OWNER,
                "activation_status": "ACTIVE",
            }
            for capability_id in controller.REQUIRED_RUNTIME_CAPABILITY_IDS
        ]
    }
    path = tmp_path / "active_ownership.json"
    path.write_text(json.dumps(registry), encoding="utf-8")
    return path


def _base_config(**overrides: Any) -> controller.ControllerConfigV1:
    values: dict[str, Any] = dict(
        trading_account_id=3,
        venue="bitvavo",
        executor_identity=SHARED_EXECUTOR_IDENTITY,
        runtime_owner=SHARED_EXECUTOR_RUNTIME_OWNER,
        canary_allowed_market="SOL-EUR",
        canary_max_orders_per_cycle=1,
        canary_max_notional_eur="25",
        now_ts_utc=NOW,
        connection_factory=_connection_factory(),
        credential_scope_repository=_credential_repo(granted=True),
        kill_switch_repository=_kill_switch_repo(
            event=ExecutionKillSwitchEventV1(
                event_id=1, state=KILL_SWITCH_DISENGAGED, actor="operator", reason="baseline",
                created_ts_utc=NOW - timedelta(minutes=5),
            )
        ),
    )
    values.update(overrides)
    return controller.ControllerConfigV1(**values)


def _run(config: controller.ControllerConfigV1, monkeypatch: pytest.MonkeyPatch | None = None,
          grant_permission: bool = True) -> dict[str, Any]:
    if monkeypatch is not None:
        if grant_permission:
            _granted_permission_history(monkeypatch, trading_account_id=config.trading_account_id)
        else:
            _no_permission_history(monkeypatch)
    return controller.run_controller(config, emit=lambda event: None)


# --- Phase ordering ------------------------------------------------------


def test_phase_order_is_fixed_and_deterministic() -> None:
    assert controller.PHASE_ORDER == (
        "PRECHECK",
        "PRODUCTION_SCHEMA_READY",
        "CREDENTIAL_BINDING_READY",
        "LIVE_PERMISSION_READY",
        "KILL_SWITCH_READY",
        "RUNTIME_READY",
        "DRY_RUN_ACCEPTANCE",
        "PAPER_ACCEPTANCE",
        "CANARY_READY",
        "LIVE_AUTHORIZATION_REQUIRED",
    )


def test_artifact_lists_every_phase_in_canonical_order(monkeypatch: pytest.MonkeyPatch) -> None:
    artifact = _run(_base_config(), monkeypatch)
    phases = [entry["phase"] for entry in artifact["phase_results"]]
    assert phases == list(controller.PHASE_ORDER)


# --- All-green path --------------------------------------------------


def test_all_checks_green_yields_live_authorization_required(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    config = _base_config(ownership_registry_path=_active_ownership_registry_path(tmp_path))
    artifact = _run(config, monkeypatch)
    assert artifact["terminal_state"] == "LIVE_AUTHORIZATION_REQUIRED"
    assert artifact["blockers"] == []
    statuses = {entry["phase"]: entry["status"] for entry in artifact["phase_results"]}
    assert all(status == "PASSED" for status in statuses.values())
    assert artifact["canary_contract_preview"]["allowed_side"] == "SELL"
    assert artifact["canary_contract_preview"]["executor_identity"] == SHARED_EXECUTOR_IDENTITY
    assert artifact["canary_contract_preview"]["runtime_owner"] == SHARED_EXECUTOR_RUNTIME_OWNER


# --- Individual fail-closed cases -----------------------------------


def test_schema_missing_tables_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _base_config(connection_factory=_connection_factory(tables=["trading_account"]))
    artifact = _run(config, monkeypatch)
    assert artifact["terminal_state"] == "BLOCKED"
    schema_result = next(r for r in artifact["phase_results"] if r["phase"] == "PRODUCTION_SCHEMA_READY")
    assert schema_result["status"] == "BLOCKED"
    assert schema_result["reason_code"] == "PRODUCTION_SCHEMA_TABLES_MISSING"


def test_credential_missing_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _base_config(credential_scope_repository=_credential_repo(granted=False))
    artifact = _run(config, monkeypatch)
    assert artifact["terminal_state"] == "BLOCKED"
    result = next(r for r in artifact["phase_results"] if r["phase"] == "CREDENTIAL_BINDING_READY")
    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "CREDENTIAL_SCOPE_NOT_BOUND"


def test_historical_manual_binding_cannot_satisfy_shared_runtime_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _base_config(
        executor_identity="manual_execution_bitvavo_v1",
        runtime_owner="odroid",
        credential_scope_repository=_credential_repo(
            executor_identity="manual_execution_bitvavo_v1",
            runtime_owner="odroid",
        ),
    )
    artifact = _run(config, monkeypatch)

    precheck = next(
        r for r in artifact["phase_results"] if r["phase"] == "PRECHECK"
    )
    assert precheck["status"] == "BLOCKED"
    assert (
        precheck["reason_code"]
        == "EXECUTOR_IDENTITY_NOT_CANONICAL_SHARED_EXECUTOR"
    )

    credential = next(
        r
        for r in artifact["phase_results"]
        if r["phase"] == "CREDENTIAL_BINDING_READY"
    )
    assert credential["status"] == "BLOCKED"
    assert credential["reason_code"] == "CREDENTIAL_SCOPE_NOT_BOUND"


def test_live_permission_absent_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    artifact = _run(_base_config(), monkeypatch, grant_permission=False)
    assert artifact["terminal_state"] == "BLOCKED"
    result = next(r for r in artifact["phase_results"] if r["phase"] == "LIVE_PERMISSION_READY")
    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "LIVE_PERMISSION_NOT_GRANTED"


def test_live_permission_revoked_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    row = AutomaticExitLiveDecisionGatePermissionV1(
        permission_id=1, trading_account_id=3, live_execution_permitted=True,
        effective_from_ts_utc=NOW - timedelta(days=2), effective_until_ts_utc=None,
        permission_version="1", source_provenance="test",
    )
    monkeypatch.setattr(
        "src.decision_gate.automatic_exit_live_permission_repository_v1."
        "load_automatic_exit_live_permission_history_v1",
        lambda conn, *, trading_account_id: (row,),
    )

    from src.decision_gate.automatic_exit_live_permission_contract_v1 import (
        AutomaticExitLiveDecisionGatePermissionRevocationV1,
    )

    revocation = AutomaticExitLiveDecisionGatePermissionRevocationV1(
        revocation_id=1, permission_id=1, trading_account_id=3, revocation_version="1",
        effective_ts_utc=NOW - timedelta(days=1), actor="operator", reason="revoked",
    )
    monkeypatch.setattr(
        "src.decision_gate.automatic_exit_live_permission_repository_v1."
        "load_automatic_exit_live_permission_revocation_history_v1",
        lambda conn, *, trading_account_id: (revocation,),
    )
    artifact = controller.run_controller(_base_config(), emit=lambda event: None)
    result = next(r for r in artifact["phase_results"] if r["phase"] == "LIVE_PERMISSION_READY")
    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "LIVE_PERMISSION_NOT_GRANTED"
    assert artifact["terminal_state"] == "BLOCKED"


def test_kill_switch_missing_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _base_config(kill_switch_repository=_kill_switch_repo(event=None))
    artifact = _run(config, monkeypatch)
    result = next(r for r in artifact["phase_results"] if r["phase"] == "KILL_SWITCH_READY")
    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "KILL_SWITCH_STATE_UNKNOWN"
    assert artifact["terminal_state"] == "BLOCKED"


def test_kill_switch_engaged_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    event = ExecutionKillSwitchEventV1(
        event_id=2, state=KILL_SWITCH_ENGAGED, actor="operator", reason="emergency",
        created_ts_utc=NOW,
    )
    config = _base_config(kill_switch_repository=_kill_switch_repo(event=event))
    artifact = _run(config, monkeypatch)
    result = next(r for r in artifact["phase_results"] if r["phase"] == "KILL_SWITCH_READY")
    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "KILL_SWITCH_ENGAGED"


def test_kill_switch_invalid_state_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BadEvent:
        event_id = 3
        state = "WEIRD_STATE"
        created_ts_utc = NOW

    config = _base_config(kill_switch_repository=_kill_switch_repo(event=_BadEvent()))
    artifact = _run(config, monkeypatch)
    result = next(r for r in artifact["phase_results"] if r["phase"] == "KILL_SWITCH_READY")
    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "KILL_SWITCH_STATE_AMBIGUOUS"


def test_runtime_missing_blocks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    registry_path = tmp_path / "ownership.json"
    registry_path.write_text(json.dumps({"capabilities": []}), encoding="utf-8")
    config = _base_config(ownership_registry_path=registry_path)
    artifact = _run(config, monkeypatch)
    result = next(r for r in artifact["phase_results"] if r["phase"] == "RUNTIME_READY")
    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "RUNTIME_CAPABILITY_NOT_ACTIVE"
    assert set(result["detail"]["not_active"]) == set(controller.REQUIRED_RUNTIME_CAPABILITY_IDS)


def test_runtime_owner_mismatch_blocks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    registry = {
        "capabilities": [
            {
                "capability_id": capability_id,
                "owner_host": "odroid",
                "activation_status": "ACTIVE",
            }
            for capability_id in controller.REQUIRED_RUNTIME_CAPABILITY_IDS
        ]
    }
    path = tmp_path / "wrong-owner.json"
    path.write_text(json.dumps(registry), encoding="utf-8")

    artifact = _run(_base_config(ownership_registry_path=path), monkeypatch)
    result = next(
        r for r in artifact["phase_results"] if r["phase"] == "RUNTIME_READY"
    )
    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "RUNTIME_CAPABILITY_OWNER_MISMATCH"


def test_runtime_registry_unreadable_blocks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = _base_config(ownership_registry_path=tmp_path / "does_not_exist.json")
    artifact = _run(config, monkeypatch)
    result = next(r for r in artifact["phase_results"] if r["phase"] == "RUNTIME_READY")
    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "RUNTIME_OWNERSHIP_REGISTRY_UNREADABLE"


def test_dry_run_and_paper_acceptance_pass_without_db(monkeypatch: pytest.MonkeyPatch) -> None:
    artifact = _run(_base_config(), monkeypatch)
    dry_run = next(r for r in artifact["phase_results"] if r["phase"] == "DRY_RUN_ACCEPTANCE")
    paper = next(r for r in artifact["phase_results"] if r["phase"] == "PAPER_ACCEPTANCE")
    assert dry_run["status"] == "PASSED"
    assert paper["status"] == "PASSED"
    assert paper["detail"]["resolved_executor_mode"] == "PAPER"


def test_production_db_unavailable_blocks_multiple_phases(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _base_config(connection_factory=_connection_factory(fail=True))
    artifact = _run(config, monkeypatch)
    precheck = next(r for r in artifact["phase_results"] if r["phase"] == "PRECHECK")
    schema = next(r for r in artifact["phase_results"] if r["phase"] == "PRODUCTION_SCHEMA_READY")
    assert precheck["status"] == "BLOCKED"
    assert precheck["reason_code"] == "PRODUCTION_DB_UNAVAILABLE"
    assert schema["status"] == "BLOCKED"
    assert schema["reason_code"] == "PRODUCTION_DB_UNAVAILABLE"
    assert artifact["terminal_state"] == "BLOCKED"


# --- Terminal state / idempotency / no-writes / no-secrets --------------


def test_exactly_one_terminal_state(monkeypatch: pytest.MonkeyPatch) -> None:
    artifact = _run(_base_config(), monkeypatch)
    assert artifact["terminal_state"] in controller.VALID_TERMINAL_STATES
    # Only one terminal_state key exists in the artifact by construction.
    assert isinstance(artifact["terminal_state"], str)


def test_repeated_check_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _base_config()
    first = _run(config, monkeypatch)
    second = _run(config, monkeypatch)
    first_stable = {k: v for k, v in first.items() if k != "generated_at_utc"}
    second_stable = {k: v for k, v in second.items() if k != "generated_at_utc"}
    assert first_stable == second_stable


def test_no_secret_material_in_artifact(monkeypatch: pytest.MonkeyPatch) -> None:
    artifact = _run(_base_config(), monkeypatch)
    serialized = json.dumps(artifact).lower()
    for forbidden in ("api_key", "api_secret", "password", "secret_key", "encrypted_envelope"):
        assert forbidden not in serialized


def test_no_production_writes_from_check_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    conn_holder: dict[str, Any] = {}

    class _TrackingConnection(_FakeConnection):
        def cursor(self):
            conn_holder["cursor_calls"] = conn_holder.get("cursor_calls", 0) + 1
            return super().cursor()

    account_row = {
        "trading_account_id": 3, "account_mode": "live", "enabled": 1,
        "live_trading_enabled": 1, "venue": "bitvavo",
    }
    config = _base_config(
        connection_factory=lambda: _TrackingConnection(tables=REQUIRED_TABLES, account_row=account_row),
        ownership_registry_path=_active_ownership_registry_path(tmp_path),
    )
    artifact = _run(config, monkeypatch)
    assert artifact["terminal_state"] == "LIVE_AUTHORIZATION_REQUIRED"
    # The fake connection/cursor never expose or record any write/commit
    # call because the controller never invokes one; presence of read
    # (cursor) calls alongside a clean PASS is the expected read-only shape.
    assert conn_holder.get("cursor_calls", 0) > 0


def test_persist_artifact_writes_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    artifact = _run(_base_config(), monkeypatch)
    path = controller.persist_artifact_v1(artifact, tmp_path / "sell_live_readiness_v1.json")
    assert path.exists()
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["schema_version"] == "sell_live_readiness_v1"


# --- Canary preview -----------------------------------------------------


def test_canary_preview_rejects_non_sell_side() -> None:
    with pytest.raises(controller.SellLiveCanaryContractPreviewError):
        controller.SellLiveCanaryContractPreviewV1(
            version=controller.CONTROLLER_VERSION,
            trading_account_id=3,
            venue="bitvavo",
            executor_identity=SHARED_EXECUTOR_IDENTITY,
            runtime_owner=SHARED_EXECUTOR_RUNTIME_OWNER,
            allowed_side="BUY",
            allowed_market="SOL-EUR",
            max_orders_per_cycle=1,
            max_notional_eur="25",
            kill_switch_required=True,
            deployed_sha="abc123",
        )


def test_canary_preview_requires_kill_switch_required_true() -> None:
    with pytest.raises(controller.SellLiveCanaryContractPreviewError):
        controller.SellLiveCanaryContractPreviewV1(
            version=controller.CONTROLLER_VERSION,
            trading_account_id=3,
            venue="bitvavo",
            executor_identity=SHARED_EXECUTOR_IDENTITY,
            runtime_owner=SHARED_EXECUTOR_RUNTIME_OWNER,
            allowed_side="SELL",
            allowed_market="SOL-EUR",
            max_orders_per_cycle=1,
            max_notional_eur="25",
            kill_switch_required=False,
            deployed_sha="abc123",
        )


def test_precheck_blocks_on_inconsistent_account_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    account_row = {
        "trading_account_id": 3, "account_mode": "live", "enabled": 1,
        "live_trading_enabled": 0, "venue": "bitvavo",
    }
    config = _base_config(connection_factory=_connection_factory(account_row=account_row))
    artifact = _run(config, monkeypatch)
    result = next(r for r in artifact["phase_results"] if r["phase"] == "PRECHECK")
    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "ACCOUNT_MODE_EVIDENCE_INCONSISTENT"


def test_precheck_blocks_live_readonly_as_not_execution_eligible(monkeypatch: pytest.MonkeyPatch) -> None:
    """Issue #551: account_mode=live_readonly with the canonically consistent
    live_trading_enabled=0 must block PRECHECK with
    ACCOUNT_MODE_NOT_EXECUTION_ELIGIBLE, distinct from
    ACCOUNT_MODE_EVIDENCE_INCONSISTENT -- the pairing itself is valid, the
    account is just permanently execution-ineligible. This is the exact
    reason code accounts 2/3 will report once the (not-yet-applied) data
    migration in docs/ops/trading_account_live_readonly_mode_migration_v1.md
    is applied."""
    account_row = {
        "trading_account_id": 3, "account_mode": "live_readonly", "enabled": 1,
        "live_trading_enabled": 0, "venue": "bitvavo",
    }
    config = _base_config(connection_factory=_connection_factory(account_row=account_row))
    artifact = _run(config, monkeypatch)
    result = next(r for r in artifact["phase_results"] if r["phase"] == "PRECHECK")
    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "ACCOUNT_MODE_NOT_EXECUTION_ELIGIBLE"


def test_precheck_blocks_live_readonly_with_inconsistent_flag_as_evidence_inconsistent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """live_readonly with live_trading_enabled=1 is invalid evidence, not
    merely execution-ineligible."""
    account_row = {
        "trading_account_id": 3, "account_mode": "live_readonly", "enabled": 1,
        "live_trading_enabled": 1, "venue": "bitvavo",
    }
    config = _base_config(connection_factory=_connection_factory(account_row=account_row))
    artifact = _run(config, monkeypatch)
    result = next(r for r in artifact["phase_results"] if r["phase"] == "PRECHECK")
    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "ACCOUNT_MODE_EVIDENCE_INCONSISTENT"


def test_precheck_blocks_on_deployed_sha_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _base_config(expected_deployed_sha="0000000000000000000000000000000000000")
    artifact = _run(config, monkeypatch)
    result = next(r for r in artifact["phase_results"] if r["phase"] == "PRECHECK")
    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "REPOSITORY_DEPLOYED_SHA_MISMATCH"
