from __future__ import annotations

"""Canonical PROMOTE_SCOPE operational-acceptance evidence contract.

Boundary: native SHORT market-data, read-only, market-only, account-agnostic.
This module defines and evaluates evidence only; it never performs, requests,
or wraps a promotion transaction, and it never mutates any database state.

Design (kept explicit and separate, per the rollout contract):

- promotion contract definition           -> this module's constants
- controlled acceptance execution         -> a separately reviewed, out-of-band
                                              invocation of
                                              ``native_short_scope_administration_transaction_v1``
                                              (PROMOTE_SCOPE), not this module
- persisted acceptance result             -> the existing
                                              ``native_short_scope_admin_operation_v1``
                                              ledger row for that operation
- audit evaluation                        -> ``evaluate_promotion_acceptance_evidence``,
                                              wired into
                                              ``native_short_multi_asset_audit_v1.evaluate_global_blockers``

Evidence store: this contract deliberately reuses the existing
``native_short_scope_admin_operation_v1`` operation ledger as the canonical,
durable, machine-readable acceptance-evidence store. That ledger already
persists exactly the fields a promotion acceptance needs to prove: immutable
operation identity (``operation_uuid``), operation type, canonical six-part
scope key with a database CHECK constraint, terminal result class/code,
schema version, and a SHA-256 request-identity digest
(``metadata_digest``). No new schema or migration is required to store
evidence; this module only adds the pinning identity and the fail-closed
evaluator on top of it, following the same pattern already used for
``PROVENANCE_AUDIT_RUN_UUID`` in ``native_short_multi_asset_audit_v1``.

Fail-closed rule: evidence closes ``PROMOTION_CONTRACT_MISSING`` only when
every one of the following holds for the exact pinned ``operation_uuid``:

- a contract version and a pinned accepted operation identity are both set;
- exactly one operation ledger row matches that identity (no ambiguity);
- ``operation_type == PROMOTE_SCOPE``;
- the operation is terminal (``completed_at_utc`` is not NULL);
- ``result_class == SUCCESS`` and ``result_code`` is one of the two accepted
  promotion success codes (new-scope or reactivate-from-withdrawal);
- the row's canonical scope key matches the fixed non-symbol canonical fields
  (venue/quote_currency/fib_trading_horizon/primary_interval/supporting_interval)
  and carries a well-formed symbol;
- ``schema_version`` equals the required administration schema version;
- ``metadata_digest`` is a well-formed 64-character lowercase hex SHA-256
  digest (proves the row is bound to one exact immutable request identity).

Any missing, malformed, incomplete, wrong-version, ambiguous, or
unrelated-scope/operation evidence leaves the blocker active. This module does
not itself constitute production promotion acceptance: as of this contract's
introduction, ``ACCEPTED_PROMOTION_OPERATION_UUID`` is intentionally unset
(``None``), so ``PROMOTION_CONTRACT_MISSING`` remains active until a real
promotion is executed, reviewed, and its ``operation_uuid`` is pinned here
alongside a reviewed operational-acceptance document (see
``docs/todo/native_short_multi_asset_rollout_contract_v1.md`` for the
required later procedure).

Safety markers:
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
"""

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


PROMOTION_ACCEPTANCE_CONTRACT_VERSION = "native_short_promotion_acceptance_v1"

# Must equal the schema_version already used by
# native_short_scope_administration_transaction_v1 / run_native_short_scope_administration_v1
# for every administration operation (see tests/test_native_short_scope_administration_transaction_v1.py).
REQUIRED_ADMINISTRATION_SCHEMA_VERSION = "native_short_scope_administration_v1"

REQUIRED_OPERATION_TYPE = "PROMOTE_SCOPE"
ACCEPTED_RESULT_CLASS = "SUCCESS"
ACCEPTED_RESULT_CODES = ("PROMOTED_NEW_SCOPE", "PROMOTED_FROM_PRIOR_WITHDRAWAL")

CANONICAL_SCOPE_EXPECTED: Mapping[str, str] = {
    "venue": "bitvavo",
    "quote_currency": "EUR",
    "fib_trading_horizon": "SHORT",
    "primary_interval": "4h",
    "supporting_interval": "1h",
}

# The reviewed, operationally accepted PROMOTE_SCOPE operation_uuid. None means
# no controlled production promotion acceptance has been reviewed and pinned
# yet; the evaluator fails closed unconditionally in that case, regardless of
# any operation rows already present in the ledger. Populate only alongside a
# reviewed operational-acceptance document analogous to
# docs/ops/native_short_writer_provenance_operational_acceptance_20260717.md.
ACCEPTED_PROMOTION_OPERATION_UUID: str | None = None

REASON_NO_ACCEPTANCE_PINNED = "NO_ACCEPTANCE_PINNED"
REASON_EVIDENCE_ABSENT = "EVIDENCE_ABSENT"
REASON_AMBIGUOUS_EVIDENCE = "AMBIGUOUS_EVIDENCE"
REASON_WRONG_OPERATION_TYPE = "WRONG_OPERATION_TYPE"
REASON_NOT_TERMINAL_SUCCESS = "NOT_TERMINAL_SUCCESS"
REASON_WRONG_SCOPE = "WRONG_SCOPE"
REASON_WRONG_SCHEMA_VERSION = "WRONG_SCHEMA_VERSION"
REASON_DIGEST_MISSING_OR_INVALID = "DIGEST_MISSING_OR_INVALID"
REASON_EVIDENCE_ACCEPTED = "EVIDENCE_ACCEPTED"

_HEX_DIGITS = frozenset("0123456789abcdef")


def _valid_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in _HEX_DIGITS for c in value)


def _valid_symbol(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and value.isascii() and value.isalnum() and value.isupper()


@dataclass(frozen=True)
class PromotionAcceptanceEvaluation:
    """Deterministic, read-only evaluation result. Never a decision to act."""

    accepted: bool
    reason: str
    operation_uuid: str | None
    scope_symbol: str | None


def evaluate_promotion_acceptance_evidence(
    operation_rows: Sequence[Mapping[str, Any]],
    *,
    accepted_operation_uuid: str | None = ACCEPTED_PROMOTION_OPERATION_UUID,
) -> PromotionAcceptanceEvaluation:
    """Evaluate whether a canonical PROMOTE_SCOPE operational acceptance closes
    PROMOTION_CONTRACT_MISSING.

    Fail-closed: absent, malformed, incomplete, wrong-version, wrong-scope,
    stale, or ambiguous evidence never accepts. This function is pure,
    deterministic, and performs no I/O and no mutation.
    """
    if not accepted_operation_uuid:
        return PromotionAcceptanceEvaluation(False, REASON_NO_ACCEPTANCE_PINNED, None, None)

    matches = [
        row for row in operation_rows if str(row.get("operation_uuid")) == accepted_operation_uuid
    ]
    if not matches:
        return PromotionAcceptanceEvaluation(False, REASON_EVIDENCE_ABSENT, accepted_operation_uuid, None)
    if len(matches) > 1:
        return PromotionAcceptanceEvaluation(
            False, REASON_AMBIGUOUS_EVIDENCE, accepted_operation_uuid, None
        )

    row = matches[0]
    symbol = row.get("symbol")
    symbol_str = str(symbol) if symbol is not None else None

    if str(row.get("operation_type")) != REQUIRED_OPERATION_TYPE:
        return PromotionAcceptanceEvaluation(
            False, REASON_WRONG_OPERATION_TYPE, accepted_operation_uuid, symbol_str
        )
    if row.get("completed_at_utc") is None:
        return PromotionAcceptanceEvaluation(
            False, REASON_NOT_TERMINAL_SUCCESS, accepted_operation_uuid, symbol_str
        )
    if (
        str(row.get("result_class")) != ACCEPTED_RESULT_CLASS
        or str(row.get("result_code")) not in ACCEPTED_RESULT_CODES
    ):
        return PromotionAcceptanceEvaluation(
            False, REASON_NOT_TERMINAL_SUCCESS, accepted_operation_uuid, symbol_str
        )
    for field, expected in CANONICAL_SCOPE_EXPECTED.items():
        if str(row.get(field)) != expected:
            return PromotionAcceptanceEvaluation(
                False, REASON_WRONG_SCOPE, accepted_operation_uuid, symbol_str
            )
    if not _valid_symbol(symbol_str):
        return PromotionAcceptanceEvaluation(
            False, REASON_WRONG_SCOPE, accepted_operation_uuid, symbol_str
        )
    if str(row.get("schema_version")) != REQUIRED_ADMINISTRATION_SCHEMA_VERSION:
        return PromotionAcceptanceEvaluation(
            False, REASON_WRONG_SCHEMA_VERSION, accepted_operation_uuid, symbol_str
        )
    if not _valid_digest(row.get("metadata_digest")):
        return PromotionAcceptanceEvaluation(
            False, REASON_DIGEST_MISSING_OR_INVALID, accepted_operation_uuid, symbol_str
        )

    return PromotionAcceptanceEvaluation(True, REASON_EVIDENCE_ACCEPTED, accepted_operation_uuid, symbol_str)


__all__ = [
    "PROMOTION_ACCEPTANCE_CONTRACT_VERSION",
    "REQUIRED_ADMINISTRATION_SCHEMA_VERSION",
    "REQUIRED_OPERATION_TYPE",
    "ACCEPTED_RESULT_CLASS",
    "ACCEPTED_RESULT_CODES",
    "CANONICAL_SCOPE_EXPECTED",
    "ACCEPTED_PROMOTION_OPERATION_UUID",
    "REASON_NO_ACCEPTANCE_PINNED",
    "REASON_EVIDENCE_ABSENT",
    "REASON_AMBIGUOUS_EVIDENCE",
    "REASON_WRONG_OPERATION_TYPE",
    "REASON_NOT_TERMINAL_SUCCESS",
    "REASON_WRONG_SCOPE",
    "REASON_WRONG_SCHEMA_VERSION",
    "REASON_DIGEST_MISSING_OR_INVALID",
    "REASON_EVIDENCE_ACCEPTED",
    "PromotionAcceptanceEvaluation",
    "evaluate_promotion_acceptance_evidence",
]
