from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path

from src.market_data.native_short_fib_context_v1 import STATUS_AVAILABLE
from src.market_data.native_short_multi_asset_audit_v1 import (
    AuditReport,
    CandidateInput,
    CandleWindow,
    LedgerState,
    MarketMetadata,
    evaluate_candidate,
)
from src.market_data.native_short_rollout_universe_v2 import (
    derive_bulk_rollout_entries,
    is_symbol_promote_scope_ready,
    ready_symbols,
)
from src.market_data.native_short_scope_administration_v1 import (
    NativeShortScopeAdministrationOperationType as OperationType,
)


AS_OF = datetime(2026, 7, 16, 20, 0, tzinfo=UTC)
MODULE_PATH = Path("src/market_data/native_short_rollout_universe_v2.py")


def _market(symbol: str, *, eligible: bool = True) -> MarketMetadata:
    return MarketMetadata(
        asset_id=1,
        venue_market_id=1,
        market=f"{symbol}-EUR",
        asset_enabled=eligible,
        market_data_enabled=eligible,
        market_tradeable=eligible,
        db_price_precisions=(4,) if eligible else (),
    )


def _supported_ledger() -> LedgerState:
    return LedgerState(
        scope_states=("SUPPORTED",),
        map_ids=(1,),
        active_map_ids=(1,),
        generation_events=(("attempt-1", "ATTEMPT_STARTED", None), ("attempt-1", "PUBLISHED", 1)),
        published_attempt_by_map=((1, "attempt-1"),),
        lifecycle_event_count=1,
        latest_lifecycle_by_map=((1, "ACTIVATED"),),
        current_status_map_ids=(1,),
        scope_status_codes=("CURRENT_EVALUATION",),
        source_freshness_states=("SOURCE_CURRENT",),
        actionability_states=("ACTIONABLE_ACTIVE_MAP",),
    )


def _candidate(symbol: str, *, eligible: bool = True, supported: bool = False) -> CandidateInput:
    return CandidateInput(
        symbol=symbol,
        markets=(_market(symbol, eligible=eligible),),
        primary=CandleWindow(count=100, latest_close_ts_utc=AS_OF),
        supporting=CandleWindow(count=200, latest_close_ts_utc=AS_OF),
        ledger=_supported_ledger() if supported else LedgerState(),
        context_status=STATUS_AVAILABLE,
    )


def _report(*results, global_blockers: tuple[str, ...] = ()) -> AuditReport:
    evaluated = tuple(
        evaluate_candidate(candidate, as_of_utc=AS_OF, global_blockers=global_blockers)
        for candidate in results
    )
    return AuditReport(
        as_of_utc=AS_OF,
        results=evaluated,
        proposed_sequential_queue=(),
        counts={},
        writer_run_count=0,
        attributable_writer_run_count=0,
        legacy_unattributed_writer_run_count=0,
        invalid_provenance_writer_run_count=0,
        provenance_audit_run_found=True,
        provenance_audit_run_attributed=True,
        provenance_contract_implemented=True,
        attributable_production_run_observed=True,
        operational_acceptance_completed=True,
        writer_provenance_blocker_active=False,
        global_blocker_codes=global_blockers,
    )


def test_ready_symbols_includes_only_market_ready_not_yet_supported_scopes() -> None:
    report = _report(
        _candidate("ZORRO", eligible=True, supported=False),
        _candidate("AERO", eligible=True, supported=False),
        _candidate("ALREADYUP", eligible=True, supported=True),
        _candidate("NOTELIGIBLE", eligible=False, supported=False),
    )
    assert ready_symbols(report) == ("AERO", "ZORRO")


def test_derive_bulk_rollout_entries_carries_no_approval_semantics() -> None:
    report = _report(_candidate("AERO", eligible=True, supported=False))
    entries = derive_bulk_rollout_entries(report)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.symbol == "AERO"
    assert entry.operation_type == OperationType.PROMOTE_SCOPE
    assert entry.approval_reference == ""
    assert entry.note == ""


def test_ready_symbols_excludes_blocked_scopes() -> None:
    report = _report(
        _candidate("BLOCKEDSYM", eligible=True, supported=False),
        global_blockers=("WRITER_PROVENANCE_UNATTRIBUTED",),
    )
    assert ready_symbols(report) == ()
    assert derive_bulk_rollout_entries(report) == ()


def test_permanently_active_removal_contract_missing_does_not_block_promote_scope() -> None:
    """REMOVAL_CONTRACT_MISSING is permanently active (no removal-acceptance
    evidence source exists) but never gates PROMOTE_SCOPE at the real
    transaction layer, so it must not make ready_symbols permanently empty."""
    report = _report(
        _candidate("READYSYM", eligible=True, supported=False),
        global_blockers=("REMOVAL_CONTRACT_MISSING",),
    )
    assert ready_symbols(report) == ("READYSYM",)
    assert is_symbol_promote_scope_ready(report, "READYSYM") == (True, "READY")


def test_is_symbol_promote_scope_ready_true_for_ready_and_already_supported() -> None:
    report = _report(
        _candidate("READYSYM", eligible=True, supported=False),
        _candidate("SUPPORTEDSYM", eligible=True, supported=True),
        _candidate("NOTELIGIBLE", eligible=False, supported=False),
    )
    assert is_symbol_promote_scope_ready(report, "readysym") == (True, "READY")
    assert is_symbol_promote_scope_ready(report, "SUPPORTEDSYM") == (True, "ALREADY_SUPPORTED")
    eligible, _ = is_symbol_promote_scope_ready(report, "NOTELIGIBLE")
    assert eligible is False
    assert is_symbol_promote_scope_ready(report, "MISSINGSYM") == (
        False,
        "SYMBOL_NOT_IN_CANONICAL_MARKET_UNIVERSE",
    )


def test_is_symbol_promote_scope_ready_rejects_applicable_blocker() -> None:
    # WRITER_PROVENANCE_UNATTRIBUTED actually gates PROMOTE_SCOPE (unlike
    # REMOVAL_CONTRACT_MISSING, which is permanently active but never
    # applies to PROMOTE_SCOPE -- see applicable_active_global_blockers).
    report = _report(
        _candidate("READYBUTBLOCKED", eligible=True, supported=False),
        global_blockers=("WRITER_PROVENANCE_UNATTRIBUTED",),
    )
    assert is_symbol_promote_scope_ready(report, "READYBUTBLOCKED") == (False, "BLOCKED")


def test_no_account_or_execution_imports() -> None:
    forbidden = ("account", "selection", "decision_gate", "execution_planner", "executor", "broker")
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.append(node.module or "")
    assert not any(any(part in module.split(".") for part in forbidden) for module in modules)


def test_no_database_io_in_pure_module() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "conn" not in source
    assert "cursor" not in source
    assert "execute(" not in source


def test_no_approval_ceremony_in_module() -> None:
    """Regression guard: this module must not reintroduce an
    approval/universe concept on top of canonical readiness."""
    source = MODULE_PATH.read_text(encoding="utf-8")
    for forbidden_token in ("APPROVAL_REFERENCE", "approval_reference=", "universe_market_symbols"):
        assert forbidden_token not in source
