from __future__ import annotations

import json
from pathlib import Path

from src.market_data.native_short_promotion_bootstrap_evidence_v1 import (
    BOOTSTRAP_CONTRACT_VERSION,
    CANONICAL_SCOPE_FIXED_FIELDS,
    REASON_ANCESTRY_CHECK_UNAVAILABLE,
    REASON_EVIDENCE_ACCEPTED,
    REASON_IMPLEMENTATION_COMMIT_NOT_ANCESTOR,
    REASON_MANIFEST_APPROVED_AT_INVALID,
    REASON_MANIFEST_CONTRACT_DIGEST_MISMATCH,
    REASON_MANIFEST_CONTRACT_VERSION_WRONG,
    REASON_MANIFEST_DIGEST_MISMATCH,
    REASON_MANIFEST_IMPLEMENTATION_COMMIT_INVALID,
    REASON_MANIFEST_MALFORMED,
    REASON_MANIFEST_MISSING_APPROVAL_REFERENCE,
    REASON_MANIFEST_MISSING_OR_UNREADABLE,
    REASON_MANIFEST_NOT_ACCEPTED,
    REASON_MANIFEST_SCHEMA_VERSION_WRONG,
    REASON_MANIFEST_SCOPE_INVALID,
    REASON_SCOPE_MISMATCH,
    REQUIRED_MANIFEST_SCHEMA_VERSION,
    compute_approval_evidence_digest,
    compute_bootstrap_contract_digest,
    evaluate_promotion_bootstrap_evidence,
    hash_implementation_file,
)


TEST_COMMIT = "a" * 40
SCOPE = {**CANONICAL_SCOPE_FIXED_FIELDS, "symbol": "SOL"}
APPROVAL_REFERENCE = "docs/ops/native_short_sol_bootstrap_promotion_approval_v1.md"
APPROVED_AT_UTC = "2026-08-01T00:00:00Z"

_IMPLEMENTATION_FILE_SHA256 = hash_implementation_file()


def _digest(**overrides: object) -> str:
    payload = {
        "accepted": True,
        "scope": dict(SCOPE),
        "approval_reference": APPROVAL_REFERENCE,
        "approved_at_utc": APPROVED_AT_UTC,
        "approved_implementation_commit": TEST_COMMIT,
        "implementation_file_sha256": _IMPLEMENTATION_FILE_SHA256,
    }
    payload.update(overrides)
    return compute_approval_evidence_digest(**payload)  # type: ignore[arg-type]


def valid_manifest(**overrides: object) -> dict:
    manifest = {
        "acceptance_schema_version": REQUIRED_MANIFEST_SCHEMA_VERSION,
        "bootstrap_contract_version": BOOTSTRAP_CONTRACT_VERSION,
        "bootstrap_contract_digest": compute_bootstrap_contract_digest(),
        "accepted": True,
        "scope": dict(SCOPE),
        "approval_reference": APPROVAL_REFERENCE,
        "approved_at_utc": APPROVED_AT_UTC,
        "approved_implementation_commit": TEST_COMMIT,
        "approval_evidence_digest": _digest(),
    }
    manifest.update(overrides)
    return manifest


def write_manifest(path: Path, manifest: object) -> Path:
    manifest_path = path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def _evaluate(
    path: Path,
    *,
    scope: dict = SCOPE,
    require_ancestry: bool = True,
    ancestry_checker=lambda commit: True,
):
    return evaluate_promotion_bootstrap_evidence(
        requested_scope=scope,
        manifest_path=path,
        require_implementation_commit_ancestry=require_ancestry,
        ancestry_checker=ancestry_checker,
    )


# --------------------------------------------------------------------------- #
# Shipped default manifest                                                    #
# --------------------------------------------------------------------------- #


def test_shipped_default_manifest_is_accepted_for_sol_with_real_ancestry() -> None:
    """The checked-in manifest names exactly SOL, is accepted:true, and its
    approved_implementation_commit is a real, already-existing ancestor of
    the current checkout -- so evaluating it with the real, default ancestry
    checker (no injection) against the exact SOL scope accepts."""
    from src.market_data.native_short_promotion_bootstrap_evidence_v1 import (
        DEFAULT_BOOTSTRAP_MANIFEST_PATH,
    )

    result = evaluate_promotion_bootstrap_evidence(
        requested_scope=SCOPE, manifest_path=DEFAULT_BOOTSTRAP_MANIFEST_PATH
    )
    assert result.accepted is True
    assert result.reason == REASON_EVIDENCE_ACCEPTED
    assert result.symbol == "SOL"


def test_shipped_default_manifest_fails_closed_for_every_other_symbol() -> None:
    from src.market_data.native_short_promotion_bootstrap_evidence_v1 import (
        DEFAULT_BOOTSTRAP_MANIFEST_PATH,
    )

    for symbol in ("ETH", "XRP", "BTC", "DOGE"):
        other_scope = {**CANONICAL_SCOPE_FIXED_FIELDS, "symbol": symbol}
        result = evaluate_promotion_bootstrap_evidence(
            requested_scope=other_scope, manifest_path=DEFAULT_BOOTSTRAP_MANIFEST_PATH
        )
        assert result.accepted is False
        assert result.reason == REASON_SCOPE_MISMATCH


def test_shipped_default_manifest_digest_matches_live_contract_and_content() -> None:
    from src.market_data.native_short_promotion_bootstrap_evidence_v1 import (
        DEFAULT_BOOTSTRAP_MANIFEST_PATH,
    )

    raw = json.loads(DEFAULT_BOOTSTRAP_MANIFEST_PATH.read_text(encoding="utf-8"))
    assert raw["bootstrap_contract_digest"] == compute_bootstrap_contract_digest()
    assert raw["acceptance_schema_version"] == REQUIRED_MANIFEST_SCHEMA_VERSION
    assert raw["bootstrap_contract_version"] == BOOTSTRAP_CONTRACT_VERSION
    assert raw["accepted"] is True
    assert raw["scope"] == SCOPE
    assert raw["approval_evidence_digest"] == compute_approval_evidence_digest(
        accepted=True,
        scope=raw["scope"],
        approval_reference=raw["approval_reference"],
        approved_at_utc=raw["approved_at_utc"],
        approved_implementation_commit=raw["approved_implementation_commit"],
        implementation_file_sha256=hash_implementation_file(),
    )


# --------------------------------------------------------------------------- #
# Structural / fail-closed manifest validation                                #
# --------------------------------------------------------------------------- #


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
    other_scope = {**CANONICAL_SCOPE_FIXED_FIELDS, "symbol": "sol"}
    path = write_manifest(tmp_path, valid_manifest(scope=other_scope))
    result = _evaluate(path, scope=other_scope)
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_SCOPE_INVALID


def test_missing_approval_reference_fails_closed(tmp_path: Path) -> None:
    path = write_manifest(tmp_path, valid_manifest(approval_reference=""))
    result = _evaluate(path)
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_MISSING_APPROVAL_REFERENCE


def test_invalid_approved_at_fails_closed(tmp_path: Path) -> None:
    path = write_manifest(tmp_path, valid_manifest(approved_at_utc="not-a-timestamp"))
    result = _evaluate(path)
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_APPROVED_AT_INVALID


def test_invalid_implementation_commit_fails_closed(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path, valid_manifest(approved_implementation_commit="not-a-sha")
    )
    result = _evaluate(path)
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_IMPLEMENTATION_COMMIT_INVALID


# --------------------------------------------------------------------------- #
# Approval-evidence digest (tamper detection)                                 #
# --------------------------------------------------------------------------- #


def test_wrong_approval_evidence_digest_fails_closed(tmp_path: Path) -> None:
    path = write_manifest(tmp_path, valid_manifest(approval_evidence_digest="0" * 64))
    result = _evaluate(path)
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_DIGEST_MISMATCH


def test_tampered_scope_without_digest_update_fails_closed(tmp_path: Path) -> None:
    """A manifest edited to name a different scope, without recomputing the
    approval-evidence digest, is detected as tampered and fails closed --
    it is not enough to change the displayed scope alone."""
    tampered_scope = {**CANONICAL_SCOPE_FIXED_FIELDS, "symbol": "ETH"}
    path = write_manifest(tmp_path, valid_manifest(scope=tampered_scope))
    result = _evaluate(path, scope=tampered_scope)
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_DIGEST_MISMATCH


def test_tampered_approval_reference_without_digest_update_fails_closed(
    tmp_path: Path,
) -> None:
    path = write_manifest(tmp_path, valid_manifest(approval_reference="docs/ops/forged.md"))
    result = _evaluate(path)
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_DIGEST_MISMATCH


def test_implementation_file_hash_change_is_detected(tmp_path: Path) -> None:
    """If the evidence-module implementation file changes after approval, the
    digest recomputed against its *current* bytes no longer matches the
    manifest's declared digest (computed against the approved bytes) --
    simulated here via a different implementation_file_path."""
    fake_impl = tmp_path / "fake_impl.py"
    fake_impl.write_text("# not the real evidence module\n", encoding="utf-8")
    path = write_manifest(tmp_path, valid_manifest())
    result = evaluate_promotion_bootstrap_evidence(
        requested_scope=SCOPE,
        manifest_path=path,
        implementation_file_path=fake_impl,
        ancestry_checker=lambda commit: True,
    )
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_DIGEST_MISMATCH


def test_recomputing_digest_after_a_genuine_field_change_accepts(tmp_path: Path) -> None:
    """A deliberate, consistent edit (new digest recomputed to match new
    fields) is exactly how a real re-approval would look, and is accepted --
    proving the digest is a real self-consistency check, not a fixed
    constant that merely happens to reject edits."""
    new_reference = "docs/ops/native_short_sol_bootstrap_promotion_approval_v2.md"
    manifest = valid_manifest(
        approval_reference=new_reference,
        approval_evidence_digest=_digest(approval_reference=new_reference),
    )
    path = write_manifest(tmp_path, manifest)
    result = _evaluate(path)
    assert result.accepted is True


# --------------------------------------------------------------------------- #
# Scope matching                                                              #
# --------------------------------------------------------------------------- #


def test_scope_mismatch_fails_closed(tmp_path: Path) -> None:
    path = write_manifest(tmp_path, valid_manifest())
    other_scope = {**CANONICAL_SCOPE_FIXED_FIELDS, "symbol": "ETH"}
    result = _evaluate(path, scope=other_scope)
    assert result.accepted is False
    assert result.reason == REASON_SCOPE_MISMATCH


# --------------------------------------------------------------------------- #
# Ancestry verification                                                       #
# --------------------------------------------------------------------------- #


def test_ancestry_required_and_satisfied_accepts(tmp_path: Path) -> None:
    path = write_manifest(tmp_path, valid_manifest())
    result = _evaluate(path, require_ancestry=True, ancestry_checker=lambda commit: True)
    assert result.accepted is True
    assert result.reason == REASON_EVIDENCE_ACCEPTED


def test_ancestry_required_and_not_satisfied_fails_closed(tmp_path: Path) -> None:
    path = write_manifest(tmp_path, valid_manifest())
    result = _evaluate(path, require_ancestry=True, ancestry_checker=lambda commit: False)
    assert result.accepted is False
    assert result.reason == REASON_IMPLEMENTATION_COMMIT_NOT_ANCESTOR


def test_ancestry_checker_exception_fails_closed(tmp_path: Path) -> None:
    def _raise(commit: str) -> bool:
        raise RuntimeError("git unavailable")

    path = write_manifest(tmp_path, valid_manifest())
    result = _evaluate(path, require_ancestry=True, ancestry_checker=_raise)
    assert result.accepted is False
    assert result.reason == REASON_ANCESTRY_CHECK_UNAVAILABLE


def test_ancestry_check_never_compares_head_equality(tmp_path: Path) -> None:
    """The ancestry checker receives only the approved commit; it is not
    asked to prove HEAD equals anything, and a checker that would only
    return True for an *equal* HEAD (never a descendant) is exactly the
    wrong contract -- this test proves the evaluator accepts an ancestry
    checker that returns True for a genuinely different, descendant HEAD,
    i.e. ancestry, not equality, is what is being verified."""
    path = write_manifest(tmp_path, valid_manifest())
    calls: list[str] = []

    def _ancestor_only(commit: str) -> bool:
        calls.append(commit)
        return commit == TEST_COMMIT  # true regardless of what HEAD "is"

    result = _evaluate(path, require_ancestry=True, ancestry_checker=_ancestor_only)
    assert result.accepted is True
    assert calls == [TEST_COMMIT]


def test_ancestry_not_required_skips_the_check_entirely(tmp_path: Path) -> None:
    path = write_manifest(tmp_path, valid_manifest())

    def _fail(commit: str) -> bool:
        raise AssertionError("ancestry checker must not be called")

    result = _evaluate(path, require_ancestry=False, ancestry_checker=_fail)
    assert result.accepted is True
