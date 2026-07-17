from __future__ import annotations

import ast
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from src.market_data.native_short_fib_context_v1 import STATUS_AVAILABLE
from src.market_data.native_short_multi_asset_audit_v1 import (
    ASSET_DISABLED,
    GENERATION_CHAIN_INVALID,
    GLOBAL_BLOCKERS,
    MARKET_DATA_DISABLED,
    MARKET_NOT_TRADEABLE,
    PRIMARY_SOURCE_STALE,
    PRIMARY_CONTEXT_UNAVAILABLE,
    READY_EXISTING_CANARY,
    READY_FOR_SEQUENTIAL_CANARY_REVIEW,
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
    rank_sequential_candidates,
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
