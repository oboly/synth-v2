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
    REASON_MANIFEST_DUPLICATE_SCOPE_ENTRIES,
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
OTHER_TEST_COMMIT = "b" * 40
SCOPE = {**CANONICAL_SCOPE_FIXED_FIELDS, "symbol": "SOL"}
ETH_SCOPE = {**CANONICAL_SCOPE_FIXED_FIELDS, "symbol": "ETH"}
APPROVAL_REFERENCE = "docs/ops/native_short_sol_bootstrap_promotion_approval_v1.md"
APPROVED_AT_UTC = "2026-08-01T00:00:00Z"

_IMPLEMENTATION_FILE_SHA256 = hash_implementation_file()


def _digest(*, scope: dict = SCOPE, **overrides: object) -> str:
    payload = {
        "accepted": True,
        "scope": dict(scope),
        "approval_reference": APPROVAL_REFERENCE,
        "approved_at_utc": APPROVED_AT_UTC,
        "approved_implementation_commit": TEST_COMMIT,
        "implementation_file_sha256": _IMPLEMENTATION_FILE_SHA256,
    }
    payload.update(overrides)
    return compute_approval_evidence_digest(**payload)  # type: ignore[arg-type]


def valid_entry(**overrides: object) -> dict:
    entry = {
        "accepted": True,
        "scope": dict(SCOPE),
        "approval_reference": APPROVAL_REFERENCE,
        "approved_at_utc": APPROVED_AT_UTC,
        "approved_implementation_commit": TEST_COMMIT,
        "approval_evidence_digest": _digest(),
    }
    entry.update(overrides)
    return entry


def valid_manifest(*, entries: list | None = None, **top_overrides: object) -> dict:
    manifest = {
        "acceptance_schema_version": REQUIRED_MANIFEST_SCHEMA_VERSION,
        "bootstrap_contract_version": BOOTSTRAP_CONTRACT_VERSION,
        "bootstrap_contract_digest": compute_bootstrap_contract_digest(),
        "entries": entries if entries is not None else [valid_entry()],
    }
    manifest.update(top_overrides)
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
    """The checked-in manifest names SOL, is accepted:true, and its
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


def test_shipped_default_manifest_fails_closed_for_every_unapproved_symbol() -> None:
    from src.market_data.native_short_promotion_bootstrap_evidence_v1 import (
        DEFAULT_BOOTSTRAP_MANIFEST_PATH,
    )

    for symbol in ("BTC", "DOGE", "FET"):
        other_scope = {**CANONICAL_SCOPE_FIXED_FIELDS, "symbol": symbol}
        result = evaluate_promotion_bootstrap_evidence(
            requested_scope=other_scope, manifest_path=DEFAULT_BOOTSTRAP_MANIFEST_PATH
        )
        assert result.accepted is False
        assert result.reason == REASON_SCOPE_MISMATCH


_BATCH_16_SYMBOLS = (
    "SUI", "SHIB", "PEPE", "HBAR", "AAVE", "BNB", "ICP", "LDO",
    "XPL", "VET", "ALGO", "CC", "HOT", "FLOKI", "HNT", "MOG",
)


def test_shipped_default_manifest_accepts_each_of_the_16_batch_symbols_with_real_ancestry() -> None:
    """Each of the 16 bounded-batch symbols resolves exactly once against the
    real, checked-in manifest, using the real default ancestry checker (no
    injection) -- proving the batch's entries are genuinely independently
    evidenced and accepted, not merely structurally present."""
    from src.market_data.native_short_promotion_bootstrap_evidence_v1 import (
        DEFAULT_BOOTSTRAP_MANIFEST_PATH,
    )

    for symbol in _BATCH_16_SYMBOLS:
        scope = {**CANONICAL_SCOPE_FIXED_FIELDS, "symbol": symbol}
        result = evaluate_promotion_bootstrap_evidence(
            requested_scope=scope, manifest_path=DEFAULT_BOOTSTRAP_MANIFEST_PATH
        )
        assert result.accepted is True, (symbol, result.reason)
        assert result.reason == REASON_EVIDENCE_ACCEPTED
        assert result.symbol == symbol


def test_shipped_default_manifest_batch_evaluation_is_deterministic_on_rerun() -> None:
    """Evaluating the same shipped manifest twice for the same scope returns
    an identical result -- rerun/read is deterministic, not a function of
    evaluation order or hidden state."""
    from src.market_data.native_short_promotion_bootstrap_evidence_v1 import (
        DEFAULT_BOOTSTRAP_MANIFEST_PATH,
    )

    for symbol in _BATCH_16_SYMBOLS:
        scope = {**CANONICAL_SCOPE_FIXED_FIELDS, "symbol": symbol}
        first = evaluate_promotion_bootstrap_evidence(
            requested_scope=scope, manifest_path=DEFAULT_BOOTSTRAP_MANIFEST_PATH
        )
        second = evaluate_promotion_bootstrap_evidence(
            requested_scope=scope, manifest_path=DEFAULT_BOOTSTRAP_MANIFEST_PATH
        )
        assert first == second


def test_shipped_default_manifest_has_exactly_19_unique_symbols() -> None:
    """Guards against silent drift: the checked-in manifest must name exactly
    SOL, ETH, XRP, and the 16 batch symbols -- no fewer, no extra, no
    duplicate."""
    from src.market_data.native_short_promotion_bootstrap_evidence_v1 import (
        DEFAULT_BOOTSTRAP_MANIFEST_PATH,
    )

    raw = json.loads(DEFAULT_BOOTSTRAP_MANIFEST_PATH.read_text(encoding="utf-8"))
    symbols = [entry["scope"]["symbol"] for entry in raw["entries"]]
    assert len(symbols) == len(set(symbols)) == 19
    assert set(symbols) == {"SOL", "ETH", "XRP", *_BATCH_16_SYMBOLS}


def test_shipped_default_manifest_digest_matches_live_contract_and_content() -> None:
    from src.market_data.native_short_promotion_bootstrap_evidence_v1 import (
        DEFAULT_BOOTSTRAP_MANIFEST_PATH,
    )

    raw = json.loads(DEFAULT_BOOTSTRAP_MANIFEST_PATH.read_text(encoding="utf-8"))
    assert raw["bootstrap_contract_digest"] == compute_bootstrap_contract_digest()
    assert raw["acceptance_schema_version"] == REQUIRED_MANIFEST_SCHEMA_VERSION
    assert raw["bootstrap_contract_version"] == BOOTSTRAP_CONTRACT_VERSION
    assert isinstance(raw["entries"], list) and raw["entries"]
    seen_symbols: set[str] = set()
    for entry in raw["entries"]:
        assert entry["accepted"] is True
        symbol = entry["scope"]["symbol"]
        assert symbol not in seen_symbols
        seen_symbols.add(symbol)
        assert entry["approval_evidence_digest"] == compute_approval_evidence_digest(
            accepted=True,
            scope=entry["scope"],
            approval_reference=entry["approval_reference"],
            approved_at_utc=entry["approved_at_utc"],
            approved_implementation_commit=entry["approved_implementation_commit"],
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


def test_v1_single_scope_manifest_shape_no_longer_parses(tmp_path: Path) -> None:
    """The legacy single-scope object shape (pre-migration) fails closed
    under the v2 schema version check instead of being silently
    reinterpreted -- proves the schema bump is load-bearing."""
    legacy_shaped = {
        "acceptance_schema_version": "native_short_promotion_bootstrap_manifest_v1",
        "bootstrap_contract_version": BOOTSTRAP_CONTRACT_VERSION,
        "bootstrap_contract_digest": compute_bootstrap_contract_digest(),
        "accepted": True,
        "scope": dict(SCOPE),
        "approval_reference": APPROVAL_REFERENCE,
        "approved_at_utc": APPROVED_AT_UTC,
        "approved_implementation_commit": TEST_COMMIT,
        "approval_evidence_digest": _digest(),
    }
    path = write_manifest(tmp_path, legacy_shaped)
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


def test_entries_missing_fails_closed(tmp_path: Path) -> None:
    manifest = valid_manifest()
    del manifest["entries"]
    path = write_manifest(tmp_path, manifest)
    result = _evaluate(path)
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_MALFORMED


def test_entries_empty_list_fails_closed(tmp_path: Path) -> None:
    path = write_manifest(tmp_path, valid_manifest(entries=[]))
    result = _evaluate(path)
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_MALFORMED


def test_entries_not_a_list_fails_closed(tmp_path: Path) -> None:
    path = write_manifest(tmp_path, valid_manifest(entries={"symbol": "SOL"}))  # type: ignore[arg-type]
    result = _evaluate(path)
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_MALFORMED


def test_entry_not_a_mapping_fails_closed(tmp_path: Path) -> None:
    path = write_manifest(tmp_path, valid_manifest(entries=["not-a-mapping"]))
    result = _evaluate(path)
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_MALFORMED


def test_not_accepted_fails_closed(tmp_path: Path) -> None:
    path = write_manifest(tmp_path, valid_manifest(entries=[valid_entry(accepted=False)]))
    result = _evaluate(path)
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_NOT_ACCEPTED


def test_incomplete_scope_fails_closed(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path, valid_manifest(entries=[valid_entry(scope={"symbol": "SOL"})])
    )
    result = _evaluate(path)
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_SCOPE_INVALID


def test_lowercase_symbol_fails_closed(tmp_path: Path) -> None:
    other_scope = {**CANONICAL_SCOPE_FIXED_FIELDS, "symbol": "sol"}
    path = write_manifest(tmp_path, valid_manifest(entries=[valid_entry(scope=other_scope)]))
    result = _evaluate(path, scope=other_scope)
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_SCOPE_INVALID


def test_missing_approval_reference_fails_closed(tmp_path: Path) -> None:
    path = write_manifest(tmp_path, valid_manifest(entries=[valid_entry(approval_reference="")]))
    result = _evaluate(path)
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_MISSING_APPROVAL_REFERENCE


def test_invalid_approved_at_fails_closed(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path, valid_manifest(entries=[valid_entry(approved_at_utc="not-a-timestamp")])
    )
    result = _evaluate(path)
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_APPROVED_AT_INVALID


def test_invalid_implementation_commit_fails_closed(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path,
        valid_manifest(entries=[valid_entry(approved_implementation_commit="not-a-sha")]),
    )
    result = _evaluate(path)
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_IMPLEMENTATION_COMMIT_INVALID


# --------------------------------------------------------------------------- #
# Approval-evidence digest (tamper detection)                                 #
# --------------------------------------------------------------------------- #


def test_wrong_approval_evidence_digest_fails_closed(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path, valid_manifest(entries=[valid_entry(approval_evidence_digest="0" * 64)])
    )
    result = _evaluate(path)
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_DIGEST_MISMATCH


def test_tampered_scope_without_digest_update_fails_closed(tmp_path: Path) -> None:
    """A manifest entry edited to name a different scope, without
    recomputing the approval-evidence digest, is detected as tampered and
    fails closed -- it is not enough to change the displayed scope alone."""
    tampered_scope = {**CANONICAL_SCOPE_FIXED_FIELDS, "symbol": "ETH"}
    path = write_manifest(tmp_path, valid_manifest(entries=[valid_entry(scope=tampered_scope)]))
    result = _evaluate(path, scope=tampered_scope)
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_DIGEST_MISMATCH


def test_tampered_approval_reference_without_digest_update_fails_closed(
    tmp_path: Path,
) -> None:
    path = write_manifest(
        tmp_path, valid_manifest(entries=[valid_entry(approval_reference="docs/ops/forged.md")])
    )
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
    entry = valid_entry(
        approval_reference=new_reference,
        approval_evidence_digest=_digest(approval_reference=new_reference),
    )
    path = write_manifest(tmp_path, valid_manifest(entries=[entry]))
    result = _evaluate(path)
    assert result.accepted is True


# --------------------------------------------------------------------------- #
# Multi-entry approval list (no wildcard, independent per-scope evidence)     #
# --------------------------------------------------------------------------- #


def test_multiple_explicit_entries_each_evaluate_independently(tmp_path: Path) -> None:
    """A manifest naming two exact, independently evidenced scopes accepts
    each one on its own merits -- neither entry's evidence leaks into or
    substitutes for the other's evaluation."""
    sol_entry = valid_entry()
    eth_entry = valid_entry(
        scope=dict(ETH_SCOPE),
        approved_implementation_commit=OTHER_TEST_COMMIT,
        approval_evidence_digest=_digest(
            scope=ETH_SCOPE, approved_implementation_commit=OTHER_TEST_COMMIT
        ),
    )
    path = write_manifest(tmp_path, valid_manifest(entries=[sol_entry, eth_entry]))

    sol_result = _evaluate(path, scope=SCOPE)
    assert sol_result.accepted is True
    assert sol_result.symbol == "SOL"
    assert sol_result.approved_implementation_commit == TEST_COMMIT

    eth_result = _evaluate(path, scope=ETH_SCOPE)
    assert eth_result.accepted is True
    assert eth_result.symbol == "ETH"
    assert eth_result.approved_implementation_commit == OTHER_TEST_COMMIT


def test_one_entry_unaccepted_does_not_block_another_accepted_entry(tmp_path: Path) -> None:
    sol_entry = valid_entry(accepted=False)
    eth_entry = valid_entry(
        scope=dict(ETH_SCOPE),
        approval_evidence_digest=_digest(scope=ETH_SCOPE),
    )
    path = write_manifest(tmp_path, valid_manifest(entries=[sol_entry, eth_entry]))

    assert _evaluate(path, scope=SCOPE).reason == REASON_MANIFEST_NOT_ACCEPTED
    assert _evaluate(path, scope=ETH_SCOPE).accepted is True


def test_a_third_unapproved_symbol_is_scope_mismatch_even_with_other_entries(
    tmp_path: Path,
) -> None:
    sol_entry = valid_entry()
    eth_entry = valid_entry(
        scope=dict(ETH_SCOPE), approval_evidence_digest=_digest(scope=ETH_SCOPE)
    )
    path = write_manifest(tmp_path, valid_manifest(entries=[sol_entry, eth_entry]))
    xrp_scope = {**CANONICAL_SCOPE_FIXED_FIELDS, "symbol": "XRP"}
    result = _evaluate(path, scope=xrp_scope)
    assert result.accepted is False
    assert result.reason == REASON_SCOPE_MISMATCH


def test_duplicate_symbol_entries_reject_the_whole_manifest(tmp_path: Path) -> None:
    """No wildcard/reused approval: two entries naming the same exact scope
    is a manifest-integrity defect that fails every evaluation against that
    manifest closed, not a "first match wins" resolution."""
    first = valid_entry()
    second = valid_entry(approved_implementation_commit=OTHER_TEST_COMMIT)
    path = write_manifest(tmp_path, valid_manifest(entries=[first, second]))
    result = _evaluate(path, scope=SCOPE)
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_DUPLICATE_SCOPE_ENTRIES


def test_duplicate_symbol_entries_reject_even_for_an_unrelated_requested_scope(
    tmp_path: Path,
) -> None:
    """A structurally ambiguous manifest fails closed for every request, not
    only for the specific duplicated scope."""
    first = valid_entry()
    second = valid_entry(approved_implementation_commit=OTHER_TEST_COMMIT)
    path = write_manifest(tmp_path, valid_manifest(entries=[first, second]))
    result = _evaluate(path, scope=ETH_SCOPE)
    assert result.accepted is False
    assert result.reason == REASON_MANIFEST_DUPLICATE_SCOPE_ENTRIES


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
