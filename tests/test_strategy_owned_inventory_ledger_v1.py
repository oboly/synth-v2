"""Issue #752: strategy-owned inventory ledger -- ownership/authority tests.

Covers the #752 minimum test list items for fill attribution, idempotence,
cross-strategy/over-owned SELL rejection, unattributed inventory, and the
canonical two-strategy-same-market example from the task contract (SOL: 60
LONG_TERM_MOONSHOT, 40 AUTO_SHORTTF_FIB).
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.decision_gate.strategy_owned_inventory_ledger_v1 import (
    SIDE_BUY,
    SIDE_SELL,
    StrategyOwnedFillEventV1,
    StrategyOwnedInventoryLedgerError,
    StrategyOwnershipLineageV1,
    compute_bucket_owned_exposure_eur_v1,
    compute_lineage_residual_acquisition_cost_v1,
    compute_owned_quantity_v1,
    validate_sell_authority_v1,
)

NOW = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
ACCOUNT = 101


def _lineage(**changes: object) -> StrategyOwnershipLineageV1:
    values: dict[str, object] = dict(
        trading_account_id=ACCOUNT,
        venue="bitvavo",
        market="SOL-EUR",
        strategy_bucket_id="AUTO_SHORTTF_FIB",
        strategy_id="auto_shorttf_fib",
        strategy_version="1",
        setup_id="setup-1",
    )
    values.update(changes)
    return StrategyOwnershipLineageV1(**values)  # type: ignore[arg-type]


def _event(**changes: object) -> StrategyOwnedFillEventV1:
    values: dict[str, object] = dict(
        lineage=_lineage(),
        order_identity="order-1",
        execution_plan_reference_id="plan-ref-1",
        side=SIDE_BUY,
        base_quantity=Decimal("10"),
        quote_notional=Decimal("1000"),
        occurred_ts_utc=NOW,
        source_provenance="test",
    )
    values.update(changes)
    return StrategyOwnedFillEventV1(**values)  # type: ignore[arg-type]


LONG_TERM = _lineage(strategy_bucket_id="LONG_TERM_MOONSHOT", strategy_id="long_term_moonshot", setup_id="lt-setup-1")
SHORT_TF = _lineage(strategy_bucket_id="AUTO_SHORTTF_FIB", strategy_id="auto_shorttf_fib", setup_id="stf-setup-1")


# --- 10/11: BUY partial fill attribution + duplicate idempotence ----------


def test_buy_partial_fills_sum_to_owned_quantity():
    events = (
        _event(order_identity="o1", base_quantity=Decimal("4")),
        _event(order_identity="o2", base_quantity=Decimal("6")),
    )
    assert compute_owned_quantity_v1(events, lineage=_lineage()) == Decimal("10")


def test_duplicate_buy_fill_is_idempotent():
    events = (
        _event(order_identity="o1", base_quantity=Decimal("4")),
        _event(order_identity="o1", base_quantity=Decimal("4")),  # exact duplicate delivery
    )
    assert compute_owned_quantity_v1(events, lineage=_lineage()) == Decimal("4")


def test_conflicting_duplicate_order_identity_fails_closed():
    events = (
        _event(order_identity="o1", base_quantity=Decimal("4")),
        _event(order_identity="o1", base_quantity=Decimal("5")),  # same id, different qty
    )
    with pytest.raises(StrategyOwnedInventoryLedgerError, match="CONFLICTING_DUPLICATE_ORDER_IDENTITY"):
        compute_owned_quantity_v1(events, lineage=_lineage())


# --- #756 Codex block: duplicate order_identity with mismatched non-quantity
# fields (quote_notional, timestamp, plan reference, provenance) must also
# fail closed rather than being silently treated as an idempotent duplicate.


def test_conflicting_duplicate_quote_notional_fails_closed():
    events = (
        _event(order_identity="o1", quote_notional=Decimal("1000")),
        _event(order_identity="o1", quote_notional=Decimal("1200")),
    )
    with pytest.raises(StrategyOwnedInventoryLedgerError, match="CONFLICTING_DUPLICATE_ORDER_IDENTITY"):
        compute_owned_quantity_v1(events, lineage=_lineage())


def test_conflicting_duplicate_occurred_ts_fails_closed():
    events = (
        _event(order_identity="o1", occurred_ts_utc=NOW),
        _event(order_identity="o1", occurred_ts_utc=NOW + timedelta(minutes=5)),
    )
    with pytest.raises(StrategyOwnedInventoryLedgerError, match="CONFLICTING_DUPLICATE_ORDER_IDENTITY"):
        compute_owned_quantity_v1(events, lineage=_lineage())


def test_conflicting_duplicate_execution_plan_reference_fails_closed():
    events = (
        _event(order_identity="o1", execution_plan_reference_id="plan-ref-1"),
        _event(order_identity="o1", execution_plan_reference_id="plan-ref-2"),
    )
    with pytest.raises(StrategyOwnedInventoryLedgerError, match="CONFLICTING_DUPLICATE_ORDER_IDENTITY"):
        compute_owned_quantity_v1(events, lineage=_lineage())


def test_conflicting_duplicate_source_provenance_fails_closed():
    events = (
        _event(order_identity="o1", source_provenance="reconciliation"),
        _event(order_identity="o1", source_provenance="manual_review"),
    )
    with pytest.raises(StrategyOwnedInventoryLedgerError, match="CONFLICTING_DUPLICATE_ORDER_IDENTITY"):
        compute_owned_quantity_v1(events, lineage=_lineage())


# --- 12/13: SELL partial fill + duplicate idempotence ----------------------


def test_sell_partial_fill_reduces_matching_lineage_only():
    events = (
        _event(order_identity="b1", side=SIDE_BUY, base_quantity=Decimal("10")),
        _event(order_identity="s1", side=SIDE_SELL, base_quantity=Decimal("3")),
    )
    assert compute_owned_quantity_v1(events, lineage=_lineage()) == Decimal("7")


def test_duplicate_sell_fill_is_idempotent():
    events = (
        _event(order_identity="b1", side=SIDE_BUY, base_quantity=Decimal("10")),
        _event(order_identity="s1", side=SIDE_SELL, base_quantity=Decimal("3")),
        _event(order_identity="s1", side=SIDE_SELL, base_quantity=Decimal("3")),  # duplicate delivery
    )
    assert compute_owned_quantity_v1(events, lineage=_lineage()) == Decimal("7")


# --- 9/16: two strategies, same market, no collision -----------------------


def test_two_strategies_same_market_no_quantity_collision():
    events = (
        _event(lineage=LONG_TERM, order_identity="lt-buy-1", base_quantity=Decimal("60")),
        _event(lineage=SHORT_TF, order_identity="stf-buy-1", base_quantity=Decimal("40")),
    )
    assert compute_owned_quantity_v1(events, lineage=LONG_TERM) == Decimal("60")
    assert compute_owned_quantity_v1(events, lineage=SHORT_TF) == Decimal("40")


def test_shorttf_exit_of_40_permitted_and_long_term_60_untouched():
    events = (
        _event(lineage=LONG_TERM, order_identity="lt-buy-1", base_quantity=Decimal("60")),
        _event(lineage=SHORT_TF, order_identity="stf-buy-1", base_quantity=Decimal("40")),
    )
    remaining_before = validate_sell_authority_v1(
        events, lineage=SHORT_TF, requested_reduce_base_quantity=Decimal("40"),
    )
    assert remaining_before == Decimal("40")
    # Long-term's own quantity is never touched by evaluating ShortTF's exit.
    assert compute_owned_quantity_v1(events, lineage=LONG_TERM) == Decimal("60")


def test_shorttf_exit_of_41_fails_closed_long_term_60_remains_untouched():
    events = (
        _event(lineage=LONG_TERM, order_identity="lt-buy-1", base_quantity=Decimal("60")),
        _event(lineage=SHORT_TF, order_identity="stf-buy-1", base_quantity=Decimal("40")),
    )
    with pytest.raises(StrategyOwnedInventoryLedgerError, match="SELL_QUANTITY_EXCEEDS_OWNED_LINEAGE_QUANTITY"):
        validate_sell_authority_v1(events, lineage=SHORT_TF, requested_reduce_base_quantity=Decimal("41"))
    assert compute_owned_quantity_v1(events, lineage=LONG_TERM) == Decimal("60")


# --- 14: cross-strategy SELL rejected --------------------------------------


def test_cross_strategy_sell_rejected():
    events = (_event(lineage=LONG_TERM, order_identity="lt-buy-1", base_quantity=Decimal("60")),)
    # AUTO_SHORTTF_FIB has recorded zero BUY fills; it may not reduce
    # LONG_TERM_MOONSHOT's quantity by requesting against its own lineage.
    with pytest.raises(StrategyOwnedInventoryLedgerError, match="SELL_QUANTITY_EXCEEDS_OWNED_LINEAGE_QUANTITY"):
        validate_sell_authority_v1(events, lineage=SHORT_TF, requested_reduce_base_quantity=Decimal("1"))


# --- 15: over-owned SELL rejected ------------------------------------------


def test_over_owned_sell_rejected():
    events = (_event(order_identity="b1", base_quantity=Decimal("10")),)
    with pytest.raises(StrategyOwnedInventoryLedgerError, match="SELL_QUANTITY_EXCEEDS_OWNED_LINEAGE_QUANTITY"):
        validate_sell_authority_v1(events, lineage=_lineage(), requested_reduce_base_quantity=Decimal("11"))


# --- 17: unattributed/manual inventory gives zero automated SELL authority -


def test_unattributed_inventory_has_zero_automated_sell_authority():
    # No fill events recorded for this lineage at all (e.g. manually
    # deposited or pre-#752 inventory) -- owned quantity is 0 and any
    # positive reduction request fails closed.
    assert compute_owned_quantity_v1((), lineage=_lineage()) == Decimal("0")
    with pytest.raises(StrategyOwnedInventoryLedgerError, match="SELL_QUANTITY_EXCEEDS_OWNED_LINEAGE_QUANTITY"):
        validate_sell_authority_v1((), lineage=_lineage(), requested_reduce_base_quantity=Decimal("0.00000001"))


# --- 21: account/strategy/market identity mismatch fails closed -----------


def test_incomplete_lineage_fails_closed():
    with pytest.raises(StrategyOwnedInventoryLedgerError, match="INVALID_STRATEGY_OWNERSHIP_LINEAGE"):
        compute_owned_quantity_v1((), lineage=_lineage(setup_id=""))


def test_malformed_fill_event_fails_closed():
    bad_event = _event(base_quantity=Decimal("-1"))
    with pytest.raises(StrategyOwnedInventoryLedgerError, match="INVALID_FILL_EVENT_BASE_QUANTITY"):
        compute_owned_quantity_v1((bad_event,), lineage=_lineage())


# --- 19: allocation max exceeded still permits reducing/protective SELL ---


def test_sell_authority_never_consults_allocation_max_pct_ceiling():
    # validate_sell_authority_v1 takes no capacity/allocation-ceiling input
    # at all -- a bucket whose allocation_max_pct is already fully consumed
    # (simulated here by owning exactly its ceiling) must still permit a
    # valid reduction of its own owned quantity.
    events = (_event(order_identity="b1", base_quantity=Decimal("100")),)
    remaining = validate_sell_authority_v1(events, lineage=_lineage(), requested_reduce_base_quantity=Decimal("100"))
    assert remaining == Decimal("100")


# --- 20: restart/reload preserves ownership (ledger is stateless/derived) --


def test_ownership_is_deterministically_reconstructible_from_events_alone():
    events = (
        _event(order_identity="o1", base_quantity=Decimal("4")),
        _event(order_identity="o2", base_quantity=Decimal("6")),
        _event(order_identity="s1", side=SIDE_SELL, base_quantity=Decimal("2")),
    )
    # Simulates a restart: recomputing from the exact same persisted events
    # (in a different iteration order) yields the identical result -- no
    # separately maintained mutable counter to lose on restart.
    reordered = tuple(reversed(events))
    assert compute_owned_quantity_v1(events, lineage=_lineage()) == compute_owned_quantity_v1(
        reordered, lineage=_lineage(),
    ) == Decimal("8")


# --- #756 Codex block BLOCKER 2: residual acquisition exposure must be
# deterministic weighted-average cost basis, never
# sum(BUY quote_notional) - sum(SELL proceeds) -----------------------------


def test_profitable_full_sell_exposure_is_zero():
    events = (
        _event(order_identity="b1", base_quantity=Decimal("10"), quote_notional=Decimal("100")),
        _event(order_identity="s1", side=SIDE_SELL, base_quantity=Decimal("10"), quote_notional=Decimal("110")),
    )
    assert compute_lineage_residual_acquisition_cost_v1(events, lineage=_lineage()) == Decimal("0")


def test_losing_full_sell_exposure_is_zero():
    events = (
        _event(order_identity="b1", base_quantity=Decimal("10"), quote_notional=Decimal("100")),
        _event(order_identity="s1", side=SIDE_SELL, base_quantity=Decimal("10"), quote_notional=Decimal("90")),
    )
    assert compute_lineage_residual_acquisition_cost_v1(events, lineage=_lineage()) == Decimal("0")


def test_partial_profitable_sell_residual_cost_basis_correct():
    # BUY 10 for 100 (avg cost 10/unit); SELL 5 at 15 each (proceeds 75,
    # ignored) -- residual exposure must be 5 * 10 = 50, not 25 (100-75) and
    # not -25.
    events = (
        _event(order_identity="b1", base_quantity=Decimal("10"), quote_notional=Decimal("100")),
        _event(order_identity="s1", side=SIDE_SELL, base_quantity=Decimal("5"), quote_notional=Decimal("75")),
    )
    assert compute_lineage_residual_acquisition_cost_v1(events, lineage=_lineage()) == Decimal("50")


def test_partial_losing_sell_residual_cost_basis_same_as_profitable_for_same_qty():
    # Identical BUY and identical quantity sold -- only the SELL proceeds
    # differ (a loss instead of a gain) -- residual exposure must be
    # identical, since proceeds/realized PnL must never affect it.
    events = (
        _event(order_identity="b1", base_quantity=Decimal("10"), quote_notional=Decimal("100")),
        _event(order_identity="s1", side=SIDE_SELL, base_quantity=Decimal("5"), quote_notional=Decimal("30")),
    )
    assert compute_lineage_residual_acquisition_cost_v1(events, lineage=_lineage()) == Decimal("50")


def test_multiple_buy_fills_deterministic_weighted_average_basis():
    events = (
        _event(order_identity="b1", base_quantity=Decimal("10"), quote_notional=Decimal("100")),
        _event(order_identity="b2", base_quantity=Decimal("10"), quote_notional=Decimal("200")),
    )
    # avg cost = 300 / 20 = 15/unit; no SELL yet -- full 300 remains.
    assert compute_lineage_residual_acquisition_cost_v1(events, lineage=_lineage()) == Decimal("300")


def test_partial_sell_after_multiple_buys_uses_weighted_average():
    events = (
        _event(order_identity="b1", base_quantity=Decimal("10"), quote_notional=Decimal("100")),
        _event(order_identity="b2", base_quantity=Decimal("10"), quote_notional=Decimal("200")),
        _event(order_identity="s1", side=SIDE_SELL, base_quantity=Decimal("10"), quote_notional=Decimal("999")),
    )
    # avg cost 15/unit; SELL 10 removes 150 regardless of its own proceeds;
    # residual = 300 - 150 = 150.
    assert compute_lineage_residual_acquisition_cost_v1(events, lineage=_lineage()) == Decimal("150")


def test_cost_basis_duplicate_fill_is_idempotent():
    events = (
        _event(order_identity="b1", base_quantity=Decimal("10"), quote_notional=Decimal("100")),
        _event(order_identity="b1", base_quantity=Decimal("10"), quote_notional=Decimal("100")),
    )
    assert compute_lineage_residual_acquisition_cost_v1(events, lineage=_lineage()) == Decimal("100")


def test_cost_basis_conflicting_duplicate_fill_fails_closed():
    events = (
        _event(order_identity="b1", base_quantity=Decimal("10"), quote_notional=Decimal("100")),
        _event(order_identity="b1", base_quantity=Decimal("10"), quote_notional=Decimal("120")),
    )
    with pytest.raises(StrategyOwnedInventoryLedgerError, match="CONFLICTING_DUPLICATE_ORDER_IDENTITY"):
        compute_lineage_residual_acquisition_cost_v1(events, lineage=_lineage())


def test_cost_basis_sell_over_owned_qty_fails_closed():
    events = (_event(order_identity="b1", base_quantity=Decimal("10"), quote_notional=Decimal("100")),)
    with pytest.raises(StrategyOwnedInventoryLedgerError, match="NEGATIVE_OWNED_QUANTITY_LEDGER_INCONSISTENT"):
        compute_lineage_residual_acquisition_cost_v1(
            events + (_event(order_identity="s1", side=SIDE_SELL, base_quantity=Decimal("11"), quote_notional=Decimal("1")),),
            lineage=_lineage(),
        )


def test_cost_basis_input_order_does_not_change_final_state():
    # Canonical sequence order is defined by occurred_ts_utc, not input
    # iteration order -- reversing the input tuple must yield the identical
    # residual cost.
    events = (
        _event(order_identity="b1", base_quantity=Decimal("10"), quote_notional=Decimal("100"), occurred_ts_utc=NOW),
        _event(
            order_identity="b2", base_quantity=Decimal("10"), quote_notional=Decimal("200"),
            occurred_ts_utc=NOW + timedelta(minutes=1),
        ),
        _event(
            order_identity="s1", side=SIDE_SELL, base_quantity=Decimal("10"), quote_notional=Decimal("999"),
            occurred_ts_utc=NOW + timedelta(minutes=2),
        ),
    )
    forward = compute_lineage_residual_acquisition_cost_v1(events, lineage=_lineage())
    reversed_input = compute_lineage_residual_acquisition_cost_v1(tuple(reversed(events)), lineage=_lineage())
    assert forward == reversed_input == Decimal("150")


def test_bucket_exposure_sums_residual_cost_basis_across_lineages():
    other_lineage_event = _event(
        lineage=LONG_TERM, order_identity="lt-b1", base_quantity=Decimal("4"), quote_notional=Decimal("40"),
    )
    this_lineage_events = (
        _event(order_identity="b1", base_quantity=Decimal("10"), quote_notional=Decimal("100")),
        _event(order_identity="s1", side=SIDE_SELL, base_quantity=Decimal("5"), quote_notional=Decimal("75")),
    )
    events = this_lineage_events + (other_lineage_event,)
    # SHORT_TF lineage residual = 50 (from the partial-sell test above);
    # LONG_TERM lineage residual = 40 (no SELL yet) -- but LONG_TERM_MOONSHOT
    # is a different strategy_bucket_id, so it must not be included.
    assert compute_bucket_owned_exposure_eur_v1(
        events, trading_account_id=ACCOUNT, strategy_bucket_id="AUTO_SHORTTF_FIB",
    ) == Decimal("50")


def test_bucket_exposure_sums_multiple_lineages_in_same_bucket():
    same_bucket_other_strategy = _lineage(strategy_id="another_strategy", setup_id="setup-2")
    events = (
        _event(order_identity="b1", base_quantity=Decimal("10"), quote_notional=Decimal("100")),
        _event(
            lineage=same_bucket_other_strategy, order_identity="b2",
            base_quantity=Decimal("4"), quote_notional=Decimal("40"),
        ),
    )
    assert compute_bucket_owned_exposure_eur_v1(
        events, trading_account_id=ACCOUNT, strategy_bucket_id="AUTO_SHORTTF_FIB",
    ) == Decimal("140")
