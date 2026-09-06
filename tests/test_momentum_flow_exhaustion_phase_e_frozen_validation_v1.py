from __future__ import annotations

import pytest

from src.research.run_momentum_flow_exhaustion_phase_e_frozen_validation_v1 import (
    DISCOVERY_REFERENCE,
    HYPOTHESES,
    build_report,
    enrich_exact_context,
    evaluate_hypothesis,
    frozen_discovery_reference,
)


def replay(side: str, score: float, ts: str, value: float) -> dict[str, object]:
    return {
        "market": "BTC",
        "interval": "4h",
        "asof_ts_utc": ts,
        f"{side.lower()}_exhaustion_score": score,
        f"{side.lower()}_reversal_return_1b_pct": value,
        f"{side.lower()}_reversal_return_3b_pct": value,
        f"{side.lower()}_reversal_return_6b_pct": value,
    }


def context(ts: str, regime: str) -> dict[str, object]:
    return {
        "symbol": "BTC",
        "interval": "4h",
        "asof_ts_utc": ts,
        "market_regime": regime,
    }


def test_discovery_reference_is_frozen_and_not_recomputed() -> None:
    frozen = frozen_discovery_reference()
    assert frozen["contaminated_for_holdout"] is True
    assert frozen["hypotheses"][0]["sample_count"] == 36
    assert frozen["hypotheses"][1]["sample_count"] == 13
    assert DISCOVERY_REFERENCE["SELLER_70_RISK_OFF_CONTINUATION"]["avg_reversal_return_6b_pct"] == -3.484848


def test_exact_context_join_is_fail_closed() -> None:
    rows = [replay("BUYER", 80, "2025-06-01T00:00:00+00:00", 1.0)]
    enriched = enrich_exact_context(rows, [])
    assert enriched[0]["market_regime"] == "UNKNOWN"
    assert enriched[0]["context_exact_match"] is False


def test_duplicate_context_identity_rejected() -> None:
    ts = "2025-06-01T00:00:00+00:00"
    rows = [replay("BUYER", 80, ts, 1.0)]
    with pytest.raises(ValueError, match="duplicate context identity"):
        enrich_exact_context(rows, [context(ts, "ALT_STRENGTH"), context(ts, "ALT_STRENGTH")])


def test_supported_pre_discovery_hypothesis() -> None:
    h = HYPOTHESES[0]
    rows = []
    for index in range(h.minimum_sample):
        row = replay("BUYER", 80, f"2025-06-{index + 1:02d}T00:00:00+00:00", 1.0)
        row["market_regime"] = "ALT_STRENGTH"
        rows.append(row)
    result = evaluate_hypothesis(rows, h, "PRE_DISCOVERY")
    assert result["status"] == "ROBUSTNESS_SUPPORTED"


def test_insufficient_forward_sample_is_not_failure() -> None:
    h = HYPOTHESES[1]
    rows = []
    for index in range(h.minimum_sample - 1):
        row = replay("SELLER", 80, f"2026-09-{index + 1:02d}T00:00:00+00:00", -1.0)
        row["market_regime"] = "RISK_OFF"
        rows.append(row)
    result = evaluate_hypothesis(rows, h, "FORWARD_HOLDOUT")
    assert result["status"] == "INSUFFICIENT_SAMPLE"


def test_build_report_rejects_pre_discovery_overlap() -> None:
    pre_ts = "2025-09-04T04:00:00+00:00"
    fwd_ts = "2026-09-01T00:00:00+00:00"
    with pytest.raises(ValueError, match="overlaps frozen discovery"):
        build_report(
            ([replay("BUYER", 80, pre_ts, 1.0)], [context(pre_ts, "ALT_STRENGTH")]),
            ([replay("BUYER", 80, fwd_ts, 1.0)], [context(fwd_ts, "ALT_STRENGTH")]),
        )


def test_build_report_rejects_forward_contamination() -> None:
    pre_ts = "2025-08-01T00:00:00+00:00"
    bad_fwd = "2026-08-31T20:00:00+00:00"
    with pytest.raises(ValueError, match="pre-2026-09-01"):
        build_report(
            ([replay("BUYER", 80, pre_ts, 1.0)], [context(pre_ts, "ALT_STRENGTH")]),
            ([replay("BUYER", 80, bad_fwd, 1.0)], [context(bad_fwd, "ALT_STRENGTH")]),
        )
