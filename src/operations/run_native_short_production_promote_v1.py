from __future__ import annotations

"""synth-native-short-promote: canonical native SHORT production activation
entrypoint.

Boundary: market-only, account-agnostic. This module creates no writer,
service, timer, or direct SQL mutation path of its own. It is a narrow
adapter that derives immutable request identity from the verified installed
checkout and delegates unchanged to
``src.market_data.run_native_short_scope_administration_rollout_v1`` (the
existing, unmodified rollout CLI over the canonical single-scope transaction
owner) and then, only after that rollout fully succeeds, to the existing
canonical ``scripts/run_chain_4h.sh`` chain (unchanged) to publish the
refreshed snapshot.

Problem this replaces
----------------------
The previous manual procedure required an operator to hand-edit
``/etc/synth/writer-capability-*-authorization-v1.json`` after every merged
commit (because the production authorization file historically pinned an
*exact* ``authorized_commit``), and to hand-reconstruct actor/trigger/
request-source/timestamp/metadata/``--repository-commit`` arguments for the
rollout CLI on every invocation. This module removes the second half of that
burden (argument reconstruction); the first half is addressed independently
by the new ``commit_verification_mode=ANCESTOR`` option on the production
authorization file itself
(``src.operations.writer_capability_authorization_v1``), which this module
does not bypass, weaken, or duplicate -- the real authorization decision
remains exactly where it already was: inside
``enforce_capability_write_authorization``, called by the rollout CLI before
any database connection.

Deterministic, hidden-state-free provenance
---------------------------------------------
Every provenance field fed to the rollout CLI is derived only from fixed,
already-available inputs -- never wall-clock "now" -- so that re-running
this exact command for the exact same symbols against the exact same
checked-out commit reproduces byte-identical request digests and hits the
existing ``OPERATION_ALREADY_COMPLETED`` / idempotent-success replay path
with zero separate run-state file:

- ``repository_commit`` -- the verified installed checkout's actual HEAD
  (``inspect_running_repository_source().head_sha``), never operator-supplied.
- ``requested_at_utc`` -- that exact commit's own commit timestamp
  (``git show -s --format=%cI``), converted to canonical UTC. Stable for as
  long as the checkout stays on that commit; a later approved deploy simply
  advances it, which is a genuinely new attempt, not a broken replay.
- ``actor_id`` -- the invoking human operator (``SUDO_USER`` when invoked via
  ``sudo``, else the current user), reflecting who actually ran it.
- ``actor_type`` / ``trigger_type`` / ``request_source`` / ``reason`` /
  ``metadata`` -- fixed literals identifying this wrapper, never varying
  between runs.

Approved symbols
------------------
Every requested symbol must already be a member of the checked-in
``APPROVED_ROLLOUT_UNIVERSE_V1``; this is enforced by
``resolve_rollout_entries`` before any database connection is opened
(unchanged from the underlying rollout CLI). This module adds no symbol
allow-list of its own and no wildcard.

Scoped writer runtime context
-------------------------------
The rollout CLI's authorization boundary
(``enforce_capability_write_authorization``) reads its execution mode from
``SYNTH_WRITER_EXECUTION_MODE`` when the caller does not pass ``mode``
explicitly, defaulting to ``READ_ONLY`` (fail closed) when that variable is
absent -- exactly like every other writer wrapper script in this repository
(``scripts/run_chain_4h.sh``, ``scripts/run_market_price_snapshot_once.sh``,
etc.). ``_writer_runtime_context`` sets ``SYNTH_WRITER_EXECUTION_MODE=
PRODUCTION`` and ``SYNTH_WRITER_CAPABILITY_ID=native_short_4h_chain`` (the
same capability identity constant already used by the rollout CLI and the
transaction owner) for the exact duration of the single, bounded
``rollout_cli.main(...)`` call only, and restores whatever value (or
absence) each variable had immediately beforehand -- on both the success and
the exception/failure path. It never mutates permanent host configuration
and never touches any other process environment. It does not authorize
anything by itself: it only ensures the rollout CLI observes the same
production mode a human operator would otherwise have to export by hand;
the real authorization decision, including host/checkout/commit/capability
verification, remains entirely inside the unmodified
``enforce_capability_write_authorization`` call. The canonical 4h chain,
invoked afterward via ``_run_chain``, keeps setting its own
``SYNTH_WRITER_EXECUTION_MODE``/``SYNTH_WRITER_CAPABILITY_ID`` exactly as it
already did (unchanged) once the scoped context above has been restored.

Safety markers:
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
map_materialization=0
snapshot_materialization=0
profit_plan_writes=0
reporting_writes=0
"""

import contextlib
import getpass
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from src.market_data.native_short_repository_source_identity_v1 import (
    REPOSITORY_ROOT,
    NativeShortRepositorySourceIdentityError,
    inspect_running_repository_source,
)
from src.market_data.native_short_scope_administration_rollout_v1 import (
    RolloutConfigurationError,
    resolve_rollout_entries,
)
from src.market_data import run_native_short_scope_administration_rollout_v1 as rollout_cli
from src.market_data.native_short_scope_administration_transaction_v1 import (
    WRITER_CAPABILITY_ID,
)
from src.operations.writer_capability_authorization_v1 import (
    ENV_CAPABILITY,
    ENV_MODE,
    ExecutionMode,
)


RUNNER_NAME = "run_native_short_production_promote_v1"
RUNNER_VERSION = "0.1"

ACTOR_TYPE = "HUMAN_OPERATOR"
TRIGGER_TYPE = "MANUAL_CLI"
REQUEST_SOURCE = "synth-native-short-promote"
REASON = (
    "Canonical native SHORT production promotion via synth-native-short-"
    "promote for the checked-in approved rollout universe entries requested "
    "on this invocation."
)

CHAIN_WRAPPER_RELATIVE_PATH = Path("scripts/run_chain_4h.sh")

_SAFETY_MARKERS = {
    "broker_private_calls": 0,
    "broker_writes": 0,
    "order_submission": 0,
    "live_orders": 0,
    "decision_gate": "none",
    "execution_planner": "none",
    "executor": "none",
    "map_materialization": 0,
    "snapshot_materialization": 0,
    "profit_plan_writes": 0,
    "reporting_writes": 0,
}


class PromotionAbortedError(RuntimeError):
    """Raised for a fail-closed condition detected before delegating to the
    rollout CLI -- never for a rollout-side or chain-side failure, which are
    reported through their own exit codes/output instead."""


def _actor_id() -> str:
    sudo_user = os.environ.get("SUDO_USER", "").strip()
    if sudo_user:
        return sudo_user
    return getpass.getuser()


def _commit_timestamp_utc(repository_root: Path, commit: str) -> str:
    """The exact commit's own commit timestamp, in canonical literal UTC
    (``YYYY-MM-DDTHH:MM:SSZ``). Deterministic for a fixed commit -- never
    wall-clock "now" -- so re-running this wrapper for the same checked-out
    commit reproduces an identical value."""
    completed = subprocess.run(
        ["git", "-C", str(repository_root), "show", "-s", "--format=%cI", commit],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        raise PromotionAbortedError(
            f"COMMIT_TIMESTAMP_UNAVAILABLE commit={commit} detail={completed.stderr.strip()}"
        )
    parsed = datetime.fromisoformat(completed.stdout.strip())
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True))
    sys.stdout.flush()


def _build_rollout_argv(
    *,
    symbols: list[str],
    repository_commit: str,
    requested_at_utc: str,
) -> list[str]:
    argv = [
        "--actor-type", ACTOR_TYPE,
        "--actor-id", _actor_id(),
        "--trigger-type", TRIGGER_TYPE,
        "--reason", REASON,
        "--request-source", REQUEST_SOURCE,
        "--repository-commit", repository_commit,
        "--requested-at-utc", requested_at_utc,
        "--metadata", "{}",
        "--write",
    ]
    for symbol in symbols:
        argv.extend(["--only-symbol", symbol])
    return argv


@contextlib.contextmanager
def _writer_runtime_context() -> Iterator[None]:
    """Set the exact writer runtime context the rollout CLI's authorization
    boundary expects (``SYNTH_WRITER_EXECUTION_MODE=PRODUCTION``,
    ``SYNTH_WRITER_CAPABILITY_ID=native_short_4h_chain``) for the duration of
    the wrapped block only, restoring whatever value -- or absence -- each
    variable had immediately before, on every exit path including an
    exception. Never mutates permanent host configuration."""
    previous: dict[str, str | None] = {
        ENV_MODE: os.environ.get(ENV_MODE),
        ENV_CAPABILITY: os.environ.get(ENV_CAPABILITY),
    }
    os.environ[ENV_MODE] = ExecutionMode.PRODUCTION.value
    os.environ[ENV_CAPABILITY] = WRITER_CAPABILITY_ID
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _run_chain(repository_root: Path) -> int:
    chain_script = repository_root / CHAIN_WRAPPER_RELATIVE_PATH
    completed = subprocess.run(["bash", str(chain_script)], cwd=str(repository_root), check=False)
    return completed.returncode


def parse_args(argv: list[str] | None = None) -> list[str]:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        raise PromotionAbortedError("NO_SYMBOLS_REQUESTED")
    return [symbol.strip().upper() for symbol in args if symbol.strip()]


def main(argv: list[str] | None = None) -> int:
    repository_root = REPOSITORY_ROOT

    try:
        symbols = parse_args(argv)
    except PromotionAbortedError as exc:
        _emit(_result("FAILED", reason_code=str(exc), symbols=[], **_SAFETY_MARKERS))
        return 2

    # Approved-universe check first, before any repository/authorization
    # inspection -- an unapproved symbol is rejected as cheaply as possible.
    try:
        resolve_rollout_entries(symbols)
    except RolloutConfigurationError as exc:
        _emit(_result("FAILED", reason_code="UNAPPROVED_SYMBOL", detail=str(exc), symbols=symbols, **_SAFETY_MARKERS))
        return 2

    try:
        state = inspect_running_repository_source()
        repository_commit = state.head_sha
        requested_at_utc = _commit_timestamp_utc(repository_root, repository_commit)
    except (NativeShortRepositorySourceIdentityError, PromotionAbortedError) as exc:
        _emit(_result("FAILED", reason_code="REPOSITORY_IDENTITY_UNAVAILABLE", detail=str(exc), symbols=symbols, **_SAFETY_MARKERS))
        return 2

    rollout_argv = _build_rollout_argv(
        symbols=symbols,
        repository_commit=repository_commit,
        requested_at_utc=requested_at_utc,
    )

    print(
        f"[PROMOTE] symbols={','.join(symbols)} repository_commit={repository_commit} "
        f"requested_at_utc={requested_at_utc}",
        file=sys.stderr,
        flush=True,
    )

    with _writer_runtime_context():
        rollout_rc = rollout_cli.main(rollout_argv)
    if rollout_rc != 0:
        _emit(
            _result(
                "FAILED",
                reason_code="ROLLOUT_NOT_SUCCESSFUL",
                detail=f"rollout exit code={rollout_rc}",
                symbols=symbols,
                repository_commit=repository_commit,
                chain_invoked=False,
                **_SAFETY_MARKERS,
            )
        )
        return rollout_rc

    print("[PROMOTE] rollout succeeded; running canonical 4h chain", file=sys.stderr, flush=True)
    chain_rc = _run_chain(repository_root)
    if chain_rc != 0:
        _emit(
            _result(
                "FAILED",
                reason_code="CHAIN_NOT_SUCCESSFUL",
                detail=f"chain exit code={chain_rc}",
                symbols=symbols,
                repository_commit=repository_commit,
                chain_invoked=True,
                **_SAFETY_MARKERS,
            )
        )
        return chain_rc

    _emit(
        _result(
            "SUCCESS",
            symbols=symbols,
            repository_commit=repository_commit,
            chain_invoked=True,
            **_SAFETY_MARKERS,
        )
    )
    return 0


def _result(event: str, *, symbols: list[str], **fields: Any) -> dict[str, Any]:
    return {
        "event": event,
        "runner": RUNNER_NAME,
        "runner_version": RUNNER_VERSION,
        "symbols": symbols,
        **fields,
    }


if __name__ == "__main__":
    raise SystemExit(main())
