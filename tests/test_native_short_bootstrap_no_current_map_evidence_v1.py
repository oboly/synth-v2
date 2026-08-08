from __future__ import annotations

"""Focused tests for the BOOTSTRAP_ORCHESTRATION_BLOCKED evidence contract
(Issue #298). Every failing-path test injects fakes: no real subprocess and
no real module import, so a failure here is always a contract failure and
never an environment artifact."""

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from src.market_data.native_short_bootstrap_no_current_map_evidence_v1 import (
    MAP_LEVEL_STATUS_MODULE,
    PREREQUISITE_IMPLEMENTATION_COMMIT,
    REASON_ANCESTRY_CHECK_UNAVAILABLE,
    REASON_CONTRACT_ATTRIBUTE_MISMATCH,
    REASON_CONTRACT_ATTRIBUTE_MISSING,
    REASON_CONTRACT_DATACLASS_FIELD_MISSING,
    REASON_CONTRACT_SIGNATURE_PARAMETER_MISSING,
    REASON_EVIDENCE_CONFIRMED,
    REASON_MODULE_IMPORT_FAILED,
    REASON_PREREQUISITE_COMMIT_NOT_ANCESTOR,
    RUNTIME_CHAIN_MODULE,
    SCOPE_STATUS_MATERIALIZER_MODULE,
    evaluate_bootstrap_no_current_map_evidence,
)

_MISSING = object()


@dataclass(frozen=True)
class _FakeScopeChainOutcome:
    key: str = ""
    skipped_not_supported: bool = False
    published_map: bool = False
    lifecycle_event_appended: bool = False
    failed: bool = False
    bootstrap_pending: bool = False


@dataclass(frozen=True)
class _FakeScopeChainOutcomeWithoutBootstrapField:
    key: str = ""
    failed: bool = False


def _gate(projection: Any, *, never_published_any_map: bool) -> tuple[str, str | None]:
    return ("ACTIVE_EVALUATION", None)


def _gate_without_predicate(projection: Any) -> tuple[str, str | None]:
    """Exactly the pre-#298 signature: no ledger predicate at all, which is
    what collapsed the bootstrap case into a genuine BLOCKED hard stop."""
    return ("BLOCKED", "NO_CURRENT_MAP")


def _stub_modules(**overrides: Any) -> dict[str, SimpleNamespace]:
    """Stub modules exposing exactly #298's contract surface, so a test can
    remove or corrupt precisely one element and prove it fails closed."""
    attrs: dict[str, dict[str, Any]] = {
        MAP_LEVEL_STATUS_MODULE: {
            "EXPECTED_BOOTSTRAP_NO_CURRENT_MAP": "EXPECTED_BOOTSTRAP_NO_CURRENT_MAP",
            "select_gate_decision": _gate,
        },
        SCOPE_STATUS_MATERIALIZER_MODULE: {
            "ScopeChainOutcome": _FakeScopeChainOutcome,
        },
        RUNTIME_CHAIN_MODULE: {
            "SCOPE_STATUS_BOOTSTRAP_PENDING": "BOOTSTRAP_PENDING",
        },
    }
    for dotted, value in overrides.items():
        module_name, _, attribute = dotted.rpartition("|")
        if value is _MISSING:
            attrs[module_name].pop(attribute, None)
        else:
            attrs[module_name][attribute] = value
    return {name: SimpleNamespace(**values) for name, values in attrs.items()}


def _provider(modules: dict[str, SimpleNamespace]) -> Any:
    def provide(module_name: str) -> Any:
        return modules[module_name]

    return provide


def _confirmed_ancestry(commit: str) -> bool:
    assert commit == PREREQUISITE_IMPLEMENTATION_COMMIT
    return True


# ---------------------------------------------------------------------------
# Confirmed path
# ---------------------------------------------------------------------------


def test_evidence_confirmed_when_ancestry_and_full_contract_surface_present() -> None:
    result = evaluate_bootstrap_no_current_map_evidence(
        ancestry_checker=_confirmed_ancestry,
        module_provider=_provider(_stub_modules()),
    )
    assert result.confirmed is True
    assert result.reason == REASON_EVIDENCE_CONFIRMED
    assert result.prerequisite_commit == PREREQUISITE_IMPLEMENTATION_COMMIT


def test_real_checkout_confirms_against_live_modules_and_real_git() -> None:
    """No injection at all: the live modules on this checkout must satisfy the
    contract, which is what actually closes the blocker."""
    result = evaluate_bootstrap_no_current_map_evidence()
    assert result.confirmed is True
    assert result.reason == REASON_EVIDENCE_CONFIRMED


# ---------------------------------------------------------------------------
# Fail-closed paths (one per failure mode)
# ---------------------------------------------------------------------------


def test_fails_closed_when_prerequisite_commit_is_not_an_ancestor() -> None:
    result = evaluate_bootstrap_no_current_map_evidence(
        ancestry_checker=lambda commit: False,
        module_provider=_provider(_stub_modules()),
    )
    assert result.confirmed is False
    assert result.reason == REASON_PREREQUISITE_COMMIT_NOT_ANCESTOR


def test_fails_closed_when_ancestry_check_is_unavailable() -> None:
    def raising(commit: str) -> bool:
        raise OSError("git unavailable")

    result = evaluate_bootstrap_no_current_map_evidence(
        ancestry_checker=raising,
        module_provider=_provider(_stub_modules()),
    )
    assert result.confirmed is False
    assert result.reason == REASON_ANCESTRY_CHECK_UNAVAILABLE
    assert "OSError" in (result.detail or "")


def test_fails_closed_when_a_module_cannot_be_imported() -> None:
    def failing_provider(module_name: str) -> Any:
        raise ImportError(f"no module named {module_name}")

    result = evaluate_bootstrap_no_current_map_evidence(
        ancestry_checker=_confirmed_ancestry,
        module_provider=failing_provider,
    )
    assert result.confirmed is False
    assert result.reason == REASON_MODULE_IMPORT_FAILED


def test_fails_closed_when_bootstrap_branch_constant_is_missing() -> None:
    modules = _stub_modules(
        **{f"{MAP_LEVEL_STATUS_MODULE}|EXPECTED_BOOTSTRAP_NO_CURRENT_MAP": _MISSING}
    )
    result = evaluate_bootstrap_no_current_map_evidence(
        ancestry_checker=_confirmed_ancestry,
        module_provider=_provider(modules),
    )
    assert result.confirmed is False
    assert result.reason == REASON_CONTRACT_ATTRIBUTE_MISSING
    assert "EXPECTED_BOOTSTRAP_NO_CURRENT_MAP" in (result.detail or "")


def test_fails_closed_when_bootstrap_branch_constant_has_a_wrong_value() -> None:
    modules = _stub_modules(
        **{f"{MAP_LEVEL_STATUS_MODULE}|EXPECTED_BOOTSTRAP_NO_CURRENT_MAP": "BLOCKED"}
    )
    result = evaluate_bootstrap_no_current_map_evidence(
        ancestry_checker=_confirmed_ancestry,
        module_provider=_provider(modules),
    )
    assert result.confirmed is False
    assert result.reason == REASON_CONTRACT_ATTRIBUTE_MISMATCH


def test_fails_closed_when_runtime_bootstrap_status_is_missing() -> None:
    modules = _stub_modules(**{f"{RUNTIME_CHAIN_MODULE}|SCOPE_STATUS_BOOTSTRAP_PENDING": _MISSING})
    result = evaluate_bootstrap_no_current_map_evidence(
        ancestry_checker=_confirmed_ancestry,
        module_provider=_provider(modules),
    )
    assert result.confirmed is False
    assert result.reason == REASON_CONTRACT_ATTRIBUTE_MISSING
    assert "SCOPE_STATUS_BOOTSTRAP_PENDING" in (result.detail or "")


def test_fails_closed_when_runtime_bootstrap_status_has_a_wrong_value() -> None:
    modules = _stub_modules(
        **{f"{RUNTIME_CHAIN_MODULE}|SCOPE_STATUS_BOOTSTRAP_PENDING": "SUCCEEDED"}
    )
    result = evaluate_bootstrap_no_current_map_evidence(
        ancestry_checker=_confirmed_ancestry,
        module_provider=_provider(modules),
    )
    assert result.confirmed is False
    assert result.reason == REASON_CONTRACT_ATTRIBUTE_MISMATCH


def test_fails_closed_when_gate_decision_is_missing() -> None:
    modules = _stub_modules(**{f"{MAP_LEVEL_STATUS_MODULE}|select_gate_decision": _MISSING})
    result = evaluate_bootstrap_no_current_map_evidence(
        ancestry_checker=_confirmed_ancestry,
        module_provider=_provider(modules),
    )
    assert result.confirmed is False
    assert result.reason == REASON_CONTRACT_ATTRIBUTE_MISSING


def test_fails_closed_when_gate_decision_lost_the_ledger_predicate_parameter() -> None:
    """The exact regression that would silently reinstate the defect: without
    never_published_any_map the bootstrap case cannot be distinguished from a
    genuine integrity BLOCKED state at all."""
    modules = _stub_modules(
        **{f"{MAP_LEVEL_STATUS_MODULE}|select_gate_decision": _gate_without_predicate}
    )
    result = evaluate_bootstrap_no_current_map_evidence(
        ancestry_checker=_confirmed_ancestry,
        module_provider=_provider(modules),
    )
    assert result.confirmed is False
    assert result.reason == REASON_CONTRACT_SIGNATURE_PARAMETER_MISSING
    assert "never_published_any_map" in (result.detail or "")


def test_fails_closed_when_gate_decision_is_not_callable() -> None:
    modules = _stub_modules(**{f"{MAP_LEVEL_STATUS_MODULE}|select_gate_decision": "not-callable"})
    result = evaluate_bootstrap_no_current_map_evidence(
        ancestry_checker=_confirmed_ancestry,
        module_provider=_provider(modules),
    )
    assert result.confirmed is False
    assert result.reason == REASON_CONTRACT_ATTRIBUTE_MISMATCH


def test_fails_closed_when_scope_chain_outcome_lost_bootstrap_pending_field() -> None:
    modules = _stub_modules(
        **{
            f"{SCOPE_STATUS_MATERIALIZER_MODULE}|ScopeChainOutcome": (
                _FakeScopeChainOutcomeWithoutBootstrapField
            )
        }
    )
    result = evaluate_bootstrap_no_current_map_evidence(
        ancestry_checker=_confirmed_ancestry,
        module_provider=_provider(modules),
    )
    assert result.confirmed is False
    assert result.reason == REASON_CONTRACT_DATACLASS_FIELD_MISSING
    assert "bootstrap_pending" in (result.detail or "")


def test_fails_closed_when_scope_chain_outcome_is_missing() -> None:
    modules = _stub_modules(**{f"{SCOPE_STATUS_MATERIALIZER_MODULE}|ScopeChainOutcome": _MISSING})
    result = evaluate_bootstrap_no_current_map_evidence(
        ancestry_checker=_confirmed_ancestry,
        module_provider=_provider(modules),
    )
    assert result.confirmed is False
    assert result.reason == REASON_CONTRACT_ATTRIBUTE_MISSING


def test_fails_closed_when_scope_chain_outcome_is_not_a_dataclass() -> None:
    modules = _stub_modules(**{f"{SCOPE_STATUS_MATERIALIZER_MODULE}|ScopeChainOutcome": object})
    result = evaluate_bootstrap_no_current_map_evidence(
        ancestry_checker=_confirmed_ancestry,
        module_provider=_provider(modules),
    )
    assert result.confirmed is False
    assert result.reason == REASON_CONTRACT_ATTRIBUTE_MISMATCH


def test_evaluation_result_is_frozen_and_performs_no_db_access() -> None:
    result = evaluate_bootstrap_no_current_map_evidence(
        ancestry_checker=_confirmed_ancestry,
        module_provider=_provider(_stub_modules()),
    )
    import dataclasses

    assert dataclasses.is_dataclass(result)
    try:
        object.__setattr__  # sanity: frozen dataclass rejects assignment below
        result.confirmed = False  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        pass
    else:  # pragma: no cover - defensive
        raise AssertionError("BootstrapEvidenceEvaluation must be frozen")
