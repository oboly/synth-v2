from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.executor.bitvavo_order_adapter_v1 import (
    BitvavoAdapterUnavailableError,
    build_bitvavo_order_adapter_v1,
)
from src.executor.execution_credential_scope_v1 import (
    CredentialScopeBinding,
    CredentialScopeDeniedError,
    ExecutorCredentialScopeRepository,
)
from src.executor.execution_handoff_v1 import ExecutionHandoffV1
from src.executor.execution_live_authority_v1 import ExecutionLiveAuthorityDeniedError


def _handoff(**changes: object) -> ExecutionHandoffV1:
    values: dict[str, object] = dict(
        handoff_id=17,
        plan_source="automatic_buy_planner_v1",
        plan_reference_id="automatic_buy_v1:101:ev-1:abc",
        plan_content_hash="a" * 64,
        trading_account_id=101,
        venue="bitvavo",
        market="BTC-EUR",
        side="BUY",
        executor_mode="LIVE",
        executor_identity="shared-executor-v1",
        runtime_owner="gurkdb",
        executor_credential_binding_id=9,
    )
    values.update(changes)
    return ExecutionHandoffV1(**values)  # type: ignore[arg-type]


def _binding(**changes: object) -> CredentialScopeBinding:
    value = CredentialScopeBinding(
        executor_credential_binding_id=9,
        trading_account_credential_id=22,
        trading_account_id=101,
        venue="bitvavo",
        permission_scope="TRADE_EXECUTION",
        executor_identity="shared-executor-v1",
        runtime_owner="gurkdb",
        credential_status="ACTIVE",
        credential_source="test_non_secret_metadata",
        allowed_order_write=True,
        allowed_withdrawal=False,
        binding_status="ACTIVE",
    )
    return replace(value, **changes)


class _CredentialCursor:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def execute(self, _sql: str, _params: list[object]) -> None:
        pass

    def fetchall(self) -> list[dict[str, object]]:
        return self.rows


def _credential_row(**changes: object) -> dict[str, object]:
    row: dict[str, object] = {
        "executor_credential_binding_id": 9,
        "trading_account_credential_id": 22,
        "trading_account_id": 101,
        "venue": "bitvavo",
        "permission_scope": "TRADE_EXECUTION",
        "executor_identity": "shared-executor-v1",
        "runtime_owner": "gurkdb",
        "binding_status": "ACTIVE",
        "credential_trading_account_id": 101,
        "credential_venue": "bitvavo",
        "credential_permission_scope": "TRADE_EXECUTION",
        "credential_status": "ACTIVE",
        "credential_source": "test_non_secret_metadata",
        "allowed_order_write": 1,
        "allowed_withdrawal": 0,
    }
    row.update(changes)
    return row


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"permission_scope": "READ_ONLY", "credential_permission_scope": "READ_ONLY"}, "NOT_TRADE_EXECUTION"),
        ({"credential_status": "DISABLED"}, "CREDENTIAL_NOT_ACTIVE"),
        ({"allowed_order_write": 0}, "ORDER_WRITE_NOT_PERMITTED"),
        ({"allowed_withdrawal": 1}, "WITHDRAWAL_CAPABLE_CREDENTIAL_DENIED"),
    ],
)
def test_trade_execution_scope_is_exact_and_withdrawal_disabled(
    changes: dict[str, object], reason: str,
) -> None:
    cursor = _CredentialCursor([_credential_row(**changes)])
    with pytest.raises(CredentialScopeDeniedError, match=reason):
        ExecutorCredentialScopeRepository._resolve(
            cursor,
            trading_account_id=101,
            venue="bitvavo",
            executor_identity="shared-executor-v1",
            runtime_owner="gurkdb",
        )


def test_credential_scope_ambiguity_fails_closed() -> None:
    cursor = _CredentialCursor([_credential_row(), _credential_row()])
    with pytest.raises(CredentialScopeDeniedError, match="AMBIGUOUS"):
        ExecutorCredentialScopeRepository._resolve(
            cursor,
            trading_account_id=101,
            venue="bitvavo",
            executor_identity="shared-executor-v1",
            runtime_owner="gurkdb",
        )


class _Scope:
    def __init__(self, binding: CredentialScopeBinding) -> None:
        self.binding = binding
        self.calls: list[dict[str, object]] = []

    def resolve(self, **kwargs: object) -> CredentialScopeBinding:
        self.calls.append(kwargs)
        return self.binding


class _Handoffs:
    def __init__(self, persisted: ExecutionHandoffV1 | None) -> None:
        self.persisted = persisted
        self.calls: list[int] = []

    def find(self, handoff_id: int) -> ExecutionHandoffV1 | None:
        self.calls.append(handoff_id)
        return self.persisted


class _KillSwitch:
    def __init__(self, engaged: bool) -> None:
        self.engaged = engaged
        self.calls = 0

    def is_engaged(self) -> bool:
        self.calls += 1
        return self.engaged


class _Authority:
    def __init__(self, permitted: bool) -> None:
        self.permitted = permitted
        self.calls: list[dict[str, object]] = []

    def resolve_effective(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if not self.permitted:
            raise ExecutionLiveAuthorityDeniedError("EXECUTION_LIVE_AUTHORITY_NOT_GRANTED")
        return object()


def _adapter_fixture(*, kill_engaged: bool = False, authority_permitted: bool = True):
    handoff = _handoff()
    scope = _Scope(_binding())
    handoffs = _Handoffs(handoff)
    kill = _KillSwitch(kill_engaged)
    authority = _Authority(authority_permitted)
    events: list[str] = []

    def credential_loader(*_args: object, **_kwargs: object) -> object:
        events.append("credential_secret_loaded")
        return SimpleNamespace(api_key="fake", api_secret="fake")

    def client_factory(**_kwargs: object) -> object:
        events.append("private_client_constructed")
        return object()

    adapter = build_bitvavo_order_adapter_v1(
        handoff=handoff,
        conn=object(),
        master_key_bytes=b"x" * 32,
        cred_repo_factory=object(),
        credential_scope_repository=scope,  # type: ignore[arg-type]
        handoff_repository=handoffs,  # type: ignore[arg-type]
        live_authority_repository=authority,  # type: ignore[arg-type]
        kill_switch_repository=kill,  # type: ignore[arg-type]
        credential_loader=credential_loader,
        client_factory=client_factory,  # type: ignore[arg-type]
    )
    return adapter, scope, handoffs, kill, authority, events


def test_engaged_kill_switch_blocks_before_secret_or_client_construction() -> None:
    adapter, scope, handoffs, kill, authority, events = _adapter_fixture(kill_engaged=True)
    with pytest.raises(BitvavoAdapterUnavailableError, match="LIVE_AUTHORITY_DENIED"):
        adapter._fresh_client()
    assert handoffs.calls == [17, 17]
    assert len(scope.calls) == 1
    assert kill.calls == 1
    assert authority.calls == []
    assert events == []


def test_missing_live_authority_blocks_before_secret_or_client_construction() -> None:
    adapter, scope, handoffs, kill, authority, events = _adapter_fixture(authority_permitted=False)
    with pytest.raises(BitvavoAdapterUnavailableError, match="LIVE_AUTHORITY_DENIED"):
        adapter._fresh_client()
    assert handoffs.calls == [17, 17]
    assert len(scope.calls) == 1
    assert kill.calls == 1
    assert len(authority.calls) == 1
    assert events == []


def test_buy_authority_is_bound_to_exact_handoff_identity() -> None:
    adapter, _scope, handoffs, kill, authority, events = _adapter_fixture()
    client = adapter._fresh_client()
    assert client is not None
    assert handoffs.calls == [17, 17]
    assert kill.calls == 1
    assert events == ["credential_secret_loaded", "private_client_constructed"]
    call = authority.calls[0]
    assert {key: call[key] for key in (
        "trading_account_id", "venue", "side", "market", "executor_identity", "runtime_owner"
    )} == {
        "trading_account_id": 101,
        "venue": "bitvavo",
        "side": "BUY",
        "market": "BTC-EUR",
        "executor_identity": "shared-executor-v1",
        "runtime_owner": "gurkdb",
    }


def test_persisted_handoff_mismatch_blocks_before_credential_resolution() -> None:
    handoff = _handoff()
    scope = _Scope(_binding())
    mismatched = _Handoffs(_handoff(market="ETH-EUR"))
    with pytest.raises(BitvavoAdapterUnavailableError, match="PERSISTED_HANDOFF_IDENTITY_MISMATCH"):
        build_bitvavo_order_adapter_v1(
            handoff=handoff,
            conn=object(),
            master_key_bytes=b"x" * 32,
            cred_repo_factory=object(),
            credential_scope_repository=scope,  # type: ignore[arg-type]
            handoff_repository=mismatched,  # type: ignore[arg-type]
            live_authority_repository=_Authority(True),  # type: ignore[arg-type]
            kill_switch_repository=_KillSwitch(False),  # type: ignore[arg-type]
            credential_loader=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("must not load")),
            client_factory=lambda **_k: (_ for _ in ()).throw(AssertionError("must not construct")),
        )
    assert mismatched.calls == [17]
    assert scope.calls == []
