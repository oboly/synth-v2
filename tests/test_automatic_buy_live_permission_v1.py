import ast
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from src.decision_gate.account_protection_contract_v1 import (
    ACTION_BUY,
    LOCK_FACT_CONTRACT_VERSION,
    PROTECTION_MAX_ACCOUNT_DRAWDOWN_BLOCK,
    SCOPE_ACCOUNT,
    ProtectionLockFactV1,
    resolve_account_protection_state_for_action_v1,
)
from src.decision_gate.automatic_buy_gate_v1 import (
    REASON_ACCOUNT_MODE_EVIDENCE_INCONSISTENT,
    REASON_LIVE_EXECUTION_NOT_GRANTED,
    REASON_LIVE_PERMISSION_EVALUATION_BINDING_MISMATCH,
    STATE_APPROVED,
    STATE_DENIED,
    STATE_NON_ACTIONABLE,
    AutomaticBuyGateContextV1,
    evaluate_automatic_buy_candidate_permission_v1,
)
from src.decision_gate.automatic_buy_live_permission_contract_v1 import (
    AutomaticBuyLiveDecisionGatePermissionRevocationV1,
    AutomaticBuyLiveDecisionGatePermissionV1,
    AutomaticBuyLivePermissionContractError,
    resolve_automatic_buy_live_decision_gate_permission_v1,
)
from src.decision_gate.automatic_buy_live_permission_evaluation_v1 import (
    DECISION_DENIED,
    DECISION_GRANTED,
    EVALUATION_CONTRACT_VERSION,
    REASON_OK,
    AutomaticBuyLivePermissionEvaluationV1,
)
from src.decision_gate.strategy_bucket_account_config_contract_v1 import StrategyBucketAccountConfigRowV1
from src.entry_policy.automatic_buy_candidate_v1 import AutomaticBuyCandidateV1

NOW = datetime(2026, 8, 19, 18, 0, tzinfo=timezone.utc)
BUCKET = "SHORT_TERM_ROTATION"


def _permission(**changes: object) -> AutomaticBuyLiveDecisionGatePermissionV1:
    values: dict[str, object] = dict(
        permission_id=11,
        trading_account_id=7,
        live_execution_permitted=True,
        effective_from_ts_utc=NOW - timedelta(hours=1),
        effective_until_ts_utc=None,
        permission_version="1",
        source_provenance="phase7a_test",
    )
    values.update(changes)
    return AutomaticBuyLiveDecisionGatePermissionV1(**values)  # type: ignore[arg-type]


def _live_eval(**changes: object) -> AutomaticBuyLivePermissionEvaluationV1:
    values: dict[str, object] = dict(
        evaluation_contract_version=EVALUATION_CONTRACT_VERSION,
        trading_account_id=7,
        decision_state=DECISION_GRANTED,
        reason_code=REASON_OK,
        permission_id=11,
        permission_version="1",
        evaluated_ts_utc=NOW,
    )
    values.update(changes)
    return AutomaticBuyLivePermissionEvaluationV1(**values)  # type: ignore[arg-type]


def _candidate() -> AutomaticBuyCandidateV1:
    return AutomaticBuyCandidateV1(
        venue="bitvavo",
        asset_id=42,
        market="SOL-EUR",
        strategy_id="strat-1",
        strategy_version="1",
        setup_id="setup-1",
        candidate_action="ENTER",
        reason_code="ENTRY_ZONE_REACHED",
        evidence_id="evidence-1",
        entry_zone_low=Decimal("90"),
        entry_zone_high=Decimal("100"),
        observed_ts_utc=NOW,
    )


def _bucket_row() -> StrategyBucketAccountConfigRowV1:
    return StrategyBucketAccountConfigRowV1(
        strategy_bucket_account_config_id=1,
        trading_account_id=7,
        strategy_bucket_id=BUCKET,
        config_version="1",
        is_enabled=True,
        risk_profile="MODERATE",
        max_position_amount_eur=None,
        max_bucket_amount_eur=None,
        max_asset_exposure_pct=None,
        max_open_positions=None,
        allow_new_entries=True,
        allow_reduce_reviews=True,
        effective_from_ts_utc=NOW - timedelta(days=1),
        effective_until_ts_utc=None,
        source_provenance="phase7a_test",
    )


def _context(**changes: object) -> AutomaticBuyGateContextV1:
    values: dict[str, object] = dict(
        trading_account_id=7,
        venue="bitvavo",
        asset_id=42,
        market="SOL-EUR",
        strategy_bucket_id=BUCKET,
        account_observed_ts_utc=NOW,
        account_enabled=True,
        account_mode="paper",
        automatic_buy_execution_enabled=True,
        free_quote_balance_eur=Decimal("500"),
        free_quote_balance_observed_ts_utc=NOW,
        blocking_conflict=False,
        proposed_position_amount_eur=Decimal("100"),
        current_bucket_amount_eur=Decimal("0"),
        current_open_positions=0,
        current_asset_exposure_pct=Decimal("0"),
        evaluation_ts_utc=NOW,
        strategy_bucket_config_rows=(_bucket_row(),),
    )
    values.update(changes)
    return AutomaticBuyGateContextV1(**values)  # type: ignore[arg-type]


def _protection():
    lock = ProtectionLockFactV1(
        lifecycle_id="lifecycle-live-buy",
        event_id="event-live-buy",
        protection_code=PROTECTION_MAX_ACCOUNT_DRAWDOWN_BLOCK,
        protection_version=LOCK_FACT_CONTRACT_VERSION,
        trading_account_id=7,
        scope_type=SCOPE_ACCOUNT,
        scope_id="7",
        observed_from_ts_utc=NOW - timedelta(minutes=1),
        observed_to_ts_utc=NOW,
        triggered_ts_utc=NOW,
        expires_ts_utc=None,
        reason_code="TEST",
        evidence_refs=("canonical:lock:live-buy",),
        configuration_version="policy-1",
    )
    return resolve_account_protection_state_for_action_v1(
        (lock,),
        trading_account_id=7,
        sleeve_code=None,
        asset_id=42,
        requested_action=ACTION_BUY,
        account_state_observed_ts_utc=NOW,
        account_state_fresh=True,
        at=NOW,
    )


def test_permission_resolver_is_account_scoped_append_only_and_revocable() -> None:
    active = _permission()
    assert resolve_automatic_buy_live_decision_gate_permission_v1(
        (active,), trading_account_id=7, at=NOW,
    ) == active
    assert resolve_automatic_buy_live_decision_gate_permission_v1(
        (active,), trading_account_id=8, at=NOW,
    ) is None

    revocation = AutomaticBuyLiveDecisionGatePermissionRevocationV1(
        revocation_id=1,
        permission_id=11,
        trading_account_id=7,
        revocation_version="1",
        effective_ts_utc=NOW - timedelta(minutes=1),
        actor="test",
        reason="revoked",
    )
    assert resolve_automatic_buy_live_decision_gate_permission_v1(
        (active,), (revocation,), trading_account_id=7, at=NOW,
    ) is None


def test_permission_overlap_fails_closed() -> None:
    with __import__("pytest").raises(AutomaticBuyLivePermissionContractError):
        resolve_automatic_buy_live_decision_gate_permission_v1(
            (_permission(permission_id=11), _permission(permission_id=12)),
            trading_account_id=7,
            at=NOW,
        )


def test_paper_path_remains_approved_without_live_state() -> None:
    result = evaluate_automatic_buy_candidate_permission_v1(
        candidate=_candidate(), context=_context(),
    )
    assert result.state == STATE_APPROVED


def test_live_mode_requires_live_trading_enabled_evidence() -> None:
    result = evaluate_automatic_buy_candidate_permission_v1(
        candidate=_candidate(),
        context=_context(account_mode="live", live_trading_enabled=False),
    )
    assert (result.state, result.reason_code) == (
        STATE_NON_ACTIONABLE,
        REASON_ACCOUNT_MODE_EVIDENCE_INCONSISTENT,
    )


def test_live_mode_requires_explicit_typed_permission() -> None:
    missing = evaluate_automatic_buy_candidate_permission_v1(
        candidate=_candidate(),
        context=_context(account_mode="live", live_trading_enabled=True),
    )
    assert (missing.state, missing.reason_code) == (STATE_DENIED, REASON_LIVE_EXECUTION_NOT_GRANTED)

    denied = evaluate_automatic_buy_candidate_permission_v1(
        candidate=_candidate(),
        context=_context(
            account_mode="live",
            live_trading_enabled=True,
            automatic_buy_live_permission_evaluation=_live_eval(
                decision_state=DECISION_DENIED,
                reason_code="AUTOMATIC_BUY_LIVE_PERMISSION_NOT_GRANTED",
                permission_id=None,
                permission_version=None,
            ),
        ),
    )
    assert (denied.state, denied.reason_code) == (STATE_DENIED, REASON_LIVE_EXECUTION_NOT_GRANTED)


def test_live_mode_approves_only_with_exact_bound_grant() -> None:
    result = evaluate_automatic_buy_candidate_permission_v1(
        candidate=_candidate(),
        context=_context(
            account_mode="live",
            live_trading_enabled=True,
            automatic_buy_live_permission_evaluation=_live_eval(),
        ),
    )
    assert result.state == STATE_APPROVED
    assert result.approved_notional_ceiling_eur == Decimal("100")


def test_stale_or_wrong_account_live_permission_fails_closed() -> None:
    stale = evaluate_automatic_buy_candidate_permission_v1(
        candidate=_candidate(),
        context=_context(
            account_mode="live",
            live_trading_enabled=True,
            automatic_buy_live_permission_evaluation=_live_eval(
                evaluated_ts_utc=NOW - timedelta(seconds=1),
            ),
        ),
    )
    assert (stale.state, stale.reason_code) == (
        STATE_DENIED,
        REASON_LIVE_PERMISSION_EVALUATION_BINDING_MISMATCH,
    )

    wrong_account = evaluate_automatic_buy_candidate_permission_v1(
        candidate=_candidate(),
        context=_context(
            account_mode="live",
            live_trading_enabled=True,
            automatic_buy_live_permission_evaluation=_live_eval(trading_account_id=8),
        ),
    )
    assert (wrong_account.state, wrong_account.reason_code) == (
        STATE_DENIED,
        REASON_LIVE_PERMISSION_EVALUATION_BINDING_MISMATCH,
    )


def test_account_protection_still_blocks_a_live_permitted_buy() -> None:
    result = evaluate_automatic_buy_candidate_permission_v1(
        candidate=_candidate(),
        context=_context(
            account_mode="live",
            live_trading_enabled=True,
            automatic_buy_live_permission_evaluation=_live_eval(),
            account_protection_evaluation=_protection(),
        ),
    )
    assert result.state == STATE_DENIED
    assert result.protection_code == PROTECTION_MAX_ACCOUNT_DRAWDOWN_BLOCK


def test_phase7a_modules_have_no_executor_broker_credential_or_kill_switch_imports() -> None:
    for path in (
        Path("src/decision_gate/automatic_buy_live_permission_contract_v1.py"),
        Path("src/decision_gate/automatic_buy_live_permission_repository_v1.py"),
        Path("src/decision_gate/automatic_buy_live_permission_evaluation_v1.py"),
        Path("src/decision_gate/automatic_buy_gate_v1.py"),
    ):
        tree = ast.parse(path.read_text())
        imports = [
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        ]
        assert not any(
            any(token in name for token in ("src.executor", "broker", "credential", "kill_switch"))
            for name in imports
        )
