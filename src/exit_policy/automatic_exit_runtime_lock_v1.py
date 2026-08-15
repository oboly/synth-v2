"""Host-local singleton lock for one automatic-exit runtime cycle scope.

Scope is (trading_account_id, venue, asset_id, market): overlapping runs for
the exact same candidate cannot double-evaluate or double-plan, while runs
for different accounts/markets never block each other. This is a plain
``flock`` file lock, the same mechanism already used by
``src.market_data.run_canonical_fib_zone_map_v1`` and
``src.market_data.native_short_fib_context_snapshot_v1``. It grants no
cross-host coordination; production runtime-host ownership is documented
separately (see docs/architecture/automatic_exit_policy_v1.md Phase 4).

broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
"""
from __future__ import annotations

import fcntl
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


DEFAULT_LOCK_DIR: Path = Path("/tmp")


class AutomaticExitRuntimeLockHeldError(RuntimeError):
    """Raised when another process already holds the singleton lock."""


def default_lock_path(
    *, trading_account_id: int, venue: str, asset_id: int, market: str, lock_dir: Path = DEFAULT_LOCK_DIR,
) -> Path:
    safe_market = market.strip().upper().replace("/", "-")
    safe_venue = venue.strip().lower()
    return lock_dir / (
        f"synth-automatic-exit-runtime-cycle-v1-{trading_account_id}-{safe_venue}-{asset_id}-{safe_market}.lock"
    )


@contextmanager
def acquire_singleton_lock(path: Path) -> Iterator[None]:
    """Hold an exclusive, non-blocking flock on ``path`` for the block body.

    Raises ``AutomaticExitRuntimeLockHeldError`` immediately rather than
    blocking when another process (or another open handle) already holds it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise AutomaticExitRuntimeLockHeldError(f"LOCK_HELD:{path}") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
