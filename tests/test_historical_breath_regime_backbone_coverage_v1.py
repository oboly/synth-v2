from datetime import UTC, datetime, timedelta

import pytest

from src.research.run_historical_breath_regime_backbone_coverage_v1 import audit_coverage

BASE = datetime(2026, 6, 1, 12, tzinfo=UTC)


def _ex(symbol="BTC", asof=BASE, buyer=80.0, seller=10.0):
    return {
        "market": symbol,
        "interval": "4h",
        "asof_ts_utc": asof.isoformat(),
        "buyer_exhaustion_score": buyer,
        "seller_exhaustion_score": seller,
    }


def _ctx(symbol="BTC", asof=BASE, **overrides):
    row = {
        "symbol": symbol,
        "interval": "4h",
        "asof_ts_utc": asof.isoformat(),
        "breath_phase": "EXPANSION",
        "breath_alignment": "ALIGNED",
        "market_regime": "RISK_ON",
        "btc_context": "BTC_OK",
        "symbol_regime": "REL_STRENGTH",
    }
    row.update(overrides)
    return row


def test_exact_asof_match_counts_and_high_score_coverage():
    summary = audit_coverage([_ex()], [_ctx()], max_context_age=timedelta(hours=4))
    assert summary["matched_context_count"] == 1
    assert summary["coverage_pct"] == 100.0
    assert summary["high_score_coverage"]["buyer_70_plus_matched"] == 1
    assert summary["high_score_coverage"]["buyer_70_plus_market_regime_known"] == 1
    assert summary["field_known_count"]["market_regime"] == 1


def test_future_context_does_not_match():
    summary = audit_coverage(
        [_ex()], [_ctx(asof=BASE + timedelta(seconds=1))], max_context_age=timedelta(hours=4)
    )
    assert summary["matched_context_count"] == 0


def test_stale_context_does_not_match():
    summary = audit_coverage(
        [_ex()], [_ctx(asof=BASE - timedelta(hours=5))], max_context_age=timedelta(hours=4)
    )
    assert summary["matched_context_count"] == 0


def test_symbol_and_interval_identity_are_strict():
    bad = [_ctx(symbol="ETH"), {**_ctx(), "interval": "1h"}]
    summary = audit_coverage([_ex()], bad, max_context_age=timedelta(hours=4))
    assert summary["matched_context_count"] == 0


def test_unknown_fields_do_not_count_as_known():
    summary = audit_coverage(
        [_ex()], [_ctx(market_regime="UNKNOWN", breath_phase="UNKNOWN")], max_context_age=timedelta(hours=4)
    )
    assert summary["field_known_count"]["market_regime"] == 0
    assert summary["field_known_count"]["breath_phase"] == 0
    assert summary["field_known_count"]["btc_context"] == 1


def test_buyer_and_seller_high_score_coverage_are_separate():
    rows = [_ex("BTC", buyer=80, seller=10), _ex("ETH", buyer=10, seller=80)]
    contexts = [_ctx("BTC"), _ctx("ETH")]
    summary = audit_coverage(rows, contexts, max_context_age=timedelta(hours=4))
    assert summary["high_score_coverage"] == {
        "buyer_70_plus_total": 1,
        "buyer_70_plus_matched": 1,
        "buyer_70_plus_market_regime_known": 1,
        "seller_70_plus_total": 1,
        "seller_70_plus_matched": 1,
        "seller_70_plus_market_regime_known": 1,
    }


def test_negative_max_age_rejected():
    with pytest.raises(ValueError):
        audit_coverage([_ex()], [_ctx()], max_context_age=timedelta(seconds=-1))
