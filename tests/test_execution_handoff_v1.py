from __future__ import annotations

from decimal import Decimal

import pytest
from pymysql.err import IntegrityError

from src.executor.execution_credential_scope_v1 import (
    CredentialScopeBinding,
    CredentialScopeDeniedError,
)
from src.executor.execution_handoff_v1 import (
    ExecutionHandoffDeniedError,
    ExecutionHandoffIdentityConflictError,
    ExecutionHandoffRepositoryV1,
)
from src.executor.execution_live_authority_v1 import ExecutionLiveAuthorityDeniedError
from src.executor.execution_plan_reference_v1 import (
    ApprovedExecutionPlanV1,
    ExecutionPlanLegV1,
)


def make_plan(
    *, reference: str = "plan-1", price: str = "100"
) -> ApprovedExecutionPlanV1:
    return ApprovedExecutionPlanV1(
        plan_source="AUTOMATIC_TEST_PLAN_V1",
        plan_reference_id=reference,
        trading_account_id=7,
        venue="bitvavo",
        market="BTC-EUR",
        side="BUY",
        legs=(
            ExecutionPlanLegV1(
                leg_index=1,
                side="BUY",
                price=Decimal(price),
                quantity=Decimal("0.1"),
            ),
        ),
    )


class CredentialRepository:
    def __init__(self, binding_id: int = 3) -> None:
        self.binding_id = binding_id
        self.calls: list[dict[str, object]] = []

    def resolve(self, **kwargs) -> CredentialScopeBinding:
        self.calls.append(kwargs)
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


class LiveAuthorityRepository:
    def __init__(self, *, permitted: bool = True) -> None:
        self.permitted = permitted
        self.calls: list[dict[str, object]] = []

    def resolve_effective(self, **kwargs):
        self.calls.append(kwargs)
        if not self.permitted:
            raise ExecutionLiveAuthorityDeniedError("EXECUTION_LIVE_AUTHORITY_NOT_GRANTED")
        return object()


class KillSwitchRepository:
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
        if sql.startswith("INSERT INTO executor_execution_handoff"):
            if self.database.insert_error is not None:
                raise self.database.insert_error
            key = (str(params[0]), str(params[1]))
            if key in self.database.rows:
                raise IntegrityError(1062, "duplicate plan reference")
            handoff_id = self.database.next_id
            self.database.next_id += 1
            self.lastrowid = handoff_id
            self.database.rows[key] = {
                "executor_execution_handoff_id": handoff_id,
                "plan_source": params[0],
                "plan_reference_id": params[1],
                "plan_content_hash": params[2],
                "trading_account_id": params[3],
                "venue": params[4],
                "market": params[5],
                "side": params[6],
                "executor_mode": params[7],
                "executor_identity": params[8],
                "runtime_owner": params[9],
                "executor_credential_binding_id": params[10],
            }
            return
        if "WHERE plan_source=%s AND plan_reference_id=%s" in sql:
            self.selected = self.database.rows.get((str(params[0]), str(params[1])))
            return
        if "WHERE executor_execution_handoff_id=%s" in sql:
            target = int(params[0])
            self.selected = next(
                (
                    row
                    for row in self.database.rows.values()
                    if row["executor_execution_handoff_id"] == target
                ),
                None,
            )
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
        self.insert_error: BaseException | None = None

    def cursor_factory(self, **_kwargs) -> MemoryContext:
        return MemoryContext(self)


def make_repository(
    database: MemoryDatabase | None = None,
    credentials: CredentialRepository | None = None,
    authority: LiveAuthorityRepository | None = None,
    kill_switch: KillSwitchRepository | None = None,
) -> ExecutionHandoffRepositoryV1:
    database = database or MemoryDatabase()
    return ExecutionHandoffRepositoryV1(
        cursor_factory=database.cursor_factory,
        credential_scope_repository=credentials or CredentialRepository(),
        live_authority_repository=authority or LiveAuthorityRepository(),
        kill_switch_repository=kill_switch or KillSwitchRepository(),
    )


def test_identical_plan_reference_and_identity_is_idempotent() -> None:
    database = MemoryDatabase()
    repository = make_repository(database)
    first = repository.intake(
        plan=make_plan(),
        executor_mode="PAPER",
        executor_identity="shared-executor-v1",
        runtime_owner="devlap",
    )
    second = repository.intake(
        plan=make_plan(),
        executor_mode="PAPER",
        executor_identity="shared-executor-v1",
        runtime_owner="devlap",
    )
    assert first == second
    assert len(database.rows) == 1


def test_same_plan_reference_with_different_content_fails_closed() -> None:
    database = MemoryDatabase()
    repository = make_repository(database)
    repository.intake(
        plan=make_plan(price="100"),
        executor_mode="PAPER",
        executor_identity="shared-executor-v1",
        runtime_owner="devlap",
    )
    with pytest.raises(ExecutionHandoffIdentityConflictError):
        repository.intake(
            plan=make_plan(price="101"),
            executor_mode="PAPER",
            executor_identity="shared-executor-v1",
            runtime_owner="devlap",
        )


def test_ordinary_live_intake_remains_denied_without_other_boundary_calls() -> None:
    credentials = CredentialRepository()
    authority = LiveAuthorityRepository()
    kill_switch = KillSwitchRepository()
    repository = make_repository(
        credentials=credentials,
        authority=authority,
        kill_switch=kill_switch,
    )
    with pytest.raises(ExecutionHandoffDeniedError, match="MODE_NOT_PERMITTED"):
        repository.intake(
            plan=make_plan(),
            executor_mode="LIVE",
            executor_identity="shared-executor-v1",
            runtime_owner="devlap",
        )
    assert credentials.calls == []
    assert authority.calls == []
    assert kill_switch.calls == 0


def test_internal_helper_cannot_bypass_authorized_live_intake() -> None:
    database = MemoryDatabase()
    credentials = CredentialRepository()
    authority = LiveAuthorityRepository(permitted=False)
    repository = make_repository(
        database=database,
        credentials=credentials,
        authority=authority,
    )
    with pytest.raises(
        ExecutionHandoffDeniedError,
        match="LIVE_REQUIRES_AUTHORIZED_INTAKE",
    ):
        repository._intake_permitted(
            plan=make_plan(),
            executor_mode="LIVE",
            executor_identity="shared-executor-v1",
            runtime_owner="devlap",
            require_live_authority=False,
        )
    assert credentials.calls == []
    assert authority.calls == []
    assert database.rows == {}


def test_credential_scope_denial_is_a_handoff_denial() -> None:
    class DeniedCredentials(CredentialRepository):
        def resolve(self, **_kwargs) -> CredentialScopeBinding:
            raise CredentialScopeDeniedError("CREDENTIAL_SCOPE_NOT_BOUND")

    repository = make_repository(credentials=DeniedCredentials())
    with pytest.raises(ExecutionHandoffDeniedError, match="CREDENTIAL_SCOPE_NOT_BOUND"):
        repository.intake(
            plan=make_plan(),
            executor_mode="DRY_RUN",
            executor_identity="shared-executor-v1",
            runtime_owner="devlap",
        )


def test_non_duplicate_database_failure_is_not_misclassified() -> None:
    database = MemoryDatabase()
    database.insert_error = RuntimeError("database unavailable")
    repository = make_repository(database)
    with pytest.raises(RuntimeError, match="database unavailable"):
        repository.intake(
            plan=make_plan(),
            executor_mode="PAPER",
            executor_identity="shared-executor-v1",
            runtime_owner="devlap",
        )


def test_live_authorized_intake_without_grant_persists_no_handoff() -> None:
    database = MemoryDatabase()
    repository = make_repository(
        database,
        authority=LiveAuthorityRepository(permitted=False),
    )
    with pytest.raises(ExecutionHandoffDeniedError, match="NOT_GRANTED"):
        repository.intake_live_authorized(
            plan=make_plan(),
            executor_identity="shared-executor-v1",
            runtime_owner="devlap",
        )
    assert database.rows == {}


def test_live_authorized_intake_with_engaged_kill_switch_persists_no_handoff() -> None:
    database = MemoryDatabase()
    authority = LiveAuthorityRepository()
    repository = make_repository(
        database,
        authority=authority,
        kill_switch=KillSwitchRepository(engaged=True),
    )
    with pytest.raises(ExecutionHandoffDeniedError, match="KILL_SWITCH_ENGAGED"):
        repository.intake_live_authorized(
            plan=make_plan(),
            executor_identity="shared-executor-v1",
            runtime_owner="devlap",
        )
    assert database.rows == {}
    assert authority.calls == []


@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_live_authorized_intake_uses_canonical_handoff_path_for_both_sides(
    side: str,
) -> None:
    database = MemoryDatabase()
    authority = LiveAuthorityRepository()
    repository = make_repository(database, authority=authority)
    plan = make_plan()
    if side == "SELL":
        plan = ApprovedExecutionPlanV1(
            plan_source=plan.plan_source,
            plan_reference_id="sell-plan-1",
            trading_account_id=plan.trading_account_id,
            venue=plan.venue,
            market=plan.market,
            side="SELL",
            legs=(
                ExecutionPlanLegV1(
                    leg_index=1,
                    side="SELL",
                    price=Decimal("100"),
                    quantity=Decimal("0.1"),
                ),
            ),
        )
    handoff = repository.intake_live_authorized(
        plan=plan,
        executor_identity="shared-executor-v1",
        runtime_owner="devlap",
    )
    assert handoff.executor_mode == "LIVE"
    assert handoff.side == side
    assert len(database.rows) == 1
    authority_call = dict(authority.calls[0])
    assert authority_call.pop("as_of_ts_utc", None) is not None
    assert authority_call == {
        "trading_account_id": 7,
        "venue": "bitvavo",
        "side": side,
        "market": "BTC-EUR",
        "executor_identity": "shared-executor-v1",
        "runtime_owner": "devlap",
    }


def test_live_authorized_intake_retry_is_idempotent_and_changed_content_conflicts() -> None:
    database = MemoryDatabase()
    repository = make_repository(database)
    kwargs = {
        "executor_identity": "shared-executor-v1",
        "runtime_owner": "devlap",
    }
    first = repository.intake_live_authorized(plan=make_plan(), **kwargs)
    second = repository.intake_live_authorized(plan=make_plan(), **kwargs)
    assert second == first
    assert len(database.rows) == 1
    with pytest.raises(ExecutionHandoffIdentityConflictError):
        repository.intake_live_authorized(
            plan=make_plan(price="101"),
            **kwargs,
        )
    assert len(database.rows) == 1
