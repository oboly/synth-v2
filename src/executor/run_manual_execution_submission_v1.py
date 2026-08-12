"""
run_manual_execution_submission_v1 — the smallest explicit operator trigger
for manual SELL ladder broker submission (Issue #369).

CLI/service entrypoint only. No scheduled/automatic invocation, no
dashboard/#254 dependency. Requires explicit human confirmation of the
exact account/venue/market/side/plan/handoff/leg identity immediately
before any LIVE broker call or LIVE authority grant.

Actions:
  --mode dry-run             Exercises the identical orchestrator
                              (src.executor.manual_execution_submission_orchestrator_v1)
                              against the non-live in-memory stub adapter
                              AND a purely in-process, never-persisted
                              submission-leg repository
                              (src.executor.manual_execution_submission_leg_inmemory_v1) —
                              this makes ZERO canonical DB writes, so the
                              exact same plan/handoff remains fully eligible
                              for LIVE submission afterwards. No broker
                              call, no credential decryption, no LIVE
                              authority required. For operator rehearsal/CI.
  --grant-live-authority      A separate, deliberate action that persists
                              LIVE authority for this exact handoff
                              (src.executor.manual_execution_live_authority_v1).
                              Never implied by --mode live; must be run
                              first, once, as its own invocation. Exits
                              without submitting anything.
  --mode live                 Requires, in order: persisted LIVE authority
                              (denied if --grant-live-authority was never
                              run for this handoff_id), the handoff-scoped
                              runtime activation env var
                              (src.executor.manual_live_authorization_v1),
                              SYNTH_BROKER_WRITE_PERMISSION (existing global
                              gate enforced inside BitvavoClient), and an
                              explicit typed confirmation. A DRY_RUN/PAPER
                              handoff can never reach the broker merely
                              because env vars are set.

Run:
  python -m src.executor.run_manual_execution_submission_v1 --help
"""
from __future__ import annotations

import argparse
import sys
from decimal import Decimal

from src.account_provisioning.credential_crypto_v1 import load_master_key_from_env
from src.account_provisioning.credential_repository_v1 import CredentialRepository
from src.execution_planner.manual_execution_plan_snapshot_v1 import (
    ManualExecutionPlanSnapshotRepository,
)
from src.executor.manual_execution_bitvavo_order_adapter_v1 import (
    LiveCredentialResolutionDeniedError,
)
from src.executor.manual_execution_client_order_id_v1 import derive_client_order_id
from src.executor.manual_execution_handoff_v1 import ExecutorHandoffRepository
from src.executor.manual_execution_live_authority_v1 import (
    LiveAuthorityConflictError,
    ManualExecutionLiveAuthorityRepository,
)
from src.executor.manual_execution_live_submission_v1 import submit_manual_sell_ladder_live
from src.executor.manual_execution_operator_identity_v1 import (
    OperatorIdentityNotConfiguredError,
    resolve_operator_id,
)
from src.executor.manual_execution_stub_order_adapter_v1 import StubOrderPlacementAdapter
from src.executor.manual_execution_submission_leg_inmemory_v1 import (
    InMemorySubmissionLegRepository,
)
from src.executor.manual_execution_submission_orchestrator_v1 import (
    extract_plan_legs,
    submit_manual_sell_ladder,
)
from src.executor.manual_execution_live_authority_v1 import LiveAuthorityDeniedError
from src.executor.manual_live_authorization_v1 import ManualLiveAuthorizationDeniedError

LIVE_CONFIRMATION_PROMPT_TEMPLATE = "CONFIRM LIVE SELL handoff_id={handoff_id}"
GRANT_CONFIRMATION_PROMPT_TEMPLATE = "GRANT LIVE AUTHORITY handoff_id={handoff_id}"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Explicit operator trigger for manual SELL ladder broker submission."
    )
    parser.add_argument("--handoff-id", type=int, required=True)
    parser.add_argument("--mode", choices=("dry-run", "live"), default="dry-run")
    parser.add_argument("--runtime-owner", required=True, help="Explicit host/service owner, e.g. devlap.")
    parser.add_argument(
        "--grant-live-authority",
        action="store_true",
        help=(
            "Persist LIVE authority for this exact handoff_id and exit "
            "without submitting. Must be run once, separately, before "
            "--mode live can succeed."
        ),
    )
    parser.add_argument(
        "--authorized-by",
        default=None,
        help="Explicit operator identity granting LIVE authority. Required with --grant-live-authority.",
    )
    parser.add_argument(
        "--assume-yes",
        action="store_true",
        help="Skip the interactive typed confirmation (dry-run only; never accepted for live/grant actions).",
    )
    return parser.parse_args(argv)


def _print_confirmation_summary(*, handoff, plan_snapshot) -> None:
    plan_legs = extract_plan_legs(plan_snapshot)
    total_quantity = sum((leg.quantity for leg in plan_legs), Decimal("0"))
    print("=" * 72)
    print("MANUAL SELL LADDER SUBMISSION — CONFIRM BEFORE PROCEEDING")
    print("=" * 72)
    print(f"trading_account_id : {handoff.trading_account_id}")
    print(f"venue              : {handoff.venue}")
    print(f"market             : {handoff.market}")
    print(f"side               : {handoff.side}")
    print(f"plan_snapshot_id   : {handoff.plan_snapshot_id}")
    print(f"handoff_id         : {handoff.handoff_id}")
    print(f"executor_identity  : {handoff.executor_identity}")
    print(f"runtime_owner      : {handoff.runtime_owner}")
    print(f"legs               : {len(plan_legs)}")
    print(f"total_quantity     : {total_quantity}")
    print("-" * 72)
    for leg in plan_legs:
        client_order_id = derive_client_order_id(
            plan_snapshot_id=plan_snapshot.plan_snapshot_id,
            leg_index=leg.leg_index,
            trading_account_id=handoff.trading_account_id,
            venue=handoff.venue,
            market=handoff.market,
        )
        print(
            f"  leg {leg.leg_index}: price={leg.price} quantity={leg.quantity} "
            f"client_order_id={client_order_id}"
        )
    print("=" * 72)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    handoff_repo = ExecutorHandoffRepository()
    handoff = handoff_repo.find_by_id(args.handoff_id)
    if handoff is None:
        print(f"HANDOFF_NOT_FOUND: handoff_id={args.handoff_id}", file=sys.stderr)
        return 2
    if handoff.runtime_owner != args.runtime_owner:
        print(
            "RUNTIME_OWNER_MISMATCH: "
            f"handoff.runtime_owner={handoff.runtime_owner!r} "
            f"--runtime-owner={args.runtime_owner!r}",
            file=sys.stderr,
        )
        return 2

    plan_snapshot_repo = ManualExecutionPlanSnapshotRepository()
    plan_snapshot = plan_snapshot_repo.find_by_id(handoff.plan_snapshot_id)
    if plan_snapshot is None:
        print(f"PLAN_SNAPSHOT_NOT_FOUND: {handoff.plan_snapshot_id}", file=sys.stderr)
        return 2

    _print_confirmation_summary(handoff=handoff, plan_snapshot=plan_snapshot)

    if args.grant_live_authority:
        return _grant_live_authority(handoff=handoff, authorized_by=args.authorized_by)

    try:
        operator_id = resolve_operator_id()
    except OperatorIdentityNotConfiguredError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.mode == "dry-run":
        return _run_dry_run(handoff=handoff, plan_snapshot=plan_snapshot, operator_id=operator_id, args=args)

    return _run_live(handoff=handoff, plan_snapshot=plan_snapshot, operator_id=operator_id)


def _grant_live_authority(*, handoff, authorized_by: str | None) -> int:
    if not authorized_by or not authorized_by.strip():
        print("--authorized-by is required with --grant-live-authority", file=sys.stderr)
        return 2

    expected_confirmation = GRANT_CONFIRMATION_PROMPT_TEMPLATE.format(handoff_id=handoff.handoff_id)
    answer = input(f"Type '{expected_confirmation}' to grant LIVE authority: ").strip()
    if answer != expected_confirmation:
        print("Aborted: grant confirmation phrase did not match exactly.", file=sys.stderr)
        return 1

    authority_repo = ManualExecutionLiveAuthorityRepository()
    try:
        authority = authority_repo.grant(handoff=handoff, authorized_by=authorized_by)
    except LiveAuthorityConflictError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(f"LIVE authority granted: authority_id={authority.authority_id} handoff_id={handoff.handoff_id}")
    print("This invocation did NOT submit anything. Run --mode live separately to submit.")
    return 0


def _run_dry_run(*, handoff, plan_snapshot, operator_id: int, args: argparse.Namespace) -> int:
    if not args.assume_yes:
        answer = input("Type CONFIRM to proceed with dry-run: ").strip()
        if answer != "CONFIRM":
            print("Aborted: confirmation not received.", file=sys.stderr)
            return 1
    adapter = StubOrderPlacementAdapter()
    result = submit_manual_sell_ladder(
        handoff=handoff,
        plan_snapshot=plan_snapshot,
        operator_id=operator_id,
        adapter=adapter,
        submission_leg_repository=InMemorySubmissionLegRepository(),
    )
    _print_result(result)
    print("(dry-run: zero canonical submission-leg rows were created or changed)")
    return 0 if result.stopped_reason is None else 1


def _run_live(*, handoff, plan_snapshot, operator_id: int) -> int:
    try:
        ManualExecutionLiveAuthorityRepository().require_matching(handoff)
    except LiveAuthorityDeniedError as exc:
        print(str(exc), file=sys.stderr)
        print("Run --grant-live-authority first, as its own separate invocation.", file=sys.stderr)
        return 2
    except LiveAuthorityConflictError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    expected_confirmation = LIVE_CONFIRMATION_PROMPT_TEMPLATE.format(handoff_id=handoff.handoff_id)
    answer = input(f"Type '{expected_confirmation}' to proceed with LIVE submission: ").strip()
    if answer != expected_confirmation:
        print("Aborted: LIVE confirmation phrase did not match exactly.", file=sys.stderr)
        return 1

    try:
        master_key_version, master_key_bytes = load_master_key_from_env()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    del master_key_version

    from src.common.db import get_connection

    try:
        with get_connection() as conn:
            result = submit_manual_sell_ladder_live(
                handoff=handoff,
                plan_snapshot=plan_snapshot,
                operator_id=operator_id,
                conn=conn,
                master_key_bytes=master_key_bytes,
                cred_repo_factory=CredentialRepository,
            )
    except (
        LiveAuthorityDeniedError,
        LiveAuthorityConflictError,
        ManualLiveAuthorizationDeniedError,
        LiveCredentialResolutionDeniedError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    _print_result(result)
    return 0 if result.stopped_reason is None else 1


def _print_result(result) -> None:
    print("-" * 72)
    for outcome in result.leg_outcomes:
        print(
            f"  leg {outcome.leg_index}: submission_state={outcome.submission_state} "
            f"broker_order_id={outcome.broker_order_id} safe_error_code={outcome.safe_error_code}"
        )
    print(f"stopped_reason: {result.stopped_reason or 'NONE (all legs accepted)'}")


if __name__ == "__main__":
    raise SystemExit(main())
