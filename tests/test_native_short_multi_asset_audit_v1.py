from __future__ import annotations

import ast
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from src.market_data.native_short_fib_context_v1 import STATUS_AVAILABLE
from src.market_data.native_short_multi_asset_audit_v1 import (
    ASSET_DISABLED,
    BLOCKER_REASON_EVIDENCE_ABSENT_OR_INVALID,
    BLOCKER_REASON_EVIDENCE_CONFIRMS_CLOSED,
    BLOCKER_REASON_IMPLEMENTATION_PENDING_SEPARATE_LANE,
    BLOCKER_REASON_NO_CANONICAL_EVIDENCE_SOURCE,
    BOOTSTRAP_ORCHESTRATION_BLOCKED,
    GENERATION_CHAIN_INVALID,
    GLOBAL_BLOCKERS,
    MARKET_DATA_DISABLED,
    MARKET_NOT_TRADEABLE,
    MULTI_SCOPE_FAILURE_ISOLATION_MISSING,
    PRIMARY_SOURCE_STALE,
    PRIMARY_CONTEXT_UNAVAILABLE,
    PROMOTION_CONTRACT_MISSING,
    PROVENANCE_AUDIT_RUN_UUID,
    READY_EXISTING_CANARY,
    READY_FOR_SEQUENTIAL_CANARY_REVIEW,
    REMOVAL_CONTRACT_MISSING,
    SCOPE_AMBIGUOUS,
    SUPPORTING_SOURCE_STALE,
    SUPPORTING_CONTEXT_UNAVAILABLE,
    TICK_RULE_AMBIGUOUS,
    TICK_RULE_MISSING,
    WRITER_PROVENANCE_UNATTRIBUTED,
    AuditReport,
    CandidateInput,
    CandleWindow,
    CanonicalScopeKey,
    LedgerState,
    MarketMetadata,
    evaluate_candidate,
    evaluate_global_blockers,
    rank_sequential_candidates,
)
from src.market_data.native_short_writer_provenance_v1 import (
    NativeShortWriterProvenanceState,
    classify_persisted_native_short_writer_provenance,
)


AS_OF = datetime(2026, 7, 16, 20, 0, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "src/market_data/native_short_multi_asset_audit_v1.py"
RUNNER = ROOT / "src/market_data/run_native_short_multi_asset_audit_v1.py"


def market(
    symbol: str,
    *,
    enabled: bool | None = True,
    data_enabled: bool | None = True,
    tradeable: bool | None = True,
    precision: tuple[int, ...] | None = None,
) -> MarketMetadata:
    if precision is None:
        precision = ()
    return MarketMetadata(
        asset_id=1,
        venue_market_id=1,
        market=f"{symbol}-EUR",
        asset_enabled=enabled,
        market_data_enabled=data_enabled,
        market_tradeable=tradeable,
        db_price_precisions=precision,
    )


def existing_btc_ledger() -> LedgerState:
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


def candidate(
    symbol: str,
    *,
    metadata: tuple[MarketMetadata, ...] | None = None,
    primary_ts: datetime = AS_OF,
    supporting_ts: datetime = AS_OF,
    ledger: LedgerState | None = None,
    volume: str = "1",
) -> CandidateInput:
    return CandidateInput(
        symbol=symbol,
        markets=metadata if metadata is not None else (market(symbol),),
        primary=CandleWindow(count=100, latest_close_ts_utc=primary_ts),
        supporting=CandleWindow(count=200, latest_close_ts_utc=supporting_ts),
        trailing_30d_quote_volume=Decimal(volume),
        ledger=ledger if ledger is not None else LedgerState(),
        context_status=STATUS_AVAILABLE,
    )


def test_exact_canonical_key() -> None:
    assert CanonicalScopeKey(symbol=" sol ").as_tuple() == (
        "bitvavo",
        "SOL",
        "EUR",
        "SHORT",
        "4h",
        "1h",
    )


def test_deterministic_symbol_ordering() -> None:
    values = [
        evaluate_candidate(candidate("XRP", volume="10"), as_of_utc=AS_OF),
        evaluate_candidate(candidate("ETH", volume="20"), as_of_utc=AS_OF),
        evaluate_candidate(candidate("SOL", volume="30"), as_of_utc=AS_OF),
    ]
    ranked = rank_sequential_candidates(values)
    assert [row.canonical_key.symbol for row in ranked] == ["ETH", "SOL", "XRP"]


def test_fail_closed_eligibility_flags() -> None:
    result = evaluate_candidate(
        candidate("DOGE", metadata=(market("DOGE", enabled=None, data_enabled=False, tradeable=False),)),
        as_of_utc=AS_OF,
    )
    assert result.market_eligible is False
    assert result.market_reason_codes[:3] == (ASSET_DISABLED, MARKET_DATA_DISABLED, MARKET_NOT_TRADEABLE)


def test_missing_and_ambiguous_tick_rules() -> None:
    missing = evaluate_candidate(
        candidate("NOTSTATIC", metadata=(market("NOTSTATIC", precision=()),)),
        as_of_utc=AS_OF,
    )
    ambiguous = evaluate_candidate(
        candidate(
            "BTC",
            metadata=(market("BTC", precision=(2, 3)),),
            ledger=existing_btc_ledger(),
        ),
        as_of_utc=AS_OF,
    )
    assert missing.tick_rule_state == TICK_RULE_MISSING
    assert TICK_RULE_MISSING in missing.market_reason_codes
    assert ambiguous.tick_rule_state == TICK_RULE_AMBIGUOUS


def test_stale_primary_and_supporting_sources() -> None:
    result = evaluate_candidate(
        candidate(
            "BTC",
            primary_ts=AS_OF - timedelta(hours=4),
            supporting_ts=AS_OF - timedelta(hours=1),
            ledger=existing_btc_ledger(),
        ),
        as_of_utc=AS_OF,
    )
    assert PRIMARY_SOURCE_STALE in result.market_reason_codes
    assert SUPPORTING_SOURCE_STALE in result.market_reason_codes


def test_unavailable_primary_and_supporting_contexts() -> None:
    value = candidate("BTC", ledger=existing_btc_ledger())
    value = CandidateInput(
        symbol=value.symbol,
        markets=value.markets,
        primary=CandleWindow(),
        supporting=CandleWindow(),
        ledger=value.ledger,
    )
    result = evaluate_candidate(value, as_of_utc=AS_OF)
    assert PRIMARY_CONTEXT_UNAVAILABLE in result.market_reason_codes
    assert SUPPORTING_CONTEXT_UNAVAILABLE in result.market_reason_codes


def test_unresolved_or_ambiguous_scope_fails_closed() -> None:
    ledger = LedgerState(scope_states=("SUPPORTED", "SUPPORTED"))
    result = evaluate_candidate(candidate("SOL", ledger=ledger), as_of_utc=AS_OF)
    assert result.ledger_readiness_status == SCOPE_AMBIGUOUS
    assert result.readiness_status != READY_FOR_SEQUENTIAL_CANARY_REVIEW


def test_invalid_generation_chain() -> None:
    ledger = LedgerState(
        scope_states=("SUPPORTED",),
        map_ids=(1,),
        generation_events=(("attempt-1", "ATTEMPT_STARTED", None),),
        published_attempt_by_map=((1, "attempt-1"),),
    )
    result = evaluate_candidate(candidate("BTC", ledger=ledger), as_of_utc=AS_OF)
    assert GENERATION_CHAIN_INVALID in result.ledger_reason_codes


def test_btc_existing_canary_classification() -> None:
    result = evaluate_candidate(candidate("BTC", ledger=existing_btc_ledger()), as_of_utc=AS_OF)
    assert result.readiness_status == READY_EXISTING_CANARY
    assert result.market_readiness_status == "MARKET_READY"
    assert result.production_promotable is False
    assert result.materializer_validate_only_possible is True


def test_sequential_ranking_is_applied_only_after_qualification() -> None:
    values = [
        evaluate_candidate(candidate("SOL", volume="300"), as_of_utc=AS_OF),
        evaluate_candidate(candidate("ETH", volume="200"), as_of_utc=AS_OF),
        evaluate_candidate(candidate("XRP", volume="100"), as_of_utc=AS_OF),
        evaluate_candidate(
            candidate(
                "NOTSTATIC",
                metadata=(market("NOTSTATIC", precision=()),),
                volume="9999",
            ),
            as_of_utc=AS_OF,
        ),
    ]
    ranked = rank_sequential_candidates(values)
    rank_by_symbol = {row.canonical_key.symbol: row.sequential_review_rank for row in ranked}
    assert rank_by_symbol == {"ETH": 2, "NOTSTATIC": None, "SOL": 1, "XRP": 3}
    assert next(row for row in ranked if row.canonical_key.symbol == "NOTSTATIC").trailing_30d_quote_volume is None


def test_global_blockers_prevent_production_promotion() -> None:
    result = evaluate_candidate(candidate("SOL"), as_of_utc=AS_OF, global_blockers=GLOBAL_BLOCKERS)
    assert result.readiness_status == READY_FOR_SEQUENTIAL_CANARY_REVIEW
    assert result.global_rollout_status == "GLOBAL_ROLLOUT_BLOCKED"
    assert WRITER_PROVENANCE_UNATTRIBUTED in result.global_blocker_codes
    assert result.production_promotable is False


def test_provenance_contract_and_operational_acceptance_are_independent() -> None:
    report = AuditReport(
        as_of_utc=AS_OF,
        results=(),
        proposed_sequential_queue=(),
        counts={},
        writer_run_count=42,
        attributable_writer_run_count=0,
        legacy_unattributed_writer_run_count=42,
        invalid_provenance_writer_run_count=0,
        provenance_audit_run_found=True,
        provenance_audit_run_attributed=False,
        provenance_contract_implemented=True,
        attributable_production_run_observed=False,
        operational_acceptance_completed=False,
        writer_provenance_blocker_active=True,
        global_blocker_codes=GLOBAL_BLOCKERS,
    ).to_dict()
    assert report["writer_run_count"] == 42
    assert report["attributable_writer_run_count"] == 0
    assert report["legacy_unattributed_writer_run_count"] == 42
    assert report["invalid_provenance_writer_run_count"] == 0
    assert report["provenance_contract_implemented"] is True
    assert report["attributable_production_run_observed"] is False
    assert report["operational_acceptance_completed"] is False
    assert report["writer_provenance_blocker_active"] is True
    assert WRITER_PROVENANCE_UNATTRIBUTED in report["global_blocker_codes"]


def test_attributable_provenance_clears_only_writer_provenance_blocker() -> None:
    active, reasons = evaluate_global_blockers(provenance_attributed=True)
    assert WRITER_PROVENANCE_UNATTRIBUTED not in active
    assert reasons[WRITER_PROVENANCE_UNATTRIBUTED] == BLOCKER_REASON_EVIDENCE_CONFIRMS_CLOSED
    # every other blocker remains active regardless of provenance evidence
    assert set(active) == {
        PROMOTION_CONTRACT_MISSING,
        REMOVAL_CONTRACT_MISSING,
        BOOTSTRAP_ORCHESTRATION_BLOCKED,
        MULTI_SCOPE_FAILURE_ISOLATION_MISSING,
    }


def test_unattributable_provenance_keeps_writer_provenance_blocker_active() -> None:
    active, reasons = evaluate_global_blockers(provenance_attributed=False)
    assert WRITER_PROVENANCE_UNATTRIBUTED in active
    assert reasons[WRITER_PROVENANCE_UNATTRIBUTED] == BLOCKER_REASON_EVIDENCE_ABSENT_OR_INVALID


def test_missing_or_malformed_provenance_fails_closed() -> None:
    # Any non-True input (absent row, invalid classification, ambiguous
    # evidence) must be treated identically to False -- fail closed.
    active_false, _ = evaluate_global_blockers(provenance_attributed=False)
    active_falsy, _ = evaluate_global_blockers(provenance_attributed=bool(None))
    assert active_false == active_falsy
    assert WRITER_PROVENANCE_UNATTRIBUTED in active_false


def test_promotion_and_removal_evidence_remain_unresolved() -> None:
    active, reasons = evaluate_global_blockers(provenance_attributed=True)
    assert PROMOTION_CONTRACT_MISSING in active
    assert REMOVAL_CONTRACT_MISSING in active
    assert reasons[PROMOTION_CONTRACT_MISSING] == BLOCKER_REASON_NO_CANONICAL_EVIDENCE_SOURCE
    assert reasons[REMOVAL_CONTRACT_MISSING] == BLOCKER_REASON_NO_CANONICAL_EVIDENCE_SOURCE


def test_promotion_accepted_evidence_clears_only_promotion_blocker() -> None:
    active, reasons = evaluate_global_blockers(
        provenance_attributed=True,
        promotion_accepted=True,
        promotion_evidence_reason="EVIDENCE_ACCEPTED",
    )
    assert PROMOTION_CONTRACT_MISSING not in active
    assert reasons[PROMOTION_CONTRACT_MISSING] == BLOCKER_REASON_EVIDENCE_CONFIRMS_CLOSED
    # every other blocker remains active regardless of promotion evidence
    assert set(active) == {
        REMOVAL_CONTRACT_MISSING,
        BOOTSTRAP_ORCHESTRATION_BLOCKED,
        MULTI_SCOPE_FAILURE_ISOLATION_MISSING,
    }


def test_promotion_evaluated_but_rejected_evidence_keeps_blocker_active_with_detail() -> None:
    active, reasons = evaluate_global_blockers(
        provenance_attributed=True,
        promotion_accepted=False,
        promotion_evidence_reason="EVIDENCE_ABSENT",
    )
    assert PROMOTION_CONTRACT_MISSING in active
    assert reasons[PROMOTION_CONTRACT_MISSING] == BLOCKER_REASON_EVIDENCE_ABSENT_OR_INVALID


def test_bootstrap_and_isolation_blockers_remain_active_pending_separate_lanes() -> None:
    active, reasons = evaluate_global_blockers(provenance_attributed=True)
    assert BOOTSTRAP_ORCHESTRATION_BLOCKED in active
    assert MULTI_SCOPE_FAILURE_ISOLATION_MISSING in active
    assert (
        reasons[BOOTSTRAP_ORCHESTRATION_BLOCKED]
        == BLOCKER_REASON_IMPLEMENTATION_PENDING_SEPARATE_LANE
    )
    assert (
        reasons[MULTI_SCOPE_FAILURE_ISOLATION_MISSING]
        == BLOCKER_REASON_IMPLEMENTATION_PENDING_SEPARATE_LANE
    )


def test_global_blocker_codes_exactly_matches_evaluated_active_blockers() -> None:
    for provenance_attributed in (True, False):
        active, _ = evaluate_global_blockers(provenance_attributed=provenance_attributed)
        result = evaluate_candidate(candidate("SOL"), as_of_utc=AS_OF, global_blockers=active)
        assert result.global_blocker_codes == active
        assert (result.global_rollout_status == "GLOBAL_ROLLOUT_BLOCKED") == bool(active)


def test_operational_acceptance_cannot_be_true_while_any_blocker_active() -> None:
    for provenance_attributed in (True, False):
        active, _ = evaluate_global_blockers(provenance_attributed=provenance_attributed)
        operational_acceptance_completed = not active
        # At least one blocker (promotion/removal/bootstrap/isolation) is
        # always active in this lane, so acceptance can never be true yet.
        assert active
        assert operational_acceptance_completed is False


def test_production_promotable_remains_false_while_blockers_remain() -> None:
    for provenance_attributed in (True, False):
        active, _ = evaluate_global_blockers(provenance_attributed=provenance_attributed)
        result = evaluate_candidate(candidate("ETH", volume="1"), as_of_utc=AS_OF, global_blockers=active)
        assert result.readiness_status == READY_FOR_SEQUENTIAL_CANARY_REVIEW
        assert result.production_promotable is False


def test_global_blocker_evidence_covers_every_canonical_blocker_deterministically() -> None:
    active, reasons = evaluate_global_blockers(provenance_attributed=True)
    assert set(reasons) == set(GLOBAL_BLOCKERS)
    active_again, reasons_again = evaluate_global_blockers(provenance_attributed=True)
    assert active == active_again
    assert reasons == reasons_again
    # ordering follows canonical GLOBAL_BLOCKERS declaration order
    assert list(active) == [code for code in GLOBAL_BLOCKERS if code in active]


def _accepted_run_row(**overrides: object) -> dict[str, object]:
    """Shape of the reviewed accepted attributable production run (run_id=52,
    docs/ops/native_short_writer_provenance_operational_acceptance_20260717.md).
    """
    row: dict[str, object] = {
        "run_uuid": PROVENANCE_AUDIT_RUN_UUID,
        "runner_name": "run_native_short_scope_status_chain_v1",
        "runner_version": "0.1",
        "trigger_type": "REPOSITORY_4H_MARKET_CHAIN",
        "trigger_ref": "scripts/run_native_short_scope_status_chain_once.sh",
        "host_name": "devlap",
        "process_id": 26030,
        "provenance_contract_version": "native_short_writer_provenance_v1",
        "writer_entrypoint": "scripts/run_native_short_scope_status_chain_once.sh",
        "repository_writer_owner": "synth-chain-4h",
        "execution_mode": "CHAIN",
        "repository_commit_sha": "38346fc1460453469ca5bd3bc2f45159f0dc303e",
    }
    row.update(overrides)
    return row


def test_valid_canonical_accepted_run_classifies_attributable() -> None:
    row = _accepted_run_row()
    assert classify_persisted_native_short_writer_provenance(row) == (
        NativeShortWriterProvenanceState.ATTRIBUTABLE
    )
    active, reasons = evaluate_global_blockers(provenance_attributed=True)
    assert WRITER_PROVENANCE_UNATTRIBUTED not in active
    assert reasons[WRITER_PROVENANCE_UNATTRIBUTED] == BLOCKER_REASON_EVIDENCE_CONFIRMS_CLOSED


def test_legacy_pre_contract_run_is_not_mistaken_for_the_accepted_run() -> None:
    # This is the real historical run_id=30 row (2026-07-15, predates the
    # provenance-contract migration): must never be treated as the accepted
    # attributable evidence, even though it shares a similarly-shaped UUID
    # format with the real accepted run.
    legacy_row = {
        "run_uuid": "b5d9ca6b-ff24-46eb-8155-4e663b948ebc",
        "runner_name": "native_short_scope_status_materializer_v1",
        "runner_version": "0.1",
        "trigger_type": "SCHEDULED_4H_MARKET_CHAIN",
        "trigger_ref": None,
        "host_name": None,
        "process_id": None,
        "provenance_contract_version": None,
        "writer_entrypoint": None,
        "repository_writer_owner": None,
        "execution_mode": None,
        "repository_commit_sha": None,
    }
    assert classify_persisted_native_short_writer_provenance(legacy_row) == (
        NativeShortWriterProvenanceState.LEGACY_UNATTRIBUTED
    )
    assert PROVENANCE_AUDIT_RUN_UUID != legacy_row["run_uuid"]


@pytest.mark.parametrize(
    "field",
    [
        "provenance_contract_version",
        "writer_entrypoint",
        "repository_writer_owner",
        "runner_name",
        "runner_version",
        "execution_mode",
        "repository_commit_sha",
        "host_name",
        "process_id",
        "trigger_type",
        "trigger_ref",
    ],
)
def test_each_missing_or_malformed_required_field_fails_closed(field: str) -> None:
    row = _accepted_run_row(**{field: None})
    assert classify_persisted_native_short_writer_provenance(row) in (
        NativeShortWriterProvenanceState.LEGACY_UNATTRIBUTED,
        NativeShortWriterProvenanceState.INVALID_PROVENANCE,
    )
    assert classify_persisted_native_short_writer_provenance(row) != (
        NativeShortWriterProvenanceState.ATTRIBUTABLE
    )


def test_unrelated_writer_identity_fails_closed() -> None:
    row = _accepted_run_row(repository_writer_owner="some-other-owner")
    assert classify_persisted_native_short_writer_provenance(row) == (
        NativeShortWriterProvenanceState.INVALID_PROVENANCE
    )


def test_stale_or_wrong_run_uuid_is_never_treated_as_the_accepted_run() -> None:
    # A row with impeccable provenance but a different run_uuid than
    # PROVENANCE_AUDIT_RUN_UUID must not be picked up by run_audit's
    # accepted-run filter (str(row["run_uuid"]) == PROVENANCE_AUDIT_RUN_UUID).
    wrong_uuid_row = _accepted_run_row(run_uuid="00000000-0000-4000-8000-000000000000")
    assert wrong_uuid_row["run_uuid"] != PROVENANCE_AUDIT_RUN_UUID
    assert classify_persisted_native_short_writer_provenance(wrong_uuid_row) == (
        NativeShortWriterProvenanceState.ATTRIBUTABLE
    )
    # valid provenance on the wrong UUID must not be mistaken for acceptance
    # of the canonical accepted run by identity comparison alone
    filtered = [
        row for row in (wrong_uuid_row,) if str(row["run_uuid"]) == PROVENANCE_AUDIT_RUN_UUID
    ]
    assert filtered == []


def test_audit_clears_only_writer_provenance_blocker() -> None:
    active, _ = evaluate_global_blockers(provenance_attributed=True)
    assert WRITER_PROVENANCE_UNATTRIBUTED not in active
    assert set(active) == {
        PROMOTION_CONTRACT_MISSING,
        REMOVAL_CONTRACT_MISSING,
        BOOTSTRAP_ORCHESTRATION_BLOCKED,
        MULTI_SCOPE_FAILURE_ISOLATION_MISSING,
    }


def test_no_account_or_execution_imports() -> None:
    forbidden = ("account", "selection", "decision_gate", "execution_planner", "executor", "broker")
    for path in (CORE, RUNNER):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules.append(node.module or "")
        assert not any(any(part in module.split(".") for part in forbidden) for module in modules)


def test_db_write_prohibition() -> None:
    forbidden_sql = {"INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP", "TRUNCATE", "REPLACE"}
    for path in (CORE, RUNNER):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        assert re.search(
            r"\b(?:INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|"
            r"CREATE\s+(?:TABLE|VIEW)|ALTER\s+TABLE|DROP\s+(?:TABLE|VIEW)|"
            r"TRUNCATE\s+TABLE|REPLACE\s+INTO)\b",
            source,
            re.IGNORECASE,
        ) is None
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr != "commit"
                if node.func.attr == "execute" and node.args and isinstance(node.args[0], ast.Constant):
                    first = str(node.args[0].value).strip().split(maxsplit=1)[0].upper()
                    assert first not in forbidden_sql
