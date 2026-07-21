"""
validate_host_preflight_external_evidence_v1

Read-only validator for the host-preflight external-evidence manifest.

The manifest binds separately collected PREFLIGHT_EXTERNAL evidence to one exact
capability, host, checkout commit, and bounded time window. This validator never
executes anything from the manifest, never connects to a database or exchange,
and never mutates host state. It exists only to decide whether a manifest may be
merged into a read-only preflight, and to reject manifests that are mismatched,
malformed, stale, mutation-attesting, or that attempt to smuggle secrets,
local-check overrides, or acceptance/cutover evidence into the preflight stage.

Freshness: strict preflight must not rest on indefinitely reusable evidence.
Every manifest and every check timestamp is bounded against an explicit
reference time and a maximum age, with a small clock-skew allowance.

Safety markers: the manifest must attest that producing the evidence performed
no mutation. Read-only probes (DB connections/queries, DNS, public exchange
calls) may be nonzero; mutation/write/invocation/order counters must be zero and
the authorization/deployment flags must be false.

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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.operations.run_host_preflight_v1 import (
    ACCEPTANCE_CHECKS,
    CAPABILITY_MODULES,
    CUTOVER_CHECKS,
    DEFAULT_MAX_EXTERNAL_EVIDENCE_AGE_SECONDS,
    PREFLIGHT_EXTERNAL_CHECKS,
    PREFLIGHT_LOCAL_CHECKS,
)

SCHEMA_PATH = Path("deploy/ownership/host_preflight_external_evidence_v1.schema.json")

SCHEMA_VERSION = "host_preflight_external_evidence_schema_v1"
ALLOWED_STATUS = {"PASS", "WARN", "FAIL"}
MAX_DETAIL_LENGTH = 500
MAX_EVIDENCE_SOURCE_LENGTH = 500

# Small allowance (seconds) for benign clock drift between the evidence producer
# and the preflight host.
CLOCK_SKEW_ALLOWANCE_SECONDS = 60

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

# Safety-marker contract.
SAFETY_ZERO_COUNTERS = (
    "host_mutations",
    "database_writes",
    "writer_invocations",
    "systemctl_mutations",
    "order_submission",
    "broker_writes",
)
SAFETY_FALSE_FLAGS = (
    "authorization_created",
    "deployment_performed",
)
# Read-only probe activity that is the purpose of this lane and may be nonzero.
SAFETY_ALLOWED_NONNEGATIVE_COUNTERS = (
    "database_connections",
    "database_read_queries",
    "dns_lookups",
    "exchange_public_calls",
)
SAFETY_REQUIRED_KEYS = set(SAFETY_ZERO_COUNTERS) | set(SAFETY_FALSE_FLAGS)
SAFETY_ALLOWED_KEYS = SAFETY_REQUIRED_KEYS | set(SAFETY_ALLOWED_NONNEGATIVE_COUNTERS)

_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_RFC3339_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?Z$"
)

# Canonical structural keys and canonical check names. These are part of the
# contract (for example the external check `private_exchange_credentials`) and
# must never be flagged as secret-like even though their names contain otherwise
# forbidden substrings. Misplaced canonical keys are still caught by the
# per-context unknown-field validation, so exempting them here opens no hole.
CANONICAL_ALLOWED_KEYS = frozenset(
    ALLOWED_TOP_KEYS
    | set(PREFLIGHT_EXTERNAL_CHECKS)
    | REQUIRED_CHECK_KEYS
    | SAFETY_ALLOWED_KEYS
)

# Substrings that mark an UNKNOWN/arbitrary key as secret-bearing: they indicate
# a secret/credential was pasted into what must remain a non-secret artifact.
# Only applied to keys not in CANONICAL_ALLOWED_KEYS.
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

# Free-text value patterns that look like a leaked secret. Applied to the
# contract's free-text fields (detail, evidence_source, evidence_producer).
# Identity values are never rendered by the structured issue boundary below.
_SECRET_VALUE_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+"),
    re.compile(r"(?i)\b(password|passwd|secret|token|api[_-]?key|private[_-]?key|passphrase)\b\s*[:=]\s*\S"),
)


_ISSUE_MESSAGES = {
    "MAX_AGE_INVALID": "max_age_seconds must be a positive integer",
    "MANIFEST_ROOT_INVALID": "manifest root must be a JSON object",
    "FORBIDDEN_SECRET_LIKE_KEY": "forbidden secret-like key detected",
    "UNKNOWN_TOP_LEVEL_FIELDS": "unknown top-level fields",
    "MISSING_TOP_LEVEL_FIELDS": "missing required top-level fields",
    "SCHEMA_VERSION_MISMATCH": "schema_version mismatch",
    "CAPABILITY_UNSUPPORTED": "capability unsupported",
    "CAPABILITY_MISMATCH": "capability mismatch",
    "HOSTNAME_MISMATCH": "hostname mismatch",
    "CHECKOUT_COMMIT_INVALID": "checkout_commit invalid format",
    "CHECKOUT_COMMIT_MISMATCH": "checkout_commit mismatch",
    "TIMESTAMP_INVALID": "observed_at_utc invalid",
    "TIMESTAMP_FUTURE": "observed_at_utc is in the future",
    "EVIDENCE_STALE": "external evidence is stale",
    "FIELD_TYPE_INVALID": "field has invalid type",
    "SECRET_LIKE_VALUE": "secret-like value detected",
    "SAFETY_UNKNOWN_FIELDS": "safety_markers has unknown fields",
    "SAFETY_MISSING_FIELDS": "safety_markers missing required fields",
    "COUNTER_TYPE_INVALID": "counter must be an integer",
    "COUNTER_NEGATIVE": "counter must not be negative",
    "COUNTER_NONZERO": "counter must be 0",
    "FLAG_TYPE_INVALID": "flag must be a boolean",
    "FLAG_TRUE": "flag must be false",
    "CHECKS_EMPTY": "checks must contain at least one preflight-external check",
    "LOCAL_CHECK_OVERRIDE": "external evidence must not override local checks",
    "DEFERRED_CHECK_PRESENT": "acceptance/cutover evidence must not be presented as preflight evidence",
    "UNKNOWN_EXTERNAL_CHECK": "unknown preflight-external check",
    "CHECK_UNKNOWN_FIELDS": "check has unknown fields",
    "CHECK_MISSING_FIELDS": "check missing required fields",
    "CHECK_STATUS_INVALID": "check status invalid",
    "STRING_EMPTY": "string field must be non-empty",
    "STRING_TOO_LONG": "string field exceeds maximum length",
    "CHECK_TIMESTAMP_NEWER": "check timestamp is newer than the manifest",
    "CHECK_TIMESTAMP_PREDATES_WINDOW": "check timestamp predates the manifest window",
    "EVIDENCE_FILE_UNREADABLE": "cannot read evidence file",
    "DUPLICATE_KEY": "duplicate key not allowed",
    "INVALID_JSON": "invalid JSON",
    "INVALID_UTF8": "evidence file must be valid UTF-8",
}

_CANONICAL_CHECK_NAMES = (
    set(PREFLIGHT_LOCAL_CHECKS)
    | set(PREFLIGHT_EXTERNAL_CHECKS)
    | set(ACCEPTANCE_CHECKS)
    | set(CUTOVER_CHECKS)
)
_SAFE_ISSUE_FIELDS = frozenset(
    {
        "manifest",
        "max_age_seconds",
        "schema_version",
        "capability",
        "hostname",
        "checkout_commit",
        "observed_at_utc",
        "evidence_producer",
        "safety_markers",
        "checks",
        "evidence_file",
    }
    | {f"safety_markers.{name}" for name in SAFETY_ALLOWED_KEYS}
    | {f"checks.{name}" for name in _CANONICAL_CHECK_NAMES}
    | {
        f"checks.{name}.{field_name}"
        for name in PREFLIGHT_EXTERNAL_CHECKS
        for field_name in REQUIRED_CHECK_KEYS
    }
)


@dataclass(frozen=True)
class EvidenceValidationIssue:
    """One redacted validation issue built only from trusted metadata."""

    code: str
    field: str
    provided_type: str | None = None
    provided_length: int | None = None
    count: int | None = None
    limit: int | None = None

    @property
    def message(self) -> str:
        return _ISSUE_MESSAGES[self.code]

    def as_dict(self) -> dict[str, str | int]:
        payload: dict[str, str | int] = {
            "code": self.code,
            "field": self.field,
        }
        for name in ("provided_type", "provided_length", "count", "limit"):
            value = getattr(self, name)
            if value is not None:
                payload[name] = value
        return payload

    def render(self) -> str:
        metadata = self.as_dict()
        metadata.pop("code")
        suffix = " ".join(f"{name}={value}" for name, value in metadata.items())
        return f"{self.message} {suffix}".strip()


_UNSET = object()


def _issue(
    code: str,
    field: str,
    *,
    provided: Any = _UNSET,
    count: int | None = None,
    limit: int | None = None,
) -> EvidenceValidationIssue:
    """Create an error without retaining or rendering an untrusted value."""

    if code not in _ISSUE_MESSAGES:
        raise ValueError("validation issue code must be canonical")
    if field not in _SAFE_ISSUE_FIELDS:
        raise ValueError("validation issue field must be canonical")
    provided_type: str | None = None
    provided_length: int | None = None
    if provided is not _UNSET:
        provided_type = type(provided).__name__
        if isinstance(provided, (str, bytes, list, tuple, dict)):
            provided_length = len(provided)
    return EvidenceValidationIssue(
        code=code,
        field=field,
        provided_type=provided_type,
        provided_length=provided_length,
        count=count,
        limit=limit,
    )


class EvidenceValidationError(Exception):
    """Raised when the manifest cannot be parsed without retaining raw input."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class EvidenceValidationResult:
    issues: list[EvidenceValidationIssue]
    warnings: list[str] = field(default_factory=list)
    checks: dict[str, dict] = field(default_factory=dict)
    observed_at_utc: str | None = None
    age_seconds: float | None = None
    max_age_seconds: int | None = None

    @property
    def ok(self) -> bool:
        return not self.issues

    @property
    def errors(self) -> list[str]:
        """Redacted human-readable errors retained for table-mode compatibility."""

        return [issue.render() for issue in self.issues]

    @property
    def error_payloads(self) -> list[dict[str, str | int]]:
        return [issue.as_dict() for issue in self.issues]


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise EvidenceValidationError("DUPLICATE_KEY")
        seen[key] = value
    return seen


def _parse_literal_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not _RFC3339_RE.match(value):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _forbidden_key_hit_count(node: Any) -> int:
    """Flag arbitrary secret-bearing keys, exempting canonical structural keys.

    Canonical schema keys and canonical check names (including
    `private_exchange_credentials`) are contract-defined and never flagged; only
    unknown/arbitrary keys are checked for secret-like tokens.
    """
    hits = 0
    if isinstance(node, dict):
        for key, value in node.items():
            lowered = str(key).lower()
            if key not in CANONICAL_ALLOWED_KEYS and any(
                token in lowered for token in FORBIDDEN_KEY_SUBSTRINGS
            ):
                hits += 1
            hits += _forbidden_key_hit_count(value)
    elif isinstance(node, list):
        for item in node:
            hits += _forbidden_key_hit_count(item)
    return hits


def _secret_value_issues(text: str, field: str) -> list[EvidenceValidationIssue]:
    if not isinstance(text, str):
        return []
    if any(pattern.search(text) for pattern in _SECRET_VALUE_PATTERNS):
        return [_issue("SECRET_LIKE_VALUE", field)]
    return []


def _is_int(value: Any) -> bool:
    # bool is a subtype of int; reject it where an integer counter is required.
    return isinstance(value, int) and not isinstance(value, bool)


def _validate_safety_markers(safety: Any) -> list[EvidenceValidationIssue]:
    issues: list[EvidenceValidationIssue] = []
    if not isinstance(safety, dict):
        return [_issue("FIELD_TYPE_INVALID", "safety_markers", provided=safety)]
    unknown = set(safety) - SAFETY_ALLOWED_KEYS
    if unknown:
        issues.append(_issue("SAFETY_UNKNOWN_FIELDS", "safety_markers", count=len(unknown)))
    missing = SAFETY_REQUIRED_KEYS - set(safety)
    if missing:
        issues.append(_issue("SAFETY_MISSING_FIELDS", "safety_markers", count=len(missing)))
    for name in SAFETY_ZERO_COUNTERS:
        if name not in safety:
            continue
        value = safety[name]
        field = f"safety_markers.{name}"
        if not _is_int(value):
            issues.append(_issue("COUNTER_TYPE_INVALID", field, provided=value))
        elif value < 0:
            issues.append(_issue("COUNTER_NEGATIVE", field))
        elif value != 0:
            issues.append(_issue("COUNTER_NONZERO", field))
    for name in SAFETY_FALSE_FLAGS:
        if name not in safety:
            continue
        value = safety[name]
        field = f"safety_markers.{name}"
        if not isinstance(value, bool):
            issues.append(_issue("FLAG_TYPE_INVALID", field, provided=value))
        elif value is not False:
            issues.append(_issue("FLAG_TRUE", field))
    for name in SAFETY_ALLOWED_NONNEGATIVE_COUNTERS:
        if name not in safety:
            continue
        value = safety[name]
        field = f"safety_markers.{name}"
        if not _is_int(value):
            issues.append(_issue("COUNTER_TYPE_INVALID", field, provided=value))
        elif value < 0:
            issues.append(_issue("COUNTER_NEGATIVE", field))
    return issues


def validate_external_evidence(
    payload: Any,
    *,
    capability: str,
    expected_host: str,
    expected_commit: str,
    reference_time: datetime,
    max_age_seconds: int = DEFAULT_MAX_EXTERNAL_EVIDENCE_AGE_SECONDS,
) -> EvidenceValidationResult:
    issues: list[EvidenceValidationIssue] = []

    if max_age_seconds <= 0:
        return EvidenceValidationResult(
            issues=[_issue("MAX_AGE_INVALID", "max_age_seconds")]
        )
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=UTC)

    if not isinstance(payload, dict):
        return EvidenceValidationResult(
            issues=[_issue("MANIFEST_ROOT_INVALID", "manifest", provided=payload)]
        )

    # Forbidden secret-like keys anywhere in the manifest.
    forbidden_key_count = _forbidden_key_hit_count(payload)
    if forbidden_key_count:
        issues.append(
            _issue(
                "FORBIDDEN_SECRET_LIKE_KEY",
                "manifest",
                count=forbidden_key_count,
            )
        )

    unknown = set(payload) - ALLOWED_TOP_KEYS
    if unknown:
        issues.append(_issue("UNKNOWN_TOP_LEVEL_FIELDS", "manifest", count=len(unknown)))
    missing = REQUIRED_TOP_KEYS - set(payload)
    if missing:
        issues.append(_issue("MISSING_TOP_LEVEL_FIELDS", "manifest", count=len(missing)))

    manifest_schema_version = payload.get("schema_version")
    if manifest_schema_version != SCHEMA_VERSION:
        issues.append(
            _issue(
                "SCHEMA_VERSION_MISMATCH",
                "schema_version",
                provided=manifest_schema_version,
            )
        )

    manifest_capability = payload.get("capability")
    if not isinstance(manifest_capability, str) or manifest_capability not in CAPABILITY_MODULES:
        issues.append(
            _issue("CAPABILITY_UNSUPPORTED", "capability", provided=manifest_capability)
        )
    elif manifest_capability != capability:
        issues.append(_issue("CAPABILITY_MISMATCH", "capability", provided=manifest_capability))

    manifest_host = payload.get("hostname")
    if manifest_host != expected_host:
        issues.append(_issue("HOSTNAME_MISMATCH", "hostname", provided=manifest_host))

    manifest_commit = payload.get("checkout_commit")
    if not isinstance(manifest_commit, str) or not _COMMIT_RE.match(manifest_commit):
        issues.append(
            _issue("CHECKOUT_COMMIT_INVALID", "checkout_commit", provided=manifest_commit)
        )
    elif manifest_commit != expected_commit:
        issues.append(
            _issue("CHECKOUT_COMMIT_MISMATCH", "checkout_commit", provided=manifest_commit)
        )

    manifest_observed_raw = payload.get("observed_at_utc")
    manifest_observed = _parse_literal_utc(manifest_observed_raw)
    age_seconds: float | None = None
    if manifest_observed is None:
        issues.append(
            _issue("TIMESTAMP_INVALID", "observed_at_utc", provided=manifest_observed_raw)
        )
    else:
        age_seconds = (reference_time - manifest_observed).total_seconds()
        if age_seconds < -CLOCK_SKEW_ALLOWANCE_SECONDS:
            issues.append(_issue("TIMESTAMP_FUTURE", "observed_at_utc"))
        elif age_seconds > max_age_seconds:
            issues.append(_issue("EVIDENCE_STALE", "observed_at_utc"))

    producer = payload.get("evidence_producer")
    if producer is not None:
        if not isinstance(producer, str):
            issues.append(
                _issue("FIELD_TYPE_INVALID", "evidence_producer", provided=producer)
            )
        else:
            issues.extend(_secret_value_issues(producer, "evidence_producer"))

    issues.extend(_validate_safety_markers(payload.get("safety_markers")))

    normalized: dict[str, dict] = {}
    checks = payload.get("checks")
    if not isinstance(checks, dict):
        issues.append(_issue("FIELD_TYPE_INVALID", "checks", provided=checks))
    elif not checks:
        issues.append(_issue("CHECKS_EMPTY", "checks"))
    else:
        for name, spec in checks.items():
            if name in PREFLIGHT_LOCAL_CHECKS:
                issues.append(
                    _issue("LOCAL_CHECK_OVERRIDE", f"checks.{name}")
                )
                continue
            if name in ACCEPTANCE_CHECKS or name in CUTOVER_CHECKS:
                issues.append(
                    _issue("DEFERRED_CHECK_PRESENT", f"checks.{name}")
                )
                continue
            if name not in PREFLIGHT_EXTERNAL_CHECKS:
                issues.append(_issue("UNKNOWN_EXTERNAL_CHECK", "checks"))
                continue
            check_field = f"checks.{name}"
            if not isinstance(spec, dict):
                issues.append(_issue("FIELD_TYPE_INVALID", check_field, provided=spec))
                continue
            unknown_check_keys = set(spec) - REQUIRED_CHECK_KEYS
            if unknown_check_keys:
                issues.append(
                    _issue(
                        "CHECK_UNKNOWN_FIELDS",
                        check_field,
                        count=len(unknown_check_keys),
                    )
                )
            missing_check_keys = REQUIRED_CHECK_KEYS - set(spec)
            if missing_check_keys:
                issues.append(
                    _issue(
                        "CHECK_MISSING_FIELDS",
                        check_field,
                        count=len(missing_check_keys),
                    )
                )
                continue
            check_issue_count = len(issues)
            status = spec.get("status")
            if status not in ALLOWED_STATUS:
                issues.append(
                    _issue(
                        "CHECK_STATUS_INVALID",
                        f"{check_field}.status",
                        provided=status,
                    )
                )
            detail = spec.get("detail")
            if not isinstance(detail, str):
                issues.append(
                    _issue("FIELD_TYPE_INVALID", f"{check_field}.detail", provided=detail)
                )
            else:
                if len(detail) > MAX_DETAIL_LENGTH:
                    issues.append(
                        _issue(
                            "STRING_TOO_LONG",
                            f"{check_field}.detail",
                            provided=detail,
                            limit=MAX_DETAIL_LENGTH,
                        )
                    )
                issues.extend(_secret_value_issues(detail, f"{check_field}.detail"))
            evidence_source = spec.get("evidence_source")
            if not isinstance(evidence_source, str) or not evidence_source.strip():
                if not isinstance(evidence_source, str):
                    issues.append(
                        _issue(
                            "FIELD_TYPE_INVALID",
                            f"{check_field}.evidence_source",
                            provided=evidence_source,
                        )
                    )
                else:
                    issues.append(
                        _issue("STRING_EMPTY", f"{check_field}.evidence_source")
                    )
            else:
                if len(evidence_source) > MAX_EVIDENCE_SOURCE_LENGTH:
                    issues.append(
                        _issue(
                            "STRING_TOO_LONG",
                            f"{check_field}.evidence_source",
                            provided=evidence_source,
                            limit=MAX_EVIDENCE_SOURCE_LENGTH,
                        )
                    )
                issues.extend(
                    _secret_value_issues(
                        evidence_source,
                        f"{check_field}.evidence_source",
                    )
                )
            check_observed_raw = spec.get("observed_at_utc")
            check_observed = _parse_literal_utc(check_observed_raw)
            if check_observed is None:
                issues.append(
                    _issue(
                        "TIMESTAMP_INVALID",
                        f"{check_field}.observed_at_utc",
                        provided=check_observed_raw,
                    )
                )
            else:
                check_age = (reference_time - check_observed).total_seconds()
                if check_age < -CLOCK_SKEW_ALLOWANCE_SECONDS:
                    issues.append(
                        _issue("TIMESTAMP_FUTURE", f"{check_field}.observed_at_utc")
                    )
                elif check_age > max_age_seconds:
                    issues.append(
                        _issue("EVIDENCE_STALE", f"{check_field}.observed_at_utc")
                    )
                if manifest_observed is not None:
                    ahead = (check_observed - manifest_observed).total_seconds()
                    if ahead > CLOCK_SKEW_ALLOWANCE_SECONDS:
                        issues.append(
                            _issue(
                                "CHECK_TIMESTAMP_NEWER",
                                f"{check_field}.observed_at_utc",
                            )
                        )
                    elif ahead < -max_age_seconds:
                        issues.append(
                            _issue(
                                "CHECK_TIMESTAMP_PREDATES_WINDOW",
                                f"{check_field}.observed_at_utc",
                            )
                        )
            if len(issues) == check_issue_count:
                normalized[name] = {
                    "status": status,
                    "detail": detail,
                    "evidence_source": evidence_source,
                    "observed_at_utc": check_observed_raw,
                }

    safe_observed_at = manifest_observed_raw if manifest_observed is not None else None
    if issues:
        return EvidenceValidationResult(
            issues=issues,
            observed_at_utc=safe_observed_at,
            age_seconds=age_seconds,
            max_age_seconds=max_age_seconds,
        )
    return EvidenceValidationResult(
        issues=[],
        checks=normalized,
        observed_at_utc=safe_observed_at,
        age_seconds=age_seconds,
        max_age_seconds=max_age_seconds,
    )


def load_and_validate_external_evidence(
    path: Path,
    *,
    capability: str,
    expected_host: str,
    expected_commit: str,
    reference_time: datetime,
    max_age_seconds: int = DEFAULT_MAX_EXTERNAL_EVIDENCE_AGE_SECONDS,
) -> EvidenceValidationResult:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return EvidenceValidationResult(
            issues=[_issue("EVIDENCE_FILE_UNREADABLE", "evidence_file")]
        )
    except UnicodeError:
        return EvidenceValidationResult(
            issues=[_issue("INVALID_UTF8", "evidence_file")]
        )
    try:
        payload = json.loads(text, object_pairs_hook=_no_duplicate_keys)
    except EvidenceValidationError as exc:
        return EvidenceValidationResult(
            issues=[_issue(exc.code, "manifest")]
        )
    except json.JSONDecodeError:
        return EvidenceValidationResult(
            issues=[_issue("INVALID_JSON", "manifest")]
        )
    return validate_external_evidence(
        payload,
        capability=capability,
        expected_host=expected_host,
        expected_commit=expected_commit,
        reference_time=reference_time,
        max_age_seconds=max_age_seconds,
    )


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a host-preflight external-evidence manifest (read-only, non-authorizing)."
    )
    parser.add_argument("--evidence-file", type=Path, required=True)
    parser.add_argument("--capability", required=True, choices=sorted(CAPABILITY_MODULES))
    parser.add_argument("--expected-host", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument(
        "--max-external-evidence-age-seconds",
        type=_positive_int,
        default=DEFAULT_MAX_EXTERNAL_EVIDENCE_AGE_SECONDS,
    )
    parser.add_argument("--output", choices=("table", "json"), default="table")
    args = parser.parse_args()

    result = load_and_validate_external_evidence(
        args.evidence_file,
        capability=args.capability,
        expected_host=args.expected_host,
        expected_commit=args.expected_commit,
        reference_time=datetime.now(UTC),
        max_age_seconds=args.max_external_evidence_age_seconds,
    )

    if args.output == "json":
        print(
            json.dumps(
                {
                    "ok": result.ok,
                    "errors": result.error_payloads,
                    "warnings": result.warnings,
                    "merged_checks": sorted(result.checks),
                    "external_evidence_observed_at_utc": result.observed_at_utc,
                    "external_evidence_age_seconds": result.age_seconds,
                    "external_evidence_max_age_seconds": result.max_age_seconds,
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
        print(
            f"evidence_ok={str(result.ok).lower()} error_count={len(result.issues)} "
            f"merged_checks={len(result.checks)} age_seconds={result.age_seconds} "
            f"max_age_seconds={result.max_age_seconds}"
        )
        for error in result.errors:
            print(f"ERROR {error}")
        print(
            "host_mutations=0 database_writes=0 writer_invocations=0 "
            "systemctl_mutations=0 exchange_calls=0"
        )
    return 0 if result.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
