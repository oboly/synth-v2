from __future__ import annotations

"""Manual market-only Native SHORT single-scope administration CLI.

Runs exactly one administration operation (ADOPT_LEGACY_SCOPE, PROMOTE_SCOPE, or
REMOVE_SCOPE) against exactly one canonical scope. Defaults to a read-only dry
run. Mutation requires an explicit ``--write`` plus a verified clean repository
source identity and canonical writer mutation authorization for the
``native_short_4h_chain`` capability.

Boundary: market-only, account-agnostic, exact-one-scope. No broker, order,
selection, decision-gate, execution-planner, executor, or reporting mutation. No
runtime or timer is activated by this CLI.

Safety markers:
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
"""

import argparse
import json
import sys
import threading
import time
from datetime import UTC, datetime
from typing import Any

from src.market_data.native_short_multi_asset_audit_v1 import run_audit
from src.market_data.native_short_rollout_universe_v2 import (
    is_symbol_promote_scope_ready,
)
from src.market_data.native_short_scope_administration_v1 import (
    NativeShortScopeAdministrationActorType,
    NativeShortScopeAdministrationKey,
    NativeShortScopeAdministrationOperationType,
    NativeShortScopeAdministrationProvenance,
    NativeShortScopeAdministrationRequest,
    NativeShortScopeAdministrationTriggerType,
    NativeShortScopeAdministrationValidationError,
)
from src.market_data.native_short_scope_administration_transaction_v1 import (
    WRITER_CAPABILITY_ID,
    execute_scope_administration,
    plan_scope_administration,
)
from src.market_data.native_short_repository_source_identity_v1 import (
    NativeShortRepositorySourceIdentityError,
    NativeShortRepositorySourceInspector,
    inspect_running_repository_source,
    verify_repository_commit_sha,
)


RUNNER_NAME = "native_short_scope_administration_v1"
RUNNER_VERSION = "0.1"
DEFAULT_SCHEMA_VERSION = "native_short_scope_administration_v1"
WRITER_SERVICE = "synth-chain-4h.service"

DEFAULT_VENUE = "bitvavo"
DEFAULT_QUOTE_CURRENCY = "EUR"
DEFAULT_FIB_TRADING_HORIZON = "SHORT"
DEFAULT_PRIMARY_INTERVAL = "4h"
DEFAULT_SUPPORTING_INTERVAL = "1h"

# CLI-selectable provenance values. TEST actor/trigger are intentionally not
# selectable from this production CLI.
_ACTOR_CHOICES = (
    NativeShortScopeAdministrationActorType.HUMAN_OPERATOR.value,
    NativeShortScopeAdministrationActorType.SERVICE_PRINCIPAL.value,
)
_TRIGGER_CHOICES = (
    NativeShortScopeAdministrationTriggerType.MANUAL_CLI.value,
    NativeShortScopeAdministrationTriggerType.AUTOMATION.value,
)
_OPERATION_CHOICES = tuple(
    item.value for item in NativeShortScopeAdministrationOperationType
)

_SAFETY_MARKERS = {
    "broker_private_calls": 0,
    "broker_writes": 0,
    "order_submission": 0,
    "live_orders": 0,
    "decision_gate": "none",
    "execution_planner": "none",
    "executor": "none",
    "systemd_changes": 0,
    "timer_changes": 0,
    "runtime_activation": 0,
    "host_mutations": 0,
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="run_native_short_scope_administration_v1",
        description=(
            "Manual market-only Native SHORT single-scope administration. "
            "Defaults to dry-run. Use --write for the explicit mutation path "
            "against exactly one canonical scope."
        ),
    )
    parser.add_argument(
        "--symbol",
        required=True,
        help="Exactly one canonical base symbol (e.g. BTC). Lists/wildcards rejected.",
    )
    parser.add_argument("--operation", required=True, choices=_OPERATION_CHOICES)
    parser.add_argument("--venue", choices=(DEFAULT_VENUE,), default=DEFAULT_VENUE)
    parser.add_argument(
        "--quote-currency",
        choices=(DEFAULT_QUOTE_CURRENCY,),
        default=DEFAULT_QUOTE_CURRENCY,
    )
    parser.add_argument("--actor-type", required=True, choices=_ACTOR_CHOICES)
    parser.add_argument("--actor-id", required=True)
    parser.add_argument("--trigger-type", required=True, choices=_TRIGGER_CHOICES)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--operation-uuid", required=True)
    parser.add_argument("--request-source", required=True)
    parser.add_argument("--repository-commit", required=True)
    parser.add_argument(
        "--trigger-ref",
        required=True,
        help="Explicit reviewed trigger reference metadata.",
    )
    parser.add_argument("--schema-version", default=DEFAULT_SCHEMA_VERSION)
    parser.add_argument(
        "--requested-at-utc",
        default=None,
        help=(
            "Explicit request timestamp in canonical UTC ISO-8601 "
            "(e.g. 2026-07-18T10:00:00Z). Part of the immutable request "
            "identity/digest: a retry must supply the identical value. "
            "Defaults to the current UTC time for a first attempt."
        ),
    )
    parser.add_argument(
        "--metadata",
        default="{}",
        help="Canonical immutable request metadata as a JSON object.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Perform the explicit single-scope mutation transaction.",
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
        raise NativeShortScopeAdministrationValidationError(
            "REQUESTED_AT_MISSING_TIMEZONE"
        )
    return parsed.astimezone(UTC)


def build_request(args: argparse.Namespace) -> NativeShortScopeAdministrationRequest:
    try:
        metadata = json.loads(args.metadata)
    except json.JSONDecodeError as exc:
        raise NativeShortScopeAdministrationValidationError(
            f"METADATA_NOT_JSON detail={exc}"
        ) from exc
    if not isinstance(metadata, dict):
        raise NativeShortScopeAdministrationValidationError(
            "METADATA_MUST_BE_JSON_OBJECT"
        )

    requested_at_utc = _parse_requested_at(args.requested_at_utc)

    scope_key = NativeShortScopeAdministrationKey(
        venue=args.venue,
        symbol=args.symbol,
        quote_currency=args.quote_currency,
        fib_trading_horizon=DEFAULT_FIB_TRADING_HORIZON,
        primary_interval=DEFAULT_PRIMARY_INTERVAL,
        supporting_interval=DEFAULT_SUPPORTING_INTERVAL,
    )
    provenance = NativeShortScopeAdministrationProvenance(
        operation_uuid=args.operation_uuid,
        actor_type=args.actor_type,
        actor_id=args.actor_id,
        trigger_type=args.trigger_type,
        request_source=args.request_source,
        reason=args.reason,
        requested_at_utc=requested_at_utc,
        repository_sha=args.repository_commit,
        schema_version=args.schema_version,
    )
    return NativeShortScopeAdministrationRequest(
        operation_type=args.operation,
        scope_key=scope_key,
        provenance=provenance,
        canonical_metadata=metadata,
    )


def _emit_stderr_json(payload: dict[str, Any]) -> None:
    """Operational progress goes to stderr, one JSON document per line, so
    stdout carries exactly one JSON result document."""
    print(json.dumps(payload, sort_keys=True), file=sys.stderr, flush=True)


def _emit_progress(args: argparse.Namespace) -> None:
    _emit_stderr_json(
        {
            "event": "STARTED",
            "runner": RUNNER_NAME,
            "runner_version": RUNNER_VERSION,
            "operation": args.operation,
            "symbol": args.symbol.strip().upper(),
            "venue": args.venue,
            "quote_currency": args.quote_currency,
            "write": bool(args.write),
            "dry_run": not args.write,
            "production_db_writes": 1 if args.write else 0,
            **_SAFETY_MARKERS,
        }
    )


def _emit_document(payload: dict[str, Any]) -> None:
    """Emit the single final JSON result document to stdout. Called exactly once
    per invocation on every code path."""
    print(json.dumps(payload, sort_keys=True))
    sys.stdout.flush()


def _result_document(outcome_dict: dict[str, Any]) -> dict[str, Any]:
    return {
        "event": "RESULT",
        "runner": RUNNER_NAME,
        "runner_version": RUNNER_VERSION,
        "production_db_writes": 1 if outcome_dict.get("persisted") else 0,
        **_SAFETY_MARKERS,
        **outcome_dict,
    }


def _error_document(
    reason_code: str,
    detail: str,
    *,
    write: bool,
    commit_state: str = "NOT_ATTEMPTED",
    persisted: bool | None = False,
) -> dict[str, Any]:
    return {
        "event": "FAILED",
        "runner": RUNNER_NAME,
        "runner_version": RUNNER_VERSION,
        "write": write,
        "persisted": persisted,
        "commit_state": commit_state,
        "production_db_writes": 0,
        "reason_code": reason_code,
        "detail": detail,
        **_SAFETY_MARKERS,
    }


def main(
    argv: list[str] | None = None,
    *,
    inspect_repository_source: NativeShortRepositorySourceInspector = (
        inspect_running_repository_source
    ),
) -> int:
    args = parse_args(argv)
    write = bool(args.write)

    try:
        request = build_request(args)
    except NativeShortScopeAdministrationValidationError as exc:
        _emit_document(_error_document("INVALID_REQUEST", str(exc), write=write))
        return 2

    # STARTED before the guard's own (potentially several-second) readiness
    # audit call: a runner must announce it has begun before any phase that
    # can take longer than a few seconds, not only before the mutation.
    _emit_progress(args)

    if args.operation == NativeShortScopeAdministrationOperationType.PROMOTE_SCOPE.value:
        guard_result = _enforce_promote_scope_readiness_guard(args.symbol, write=write)
        if guard_result is not None:
            return guard_result

    if not write:
        return _run_dry_run(request)

    return _run_write(request, inspect_repository_source=inspect_repository_source)


_GUARD_HEARTBEAT_SECONDS = 15.0


class _GuardHeartbeat:
    """Periodic stderr heartbeat while the PROMOTE_SCOPE readiness guard's
    audit call runs. Mirrors ``run_native_short_multi_asset_audit_v1.Heartbeat``
    -- an independent, ~15-line duplicate rather than a shared import,
    consistent with this codebase's existing preference for small
    independent helpers over cross-module coupling for unrelated CLIs."""

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
        while not self._stop.wait(_GUARD_HEARTBEAT_SECONDS):
            _emit_stderr_json(
                {
                    "event": "HEARTBEAT",
                    "runner": RUNNER_NAME,
                    "phase": "promote_scope_readiness_guard",
                    "elapsed_s": round(time.monotonic() - self.started, 1),
                }
            )


def _load_bulk_rollout_report(conn: Any, *, as_of_utc: datetime) -> Any:
    """Thin, monkeypatchable seam around ``run_audit`` for the ``PROMOTE_SCOPE``
    readiness guard below. Exists so tests can substitute a canned
    ``AuditReport`` without needing a fake connection that also implements
    ``run_audit``'s complete multi-table canonical-market query surface (the
    existing CLI test fakes are deliberately shaped only for
    ``execute_scope_administration``/``plan_scope_administration``)."""
    with conn.cursor() as cur:
        cur.execute("SET TRANSACTION READ ONLY")
    return run_audit(conn, as_of_utc=as_of_utc)


def _enforce_promote_scope_readiness_guard(symbol: str, *, write: bool) -> int | None:
    """Single-scope/bulk-rollout readiness parity guard for ``PROMOTE_SCOPE``
    (Issue #276 v2). Before #276 v2, this CLI accepted an arbitrary
    ``--symbol`` for ``PROMOTE_SCOPE`` with no readiness check at all -- the
    approved-universe check lived only inside the batch orchestrator's
    ``resolve_rollout_entries``, so a direct single-scope CLI invocation was
    an unguarded bypass of it. This applies the identical, unchanged
    ``native_short_rollout_universe_v2`` readiness definition a bulk run
    would apply, so a single-scope ``PROMOTE_SCOPE`` and a bulk-rollout
    ``PROMOTE_SCOPE`` for the same symbol always agree.

    Read-only: runs the same audit a bulk run would, decides nothing about
    mutation itself. Returns ``None`` to proceed, or the process exit code to
    return immediately (guard failed or could not be evaluated -- fail
    closed either way).
    """
    from src.common.db import get_connection

    guard_started = time.monotonic()
    heartbeat = _GuardHeartbeat()
    heartbeat.start()
    conn = None
    try:
        conn = get_connection()
        report = _load_bulk_rollout_report(conn, as_of_utc=datetime.now(UTC))
    except Exception as exc:  # noqa: BLE001 - fail closed: guard failure blocks the operation.
        _emit_document(
            _error_document(
                "PROMOTE_SCOPE_READINESS_GUARD_FAILED", f"{type(exc).__name__}: {exc}", write=write
            )
        )
        return 1
    finally:
        heartbeat.stop()
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
            conn.close()
    _emit_stderr_json(
        {
            "event": "PHASE_FINISHED",
            "runner": RUNNER_NAME,
            "phase": "promote_scope_readiness_guard",
            "elapsed_s": round(time.monotonic() - guard_started, 3),
        }
    )

    eligible, reason = is_symbol_promote_scope_ready(report, symbol)
    if not eligible:
        _emit_document(
            _error_document("SYMBOL_NOT_PROMOTE_SCOPE_READY", reason, write=write)
        )
        return 2
    return None


def _run_dry_run(request: NativeShortScopeAdministrationRequest) -> int:
    from src.common.db import get_connection

    conn = None
    try:
        conn = get_connection()
        outcome = plan_scope_administration(conn, request)
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
    return 0 if _is_success(outcome) else 1


def _run_write(
    request: NativeShortScopeAdministrationRequest,
    *,
    inspect_repository_source: NativeShortRepositorySourceInspector,
) -> int:
    from src.common.db import get_connection
    from src.operations.writer_capability_authorization_v1 import (
        AuthorizationDenied,
        enforce_capability_write_authorization,
    )

    # Verify the exact clean repository source identity before any mutation.
    try:
        verify_repository_commit_sha(
            request.provenance.repository_sha,
            inspect_repository_source=inspect_repository_source,
        )
    except NativeShortRepositorySourceIdentityError as exc:
        _emit_document(
            _error_document("INVALID_REPOSITORY_SOURCE", str(exc), write=True)
        )
        return 2

    # Require canonical writer mutation authorization without emitting any
    # uncontrolled non-JSON stdout: a denial becomes exactly one JSON document.
    try:
        authorization = enforce_capability_write_authorization(
            WRITER_CAPABILITY_ID, service=WRITER_SERVICE
        )
    except AuthorizationDenied as exc:
        _emit_document(
            _error_document("WRITER_AUTHORIZATION_DENIED", str(exc), write=True)
        )
        return 3

    from src.market_data.native_short_scope_administration_transaction_v1 import (
        NativeShortScopeAdministrationExecutionError,
    )

    conn = None
    try:
        conn = get_connection()
        # Immediately-before-transaction revalidation (Issue #276 v2 TOCTOU
        # fix): the upfront guard in main() ran its own audit on its own
        # connection, then closed it -- by the time this write transaction
        # actually opens, that snapshot may be stale, and
        # execute_scope_administration never checks market readiness itself
        # (only ledger state). Mirrors the bulk CLI's own per-entry
        # revalidate hook: one more fresh, single-symbol check on the exact
        # connection this write is about to use, fail closed.
        if request.operation_type == NativeShortScopeAdministrationOperationType.PROMOTE_SCOPE.value:
            report = _load_bulk_rollout_report(conn, as_of_utc=datetime.now(UTC))
            still_eligible, reason = is_symbol_promote_scope_ready(report, request.scope_key.symbol)
            if not still_eligible:
                _emit_document(
                    _error_document("SYMBOL_NOT_PROMOTE_SCOPE_READY", reason, write=True)
                )
                return 2
        outcome = execute_scope_administration(
            conn, request, authorization=authorization
        )
    except NativeShortScopeAdministrationExecutionError as exc:
        # Confirmed pre-commit rollback of an unexpected defect: report the
        # authoritative commit_state without hiding the defect (str carries it).
        _emit_document(
            _error_document(
                exc.reason_code,
                exc.detail,
                write=True,
                commit_state=str(exc.commit_state),
                persisted=exc.persisted,
            )
        )
        return 1
    except Exception as exc:  # noqa: BLE001 - surface as fail-closed result.
        _emit_document(_error_document(type(exc).__name__, str(exc), write=True))
        return 1
    finally:
        if conn is not None:
            conn.close()

    _emit_document(_result_document(outcome.as_json_dict()))
    return 0 if _is_success(outcome) else 1


def _is_success(outcome: Any) -> bool:
    result_class = str(outcome.result.result_class)
    return result_class in ("SUCCESS", "IDEMPOTENT_SUCCESS")


if __name__ == "__main__":
    raise SystemExit(main())
