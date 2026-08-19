import ast
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from src.decision_gate.account_protection_contract_v1 import (
    ACTION_BUY,
    ACTION_EXIT,
    LOCK_FACT_CONTRACT_VERSION,
    PROTECTION_MANUAL_ACCOUNT_LOCK,
    PROTECTION_MAX_ACCOUNT_DRAWDOWN_BLOCK,
    SCOPE_ACCOUNT,
    ProtectionLockFactV1,
    resolve_account_protection_state_for_action_v1,
)
from src.decision_gate.automatic_buy_gate_v1 import (
    REASON_ACCOUNT_DISABLED,
    REASON_ACCOUNT_EVIDENCE_STALE,
    REASON_ACCOUNT_MODE_EVIDENCE_INCONSISTENT,
    REASON_BLOCKING_CONFLICT,
    REASON_CANDIDATE_EVIDENCE_STALE,
    REASON_EXECUTION_PERMISSION_DISABLED,
    REASON_FREE_QUOTE_BALANCE_STALE,
    REASON_IDENTITY_MISMATCH,
    REASON_INVALID_CANDIDATE,
    REASON_INVALID_FREE_QUOTE_BALANCE,
    REASON_INVALID_PROPOSED_POSITION_AMOUNT,
    REASON_INVALID_TIMESTAMP,
    REASON_NO_FREE_QUOTE_BALANCE,
    REASON_RISK_BOUND_UNRESOLVED,
    REASON_UNSUPPORTED_ACCOUNT_MODE,
    REASON_UNSUPPORTED_POLICY_CONTRACT,
    STATE_APPROVED,
    STATE_DENIED,
    STATE_NON_ACTIONABLE,
    AutomaticBuyGateContextV1,
    evaluate_automatic_buy_candidate_permission_v1,
)
from src.decision_gate.strategy_bucket_account_config_contract_v1 import StrategyBucketAccountConfigRowV1
from src.decision_gate.strategy_bucket_participation_evaluation_v1 import (
    REASON_BUCKET_DISABLED,
    REASON_NEW_ENTRIES_NOT_ALLOWED,
    REASON_OPEN_POSITIONS_CEILING_EXCEEDED,
    REASON_POSITION_AMOUNT_CEILING_EXCEEDED,
)
from src.entry_policy import POLICY_NAME, POLICY_VERSION
from src.entry_policy.automatic_buy_candidate_v1 import AutomaticBuyCandidateV1


NOW = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)
BUCKET = "SHORT_TERM_ROTATION"


def _candidate(**changes: object) -> AutomaticBuyCandidateV1:
    values: dict[str, object] = dict(
        venue="bitvavo", asset_id=42, market="SOL-EUR", strategy_id="strat-1",
        strategy_version="1", setup_id="setup-1", candidate_action="ENTER",
        reason_code="ENTRY_ZONE_REACHED", evidence_id="evidence-1",
        entry_zone_low=Decimal("90"), entry_zone_high=Decimal("100"), observed_ts_utc=NOW,
    )
    values.update(changes)
    return AutomaticBuyCandidateV1(**values)  # type: ignore[arg-type]


def _bucket_row(**changes: object) -> StrategyBucketAccountConfigRowV1:
    values: dict[str, object] = dict(
        strategy_bucket_account_config_id=1, trading_account_id=7, strategy_bucket_id=BUCKET,
        config_version="1", is_enabled=True, risk_profile="MODERATE",
        max_position_amount_eur=None, max_bucket_amount_eur=None, max_asset_exposure_pct=None,
        max_open_positions=None, allow_new_entries=True, allow_reduce_reviews=True,
        effective_from_ts_utc=NOW - timedelta(days=1), effective_until_ts_utc=None,
        source_provenance="manual_review",
    )
    values.update(changes)
    return StrategyBucketAccountConfigRowV1(**values)  # type: ignore[arg-type]


def _context(**changes: object) -> AutomaticBuyGateContextV1:
    values: dict[str, object] = dict(
        trading_account_id=7, venue="bitvavo", asset_id=42, market="SOL-EUR",
        strategy_bucket_id=BUCKET, account_observed_ts_utc=NOW, account_enabled=True,
        account_mode="paper", automatic_buy_execution_enabled=True,
        free_quote_balance_eur=Decimal("500"), free_quote_balance_observed_ts_utc=NOW,
        blocking_conflict=False, proposed_position_amount_eur=Decimal("100"),
        current_bucket_amount_eur=Decimal("0"), current_open_positions=0,
        current_asset_exposure_pct=Decimal("0"), evaluation_ts_utc=NOW,
        strategy_bucket_config_rows=(_bucket_row(),),
    )
    values.update(changes)
    return AutomaticBuyGateContextV1(**values)  # type: ignore[arg-type]


def _evaluate(**changes: object):
    return evaluate_automatic_buy_candidate_permission_v1(candidate=_candidate(), context=_context(**changes))


def _protection(action: str, *, manual: bool = False):
    code = PROTECTION_MANUAL_ACCOUNT_LOCK if manual else PROTECTION_MAX_ACCOUNT_DRAWDOWN_BLOCK
    lock = ProtectionLockFactV1(
        lifecycle_id=f"lifecycle-{code}", event_id=f"event-{code}", protection_code=code,
        protection_version=LOCK_FACT_CONTRACT_VERSION, trading_account_id=7,
        scope_type=SCOPE_ACCOUNT, scope_id="7", observed_from_ts_utc=NOW - timedelta(minutes=1),
        observed_to_ts_utc=NOW, triggered_ts_utc=NOW, expires_ts_utc=None,
        reason_code="TEST", evidence_refs=("canonical:lock:1",), configuration_version="policy-1",
    )
    return resolve_account_protection_state_for_action_v1(
        (lock,), trading_account_id=7, sleeve_code=None, asset_id=42,
        requested_action=action, account_state_observed_ts_utc=NOW,
        account_state_fresh=True, at=NOW,
    )


def test_healthy_candidate_is_approved_with_account_safe_ceiling_and_preserved_provenance() -> None:
    candidate = _candidate()
    result = evaluate_automatic_buy_candidate_permission_v1(candidate=candidate, context=_context())
    assert result.state == STATE_APPROVED
    assert result.candidate is candidate
    assert result.approved_notional_ceiling_eur == Decimal("100")
    assert result.reason_code == "OK"


def test_re_enter_action_is_also_a_valid_candidate_action() -> None:
    result = evaluate_automatic_buy_candidate_permission_v1(
        candidate=_candidate(candidate_action="RE_ENTER"), context=_context(),
    )
    assert result.state == STATE_APPROVED


def test_manual_lock_denies_buy() -> None:
    result = _evaluate(account_protection_evaluation=_protection(ACTION_BUY, manual=True))
    assert result.state == STATE_DENIED
    assert result.protection_code == PROTECTION_MANUAL_ACCOUNT_LOCK


def test_drawdown_protection_denies_buy() -> None:
    result = _evaluate(account_protection_evaluation=_protection(ACTION_BUY))
    assert result.state == STATE_DENIED
    assert result.protection_code == PROTECTION_MAX_ACCOUNT_DRAWDOWN_BLOCK


def test_protection_evaluation_binding_mismatch_denies_an_otherwise_approved_candidate() -> None:
    mismatched = _protection(ACTION_EXIT)
    result = _evaluate(account_protection_evaluation=mismatched)
    assert result.state == STATE_DENIED
    assert result.reason_code == "INVALID_PROTECTION_EVALUATION_BINDING"


def test_stale_account_or_free_quote_balance_is_non_actionable() -> None:
    stale_account = _evaluate(account_observed_ts_utc=NOW - timedelta(minutes=16))
    assert (stale_account.state, stale_account.reason_code) == (STATE_NON_ACTIONABLE, REASON_ACCOUNT_EVIDENCE_STALE)
    stale_balance = _evaluate(free_quote_balance_observed_ts_utc=NOW - timedelta(minutes=16))
    assert (stale_balance.state, stale_balance.reason_code) == (STATE_NON_ACTIONABLE, REASON_FREE_QUOTE_BALANCE_STALE)


def test_stale_candidate_evidence_is_non_actionable() -> None:
    result = evaluate_automatic_buy_candidate_permission_v1(
        candidate=_candidate(observed_ts_utc=NOW - timedelta(minutes=16)), context=_context(),
    )
    assert (result.state, result.reason_code) == (STATE_NON_ACTIONABLE, REASON_CANDIDATE_EVIDENCE_STALE)


def test_future_and_naive_timestamps_are_non_actionable() -> None:
    future_result = _evaluate(free_quote_balance_observed_ts_utc=NOW + timedelta(seconds=1))
    naive_result = _evaluate(free_quote_balance_observed_ts_utc=NOW.replace(tzinfo=None))
    assert (future_result.state, future_result.reason_code) == (STATE_NON_ACTIONABLE, REASON_FREE_QUOTE_BALANCE_STALE)
    assert (naive_result.state, naive_result.reason_code) == (STATE_NON_ACTIONABLE, REASON_INVALID_TIMESTAMP)


def test_market_identity_mismatches_are_non_actionable() -> None:
    assert _evaluate(venue="other").reason_code == REASON_IDENTITY_MISMATCH
    assert _evaluate(asset_id=99).reason_code == REASON_IDENTITY_MISMATCH
    assert _evaluate(market="ETH-EUR").reason_code == REASON_IDENTITY_MISMATCH


def test_zero_free_quote_balance_and_conflicts_are_denied() -> None:
    assert _evaluate(free_quote_balance_eur=Decimal("0")).reason_code == REASON_NO_FREE_QUOTE_BALANCE
    result = _evaluate(blocking_conflict=True)
    assert (result.state, result.reason_code) == (STATE_DENIED, REASON_BLOCKING_CONFLICT)


def test_disabled_execution_permission_is_denied() -> None:
    result = _evaluate(automatic_buy_execution_enabled=False)
    assert (result.state, result.reason_code) == (STATE_DENIED, REASON_EXECUTION_PERMISSION_DISABLED)


def test_account_disabled_is_denied() -> None:
    assert _evaluate(account_enabled=False).reason_code == REASON_ACCOUNT_DISABLED


def test_live_without_live_flag_is_non_actionable_and_other_unknown_modes_remain_unsupported() -> None:
    live = _evaluate(account_mode="live")
    assert (live.state, live.reason_code) == (STATE_NON_ACTIONABLE, REASON_ACCOUNT_MODE_EVIDENCE_INCONSISTENT)
    for mode in ("LIVE", "Paper", "demo", "", "sandbox"):
        result = _evaluate(account_mode=mode)
        assert (result.state, result.reason_code) == (STATE_NON_ACTIONABLE, REASON_UNSUPPORTED_ACCOUNT_MODE)


def test_negative_free_quote_balance_or_non_positive_proposed_amount_is_non_actionable() -> None:
    assert _evaluate(free_quote_balance_eur=Decimal("-1")).reason_code == REASON_INVALID_FREE_QUOTE_BALANCE
    assert _evaluate(proposed_position_amount_eur=Decimal("0")).reason_code == REASON_INVALID_PROPOSED_POSITION_AMOUNT


def test_malformed_candidate_provenance_is_non_actionable() -> None:
    for changes in ({"evidence_id": ""}, {"setup_id": ""}, {"strategy_id": ""}):
        result = evaluate_automatic_buy_candidate_permission_v1(candidate=_candidate(**changes), context=_context())
        assert (result.state, result.reason_code) == (STATE_NON_ACTIONABLE, REASON_INVALID_CANDIDATE)


def test_policy_contract_must_match_canonical_entry_policy_constants() -> None:
    assert _candidate().policy_name == POLICY_NAME
    assert _candidate().policy_version == POLICY_VERSION
    for changes in ({"policy_name": "other"}, {"policy_version": "2"}):
        result = evaluate_automatic_buy_candidate_permission_v1(candidate=_candidate(**changes), context=_context())
        assert (result.state, result.reason_code) == (STATE_NON_ACTIONABLE, REASON_UNSUPPORTED_POLICY_CONTRACT)


def test_disabled_strategy_bucket_denies() -> None:
    result = _evaluate(strategy_bucket_config_rows=(_bucket_row(is_enabled=False),))
    assert (result.state, result.reason_code) == (STATE_DENIED, REASON_BUCKET_DISABLED)
    assert result.strategy_bucket_reason_code == REASON_BUCKET_DISABLED


def test_new_entries_not_allowed_denies() -> None:
    result = _evaluate(strategy_bucket_config_rows=(_bucket_row(allow_new_entries=False),))
    assert (result.state, result.reason_code) == (STATE_DENIED, REASON_NEW_ENTRIES_NOT_ALLOWED)


def test_max_position_amount_ceiling_exceeded_denies() -> None:
    result = _evaluate(
        strategy_bucket_config_rows=(_bucket_row(max_position_amount_eur=Decimal("50")),),
        proposed_position_amount_eur=Decimal("100"),
    )
    assert (result.state, result.reason_code) == (STATE_DENIED, REASON_POSITION_AMOUNT_CEILING_EXCEEDED)


def test_max_open_positions_ceiling_exceeded_denies() -> None:
    result = _evaluate(
        strategy_bucket_config_rows=(_bucket_row(max_open_positions=2),),
        current_open_positions=2,
    )
    assert (result.state, result.reason_code) == (STATE_DENIED, REASON_OPEN_POSITIONS_CEILING_EXCEEDED)


def test_missing_strategy_bucket_configuration_denies() -> None:
    result = _evaluate(strategy_bucket_config_rows=())
    assert result.state == STATE_DENIED


def test_ceiling_is_bounded_by_free_quote_balance_and_risk_cap() -> None:
    capped_by_balance = _evaluate(free_quote_balance_eur=Decimal("40"))
    assert capped_by_balance.state == STATE_APPROVED
    assert capped_by_balance.approved_notional_ceiling_eur == Decimal("40")

    capped_by_risk = _evaluate(max_automatic_buy_notional_eur=Decimal("10"))
    assert capped_by_risk.state == STATE_APPROVED
    assert capped_by_risk.approved_notional_ceiling_eur == Decimal("10")

    zero_cap = _evaluate(max_automatic_buy_notional_eur=Decimal("0"))
    assert (zero_cap.state, zero_cap.reason_code) == (STATE_DENIED, REASON_RISK_BOUND_UNRESOLVED)

    invalid_cap = _evaluate(max_automatic_buy_notional_eur=Decimal("-1"))
    assert (invalid_cap.state, invalid_cap.reason_code) == (STATE_NON_ACTIONABLE, REASON_RISK_BOUND_UNRESOLVED)


def test_same_input_has_same_output() -> None:
    candidate, context = _candidate(), _context()
    assert evaluate_automatic_buy_candidate_permission_v1(
        candidate=candidate, context=context,
    ) == evaluate_automatic_buy_candidate_permission_v1(candidate=candidate, context=context)


def test_gate_has_no_planner_executor_broker_or_manual_dependencies() -> None:
    tree = ast.parse((Path("src/decision_gate") / "automatic_buy_gate_v1.py").read_text())
    imports = [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    ]
    assert not any(
        any(word in name for word in ("execution_planner", "executor", "broker", "manual_execution", "approval"))
        for name in imports
    )


def test_gate_does_not_re_evaluate_entry_zone_geometry() -> None:
    tree = ast.parse((Path("src/decision_gate") / "automatic_buy_gate_v1.py").read_text())
    candidate_attributes = {
        node.attr for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "candidate"
    }
    assert not {"entry_zone_low", "entry_zone_high"} & candidate_attributes
