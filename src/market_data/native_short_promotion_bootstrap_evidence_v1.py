from __future__ import annotations

"""Canonical PROMOTE_SCOPE first-promotion bootstrap-evidence contract.

Boundary: native SHORT market-data, read-only, market-only, account-agnostic.
This module defines and evaluates evidence only. It performs no database
I/O, no mutation, no promotion, and no writer-capability authorization; it
never calls or wraps
``native_short_scope_administration_transaction_v1.execute_scope_administration``.
Its sole caller is that module's ``decide_administration``/
``plan_scope_administration``/``execute_scope_administration``, which use its
result only to narrow -- never widen beyond one exact, checked-in,
commit-bound scope -- the applicability of the existing
``PROMOTION_CONTRACT_MISSING`` global blocker for a PROMOTE_SCOPE decision.

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
second, independent, *pre*-authorization evidentiary path for the
``PROMOTION_CONTRACT_MISSING`` sub-check specifically, evaluated fresh for
every PROMOTE_SCOPE decision against the exact request being decided --
never a global "promotion allowed" toggle.

BOOTSTRAP MANIFEST
-------------------
A single, versioned, repository-owned JSON manifest,
``native_short_promotion_bootstrap_manifest_v1.json``, co-located with this
module. It authorizes **at most one** exact canonical scope (including
``symbol``) and is bound to one exact ``repository_commit_sha``. It ships
``accepted: false`` with null placeholders; setting it to ``accepted: true``
for a specific symbol requires its own reviewed repository change, naming the
exact symbol and commit, per
``docs/todo/native_short_multi_asset_rollout_contract_v1.md``.

Manifest fields (all required for evidence to ever accept):

- ``acceptance_schema_version``: must equal ``REQUIRED_MANIFEST_SCHEMA_VERSION``;
- ``bootstrap_contract_version``: must equal ``BOOTSTRAP_CONTRACT_VERSION``;
- ``bootstrap_contract_digest``: must equal the live
  ``compute_bootstrap_contract_digest()`` value;
- ``accepted``: must be the JSON literal ``true``;
- ``scope``: the exact six-part canonical scope key, including the one
  authorized ``symbol``;
- ``repository_commit_sha``: the exact 40-character lowercase-hex commit this
  bootstrap authorization is bound to -- a request from any other commit is
  rejected;
- ``approval_reference``: a non-empty pointer to the reviewed decision
  document that approved this exact symbol as the next canary.

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
symbol it cannot apply to any other scope either. No mutable "consumed" flag
is introduced or required; the existing immutable ledger already provides
consumption semantics. This module performs no such check itself (it has no
database access) -- the caller enforces it against the already-read scope
snapshot.

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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

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

# The versioned, repository-owned bootstrap manifest lives next to this
# module. It ships unaccepted; see module docstring.
DEFAULT_BOOTSTRAP_MANIFEST_PATH = Path(__file__).with_name(
    "native_short_promotion_bootstrap_manifest_v1.json"
)

REASON_MANIFEST_MISSING_OR_UNREADABLE = "MANIFEST_MISSING_OR_UNREADABLE"
REASON_MANIFEST_MALFORMED = "MANIFEST_MALFORMED"
REASON_MANIFEST_SCHEMA_VERSION_WRONG = "MANIFEST_SCHEMA_VERSION_WRONG"
REASON_MANIFEST_CONTRACT_VERSION_WRONG = "MANIFEST_CONTRACT_VERSION_WRONG"
REASON_MANIFEST_CONTRACT_DIGEST_MISMATCH = "MANIFEST_CONTRACT_DIGEST_MISMATCH"
REASON_MANIFEST_NOT_ACCEPTED = "MANIFEST_NOT_ACCEPTED"
REASON_MANIFEST_SCOPE_INVALID = "MANIFEST_SCOPE_INVALID"
REASON_MANIFEST_COMMIT_INVALID = "MANIFEST_COMMIT_INVALID"
REASON_MANIFEST_MISSING_APPROVAL_REFERENCE = "MANIFEST_MISSING_APPROVAL_REFERENCE"
REASON_SCOPE_MISMATCH = "SCOPE_MISMATCH"
REASON_COMMIT_MISMATCH = "COMMIT_MISMATCH"
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


@dataclass(frozen=True)
class BootstrapPromotionEvaluation:
    """Deterministic, read-only evaluation result. Never a decision to act."""

    accepted: bool
    reason: str
    symbol: str | None
    repository_commit_sha: str | None


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
    requested_repository_commit_sha: str,
    manifest_path: Path = DEFAULT_BOOTSTRAP_MANIFEST_PATH,
) -> BootstrapPromotionEvaluation:
    """Evaluate whether the checked-in bootstrap manifest authorizes exactly
    this requested scope from exactly this repository commit.

    Fail-closed: a missing/malformed/wrong-version/wrong-digest/unaccepted
    manifest, or one naming a different scope/symbol or a different commit,
    never accepts. Pure given its inputs; the manifest file read is the only
    I/O and it is read-only. This function makes no claim about whether the
    requested scope's *current database state* is eligible for the bootstrap
    exception (e.g. genuinely first-ever, no prior ledger row) -- that check
    belongs to the caller, which has the scope snapshot.
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

    commit_sha = raw.get("repository_commit_sha")
    if not isinstance(commit_sha, str) or _SHA_PATTERN.fullmatch(commit_sha) is None:
        return BootstrapPromotionEvaluation(
            False, REASON_MANIFEST_COMMIT_INVALID, symbol, None
        )

    approval_reference = raw.get("approval_reference")
    if not isinstance(approval_reference, str) or not approval_reference.strip():
        return BootstrapPromotionEvaluation(
            False, REASON_MANIFEST_MISSING_APPROVAL_REFERENCE, symbol, commit_sha
        )

    if dict(scope) != dict(requested_scope):
        return BootstrapPromotionEvaluation(
            False, REASON_SCOPE_MISMATCH, symbol, commit_sha
        )
    if commit_sha != requested_repository_commit_sha:
        return BootstrapPromotionEvaluation(
            False, REASON_COMMIT_MISMATCH, symbol, commit_sha
        )

    return BootstrapPromotionEvaluation(True, REASON_EVIDENCE_ACCEPTED, symbol, commit_sha)


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
    "REASON_MANIFEST_COMMIT_INVALID",
    "REASON_MANIFEST_MISSING_APPROVAL_REFERENCE",
    "REASON_SCOPE_MISMATCH",
    "REASON_COMMIT_MISMATCH",
    "REASON_EVIDENCE_ACCEPTED",
    "BootstrapPromotionEvaluation",
    "compute_bootstrap_contract_digest",
    "evaluate_promotion_bootstrap_evidence",
]
