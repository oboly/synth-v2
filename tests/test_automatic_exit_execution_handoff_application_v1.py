"""Issue #392 Phase 6 blocker A: handoff application-seam tests.

Proves DRY_RUN/PAPER route through ExecutionHandoffRepositoryV1.intake,
LIVE routes through .intake_live_authorized (never ordinary intake),
unsupported executor_mode fails closed, executor identity/runtime owner are
passed through exactly, retries are idempotent, and credential/LIVE-
authority/kill-switch denial remain entirely owned by the injected fake
#206 repository -- this seam never pre-checks them itself. All persistence
is an in-memory fake; no real DB, no broker.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pymysql.err import IntegrityError

from src.decision_gate.automatic_exit_gate_v1 import STATE_APPROVED, AutomaticExitGateDecisionV1
from src.execution_planner.automatic_exit_execution_handoff_adapter_v1 import (
    derive_automatic_exit_plan_reference_id_v1,
)
from src.execution_planner.automatic_exit_execution_handoff_application_v1 import (
    AutomaticExitExecutorModeError,
    resolve_automatic_exit_executor_mode_v1,
    submit_automatic_exit_plan_to_execution_handoff_v1,
)
from src.execution_planner.automatic_exit_planner_v1 import (
    AutomaticExitPlanningContextV1,
    build_automatic_exit_plan_v1,
)
from src.executor.execution_credential_scope_v1 import CredentialScopeBinding, CredentialScopeDeniedError
from src.executor.execution_handoff_v1 import (
    ExecutionHandoffDeniedError,
    ExecutionHandoffIdentityConflictError,
    ExecutionHandoffRepositoryV1,
)
from src.executor.execution_live_authority_v1 import ExecutionLiveAuthorityDeniedError
from src.exit_policy.automatic_exit_candidate_v1 import AutomaticExitCandidateV1
from src.market_rules.venue_execution_constraints_v1 import STATUS_FRESH, VenueExecutionConstraints


NOW = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)


def _candidate(**overrides: object) -> AutomaticExitCandidateV1:
    values: dict[str, object] = dict(
        trading_account_id=7, position_reference="position-9", venue="bitvavo", asset_id=42,
        market="SOL-EUR", candidate_action="REDUCE", reduction_fraction_candidate=Decimal("0.25"),
        urgency_candidate="NORMAL", reason_code="TARGET_REACHED", evidence_id="evidence-1",
        exit_profile_id="profile-1", exit_profile_version="1", target_price=Decimal("100"),
        invalidation_price=Decimal("80"), observed_ts_utc=NOW,
    )
    values.update(overrides)
    return AutomaticExitCandidateV1(**values)  # type: ignore[arg-type]


def _decision(**overrides: object) -> AutomaticExitGateDecisionV1:
    values: dict[str, object] = dict(
        state=STATE_APPROVED, reason_code="OK", candidate=_candidate(),
        approved_fraction_candidate=Decimal("0.25"), approved_quantity_ceiling_base=Decimal("2.57"),
    )
    values.update(overrides)
    return AutomaticExitGateDecisionV1(**values)  # type: ignore[arg-type]


def _constraints(**overrides: object) -> VenueExecutionConstraints:
    values: dict[str, object] = dict(
        venue="bitvavo", market="SOL-EUR", tick_size=Decimal("0.05"), qty_step_size=Decimal("0.1"),
        min_base_quantity=Decimal("0.1"), min_quote_notional=Decimal("5"), supported_order_types=("limit",),
        supported_time_in_force=("GTC",), source_provenance="PUBLIC", metadata_synced_ts_utc=NOW,
        status=STATUS_FRESH,
    )
    values.update(overrides)
    return VenueExecutionConstraints(**values)  # type: ignore[arg-type]


def _context(**overrides: object) -> AutomaticExitPlanningContextV1:
    values: dict[str, object] = dict(
        trading_account_id=7, position_reference="position-9", venue="bitvavo", asset_id=42,
        market="SOL-EUR", reference_price=Decimal("100.01"), venue_constraints=_constraints(),
        planning_ts_utc=NOW,
    )
    values.update(overrides)
    return AutomaticExitPlanningContextV1(**values)  # type: ignore[arg-type]


def _plan(**decision_overrides: object):
    return build_automatic_exit_plan_v1(decision=_decision(**decision_overrides), context=_context())


class FakeCredentialRepository:
    def __init__(self, *, denied: bool = False, binding_id: int = 3) -> None:
        self.denied = denied
        self.binding_id = binding_id
        self.calls: list[dict[str, object]] = []

    def resolve(self, **kwargs) -> CredentialScopeBinding:
        self.calls.append(kwargs)
        if self.denied:
            raise CredentialScopeDeniedError("CREDENTIAL_SCOPE_DENIED")
        return CredentialScopeBinding(
            executor_credential_binding_id=self.binding_id,
            trading_account_credential_id=11,
            trading_account_id=int(kwargs["trading_account_id"]),
            venue=str(kwargs["venue"]),
            permission_scope="TRADE_EXECUTION",
            executor_identity=str(kwargs["executor_identity"]),
            runtime_owner=str(kwargs["runtime_owner"]),
            credential_status="ACTIVE",
            credential_source="ENCRYPTED_DB",
            allowed_order_write=True,
            allowed_withdrawal=False,
        )


class FakeLiveAuthorityRepository:
    def __init__(self, *, permitted: bool = True) -> None:
        self.permitted = permitted
        self.calls: list[dict[str, object]] = []

    def resolve_effective(self, **kwargs):
        self.calls.append(kwargs)
        if not self.permitted:
            raise ExecutionLiveAuthorityDeniedError("EXECUTION_LIVE_AUTHORITY_NOT_GRANTED")
        return object()


class FakeKillSwitchRepository:
    def __init__(self, *, engaged: bool = False) -> None:
        self.engaged = engaged
        self.calls = 0

    def is_engaged(self) -> bool:
        self.calls += 1
        return self.engaged


class MemoryCursor:
    def __init__(self, database: "MemoryDatabase") -> None:
        self.database = database
        self.lastrowid = 0
        self.selected: dict[str, object] | None = None

    def execute(self, sql: str, params: list[object]) -> None:
        if sql.startswith("INSERT INTO executor_execution_handoff ("):
            key = (str(params[0]), str(params[1]))
            if key in self.database.rows:
                raise IntegrityError(1062, "duplicate plan reference")
            handoff_id = self.database.next_id
            self.database.next_id += 1
            self.lastrowid = handoff_id
            self.database.rows[key] = {
                "executor_execution_handoff_id": handoff_id,
                "plan_source": params[0], "plan_reference_id": params[1], "plan_content_hash": params[2],
                "trading_account_id": params[3], "venue": params[4], "market": params[5], "side": params[6],
                "strategy_bucket_id": params[7], "strategy_id": params[8], "strategy_version": params[9],
                "setup_id": params[10], "executor_mode": params[11], "executor_identity": params[12],
                "runtime_owner": params[13], "executor_credential_binding_id": params[14],
            }
            return
        if sql.startswith("INSERT INTO executor_execution_handoff_plan_leg"):
            return
        if sql.startswith("INSERT INTO executor_execution_handoff_consumption"):
            return
        if "WHERE plan_source=%s AND plan_reference_id=%s" in sql:
            self.selected = self.database.rows.get((str(params[0]), str(params[1])))
            return
        raise AssertionError(f"unexpected SQL: {sql}")

    def fetchone(self):
        return self.selected


class MemoryContext:
    def __init__(self, database: "MemoryDatabase") -> None:
        self.cursor = MemoryCursor(database)

    def __enter__(self) -> MemoryCursor:
        return self.cursor

    def __exit__(self, *_args) -> None:
        return None


class MemoryDatabase:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], dict[str, object]] = {}
        self.next_id = 1

    def cursor_factory(self, **_kwargs) -> MemoryContext:
        return MemoryContext(self)


def _repository(
    *, database: MemoryDatabase | None = None, credentials=None, authority=None, kill_switch=None,
) -> ExecutionHandoffRepositoryV1:
    return ExecutionHandoffRepositoryV1(
        cursor_factory=(database or MemoryDatabase()).cursor_factory,
        credential_scope_repository=credentials or FakeCredentialRepository(),
        live_authority_repository=authority or FakeLiveAuthorityRepository(),
        kill_switch_repository=kill_switch or FakeKillSwitchRepository(),
    )


# --- Mode routing --------------------------------------------------------


def test_dry_run_uses_ordinary_intake() -> None:
    database = MemoryDatabase()
    handoff = submit_automatic_exit_plan_to_execution_handoff_v1(
        plan=_plan(), executor_mode="DRY_RUN", executor_identity="shared-executor-v1",
        runtime_owner="devlap", handoff_repository=_repository(database=database),
    )
    assert handoff.executor_mode == "DRY_RUN"
    assert len(database.rows) == 1


def test_paper_uses_ordinary_intake() -> None:
    database = MemoryDatabase()
    handoff = submit_automatic_exit_plan_to_execution_handoff_v1(
        plan=_plan(), executor_mode="PAPER", executor_identity="shared-executor-v1",
        runtime_owner="devlap", handoff_repository=_repository(database=database),
    )
    assert handoff.executor_mode == "PAPER"
    assert len(database.rows) == 1


def test_live_uses_intake_live_authorized_not_ordinary_intake() -> None:
    database = MemoryDatabase()
    authority = FakeLiveAuthorityRepository(permitted=True)
    handoff = submit_automatic_exit_plan_to_execution_handoff_v1(
        plan=_plan(), executor_mode="LIVE", executor_identity="shared-executor-v1",
        runtime_owner="devlap", handoff_repository=_repository(database=database, authority=authority),
    )
    assert handoff.executor_mode == "LIVE"
    # LIVE authority resolution only happens on the intake_live_authorized path.
    assert len(authority.calls) == 1


def test_unsupported_mode_fails_closed() -> None:
    with pytest.raises(AutomaticExitExecutorModeError, match="UNSUPPORTED_EXECUTOR_MODE"):
        submit_automatic_exit_plan_to_execution_handoff_v1(
            plan=_plan(), executor_mode="SANDBOX", executor_identity="shared-executor-v1",
            runtime_owner="devlap", handoff_repository=_repository(),
        )


def test_executor_identity_and_runtime_owner_passed_through_exactly() -> None:
    credentials = FakeCredentialRepository()
    handoff = submit_automatic_exit_plan_to_execution_handoff_v1(
        plan=_plan(), executor_mode="PAPER", executor_identity="my-executor",
        runtime_owner="odroid", handoff_repository=_repository(credentials=credentials),
    )
    assert handoff.executor_identity == "my-executor"
    assert handoff.runtime_owner == "odroid"
    assert credentials.calls[0]["executor_identity"] == "my-executor"
    assert credentials.calls[0]["runtime_owner"] == "odroid"


def test_retry_returns_same_handoff_under_same_identity() -> None:
    database = MemoryDatabase()
    plan = _plan()
    repository = _repository(database=database)
    first = submit_automatic_exit_plan_to_execution_handoff_v1(
        plan=plan, executor_mode="PAPER", executor_identity="shared-executor-v1",
        runtime_owner="devlap", handoff_repository=repository,
    )
    second = submit_automatic_exit_plan_to_execution_handoff_v1(
        plan=plan, executor_mode="PAPER", executor_identity="shared-executor-v1",
        runtime_owner="devlap", handoff_repository=repository,
    )
    assert first == second
    assert len(database.rows) == 1


def test_same_plan_reference_id_with_changed_content_raises_identity_conflict() -> None:
    """#206 behavior, unmodified: same plan_reference_id but a different plan
    payload must never silently overwrite -- this seam does not add or bypass
    that check."""
    database = MemoryDatabase()
    repository = _repository(database=database)
    plan = _plan()
    submit_automatic_exit_plan_to_execution_handoff_v1(
        plan=plan, executor_mode="PAPER", executor_identity="shared-executor-v1",
        runtime_owner="devlap", handoff_repository=repository,
    )
    # Same trading_account_id/position_reference/evidence but a different leg
    # (higher reference price) still derives a *different* plan_reference_id
    # under the real adapter (by design -- see adapter identity tests), so to
    # exercise the #206-owned conflict path directly we bypass the adapter
    # and reuse its derived id with a mutated plan via the shared repository.
    from src.executor.execution_plan_reference_v1 import ApprovedExecutionPlanV1, ExecutionPlanLegV1
    reference_id = derive_automatic_exit_plan_reference_id_v1(plan)
    conflicting = ApprovedExecutionPlanV1(
        plan_source="automatic_exit_planner_v1",
        plan_reference_id=reference_id,
        trading_account_id=plan.trading_account_id,
        venue=plan.venue,
        market=plan.market,
        side=plan.side,
        legs=(ExecutionPlanLegV1(leg_index=1, side="SELL", price=Decimal("999"), quantity=Decimal("0.1")),),
    )
    with pytest.raises(ExecutionHandoffIdentityConflictError):
        repository.intake(
            plan=conflicting, executor_mode="PAPER", executor_identity="shared-executor-v1", runtime_owner="devlap",
        )


# --- Credential / LIVE-authority / kill-switch denial stay #206-owned ----


def test_credential_denial_is_owned_by_206_not_pre_checked_by_seam() -> None:
    credentials = FakeCredentialRepository(denied=True)
    with pytest.raises(ExecutionHandoffDeniedError):
        submit_automatic_exit_plan_to_execution_handoff_v1(
            plan=_plan(), executor_mode="PAPER", executor_identity="shared-executor-v1",
            runtime_owner="devlap", handoff_repository=_repository(credentials=credentials),
        )


def test_live_authority_denial_is_owned_by_206_not_pre_checked_by_seam() -> None:
    authority = FakeLiveAuthorityRepository(permitted=False)
    with pytest.raises(ExecutionHandoffDeniedError):
        submit_automatic_exit_plan_to_execution_handoff_v1(
            plan=_plan(), executor_mode="LIVE", executor_identity="shared-executor-v1",
            runtime_owner="devlap", handoff_repository=_repository(authority=authority),
        )


def test_kill_switch_engaged_denies_live_and_is_owned_by_206() -> None:
    kill_switch = FakeKillSwitchRepository(engaged=True)
    with pytest.raises(ExecutionHandoffDeniedError):
        submit_automatic_exit_plan_to_execution_handoff_v1(
            plan=_plan(), executor_mode="LIVE", executor_identity="shared-executor-v1",
            runtime_owner="devlap", handoff_repository=_repository(kill_switch=kill_switch),
        )
    assert kill_switch.calls >= 1


# --- account_mode -> executor_mode mapping -------------------------------


def test_paper_account_mode_maps_to_paper_executor_mode() -> None:
    assert resolve_automatic_exit_executor_mode_v1("paper") == "PAPER"


def test_live_account_mode_maps_to_live_executor_mode() -> None:
    assert resolve_automatic_exit_executor_mode_v1("live") == "LIVE"


def test_unsupported_account_mode_fails_closed() -> None:
    with pytest.raises(AutomaticExitExecutorModeError, match="UNSUPPORTED_ACCOUNT_MODE_FOR_EXECUTOR_HANDOFF"):
        resolve_automatic_exit_executor_mode_v1("sandbox")


def test_live_readonly_account_mode_never_resolves_to_any_executor_mode() -> None:
    """Issue #551: live_readonly (real broker, read-only) must fail closed
    before any executor mode is derived -- it is deliberately absent from
    the account_mode -> executor_mode map, and this asserts the explicit
    rejection reason rather than relying on an accidental KeyError."""
    with pytest.raises(AutomaticExitExecutorModeError, match="ACCOUNT_MODE_NOT_EXECUTION_ELIGIBLE"):
        resolve_automatic_exit_executor_mode_v1("live_readonly")
