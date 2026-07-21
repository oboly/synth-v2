"""
validate_host_preflight_external_evidence_v1

Read-only validator for the host-preflight external-evidence manifest.

The manifest binds separately collected PREFLIGHT_EXTERNAL evidence to one exact
capability, host, and checkout commit. This validator never executes anything
from the manifest, never connects to a database or exchange, and never mutates
host state. It exists only to decide whether a manifest may be merged into a
read-only preflight, and to reject manifests that are mismatched, malformed, or
that attempt to smuggle secrets, local-check overrides, or acceptance/cutover
evidence into the preflight stage.

Safety boundary:
- reads only the manifest file supplied by path
- no command execution from the manifest
- no host mutation, no systemctl mutation, no writer invocation
- no database, broker, exchange, decision_gate, execution_planner, or executor

host_mutations=0 database_writes=0 writer_invocations=0 systemctl_mutations=0
broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0
decision_gate=none execution_planner=none executor=none
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from src.operations.run_host_preflight_v1 import (
    ACCEPTANCE_CHECKS,
    CAPABILITY_MODULES,
    CUTOVER_CHECKS,
    PREFLIGHT_EXTERNAL_CHECKS,
    PREFLIGHT_LOCAL_CHECKS,
)

SCHEMA_PATH = Path("deploy/ownership/host_preflight_external_evidence_v1.schema.json")

SCHEMA_VERSION = "host_preflight_external_evidence_schema_v1"
ALLOWED_STATUS = {"PASS", "WARN", "FAIL"}
REQUIRED_TOP_KEYS = {
    "schema_version",
    "capability",
    "hostname",
    "checkout_commit",
    "observed_at_utc",
    "checks",
    "safety_markers",
}
ALLOWED_TOP_KEYS = REQUIRED_TOP_KEYS | {"evidence_producer"}
REQUIRED_CHECK_KEYS = {"status", "detail", "evidence_source", "observed_at_utc"}

_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_RFC3339_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?Z$"
)

# Key names anywhere in the manifest that must never appear: they indicate a
# secret/credential was pasted into what must remain a non-secret artifact.
FORBIDDEN_KEY_SUBSTRINGS = (
    "secret",
    "password",
    "passwd",
    "api_key",
    "apikey",
    "api-key",
    "access_key",
    "token",
    "private_key",
    "privatekey",
    "seed",
    "credential",
    "passphrase",
)

# Free-text value patterns that look like a leaked secret. Applied only to the
# free-text fields (detail, evidence_source, evidence_producer); identity fields
# are matched exactly and cannot carry a payload.
_SECRET_VALUE_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+"),
    re.compile(r"(?i)\b(password|passwd|secret|token|api[_-]?key|private[_-]?key|passphrase)\b\s*[:=]\s*\S"),
)


class EvidenceValidationError(Exception):
    """Raised when the manifest cannot be parsed (including duplicate keys)."""


@dataclass(frozen=True)
class EvidenceValidationResult:
    errors: list[str]
    warnings: list[str] = field(default_factory=list)
    checks: dict[str, dict] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise EvidenceValidationError(f"duplicate key not allowed: {key!r}")
        seen[key] = value
    return seen


def _valid_literal_utc(value: Any) -> bool:
    if not isinstance(value, str) or not _RFC3339_RE.match(value):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _forbidden_key_hits(node: Any, path: str = "") -> list[str]:
    hits: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            lowered = str(key).lower()
            if any(token in lowered for token in FORBIDDEN_KEY_SUBSTRINGS):
                hits.append(f"forbidden secret-like key at {path or '<root>'}: {key!r}")
            hits.extend(_forbidden_key_hits(value, f"{path}.{key}" if path else str(key)))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            hits.extend(_forbidden_key_hits(item, f"{path}[{index}]"))
    return hits


def _secret_value_hits(text: str, where: str) -> list[str]:
    if not isinstance(text, str):
        return []
    return [
        f"secret-like value in {where}"
        for pattern in _SECRET_VALUE_PATTERNS
        if pattern.search(text)
    ]


def validate_external_evidence(
    payload: Any,
    *,
    capability: str,
    expected_host: str,
    expected_commit: str,
) -> EvidenceValidationResult:
    errors: list[str] = []

    if not isinstance(payload, dict):
        return EvidenceValidationResult(errors=["manifest root must be a JSON object"])

    # Forbidden secret-like keys anywhere in the manifest.
    errors.extend(_forbidden_key_hits(payload))

    unknown = set(payload) - ALLOWED_TOP_KEYS
    if unknown:
        errors.append(f"unknown top-level fields: {sorted(unknown)}")
    missing = REQUIRED_TOP_KEYS - set(payload)
    if missing:
        errors.append(f"missing required top-level fields: {sorted(missing)}")

    if payload.get("schema_version") != SCHEMA_VERSION:
        errors.append(
            f"schema_version must be {SCHEMA_VERSION!r}, got {payload.get('schema_version')!r}"
        )

    manifest_capability = payload.get("capability")
    if manifest_capability not in CAPABILITY_MODULES:
        errors.append(f"unknown capability: {manifest_capability!r}")
    elif manifest_capability != capability:
        errors.append(
            f"capability mismatch: manifest={manifest_capability!r} expected={capability!r}"
        )

    manifest_host = payload.get("hostname")
    if manifest_host != expected_host:
        errors.append(
            f"hostname mismatch: manifest={manifest_host!r} expected={expected_host!r} "
            "(evidence for a different host is rejected)"
        )

    manifest_commit = payload.get("checkout_commit")
    if not isinstance(manifest_commit, str) or not _COMMIT_RE.match(manifest_commit):
        errors.append(f"checkout_commit must be a 40-char lowercase hex sha, got {manifest_commit!r}")
    elif manifest_commit != expected_commit:
        errors.append(
            f"checkout_commit mismatch: manifest={manifest_commit!r} expected={expected_commit!r} "
            "(evidence for a different commit is rejected)"
        )

    if not _valid_literal_utc(payload.get("observed_at_utc")):
        errors.append(f"observed_at_utc is not a valid literal-Z UTC timestamp: {payload.get('observed_at_utc')!r}")

    producer = payload.get("evidence_producer")
    if producer is not None:
        if not isinstance(producer, str):
            errors.append("evidence_producer must be a string")
        else:
            errors.extend(_secret_value_hits(producer, "evidence_producer"))

    safety = payload.get("safety_markers")
    if not isinstance(safety, dict):
        errors.append("safety_markers must be an object")

    normalized: dict[str, dict] = {}
    checks = payload.get("checks")
    if not isinstance(checks, dict):
        errors.append("checks must be an object")
    elif not checks:
        errors.append("checks must contain at least one preflight-external check")
    else:
        for name, spec in checks.items():
            if name in PREFLIGHT_LOCAL_CHECKS:
                errors.append(
                    f"check {name!r} is a local check; external evidence must not override local checks"
                )
                continue
            if name in ACCEPTANCE_CHECKS or name in CUTOVER_CHECKS:
                errors.append(
                    f"check {name!r} is acceptance/cutover evidence; it must not be presented as preflight evidence"
                )
                continue
            if name not in PREFLIGHT_EXTERNAL_CHECKS:
                errors.append(f"unknown preflight-external check: {name!r}")
                continue
            if not isinstance(spec, dict):
                errors.append(f"check {name!r} must be an object")
                continue
            unknown_check_keys = set(spec) - REQUIRED_CHECK_KEYS
            if unknown_check_keys:
                errors.append(f"check {name!r} has unknown fields: {sorted(unknown_check_keys)}")
            missing_check_keys = REQUIRED_CHECK_KEYS - set(spec)
            if missing_check_keys:
                errors.append(f"check {name!r} missing fields: {sorted(missing_check_keys)}")
                continue
            status = spec.get("status")
            if status not in ALLOWED_STATUS:
                errors.append(f"check {name!r} status must be one of {sorted(ALLOWED_STATUS)}, got {status!r}")
            detail = spec.get("detail")
            if not isinstance(detail, str):
                errors.append(f"check {name!r} detail must be a string")
            else:
                errors.extend(_secret_value_hits(detail, f"check {name!r} detail"))
            evidence_source = spec.get("evidence_source")
            if not isinstance(evidence_source, str) or not evidence_source.strip():
                errors.append(f"check {name!r} evidence_source must be a non-empty string")
            else:
                errors.extend(_secret_value_hits(evidence_source, f"check {name!r} evidence_source"))
            if not _valid_literal_utc(spec.get("observed_at_utc")):
                errors.append(
                    f"check {name!r} observed_at_utc is not a valid literal-Z UTC timestamp: {spec.get('observed_at_utc')!r}"
                )
            if status in ALLOWED_STATUS and isinstance(detail, str) and isinstance(evidence_source, str):
                normalized[name] = {
                    "status": status,
                    "detail": detail,
                    "evidence_source": evidence_source,
                    "observed_at_utc": spec.get("observed_at_utc"),
                }

    if errors:
        return EvidenceValidationResult(errors=errors)
    return EvidenceValidationResult(errors=[], checks=normalized)


def load_and_validate_external_evidence(
    path: Path,
    *,
    capability: str,
    expected_host: str,
    expected_commit: str,
) -> EvidenceValidationResult:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return EvidenceValidationResult(errors=[f"cannot read evidence file: {exc}"])
    try:
        payload = json.loads(text, object_pairs_hook=_no_duplicate_keys)
    except EvidenceValidationError as exc:
        return EvidenceValidationResult(errors=[str(exc)])
    except json.JSONDecodeError as exc:
        return EvidenceValidationResult(errors=[f"invalid JSON: {exc}"])
    return validate_external_evidence(
        payload,
        capability=capability,
        expected_host=expected_host,
        expected_commit=expected_commit,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a host-preflight external-evidence manifest (read-only, non-authorizing)."
    )
    parser.add_argument("--evidence-file", type=Path, required=True)
    parser.add_argument("--capability", required=True, choices=sorted(CAPABILITY_MODULES))
    parser.add_argument("--expected-host", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--output", choices=("table", "json"), default="table")
    args = parser.parse_args()

    result = load_and_validate_external_evidence(
        args.evidence_file,
        capability=args.capability,
        expected_host=args.expected_host,
        expected_commit=args.expected_commit,
    )

    if args.output == "json":
        print(
            json.dumps(
                {
                    "ok": result.ok,
                    "errors": result.errors,
                    "warnings": result.warnings,
                    "merged_checks": sorted(result.checks),
                    "safety_markers": {
                        "host_mutations": 0,
                        "database_writes": 0,
                        "writer_invocations": 0,
                        "systemctl_mutations": 0,
                        "exchange_calls": 0,
                    },
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(f"evidence_ok={str(result.ok).lower()} error_count={len(result.errors)} merged_checks={len(result.checks)}")
        for error in result.errors:
            print(f"ERROR {error}")
        print(
            "host_mutations=0 database_writes=0 writer_invocations=0 "
            "systemctl_mutations=0 exchange_calls=0"
        )
    return 0 if result.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
