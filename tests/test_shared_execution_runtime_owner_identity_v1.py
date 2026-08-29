from __future__ import annotations

import pytest

from src.executor.execution_handoff_v1 import RUNTIME_MODE_LIVE
from src.executor.shared_execution_runtime_v1 import (
    SharedExecutorModeAdapterUnavailableError,
    SharedExecutorRuntimeConfigV1,
    build_runtime_adapter_factory_v1,
)


def test_live_shared_executor_rejects_noncanonical_runtime_owner_before_private_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SYNTH_LIVE_EXECUTION_PERMISSION", "GRANTED")
    monkeypatch.setenv("SYNTH_BROKER_WRITE_PERMISSION", "GRANTED")

    config = SharedExecutorRuntimeConfigV1(
        executor_mode=RUNTIME_MODE_LIVE,
        runtime_owner="odroid",
        executor_identity="shared-executor-v1",
        worker_id="shared-executor-v1:test:wrong-owner",
        operator_id=9,
    )

    def _must_not_resolve_canary():
        raise AssertionError("canary resolution must not run for wrong runtime owner")

    with pytest.raises(
        SharedExecutorModeAdapterUnavailableError,
        match="LIVE_RUNTIME_OWNER_NOT_AUTHORIZED",
    ):
        build_runtime_adapter_factory_v1(
            config,
            live_canary_bounds_loader=_must_not_resolve_canary,
        )
