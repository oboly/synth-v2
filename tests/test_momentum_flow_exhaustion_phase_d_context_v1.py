from datetime import UTC, datetime, timedelta

import pytest

from src.research.run_momentum_flow_exhaustion_phase_d_context_v1 import (
    REGIME_HORIZON_HOURS,
    REGIME_REPORT_NAME,
    REGIME_REPORT_VERSION,
    REGIME_SELECTOR_MODE,
    UNKNOWN,
    build_interaction_summary,
    enrich_with_regime_context,
)

BASE = datetime(2026, 4, 1, 12, tzinfo=UTC)


def _exhaustion(asof=BASE, market="BTC"):
    return {"market": market, "interval": "4h", "asof_ts_utc": asof.isoformat(),
            "buyer_exhaustion_score": 80.0, "seller_exhaustion_score": 10.0,
            "buyer_reversal_return_1b_pct": 0.2, "buyer_reversal_return_3b_pct": 0.4,
            "buyer_reversal_return_6b_pct": 0.6, "seller_reversal_return_1b_pct": -0.2,
            "seller_reversal_return_3b_pct": -0.4, "seller_reversal_return_6b_pct": -0.6}


def _regime(ts, regime="RISK_ON", symbol="BTC"):
    return {"symbol": symbol, "interval_code": "4h", "asof_ts_utc": ts,
            "global_regime": regime, "asset_class_regime": "ALT_STRENGTH",
            "global_class_regime": "MIXED", "asset_class": "CRYPTO"}


def test_latest_context_at_or_before_asof_is_used():
    rows = enrich_with_regime_context([_exhaustion()], [_regime(BASE-timedelta(hours=3), "OLD"), _regime(BASE-timedelta(hours=1), "NEW")])
    assert rows[0]["global_regime"] == "NEW"
    assert rows[0]["context_age_seconds"] == 3600


def test_future_context_never_leaks():
    rows = enrich_with_regime_context([_exhaustion()], [_regime(BASE+timedelta(seconds=1), "FUTURE")])
    assert rows[0]["context_state"] == UNKNOWN
    assert rows[0]["global_regime"] == UNKNOWN


def test_stale_context_fails_to_unknown():
    rows = enrich_with_regime_context([_exhaustion()], [_regime(BASE-timedelta(hours=5), "STALE")], max_context_age=timedelta(hours=4))
    assert rows[0]["context_state"] == UNKNOWN


def test_symbol_and_interval_identity_are_required():
    regimes = [_regime(BASE-timedelta(hours=1), symbol="ETH"), {**_regime(BASE-timedelta(hours=1)), "interval_code": "1h"}]
    rows = enrich_with_regime_context([_exhaustion()], regimes)
    assert rows[0]["context_state"] == UNKNOWN


def test_summary_keeps_buyer_and_seller_separate():
    buyer = _exhaustion(); buyer["global_regime"]="RISK_ON"; buyer["context_state"]="KNOWN"
    seller = _exhaustion(market="ETH"); seller["buyer_exhaustion_score"]=10; seller["seller_exhaustion_score"]=80
    seller["global_regime"]="RISK_OFF"; seller["context_state"]="KNOWN"; seller["seller_reversal_return_6b_pct"]=1.25
    s=build_interaction_summary([buyer,seller])
    assert s["by_side_and_global_regime_70_plus"]["BUYER"]["RISK_ON"]["count"] == 1
    assert s["by_side_and_global_regime_70_plus"]["SELLER"]["RISK_OFF"]["avg_reversal_return_6b_pct"] == 1.25


def test_negative_max_age_is_rejected():
    with pytest.raises(ValueError):
        enrich_with_regime_context([_exhaustion()], [], max_context_age=timedelta(seconds=-1))


def test_regime_source_identity_is_explicit_and_single_lane():
    assert REGIME_REPORT_NAME == "regime_selector_backtest_v1"
    assert REGIME_REPORT_VERSION == "1.1"
    assert REGIME_SELECTOR_MODE == "GLOBAL"
    assert REGIME_HORIZON_HOURS == 4


def test_duplicate_timestamp_rows_have_deterministic_last_row_precedence():
    first = _regime(BASE-timedelta(hours=1), "FIRST")
    second = _regime(BASE-timedelta(hours=1), "SECOND")
    rows = enrich_with_regime_context([_exhaustion()], [first, second])
    assert rows[0]["global_regime"] == "SECOND"
