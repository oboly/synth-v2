from __future__ import annotations

"""Canonical PROMOTE_SCOPE first-promotion bootstrap-evidence contract.

Boundary: native SHORT market-data, read-only, market-only, account-agnostic.
This module defines and evaluates evidence only. It performs no database
I/O, no mutation, no promotion, and no writer-capability authorization; it
never calls or wraps
``native_short_scope_administration_transaction_v1.execute_scope_administration``.
Its sole caller is that module's ``decide_administration``/
``plan_scope_administration``/``execute_scope_administration``, which use its
result only to narrow -- never widen beyond one exact, checked-in, matched
scope -- the applicability of a fixed, named subset of the existing global
blockers for a PROMOTE_SCOPE decision.

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
specifically for that first controlled run" that document anticipates,
applied independently to each explicitly reviewed scope. It does **not**
touch, weaken, or duplicate the existing gate mechanism
(``_APPLICABLE_GLOBAL_BLOCKERS_BY_OPERATION`` /
``applicable_active_global_blockers`` / the ``GLOBAL_BLOCKERS_ACTIVE`` reject
path in ``decide_administration`` are all unchanged). It only supplies a
second, independent, *pre*-authorization evidentiary path evaluated fresh
for every PROMOTE_SCOPE decision against the exact request being decided --
never a global "promotion allowed" toggle, and never a wildcard.

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
weaker, entirely non-circular property: each entry's
``approved_implementation_commit`` (a fixed, already-existing, immutable
commit -- never the commit that introduces that entry itself) must be an
*ancestor* of the current ``HEAD`` (``git merge-base --is-ancestor``), never
equal to it. Any real commit created after that one, on any branch that
contains it, satisfies this by construction; no further "pin" commit is
ever required.

BOOTSTRAP MANIFEST (v2: a reviewed list of independently-evidenced entries)
----------------------------------------------------------------------------
A single, versioned, repository-owned JSON manifest,
``native_short_promotion_bootstrap_manifest_v1.json``, co-located with this
module. Its top-level shape is a fixed contract-identity envelope plus an
``entries`` list. Each entry authorizes **exactly one** exact canonical
scope (including ``symbol``) -- there is no wildcard entry and no field that
can match more than one scope. Adding a new approved scope means appending a
new, independently reviewed, independently digested entry naming that exact
symbol; it never widens or reinterprets an existing entry.

Top-level fields (shared contract identity, apply to the whole manifest):

- ``acceptance_schema_version``: must equal ``REQUIRED_MANIFEST_SCHEMA_VERSION``
  (``native_short_promotion_bootstrap_manifest_v2`` -- this is a breaking
  structural migration from the v1 single-scope object, so the version is
  bumped rather than silently reinterpreting an old-shaped file);
- ``bootstrap_contract_version`` / ``bootstrap_contract_digest``: must equal
  ``BOOTSTRAP_CONTRACT_VERSION`` / the live ``compute_bootstrap_contract_digest()``
  value (unchanged contract invariants; binds every entry to the same fixed
  canonical scope fields);
- ``entries``: a non-empty JSON array. Every element must be a well-formed
  entry (see below); the manifest is malformed as a whole if any element is
  not. No two entries may declare the same exact six-part canonical scope --
  a duplicate/reused scope key across entries is a manifest-integrity defect
  and fails the *entire* manifest read closed
  (``MANIFEST_DUPLICATE_SCOPE_ENTRIES``), before any entry is matched or
  evaluated, so a malformed or tampered manifest can never be resolved by
  "picking" one of two conflicting entries for the same scope.

Per-entry fields (independent evidence per scope; all required for that
entry to ever accept):

- ``accepted``: must be the JSON literal ``true`` for this exact entry;
- ``scope``: the exact six-part canonical scope key, including the one
  symbol this entry authorizes;
- ``approval_reference``: a non-empty pointer to the reviewed decision
  document that approved this exact symbol as a canary;
- ``approved_at_utc``: canonical UTC ISO-8601 timestamp of the approval
  decision;
- ``approved_implementation_commit``: the exact 40-character lowercase-hex
  commit that introduced the reviewed bootstrap implementation this
  specific approval trusts -- an already-existing, ordinary historical
  commit, never the commit that introduces this entry's own ``accepted:
  true`` state, and never compared against ``HEAD`` for equality (only,
  optionally, for ancestry -- see ``require_implementation_commit_ancestry``);
- ``approval_evidence_digest``: the value of ``compute_approval_evidence_digest``
  over this entry's own five fields above (excluding itself) plus the
  current SHA-256 of this module's own source file, computed once at
  approval time and re-verified, per entry, at every evaluation.

Evaluation matches the caller's ``requested_scope`` against exactly one
entry's ``scope`` (exact dict equality on all six fields); every other
entry is irrelevant to that decision. A request whose scope matches no
entry, or whose matched entry fails any of its own independent checks,
never accepts -- evidence for one approved scope never leaks into, weakens,
or substitutes for any other scope's evaluation.

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
a second promotion of the same scope, and because each entry is bound to one
exact symbol it cannot apply to any other scope either. No mutable
"consumed" flag is introduced or required; the existing immutable ledger
already provides consumption semantics. This module performs no such check
itself (it has no database access) -- the caller enforces it against the
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
from typing import Any, Callable, Mapping, Sequence

from src.market_data.native_short_repository_source_identity_v1 import (
    REPOSITORY_ROOT,
)
from src.market_data.native_short_scope_administration_v1 import (
    NativeShortScopeAdministrationKey,
    NativeShortScopeAdministrationValidationError,
)


BOOTSTRAP_CONTRACT_VERSION = "native_short_promotion_bootstrap_v1"
REQUIRED_MANIFEST_SCHEMA_VERSION = "native_short_promotion_bootstrap_manifest_v2"

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
# module. It ships with a reviewed list of explicit, independently
# evidenced entries; see module docstring.
DEFAULT_BOOTSTRAP_MANIFEST_PATH = Path(__file__).with_name(
    "native_short_promotion_bootstrap_manifest_v1.json"
)
# This module's own source file: its current SHA-256 is folded into each
# entry's approval-evidence digest so an edit to the bootstrap gating/
# evidence implementation made after approval, without a corresponding
# re-approval of every entry, fails the digest check closed. Reading this
# fixed, already-known path is not circular: the hash is stored in a
# *different* file (the manifest), not inside this file's own content.
_THIS_MODULE_PATH = Path(__file__)

REASON_MANIFEST_MISSING_OR_UNREADABLE = "MANIFEST_MISSING_OR_UNREADABLE"
REASON_MANIFEST_MALFORMED = "MANIFEST_MALFORMED"
REASON_MANIFEST_SCHEMA_VERSION_WRONG = "MANIFEST_SCHEMA_VERSION_WRONG"
REASON_MANIFEST_CONTRACT_VERSION_WRONG = "MANIFEST_CONTRACT_VERSION_WRONG"
REASON_MANIFEST_CONTRACT_DIGEST_MISMATCH = "MANIFEST_CONTRACT_DIGEST_MISMATCH"
REASON_MANIFEST_DUPLICATE_SCOPE_ENTRIES = "MANIFEST_DUPLICATE_SCOPE_ENTRIES"
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
    """Deterministic SHA-256 digest over one entry's immutable, normalized
    approval payload. Pure function of its arguments; no I/O. This is the
    per-scope evidence-identity anchor for one reviewed approval decision --
    distinct from, and never compared against, any git commit hash."""
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


def _raw_scope_symbol(scope: Any) -> str | None:
    """The raw, unvalidated ``symbol`` an entry's declared ``scope`` names,
    used only for entry *matching* and duplicate detection -- deliberately
    not full structural validation, so a request naming the exact same
    symbol a malformed manifest entry declares is still routed to that
    entry for full per-entry validation (see ``_evaluate_entry``), rather
    than being silently treated as "no matching entry" and reported as a
    less specific ``SCOPE_MISMATCH`` instead of the real defect."""
    if not isinstance(scope, Mapping):
        return None
    symbol = scope.get("symbol")
    return symbol if isinstance(symbol, str) and symbol else None


def _validated_scope_key(scope: Any) -> dict[str, str] | None:
    """Return a normalized scope dict if ``scope`` is a well-formed exact
    canonical scope (fixed fields plus a well-formed upper-case symbol),
    else ``None``. Reuses the existing canonical key validator instead of
    duplicating symbol/venue/quote/horizon/interval normalization rules."""
    if not isinstance(scope, Mapping):
        return None
    for field, expected in CANONICAL_SCOPE_FIXED_FIELDS.items():
        if scope.get(field) != expected:
            return None
    symbol = scope.get("symbol")
    if not _valid_symbol(symbol):
        return None
    try:
        NativeShortScopeAdministrationKey(
            venue=str(scope.get("venue")),
            symbol=str(symbol),
            quote_currency=str(scope.get("quote_currency")),
            fib_trading_horizon=str(scope.get("fib_trading_horizon")),
            primary_interval=str(scope.get("primary_interval")),
            supporting_interval=str(scope.get("supporting_interval")),
        )
    except NativeShortScopeAdministrationValidationError:
        return None
    return dict(scope)


def _evaluate_entry(
    entry: Mapping[str, Any],
    *,
    requested_scope: Mapping[str, str],
    require_implementation_commit_ancestry: bool,
    ancestry_checker: AncestryChecker,
    implementation_file_path: Path,
) -> BootstrapPromotionEvaluation:
    """Evaluate one already scope-matched manifest entry in full isolation.
    Every other entry in the manifest is irrelevant to this result."""
    scope = _validated_scope_key(entry.get("scope"))
    symbol = None if scope is None else scope["symbol"]

    if scope is None:
        return BootstrapPromotionEvaluation(False, REASON_MANIFEST_SCOPE_INVALID, None, None)

    approval_reference = entry.get("approval_reference")
    if not isinstance(approval_reference, str) or not approval_reference.strip():
        return BootstrapPromotionEvaluation(
            False, REASON_MANIFEST_MISSING_APPROVAL_REFERENCE, symbol, None
        )

    approved_at_utc = entry.get("approved_at_utc")
    if not isinstance(approved_at_utc, str) or _UTC_ISO_PATTERN.match(approved_at_utc) is None:
        return BootstrapPromotionEvaluation(
            False, REASON_MANIFEST_APPROVED_AT_INVALID, symbol, None
        )

    approved_implementation_commit = entry.get("approved_implementation_commit")
    if (
        not isinstance(approved_implementation_commit, str)
        or _SHA_PATTERN.fullmatch(approved_implementation_commit) is None
    ):
        return BootstrapPromotionEvaluation(
            False, REASON_MANIFEST_IMPLEMENTATION_COMMIT_INVALID, symbol, None
        )

    if entry.get("accepted") is not True:
        return BootstrapPromotionEvaluation(
            False, REASON_MANIFEST_NOT_ACCEPTED, symbol, approved_implementation_commit
        )

    declared_digest = entry.get("approval_evidence_digest")
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

    if scope != dict(requested_scope):
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


def evaluate_promotion_bootstrap_evidence(
    *,
    requested_scope: Mapping[str, str],
    manifest_path: Path = DEFAULT_BOOTSTRAP_MANIFEST_PATH,
    require_implementation_commit_ancestry: bool = True,
    ancestry_checker: AncestryChecker = _default_ancestry_checker,
    implementation_file_path: Path = _THIS_MODULE_PATH,
) -> BootstrapPromotionEvaluation:
    """Evaluate whether the checked-in bootstrap manifest authorizes exactly
    this requested scope, via its own independently-evidenced entry.

    Fail-closed: a missing/malformed/wrong-version/wrong-digest manifest, a
    manifest with two entries naming the same scope, no entry matching the
    requested scope, or a matched entry that is unaccepted, tampered
    (approval-evidence digest mismatch), or (when
    ``require_implementation_commit_ancestry`` is true, the default) names
    an approved implementation commit that is not an ancestor of the current
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

    entries = raw.get("entries")
    if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)) or not entries:
        return BootstrapPromotionEvaluation(False, REASON_MANIFEST_MALFORMED, None, None)
    if not all(isinstance(entry, Mapping) for entry in entries):
        return BootstrapPromotionEvaluation(False, REASON_MANIFEST_MALFORMED, None, None)

    # No two entries may declare the same raw symbol (this manifest's fixed
    # venue/quote/horizon/interval fields are shared across every entry by
    # contract, so the symbol is the real uniqueness dimension). Checked
    # over every entry with an extractable raw symbol regardless of its own
    # well-formed/accepted state, so a tampered or duplicated manifest can
    # never be resolved by silently picking one of two conflicting entries
    # for the same symbol.
    seen_symbols: set[str] = set()
    for entry in entries:
        raw_symbol = _raw_scope_symbol(entry.get("scope"))
        if raw_symbol is None:
            continue
        if raw_symbol in seen_symbols:
            return BootstrapPromotionEvaluation(
                False, REASON_MANIFEST_DUPLICATE_SCOPE_ENTRIES, None, None
            )
        seen_symbols.add(raw_symbol)

    requested_normalized = dict(requested_scope)
    requested_symbol = _raw_scope_symbol(requested_normalized)
    matches = (
        []
        if requested_symbol is None
        else [
            entry
            for entry in entries
            if _raw_scope_symbol(entry.get("scope")) == requested_symbol
        ]
    )
    if not matches:
        return BootstrapPromotionEvaluation(False, REASON_SCOPE_MISMATCH, None, None)
    # Duplicate-scope detection above guarantees at most one match reaches
    # here; this remains a defensive, never-relied-upon-alone second guard.
    if len(matches) > 1:
        return BootstrapPromotionEvaluation(
            False, REASON_MANIFEST_DUPLICATE_SCOPE_ENTRIES, None, None
        )

    return _evaluate_entry(
        matches[0],
        requested_scope=requested_normalized,
        require_implementation_commit_ancestry=require_implementation_commit_ancestry,
        ancestry_checker=ancestry_checker,
        implementation_file_path=implementation_file_path,
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
    "REASON_MANIFEST_DUPLICATE_SCOPE_ENTRIES",
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
