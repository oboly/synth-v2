from __future__ import annotations

"""Focused tests for the MULTI_SCOPE_FAILURE_ISOLATION_MISSING evidence
contract. Every failing-path test injects fakes: no real subprocess and no
real module import, so a failure here is always a contract failure and never
an environment artifact."""

import dataclasses
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from src.market_data.native_short_runtime_isolation_evidence_v1 import (
    ISOLATION_IMPLEMENTATION_COMMIT,
    REASON_ANCESTRY_CHECK_UNAVAILABLE,
    REASON_EVIDENCE_CONFIRMED,
    REASON_IMPLEMENTATION_COMMIT_NOT_ANCESTOR,
    REASON_RUNTIME_CONTRACT_ATTRIBUTE_MISMATCH,
    REASON_RUNTIME_CONTRACT_ATTRIBUTE_MISSING,
    REASON_RUNTIME_MODULE_IMPORT_FAILED,
    evaluate_multi_scope_failure_isolation_evidence,
)


@dataclass(frozen=True)
class _FakeScopeChainResult:
    key: str
    status: str
    detail: str | None = None


@dataclass(frozen=True)
class _FakeRuntimeResult:
    run: Any = None
    scope_results: tuple[_FakeScopeChainResult, ...] = ()


def _stub_runtime(**overrides: Any) -> SimpleNamespace:
    """A stub module exposing exactly #200's contract surface, so a test can
    remove or corrupt precisely one attribute and prove it fails closed."""
    attrs: dict[str, Any] = {
        "TRANSACTION_BOUNDARY": "exact_scope",
        "FAILURE_POLICY": "continue_on_unexpected_and_expected_not_ready_stop_on_integrity_blocked",
        "SCOPE_STATUS_SUCCEEDED": "SUCCEEDED",
        "SCOPE_STATUS_SKIPPED_NOT_SUPPORTED": "SKIPPED_NOT_SUPPORTED",
        "SCOPE_STATUS_SKIPPED_NOT_READY": "SKIPPED_NOT_READY",
        "SCOPE_STATUS_BLOCKED": "BLOCKED",
        "SCOPE_STATUS_UNEXPECTED_FAILED": "UNEXPECTED_FAILED",
        "ScopeChainResult": _FakeScopeChainResult,
        "RuntimeResult": _FakeRuntimeResult,
        "evaluate_and_project_scope": lambda *a, **k: None,
    }
    for key, value in overrides.items():
        if value is _MISSING:
            attrs.pop(key, None)
        else:
            attrs[key] = value
    return SimpleNamespace(**attrs)


_MISSING = object()


def _accept_ancestry(commit: str) -> bool:
    assert commit == ISOLATION_IMPLEMENTATION_COMMIT
    return True


def test_evidence_confirms_when_ancestry_and_every_attribute_match() -> None:
    result = evaluate_multi_scope_failure_isolation_evidence(
        ancestry_checker=_accept_ancestry,
        runtime_module_provider=_stub_runtime,
    )
    assert result.confirmed is True
    assert result.reason == REASON_EVIDENCE_CONFIRMED
    assert result.implementation_commit == ISOLATION_IMPLEMENTATION_COMMIT


def test_fails_closed_when_implementation_commit_is_not_an_ancestor() -> None:
    result = evaluate_multi_scope_failure_isolation_evidence(
        ancestry_checker=lambda commit: False,
        runtime_module_provider=_stub_runtime,
    )
    assert result.confirmed is False
    assert result.reason == REASON_IMPLEMENTATION_COMMIT_NOT_ANCESTOR


def test_fails_closed_when_ancestry_check_is_unavailable() -> None:
    """An unavailable check is never treated as a passed check."""

    def raising(commit: str) -> bool:
        raise OSError("git unavailable")

    result = evaluate_multi_scope_failure_isolation_evidence(
        ancestry_checker=raising,
        runtime_module_provider=_stub_runtime,
    )
    assert result.confirmed is False
    assert result.reason == REASON_ANCESTRY_CHECK_UNAVAILABLE


def test_fails_closed_when_runtime_module_cannot_be_imported() -> None:
    def raising() -> Any:
        raise ImportError("no such module")

    result = evaluate_multi_scope_failure_isolation_evidence(
        ancestry_checker=_accept_ancestry,
        runtime_module_provider=raising,
    )
    assert result.confirmed is False
    assert result.reason == REASON_RUNTIME_MODULE_IMPORT_FAILED


def test_fails_closed_when_a_required_attribute_is_missing() -> None:
    for name in (
        "TRANSACTION_BOUNDARY",
        "FAILURE_POLICY",
        "SCOPE_STATUS_BLOCKED",
        "ScopeChainResult",
        "RuntimeResult",
        "evaluate_and_project_scope",
    ):
        result = evaluate_multi_scope_failure_isolation_evidence(
            ancestry_checker=_accept_ancestry,
            runtime_module_provider=lambda n=name: _stub_runtime(**{n: _MISSING}),
        )
        assert result.confirmed is False, name
        assert result.reason == REASON_RUNTIME_CONTRACT_ATTRIBUTE_MISSING, name
        assert name in (result.detail or ""), name


def test_fails_closed_on_regressed_transaction_boundary_value() -> None:
    """The exact regression this evidence exists to catch: the #200 commit
    stays an ancestor forever, so only the live value can prove the guarantee
    still holds."""
    result = evaluate_multi_scope_failure_isolation_evidence(
        ancestry_checker=_accept_ancestry,
        runtime_module_provider=lambda: _stub_runtime(TRANSACTION_BOUNDARY="chain_wide"),
    )
    assert result.confirmed is False
    assert result.reason == REASON_RUNTIME_CONTRACT_ATTRIBUTE_MISMATCH
    assert "chain_wide" in (result.detail or "")


def test_fails_closed_on_wrong_valued_scope_status_or_failure_policy() -> None:
    for name, wrong in (
        ("FAILURE_POLICY", "stop_on_any_failure"),
        ("SCOPE_STATUS_SUCCEEDED", "OK"),
    ):
        result = evaluate_multi_scope_failure_isolation_evidence(
            ancestry_checker=_accept_ancestry,
            runtime_module_provider=lambda n=name, w=wrong: _stub_runtime(**{n: w}),
        )
        assert result.confirmed is False, name
        assert result.reason == REASON_RUNTIME_CONTRACT_ATTRIBUTE_MISMATCH, name


def test_fails_closed_when_scope_result_dataclass_shape_changes() -> None:
    @dataclass(frozen=True)
    class _Narrowed:
        key: str

    result = evaluate_multi_scope_failure_isolation_evidence(
        ancestry_checker=_accept_ancestry,
        runtime_module_provider=lambda: _stub_runtime(ScopeChainResult=_Narrowed),
    )
    assert result.confirmed is False
    assert result.reason == REASON_RUNTIME_CONTRACT_ATTRIBUTE_MISMATCH


def test_fails_closed_when_scope_result_is_not_a_dataclass() -> None:
    class _NotADataclass:
        key = None
        status = None
        detail = None

    result = evaluate_multi_scope_failure_isolation_evidence(
        ancestry_checker=_accept_ancestry,
        runtime_module_provider=lambda: _stub_runtime(ScopeChainResult=_NotADataclass),
    )
    assert result.confirmed is False
    assert result.reason == REASON_RUNTIME_CONTRACT_ATTRIBUTE_MISMATCH


def test_fails_closed_when_runtime_result_loses_scope_results_field() -> None:
    @dataclass(frozen=True)
    class _NoScopeResults:
        run: Any = None

    result = evaluate_multi_scope_failure_isolation_evidence(
        ancestry_checker=_accept_ancestry,
        runtime_module_provider=lambda: _stub_runtime(RuntimeResult=_NoScopeResults),
    )
    assert result.confirmed is False
    assert result.reason == REASON_RUNTIME_CONTRACT_ATTRIBUTE_MISSING
    assert "scope_results" in (result.detail or "")


def test_fails_closed_when_entrypoint_is_present_but_not_callable() -> None:
    result = evaluate_multi_scope_failure_isolation_evidence(
        ancestry_checker=_accept_ancestry,
        runtime_module_provider=lambda: _stub_runtime(evaluate_and_project_scope="nope"),
    )
    assert result.confirmed is False
    assert result.reason == REASON_RUNTIME_CONTRACT_ATTRIBUTE_MISMATCH


def test_real_default_providers_confirm_on_this_checkout() -> None:
    """The only test that touches the real git repo and the real runtime
    module: on this checkout #200 is an ancestor and the contract is intact,
    so evidence must confirm."""
    result = evaluate_multi_scope_failure_isolation_evidence()
    assert result.confirmed is True
    assert result.reason == REASON_EVIDENCE_CONFIRMED


def test_real_runtime_module_scope_result_fields_match_the_declared_contract() -> None:
    """Guards the stub against drifting from the real module's shape."""
    from src.market_data import run_native_short_scope_status_chain_v1 as runtime

    assert [f.name for f in dataclasses.fields(runtime.ScopeChainResult)] == [
        f.name for f in dataclasses.fields(_FakeScopeChainResult)
    ]
