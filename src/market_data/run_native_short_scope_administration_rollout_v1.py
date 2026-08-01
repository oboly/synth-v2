from __future__ import annotations

"""Manual market-only Native SHORT multi-symbol rollout orchestration CLI.

Processes the checked-in approved rollout universe
(``native_short_scope_administration_rollout_v1.APPROVED_ROLLOUT_UNIVERSE_V1``),
or an explicit ``--only-symbol`` subset of it, one scope at a time. Every
scope is delegated unchanged to the canonical single-scope transaction owner
(``native_short_scope_administration_transaction_v1``); this CLI creates no
writer, service, timer, or direct SQL mutation path of its own. Defaults to a
read-only plan/dry run. Mutation requires an explicit ``--write`` plus a
verified clean repository source identity and canonical writer mutation
authorization for the ``native_short_4h_chain`` capability, exactly as the
existing single-scope CLI (``run_native_short_scope_administration_v1.py``)
requires.

The rollout stops at the first scope whose result is not
SUCCESS/IDEMPOTENT_SUCCESS (including a ``GLOBAL_BLOCKERS_ACTIVE`` rejection)
or on the first unexpected exception; every remaining symbol is left
untouched and reported as remaining. Each entry's operation UUID is derived
deterministically (see
``native_short_scope_administration_rollout_v1.deterministic_operation_uuid``),
so re-running this CLI with identical arguments after a partial run or crash
is idempotent and safely restartable: already-completed entries replay as
``OPERATION_ALREADY_COMPLETED`` and processing continues from the first
not-yet-attempted entry.

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
from datetime import UTC, datetime
from typing import Any, Sequence

from src.market_data.native_short_scope_administration_v1 import (
    NativeShortScopeAdministrationActorType,
    NativeShortScopeAdministrationRequest,
    NativeShortScopeAdministrationTriggerType,
    NativeShortScopeAdministrationValidationError,
)
from src.market_data.native_short_scope_administration_rollout_v1 import (
    RolloutConfigurationError,
    RolloutOutcome,
    RolloutSymbolEntry,
    build_request_for_entry,
    execute_rollout,
    plan_rollout,
    resolve_rollout_entries,
)
from src.market_data.native_short_repository_source_identity_v1 import (
    NativeShortRepositorySourceIdentityError,
    NativeShortRepositorySourceInspector,
    inspect_running_repository_source,
    verify_repository_commit_sha,
)


RUNNER_NAME = "native_short_scope_administration_rollout_v1"
RUNNER_VERSION = "0.1"
DEFAULT_SCHEMA_VERSION = "native_short_scope_administration_v1"
WRITER_SERVICE = "synth-chain-4h.service"

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
        prog="run_native_short_scope_administration_rollout_v1",
        description=(
            "Manual market-only Native SHORT multi-symbol rollout "
            "orchestration. Defaults to plan/dry-run. Use --write for the "
            "explicit sequential mutation path, one scope at a time, over "
            "the checked-in approved rollout universe."
        ),
    )
    parser.add_argument(
        "--only-symbol",
        action="append",
        default=None,
        help=(
            "Restrict processing to this symbol; repeatable. Must already be "
            "present in the checked-in approved rollout universe -- this "
            "cannot add an unapproved symbol. Omit to process the complete "
            "checked-in universe in order."
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
            "identity/digest: a restart that must replay identically has to "
            "supply the identical value. Defaults to the current UTC time "
            "for a first attempt."
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
        raise NativeShortScopeAdministrationValidationError(
            "REQUESTED_AT_MISSING_TIMEZONE"
        )
    return parsed.astimezone(UTC)


def _parse_metadata(value: str) -> dict[str, Any]:
    try:
        metadata = json.loads(value)
    except json.JSONDecodeError as exc:
        raise NativeShortScopeAdministrationValidationError(
            f"METADATA_NOT_JSON detail={exc}"
        ) from exc
    if not isinstance(metadata, dict):
        raise NativeShortScopeAdministrationValidationError(
            "METADATA_MUST_BE_JSON_OBJECT"
        )
    return metadata


def _emit_progress(args: argparse.Namespace, entries: Sequence[RolloutSymbolEntry]) -> None:
    """Operational progress goes to stderr so stdout carries exactly one JSON
    result document."""
    payload = {
        "event": "STARTED",
        "runner": RUNNER_NAME,
        "runner_version": RUNNER_VERSION,
        "requested_symbols": [entry.symbol for entry in entries],
        "requested_operations": [str(entry.operation_type) for entry in entries],
        "write": bool(args.write),
        "dry_run": not args.write,
        "production_db_writes": 1 if args.write else 0,
        **_SAFETY_MARKERS,
    }
    print(json.dumps(payload, sort_keys=True), file=sys.stderr, flush=True)


def _emit_document(payload: dict[str, Any]) -> None:
    """Emit the single final JSON result document to stdout. Called exactly
    once per invocation on every code path."""
    print(json.dumps(payload, sort_keys=True))
    sys.stdout.flush()


def _result_document(outcome_dict: dict[str, Any]) -> dict[str, Any]:
    completed_writes = sum(
        1
        for c in outcome_dict.get("completed", [])
        if c.get("persisted") is True
    )
    return {
        "event": "RESULT",
        "runner": RUNNER_NAME,
        "runner_version": RUNNER_VERSION,
        "production_db_writes": completed_writes,
        **_SAFETY_MARKERS,
        **outcome_dict,
    }


def _error_document(
    reason_code: str,
    detail: str,
    *,
    write: bool,
) -> dict[str, Any]:
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
        entries = resolve_rollout_entries(args.only_symbol)
    except RolloutConfigurationError as exc:
        _emit_document(_error_document("INVALID_ROLLOUT_SYMBOLS", str(exc), write=write))
        return 2

    try:
        requested_at_utc = _parse_requested_at(args.requested_at_utc)
        metadata = _parse_metadata(args.metadata)
    except NativeShortScopeAdministrationValidationError as exc:
        _emit_document(_error_document("INVALID_REQUEST", str(exc), write=write))
        return 2

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

    _emit_progress(args, entries)

    if not write:
        return _run_dry_run(entries, build_request)

    return _run_write(
        entries,
        build_request,
        repository_sha=args.repository_commit,
        inspect_repository_source=inspect_repository_source,
    )


def _run_dry_run(
    entries: Sequence[RolloutSymbolEntry],
    build_request: Any,
) -> int:
    from src.common.db import get_connection

    conn = None
    try:
        conn = get_connection()
        outcome = plan_rollout(conn, entries, build_request=build_request)
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

    # Verify the exact clean repository source identity once for the whole
    # batch: every entry in one invocation runs from the same checked-out
    # commit; the canonical writer independently re-verifies this again
    # immediately before its own DB access, exactly as the single-scope CLI's
    # underlying transaction path already does.
    try:
        verify_repository_commit_sha(
            repository_sha, inspect_repository_source=inspect_repository_source
        )
    except NativeShortRepositorySourceIdentityError as exc:
        _emit_document(
            _error_document("INVALID_REPOSITORY_SOURCE", str(exc), write=True)
        )
        return 2

    # Require canonical writer mutation authorization once for the whole
    # batch, reused unchanged for every scope's execute_scope_administration
    # call -- this orchestrator never bypasses or duplicates authorization.
    try:
        authorization = enforce_capability_write_authorization(
            WRITER_CAPABILITY_ID, service=WRITER_SERVICE
        )
    except AuthorizationDenied as exc:
        _emit_document(
            _error_document("WRITER_AUTHORIZATION_DENIED", str(exc), write=True)
        )
        return 3

    conn = None
    try:
        conn = get_connection()
        outcome = execute_rollout(
            conn, entries, build_request=build_request, authorization=authorization
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
