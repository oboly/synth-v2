from __future__ import annotations

import json
from pathlib import Path

from src.market_data.native_short_promotion_bootstrap_evidence_v1 import (
    BOOTSTRAP_CONTRACT_VERSION,
    CANONICAL_SCOPE_FIXED_FIELDS,
    REASON_COMMIT_MISMATCH,
    REASON_EVIDENCE_ACCEPTED,
    REASON_MANIFEST_CONTRACT_DIGEST_MISMATCH,
    REASON_MANIFEST_CONTRACT_VERSION_WRONG,
    REASON_MANIFEST_COMMIT_INVALID,
    REASON_MANIFEST_MALFORMED,
    REASON_MANIFEST_MISSING_APPROVAL_REFERENCE,
    REASON_MANIFEST_MISSING_OR_UNREADABLE,
    REASON_MANIFEST_NOT_ACCEPTED,
    REASON_MANIFEST_SCHEMA_VERSION_WRONG,
    REASON_MANIFEST_SCOPE_INVALID,
    REASON_SCOPE_MISMATCH,
    REQUIRED_MANIFEST_SCHEMA_VERSION,
    compute_bootstrap_contract_digest,
    evaluate_promotion_bootstrap_evidence,
)


TEST_COMMIT = "a" * 40
SCOPE = {**CANONICAL_SCOPE_FIXED_FIELDS, "symbol": "SOL"}


def valid_manifest(**overrides: object) -> dict:
    manifest = {
        "acceptance_schema_version": REQUIRED_MANIFEST_SCHEMA_VERSION,
        "bootstrap_contract_version": BOOTSTRAP_CONTRACT_VERSION,
        "bootstrap_contract_digest": compute_bootstrap_contract_digest(),
        "accepted": True,
        "scope": dict(SCOPE),
        "repository_commit_sha": TEST_COMMIT,
        "approval_reference": "docs/todo/native_short_multi_asset_rollout_contract_v1.md",
    }
    manifest.update(overrides)
    return manifest


def write_manifest(path: Path, manifest: object) -> Path:
    manifest_path = path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def _evaluate(path: Path, *, scope: dict = SCOPE, commit: str = TEST_COMMIT):
    return evaluate_promotion_bootstrap_evidence(
        requested_scope=scope,
        requested_repository_commit_sha=commit,
        manifest_path=path,
    )


def test_shipped_default_manifest_is_unaccepted() -> None:
    from src.market_data.native_short_promotion_bootstrap_evidence_v1 import (
        DEFAULT_BOOTSTRAP_MANIFEST_PATH,
    )

    result = _evaluate(DEFAULT_BOOTSTRAP_MANIFEST_PATH, scope=SCOPE, commit=TEST_COMMIT)
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_NOT_ACCEPTED


def test_shipped_default_manifest_digest_matches_live_contract() -> None:
    from src.market_data.native_short_promotion_bootstrap_evidence_v1 import (
        DEFAULT_BOOTSTRAP_MANIFEST_PATH,
    )

    raw = json.loads(DEFAULT_BOOTSTRAP_MANIFEST_PATH.read_text(encoding="utf-8"))
    assert raw["bootstrap_contract_digest"] == compute_bootstrap_contract_digest()
    assert raw["acceptance_schema_version"] == REQUIRED_MANIFEST_SCHEMA_VERSION
    assert raw["bootstrap_contract_version"] == BOOTSTRAP_CONTRACT_VERSION
    assert raw["accepted"] is False


def test_missing_manifest_fails_closed(tmp_path: Path) -> None:
    result = _evaluate(tmp_path / "does_not_exist.json")
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_MISSING_OR_UNREADABLE


def test_malformed_json_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text("not json", encoding="utf-8")
    result = _evaluate(path)
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_MISSING_OR_UNREADABLE


def test_non_mapping_manifest_fails_closed(tmp_path: Path) -> None:
    path = write_manifest(tmp_path, [1, 2, 3])
    result = _evaluate(path)
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_MALFORMED


def test_wrong_schema_version_fails_closed(tmp_path: Path) -> None:
    path = write_manifest(tmp_path, valid_manifest(acceptance_schema_version="wrong"))
    result = _evaluate(path)
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_SCHEMA_VERSION_WRONG


def test_wrong_contract_version_fails_closed(tmp_path: Path) -> None:
    path = write_manifest(tmp_path, valid_manifest(bootstrap_contract_version="wrong"))
    result = _evaluate(path)
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_CONTRACT_VERSION_WRONG


def test_wrong_contract_digest_fails_closed(tmp_path: Path) -> None:
    path = write_manifest(tmp_path, valid_manifest(bootstrap_contract_digest="0" * 64))
    result = _evaluate(path)
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_CONTRACT_DIGEST_MISMATCH


def test_not_accepted_fails_closed(tmp_path: Path) -> None:
    path = write_manifest(tmp_path, valid_manifest(accepted=False))
    result = _evaluate(path)
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_NOT_ACCEPTED


def test_incomplete_scope_fails_closed(tmp_path: Path) -> None:
    path = write_manifest(tmp_path, valid_manifest(scope={"symbol": "SOL"}))
    result = _evaluate(path)
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_SCOPE_INVALID


def test_lowercase_symbol_fails_closed(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path, valid_manifest(scope={**CANONICAL_SCOPE_FIXED_FIELDS, "symbol": "sol"})
    )
    result = _evaluate(path, scope={**CANONICAL_SCOPE_FIXED_FIELDS, "symbol": "sol"})
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_SCOPE_INVALID


def test_invalid_commit_fails_closed(tmp_path: Path) -> None:
    path = write_manifest(tmp_path, valid_manifest(repository_commit_sha="not-a-sha"))
    result = _evaluate(path)
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_COMMIT_INVALID


def test_missing_approval_reference_fails_closed(tmp_path: Path) -> None:
    path = write_manifest(tmp_path, valid_manifest(approval_reference=""))
    result = _evaluate(path)
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_MISSING_APPROVAL_REFERENCE


def test_scope_mismatch_fails_closed(tmp_path: Path) -> None:
    path = write_manifest(tmp_path, valid_manifest())
    other_scope = {**CANONICAL_SCOPE_FIXED_FIELDS, "symbol": "ETH"}
    result = _evaluate(path, scope=other_scope, commit=TEST_COMMIT)
    assert result.accepted is False
    assert result.reason == REASON_SCOPE_MISMATCH


def test_commit_mismatch_fails_closed(tmp_path: Path) -> None:
    path = write_manifest(tmp_path, valid_manifest())
    result = _evaluate(path, scope=SCOPE, commit="b" * 40)
    assert result.accepted is False
    assert result.reason == REASON_COMMIT_MISMATCH


def test_fully_valid_manifest_accepts_exact_match(tmp_path: Path) -> None:
    path = write_manifest(tmp_path, valid_manifest())
    result = _evaluate(path, scope=SCOPE, commit=TEST_COMMIT)
    assert result.accepted is True
    assert result.reason == REASON_EVIDENCE_ACCEPTED
    assert result.symbol == "SOL"
    assert result.repository_commit_sha == TEST_COMMIT
