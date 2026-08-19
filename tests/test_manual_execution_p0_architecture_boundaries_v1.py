"""
Architecture-boundary tests for the P0 manual execution ladder safety
remediation (see
docs/architecture/manual_execution_ladder_future_readiness_audit_v1.md and
docs/todo/manual_execution_ladder_future_readiness_backlog_v1.md).

These mirror the existing repository pattern of import-graph boundary tests
(e.g. tests/test_account_asset_management_v1.py::
test_no_decision_gate_execution_planner_executor_imports) rather than
inventing a new checking style.
"""
from __future__ import annotations

import ast
import pathlib

import pytest


_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _imported_module_names(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _all_py_files(rel_dir: str) -> list[pathlib.Path]:
    return sorted((_REPO_ROOT / rel_dir).rglob("*.py"))


class TestSelectionEngineNeverConsumesAccountAwareP0Modules:
    """selection_engine must remain market-only and account-agnostic: it
    must never import the new FREE_BASE_QUANTITY resolver, the SELL
    reservation model, or the research-provenance override module, all of
    which are account-aware or governance-scoped by construction."""

    _FORBIDDEN_MODULES = (
        "src.decision_gate.free_base_quantity_v1",
        "src.decision_gate.sell_reservation_v1",
        "src.decision_gate.research_provenance_v1",
    )

    def test_selection_engine_does_not_import_new_p0_modules(self) -> None:
        selection_dir = _REPO_ROOT / "src" / "selection"
        if not selection_dir.exists():
            pytest.skip("src/selection not present in this checkout")

        for path in selection_dir.rglob("*.py"):
            imported = _imported_module_names(path)
            for forbidden in self._FORBIDDEN_MODULES:
                assert forbidden not in imported, (
                    f"{path.relative_to(_REPO_ROOT)} imports {forbidden}, "
                    "which is account-aware/governance-scoped and must not "
                    "be reachable from selection_engine"
                )


class TestSelectionEngineNeverImportsOperatorIntent:
    """selection_engine must stay account-agnostic (Issue #262/#254 Phase 1):
    it must never import the operator_intent package, which is account-scoped
    operator-preference state, not market data."""

    def test_selection_engine_does_not_import_operator_intent(self) -> None:
        selection_dir = _REPO_ROOT / "src" / "selection"
        if not selection_dir.exists():
            pytest.skip("src/selection not present in this checkout")

        for path in selection_dir.rglob("*.py"):
            imported = _imported_module_names(path)
            for module_name in imported:
                assert not module_name.startswith("src.operator_intent"), (
                    f"{path.relative_to(_REPO_ROOT)} imports {module_name}, "
                    "which is account-scoped operator-intent state and must "
                    "not be reachable from selection_engine"
                )


class TestResearchProvenanceCannotReachSelectionOrDecisionScoring:
    """The research-provenance module's selection_weight/decision_weight
    fields must never be consumed as scoring input by decision_gate's own
    scoring/decision functions. This is enforced two ways: (1) DB-level
    CHECK constraints force both fields to 0 (see the migration), and (2) no
    decision_gate scoring module imports research_provenance_v1 at all."""

    _DECISION_GATE_SCORING_MODULES = (
        "decision_gate_v1.py",
        "sell_intent_policy_v1.py",
    )

    def test_decision_gate_scoring_modules_do_not_import_research_provenance(self) -> None:
        decision_gate_dir = _REPO_ROOT / "src" / "decision_gate"
        for filename in self._DECISION_GATE_SCORING_MODULES:
            path = decision_gate_dir / filename
            if not path.exists():
                continue
            imported = _imported_module_names(path)
            assert "src.decision_gate.research_provenance_v1" not in imported, (
                f"{filename} must not import research_provenance_v1 — "
                "research overrides must never become scoring input"
            )

    def test_migration_enforces_zero_weights_and_no_live_permission(self) -> None:
        migration = (
            _REPO_ROOT
            / "db/migrations/20260725_manual_execution_ladder_p0_safety_v1.sql"
        ).read_text()
        assert "chk_execution_research_provenance_weights_zero" in migration
        assert "selection_weight = 0 AND decision_weight = 0" in migration
        assert "chk_execution_research_provenance_live_permission_off" in migration
        assert "live_permission = 0" in migration


class TestNoParallelReservationPath:
    """Do not create a parallel SELL-reservation path: exactly one module
    may write execution_sell_reservation.reservation_state."""

    def test_only_sell_reservation_module_updates_the_reservation_table(self) -> None:
        offenders = []
        for path in _all_py_files("src"):
            if path.name == "sell_reservation_v1.py":
                continue
            text = path.read_text()
            if "execution_sell_reservation" in text and "UPDATE" in text.upper():
                offenders.append(str(path.relative_to(_REPO_ROOT)))
        assert offenders == [], (
            f"unexpected writers of execution_sell_reservation: {offenders}"
        )


class TestExecutionPlannerDoesNotFetchPrivateBrokerState:
    """execution_planner must consume only an approved immutable quantity
    snapshot (FreeBaseQuantityResult); it must not call the broker's
    private balance/order endpoints itself."""

    def test_execution_planner_package_does_not_call_private_bitvavo_methods(self) -> None:
        forbidden_calls = ("get_balance(", "get_open_orders(")
        offenders = []
        for path in _all_py_files("src/execution_planner"):
            text = path.read_text()
            for call in forbidden_calls:
                if call in text:
                    offenders.append(f"{path.relative_to(_REPO_ROOT)}::{call}")
        assert offenders == [], (
            f"execution_planner must not call private broker methods: {offenders}"
        )


class TestExecutorHandoffBoundary:
    """Issue #206: the executor handoff/credential-scope boundary must stay
    reachable only from the executor lane, and the executor lane itself must
    never call a broker directly."""

    _FORBIDDEN_HANDOFF_MODULES = (
        "src.executor.execution_handoff_v1",
        "src.executor.execution_credential_scope_v1",
        "src.executor.manual_execution_handoff_v1",
        "src.executor.manual_execution_credential_scope_v1",
    )

    _NON_EXECUTOR_DIRS = (
        "src/selection",
        "src/execution_planner",
        "src/decision_gate",
        "src/reporting",
        "src/advice",
        "src/trade_setup_filter",
    )

    def test_no_non_executor_layer_imports_the_handoff_boundary(self) -> None:
        offenders = []
        for rel_dir in self._NON_EXECUTOR_DIRS:
            directory = _REPO_ROOT / rel_dir
            if not directory.exists():
                continue
            for path in directory.rglob("*.py"):
                imported = _imported_module_names(path)
                for forbidden in self._FORBIDDEN_HANDOFF_MODULES:
                    if (
                        path.relative_to(_REPO_ROOT).as_posix()
                        == "src/execution_planner/automatic_exit_execution_handoff_application_v1.py"
                        and forbidden == "src.executor.execution_handoff_v1"
                    ):
                        # Canonical #392 -> #206 composition seam only.
                        continue
                    if forbidden in imported:
                        offenders.append(f"{path.relative_to(_REPO_ROOT)} imports {forbidden}")
        assert offenders == [], (
            f"only src/executor may reach the executor handoff boundary: {offenders}"
        )

    def test_handoff_and_credential_scope_modules_never_import_a_broker_client(self) -> None:
        forbidden_modules = (
            "src.execution.bitvavo_client",
            "src.market_data.bitvavo_public_client_v1",
            "src.market_rules.bitvavo_venue_adapter_v1",
        )
        for filename in (
            "execution_handoff_v1.py",
            "execution_credential_scope_v1.py",
            "manual_execution_handoff_v1.py",
            "manual_execution_credential_scope_v1.py",
        ):
            path = _REPO_ROOT / "src" / "executor" / filename
            imported = _imported_module_names(path)
            for forbidden in forbidden_modules:
                assert forbidden not in imported, f"{filename} must not import {forbidden}"

    def test_credential_scope_resolver_never_selects_secret_columns(self) -> None:
        path = _REPO_ROOT / "src" / "executor" / "execution_credential_scope_v1.py"
        tree = ast.parse(path.read_text())
        sql_block = None
        for node in tree.body:
            if (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == "_SCOPE_SELECT"
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                sql_block = node.value.value
                break
        assert sql_block is not None, "canonical credential scope SELECT must be statically defined"
        forbidden_columns = ("encrypted_envelope", "credential_fingerprint", "api_key", "api_secret", "key_version")
        for column in forbidden_columns:
                assert column not in sql_block, f"credential scope SELECT must never read {column}"

    def test_manual_credential_scope_is_compatibility_only(self) -> None:
        path = _REPO_ROOT / "src" / "executor" / "manual_execution_credential_scope_v1.py"
        imported = _imported_module_names(path)
        assert imported == {"src.executor.execution_credential_scope_v1"}

    def test_migration_denies_live_and_enforces_single_writer(self) -> None:
        migration = (
            _REPO_ROOT / "db/migrations/20260812_manual_execution_executor_handoff_v1.sql"
        ).read_text()
        assert "chk_meeh_executor_mode" in migration
        assert "'DRY_RUN', 'PAPER', 'LIVE_DISABLED'" in migration
        assert "UNIQUE KEY uq_meeh_plan_snapshot" in migration
        assert "MANUAL_EXECUTION_EXECUTOR_HANDOFF_ALREADY_TERMINAL" in migration
        assert "MANUAL_EXECUTION_EXECUTOR_HANDOFF_IDENTITY_IS_IMMUTABLE" in migration
        assert "MANUAL_EXECUTION_EXECUTOR_HANDOFF_INVALID_CLAIM_TRANSITION" in migration
        assert "chk_ecb_binding_status" in migration
        assert "chk_ecb_permission_scope" in migration
        assert "fk_ecb_credential_identity" in migration
        assert "uq_tac_credential_identity_v1" in migration
