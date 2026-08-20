from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from pymysql.err import IntegrityError

from src.executor.execution_credential_scope_v1 import CredentialScopeDeniedError
from src.executor.execution_handoff_v1 import (
    ExecutionHandoffDeniedError,
    ExecutionHandoffRepositoryV1,
)
from src.executor.execution_plan_reference_v1 import (
    ApprovedExecutionPlanV1,
    ExecutionPlanLegV1,
)


MIGRATION = Path(
    "db/migrations/20260820_shared_executor_dry_run_credential_decoupling_v1.sql"
)


def make_plan() -> ApprovedExecutionPlanV1:
    return ApprovedExecutionPlanV1(
        plan_source="ISSUE_461_TEST",
        plan_reference_id="dry-run-plan-1",
        trading_account_id=3,
        venue="bitvavo",
        market="BTC-EUR",
        side="BUY",
        legs=(
            ExecutionPlanLegV1(
                leg_index=1,
                side="BUY",
                price=Decimal("100"),
                quantity=Decimal("0.1"),
            ),
        ),
    )


class DeniedCredentials:
    def __init__(self) -> None:
        self.calls = 0

    def resolve(self, **_kwargs):
        self.calls += 1
        raise CredentialScopeDeniedError("CREDENTIAL_SCOPE_NOT_BOUND")


class NoLiveAuthority:
    def resolve_effective(self, **_kwargs):
        raise AssertionError("LIVE authority must not be reached without credential scope")


class KillSwitchOff:
    def is_engaged(self) -> bool:
        return False


class MemoryCursor:
    def __init__(self, database: "MemoryDatabase") -> None:
        self.database = database
        self.lastrowid = 0
        self.selected = None

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


def make_repository(database: MemoryDatabase, credentials: DeniedCredentials):
    return ExecutionHandoffRepositoryV1(
        cursor_factory=database.cursor_factory,
        credential_scope_repository=credentials,
        live_authority_repository=NoLiveAuthority(),
        kill_switch_repository=KillSwitchOff(),
    )


def test_dry_run_intake_never_resolves_trade_execution_credential() -> None:
    database = MemoryDatabase()
    credentials = DeniedCredentials()
    repository = make_repository(database, credentials)

    handoff = repository.intake(
        plan=make_plan(),
        executor_mode="DRY_RUN",
        executor_identity="shared-executor-v1",
        runtime_owner="gurkdb",
    )

    assert credentials.calls == 0
    assert handoff.executor_credential_binding_id is None
    assert len(database.rows) == 1


def test_dry_run_retry_preserves_same_handoff_identity_without_credentials() -> None:
    database = MemoryDatabase()
    credentials = DeniedCredentials()
    repository = make_repository(database, credentials)
    kwargs = {
        "plan": make_plan(),
        "executor_mode": "DRY_RUN",
        "executor_identity": "shared-executor-v1",
        "runtime_owner": "gurkdb",
    }

    first = repository.intake(**kwargs)
    second = repository.intake(**kwargs)

    assert second == first
    assert credentials.calls == 0
    assert len(database.rows) == 1


def test_live_intake_still_fails_closed_without_trade_execution_binding() -> None:
    database = MemoryDatabase()
    credentials = DeniedCredentials()
    repository = make_repository(database, credentials)

    with pytest.raises(ExecutionHandoffDeniedError, match="CREDENTIAL_SCOPE_NOT_BOUND"):
        repository.intake_live_authorized(
            plan=make_plan(),
            executor_identity="shared-executor-v1",
            runtime_owner="gurkdb",
        )

    assert credentials.calls == 1
    assert database.rows == {}


def test_migration_makes_binding_nullable_only_with_mode_invariant() -> None:
    text = MIGRATION.read_text()

    assert "MODIFY COLUMN executor_credential_binding_id BIGINT UNSIGNED NULL" in text
    assert "executor_mode = 'DRY_RUN' AND executor_credential_binding_id IS NULL" in text
    assert "executor_mode IN ('PAPER', 'LIVE') AND executor_credential_binding_id IS NOT NULL" in text
    assert "CREATE TABLE" not in text
    assert "DROP TABLE" not in text
    assert "live_trading_enabled" not in text
    assert "trading_account_credential" not in text
