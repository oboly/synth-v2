from __future__ import annotations

"""Canonical PROMOTE_SCOPE first-promotion bootstrap-evidence contract.

Boundary: native SHORT market-data, read-only, market-only, account-agnostic.
This module defines and evaluates evidence only. It performs no database
I/O, no mutation, no promotion, and no writer-capability authorization; it
never calls or wraps
``native_short_scope_administration_transaction_v1.execute_scope_administration``.
Its sole caller is that module's ``decide_administration``/
``plan_scope_administration``/``execute_scope_administration``, which use its
result only to narrow -- never widen beyond one exact, checked-in scope --
the applicability of a fixed, named subset of the existing global blockers
for a PROMOTE_SCOPE decision.

Why this module exists (the bootstrap circularity)
----------------------------------------------------
``native_short_promotion_acceptance_evidence_v1.evaluate_promotion_acceptance_evidence``
closes ``PROMOTION_CONTRACT_MISSING`` only by proving a **terminal, already
persisted, SUCCESS** ``native_short_scope_admin_operation_v1`` row for a
reviewed PROMOTE_SCOPE operation. That is correct evidence for the second and
every later promotion, but it is structurally circular for the very first
one: no such row can exist until a PROMOTE_SCOPE transaction has already
executed, and the existing gate
(``native_short_scope_administration_transaction_v1._APPLICABLE_GLOBAL_BLOCKERS_BY_OPERATION``)
correctly refuses to execute PROMOTE_SCOPE while ``PROMOTION_CONTRACT_MISSING``
is active. See
``docs/todo/native_short_multi_asset_rollout_contract_v1.md``
("Promotion-acceptance bootstrap circularity") for the full trace.

This module is the "distinct reviewed one-time exception procedure ...
specifically for that first controlled run" that document anticipates. It
does **not** touch, weaken, or duplicate the existing gate mechanism
(``_APPLICABLE_GLOBAL_BLOCKERS_BY_OPERATION`` /
``applicable_active_global_blockers`` / the ``GLOBAL_BLOCKERS_ACTIVE`` reject
path in ``decide_administration`` are all unchanged). It only supplies a
second, independent, *pre*-authorization evidentiary path evaluated fresh
for every PROMOTE_SCOPE decision against the exact request being decided --
never a global "promotion allowed" toggle.

Why this is NOT a repository-commit exact-match design
---------------------------------------------------------
An earlier revision of this module bound the manifest to one exact
``repository_commit_sha`` and required it to equal the checked-out
``HEAD`` at invocation time. That is unsound: a git commit object cannot
state its own hash inside its own tree (the hash is a pure function of the
tree's content, which would need to already contain the hash -- a fixed
point that is not achievable without brute-force hash-grinding). No finite
sequence of commits resolves this for a manifest that must be valid
starting from the exact commit that introduces it.

This revision separates two genuinely different concerns instead:

- **approval evidence identity** -- a deterministic digest
  (``compute_approval_evidence_digest``) over the immutable, normalized
  approval payload (``accepted``, the exact scope, ``approval_reference``,
  ``approved_at_utc``, the approved substantive implementation commit, and
  a hash of this module's own source file at approval time). This digest
  has no relationship to git commit hashing and is not self-referential:
  it is computed from fields the manifest also stores in plain form, and
  is recomputed fresh from those same fields (plus the *current* on-disk
  copy of this file) at every evaluation, so a manifest field or an
  implementation-file edit made after approval, without a matching digest
  update, fails closed (``MANIFEST_DIGEST_MISMATCH``).
- **deployed checkout authorization** -- unchanged, and still entirely the
  job of ``native_short_repository_source_identity_v1.verify_repository_commit_sha``
  and ``src.operations.writer_capability_authorization_v1``, both already
  required, unmodified, before any write. This module never re-checks
  ``HEAD`` equality.

If repository ancestry needs verifying at all, it is checked as a much
weaker, entirely non-circular property: the manifest's
``approved_implementation_commit`` (a fixed, already-existing, immutable
commit -- never the commit that introduces the manifest itself) must be an
*ancestor* of the current ``HEAD`` (``git merge-base --is-ancestor``), never
equal to it. Any real commit created after that one, on any branch that
contains it, satisfies this by construction; no further "pin" commit is
ever required.

BOOTSTRAP MANIFEST
-------------------
A single, versioned, repository-owned JSON manifest,
``native_short_promotion_bootstrap_manifest_v1.json``, co-located with this
module. It authorizes **at most one** exact canonical scope (including
``symbol``). It ships ``accepted: false`` with null placeholders; setting it
to ``accepted: true`` for a specific symbol requires its own reviewed
repository change, naming the exact symbol, per
``docs/todo/native_short_multi_asset_rollout_contract_v1.md``.

Manifest fields (all required for evidence to ever accept):

- ``acceptance_schema_version``: must equal ``REQUIRED_MANIFEST_SCHEMA_VERSION``;
- ``bootstrap_contract_version``: must equal ``BOOTSTRAP_CONTRACT_VERSION``;
- ``bootstrap_contract_digest``: must equal the live
  ``compute_bootstrap_contract_digest()`` value;
- ``accepted``: must be the JSON literal ``true``;
- ``scope``: the exact six-part canonical scope key, including the one
  authorized ``symbol``;
- ``approval_reference``: a non-empty pointer to the reviewed decision
  document that approved this exact symbol as the next canary;
- ``approved_at_utc``: canonical UTC ISO-8601 timestamp of the approval
  decision;
- ``approved_implementation_commit``: the exact 40-character lowercase-hex
  commit that introduced the reviewed bootstrap implementation this
  approval trusts -- an already-existing, ordinary historical commit, never
  the commit that introduces the manifest's own ``accepted: true`` state,
  and never compared against ``HEAD`` for equality (only, optionally, for
  ancestry -- see ``require_implementation_commit_ancestry``);
- ``approval_evidence_digest``: the value of
  ``compute_approval_evidence_digest`` over the six fields above (excluding
  itself) plus the current SHA-256 of this module's own source file,
  computed once at approval time and re-verified at every evaluation.

Single-use by construction, not by a mutable flag
---------------------------------------------------
This evidence is applied by the caller (see
``native_short_scope_administration_transaction_v1.decide_administration``)
**only** when the requested scope currently classifies ``NO_SCOPE`` (no
canonical scope row, no cadence row, no support event, and -- checked
defensively by the caller -- no administration-operation-ledger row at all
for that exact scope). Because a successful first promotion permanently
creates that scope's row and its ledger row, the exact same scope can never
classify ``NO_SCOPE`` again -- so this evidence cannot re-apply to authorize
a second promotion of the same scope, and because it is bound to one exact
symbol it cannot apply to any other scope either. No mutable "consumed"
flag is introduced or required; the existing immutable ledger already
provides consumption semantics. This module performs no such check itself
(it has no database access) -- the caller enforces it against the
already-read scope snapshot.

Safety markers:
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
"""

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from src.market_data.native_short_repository_source_identity_v1 import (
    REPOSITORY_ROOT,
)
from src.market_data.native_short_scope_administration_v1 import (
    NativeShortScopeAdministrationKey,
    NativeShortScopeAdministrationValidationError,
)


BOOTSTRAP_CONTRACT_VERSION = "native_short_promotion_bootstrap_v1"
REQUIRED_MANIFEST_SCHEMA_VERSION = "native_short_promotion_bootstrap_manifest_v1"

CANONICAL_SCOPE_FIXED_FIELDS: Mapping[str, str] = {
    "venue": "bitvavo",
    "quote_currency": "EUR",
    "fib_trading_horizon": "SHORT",
    "primary_interval": "4h",
    "supporting_interval": "1h",
}

_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_UTC_ISO_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")

# The versioned, repository-owned bootstrap manifest lives next to this
# module. It ships unaccepted; see module docstring.
DEFAULT_BOOTSTRAP_MANIFEST_PATH = Path(__file__).with_name(
    "native_short_promotion_bootstrap_manifest_v1.json"
)
# This module's own source file: its current SHA-256 is folded into the
# approval-evidence digest so an edit to the bootstrap gating/evidence
# implementation made after approval, without a corresponding re-approval,
# fails the digest check closed. Reading this fixed, already-known path is
# not circular: the hash is stored in a *different* file (the manifest),
# not inside this file's own content.
_THIS_MODULE_PATH = Path(__file__)

REASON_MANIFEST_MISSING_OR_UNREADABLE = "MANIFEST_MISSING_OR_UNREADABLE"
REASON_MANIFEST_MALFORMED = "MANIFEST_MALFORMED"
REASON_MANIFEST_SCHEMA_VERSION_WRONG = "MANIFEST_SCHEMA_VERSION_WRONG"
REASON_MANIFEST_CONTRACT_VERSION_WRONG = "MANIFEST_CONTRACT_VERSION_WRONG"
REASON_MANIFEST_CONTRACT_DIGEST_MISMATCH = "MANIFEST_CONTRACT_DIGEST_MISMATCH"
REASON_MANIFEST_NOT_ACCEPTED = "MANIFEST_NOT_ACCEPTED"
REASON_MANIFEST_SCOPE_INVALID = "MANIFEST_SCOPE_INVALID"
REASON_MANIFEST_APPROVED_AT_INVALID = "MANIFEST_APPROVED_AT_INVALID"
REASON_MANIFEST_IMPLEMENTATION_COMMIT_INVALID = "MANIFEST_IMPLEMENTATION_COMMIT_INVALID"
REASON_MANIFEST_MISSING_APPROVAL_REFERENCE = "MANIFEST_MISSING_APPROVAL_REFERENCE"
REASON_MANIFEST_DIGEST_MISMATCH = "MANIFEST_DIGEST_MISMATCH"
REASON_SCOPE_MISMATCH = "SCOPE_MISMATCH"
REASON_IMPLEMENTATION_COMMIT_NOT_ANCESTOR = "IMPLEMENTATION_COMMIT_NOT_ANCESTOR"
REASON_ANCESTRY_CHECK_UNAVAILABLE = "ANCESTRY_CHECK_UNAVAILABLE"
REASON_EVIDENCE_ACCEPTED = "EVIDENCE_ACCEPTED"


def _valid_symbol(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value.isascii()
        and value.isalnum()
        and value.isupper()
    )


def compute_bootstrap_contract_digest() -> str:
    """Deterministic SHA-256 digest of this contract's fixed invariants. A
    manifest's ``bootstrap_contract_digest`` must equal this value, so a
    contract change fails any manifest written against the old contract
    closed instead of silently reinterpreting it."""
    payload = {
        "contract_version": BOOTSTRAP_CONTRACT_VERSION,
        "canonical_scope_fixed_fields": dict(CANONICAL_SCOPE_FIXED_FIELDS),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def hash_implementation_file(path: Path = _THIS_MODULE_PATH) -> str:
    """SHA-256 of this module's own source file, read fresh from disk. Used
    only as one more input to ``compute_approval_evidence_digest`` -- never
    written into this same file, so this is an ordinary, non-circular
    integrity check (like verifying a download against a published
    checksum stored elsewhere)."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compute_approval_evidence_digest(
    *,
    accepted: bool,
    scope: Mapping[str, str],
    approval_reference: str,
    approved_at_utc: str,
    approved_implementation_commit: str,
    implementation_file_sha256: str,
) -> str:
    """Deterministic SHA-256 digest over the immutable, normalized approval
    payload. Pure function of its arguments; no I/O. This is the single
    evidence-identity anchor for one reviewed approval decision -- distinct
    from, and never compared against, any git commit hash."""
    payload = {
        "accepted": bool(accepted),
        "scope": dict(scope),
        "approval_reference": approval_reference,
        "approved_at_utc": approved_at_utc,
        "approved_implementation_commit": approved_implementation_commit,
        "implementation_file_sha256": implementation_file_sha256,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


AncestryChecker = Callable[[str], bool]


def _default_ancestry_checker(commit: str) -> bool:
    """Real git ancestry check: is ``commit`` an ancestor of (or equal to)
    the current ``HEAD``? Fails closed (returns ``False``) on any git or
    subprocess error -- an unavailable check is never treated as a passed
    check."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(REPOSITORY_ROOT), "merge-base", "--is-ancestor", commit, "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


@dataclass(frozen=True)
class BootstrapPromotionEvaluation:
    """Deterministic, read-only evaluation result. Never a decision to act."""

    accepted: bool
    reason: str
    symbol: str | None
    approved_implementation_commit: str | None


def _read_manifest(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def evaluate_promotion_bootstrap_evidence(
    *,
    requested_scope: Mapping[str, str],
    manifest_path: Path = DEFAULT_BOOTSTRAP_MANIFEST_PATH,
    require_implementation_commit_ancestry: bool = True,
    ancestry_checker: AncestryChecker = _default_ancestry_checker,
    implementation_file_path: Path = _THIS_MODULE_PATH,
) -> BootstrapPromotionEvaluation:
    """Evaluate whether the checked-in bootstrap manifest authorizes exactly
    this requested scope.

    Fail-closed: a missing/malformed/wrong-version/wrong-digest/unaccepted
    manifest, a naming mismatch, a tampered field or implementation file
    (approval-evidence digest mismatch), or (when
    ``require_implementation_commit_ancestry`` is true, the default) an
    approved implementation commit that is not an ancestor of the current
    checkout, never accepts.

    This function does **not** check deployed-checkout identity (``HEAD``
    equality) at all -- that remains the unmodified job of
    ``native_short_repository_source_identity_v1.verify_repository_commit_sha``
    and the writer-capability authorization boundary, both already required
    by the caller before any write. This function also makes no claim about
    whether the requested scope's *current database state* is eligible for
    the bootstrap exception (e.g. genuinely first-ever, no prior ledger
    row) -- that check belongs to the caller, which has the scope snapshot.
    """
    raw = _read_manifest(manifest_path)
    if raw is None:
        return BootstrapPromotionEvaluation(
            False, REASON_MANIFEST_MISSING_OR_UNREADABLE, None, None
        )
    if not isinstance(raw, Mapping):
        return BootstrapPromotionEvaluation(False, REASON_MANIFEST_MALFORMED, None, None)

    if raw.get("acceptance_schema_version") != REQUIRED_MANIFEST_SCHEMA_VERSION:
        return BootstrapPromotionEvaluation(
            False, REASON_MANIFEST_SCHEMA_VERSION_WRONG, None, None
        )
    if raw.get("bootstrap_contract_version") != BOOTSTRAP_CONTRACT_VERSION:
        return BootstrapPromotionEvaluation(
            False, REASON_MANIFEST_CONTRACT_VERSION_WRONG, None, None
        )
    if raw.get("bootstrap_contract_digest") != compute_bootstrap_contract_digest():
        return BootstrapPromotionEvaluation(
            False, REASON_MANIFEST_CONTRACT_DIGEST_MISMATCH, None, None
        )
    if raw.get("accepted") is not True:
        return BootstrapPromotionEvaluation(False, REASON_MANIFEST_NOT_ACCEPTED, None, None)

    scope = raw.get("scope")
    if not isinstance(scope, Mapping):
        return BootstrapPromotionEvaluation(False, REASON_MANIFEST_SCOPE_INVALID, None, None)
    for field, expected in CANONICAL_SCOPE_FIXED_FIELDS.items():
        if scope.get(field) != expected:
            return BootstrapPromotionEvaluation(
                False, REASON_MANIFEST_SCOPE_INVALID, None, None
            )
    symbol = scope.get("symbol")
    if not _valid_symbol(symbol):
        return BootstrapPromotionEvaluation(False, REASON_MANIFEST_SCOPE_INVALID, None, None)
    try:
        # Reuse the existing canonical key validator instead of duplicating
        # symbol/venue/quote/horizon/interval normalization rules.
        NativeShortScopeAdministrationKey(
            venue=str(scope.get("venue")),
            symbol=str(symbol),
            quote_currency=str(scope.get("quote_currency")),
            fib_trading_horizon=str(scope.get("fib_trading_horizon")),
            primary_interval=str(scope.get("primary_interval")),
            supporting_interval=str(scope.get("supporting_interval")),
        )
    except NativeShortScopeAdministrationValidationError:
        return BootstrapPromotionEvaluation(False, REASON_MANIFEST_SCOPE_INVALID, None, None)

    approval_reference = raw.get("approval_reference")
    if not isinstance(approval_reference, str) or not approval_reference.strip():
        return BootstrapPromotionEvaluation(
            False, REASON_MANIFEST_MISSING_APPROVAL_REFERENCE, symbol, None
        )

    approved_at_utc = raw.get("approved_at_utc")
    if not isinstance(approved_at_utc, str) or _UTC_ISO_PATTERN.match(approved_at_utc) is None:
        return BootstrapPromotionEvaluation(
            False, REASON_MANIFEST_APPROVED_AT_INVALID, symbol, None
        )

    approved_implementation_commit = raw.get("approved_implementation_commit")
    if (
        not isinstance(approved_implementation_commit, str)
        or _SHA_PATTERN.fullmatch(approved_implementation_commit) is None
    ):
        return BootstrapPromotionEvaluation(
            False, REASON_MANIFEST_IMPLEMENTATION_COMMIT_INVALID, symbol, None
        )

    declared_digest = raw.get("approval_evidence_digest")
    try:
        implementation_file_sha256 = hash_implementation_file(implementation_file_path)
    except OSError:
        return BootstrapPromotionEvaluation(
            False, REASON_MANIFEST_DIGEST_MISMATCH, symbol, approved_implementation_commit
        )
    recomputed_digest = compute_approval_evidence_digest(
        accepted=True,
        scope=scope,
        approval_reference=approval_reference,
        approved_at_utc=approved_at_utc,
        approved_implementation_commit=approved_implementation_commit,
        implementation_file_sha256=implementation_file_sha256,
    )
    if not isinstance(declared_digest, str) or declared_digest != recomputed_digest:
        return BootstrapPromotionEvaluation(
            False, REASON_MANIFEST_DIGEST_MISMATCH, symbol, approved_implementation_commit
        )

    if dict(scope) != dict(requested_scope):
        return BootstrapPromotionEvaluation(
            False, REASON_SCOPE_MISMATCH, symbol, approved_implementation_commit
        )

    if require_implementation_commit_ancestry:
        try:
            is_ancestor = ancestry_checker(approved_implementation_commit)
        except Exception:  # noqa: BLE001 - any ancestry-check failure fails closed.
            return BootstrapPromotionEvaluation(
                False,
                REASON_ANCESTRY_CHECK_UNAVAILABLE,
                symbol,
                approved_implementation_commit,
            )
        if not is_ancestor:
            return BootstrapPromotionEvaluation(
                False,
                REASON_IMPLEMENTATION_COMMIT_NOT_ANCESTOR,
                symbol,
                approved_implementation_commit,
            )

    return BootstrapPromotionEvaluation(
        True, REASON_EVIDENCE_ACCEPTED, symbol, approved_implementation_commit
    )


__all__ = [
    "BOOTSTRAP_CONTRACT_VERSION",
    "REQUIRED_MANIFEST_SCHEMA_VERSION",
    "CANONICAL_SCOPE_FIXED_FIELDS",
    "DEFAULT_BOOTSTRAP_MANIFEST_PATH",
    "REASON_MANIFEST_MISSING_OR_UNREADABLE",
    "REASON_MANIFEST_MALFORMED",
    "REASON_MANIFEST_SCHEMA_VERSION_WRONG",
    "REASON_MANIFEST_CONTRACT_VERSION_WRONG",
    "REASON_MANIFEST_CONTRACT_DIGEST_MISMATCH",
    "REASON_MANIFEST_NOT_ACCEPTED",
    "REASON_MANIFEST_SCOPE_INVALID",
    "REASON_MANIFEST_APPROVED_AT_INVALID",
    "REASON_MANIFEST_IMPLEMENTATION_COMMIT_INVALID",
    "REASON_MANIFEST_MISSING_APPROVAL_REFERENCE",
    "REASON_MANIFEST_DIGEST_MISMATCH",
    "REASON_SCOPE_MISMATCH",
    "REASON_IMPLEMENTATION_COMMIT_NOT_ANCESTOR",
    "REASON_ANCESTRY_CHECK_UNAVAILABLE",
    "REASON_EVIDENCE_ACCEPTED",
    "AncestryChecker",
    "BootstrapPromotionEvaluation",
    "compute_bootstrap_contract_digest",
    "compute_approval_evidence_digest",
    "hash_implementation_file",
    "evaluate_promotion_bootstrap_evidence",
]
