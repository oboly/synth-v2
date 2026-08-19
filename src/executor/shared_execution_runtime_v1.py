"""Mode-explicit composition contract for the generic shared executor runtime.

The Phase-J deployment artifact composes DRY_RUN only. PAPER and LIVE remain
valid persisted handoff modes, but each requires a separately authorized,
truthful adapter; they never fall back to a synthetic or test adapter.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from src.executor.dry_run_order_adapter_v1 import DryRunOrderPlacementAdapterV1
from src.executor.execution_handoff_v1 import (
    RUNTIME_MODE_DRY_RUN,
    RUNTIME_MODE_LIVE,
    RUNTIME_MODE_PAPER,
    ExecutionHandoffV1,
)


DEFAULT_LEASE_SECONDS: Final[int] = 60
DEFAULT_BATCH_LIMIT: Final[int] = 100


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


def build_runtime_adapter_factory_v1(
    config: SharedExecutorRuntimeConfigV1,
) -> SharedExecutorRuntimeAdapterFactoryV1:
    """Fail before DB/private work when the selected mode lacks a real adapter."""
    if config.executor_mode == RUNTIME_MODE_PAPER:
        raise SharedExecutorModeAdapterUnavailableError("PAPER_ADAPTER_NOT_CONFIGURED")
    if config.executor_mode == RUNTIME_MODE_LIVE:
        raise SharedExecutorModeAdapterUnavailableError("LIVE_RUNTIME_NOT_AUTHORIZED")
    return SharedExecutorRuntimeAdapterFactoryV1(config)
