"""
writer_capability_authorization_v1

Single shared, importable authorization implementation for writer-capability
runtime execution. The systemd ``ExecStartPre`` guard, the shell wrappers, and
the Python mutation entrypoints all consume this one module so that
authorization semantics are identical at every layer. Absence or invalidity of
any required artifact fails closed.

Enforcement layers (defense in depth, single semantics):

    systemd ExecStartPre  -> early failure before the service body runs
    shell wrapper         -> fail before launching a write-capable process
    Python mutation entry -> final mandatory boundary immediately before a
                             database write or artifact publication

Execution modes:

    READ_ONLY   -> no production authorization required; mutation is forbidden
    ACCEPTANCE  -> a separate bounded, expiring acceptance permit is required;
                   never grants production ownership
    PRODUCTION  -> exact production authorization is required

Default mode is READ_ONLY. A missing or unparsable mode is treated as
READ_ONLY (fail closed against mutation), never implicitly PRODUCTION.

Safety boundary:
- reads only repository files and the supplied authorization/permit files
- no host mutation, no systemctl mutation, no writer invocation
- no database, broker, reporting, decision_gate, execution_planner, executor

host_mutations=0 database_writes=0 writer_invocations=0 systemctl_mutations=0
broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0
decision_gate=none execution_planner=none executor=none
"""
from __future__ import annotations

import json
import os
import platform
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from src.operations.validate_writer_capability_ownership_v1 import (
    RegistryValidationError,
    validate_registry_payload,
)


# ---------------------------------------------------------------------------
# Constants and canonical identity mapping.
# ---------------------------------------------------------------------------

REPO_RELATIVE_REGISTRY = Path("deploy/ownership/writer_capability_ownership_v1.json")
REPO_RELATIVE_REGISTRY_SCHEMA = Path("deploy/ownership/writer_capability_ownership_v1.schema.json")
REPO_RELATIVE_AUTHORIZATION_SCHEMA = Path("deploy/ownership/writer_capability_authorization_v1.schema.json")
REPO_RELATIVE_ACCEPTANCE_SCHEMA = Path("deploy/ownership/writer_capability_acceptance_permit_v1.schema.json")

DEFAULT_AUTHORIZATION_FILE = Path("/etc/synth/writer-capability-runtime-authorization-v1.json")
# The single fixed, documented runtime directory an acceptance permit path may
# live under in production. Not environment-controlled.
DEFAULT_ACCEPTANCE_PERMIT_ROOT = Path("/run/synth/writer-acceptance")

ENV_MODE = "SYNTH_WRITER_EXECUTION_MODE"
ENV_CAPABILITY = "SYNTH_WRITER_CAPABILITY_ID"
# The production authorization path is registry-declared and is never
# environment-overridable. Acceptance permits are supplied by explicit path.
ENV_ACCEPTANCE_PERMIT = "SYNTH_WRITER_ACCEPTANCE_PERMIT"
ENV_ALLOWED_UNTRACKED = "SYNTH_WRITER_ALLOWED_UNTRACKED_PATHS"

AUTHORIZATION_VERSION = "writer_capability_runtime_authorization_v1"
ACCEPTANCE_PERMIT_VERSION = "writer_capability_acceptance_permit_v1"

ALLOWED_PRODUCTION_LIFECYCLES = {"AUTHORIZED_INACTIVE", "ACTIVE"}

CAPABILITY_IDENTITY: dict[str, str] = {
    "public_price_snapshot": "public-price-snapshot-writer",
    "public_candle_freshness": "public-candle-freshness-writer",
    "market_rotation_pressure": "market-rotation-pressure-writer",
    "native_short_4h_chain": "native-short-4h-chain",
}

# Untracked files under these repo-relative prefixes can affect imported or
# executed code, configuration, authorization, registry, schema, service units,
# wrappers, or runtime artifacts. They are always rejected regardless of the
# allow-list. Only explicitly documented paths outside these prefixes may be
# allowed.
PROTECTED_UNTRACKED_PREFIXES = (
    "src/",
    "scripts/",
    "deploy/",
    "configs/",
    "config/",
    "etc/",
    "apps/",
    "db/",
    ".github/",
    "data/public/",
)
PROTECTED_UNTRACKED_SUFFIXES = (
    ".py",
    ".sh",
    ".service",
    ".timer",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".cfg",
    ".ini",
    ".env",
)

# Canonical literal-UTC only: YYYY-MM-DDTHH:MM:SS(.frac)?Z. A numeric offset
# (+01:00, -05:00) or a timezone-less timestamp is rejected; there is exactly
# one accepted representation and offsets are never silently normalized.
_UTC_LITERAL_Z_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?Z$"
)
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


class ExecutionMode(str, Enum):
    READ_ONLY = "READ_ONLY"
    ACCEPTANCE = "ACCEPTANCE"
    PRODUCTION = "PRODUCTION"


class AuthorizationDenied(RuntimeError):
    """Raised at a mutation boundary when authorization is not satisfied."""

    def __init__(self, capability_id: str, mode: "ExecutionMode", reasons: list[str]):
        self.capability_id = capability_id
        self.mode = mode
        self.reasons = list(reasons)
        joined = "; ".join(reasons) if reasons else "authorization not satisfied"
        super().__init__(
            f"writer capability authorization denied capability={capability_id} mode={mode.value}: {joined}"
        )


@dataclass(frozen=True)
class LoadResult:
    payload: dict[str, Any] | None
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.payload is not None and not self.errors


# Module-private construction seal. A WriterMutationAuthorization can only be
# constructed by this module's verification flow. This deterministically
# prevents accidental and alternate-call-path bypasses (a caller cannot build a
# context out of a plain dict, an unvalidated dataclass, or authorized=True).
_MUTATION_AUTH_SEAL = object()


@dataclass(frozen=True)
class WriterMutationAuthorization:
    """Immutable, validated proof that a specific mutation is authorized.

    Constructed only by the shared authorization verification flow after the
    full registry/schema/semantic/mode/capability/host/commit/checkout and
    authorization-or-permit validation has passed. Mutating helpers require an
    instance as a keyword-only argument and call :meth:`require_capability`
    before their first mutation.
    """

    capability_id: str
    execution_mode: ExecutionMode
    validated_host: str
    validated_commit: str
    authorization_or_permit_id: str
    _seal: Any = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._seal is not _MUTATION_AUTH_SEAL:
            raise RuntimeError(
                "WriterMutationAuthorization may only be constructed by the shared "
                "authorization verification flow"
            )
        object.__setattr__(self, "_seal", None)

    def require_capability(self, capability_id: str) -> "WriterMutationAuthorization":
        if self.capability_id != capability_id:
            raise AuthorizationDenied(
                capability_id,
                self.execution_mode,
                [f"authorization context is for {self.capability_id}, not {capability_id}"],
            )
        return self


def _mint_authorization(
    *,
    capability_id: str,
    execution_mode: ExecutionMode,
    validated_host: str,
    validated_commit: str,
    authorization_or_permit_id: str,
) -> WriterMutationAuthorization:
    return WriterMutationAuthorization(
        capability_id=capability_id,
        execution_mode=execution_mode,
        validated_host=validated_host,
        validated_commit=validated_commit,
        authorization_or_permit_id=authorization_or_permit_id,
        _seal=_MUTATION_AUTH_SEAL,
    )


def require_writer_mutation_authorization(
    authorization: Any, capability_id: str
) -> WriterMutationAuthorization:
    """Fail-closed guard for a low-level mutation helper.

    Rejects a missing/None/plain-dict/unvalidated authorization before the first
    mutation and requires the exact capability.
    """
    if not isinstance(authorization, WriterMutationAuthorization):
        raise AuthorizationDenied(
            capability_id,
            ExecutionMode.READ_ONLY,
            ["missing or invalid WriterMutationAuthorization context"],
        )
    return authorization.require_capability(capability_id)


@dataclass(frozen=True)
class AuthorizationDecision:
    allowed: bool
    capability_id: str
    mode: ExecutionMode
    reasons: list[str] = field(default_factory=list)
    authorization: WriterMutationAuthorization | None = None

    def raise_if_denied(self) -> "AuthorizationDecision":
        if not self.allowed:
            raise AuthorizationDenied(self.capability_id, self.mode, self.reasons)
        return self


# ---------------------------------------------------------------------------
# Low-level helpers.
# ---------------------------------------------------------------------------

def _json_schema_errors(payload: Any, schema_path: Path) -> list[str]:
    """Deterministic JSON Schema validation. Fail closed on any import/parse error."""
    try:
        import jsonschema  # local import so absence fails closed here, not at module import
        from jsonschema import Draft202012Validator
    except Exception as exc:  # noqa: BLE001 - fail closed if validator unavailable.
        return [f"jsonschema validator unavailable: {exc}"]

    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [f"schema file missing: {schema_path}"]
    except json.JSONDecodeError as exc:
        return [f"schema file invalid JSON: {schema_path}: {exc}"]

    try:
        validator = Draft202012Validator(schema)
    except Exception as exc:  # noqa: BLE001
        return [f"schema is not a valid JSON Schema: {schema_path}: {exc}"]

    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.absolute_path))
    return [
        "schema violation at {path}: {message}".format(
            path="/".join(str(p) for p in err.absolute_path) or "<root>",
            message=err.message,
        )
        for err in errors
    ]


def _read_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, f"file missing: {path}"
    except OSError as exc:
        return None, f"file unreadable: {path}: {exc}"
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {path}: {exc}"
    if not isinstance(payload, dict):
        return None, f"root must be a JSON object: {path}"
    return payload, None


def _git(checkout_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(checkout_path), *args],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def _utc_literal_to_datetime(value: str) -> datetime | None:
    """Parse a canonical literal-UTC timestamp (must end in literal ``Z``)."""
    if not isinstance(value, str) or not _UTC_LITERAL_Z_RE.match(value):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Registry / authorization / permit loading and validation.
# ---------------------------------------------------------------------------

def load_and_validate_registry(
    registry_path: Path,
    schema_path: Path,
    *,
    repo_root: Path,
) -> LoadResult:
    """Load the registry, JSON-Schema validate it, then run full semantic validation.

    A schema-invalid or semantically invalid registry always fails closed.
    """
    payload, read_error = _read_json(registry_path)
    if read_error is not None:
        return LoadResult(None, [read_error])

    schema_errors = _json_schema_errors(payload, schema_path)
    if schema_errors:
        return LoadResult(None, [f"registry {e}" for e in schema_errors])

    try:
        semantic = validate_registry_payload(payload, repo_root=repo_root)
    except RegistryValidationError as exc:
        return LoadResult(None, [f"registry semantic load error: {exc}"])
    if not semantic.ok:
        return LoadResult(None, [f"registry semantic invalid: {e}" for e in semantic.errors])
    return LoadResult(payload, [])


def load_and_validate_authorization(
    authorization_path: Path,
    schema_path: Path,
) -> LoadResult:
    payload, read_error = _read_json(authorization_path)
    if read_error is not None:
        return LoadResult(None, [f"authorization {read_error}"])
    schema_errors = _json_schema_errors(payload, schema_path)
    if schema_errors:
        return LoadResult(None, [f"authorization {e}" for e in schema_errors])
    return LoadResult(payload, [])


def load_and_validate_acceptance_permit(
    permit_path: Path,
    schema_path: Path,
) -> LoadResult:
    payload, read_error = _read_json(permit_path)
    if read_error is not None:
        return LoadResult(None, [f"acceptance permit {read_error}"])
    schema_errors = _json_schema_errors(payload, schema_path)
    if schema_errors:
        return LoadResult(None, [f"acceptance permit {e}" for e in schema_errors])
    return LoadResult(payload, [])


def capability_entry(registry: dict[str, Any], capability_id: str) -> dict[str, Any] | None:
    for cap in registry.get("capabilities", []):
        if isinstance(cap, dict) and cap.get("capability_id") == capability_id:
            return cap
    return None


# ---------------------------------------------------------------------------
# Checkout identity.
# ---------------------------------------------------------------------------

def _is_untracked_allowed(rel_path: str, allowed_untracked_paths: set[str]) -> bool:
    if rel_path not in allowed_untracked_paths:
        return False
    if any(rel_path.startswith(prefix) for prefix in PROTECTED_UNTRACKED_PREFIXES):
        return False
    if rel_path.endswith(PROTECTED_UNTRACKED_SUFFIXES):
        return False
    return True


def verify_checkout_identity(
    *,
    checkout_path: Path,
    expected_commit: str,
    expected_working_directory: Path | str | None = None,
    allowed_untracked_paths: set[str] | None = None,
) -> list[str]:
    """Prove the exact deployed checkout. Returns a deterministic list of errors.

    Verifies HEAD == expected commit, no staged/unstaged tracked changes,
    canonical realpath match, non-detached HEAD, no linked worktree, and a
    strict untracked-file policy.
    """
    errors: list[str] = []
    allowed = set(allowed_untracked_paths or set())

    if not _COMMIT_RE.match(str(expected_commit)):
        errors.append("expected commit is not a full 40-character sha")

    head = _git(checkout_path, "rev-parse", "--verify", "HEAD")
    if head.returncode != 0:
        errors.append("checkout HEAD could not be resolved")
        return errors
    actual_commit = head.stdout.strip()
    if actual_commit != str(expected_commit):
        errors.append(f"HEAD {actual_commit} does not match expected commit {expected_commit}")

    symbolic = _git(checkout_path, "symbolic-ref", "-q", "HEAD")
    if symbolic.returncode != 0:
        errors.append("checkout HEAD is detached")

    git_dir = _git(checkout_path, "rev-parse", "--git-dir")
    if git_dir.returncode != 0:
        errors.append("checkout is not a git working tree")
    elif "/worktrees/" in git_dir.stdout.strip().replace("\\", "/"):
        errors.append("checkout is a linked worktree, not the canonical checkout")

    if _git(checkout_path, "diff", "--cached", "--quiet").returncode != 0:
        errors.append("checkout has staged tracked changes")
    if _git(checkout_path, "diff", "--quiet").returncode != 0:
        errors.append("checkout has unstaged tracked changes")

    untracked = _git(checkout_path, "ls-files", "--others", "--exclude-standard")
    if untracked.returncode == 0:
        for rel in (line.strip() for line in untracked.stdout.splitlines()):
            if not rel:
                continue
            if not _is_untracked_allowed(rel, allowed):
                errors.append(f"untracked file not permitted in checkout: {rel}")

    canonical = os.path.realpath(str(checkout_path))
    if expected_working_directory is not None:
        expected_real = os.path.realpath(str(expected_working_directory))
        if canonical != expected_real:
            errors.append(
                f"checkout realpath {canonical} does not match expected working directory {expected_real}"
            )
    if canonical != os.path.abspath(str(checkout_path)):
        # A symlinked checkout path is only acceptable when it resolves to the
        # explicitly expected working directory (checked above).
        if expected_working_directory is None:
            errors.append(f"checkout path is symlinked to {canonical}; expected working directory not provided")

    return errors


# ---------------------------------------------------------------------------
# Top-level authorization decision.
# ---------------------------------------------------------------------------

def _resolve_mode(mode: ExecutionMode | str | None) -> ExecutionMode:
    if isinstance(mode, ExecutionMode):
        return mode
    if mode is None:
        return ExecutionMode.READ_ONLY
    try:
        return ExecutionMode(str(mode).strip().upper())
    except ValueError:
        # Unknown mode fails closed against mutation.
        return ExecutionMode.READ_ONLY


def _verify_production(
    *,
    capability_id: str,
    service: str | None,
    cap: dict[str, Any],
    authorization: dict[str, Any],
    actual_host: str,
    checkout_path: Path,
    expected_working_directory: Path | str | None,
    allowed_untracked_paths: set[str],
) -> list[str]:
    reasons: list[str] = []
    identity = CAPABILITY_IDENTITY.get(capability_id)

    # Registry must itself authorize production for this capability.
    if cap.get("production_runtime_owner") == "UNASSIGNED":
        reasons.append("registry production_runtime_owner is UNASSIGNED")
    if cap.get("production_authorization_status") != "AUTHORIZED":
        reasons.append("registry production_authorization_status is not AUTHORIZED")
    if cap.get("runtime_lifecycle") not in ALLOWED_PRODUCTION_LIFECYCLES:
        reasons.append("registry runtime_lifecycle is not AUTHORIZED_INACTIVE or ACTIVE")
    if not str(cap.get("production_decision_evidence") or "").strip():
        reasons.append("registry production_decision_evidence is empty")

    # Authorization file must match the registry and the running host/checkout.
    if authorization.get("purpose") != "PRODUCTION":
        reasons.append("authorization purpose is not PRODUCTION")
    if authorization.get("capability_id") != capability_id:
        reasons.append("authorization capability_id mismatch")
    if authorization.get("capability_identity") != identity:
        reasons.append("authorization capability_identity mismatch")
    if service is not None and authorization.get("service") != service:
        reasons.append("authorization service mismatch")
    if authorization.get("service") != cap.get("systemd_unit"):
        reasons.append("authorization service does not match registry systemd_unit")
    if authorization.get("systemd_unit") != cap.get("systemd_unit"):
        reasons.append("authorization systemd_unit does not match registry systemd_unit")
    if authorization.get("authorized_host") != cap.get("production_runtime_owner"):
        reasons.append("authorization host does not match registry production_runtime_owner")
    if authorization.get("authorized_host") != actual_host:
        reasons.append("actual hostname does not match authorized host")
    if authorization.get("decision_evidence") != cap.get("production_decision_evidence"):
        reasons.append("authorization decision_evidence must match registry production_decision_evidence")
    if _utc_literal_to_datetime(str(authorization.get("authorized_at_utc"))) is None:
        reasons.append("authorization authorized_at_utc is not a valid RFC3339 UTC timestamp")

    expected_commit = str(authorization.get("authorized_commit", ""))
    reasons.extend(
        verify_checkout_identity(
            checkout_path=checkout_path,
            expected_commit=expected_commit,
            expected_working_directory=expected_working_directory,
            allowed_untracked_paths=allowed_untracked_paths,
        )
    )
    return reasons


def _verify_acceptance(
    *,
    capability_id: str,
    permit: dict[str, Any],
    actual_host: str,
    checkout_path: Path,
    expected_working_directory: Path | str | None,
    allowed_untracked_paths: set[str],
    now_utc: datetime,
) -> list[str]:
    reasons: list[str] = []
    identity = CAPABILITY_IDENTITY.get(capability_id)
    if permit.get("purpose") != "ACCEPTANCE":
        reasons.append("acceptance permit purpose is not ACCEPTANCE")
    if permit.get("capability_id") != capability_id:
        reasons.append("acceptance permit capability_id mismatch")
    if permit.get("capability_identity") != identity:
        reasons.append("acceptance permit capability_identity mismatch")
    if permit.get("acceptance_host") != actual_host:
        reasons.append("actual hostname does not match acceptance host")

    issued = _utc_literal_to_datetime(str(permit.get("issued_at_utc")))
    expiry = _utc_literal_to_datetime(str(permit.get("expiry_utc")))
    if issued is None:
        reasons.append("acceptance permit issued_at_utc is not valid RFC3339")
    if expiry is None:
        reasons.append("acceptance permit expiry_utc is not valid RFC3339")
    elif expiry <= now_utc:
        reasons.append("acceptance permit has expired")
    if issued is not None and expiry is not None and expiry <= issued:
        reasons.append("acceptance permit expiry is not after issue time")

    expected_commit = str(permit.get("authorized_commit", ""))
    reasons.extend(
        verify_checkout_identity(
            checkout_path=checkout_path,
            expected_commit=expected_commit,
            expected_working_directory=expected_working_directory,
            allowed_untracked_paths=allowed_untracked_paths,
        )
    )
    return reasons


def _validate_writer_file_security(path: Path, *, label: str) -> list[str]:
    """Deterministic filesystem-safety checks for an authorization/permit file.

    Rejects a symlink, a non-regular file, unsafe ownership (must be root or the
    invoking user), and group/world-writable permission bits.
    """
    reasons: list[str] = []
    if path.is_symlink():
        reasons.append(f"{label} must not be a symlink: {path}")
        return reasons
    if not path.is_file():
        reasons.append(f"{label} is not a regular file: {path}")
        return reasons
    try:
        info = path.stat()
    except OSError as exc:
        reasons.append(f"{label} is unreadable: {path}: {exc}")
        return reasons
    if info.st_uid not in (0, os.getuid()):
        reasons.append(f"{label} has unsafe ownership (uid={info.st_uid}): {path}")
    if info.st_mode & 0o022:
        reasons.append(f"{label} is group/world writable: {path}")
    return reasons


def _validate_acceptance_permit_path(path: Path, allowed_root: Path) -> list[str]:
    reasons = _validate_writer_file_security(path, label="acceptance permit")
    try:
        real = Path(os.path.realpath(str(path)))
        real_root = Path(os.path.realpath(str(allowed_root)))
        if real_root not in real.parents:
            reasons.append(
                f"acceptance permit must live under {allowed_root}: {path}"
            )
    except OSError as exc:
        reasons.append(f"acceptance permit path could not be resolved: {path}: {exc}")
    return reasons


def verify_writer_execution_authorization(
    *,
    capability_id: str,
    mode: ExecutionMode | str | None,
    repo_root: Path,
    checkout_path: Path,
    service: str | None = None,
    actual_host: str | None = None,
    registry_path: Path | None = None,
    registry_schema_path: Path | None = None,
    authorization_path: Path | None = None,
    authorization_schema_path: Path | None = None,
    acceptance_permit_path: Path | None = None,
    acceptance_schema_path: Path | None = None,
    acceptance_permit_root: Path | None = None,
    allowed_untracked_paths: set[str] | None = None,
    expected_working_directory: Path | str | None = None,
    now_utc: datetime | None = None,
) -> AuthorizationDecision:
    """Deterministic authorization decision shared by every enforcement layer."""
    resolved_mode = _resolve_mode(mode)
    host = (actual_host or platform.node()).strip()
    allowed = set(allowed_untracked_paths or set())
    now = now_utc or datetime.now(timezone.utc)

    if capability_id not in CAPABILITY_IDENTITY:
        return AuthorizationDecision(False, capability_id, resolved_mode, [f"unknown capability_id={capability_id}"])

    registry_path = registry_path or (repo_root / REPO_RELATIVE_REGISTRY)
    registry_schema_path = registry_schema_path or (repo_root / REPO_RELATIVE_REGISTRY_SCHEMA)
    authorization_schema_path = authorization_schema_path or (repo_root / REPO_RELATIVE_AUTHORIZATION_SCHEMA)
    acceptance_schema_path = acceptance_schema_path or (repo_root / REPO_RELATIVE_ACCEPTANCE_SCHEMA)

    # Registry must always validate (schema + semantics), in every mode.
    registry_result = load_and_validate_registry(registry_path, registry_schema_path, repo_root=repo_root)
    if not registry_result.ok:
        return AuthorizationDecision(False, capability_id, resolved_mode, registry_result.errors)
    registry = registry_result.payload or {}
    cap = capability_entry(registry, capability_id)
    if cap is None:
        return AuthorizationDecision(False, capability_id, resolved_mode, [f"capability not in registry: {capability_id}"])

    if resolved_mode is ExecutionMode.READ_ONLY:
        # A mutation boundary reached in READ_ONLY mode is a fail-closed condition:
        # read-only execution must not mutate.
        return AuthorizationDecision(
            False,
            capability_id,
            resolved_mode,
            ["READ_ONLY execution mode may not perform database or artifact mutation"],
        )

    if resolved_mode is ExecutionMode.PRODUCTION:
        # The production authorization path is registry-declared and is never
        # environment-overridable. Tests may inject an explicit path.
        guard = cap.get("authorization_guard") if isinstance(cap.get("authorization_guard"), dict) else {}
        registry_declared = Path(str(guard.get("authorization_file") or DEFAULT_AUTHORIZATION_FILE))
        resolved_authorization_path = authorization_path or registry_declared
        reasons = _validate_writer_file_security(resolved_authorization_path, label="production authorization file")
        if reasons:
            return AuthorizationDecision(False, capability_id, resolved_mode, reasons)
        auth_result = load_and_validate_authorization(resolved_authorization_path, authorization_schema_path)
        if not auth_result.ok:
            return AuthorizationDecision(False, capability_id, resolved_mode, auth_result.errors)
        payload = auth_result.payload or {}
        reasons = _verify_production(
            capability_id=capability_id,
            service=service,
            cap=cap,
            authorization=payload,
            actual_host=host,
            checkout_path=checkout_path,
            expected_working_directory=expected_working_directory,
            allowed_untracked_paths=allowed,
        )
        if reasons:
            return AuthorizationDecision(False, capability_id, resolved_mode, reasons)
        context = _mint_authorization(
            capability_id=capability_id,
            execution_mode=resolved_mode,
            validated_host=host,
            validated_commit=str(payload.get("authorized_commit", "")),
            authorization_or_permit_id=str(payload.get("authorization_id", "")),
        )
        return AuthorizationDecision(True, capability_id, resolved_mode, [], context)

    # ACCEPTANCE mode.
    if acceptance_permit_path is None:
        return AuthorizationDecision(
            False,
            capability_id,
            resolved_mode,
            ["ACCEPTANCE mode requires an acceptance permit path"],
        )
    permit_root = acceptance_permit_root or DEFAULT_ACCEPTANCE_PERMIT_ROOT
    reasons = _validate_acceptance_permit_path(Path(acceptance_permit_path), Path(permit_root))
    if reasons:
        return AuthorizationDecision(False, capability_id, resolved_mode, reasons)
    permit_result = load_and_validate_acceptance_permit(acceptance_permit_path, acceptance_schema_path)
    if not permit_result.ok:
        return AuthorizationDecision(False, capability_id, resolved_mode, permit_result.errors)
    permit_payload = permit_result.payload or {}
    reasons = _verify_acceptance(
        capability_id=capability_id,
        permit=permit_payload,
        actual_host=host,
        checkout_path=checkout_path,
        expected_working_directory=expected_working_directory,
        allowed_untracked_paths=allowed,
        now_utc=now,
    )
    if reasons:
        return AuthorizationDecision(False, capability_id, resolved_mode, reasons)
    context = _mint_authorization(
        capability_id=capability_id,
        execution_mode=resolved_mode,
        validated_host=host,
        validated_commit=str(permit_payload.get("authorized_commit", "")),
        authorization_or_permit_id=str(permit_payload.get("permit_id", "")),
    )
    return AuthorizationDecision(True, capability_id, resolved_mode, [], context)


# ---------------------------------------------------------------------------
# Convenience: the mandatory Python mutation-boundary gate.
# ---------------------------------------------------------------------------

def _env_allowed_untracked() -> set[str]:
    raw = os.environ.get(ENV_ALLOWED_UNTRACKED, "")
    return {token.strip() for token in raw.split(os.pathsep) if token.strip()} | {
        token.strip() for token in raw.split(",") if token.strip()
    }


def enforce_capability_write_authorization(
    capability_id: str,
    *,
    repo_root: Path | None = None,
    checkout_path: Path | None = None,
    mode: ExecutionMode | str | None = None,
    service: str | None = None,
    allowed_untracked_paths: set[str] | None = None,
) -> WriterMutationAuthorization:
    """Final mandatory authorization boundary, called immediately before a
    database write or artifact publication.

    Reads the execution mode from the environment (defaulting to READ_ONLY / fail
    closed). The production authorization path is registry-declared and never
    environment-overridable; an acceptance permit path may be supplied through
    the environment for ACCEPTANCE mode only. Raises ``AuthorizationDenied`` when
    authorization is not satisfied and otherwise returns a validated
    :class:`WriterMutationAuthorization`. A direct invocation cannot bypass this
    boundary.
    """
    root = Path(repo_root) if repo_root is not None else Path.cwd()
    checkout = Path(checkout_path) if checkout_path is not None else root
    resolved_mode = mode if mode is not None else os.environ.get(ENV_MODE)

    acceptance_permit_path = None
    env_permit = os.environ.get(ENV_ACCEPTANCE_PERMIT)
    if env_permit:
        acceptance_permit_path = Path(env_permit)

    allowed = set(allowed_untracked_paths or set()) | _env_allowed_untracked()

    decision = verify_writer_execution_authorization(
        capability_id=capability_id,
        mode=resolved_mode,
        repo_root=root,
        checkout_path=checkout,
        service=service,
        acceptance_permit_path=acceptance_permit_path,
        allowed_untracked_paths=allowed,
        expected_working_directory=root,
    )
    decision.raise_if_denied()
    assert decision.authorization is not None  # guaranteed on allowed decisions
    return decision.authorization


def require_capability_write_authorization(
    capability_id: str,
    *,
    repo_root: Path | None = None,
    checkout_path: Path | None = None,
    mode: ExecutionMode | str | None = None,
    service: str | None = None,
    allowed_untracked_paths: set[str] | None = None,
) -> WriterMutationAuthorization:
    """CLI-friendly mutation-boundary gate.

    Returns the validated :class:`WriterMutationAuthorization` on success. On
    denial prints deterministic fail-closed FAIL lines and raises
    ``SystemExit(3)`` so a writer ``main`` exits non-zero before mutating.
    """
    try:
        return enforce_capability_write_authorization(
            capability_id,
            repo_root=repo_root,
            checkout_path=checkout_path,
            mode=mode,
            service=service,
            allowed_untracked_paths=allowed_untracked_paths,
        )
    except AuthorizationDenied as exc:
        print(
            "FAILED writer_authorization=denied "
            f"capability={capability_id} mode={exc.mode.value} "
            "host_mutations=0 database_writes=0 writer_invocations=0"
        )
        for reason in exc.reasons:
            print(f"FAIL capability={capability_id} reason={reason}")
        raise SystemExit(3) from exc
