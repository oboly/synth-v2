from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.entry_policy.run_automatic_buy_policy_once_v1 import (
    RuntimeOwnershipError,
    default_lock_path,
    validate_lock_path,
    verify_runtime_ownership,
)


def test_default_lock_path_is_under_home_state() -> None:
    path = default_lock_path()
    assert ".local/state/synth/runtime/locks" in str(path)
    assert path.name == "automatic-buy-policy-runtime.lock"


def test_tmp_lock_paths_are_rejected() -> None:
    with pytest.raises(ValueError):
        validate_lock_path(Path("/tmp/automatic-buy.lock"))
    with pytest.raises(ValueError):
        validate_lock_path(Path("/var/tmp/automatic-buy.lock"))


def test_runtime_ownership_requires_exact_registered_owner(tmp_path: Path) -> None:
    registry = tmp_path / "deploy/ownership/account_runtime_capability_ownership_v1.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(json.dumps({
        "capabilities": [{
            "capability_id": "AUTOMATIC_BUY_POLICY_RUNTIME",
            "owner_host": "gurkdb",
        }]
    }))
    verify_runtime_ownership(repo_root=tmp_path, expect_owner_host="gurkdb")
    with pytest.raises(RuntimeOwnershipError, match="OWNERSHIP_HOST_MISMATCH"):
        verify_runtime_ownership(repo_root=tmp_path, expect_owner_host="odroid")
