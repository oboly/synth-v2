"""Issue #752 Codex block fix: gate-level integration tests proving sleeve
capacity enforcement runs inside the actual canonical account-aware
automatic-BUY decision path (``evaluate_automatic_buy_candidate_permission_v1``
in ``src/decision_gate/automatic_buy_gate_v1.py``), not only in the
standalone ``strategy_bucket_capacity_v1``/``strategy_owned_inventory_ledger_v1``
unit tests.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.decision_gate.automatic_buy_gate_v1 import (
    REASON_AGGREGATE_SLEEVE_ALLOCATION_POLICY_EXCEEDED,
    REASON_STRATEGY_BUCKET_CAPACITY_EVIDENCE_MISSING,
    REASON_STRATEGY_BUCKET_CAPACITY_EXCEEDED,
    STATE_APPROVED,
    STATE_DENIED,
    AutomaticBuyGateContextV1,
    evaluate_automatic_buy_candidate_permission_v1,
)
from src.decision_gate.strategy_bucket_account_config_contract_v1 import StrategyBucketAccountConfigRowV1
from src.entry_policy.automatic_buy_candidate_v1 import AutomaticBuyCandidateV1

NOW = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
BUCKET = "AUTO_SHORTTF_FIB"
OTHER_BUCKET = "LONG_TERM_MOONSHOT"
ACCOUNT = 7


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
        strategy_bucket_account_config_id=1, trading_account_id=ACCOUNT, strategy_bucket_id=BUCKET,
        config_version="1", is_enabled=True, risk_profile="MODERATE",
        max_position_amount_eur=None, max_bucket_amount_eur=None, max_asset_exposure_pct=None,
        max_open_positions=None, allow_new_entries=True, allow_reduce_reviews=True,
        effective_from_ts_utc=NOW - timedelta(days=1), effective_until_ts_utc=None,
        source_provenance="manual_review", allocation_target_pct=None, allocation_max_pct=None,
        max_position_pct_of_bucket=None,
    )
    values.update(changes)
    return StrategyBucketAccountConfigRowV1(**values)  # type: ignore[arg-type]


def _context(**changes: object) -> AutomaticBuyGateContextV1:
    values: dict[str, object] = dict(
        trading_account_id=ACCOUNT, venue="bitvavo", asset_id=42, market="SOL-EUR",
        strategy_bucket_id=BUCKET, account_observed_ts_utc=NOW, account_enabled=True,
        account_mode="paper", automatic_buy_execution_enabled=True,
        free_quote_balance_eur=Decimal("100000"), free_quote_balance_observed_ts_utc=NOW,
        blocking_conflict=False, proposed_position_amount_eur=Decimal("100"),
        current_bucket_amount_eur=Decimal("0"), current_open_positions=0,
        current_asset_exposure_pct=Decimal("0"), evaluation_ts_utc=NOW,
        strategy_bucket_config_rows=(_bucket_row(),),
    )
    values.update(changes)
    return AutomaticBuyGateContextV1(**values)  # type: ignore[arg-type]


def _evaluate(**changes: object):
    return evaluate_automatic_buy_candidate_permission_v1(candidate=_candidate(), context=_context(**changes))


# --- 1/5: new BUY below/crossing remaining sleeve capacity ----------------


def test_new_buy_below_remaining_sleeve_capacity_is_allowed():
    result = _evaluate(
        strategy_bucket_config_rows=(_bucket_row(allocation_max_pct=Decimal("0.5")),),
        proposed_position_amount_eur=Decimal("400"),
        account_equity_eur=Decimal("1000"),
        strategy_owned_exposure_eur=Decimal("0"),
    )
    # 50% of 1000 = 500 remaining capacity; 400 fits.
    assert result.state == STATE_APPROVED
    assert result.approved_notional_ceiling_eur == Decimal("400")


def test_new_buy_above_remaining_sleeve_capacity_is_blocked():
    result = _evaluate(
        strategy_bucket_config_rows=(_bucket_row(allocation_max_pct=Decimal("0.5")),),
        proposed_position_amount_eur=Decimal("600"),
        account_equity_eur=Decimal("1000"),
        strategy_owned_exposure_eur=Decimal("0"),
    )
    # 50% of 1000 = 500 remaining capacity; 600 exceeds it.
    assert result.state == STATE_DENIED
    assert result.reason_code == REASON_STRATEGY_BUCKET_CAPACITY_EXCEEDED


# --- 3: current owned exposure reduces remaining capacity ------------------


def test_current_owned_exposure_reduces_remaining_capacity():
    result = _evaluate(
        strategy_bucket_config_rows=(_bucket_row(allocation_max_pct=Decimal("0.5")),),
        proposed_position_amount_eur=Decimal("200"),
        account_equity_eur=Decimal("1000"),
        strategy_owned_exposure_eur=Decimal("400"),
    )
    # Ceiling 500 - already-owned 400 = 100 remaining; 200 exceeds it.
    assert result.state == STATE_DENIED
    assert result.reason_code == REASON_STRATEGY_BUCKET_CAPACITY_EXCEEDED


def test_current_owned_exposure_leaves_enough_room_when_small():
    result = _evaluate(
        strategy_bucket_config_rows=(_bucket_row(allocation_max_pct=Decimal("0.5")),),
        proposed_position_amount_eur=Decimal("50"),
        account_equity_eur=Decimal("1000"),
        strategy_owned_exposure_eur=Decimal("400"),
    )
    # Ceiling 500 - already-owned 400 = 100 remaining; 50 fits.
    assert result.state == STATE_APPROVED


# --- 4: active BUY reservations reduce remaining capacity ------------------


def test_active_buy_reservations_reduce_remaining_capacity():
    result = _evaluate(
        strategy_bucket_config_rows=(_bucket_row(allocation_max_pct=Decimal("0.5")),),
        proposed_position_amount_eur=Decimal("100"),
        account_equity_eur=Decimal("1000"),
        strategy_owned_exposure_eur=Decimal("0"),
        active_buy_reservations_eur=Decimal("450"),
    )
    # Ceiling 500 - reservations 450 = 50 remaining; 100 exceeds it.
    assert result.state == STATE_DENIED
    assert result.reason_code == REASON_STRATEGY_BUCKET_CAPACITY_EXCEEDED


# --- 6: allocation_target_pct does not force/authorize exposure ------------


def test_allocation_target_pct_does_not_force_or_authorize_exposure():
    # A low target alongside a higher max (target <= max is required by
    # #279/#752 config validation) must never itself widen or narrow the
    # ceiling -- only max (and the absolute cap) govern it.
    result = _evaluate(
        strategy_bucket_config_rows=(
            _bucket_row(allocation_target_pct=Decimal("0.01"), allocation_max_pct=Decimal("0.1")),
        ),
        proposed_position_amount_eur=Decimal("150"),
        account_equity_eur=Decimal("1000"),
        strategy_owned_exposure_eur=Decimal("0"),
    )
    # 10% of 1000 = 100 ceiling (not 1% = 10); 150 exceeds it.
    assert result.state == STATE_DENIED
    assert result.reason_code == REASON_STRATEGY_BUCKET_CAPACITY_EXCEEDED


def test_allocation_target_pct_alone_never_blocks_when_max_has_room():
    result = _evaluate(
        strategy_bucket_config_rows=(
            _bucket_row(allocation_target_pct=Decimal("0.01"), allocation_max_pct=Decimal("0.5")),
        ),
        proposed_position_amount_eur=Decimal("400"),
        account_equity_eur=Decimal("1000"),
        strategy_owned_exposure_eur=Decimal("0"),
    )
    assert result.state == STATE_APPROVED


# --- 7/8: absolute EUR cap vs percent cap, whichever is stricter wins ------


def test_absolute_cap_wins_when_stricter_than_percent():
    # current_bucket_amount_eur (the #279 whole-account approximation) stays
    # 0 so the pre-existing #279 absolute check never fires here -- isolates
    # #752's own capacity check, which reduces the stricter 100 absolute
    # ceiling by the ledger-derived strategy_owned_exposure_eur (60).
    result = _evaluate(
        strategy_bucket_config_rows=(
            _bucket_row(allocation_max_pct=Decimal("0.5"), max_bucket_amount_eur=Decimal("100")),
        ),
        proposed_position_amount_eur=Decimal("50"),
        current_bucket_amount_eur=Decimal("0"),
        account_equity_eur=Decimal("1000"),
        strategy_owned_exposure_eur=Decimal("60"),
    )
    # min(500, 100) = 100 ceiling; 100 - 60 owned = 40 remaining; 50 exceeds it.
    assert result.state == STATE_DENIED
    assert result.reason_code == REASON_STRATEGY_BUCKET_CAPACITY_EXCEEDED


def test_percent_cap_wins_when_stricter_than_absolute():
    result = _evaluate(
        strategy_bucket_config_rows=(
            _bucket_row(allocation_max_pct=Decimal("0.05"), max_bucket_amount_eur=Decimal("1000")),
        ),
        proposed_position_amount_eur=Decimal("70"),
        account_equity_eur=Decimal("1000"),
        strategy_owned_exposure_eur=Decimal("0"),
    )
    # 5% of 1000 = 50, stricter than the 1000 absolute cap; 70 exceeds it.
    assert result.state == STATE_DENIED
    assert result.reason_code == REASON_STRATEGY_BUCKET_CAPACITY_EXCEEDED


# --- 9: missing/stale equity/capacity evidence fails closed for NEW exposure


def test_missing_account_equity_fails_closed_when_allocation_max_pct_configured():
    result = _evaluate(
        strategy_bucket_config_rows=(_bucket_row(allocation_max_pct=Decimal("0.5")),),
        proposed_position_amount_eur=Decimal("10"),
        account_equity_eur=None,
        strategy_owned_exposure_eur=Decimal("0"),
    )
    assert result.state == STATE_DENIED
    assert result.reason_code == REASON_STRATEGY_BUCKET_CAPACITY_EVIDENCE_MISSING


def test_missing_strategy_owned_exposure_fails_closed_when_allocation_max_pct_configured():
    result = _evaluate(
        strategy_bucket_config_rows=(_bucket_row(allocation_max_pct=Decimal("0.5")),),
        proposed_position_amount_eur=Decimal("10"),
        account_equity_eur=Decimal("1000"),
        strategy_owned_exposure_eur=None,
    )
    assert result.state == STATE_DENIED
    assert result.reason_code == REASON_STRATEGY_BUCKET_CAPACITY_EVIDENCE_MISSING


# --- 10: legacy config with allocation_max_pct NULL keeps prior behavior --


def test_legacy_config_with_allocation_max_pct_null_ignores_missing_capacity_evidence():
    # No percentage policy configured at all -- missing equity/exposure
    # evidence must never newly block this account, preserving #279's exact
    # prior "no ceiling configured means no block" behavior.
    result = _evaluate(
        strategy_bucket_config_rows=(_bucket_row(allocation_max_pct=None),),
        proposed_position_amount_eur=Decimal("100"),
        account_equity_eur=None,
        strategy_owned_exposure_eur=None,
    )
    assert result.state == STATE_APPROVED
    assert result.approved_notional_ceiling_eur == Decimal("100")


def test_legacy_config_absolute_only_behavior_unaffected_by_752():
    result = _evaluate(
        strategy_bucket_config_rows=(_bucket_row(allocation_max_pct=None, max_bucket_amount_eur=Decimal("50")),),
        proposed_position_amount_eur=Decimal("100"),
        current_bucket_amount_eur=Decimal("0"),
        account_equity_eur=None,
        strategy_owned_exposure_eur=None,
    )
    # Blocked by #279's own existing max_bucket_amount_eur ceiling (0 + 100
    # > 50), evaluated by evaluate_strategy_bucket_participation_v1 exactly
    # as before -- #752's capacity check never even runs since
    # allocation_max_pct is None.
    assert result.state == STATE_DENIED
    assert result.reason_code == "STRATEGY_BUCKET_AMOUNT_CEILING_EXCEEDED"


# --- 11: aggregate enabled-bucket max >100% fails closed before new exposure


def test_aggregate_enabled_bucket_max_over_100_percent_fails_closed():
    result = _evaluate(
        strategy_bucket_config_rows=(
            _bucket_row(strategy_bucket_id=BUCKET, allocation_max_pct=Decimal("0.7")),
            _bucket_row(
                strategy_bucket_account_config_id=2, strategy_bucket_id=OTHER_BUCKET,
                allocation_max_pct=Decimal("0.4"),
            ),
        ),
        proposed_position_amount_eur=Decimal("10"),
        account_equity_eur=Decimal("1000"),
        strategy_owned_exposure_eur=Decimal("0"),
    )
    assert result.state == STATE_DENIED
    assert result.reason_code == REASON_AGGREGATE_SLEEVE_ALLOCATION_POLICY_EXCEEDED


def test_aggregate_enabled_bucket_max_within_100_percent_permitted():
    result = _evaluate(
        strategy_bucket_config_rows=(
            _bucket_row(strategy_bucket_id=BUCKET, allocation_max_pct=Decimal("0.4")),
            _bucket_row(
                strategy_bucket_account_config_id=2, strategy_bucket_id=OTHER_BUCKET,
                allocation_max_pct=Decimal("0.4"),
            ),
        ),
        proposed_position_amount_eur=Decimal("10"),
        account_equity_eur=Decimal("1000"),
        strategy_owned_exposure_eur=Decimal("0"),
    )
    assert result.state == STATE_APPROVED


def test_aggregate_policy_ignores_disabled_sibling_bucket():
    result = _evaluate(
        strategy_bucket_config_rows=(
            _bucket_row(strategy_bucket_id=BUCKET, allocation_max_pct=Decimal("0.4")),
            _bucket_row(
                strategy_bucket_account_config_id=2, strategy_bucket_id=OTHER_BUCKET,
                is_enabled=False, allocation_max_pct=Decimal("0.9"),
            ),
        ),
        proposed_position_amount_eur=Decimal("10"),
        account_equity_eur=Decimal("1000"),
        strategy_owned_exposure_eur=Decimal("0"),
    )
    assert result.state == STATE_APPROVED
