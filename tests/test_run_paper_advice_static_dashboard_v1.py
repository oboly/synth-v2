from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from src.market_data.market_price_snapshot_v1 import MarketPriceSnapshot
from src.reporting.run_paper_advice_static_dashboard_v1 import (
    _target_distance_text,
    apply_current_price_snapshot,
    render_table,
)


def _now() -> datetime:
    return datetime(2026, 6, 5, 12, 0, tzinfo=UTC)


def test_stale_home_price_blocks_delta_and_actionable_display() -> None:
    now = _now()
    row = {
        "symbol": "HOME",
        "advice_state": "WATCH",
        "advice_action": "BUY_REVIEW",
        "risk_label": "MODERATE",
        "leg_direction": "UP",
        "entry_zone_low": Decimal("1.00"),
        "entry_zone_high": Decimal("1.10"),
        "tp_zone_low": Decimal("1.69"),
        "tp_zone_high": Decimal("1.69"),
        "invalidation_price": Decimal("0.95"),
        "selection_state": "ACTIVE",
        "setup_filter_state": "PASS",
        "policy_decision": "ALLOW",
        "confidence_score": Decimal("0.40"),
        "priority_rank": 1,
        "asof_ts_utc": now.replace(tzinfo=None),
    }
    stale_snapshot = MarketPriceSnapshot(
        venue="bitvavo",
        symbol="HOME",
        market="HOME-EUR",
        quote_currency="EUR",
        price=Decimal("1.30"),
        source_name="market_price_snapshot_v1",
        source_ts_utc=(now - timedelta(days=2)).replace(tzinfo=None),
        observed_ts_utc=(now - timedelta(days=2)).replace(tzinfo=None),
    )
    apply_current_price_snapshot(row, stale_snapshot, now_utc=now)
    assert row["current_price_status"] == "STALE_CURRENT_PRICE"
    assert row["current_price"] is None
    assert _target_distance_text(Decimal("1.69"), row["current_price"]) == ""

    html = render_table([row])
    assert "STALE_CURRENT_PRICE" in html
    assert "price-based action review blocked" in html
    assert "+30.0%" not in html


def main() -> None:
    test_stale_home_price_blocks_delta_and_actionable_display()
    print("ok")


if __name__ == "__main__":
    main()
