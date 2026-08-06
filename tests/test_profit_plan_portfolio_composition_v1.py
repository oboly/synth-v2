from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from src.market_data.native_short_fib_context_v1 import write_context_rows
import src.reporting.run_manual_short_trader_profit_plan_v1 as profit_plan_runner
from src.reporting.manual_short_trader_dashboard_v1 import BrokerBalanceRow
from src.reporting.manual_short_trader_profit_plan_v1 import (
    CARD_MODE_MARKET_SELECTED,
    CARD_MODE_POSITION_HELD,
    CardEvidence,
    apply_portfolio_account_evidence,
    build_json_snapshot,
    build_profit_plan_card,
)

from tests.test_manual_short_trader_profit_plan_v1 import _canonical_fib_row, _native_short_row


def test_held_amount_and_value_by_symbol_computes_totals_and_eur_value() -> None:
    """Authoritative held-asset universe: available + in_order per symbol, and
    EUR value from the current price snapshot. Zero-balance rows are excluded."""
    balances = (
        BrokerBalanceRow(symbol="BTC", available=Decimal("0.5"), in_order=Decimal("0.1")),
        BrokerBalanceRow(symbol="ETH", available=Decimal("2"), in_order=Decimal("0")),
        BrokerBalanceRow(symbol="XRP", available=Decimal("0"), in_order=Decimal("0")),
        BrokerBalanceRow(symbol="EUR", available=Decimal("100"), in_order=Decimal("0")),
    )
    prices = {"BTC-EUR": Decimal("50000"), "ETH-EUR": Decimal("2000")}
    amount_by_symbol, eur_value_by_symbol = profit_plan_runner.held_amount_and_value_by_symbol(
        balances=list(balances),
        prices=prices,
    )
    assert amount_by_symbol == {"BTC": Decimal("0.6"), "ETH": Decimal("2")}
    assert eur_value_by_symbol["BTC"] == Decimal("30000.0")
    assert eur_value_by_symbol["ETH"] == Decimal("4000")
    assert "XRP" not in amount_by_symbol
    assert "EUR" not in amount_by_symbol


def test_held_amount_and_value_missing_price_stays_none_not_zero() -> None:
    """No price snapshot for a held symbol must yield None (DATA_UNAVAILABLE
    display), never a fabricated zero EUR value."""
    balances = (BrokerBalanceRow(symbol="SOL", available=Decimal("10"), in_order=Decimal("0")),)
    amount_by_symbol, eur_value_by_symbol = profit_plan_runner.held_amount_and_value_by_symbol(
        balances=list(balances),
        prices={},
    )
    assert amount_by_symbol == {"SOL": Decimal("10")}
    assert eur_value_by_symbol["SOL"] is None


def test_apply_portfolio_account_evidence_renders_held_balance_cost_basis_and_freshness() -> None:
    card = build_profit_plan_card(
        symbol="BTC",
        market="BTC-EUR",
        current_price=Decimal("50000"),
        short_context_input_status="MISSING_ZONE_CONTEXT",
        short_context_coverage_status="CONTEXT_INVALID_OR_STALE",
        short_context_display_state="NO_NATIVE_SHORT_FIB_CONTEXT",
        presentation_mode=CARD_MODE_POSITION_HELD,
    )
    [composed] = apply_portfolio_account_evidence(
        [card],
        held_amount_by_symbol={"BTC": Decimal("0.6")},
        held_eur_value_by_symbol={"BTC": Decimal("30000")},
        cost_basis_by_symbol={"BTC": Decimal("28000")},
        balance_freshness_status="FRESH",
    )
    assert composed.evidence.held_amount == "0.6"
    assert composed.evidence.held_eur_value == "30000"
    assert composed.evidence.cost_basis_price_eur == "28000"
    assert composed.evidence.wallet_snapshot_status == "FRESH"
    assert composed.evidence.position_snapshot_status == "FRESH"


def test_apply_portfolio_account_evidence_missing_cost_basis_stays_truthfully_unavailable() -> None:
    """account_position_snapshot.average_entry_price_eur is currently always
    NULL from the writer; the composer must report DATA_UNAVAILABLE, not a
    fabricated cost basis."""
    card = build_profit_plan_card(
        symbol="ETH",
        market="ETH-EUR",
        current_price=Decimal("2000"),
        short_context_input_status="MISSING_ZONE_CONTEXT",
        short_context_coverage_status="CONTEXT_INVALID_OR_STALE",
        short_context_display_state="NO_NATIVE_SHORT_FIB_CONTEXT",
        presentation_mode=CARD_MODE_POSITION_HELD,
    )
    [composed] = apply_portfolio_account_evidence(
        [card],
        held_amount_by_symbol={"ETH": Decimal("2")},
        held_eur_value_by_symbol={"ETH": Decimal("4000")},
        cost_basis_by_symbol={},
        balance_freshness_status="FRESH",
    )
    assert composed.evidence.cost_basis_price_eur == "DATA_UNAVAILABLE"
    assert composed.evidence.position_snapshot_status == "DATA_UNAVAILABLE"


def test_apply_portfolio_account_evidence_leaves_non_held_cards_untouched() -> None:
    card = build_profit_plan_card(
        symbol="ONDO",
        market="ONDO-EUR",
        current_price=Decimal("1"),
        short_context_input_status="MISSING_ZONE_CONTEXT",
        short_context_coverage_status="CONTEXT_INVALID_OR_STALE",
        short_context_display_state="NO_NATIVE_SHORT_FIB_CONTEXT",
        presentation_mode=CARD_MODE_MARKET_SELECTED,
    )
    [composed] = apply_portfolio_account_evidence(
        [card],
        held_amount_by_symbol={},
        held_eur_value_by_symbol={},
        cost_basis_by_symbol={},
        balance_freshness_status="FRESH",
    )
    assert composed is card
    assert composed.evidence.held_amount == "DATA_UNAVAILABLE"


def test_load_zone_contexts_partial_native_row_fills_reentry_from_canonical_for_planning_ppp() -> None:
    """Root cause of the BTC-only Planning PPP gap (Issue #238): a present
    native row in a non-AVAILABLE lifecycle state (e.g. ETH 'Wait for entry')
    must not block the read-only canonical 4h reference from filling in the
    missing reentry context, so a held token still gets a numeric Planning PPP
    without requiring native SHORT lifecycle proof."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fib_rows = Path(tmpdir) / "fibo_target_map_rows_v1.csv"
        fib_rows.write_text(
            "symbol,current_price,swing_low_price,swing_high_price,local_reaction_price,next_fibo_support_price\n",
            encoding="utf-8",
        )
        native_dir = Path(tmpdir) / "native"
        native_paths = write_context_rows(
            rows=[_native_short_row(symbol="ETH", status="WAITING_FOR_ENTRY")],
            output_dir=native_dir,
        )
        result = profit_plan_runner.load_zone_contexts(
            markets=["ETH-EUR"],
            prices={"ETH-EUR": Decimal("0.48")},
            swing_anchors={},
            recent_lows={},
            native_short_rows_path=native_paths["rows_csv"],
            fib_map_rows_path=fib_rows,
            canonical_fib_rows_by_symbol={"ETH": _canonical_fib_row(symbol="ETH")},
            now_utc=datetime(2026, 8, 6, 9, 0, tzinfo=UTC),
        )
        # Native lifecycle truth is untouched: still not AVAILABLE, still no
        # native-canonical map identity claimed.
        assert result.input_status_by_symbol["ETH"] == "WAITING_FOR_ENTRY"
        assert result.display_state_by_symbol["ETH"] == "NO_NATIVE_SHORT_FIB_CONTEXT"
        # Native-derived fib_ext values are preserved, not overwritten by canonical.
        assert result.fib_ext_by_symbol["ETH"].ext_1_618 == Decimal("0.515600")
        # Reentry (reference re-entry zone) is now filled in from canonical 4h —
        # this is the missing input that previously left Planning PPP unavailable
        # for every held token except BTC.
        assert "ETH" in result.reentry_by_symbol
        assert result.reentry_by_symbol["ETH"].r382_price == Decimal("1.10")


def test_planning_ppp_numeric_once_reference_entry_and_target_are_both_present() -> None:
    """Planning PPP only needs a reference entry (reload/buy zone) and a
    reference target — it must never require native SHORT lifecycle proof to
    produce a number. This is the composition the load_zone_contexts fallback
    above unlocks for held tokens that only have a partial/non-AVAILABLE
    native row plus a canonical 4h reference."""
    import dataclasses

    from src.reporting.manual_short_trader_profit_plan_v1 import (
        TargetLevelStatus,
        _planning_ppp,
        _planning_ppp_unavailable_reason,
    )

    card = build_profit_plan_card(
        symbol="ETH",
        market="ETH-EUR",
        current_price=Decimal("0.48"),
        short_context_input_status="WAITING_FOR_ENTRY",
        short_context_coverage_status="WAITING_FOR_ENTRY",
        short_context_display_state="NO_NATIVE_SHORT_FIB_CONTEXT",
        presentation_mode=CARD_MODE_POSITION_HELD,
    )
    card = dataclasses.replace(
        card,
        reload_reentry_zone=(Decimal("0.40"),),
        target_exit_zone=(Decimal("0.60"),),
        target_level_statuses=(
            TargetLevelStatus(
                level=Decimal("0.60"),
                lifecycle_state="UPCOMING",
                coverage_state="COVERED",
                human_label="target",
                retest_context=None,
                first_cross_ts_utc=None,
                distance_pct=None,
                matching_open_sell_orders=0,
                nearest_open_sell_price=None,
                nearest_open_sell_distance_pct=None,
                is_active_target=True,
            ),
        ),
    )
    ppp = _planning_ppp(card)
    assert ppp is not None
    assert ppp == Decimal("50")  # (0.60 - 0.40) / 0.40 * 100
    assert _planning_ppp_unavailable_reason(card) is None


def test_planning_ppp_unavailable_reason_is_precise_when_zone_context_missing() -> None:
    from src.reporting.manual_short_trader_profit_plan_v1 import _planning_ppp_unavailable_reason

    card = build_profit_plan_card(
        symbol="SOL",
        market="SOL-EUR",
        current_price=Decimal("100"),
        short_context_input_status="CANONICAL_4H_CONTEXT_UNAVAILABLE",
        short_context_coverage_status="CONTEXT_INVALID_OR_STALE",
        short_context_display_state="CONTEXT_INVALID_OR_STALE",
        fib_ext=None,
        reentry=None,
        presentation_mode=CARD_MODE_POSITION_HELD,
    )
    reason = _planning_ppp_unavailable_reason(card)
    assert reason is not None
    assert "re-entry" in reason or "buy zone" in reason or "target" in reason


def test_build_json_snapshot_reports_portfolio_held_count_separately_from_card_count() -> None:
    held_card = build_profit_plan_card(
        symbol="BTC",
        market="BTC-EUR",
        current_price=Decimal("50000"),
        short_context_input_status="MISSING_ZONE_CONTEXT",
        short_context_coverage_status="CONTEXT_INVALID_OR_STALE",
        short_context_display_state="NO_NATIVE_SHORT_FIB_CONTEXT",
        presentation_mode=CARD_MODE_POSITION_HELD,
    )
    watch_card = build_profit_plan_card(
        symbol="ONDO",
        market="ONDO-EUR",
        current_price=Decimal("1"),
        short_context_input_status="MISSING_ZONE_CONTEXT",
        short_context_coverage_status="CONTEXT_INVALID_OR_STALE",
        short_context_display_state="NO_NATIVE_SHORT_FIB_CONTEXT",
        presentation_mode=CARD_MODE_MARKET_SELECTED,
    )
    snapshot = build_json_snapshot([held_card, watch_card], broker_mode="db_snapshot")
    assert snapshot["card_count"] == 2
    assert snapshot["portfolio_held_count"] == 1
    by_symbol = {row["symbol"]: row for row in snapshot["symbols"]}
    assert by_symbol["BTC"]["is_portfolio_held"] is True
    assert by_symbol["ONDO"]["is_portfolio_held"] is False
    assert "planning_ppp_unavailable_reason" in by_symbol["BTC"]
