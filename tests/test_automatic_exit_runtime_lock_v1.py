from __future__ import annotations

from pathlib import Path

import pytest

from src.exit_policy.automatic_exit_runtime_lock_v1 import (
    AutomaticExitRuntimeLockHeldError,
    acquire_singleton_lock,
    default_lock_path,
)


def test_default_lock_path_is_deterministic_and_scoped_per_candidate(tmp_path: Path) -> None:
    a = default_lock_path(trading_account_id=7, venue="bitvavo", asset_id=42, market="SOL-EUR", lock_dir=tmp_path)
    b = default_lock_path(trading_account_id=7, venue="bitvavo", asset_id=42, market="SOL-EUR", lock_dir=tmp_path)
    c = default_lock_path(trading_account_id=8, venue="bitvavo", asset_id=42, market="SOL-EUR", lock_dir=tmp_path)
    assert a == b
    assert a != c


def test_overlapping_acquire_fails_closed_and_release_allows_reacquire(tmp_path: Path) -> None:
    path = tmp_path / "automatic-exit.lock"
    with acquire_singleton_lock(path):
        with pytest.raises(AutomaticExitRuntimeLockHeldError):
            with acquire_singleton_lock(path):
                pass  # pragma: no cover - must not be reached

    # Lock released on context exit; a fresh acquire must succeed.
    with acquire_singleton_lock(path):
        pass


def test_lock_dir_is_created_if_missing(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "dir" / "automatic-exit.lock"
    with acquire_singleton_lock(path):
        assert path.exists()
