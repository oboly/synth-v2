from decimal import Decimal
from types import SimpleNamespace

from src.reporting.manual_short_trader_profit_plan_v1 import (
    CARD_ACTIONABILITY_ACTIVE,
    CARD_ACTIONABILITY_CONTEXT_UNAVAILABLE,
    CARD_ACTIONABILITY_HISTORICAL_REFERENCE,
    CARD_ACTIONABILITY_INVALIDATED,
    CARD_ACTIONABILITY_NAVIGATION_ONLY,
    CARD_ACTIONABILITY_NEEDS_RECOMPUTE,
    CARD_MODE_POSITION_HELD,
    _actionability_display_bundle,
)


def _card(state: str):
    return SimpleNamespace(
        reload_reentry_zone=(Decimal("1"), Decimal("2")),
        target_exit_zone=(Decimal("3"), Decimal("4")),
        sell_zone=(Decimal("3"), Decimal("4")),
        current_price=Decimal("2.5"),
        presentation_mode=CARD_MODE_POSITION_HELD,
        actionability_state=state,
    )


def test_active_profit_plan_fib_labels_are_compact():
    labels = _actionability_display_bundle(_card(CARD_ACTIONABILITY_ACTIVE))[:2]
    assert labels == ("Re-entry", "Target")


def test_state_qualified_profit_plan_fib_labels_do_not_say_zone():
    states = (
        CARD_ACTIONABILITY_CONTEXT_UNAVAILABLE,
        CARD_ACTIONABILITY_NAVIGATION_ONLY,
        CARD_ACTIONABILITY_HISTORICAL_REFERENCE,
        CARD_ACTIONABILITY_NEEDS_RECOMPUTE,
        CARD_ACTIONABILITY_INVALIDATED,
    )
    for state in states:
        reentry_label, target_label = _actionability_display_bundle(_card(state))[:2]
        assert "zone" not in reentry_label.lower()
        assert "zone" not in target_label.lower()
