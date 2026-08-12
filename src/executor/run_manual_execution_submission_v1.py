"""
run_manual_execution_submission_v1 — the smallest explicit operator trigger
for manual SELL ladder broker submission (Issue #369).

CLI/service entrypoint only. No scheduled/automatic invocation, no
dashboard/#254 dependency. Requires explicit human confirmation of the
exact account/venue/market/side/plan/handoff/leg identity immediately
before any LIVE broker call.

Modes:
  --mode dry-run   Exercises the identical orchestrator
                    (src.executor.manual_execution_submission_orchestrator_v1)
                    against the non-live in-memory stub adapter
                    (src.executor.manual_execution_stub_order_adapter_v1).
                    No broker call, no credential decryption, no manual-live
                    authorization required. For operator rehearsal / CI.
  --mode live      Requires: SYNTH_BROKER_WRITE_PERMISSION (existing global
                    gate, enforced inside BitvavoClient), the explicit
                    handoff-scoped manual-live authorization env var
                    (src.executor.manual_live_authorization_v1), and an
                    explicit typed confirmation matching this exact
                    handoff_id. Live trading remains disabled unless every
                    one of these is explicitly set by the operator.

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
    LiveBitvavoOrderAdapter,
    LiveCredentialResolutionDeniedError,
    build_live_bitvavo_client,
)
from src.executor.manual_execution_client_order_id_v1 import derive_client_order_id
from src.executor.manual_execution_handoff_v1 import ExecutorHandoffRepository
from src.executor.manual_execution_operator_identity_v1 import (
    OperatorIdentityNotConfiguredError,
    resolve_operator_id,
)
from src.executor.manual_execution_stub_order_adapter_v1 import StubOrderPlacementAdapter
from src.executor.manual_execution_submission_orchestrator_v1 import (
    extract_plan_legs,
    submit_manual_sell_ladder,
)
from src.executor.manual_live_authorization_v1 import (
    ManualLiveAuthorizationDeniedError,
    require_manual_live_authorization,
)

CONFIRMATION_PROMPT_TEMPLATE = "CONFIRM LIVE SELL handoff_id={handoff_id}"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Explicit operator trigger for manual SELL ladder broker submission."
    )
    parser.add_argument("--handoff-id", type=int, required=True)
    parser.add_argument("--mode", choices=("dry-run", "live"), default="dry-run")
    parser.add_argument("--runtime-owner", required=True, help="Explicit host/service owner, e.g. devlap.")
    parser.add_argument(
        "--assume-yes",
        action="store_true",
        help="Skip the interactive typed confirmation (dry-run only; never accepted for --mode live).",
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

    try:
        operator_id = resolve_operator_id()
    except OperatorIdentityNotConfiguredError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.mode == "dry-run":
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
        )
        _print_result(result)
        return 0 if result.stopped_reason is None else 1

    # --mode live
    try:
        require_manual_live_authorization(handoff_id=handoff.handoff_id)
    except ManualLiveAuthorizationDeniedError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    expected_confirmation = CONFIRMATION_PROMPT_TEMPLATE.format(handoff_id=handoff.handoff_id)
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

    with get_connection() as conn:
        try:
            client = build_live_bitvavo_client(
                conn=conn,
                trading_account_id=handoff.trading_account_id,
                venue=handoff.venue,
                executor_identity=handoff.executor_identity,
                runtime_owner=handoff.runtime_owner,
                master_key_bytes=master_key_bytes,
                cred_repo_factory=CredentialRepository,
            )
        except LiveCredentialResolutionDeniedError as exc:
            print(str(exc), file=sys.stderr)
            return 2

    adapter = LiveBitvavoOrderAdapter(client=client)
    result = submit_manual_sell_ladder(
        handoff=handoff,
        plan_snapshot=plan_snapshot,
        operator_id=operator_id,
        adapter=adapter,
    )
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
