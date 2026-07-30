from __future__ import annotations

"""Canonical PROMOTE_SCOPE operational-acceptance evidence contract.

Boundary: native SHORT market-data, read-only, market-only, account-agnostic.
This module defines and evaluates evidence only; it never performs, requests,
or wraps a promotion transaction, and it never mutates any database or
repository state.

Design (kept explicit and separate, per the rollout contract):

- promotion contract definition   -> the constants in this module plus
                                      ``compute_promotion_contract_digest``
- controlled acceptance execution -> a separately reviewed, out-of-band
                                      invocation of
                                      ``native_short_scope_administration_transaction_v1``
                                      (PROMOTE_SCOPE), not this module
- persisted acceptance result     -> two independent, cross-checked sources
                                      that must agree, not one:
                                        1. the existing
                                           ``native_short_scope_admin_operation_v1``
                                           ledger row (proves the transaction
                                           executed and its terminal result);
                                        2. this module's versioned,
                                           repository-owned acceptance
                                           manifest (proves a human reviewed
                                           and explicitly accepted that exact
                                           result for that exact scope) --
                                           see ``ACCEPTANCE MANIFEST`` below;
- audit evaluation                -> ``evaluate_promotion_acceptance_evidence``,
                                      wired into
                                      ``native_short_multi_asset_audit_v1.evaluate_global_blockers``

Why two sources, not a bare Python constant: an operation-ledger row proves
only that *some* PROMOTE_SCOPE transaction executed and committed with a
given terminal result -- it does not by itself prove a human reviewed and
accepted that specific outcome for that specific scope as production
promotion. A bare hardcoded ``operation_uuid`` constant in Python is exactly
the stale-reference failure mode this contract must avoid (the same failure
already fixed once for writer provenance). Instead, reviewed acceptance is
represented by a separate, versioned, machine-readable JSON manifest
(``native_short_promotion_acceptance_manifest_v1.json``, co-located with this
module) that must itself be internally valid, bound to the exact current
contract version and contract digest, explicitly marked ``accepted: true``,
carry a reviewed-acceptance document reference, and cross-validate exactly
against the ledger row it names -- including recomputing the immutable
request digest from the manifest's own recorded request identity fields using
the existing canonical digest function in
``native_short_scope_administration_v1.NativeShortScopeAdministrationRequest``
(no duplicated hashing logic), and requiring that recomputed digest to equal
both the manifest's declared expected digest and the ledger row's persisted
``metadata_digest``.

ACCEPTANCE MANIFEST
--------------------
No existing canonical machine-readable *reviewed-acceptance* pattern exists
in this repository (operational acceptances to date are narrative markdown
under ``docs/ops/``; ``data/research/**/manifest_v1.json`` files are a
different, research-domain artifact with different ownership and semantics
and are not reused here). This module therefore introduces the smallest new
versioned evidence artifact, owned by native SHORT market-data and located
next to the code that defines its schema, rather than adding a new
ownership boundary elsewhere.

Manifest fields (all required for evidence to ever accept):

- ``acceptance_schema_version``: must equal ``REQUIRED_MANIFEST_SCHEMA_VERSION``;
- ``promotion_contract_version``: must equal ``PROMOTION_ACCEPTANCE_CONTRACT_VERSION``;
- ``promotion_contract_digest``: must equal the live
  ``compute_promotion_contract_digest()`` value (binds the manifest to the
  exact contract invariants; a contract change without a matching manifest
  update fails closed);
- ``accepted``: must be the JSON literal ``true``; anything else (including
  absence) fails closed -- this is the file's only ``accepted`` state and it
  ships ``false`` in this PR, so no production evidence can pass yet;
- ``operation_uuid``: the exact ledger operation this manifest reviews;
- ``scope``: the exact six-part canonical scope key, including the specific
  promoted ``symbol`` (not merely a well-formed ticker);
- ``expected_request_metadata_digest``: the reviewed expected SHA-256 digest;
- ``immutable_request_identity``: the recorded ``operation_type``,
  ``scope_key``, ``provenance``, and ``canonical_metadata`` used to
  *recompute* that digest via the existing contract's own digest function;
- ``reviewed_acceptance_reference``: a non-empty pointer to the reviewed
  operational-acceptance document.

Fail-closed rule: evidence closes ``PROMOTION_CONTRACT_MISSING`` only when
every one of the following holds:

- the manifest file exists, parses as JSON, and is a well-formed mapping;
- its schema version, contract version, and contract digest all match;
- it is explicitly ``accepted: true`` with a non-empty reviewed reference;
- its scope is the fixed canonical non-symbol fields plus a well-formed,
  specific symbol;
- its recorded immutable request identity recomputes (via the existing
  contract's own canonical digest function) to exactly its own declared
  ``expected_request_metadata_digest``;
- exactly one ``native_short_scope_admin_operation_v1`` row matches the
  manifest's ``operation_uuid`` (no ambiguity);
- that row is ``operation_type=PROMOTE_SCOPE``, terminal,
  ``result_class=SUCCESS`` with an accepted ``result_code``, carries the
  manifest's exact scope (including symbol) and the required administration
  ``schema_version``, and its persisted ``metadata_digest`` equals both the
  well-formed-hex check and the manifest's ``expected_request_metadata_digest``.

Any missing, malformed, incomplete, wrong-version, wrong-digest,
not-yet-accepted, ambiguous, stale, or unrelated evidence on either side
leaves the blocker active. As introduced by this PR, the shipped manifest is
unaccepted, so ``PROMOTION_CONTRACT_MISSING`` remains active. The required
later controlled operational acceptance procedure is documented in
``docs/todo/native_short_multi_asset_rollout_contract_v1.md``.

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
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.market_data.native_short_scope_administration_v1 import (
    NativeShortScopeAdministrationKey,
    NativeShortScopeAdministrationProvenance,
    NativeShortScopeAdministrationRequest,
    NativeShortScopeAdministrationValidationError,
)


PROMOTION_ACCEPTANCE_CONTRACT_VERSION = "native_short_promotion_acceptance_v1"
REQUIRED_MANIFEST_SCHEMA_VERSION = "native_short_promotion_acceptance_manifest_v1"

# Must equal the schema_version already used by
# native_short_scope_administration_transaction_v1 / run_native_short_scope_administration_v1
# for every administration operation (see tests/test_native_short_scope_administration_transaction_v1.py).
REQUIRED_ADMINISTRATION_SCHEMA_VERSION = "native_short_scope_administration_v1"

REQUIRED_OPERATION_TYPE = "PROMOTE_SCOPE"
ACCEPTED_RESULT_CLASS = "SUCCESS"
ACCEPTED_RESULT_CODES = ("PROMOTED_NEW_SCOPE", "PROMOTED_FROM_PRIOR_WITHDRAWAL")

CANONICAL_SCOPE_FIXED_FIELDS: Mapping[str, str] = {
    "venue": "bitvavo",
    "quote_currency": "EUR",
    "fib_trading_horizon": "SHORT",
    "primary_interval": "4h",
    "supporting_interval": "1h",
}

# The versioned, repository-owned acceptance manifest lives next to this
# module. It ships unaccepted; see module docstring.
DEFAULT_MANIFEST_PATH = Path(__file__).with_name(
    "native_short_promotion_acceptance_manifest_v1.json"
)

REASON_MANIFEST_MISSING_OR_UNREADABLE = "MANIFEST_MISSING_OR_UNREADABLE"
REASON_MANIFEST_MALFORMED = "MANIFEST_MALFORMED"
REASON_MANIFEST_SCHEMA_VERSION_WRONG = "MANIFEST_SCHEMA_VERSION_WRONG"
REASON_MANIFEST_CONTRACT_VERSION_WRONG = "MANIFEST_CONTRACT_VERSION_WRONG"
REASON_MANIFEST_CONTRACT_DIGEST_MISMATCH = "MANIFEST_CONTRACT_DIGEST_MISMATCH"
REASON_MANIFEST_NOT_ACCEPTED = "MANIFEST_NOT_ACCEPTED"
REASON_MANIFEST_SCOPE_INCOMPLETE = "MANIFEST_SCOPE_INCOMPLETE"
REASON_MANIFEST_MISSING_REVIEW_REFERENCE = "MANIFEST_MISSING_REVIEW_REFERENCE"
REASON_MANIFEST_REQUEST_IDENTITY_INVALID = "MANIFEST_REQUEST_IDENTITY_INVALID"
REASON_MANIFEST_DIGEST_RECOMPUTE_MISMATCH = "MANIFEST_DIGEST_RECOMPUTE_MISMATCH"
REASON_EVIDENCE_ABSENT = "EVIDENCE_ABSENT"
REASON_AMBIGUOUS_EVIDENCE = "AMBIGUOUS_EVIDENCE"
REASON_WRONG_OPERATION_TYPE = "WRONG_OPERATION_TYPE"
REASON_NOT_TERMINAL_SUCCESS = "NOT_TERMINAL_SUCCESS"
REASON_WRONG_SCOPE = "WRONG_SCOPE"
REASON_WRONG_SCHEMA_VERSION = "WRONG_SCHEMA_VERSION"
REASON_DIGEST_MISMATCH = "DIGEST_MISMATCH"
REASON_EVIDENCE_ACCEPTED = "EVIDENCE_ACCEPTED"

_HEX_DIGITS = frozenset("0123456789abcdef")


def _valid_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in _HEX_DIGITS for c in value)


def _valid_symbol(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and value.isascii() and value.isalnum() and value.isupper()


def compute_promotion_contract_digest() -> str:
    """Deterministic SHA-256 digest of this contract's fixed invariants.

    A manifest's ``promotion_contract_digest`` must equal this value. If the
    contract's operation type, accepted result codes, required schema
    version, or fixed canonical scope fields ever change, this digest changes
    too, and any manifest written against the old contract fails closed
    instead of silently being reinterpreted under the new one.
    """
    payload = {
        "contract_version": PROMOTION_ACCEPTANCE_CONTRACT_VERSION,
        "administration_schema_version": REQUIRED_ADMINISTRATION_SCHEMA_VERSION,
        "operation_type": REQUIRED_OPERATION_TYPE,
        "accepted_result_class": ACCEPTED_RESULT_CLASS,
        "accepted_result_codes": list(ACCEPTED_RESULT_CODES),
        "canonical_scope_fixed_fields": dict(CANONICAL_SCOPE_FIXED_FIELDS),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PromotionAcceptanceEvaluation:
    """Deterministic, read-only evaluation result. Never a decision to act."""

    accepted: bool
    reason: str
    operation_uuid: str | None
    scope_symbol: str | None


def _read_manifest(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _recompute_request_digest(identity: Mapping[str, Any]) -> str:
    """Recompute the immutable request digest using the existing contract's
    own canonical digest function -- never a duplicated hash implementation.
    Raises on any malformed input; callers must treat that as fail-closed.
    """
    scope_key_raw = identity["scope_key"]
    provenance_raw = identity["provenance"]
    requested_at_raw = str(provenance_raw["requested_at_utc"]).replace("Z", "+00:00")
    request = NativeShortScopeAdministrationRequest(
        operation_type=identity["operation_type"],
        scope_key=NativeShortScopeAdministrationKey(
            venue=scope_key_raw["venue"],
            symbol=scope_key_raw["symbol"],
            quote_currency=scope_key_raw["quote_currency"],
            fib_trading_horizon=scope_key_raw["fib_trading_horizon"],
            primary_interval=scope_key_raw["primary_interval"],
            supporting_interval=scope_key_raw["supporting_interval"],
        ),
        provenance=NativeShortScopeAdministrationProvenance(
            operation_uuid=provenance_raw["operation_uuid"],
            actor_type=provenance_raw["actor_type"],
            actor_id=provenance_raw["actor_id"],
            trigger_type=provenance_raw["trigger_type"],
            request_source=provenance_raw["request_source"],
            reason=provenance_raw["reason"],
            requested_at_utc=datetime.fromisoformat(requested_at_raw),
            repository_sha=provenance_raw["repository_sha"],
            schema_version=provenance_raw["schema_version"],
        ),
        canonical_metadata=identity.get("canonical_metadata", {}),
    )
    return request.request_digest


def _evaluate_manifest(
    raw: Any,
) -> tuple[PromotionAcceptanceEvaluation | None, Mapping[str, Any] | None, str | None]:
    """Validate the manifest in isolation. Returns ``(early_result, scope,
    expected_digest)``: ``early_result`` is set (and the caller must return
    it) unless the manifest is fully valid, accepted, and internally
    consistent, in which case ``scope``/``expected_digest`` are populated for
    cross-validation against the ledger.
    """
    if not isinstance(raw, Mapping):
        return PromotionAcceptanceEvaluation(False, REASON_MANIFEST_MALFORMED, None, None), None, None

    if raw.get("acceptance_schema_version") != REQUIRED_MANIFEST_SCHEMA_VERSION:
        return (
            PromotionAcceptanceEvaluation(False, REASON_MANIFEST_SCHEMA_VERSION_WRONG, None, None),
            None,
            None,
        )
    if raw.get("promotion_contract_version") != PROMOTION_ACCEPTANCE_CONTRACT_VERSION:
        return (
            PromotionAcceptanceEvaluation(False, REASON_MANIFEST_CONTRACT_VERSION_WRONG, None, None),
            None,
            None,
        )
    if raw.get("promotion_contract_digest") != compute_promotion_contract_digest():
        return (
            PromotionAcceptanceEvaluation(False, REASON_MANIFEST_CONTRACT_DIGEST_MISMATCH, None, None),
            None,
            None,
        )
    if raw.get("accepted") is not True:
        return (
            PromotionAcceptanceEvaluation(False, REASON_MANIFEST_NOT_ACCEPTED, None, None),
            None,
            None,
        )

    operation_uuid = raw.get("operation_uuid")
    if not isinstance(operation_uuid, str) or not operation_uuid:
        return (
            PromotionAcceptanceEvaluation(False, REASON_MANIFEST_MALFORMED, None, None),
            None,
            None,
        )

    scope = raw.get("scope")
    if not isinstance(scope, Mapping):
        return (
            PromotionAcceptanceEvaluation(False, REASON_MANIFEST_SCOPE_INCOMPLETE, operation_uuid, None),
            None,
            None,
        )
    for field, expected in CANONICAL_SCOPE_FIXED_FIELDS.items():
        if scope.get(field) != expected:
            return (
                PromotionAcceptanceEvaluation(
                    False, REASON_MANIFEST_SCOPE_INCOMPLETE, operation_uuid, None
                ),
                None,
                None,
            )
    symbol = scope.get("symbol")
    if not _valid_symbol(symbol):
        return (
            PromotionAcceptanceEvaluation(
                False, REASON_MANIFEST_SCOPE_INCOMPLETE, operation_uuid, None
            ),
            None,
            None,
        )

    reviewed_reference = raw.get("reviewed_acceptance_reference")
    if not isinstance(reviewed_reference, str) or not reviewed_reference.strip():
        return (
            PromotionAcceptanceEvaluation(
                False, REASON_MANIFEST_MISSING_REVIEW_REFERENCE, operation_uuid, symbol
            ),
            None,
            None,
        )

    expected_digest = raw.get("expected_request_metadata_digest")
    if not _valid_digest(expected_digest):
        return (
            PromotionAcceptanceEvaluation(
                False, REASON_MANIFEST_REQUEST_IDENTITY_INVALID, operation_uuid, symbol
            ),
            None,
            None,
        )

    identity = raw.get("immutable_request_identity")
    if not isinstance(identity, Mapping):
        return (
            PromotionAcceptanceEvaluation(
                False, REASON_MANIFEST_REQUEST_IDENTITY_INVALID, operation_uuid, symbol
            ),
            None,
            None,
        )
    try:
        recomputed = _recompute_request_digest(identity)
    except (
        NativeShortScopeAdministrationValidationError,
        KeyError,
        TypeError,
        ValueError,
    ):
        return (
            PromotionAcceptanceEvaluation(
                False, REASON_MANIFEST_REQUEST_IDENTITY_INVALID, operation_uuid, symbol
            ),
            None,
            None,
        )
    if recomputed != expected_digest:
        return (
            PromotionAcceptanceEvaluation(
                False, REASON_MANIFEST_DIGEST_RECOMPUTE_MISMATCH, operation_uuid, symbol
            ),
            None,
            None,
        )

    return None, {**scope, "operation_uuid": operation_uuid}, expected_digest


def evaluate_promotion_acceptance_evidence(
    operation_rows: Sequence[Mapping[str, Any]],
    *,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
) -> PromotionAcceptanceEvaluation:
    """Evaluate whether a canonical, reviewed PROMOTE_SCOPE operational
    acceptance closes PROMOTION_CONTRACT_MISSING.

    Fail-closed: a missing/malformed/wrong-version/wrong-digest/unaccepted
    manifest, or ledger evidence that is absent, ambiguous, wrong-type,
    non-terminal, wrong-scope, wrong-schema, or digest-mismatched, never
    accepts. This function is pure given its inputs, deterministic, and
    performs no mutation; the manifest file read is the only I/O and it is
    read-only.
    """
    raw = _read_manifest(manifest_path)
    if raw is None:
        return PromotionAcceptanceEvaluation(False, REASON_MANIFEST_MISSING_OR_UNREADABLE, None, None)

    early_result, scope, expected_digest = _evaluate_manifest(raw)
    if early_result is not None:
        return early_result
    assert scope is not None and expected_digest is not None

    operation_uuid = scope["operation_uuid"]
    symbol = scope["symbol"]

    matches = [
        row for row in operation_rows if str(row.get("operation_uuid")) == operation_uuid
    ]
    if not matches:
        return PromotionAcceptanceEvaluation(False, REASON_EVIDENCE_ABSENT, operation_uuid, symbol)
    if len(matches) > 1:
        return PromotionAcceptanceEvaluation(False, REASON_AMBIGUOUS_EVIDENCE, operation_uuid, symbol)

    row = matches[0]
    if str(row.get("operation_type")) != REQUIRED_OPERATION_TYPE:
        return PromotionAcceptanceEvaluation(False, REASON_WRONG_OPERATION_TYPE, operation_uuid, symbol)
    if row.get("completed_at_utc") is None:
        return PromotionAcceptanceEvaluation(False, REASON_NOT_TERMINAL_SUCCESS, operation_uuid, symbol)
    if (
        str(row.get("result_class")) != ACCEPTED_RESULT_CLASS
        or str(row.get("result_code")) not in ACCEPTED_RESULT_CODES
    ):
        return PromotionAcceptanceEvaluation(False, REASON_NOT_TERMINAL_SUCCESS, operation_uuid, symbol)
    for field, expected in CANONICAL_SCOPE_FIXED_FIELDS.items():
        if str(row.get(field)) != expected:
            return PromotionAcceptanceEvaluation(False, REASON_WRONG_SCOPE, operation_uuid, symbol)
    if str(row.get("symbol")) != symbol:
        return PromotionAcceptanceEvaluation(False, REASON_WRONG_SCOPE, operation_uuid, symbol)
    if str(row.get("schema_version")) != REQUIRED_ADMINISTRATION_SCHEMA_VERSION:
        return PromotionAcceptanceEvaluation(False, REASON_WRONG_SCHEMA_VERSION, operation_uuid, symbol)
    ledger_digest = row.get("metadata_digest")
    if not _valid_digest(ledger_digest) or str(ledger_digest) != expected_digest:
        return PromotionAcceptanceEvaluation(False, REASON_DIGEST_MISMATCH, operation_uuid, symbol)

    return PromotionAcceptanceEvaluation(True, REASON_EVIDENCE_ACCEPTED, operation_uuid, symbol)


__all__ = [
    "PROMOTION_ACCEPTANCE_CONTRACT_VERSION",
    "REQUIRED_MANIFEST_SCHEMA_VERSION",
    "REQUIRED_ADMINISTRATION_SCHEMA_VERSION",
    "REQUIRED_OPERATION_TYPE",
    "ACCEPTED_RESULT_CLASS",
    "ACCEPTED_RESULT_CODES",
    "CANONICAL_SCOPE_FIXED_FIELDS",
    "DEFAULT_MANIFEST_PATH",
    "REASON_MANIFEST_MISSING_OR_UNREADABLE",
    "REASON_MANIFEST_MALFORMED",
    "REASON_MANIFEST_SCHEMA_VERSION_WRONG",
    "REASON_MANIFEST_CONTRACT_VERSION_WRONG",
    "REASON_MANIFEST_CONTRACT_DIGEST_MISMATCH",
    "REASON_MANIFEST_NOT_ACCEPTED",
    "REASON_MANIFEST_SCOPE_INCOMPLETE",
    "REASON_MANIFEST_MISSING_REVIEW_REFERENCE",
    "REASON_MANIFEST_REQUEST_IDENTITY_INVALID",
    "REASON_MANIFEST_DIGEST_RECOMPUTE_MISMATCH",
    "REASON_EVIDENCE_ABSENT",
    "REASON_AMBIGUOUS_EVIDENCE",
    "REASON_WRONG_OPERATION_TYPE",
    "REASON_NOT_TERMINAL_SUCCESS",
    "REASON_WRONG_SCOPE",
    "REASON_WRONG_SCHEMA_VERSION",
    "REASON_DIGEST_MISMATCH",
    "REASON_EVIDENCE_ACCEPTED",
    "PromotionAcceptanceEvaluation",
    "compute_promotion_contract_digest",
    "evaluate_promotion_acceptance_evidence",
]
