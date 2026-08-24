from __future__ import annotations

"""Manual market-only Native SHORT deterministic bulk-rollout CLI (v2).

Processes every scope the current, fresh
``native_short_multi_asset_audit_v1.run_audit`` classifies ready for a first
``PROMOTE_SCOPE`` (``native_short_rollout_universe_v2.ready_symbols``) --
derived fresh from readiness on every invocation, not a checked-in
per-symbol list and not a separate approval concept. Every scope is
delegated unchanged to the same canonical rollout orchestrator
already used by ``run_native_short_scope_administration_rollout_v1.py``
(``native_short_scope_administration_rollout_v1.plan_rollout`` /
``execute_rollout``), which delegates each scope unchanged to
``native_short_scope_administration_transaction_v1`` -- the sole canonical
transaction owner. This CLI creates no writer, service, timer, new promotion
primitive, or direct SQL mutation path of its own; it only changes where the
entry list comes from.

Defaults to a read-only plan/dry run. Mutation requires an explicit
``--write`` plus a verified clean repository source identity and canonical
writer mutation authorization for the ``native_short_4h_chain`` capability,
exactly as both existing administration CLIs require.

Per-scope isolation (Issue #276, unchanged): every entry is always attempted
regardless of any other entry's rejection or crash, via the same
``execute_rollout``/``plan_rollout`` this CLI reuses. Idempotent rerun:
each entry's operation UUID is still derived deterministically from only
``(operation_type, scope_key)``, so a repeated run replays already-completed
entries as ``IDEMPOTENT_SUCCESS``.

Boundary: market-only, account-agnostic. No broker, order, selection,
decision-gate, execution-planner, executor, or reporting mutation. No map,
snapshot, or Profit Plan materialization. No runtime or timer is activated by
this CLI.

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

import argparse
import json
import sys
import threading
import time
from datetime import UTC, datetime
from typing import Any, Sequence

from src.market_data.native_short_multi_asset_audit_v1 import run_audit
from src.market_data.native_short_rollout_universe_v2 import (
    derive_bulk_rollout_entries,
    is_symbol_promote_scope_ready,
)
from src.market_data.native_short_scope_administration_v1 import (
    NativeShortScopeAdministrationActorType,
    NativeShortScopeAdministrationRequest,
    NativeShortScopeAdministrationTriggerType,
    NativeShortScopeAdministrationValidationError,
)
from src.market_data.native_short_scope_administration_rollout_v1 import (
    RolloutOutcome,
    RolloutSymbolEntry,
    build_request_for_entry,
    execute_rollout,
    plan_rollout,
)
from src.market_data.native_short_repository_source_identity_v1 import (
    NativeShortRepositorySourceIdentityError,
    NativeShortRepositorySourceInspector,
    inspect_running_repository_source,
    verify_repository_commit_sha,
)


RUNNER_NAME = "native_short_bulk_rollout_v2"
RUNNER_VERSION = "0.1"
DEFAULT_SCHEMA_VERSION = "native_short_scope_administration_v1"
WRITER_SERVICE = "synth-chain-4h.service"
HEARTBEAT_SECONDS = 15.0

_ACTOR_CHOICES = (
    NativeShortScopeAdministrationActorType.HUMAN_OPERATOR.value,
    NativeShortScopeAdministrationActorType.SERVICE_PRINCIPAL.value,
)
_TRIGGER_CHOICES = (
    NativeShortScopeAdministrationTriggerType.MANUAL_CLI.value,
    NativeShortScopeAdministrationTriggerType.AUTOMATION.value,
)

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
    "systemd_changes": 0,
    "timer_changes": 0,
    "runtime_activation": 0,
    "host_mutations": 0,
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="run_native_short_bulk_rollout_v2",
        description=(
            "Deterministic market-only Native SHORT bulk rollout: processes "
            "every scope the current audit classifies READY. Defaults to "
            "plan/dry-run. Use --write for the explicit mutation path."
        ),
    )
    parser.add_argument("--actor-type", required=True, choices=_ACTOR_CHOICES)
    parser.add_argument("--actor-id", required=True)
    parser.add_argument("--trigger-type", required=True, choices=_TRIGGER_CHOICES)
    parser.add_argument(
        "--reason",
        required=True,
        help="Explicit reviewed reason applied to every scope in this rollout run.",
    )
    parser.add_argument("--request-source", required=True)
    parser.add_argument("--repository-commit", required=True)
    parser.add_argument("--schema-version", default=DEFAULT_SCHEMA_VERSION)
    parser.add_argument(
        "--requested-at-utc",
        default=None,
        help=(
            "Explicit request timestamp in canonical UTC ISO-8601 "
            "(e.g. 2026-07-18T10:00:00Z), shared by every scope in this "
            "rollout run. Part of each entry's immutable request "
            "identity/digest. Defaults to the current UTC time."
        ),
    )
    parser.add_argument(
        "--metadata",
        default="{}",
        help="Canonical immutable request metadata as a JSON object, shared by every scope.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Perform the explicit sequential mutation path.",
    )
    return parser.parse_args(argv)


def _parse_requested_at(value: str | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise NativeShortScopeAdministrationValidationError(
            f"REQUESTED_AT_NOT_ISO_UTC value={value}"
        ) from exc
    if parsed.tzinfo is None:
        raise NativeShortScopeAdministrationValidationError("REQUESTED_AT_MISSING_TIMEZONE")
    return parsed.astimezone(UTC)


def _parse_metadata(value: str) -> dict[str, Any]:
    try:
        metadata = json.loads(value)
    except json.JSONDecodeError as exc:
        raise NativeShortScopeAdministrationValidationError(
            f"METADATA_NOT_JSON detail={exc}"
        ) from exc
    if not isinstance(metadata, dict):
        raise NativeShortScopeAdministrationValidationError("METADATA_MUST_BE_JSON_OBJECT")
    return metadata


def _emit_stderr_json(payload: dict[str, Any]) -> None:
    """Operational progress goes to stderr, one JSON document per line, so
    stdout carries exactly one JSON result document."""
    print(json.dumps(payload, sort_keys=True), file=sys.stderr, flush=True)


class _Heartbeat:
    """Periodic stderr heartbeat while the readiness audit runs. Mirrors
    ``run_native_short_multi_asset_audit_v1.Heartbeat`` -- an independent,
    ~15-line duplicate rather than a shared import, consistent with this
    codebase's existing preference for small independent helpers over
    cross-module coupling for unrelated CLIs."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self.started = time.monotonic()

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)

    def _run(self) -> None:
        while not self._stop.wait(HEARTBEAT_SECONDS):
            _emit_stderr_json(
                {
                    "event": "HEARTBEAT",
                    "runner": RUNNER_NAME,
                    "phase": "audit",
                    "elapsed_s": round(time.monotonic() - self.started, 1),
                }
            )


def _audit_progress(phase: str, rows: int, elapsed_s: float) -> None:
    _emit_stderr_json(
        {
            "event": "PHASE_FINISHED",
            "runner": RUNNER_NAME,
            "phase": phase,
            "rows": rows,
            "elapsed_s": round(elapsed_s, 3),
        }
    )


def _emit_started(args: argparse.Namespace) -> None:
    _emit_stderr_json(
        {
            "event": "STARTED",
            "runner": RUNNER_NAME,
            "runner_version": RUNNER_VERSION,
            "phase": "audit",
            "write": bool(args.write),
            "dry_run": not args.write,
            "production_db_writes": 1 if args.write else 0,
            **_SAFETY_MARKERS,
        }
    )


def _emit_audit_finished(entries: Sequence[RolloutSymbolEntry], *, elapsed_s: float) -> None:
    _emit_stderr_json(
        {
            "event": "AUDIT_FINISHED",
            "runner": RUNNER_NAME,
            "runner_version": RUNNER_VERSION,
            "ready_scope_source": "native_short_rollout_universe_v2.ready_symbols",
            "ready_scope_count": len(entries),
            "requested_symbols": [entry.symbol for entry in entries],
            "elapsed_s": round(elapsed_s, 3),
            **_SAFETY_MARKERS,
        }
    )


def _emit_finished(*, elapsed_s: float, exit_code: int) -> None:
    _emit_stderr_json(
        {"event": "FINISHED", "runner": RUNNER_NAME, "elapsed_s": round(elapsed_s, 3), "exit_code": exit_code}
    )


def _emit_interrupted(*, elapsed_s: float) -> None:
    _emit_stderr_json(
        {"event": "INTERRUPTED", "runner": RUNNER_NAME, "elapsed_s": round(elapsed_s, 3)}
    )


def _emit_document(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True))
    sys.stdout.flush()


def _result_document(outcome_dict: dict[str, Any]) -> dict[str, Any]:
    completed_writes = sum(
        1 for c in outcome_dict.get("completed", []) if c.get("persisted") is True
    )
    return {
        "event": "RESULT",
        "runner": RUNNER_NAME,
        "runner_version": RUNNER_VERSION,
        "production_db_writes": completed_writes,
        **_SAFETY_MARKERS,
        **outcome_dict,
    }


def _error_document(reason_code: str, detail: str, *, write: bool) -> dict[str, Any]:
    return {
        "event": "FAILED",
        "runner": RUNNER_NAME,
        "runner_version": RUNNER_VERSION,
        "write": write,
        "production_db_writes": 0,
        "reason_code": reason_code,
        "detail": detail,
        **_SAFETY_MARKERS,
    }


def _load_report(conn: Any, *, as_of_utc: datetime) -> Any:
    """Thin, monkeypatchable seam around ``run_audit``. Exists so tests can
    substitute a canned ``AuditReport`` without needing a fake connection
    that also implements ``run_audit``'s complete multi-table
    canonical-market query surface (mirrors
    ``run_native_short_scope_administration_v1._load_bulk_rollout_report``)."""
    with conn.cursor() as cur:
        cur.execute("SET TRANSACTION READ ONLY")
    return run_audit(conn, as_of_utc=as_of_utc, progress=_audit_progress)


def main(
    argv: list[str] | None = None,
    *,
    inspect_repository_source: NativeShortRepositorySourceInspector = (
        inspect_running_repository_source
    ),
) -> int:
    from src.common.db import get_connection

    args = parse_args(argv)
    write = bool(args.write)

    try:
        requested_at_utc = _parse_requested_at(args.requested_at_utc)
        metadata = _parse_metadata(args.metadata)
    except NativeShortScopeAdministrationValidationError as exc:
        _emit_document(_error_document("INVALID_REQUEST", str(exc), write=write))
        return 2

    started = time.monotonic()
    _emit_started(args)

    try:
        # Fresh, read-only readiness audit: the set of scopes this run
        # processes is re-derived from current market/ledger state every
        # invocation, never a frozen repository list. This is the
        # potentially long phase (the full canonical Bitvavo EUR market
        # universe), so it gets its own heartbeat and phase-finished events,
        # matching run_native_short_multi_asset_audit_v1's own runner.
        heartbeat = _Heartbeat()
        heartbeat.start()
        conn = None
        try:
            conn = get_connection()
            report = _load_report(conn, as_of_utc=datetime.now(UTC))
        except Exception as exc:  # noqa: BLE001 - surface as fail-closed result.
            _emit_document(
                _error_document("AUDIT_FAILED", f"{type(exc).__name__}: {exc}", write=write)
            )
            _emit_finished(elapsed_s=time.monotonic() - started, exit_code=1)
            return 1
        finally:
            heartbeat.stop()
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass
                conn.close()

        entries = derive_bulk_rollout_entries(report)
        _emit_audit_finished(entries, elapsed_s=time.monotonic() - started)

        def build_request(entry: RolloutSymbolEntry) -> NativeShortScopeAdministrationRequest:
            return build_request_for_entry(
                entry,
                actor_type=args.actor_type,
                actor_id=args.actor_id,
                trigger_type=args.trigger_type,
                request_source=args.request_source,
                reason=args.reason,
                requested_at_utc=requested_at_utc,
                repository_sha=args.repository_commit,
                schema_version=args.schema_version,
                metadata=metadata,
            )

        if not entries:
            _emit_document(
                _result_document(
                    {
                        "mode": "DRY_RUN" if not write else "WRITE",
                        "requested_symbols": [],
                        "completed": [],
                        "completed_symbols": [],
                        "remaining_symbols": [],
                        "stopped_early": False,
                        "stop_reason": None,
                        "all_succeeded": True,
                    }
                )
            )
            _emit_finished(elapsed_s=time.monotonic() - started, exit_code=0)
            return 0

        if not write:
            exit_code = _run_dry_run(entries, build_request)
        else:
            exit_code = _run_write(
                entries,
                build_request,
                repository_sha=args.repository_commit,
                inspect_repository_source=inspect_repository_source,
            )
        _emit_finished(elapsed_s=time.monotonic() - started, exit_code=exit_code)
        return exit_code
    except KeyboardInterrupt:
        _emit_interrupted(elapsed_s=time.monotonic() - started)
        return 130


def _make_revalidate(conn: Any) -> Any:
    """Immediately-before-transaction revalidation for one rollout run.

    The upfront audit that produced ``entries`` is one snapshot, taken once
    before this run's loop starts. ``execute_scope_administration`` always
    reads *ledger* state fresh at call time, but it never checks market
    readiness (candle freshness, tick rules, market eligibility) at all --
    that determination is entirely the audit's. For a long-running,
    many-entry rollout, a scope's market eligibility can change between the
    initial snapshot and this entry's actual turn, so it must be re-checked
    here, on the same connection, immediately before that entry's own
    transaction -- a cheap, single-symbol ``run_audit`` call (~0.1-0.2s),
    not the full canonical-market audit repeated per entry."""

    def _revalidate(entry: RolloutSymbolEntry) -> tuple[bool, str]:
        # No SET TRANSACTION READ ONLY here: on the write path this shares
        # the connection with each entry's own write transaction, and this
        # call only ever issues SELECTs -- forcing a read-only mode on the
        # session here risks leaking into the very next entry's
        # PROMOTE_SCOPE transaction on the same connection.
        try:
            report = run_audit(conn, as_of_utc=datetime.now(UTC), symbols=(entry.symbol,))
        except Exception as exc:  # noqa: BLE001 - fail closed: unrevalidatable blocks this entry.
            return False, f"REVALIDATION_ERROR: {type(exc).__name__}: {exc}"
        return is_symbol_promote_scope_ready(report, entry.symbol)

    return _revalidate


def _run_dry_run(entries: Sequence[RolloutSymbolEntry], build_request: Any) -> int:
    from src.common.db import get_connection

    conn = None
    try:
        conn = get_connection()
        outcome = plan_rollout(
            conn, entries, build_request=build_request, revalidate=_make_revalidate(conn)
        )
    except Exception as exc:  # noqa: BLE001 - surface as fail-closed result.
        _emit_document(_error_document(type(exc).__name__, str(exc), write=False))
        return 1
    finally:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
            conn.close()

    _emit_document(_result_document(outcome.as_json_dict()))
    return 0 if _rollout_succeeded(outcome) else 1


def _run_write(
    entries: Sequence[RolloutSymbolEntry],
    build_request: Any,
    *,
    repository_sha: str,
    inspect_repository_source: NativeShortRepositorySourceInspector,
) -> int:
    from src.common.db import get_connection
    from src.operations.writer_capability_authorization_v1 import (
        AuthorizationDenied,
        enforce_capability_write_authorization,
    )
    from src.market_data.native_short_scope_administration_transaction_v1 import (
        WRITER_CAPABILITY_ID,
    )

    try:
        verify_repository_commit_sha(
            repository_sha, inspect_repository_source=inspect_repository_source
        )
    except NativeShortRepositorySourceIdentityError as exc:
        _emit_document(_error_document("INVALID_REPOSITORY_SOURCE", str(exc), write=True))
        return 2

    try:
        authorization = enforce_capability_write_authorization(
            WRITER_CAPABILITY_ID, service=WRITER_SERVICE
        )
    except AuthorizationDenied as exc:
        _emit_document(_error_document("WRITER_AUTHORIZATION_DENIED", str(exc), write=True))
        return 3

    conn = None
    try:
        conn = get_connection()
        outcome = execute_rollout(
            conn,
            entries,
            build_request=build_request,
            authorization=authorization,
            revalidate=_make_revalidate(conn),
        )
    except Exception as exc:  # noqa: BLE001 - surface as fail-closed result.
        _emit_document(_error_document(type(exc).__name__, str(exc), write=True))
        return 1
    finally:
        if conn is not None:
            conn.close()

    _emit_document(_result_document(outcome.as_json_dict()))
    return 0 if _rollout_succeeded(outcome) else 1


def _rollout_succeeded(outcome: RolloutOutcome) -> bool:
    return bool(outcome.as_json_dict()["all_succeeded"])


if __name__ == "__main__":
    raise SystemExit(main())
