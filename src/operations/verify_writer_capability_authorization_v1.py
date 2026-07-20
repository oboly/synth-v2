"""
verify_writer_capability_authorization_v1

Thin CLI adapter over the shared writer-capability authorization library
(``src.operations.writer_capability_authorization_v1``). It is the systemd
``ExecStartPre`` guard and the wrapper-level early check. It proves that a
committed service is starting only on the explicitly authorized host, at the
exact authorized checkout commit and clean tracked working tree, for a
capability whose registry lifecycle permits runtime execution.

Systemd, shell wrappers, and Python write entrypoints all use the same shared
semantics; this module adds no divergent authorization logic. Absence of the
deployment authorization file, a schema-invalid registry/authorization, or a
dirty/mismatched checkout all fail closed.

host_mutations=0 database_writes=0 writer_invocations=0 systemctl_mutations=0
broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0
decision_gate=none execution_planner=none executor=none
"""
from __future__ import annotations

import argparse
import platform
from pathlib import Path

from src.operations.writer_capability_authorization_v1 import (
    DEFAULT_AUTHORIZATION_FILE,
    REPO_RELATIVE_REGISTRY,
    AuthorizationDecision,
    ExecutionMode,
    verify_writer_execution_authorization,
)


def _allowed_untracked(values: list[str] | None) -> set[str]:
    return {value.strip() for value in (values or []) if value.strip()}


def run_guard(args: argparse.Namespace) -> AuthorizationDecision:
    repo_root = args.repo_root or args.checkout_path
    return verify_writer_execution_authorization(
        capability_id=args.capability,
        mode=args.mode,
        repo_root=repo_root,
        checkout_path=args.checkout_path,
        service=args.service,
        actual_host=platform.node().strip(),
        registry_path=args.registry,
        authorization_path=args.authorization_file,
        acceptance_permit_path=args.acceptance_permit,
        allowed_untracked_paths=_allowed_untracked(args.allowed_untracked_path),
        expected_working_directory=repo_root,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only writer capability authorization guard.")
    parser.add_argument("--capability", required=True)
    parser.add_argument("--service", required=True)
    parser.add_argument("--checkout-path", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--registry", type=Path, default=None)
    parser.add_argument(
        "--mode",
        choices=[m.value for m in ExecutionMode],
        default=ExecutionMode.PRODUCTION.value,
        help="Authorization mode to prove (default PRODUCTION for a committed service start).",
    )
    parser.add_argument("--authorization-file", type=Path, default=DEFAULT_AUTHORIZATION_FILE)
    parser.add_argument("--acceptance-permit", type=Path, default=None)
    parser.add_argument("--allowed-untracked-path", action="append", default=[])
    args = parser.parse_args()
    if args.registry is None:
        args.registry = (args.repo_root or args.checkout_path) / REPO_RELATIVE_REGISTRY

    try:
        decision = run_guard(args)
    except Exception as exc:  # noqa: BLE001 - fail-closed boundary.
        decision = AuthorizationDecision(False, args.capability, ExecutionMode(args.mode), [f"guard error: {exc}"])

    if decision.allowed:
        print(
            f"PASS capability={args.capability} service={args.service} mode={decision.mode.value} "
            "authorization_guard=pass host_mutations=0 database_writes=0 "
            "writer_invocations=0 systemctl_mutations=0"
        )
        return 0

    for reason in decision.reasons:
        print(f"FAIL capability={args.capability} service={args.service} reason={reason}")
    print(
        "authorization_guard=fail_closed host_mutations=0 database_writes=0 "
        "writer_invocations=0 systemctl_mutations=0"
    )
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
