"""Mode-explicit composition contract for the generic shared executor runtime.

The Phase-J deployment artifact composes DRY_RUN only. PAPER and LIVE remain
valid persisted handoff modes, but each requires a separately authorized,
truthful adapter; they never fall back to a synthetic or test adapter.

LIVE composition (``_build_live_adapter_factory_v1``) is a reviewed,
LIVE-capable path only: it is never reached by the installed CLI runner,
which independently hard-requires both permission environment variables to
remain ``NOT_GRANTED`` before this module is ever invoked (see
``run_shared_execution_runtime_v1.config_from_args``). This module's own
LIVE gate sequence exists so the composed path can be built and tested in
isolation ahead of any separately authorized production activation.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable, Final

from src.account_provisioning.credential_crypto_v1 import load_master_key_from_env
from src.account_provisioning.credential_repository_v1 import CredentialRepository
from src.executor.bitvavo_order_adapter_v1 import (
    BitvavoOrderAdapterV1,
    build_bitvavo_order_adapter_v1,
)
from src.executor.dry_run_order_adapter_v1 import DryRunOrderPlacementAdapterV1
from src.executor.execution_handoff_v1 import (
    RUNTIME_MODE_DRY_RUN,
    RUNTIME_MODE_LIVE,
    RUNTIME_MODE_PAPER,
    ExecutionHandoffRepositoryV1,
    ExecutionHandoffV1,
)
from src.executor.live_canary_bounds_v1 import (
    LiveCanaryBoundsV1,
    assert_handoff_within_canary_scope_v1,
    assert_plan_notional_within_canary_bound_v1,
    load_live_canary_bounds_from_env_v1,
)


DEFAULT_LEASE_SECONDS: Final[int] = 60
DEFAULT_BATCH_LIMIT: Final[int] = 100

LIVE_EXECUTION_PERMISSION_ENV: Final[str] = "SYNTH_LIVE_EXECUTION_PERMISSION"
BROKER_WRITE_PERMISSION_ENV: Final[str] = "SYNTH_BROKER_WRITE_PERMISSION"
_GRANTED: Final[str] = "GRANTED"
_AUTHORIZED_LIVE_EXECUTOR_IDENTITY: Final[str] = "shared-executor-v1"


class SharedExecutorRuntimeConfigurationError(ValueError):
    pass


class SharedExecutorModeAdapterUnavailableError(PermissionError):
    pass


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SharedExecutorRuntimeConfigurationError(f"{field_name} required")
    return value.strip()


@dataclass(frozen=True)
class SharedExecutorRuntimeConfigV1:
    executor_mode: str
    runtime_owner: str
    executor_identity: str
    worker_id: str
    operator_id: int
    lease_seconds: int = DEFAULT_LEASE_SECONDS
    batch_limit: int = DEFAULT_BATCH_LIMIT

    def __post_init__(self) -> None:
        if self.executor_mode not in {
            RUNTIME_MODE_DRY_RUN,
            RUNTIME_MODE_PAPER,
            RUNTIME_MODE_LIVE,
        }:
            raise SharedExecutorRuntimeConfigurationError("executor_mode invalid")
        for name in ("runtime_owner", "executor_identity", "worker_id"):
            object.__setattr__(self, name, _required_text(getattr(self, name), name))
        for name in ("operator_id", "lease_seconds", "batch_limit"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise SharedExecutorRuntimeConfigurationError(f"{name} must be a positive integer")


class SharedExecutorRuntimeAdapterFactoryV1:
    """Identity-bound per-handoff factory; required for future LIVE adapters."""

    def __init__(self, config: SharedExecutorRuntimeConfigV1) -> None:
        self.config = config

    def adapter_for_handoff(self, handoff: ExecutionHandoffV1) -> DryRunOrderPlacementAdapterV1:
        if (
            handoff.executor_mode != self.config.executor_mode
            or handoff.runtime_owner != self.config.runtime_owner
            or handoff.executor_identity != self.config.executor_identity
        ):
            raise SharedExecutorRuntimeConfigurationError(
                "HANDOFF_RUNTIME_IDENTITY_MISMATCH"
            )
        return DryRunOrderPlacementAdapterV1()


@dataclass
class LiveExecutorRuntimeAdapterFactoryV1:
    """Identity- and canary-bound per-handoff LIVE factory.

    Construction alone grants nothing: every gate below (identity, canary
    scope, kill switch, execution-live-authority, credential scope) is
    re-checked per handoff by ``adapter_for_handoff``/``BitvavoOrderAdapterV1``
    before any broker-write client is built. No credential secret is loaded
    and no client is constructed at composition time.
    """

    config: SharedExecutorRuntimeConfigV1
    conn: Any = field(repr=False)
    master_key_bytes: bytes = field(repr=False)
    canary_bounds: LiveCanaryBoundsV1

    def adapter_for_handoff(self, handoff: ExecutionHandoffV1) -> BitvavoOrderAdapterV1:
        if (
            handoff.executor_mode != self.config.executor_mode
            or handoff.runtime_owner != self.config.runtime_owner
            or handoff.executor_identity != self.config.executor_identity
        ):
            raise SharedExecutorRuntimeConfigurationError(
                "HANDOFF_RUNTIME_IDENTITY_MISMATCH"
            )
        assert_handoff_within_canary_scope_v1(self.canary_bounds, handoff)
        handoff_repository = ExecutionHandoffRepositoryV1(
            cursor_factory=lambda **_kwargs: self.conn.cursor()
        )
        if handoff.handoff_id is not None:
            legs = handoff_repository.load_immutable_legs(handoff.handoff_id)
            assert_plan_notional_within_canary_bound_v1(self.canary_bounds, legs)
        return build_bitvavo_order_adapter_v1(
            handoff=handoff,
            conn=self.conn,
            master_key_bytes=self.master_key_bytes,
            cred_repo_factory=CredentialRepository,
            handoff_repository=handoff_repository,
        )

    def close(self) -> None:
        self.conn.close()


def _default_live_connection() -> Any:
    from src.common.db_core_v1 import get_connection

    return get_connection()


def _build_live_adapter_factory_v1(
    config: SharedExecutorRuntimeConfigV1,
    *,
    connection_factory: Callable[[], Any] | None,
    canary_bounds_loader: Callable[[], LiveCanaryBoundsV1],
) -> LiveExecutorRuntimeAdapterFactoryV1:
    """Compose the LIVE-capable adapter factory, or fail closed.

    Sequence: env permissions -> executor identity -> canary bounds resolved
    -> master key resolved -> DB connection resolved. No DB/broker/secret
    work happens before the cheap, deterministic checks earlier in the
    sequence.
    """
    if os.getenv(LIVE_EXECUTION_PERMISSION_ENV) != _GRANTED:
        raise SharedExecutorModeAdapterUnavailableError(
            "LIVE_EXECUTION_PERMISSION_NOT_GRANTED"
        )
    if os.getenv(BROKER_WRITE_PERMISSION_ENV) != _GRANTED:
        raise SharedExecutorModeAdapterUnavailableError(
            "BROKER_WRITE_PERMISSION_NOT_GRANTED"
        )
    if config.executor_identity != _AUTHORIZED_LIVE_EXECUTOR_IDENTITY:
        raise SharedExecutorModeAdapterUnavailableError(
            "LIVE_EXECUTOR_IDENTITY_NOT_AUTHORIZED"
        )
    try:
        canary_bounds = canary_bounds_loader()
    except Exception:
        raise SharedExecutorModeAdapterUnavailableError(
            "LIVE_CANARY_BOUNDS_UNRESOLVED"
        ) from None
    try:
        _, master_key_bytes = load_master_key_from_env()
    except ValueError:
        raise SharedExecutorModeAdapterUnavailableError(
            "LIVE_MASTER_KEY_UNAVAILABLE"
        ) from None
    resolve_connection = connection_factory or _default_live_connection
    try:
        conn = resolve_connection()
    except Exception:
        raise SharedExecutorModeAdapterUnavailableError(
            "LIVE_DB_CONNECTION_FAILED"
        ) from None
    return LiveExecutorRuntimeAdapterFactoryV1(
        config=config,
        conn=conn,
        master_key_bytes=master_key_bytes,
        canary_bounds=canary_bounds,
    )


def build_runtime_adapter_factory_v1(
    config: SharedExecutorRuntimeConfigV1,
    *,
    live_connection_factory: Callable[[], Any] | None = None,
    live_canary_bounds_loader: Callable[[], LiveCanaryBoundsV1] = load_live_canary_bounds_from_env_v1,
) -> SharedExecutorRuntimeAdapterFactoryV1 | LiveExecutorRuntimeAdapterFactoryV1:
    """Fail before DB/private work when the selected mode lacks a real adapter."""
    if config.executor_mode == RUNTIME_MODE_PAPER:
        raise SharedExecutorModeAdapterUnavailableError("PAPER_ADAPTER_NOT_CONFIGURED")
    if config.executor_mode == RUNTIME_MODE_LIVE:
        return _build_live_adapter_factory_v1(
            config,
            connection_factory=live_connection_factory,
            canary_bounds_loader=live_canary_bounds_loader,
        )
    return SharedExecutorRuntimeAdapterFactoryV1(config)
