from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

import pytest

from src.account_provisioning.credential_crypto_v1 import (
    MASTER_KEY_ENV_VAR,
    generate_test_master_key,
)
from src.executor.execution_handoff_v1 import RUNTIME_MODE_LIVE
from src.executor.live_canary_bounds_v1 import LiveCanaryBoundsV1
from src.executor.shared_execution_runtime_v1 import (
    LiveExecutorRuntimeAdapterFactoryV1,
    SharedExecutorModeAdapterUnavailableError,
    SharedExecutorRuntimeConfigV1,
    SharedExecutorRuntimeConfigurationError,
    build_runtime_adapter_factory_v1,
)


def _config() -> SharedExecutorRuntimeConfigV1:
    return SharedExecutorRuntimeConfigV1(
        executor_mode=RUNTIME_MODE_LIVE,
        runtime_owner="gurkdb",
        executor_identity="shared-executor-v1",
        worker_id="shared-executor-v1:test:1",
        operator_id=9,
    )


def _canary_bounds() -> LiveCanaryBoundsV1:
    return LiveCanaryBoundsV1(
        version="v1",
        allowed_trading_account_id=3,
        allowed_venue="bitvavo",
        allowed_market="BTC-EUR",
        allowed_side="BUY",
        max_orders_per_cycle=1,
        max_notional_eur=Decimal("10"),
        kill_switch_required=True,
        withdrawal_permission=False,
    )


class _FakeConn:
    def __init__(self) -> None:
        self.closed = False

    def cursor(self):  # pragma: no cover - not exercised in these tests
        raise AssertionError("cursor must not be constructed in these tests")

    def close(self) -> None:
        self.closed = True


def _grant_env(monkeypatch) -> None:
    monkeypatch.setenv("SYNTH_LIVE_EXECUTION_PERMISSION", "GRANTED")
    monkeypatch.setenv("SYNTH_BROKER_WRITE_PERMISSION", "GRANTED")
    monkeypatch.setenv(MASTER_KEY_ENV_VAR, generate_test_master_key())


def test_live_composition_blocked_when_broker_write_permission_not_granted(monkeypatch) -> None:
    monkeypatch.setenv("SYNTH_LIVE_EXECUTION_PERMISSION", "GRANTED")
    monkeypatch.delenv("SYNTH_BROKER_WRITE_PERMISSION", raising=False)
    with pytest.raises(SharedExecutorModeAdapterUnavailableError, match="BROKER_WRITE_PERMISSION_NOT_GRANTED"):
        build_runtime_adapter_factory_v1(_config())


def test_live_composition_blocked_for_non_canonical_executor_identity(monkeypatch) -> None:
    _grant_env(monkeypatch)
    config = replace(_config(), executor_identity="some-other-executor")
    with pytest.raises(SharedExecutorModeAdapterUnavailableError, match="LIVE_EXECUTOR_IDENTITY_NOT_AUTHORIZED"):
        build_runtime_adapter_factory_v1(config)


def test_live_composition_blocked_when_canary_bounds_unresolved(monkeypatch) -> None:
    _grant_env(monkeypatch)
    with pytest.raises(SharedExecutorModeAdapterUnavailableError, match="LIVE_CANARY_BOUNDS_UNRESOLVED"):
        build_runtime_adapter_factory_v1(
            _config(),
            live_canary_bounds_loader=lambda: (_ for _ in ()).throw(ValueError("boom")),
        )


def test_live_composition_blocked_when_master_key_missing(monkeypatch) -> None:
    monkeypatch.setenv("SYNTH_LIVE_EXECUTION_PERMISSION", "GRANTED")
    monkeypatch.setenv("SYNTH_BROKER_WRITE_PERMISSION", "GRANTED")
    monkeypatch.delenv(MASTER_KEY_ENV_VAR, raising=False)
    with pytest.raises(SharedExecutorModeAdapterUnavailableError, match="LIVE_MASTER_KEY_UNAVAILABLE"):
        build_runtime_adapter_factory_v1(
            _config(),
            live_canary_bounds_loader=_canary_bounds,
        )


def test_live_composition_blocked_when_db_connection_fails(monkeypatch) -> None:
    _grant_env(monkeypatch)
    with pytest.raises(SharedExecutorModeAdapterUnavailableError, match="LIVE_DB_CONNECTION_FAILED"):
        build_runtime_adapter_factory_v1(
            _config(),
            live_canary_bounds_loader=_canary_bounds,
            live_connection_factory=lambda: (_ for _ in ()).throw(RuntimeError("no db")),
        )


def test_live_composition_succeeds_only_after_every_gate_passes(monkeypatch) -> None:
    _grant_env(monkeypatch)
    conn = _FakeConn()
    factory = build_runtime_adapter_factory_v1(
        _config(),
        live_canary_bounds_loader=_canary_bounds,
        live_connection_factory=lambda: conn,
    )
    assert isinstance(factory, LiveExecutorRuntimeAdapterFactoryV1)
    assert factory.canary_bounds.allowed_trading_account_id == 3
    assert factory.conn is conn
    factory.close()
    assert conn.closed is True


@dataclass
class _Handoff:
    handoff_id: int | None
    executor_mode: str
    runtime_owner: str
    executor_identity: str
    trading_account_id: int
    venue: str
    market: str
    side: str


def test_adapter_for_handoff_rejects_out_of_scope_handoff_before_db_work(monkeypatch) -> None:
    _grant_env(monkeypatch)
    conn = _FakeConn()
    factory = build_runtime_adapter_factory_v1(
        _config(),
        live_canary_bounds_loader=_canary_bounds,
        live_connection_factory=lambda: conn,
    )
    handoff = _Handoff(
        handoff_id=None,
        executor_mode=RUNTIME_MODE_LIVE,
        runtime_owner="gurkdb",
        executor_identity="shared-executor-v1",
        trading_account_id=999,
        venue="bitvavo",
        market="BTC-EUR",
        side="BUY",
    )
    from src.executor.live_canary_bounds_v1 import LiveCanaryScopeDeniedError

    with pytest.raises(LiveCanaryScopeDeniedError):
        factory.adapter_for_handoff(handoff)


def test_adapter_for_handoff_rejects_runtime_identity_mismatch(monkeypatch) -> None:
    _grant_env(monkeypatch)
    conn = _FakeConn()
    factory = build_runtime_adapter_factory_v1(
        _config(),
        live_canary_bounds_loader=_canary_bounds,
        live_connection_factory=lambda: conn,
    )
    handoff = _Handoff(
        handoff_id=None,
        executor_mode=RUNTIME_MODE_LIVE,
        runtime_owner="wrong-owner",
        executor_identity="shared-executor-v1",
        trading_account_id=3,
        venue="bitvavo",
        market="BTC-EUR",
        side="BUY",
    )
    with pytest.raises(SharedExecutorRuntimeConfigurationError, match="HANDOFF_RUNTIME_IDENTITY_MISMATCH"):
        factory.adapter_for_handoff(handoff)
