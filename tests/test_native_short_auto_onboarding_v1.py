from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from src.market_data import native_short_auto_onboarding_v1 as onboarding
from src.market_data.native_short_scope_administration_v1 import (
    NativeShortScopeAdministrationOperationType,
)
from src.market_data.native_short_scope_administration_transaction_v1 import (
    applicable_active_global_blockers,
)

NOW = datetime(2026, 8, 26, 20, 0, tzinfo=UTC)
SHA = "a" * 40


def _candidate(
    symbol: str,
    *,
    market: str = "MARKET_READY",
    ledger: str = "LEDGER_READY",
    states=(),
    market_reasons=(),
):
    return SimpleNamespace(
        canonical_key=SimpleNamespace(symbol=symbol),
        market_readiness_status=market,
        ledger_readiness_status=ledger,
        market_reason_codes=market_reasons or ((market,) if market != "MARKET_READY" else ()),
        ledger_reason_codes=(ledger,) if ledger != "LEDGER_READY" else (),
        scope_states=states,
    )


def _report(*candidates):
    return SimpleNamespace(results=candidates)


def _success():
    return SimpleNamespace(result=SimpleNamespace(result_class="SUCCESS", result_code="PROMOTED_NEW_SCOPE"))


def test_ready_market_auto_onboards_without_rollout_gates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(onboarding, "run_audit", lambda *_args, **_kwargs: _report(_candidate("IOST")))
    calls = []
    result = onboarding.reconcile_ready_scopes(
        object(), as_of_utc=NOW, repository_commit_sha=SHA, authorization=object(),
        execute=lambda *_args, **kwargs: calls.append(kwargs["request"] if "request" in kwargs else _args[1]) or _success(),
    )
    assert result == (onboarding.OnboardingResult("IOST", "SUPPORTED", "PROMOTED_NEW_SCOPE"),)
    assert len(calls) == 1
    assert calls[0].operation_type == NativeShortScopeAdministrationOperationType.AUTO_ONBOARD_SCOPE


def test_transient_stale_market_auto_onboards_without_blocking_other_ready_markets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(onboarding, "run_audit", lambda *_args, **_kwargs: _report(
        _candidate("DGB", market_reasons=("SUPPORTING_SOURCE_STALE",)),
        _candidate("NOT", market_reasons=("SUPPORTING_SOURCE_STALE",)),
        _candidate("IOST"),
    ))
    calls = []
    result = onboarding.reconcile_ready_scopes(
        object(), as_of_utc=NOW, repository_commit_sha=SHA, authorization=object(),
        execute=lambda *_args, **_kwargs: calls.append(1) or _success(),
    )
    assert [item.state for item in result] == ["SUPPORTED", "SUPPORTED", "SUPPORTED"]
    assert len(calls) == 3


def test_supported_scope_is_idempotent_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(onboarding, "run_audit", lambda *_args, **_kwargs: _report(_candidate("IOST", states=("SUPPORTED",))))
    result = onboarding.reconcile_ready_scopes(
        object(), as_of_utc=NOW, repository_commit_sha=SHA, authorization=object(),
        execute=lambda *_args, **_kwargs: pytest.fail("must not execute"),
    )
    assert result[0].detail == "ALREADY_SUPPORTED"


def test_auto_onboarding_retains_only_writer_integrity_gate() -> None:
    assert applicable_active_global_blockers(
        NativeShortScopeAdministrationOperationType.AUTO_ONBOARD_SCOPE,
        ("REMOVAL_CONTRACT_MISSING", "PROMOTION_CONTRACT_MISSING"),
    ) == ()
    assert applicable_active_global_blockers(
        NativeShortScopeAdministrationOperationType.AUTO_ONBOARD_SCOPE,
        ("WRITER_PROVENANCE_UNATTRIBUTED",),
    ) == ("WRITER_PROVENANCE_UNATTRIBUTED",)


def test_auto_onboarding_operation_ignores_rollout_only_blockers() -> None:
    from src.market_data.native_short_scope_administration_transaction_v1 import (
        ScopeClassification,
        ScopeStateSnapshot,
        decide_administration,
    )

    snapshot = ScopeStateSnapshot(
        scope_present=False, scope_id=None, scope_support_state=None,
        support_generation=None, scope_reason_code=None, scope_reason_detail=None,
        cadence_rows=(), support_events=(), operations=(),
        scope_status_residue_count=0, map_level_status_residue_count=0,
    )
    decision = decide_administration(
        NativeShortScopeAdministrationOperationType.AUTO_ONBOARD_SCOPE,
        snapshot,
        active_global_blockers=(
            "REMOVAL_CONTRACT_MISSING", "PROMOTION_CONTRACT_MISSING",
            "BOOTSTRAP_ORCHESTRATION_BLOCKED", "MULTI_SCOPE_FAILURE_ISOLATION_MISSING",
        ),
    )
    assert decision.classification == ScopeClassification.NO_SCOPE
    assert str(decision.action) == "PROMOTE_NEW"


def test_real_readiness_boundaries_remain_not_ready() -> None:
    from src.market_data.native_short_multi_asset_audit_v1 import (
        CandidateInput, CandleWindow, LedgerState, MarketMetadata, evaluate_candidate,
    )
    market = MarketMetadata(1, 1, "IOST-EUR", True, True, True, ())
    base = CandidateInput("IOST", (market,), CandleWindow(), CandleWindow(), ledger=LedgerState())
    result = evaluate_candidate(base, as_of_utc=NOW, global_blockers=("REMOVAL_CONTRACT_MISSING",))
    assert result.readiness_status == "PRIMARY_CONTEXT_UNAVAILABLE"
    inactive = CandidateInput("IOST", (MarketMetadata(1, 1, "IOST-EUR", True, True, False, ()),), CandleWindow(), CandleWindow(), ledger=LedgerState())
    assert "MARKET_NOT_TRADEABLE" in evaluate_candidate(inactive, as_of_utc=NOW).market_reason_codes
