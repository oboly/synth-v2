from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from src.market_data.native_short_promotion_acceptance_evidence_v1 import (
    ACCEPTED_RESULT_CODES,
    CANONICAL_SCOPE_FIXED_FIELDS,
    PROMOTION_ACCEPTANCE_CONTRACT_VERSION,
    REASON_AMBIGUOUS_EVIDENCE,
    REASON_DIGEST_MISMATCH,
    REASON_EVIDENCE_ABSENT,
    REASON_EVIDENCE_ACCEPTED,
    REASON_MANIFEST_CONTRACT_DIGEST_MISMATCH,
    REASON_MANIFEST_CONTRACT_VERSION_WRONG,
    REASON_MANIFEST_DIGEST_RECOMPUTE_MISMATCH,
    REASON_MANIFEST_IDENTITY_FIELD_MISMATCH,
    REASON_MANIFEST_MALFORMED,
    REASON_MANIFEST_MISSING_OR_UNREADABLE,
    REASON_MANIFEST_MISSING_REVIEW_REFERENCE,
    REASON_MANIFEST_NOT_ACCEPTED,
    REASON_MANIFEST_REQUEST_IDENTITY_INVALID,
    REASON_MANIFEST_SCHEMA_VERSION_WRONG,
    REASON_MANIFEST_SCOPE_INCOMPLETE,
    REASON_MANIFEST_TEST_PROVENANCE_REJECTED,
    REASON_NOT_TERMINAL_SUCCESS,
    REASON_WRONG_OPERATION_TYPE,
    REASON_WRONG_SCHEMA_VERSION,
    REASON_WRONG_SCOPE,
    REQUIRED_ADMINISTRATION_SCHEMA_VERSION,
    REQUIRED_MANIFEST_SCHEMA_VERSION,
    _reconstruct_identity_request,
    compute_promotion_contract_digest,
    evaluate_promotion_acceptance_evidence,
)


OPERATION_UUID = "11111111-1111-1111-1111-111111111111"
TEST_COMMIT = "0" * 40
SCOPE = {**CANONICAL_SCOPE_FIXED_FIELDS, "symbol": "SOL"}

# Reviewed production acceptance provenance must never be TEST/TEST -- it uses
# an explicit non-TEST actor/trigger pair, matching what a real reviewed
# PROMOTE_SCOPE invocation would record.
IMMUTABLE_REQUEST_IDENTITY: dict[str, Any] = {
    "operation_type": "PROMOTE_SCOPE",
    "scope_key": dict(SCOPE),
    "provenance": {
        "operation_uuid": OPERATION_UUID,
        "actor_type": "HUMAN_OPERATOR",
        "actor_id": "acceptance-test-operator",
        "trigger_type": "MANUAL_CLI",
        "request_source": "tests.test_native_short_promotion_acceptance_evidence_v1",
        "reason": "synthetic reviewed acceptance fixture",
        "requested_at_utc": "2026-07-30T00:00:00Z",
        "repository_sha": TEST_COMMIT,
        "schema_version": REQUIRED_ADMINISTRATION_SCHEMA_VERSION,
    },
    "canonical_metadata": {},
}


def _expected_digest(identity: dict[str, Any] | None = None) -> str:
    return _reconstruct_identity_request(identity or IMMUTABLE_REQUEST_IDENTITY).request_digest


def valid_manifest(**overrides: object) -> dict:
    manifest = {
        "acceptance_schema_version": REQUIRED_MANIFEST_SCHEMA_VERSION,
        "promotion_contract_version": PROMOTION_ACCEPTANCE_CONTRACT_VERSION,
        "promotion_contract_digest": compute_promotion_contract_digest(),
        "accepted": True,
        "operation_uuid": OPERATION_UUID,
        "scope": dict(SCOPE),
        "expected_request_metadata_digest": _expected_digest(),
        "immutable_request_identity": IMMUTABLE_REQUEST_IDENTITY,
        "reviewed_acceptance_reference": "docs/ops/native_short_promotion_operational_acceptance_TEMPLATE.md",
    }
    manifest.update(overrides)
    return manifest


def valid_ledger_row(**overrides: object) -> dict:
    row = {
        "operation_uuid": OPERATION_UUID,
        "operation_type": "PROMOTE_SCOPE",
        **CANONICAL_SCOPE_FIXED_FIELDS,
        "symbol": "SOL",
        "schema_version": REQUIRED_ADMINISTRATION_SCHEMA_VERSION,
        "metadata_digest": _expected_digest(),
        "completed_at_utc": datetime(2026, 7, 30, 12, 0, tzinfo=UTC),
        "result_class": "SUCCESS",
        "result_code": "PROMOTED_NEW_SCOPE",
    }
    row.update(overrides)
    return row


def write_manifest(path: Path, manifest: object) -> Path:
    manifest_path = path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def test_no_python_hardcoded_operation_uuid_constant() -> None:
    import src.market_data.native_short_promotion_acceptance_evidence_v1 as module

    assert not hasattr(module, "ACCEPTED_PROMOTION_OPERATION_UUID")


def test_missing_manifest_fails_closed(tmp_path: Path) -> None:
    result = evaluate_promotion_acceptance_evidence(
        [valid_ledger_row()], manifest_path=tmp_path / "does_not_exist.json"
    )
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_MISSING_OR_UNREADABLE


def test_malformed_manifest_json_fails_closed(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("{not valid json", encoding="utf-8")
    result = evaluate_promotion_acceptance_evidence(
        [valid_ledger_row()], manifest_path=manifest_path
    )
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_MISSING_OR_UNREADABLE


def test_manifest_not_a_mapping_fails_closed(tmp_path: Path) -> None:
    manifest_path = write_manifest(tmp_path, ["not", "a", "mapping"])
    result = evaluate_promotion_acceptance_evidence(
        [valid_ledger_row()], manifest_path=manifest_path
    )
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_MALFORMED


def test_wrong_manifest_schema_version_fails_closed(tmp_path: Path) -> None:
    manifest_path = write_manifest(
        tmp_path, valid_manifest(acceptance_schema_version="stale_v0")
    )
    result = evaluate_promotion_acceptance_evidence(
        [valid_ledger_row()], manifest_path=manifest_path
    )
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_SCHEMA_VERSION_WRONG


def test_wrong_contract_version_fails_closed(tmp_path: Path) -> None:
    manifest_path = write_manifest(
        tmp_path, valid_manifest(promotion_contract_version="stale_contract_v0")
    )
    result = evaluate_promotion_acceptance_evidence(
        [valid_ledger_row()], manifest_path=manifest_path
    )
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_CONTRACT_VERSION_WRONG


def test_wrong_contract_digest_fails_closed(tmp_path: Path) -> None:
    manifest_path = write_manifest(
        tmp_path, valid_manifest(promotion_contract_digest="f" * 64)
    )
    result = evaluate_promotion_acceptance_evidence(
        [valid_ledger_row()], manifest_path=manifest_path
    )
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_CONTRACT_DIGEST_MISMATCH


def test_unaccepted_manifest_fails_closed(tmp_path: Path) -> None:
    manifest_path = write_manifest(tmp_path, valid_manifest(accepted=False))
    result = evaluate_promotion_acceptance_evidence(
        [valid_ledger_row()], manifest_path=manifest_path
    )
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_NOT_ACCEPTED


def test_shipped_repository_manifest_is_accepted_against_the_real_sol_ledger_row() -> None:
    # The manifest shipped by this lane records the reviewed acceptance of
    # the real, already-persisted production SOL PROMOTE_SCOPE operation
    # (docs/ops/native_short_sol_promotion_operational_acceptance_v1.md).
    # Cross-validated here against a reconstruction of that exact ledger row
    # (not a live database read -- this module's evaluator takes rows as a
    # pure argument), proving the manifest and the ledger evidence agree.
    sol_row = {
        "operation_uuid": "7ef9c93a-4418-458f-939e-7c3caf00705f",
        "operation_type": "PROMOTE_SCOPE",
        "venue": "bitvavo",
        "symbol": "SOL",
        "quote_currency": "EUR",
        "fib_trading_horizon": "SHORT",
        "primary_interval": "4h",
        "supporting_interval": "1h",
        "schema_version": REQUIRED_ADMINISTRATION_SCHEMA_VERSION,
        "metadata_digest": "8f0168b57ed8905154f8157643f5cddfd3e51fa41de85c6d096432801c401a5a",
        "completed_at_utc": datetime(2026, 8, 1, 17, 30, 15, tzinfo=UTC),
        "result_class": "SUCCESS",
        "result_code": "PROMOTED_NEW_SCOPE",
    }
    result = evaluate_promotion_acceptance_evidence([sol_row])
    assert result.accepted is True
    assert result.reason == REASON_EVIDENCE_ACCEPTED
    assert result.operation_uuid == "7ef9c93a-4418-458f-939e-7c3caf00705f"
    assert result.scope_symbol == "SOL"


def test_shipped_repository_manifest_fails_closed_without_its_matching_ledger_row() -> None:
    # No canonical evidence source is ever inferred from the manifest alone
    # -- absent the exact matching ledger row, the shipped accepted manifest
    # still fails closed.
    result = evaluate_promotion_acceptance_evidence([])
    assert result.accepted is False
    assert result.reason == REASON_EVIDENCE_ABSENT


@pytest.mark.parametrize("accepted_value", [1, "true", None, "yes"])
def test_non_boolean_true_accepted_field_fails_closed(tmp_path: Path, accepted_value: object) -> None:
    manifest_path = write_manifest(tmp_path, valid_manifest(accepted=accepted_value))
    result = evaluate_promotion_acceptance_evidence(
        [valid_ledger_row()], manifest_path=manifest_path
    )
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_NOT_ACCEPTED


def test_incomplete_scope_fails_closed(tmp_path: Path) -> None:
    bad_scope = {**SCOPE, "venue": "kraken"}
    manifest_path = write_manifest(tmp_path, valid_manifest(scope=bad_scope))
    result = evaluate_promotion_acceptance_evidence(
        [valid_ledger_row()], manifest_path=manifest_path
    )
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_SCOPE_INCOMPLETE


def test_missing_review_reference_fails_closed(tmp_path: Path) -> None:
    manifest_path = write_manifest(
        tmp_path, valid_manifest(reviewed_acceptance_reference="")
    )
    result = evaluate_promotion_acceptance_evidence(
        [valid_ledger_row()], manifest_path=manifest_path
    )
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_MISSING_REVIEW_REFERENCE


def test_malformed_expected_digest_fails_closed(tmp_path: Path) -> None:
    manifest_path = write_manifest(
        tmp_path, valid_manifest(expected_request_metadata_digest="not-hex")
    )
    result = evaluate_promotion_acceptance_evidence(
        [valid_ledger_row()], manifest_path=manifest_path
    )
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_REQUEST_IDENTITY_INVALID


def test_missing_immutable_request_identity_fails_closed(tmp_path: Path) -> None:
    manifest_path = write_manifest(
        tmp_path, valid_manifest(immutable_request_identity=None)
    )
    result = evaluate_promotion_acceptance_evidence(
        [valid_ledger_row()], manifest_path=manifest_path
    )
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_REQUEST_IDENTITY_INVALID


def test_malformed_immutable_request_identity_fails_closed(tmp_path: Path) -> None:
    bad_identity = {**IMMUTABLE_REQUEST_IDENTITY, "scope_key": {"venue": "bitvavo"}}
    manifest_path = write_manifest(
        tmp_path, valid_manifest(immutable_request_identity=bad_identity)
    )
    result = evaluate_promotion_acceptance_evidence(
        [valid_ledger_row()], manifest_path=manifest_path
    )
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_REQUEST_IDENTITY_INVALID


def test_recomputed_digest_mismatch_fails_closed(tmp_path: Path) -> None:
    # expected_request_metadata_digest does not match what the recorded
    # immutable_request_identity actually recomputes to.
    manifest_path = write_manifest(
        tmp_path,
        valid_manifest(expected_request_metadata_digest="a" * 64),
    )
    result = evaluate_promotion_acceptance_evidence(
        [valid_ledger_row()], manifest_path=manifest_path
    )
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_DIGEST_RECOMPUTE_MISMATCH


def test_test_actor_type_in_identity_fails_closed(tmp_path: Path) -> None:
    bad_identity = {
        **IMMUTABLE_REQUEST_IDENTITY,
        "provenance": {
            **IMMUTABLE_REQUEST_IDENTITY["provenance"],
            "actor_type": "TEST",
            "trigger_type": "TEST",
        },
    }
    manifest_path = write_manifest(
        tmp_path,
        valid_manifest(
            immutable_request_identity=bad_identity,
            expected_request_metadata_digest=_expected_digest(bad_identity),
        ),
    )
    result = evaluate_promotion_acceptance_evidence(
        [valid_ledger_row(metadata_digest=_expected_digest(bad_identity))],
        manifest_path=manifest_path,
    )
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_TEST_PROVENANCE_REJECTED


def test_test_trigger_type_alone_is_invalid_provenance_and_fails_closed(tmp_path: Path) -> None:
    # actor_type=TEST xor trigger_type=TEST is rejected by the underlying
    # contract's own construction invariant before this module's TEST-provenance
    # check even runs -- still fail-closed, via the identity-reconstruction path.
    bad_identity = {
        **IMMUTABLE_REQUEST_IDENTITY,
        "provenance": {
            **IMMUTABLE_REQUEST_IDENTITY["provenance"],
            "trigger_type": "TEST",
        },
    }
    manifest_path = write_manifest(
        tmp_path,
        valid_manifest(immutable_request_identity=bad_identity),
    )
    result = evaluate_promotion_acceptance_evidence(
        [valid_ledger_row()], manifest_path=manifest_path
    )
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_REQUEST_IDENTITY_INVALID


def test_remove_scope_in_identity_fails_closed(tmp_path: Path) -> None:
    bad_identity = {**IMMUTABLE_REQUEST_IDENTITY, "operation_type": "REMOVE_SCOPE"}
    manifest_path = write_manifest(
        tmp_path,
        valid_manifest(
            immutable_request_identity=bad_identity,
            expected_request_metadata_digest=_expected_digest(bad_identity),
        ),
    )
    result = evaluate_promotion_acceptance_evidence(
        [valid_ledger_row(metadata_digest=_expected_digest(bad_identity))],
        manifest_path=manifest_path,
    )
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_IDENTITY_FIELD_MISMATCH


def test_identity_scope_symbol_differs_from_manifest_scope_fails_closed(tmp_path: Path) -> None:
    other_scope = {**SCOPE, "symbol": "ETH"}
    bad_identity = {**IMMUTABLE_REQUEST_IDENTITY, "scope_key": other_scope}
    manifest_path = write_manifest(
        tmp_path,
        valid_manifest(
            immutable_request_identity=bad_identity,
            expected_request_metadata_digest=_expected_digest(bad_identity),
        ),
    )
    result = evaluate_promotion_acceptance_evidence(
        [valid_ledger_row(metadata_digest=_expected_digest(bad_identity))],
        manifest_path=manifest_path,
    )
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_IDENTITY_FIELD_MISMATCH


def test_identity_operation_uuid_differs_from_manifest_operation_uuid_fails_closed(
    tmp_path: Path,
) -> None:
    bad_identity = {
        **IMMUTABLE_REQUEST_IDENTITY,
        "provenance": {
            **IMMUTABLE_REQUEST_IDENTITY["provenance"],
            "operation_uuid": "44444444-4444-4444-4444-444444444444",
        },
    }
    manifest_path = write_manifest(
        tmp_path,
        valid_manifest(
            immutable_request_identity=bad_identity,
            expected_request_metadata_digest=_expected_digest(bad_identity),
        ),
    )
    result = evaluate_promotion_acceptance_evidence(
        [valid_ledger_row(metadata_digest=_expected_digest(bad_identity))],
        manifest_path=manifest_path,
    )
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_IDENTITY_FIELD_MISMATCH


def test_identity_provenance_schema_version_wrong_fails_closed(tmp_path: Path) -> None:
    bad_identity = {
        **IMMUTABLE_REQUEST_IDENTITY,
        "provenance": {
            **IMMUTABLE_REQUEST_IDENTITY["provenance"],
            "schema_version": "stale_schema_v0",
        },
    }
    manifest_path = write_manifest(
        tmp_path,
        valid_manifest(
            immutable_request_identity=bad_identity,
            expected_request_metadata_digest=_expected_digest(bad_identity),
        ),
    )
    result = evaluate_promotion_acceptance_evidence(
        [valid_ledger_row(metadata_digest=_expected_digest(bad_identity))],
        manifest_path=manifest_path,
    )
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_IDENTITY_FIELD_MISMATCH


def test_valid_manifest_but_missing_ledger_evidence_fails_closed(tmp_path: Path) -> None:
    manifest_path = write_manifest(tmp_path, valid_manifest())
    result = evaluate_promotion_acceptance_evidence([], manifest_path=manifest_path)
    assert result.accepted is False
    assert result.reason == REASON_EVIDENCE_ABSENT


def test_ledger_success_without_reviewed_manifest_fails_closed(tmp_path: Path) -> None:
    # A terminal SUCCESS ledger row alone, with no manifest at all, must not
    # close the blocker -- execution/result evidence is not reviewed acceptance.
    result = evaluate_promotion_acceptance_evidence(
        [valid_ledger_row()], manifest_path=tmp_path / "absent.json"
    )
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_MISSING_OR_UNREADABLE


def test_wrong_operation_uuid_in_ledger_fails_closed(tmp_path: Path) -> None:
    manifest_path = write_manifest(tmp_path, valid_manifest())
    other_row = valid_ledger_row(
        operation_uuid="22222222-2222-2222-2222-222222222222"
    )
    result = evaluate_promotion_acceptance_evidence(
        [other_row], manifest_path=manifest_path
    )
    assert result.accepted is False
    assert result.reason == REASON_EVIDENCE_ABSENT


def test_wrong_symbol_in_ledger_fails_closed(tmp_path: Path) -> None:
    manifest_path = write_manifest(tmp_path, valid_manifest())
    row = valid_ledger_row(symbol="ETH")
    result = evaluate_promotion_acceptance_evidence([row], manifest_path=manifest_path)
    assert result.accepted is False
    assert result.reason == REASON_WRONG_SCOPE


def test_wrong_scope_field_in_ledger_fails_closed(tmp_path: Path) -> None:
    manifest_path = write_manifest(tmp_path, valid_manifest())
    row = valid_ledger_row(venue="kraken")
    result = evaluate_promotion_acceptance_evidence([row], manifest_path=manifest_path)
    assert result.accepted is False
    assert result.reason == REASON_WRONG_SCOPE


def test_wrong_operation_type_in_ledger_fails_closed(tmp_path: Path) -> None:
    manifest_path = write_manifest(tmp_path, valid_manifest())
    row = valid_ledger_row(operation_type="REMOVE_SCOPE")
    result = evaluate_promotion_acceptance_evidence([row], manifest_path=manifest_path)
    assert result.accepted is False
    assert result.reason == REASON_WRONG_OPERATION_TYPE


def test_non_terminal_ledger_row_fails_closed(tmp_path: Path) -> None:
    manifest_path = write_manifest(tmp_path, valid_manifest())
    row = valid_ledger_row(completed_at_utc=None, result_class=None, result_code=None)
    result = evaluate_promotion_acceptance_evidence([row], manifest_path=manifest_path)
    assert result.accepted is False
    assert result.reason == REASON_NOT_TERMINAL_SUCCESS


def test_wrong_schema_version_in_ledger_fails_closed(tmp_path: Path) -> None:
    manifest_path = write_manifest(tmp_path, valid_manifest())
    row = valid_ledger_row(schema_version="stale_schema_v0")
    result = evaluate_promotion_acceptance_evidence([row], manifest_path=manifest_path)
    assert result.accepted is False
    assert result.reason == REASON_WRONG_SCHEMA_VERSION


def test_well_formed_but_incorrect_metadata_digest_fails_closed(tmp_path: Path) -> None:
    # A well-formed 64-char hex digest that simply does not equal the
    # manifest-bound expected digest must still fail closed.
    manifest_path = write_manifest(tmp_path, valid_manifest())
    row = valid_ledger_row(metadata_digest="b" * 64)
    result = evaluate_promotion_acceptance_evidence([row], manifest_path=manifest_path)
    assert result.accepted is False
    assert result.reason == REASON_DIGEST_MISMATCH


def test_ambiguous_duplicate_ledger_evidence_fails_closed(tmp_path: Path) -> None:
    manifest_path = write_manifest(tmp_path, valid_manifest())
    result = evaluate_promotion_acceptance_evidence(
        [valid_ledger_row(), valid_ledger_row()], manifest_path=manifest_path
    )
    assert result.accepted is False
    assert result.reason == REASON_AMBIGUOUS_EVIDENCE


def test_valid_synthetic_manifest_and_matching_ledger_row_accepts(tmp_path: Path) -> None:
    manifest_path = write_manifest(tmp_path, valid_manifest())
    result = evaluate_promotion_acceptance_evidence(
        [valid_ledger_row()], manifest_path=manifest_path
    )
    assert result.accepted is True
    assert result.reason == REASON_EVIDENCE_ACCEPTED
    assert result.operation_uuid == OPERATION_UUID
    assert result.scope_symbol == "SOL"


def test_valid_evidence_among_unrelated_rows_still_accepts(tmp_path: Path) -> None:
    manifest_path = write_manifest(tmp_path, valid_manifest())
    unrelated = valid_ledger_row(
        operation_uuid="33333333-3333-3333-3333-333333333333", symbol="ETH"
    )
    rows = [unrelated, valid_ledger_row()]
    result = evaluate_promotion_acceptance_evidence(rows, manifest_path=manifest_path)
    assert result.accepted is True


def test_accepted_result_codes_constant_matches_evaluated_set(tmp_path: Path) -> None:
    manifest_path = write_manifest(tmp_path, valid_manifest())
    for code in ACCEPTED_RESULT_CODES:
        row = valid_ledger_row(result_code=code)
        result = evaluate_promotion_acceptance_evidence([row], manifest_path=manifest_path)
        assert result.accepted is True


def test_evaluator_is_deterministic_and_read_only(tmp_path: Path) -> None:
    manifest_path = write_manifest(tmp_path, valid_manifest())
    before = manifest_path.read_text(encoding="utf-8")
    first = evaluate_promotion_acceptance_evidence(
        [valid_ledger_row()], manifest_path=manifest_path
    )
    second = evaluate_promotion_acceptance_evidence(
        [valid_ledger_row()], manifest_path=manifest_path
    )
    after = manifest_path.read_text(encoding="utf-8")
    assert first == second
    assert before == after
