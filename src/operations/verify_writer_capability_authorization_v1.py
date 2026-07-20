"""
verify_writer_capability_authorization_v1

Fail-closed, read-only ExecStartPre guard for writer-capability runtime starts.
The guard proves that a committed service is running only on the explicitly
authorized host, at the exact authorized checkout commit, for a capability whose
registry lifecycle permits runtime execution.

Absence of the deployment authorization file fails closed.

host_mutations=0 database_writes=0 writer_invocations=0 systemctl_mutations=0
broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0
decision_gate=none execution_planner=none executor=none
"""
from __future__ import annotations

import argparse
import json
import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REGISTRY_PATH = Path("deploy/ownership/writer_capability_ownership_v1.json")
DEFAULT_AUTHORIZATION_FILE = Path("/etc/synth/writer-capability-runtime-authorization-v1.json")
ALLOWED_LIFECYCLES = {"AUTHORIZED_INACTIVE", "ACTIVE"}
UNASSIGNED = "UNASSIGNED"


@dataclass(frozen=True)
class GuardResult:
    ok: bool
    errors: list[str]


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: expected JSON object")
    return payload


def _head_commit(checkout_path: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(checkout_path), "rev-parse", "--verify", "HEAD"],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("checkout HEAD commit could not be resolved")
    return result.stdout.strip()


def _capability(registry: dict[str, Any], capability_id: str) -> dict[str, Any] | None:
    for cap in registry.get("capabilities", []):
        if isinstance(cap, dict) and cap.get("capability_id") == capability_id:
            return cap
    return None


def verify_authorization(
    *,
    registry: dict[str, Any],
    authorization: dict[str, Any],
    capability_id: str,
    service: str,
    actual_host: str,
    actual_commit: str,
) -> GuardResult:
    errors: list[str] = []
    cap = _capability(registry, capability_id)
    if cap is None:
        return GuardResult(False, [f"unknown capability_id={capability_id}"])

    if authorization.get("authorization_version") != "writer_capability_runtime_authorization_v1":
        errors.append("authorization_version must be writer_capability_runtime_authorization_v1")
    if authorization.get("capability_id") != capability_id:
        errors.append("authorization capability_id mismatch")
    if authorization.get("service") != service:
        errors.append("authorization service mismatch")
    if cap.get("systemd_unit") != service:
        errors.append("registry systemd_unit mismatch")

    authorized_host = authorization.get("authorized_host")
    authorized_commit = authorization.get("authorized_commit")
    lifecycle = authorization.get("runtime_lifecycle")
    status = authorization.get("production_authorization_status")

    if cap.get("production_runtime_owner") == UNASSIGNED:
        errors.append("registry production_runtime_owner is UNASSIGNED")
    if cap.get("production_authorization_status") != "AUTHORIZED":
        errors.append("registry production_authorization_status is not AUTHORIZED")
    if cap.get("runtime_lifecycle") not in ALLOWED_LIFECYCLES:
        errors.append("registry runtime_lifecycle is not AUTHORIZED_INACTIVE or ACTIVE")
    if cap.get("production_decision_evidence", "").strip() == "":
        errors.append("registry production_decision_evidence is empty")

    if status != "AUTHORIZED":
        errors.append("authorization file status is not AUTHORIZED")
    if lifecycle not in ALLOWED_LIFECYCLES:
        errors.append("authorization file lifecycle is not AUTHORIZED_INACTIVE or ACTIVE")
    if authorized_host != cap.get("production_runtime_owner"):
        errors.append("authorization host does not match registry production_runtime_owner")
    if authorized_commit != actual_commit:
        errors.append("authorization commit does not match checkout HEAD")
    if actual_host != authorized_host:
        errors.append("actual hostname does not match authorized host")
    if not isinstance(authorized_commit, str) or len(authorized_commit) != 40:
        errors.append("authorization commit must be a full 40-character commit sha")
    if not authorization.get("decision_evidence"):
        errors.append("authorization file decision_evidence is required")
    if authorization.get("decision_evidence") != cap.get("production_decision_evidence"):
        errors.append("authorization decision_evidence must match registry")

    return GuardResult(not errors, errors)


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only writer capability authorization guard.")
    parser.add_argument("--capability", required=True)
    parser.add_argument("--service", required=True)
    parser.add_argument("--checkout-path", type=Path, required=True)
    parser.add_argument("--registry", type=Path, default=REGISTRY_PATH)
    parser.add_argument("--authorization-file", type=Path, default=DEFAULT_AUTHORIZATION_FILE)
    args = parser.parse_args()

    errors: list[str] = []
    if not args.authorization_file.exists():
        errors.append(f"authorization file missing: {args.authorization_file}")
        result = GuardResult(False, errors)
    else:
        try:
            registry = _load_json(args.registry)
            authorization = _load_json(args.authorization_file)
            result = verify_authorization(
                registry=registry,
                authorization=authorization,
                capability_id=args.capability,
                service=args.service,
                actual_host=platform.node().strip(),
                actual_commit=_head_commit(args.checkout_path),
            )
        except Exception as exc:  # noqa: BLE001 - fail-closed boundary.
            result = GuardResult(False, [f"authorization guard error: {exc}"])

    if result.ok:
        print(
            f"PASS capability={args.capability} service={args.service} "
            "authorization_guard=pass host_mutations=0 database_writes=0 "
            "writer_invocations=0 systemctl_mutations=0"
        )
        return 0

    for error in result.errors:
        print(f"FAIL capability={args.capability} service={args.service} reason={error}")
    print(
        "authorization_guard=fail_closed host_mutations=0 database_writes=0 "
        "writer_invocations=0 systemctl_mutations=0"
    )
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
