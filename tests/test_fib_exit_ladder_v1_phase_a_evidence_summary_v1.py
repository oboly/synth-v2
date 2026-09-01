"""Regression test for the tracked #270 Phase A evidence summary.

Loads docs/research/fib_exit_ladder_v1_phase_a_evidence_summary_v1.json and
feeds its stored, already-derived inputs into the unmodified production
disposition helpers in
src/research/fib_exit_ladder_v1_phase_a_disposition_v1.py, so that a future
edit to that JSON which would silently change the reported #270 Phase A
disposition is caught here. Does not duplicate the disposition logic itself
and does not require DB access.
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from src.research import fib_exit_ladder_v1_phase_a_disposition_v1 as disposition

REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_PATH = (
    REPO_ROOT
    / "docs/research/fib_exit_ladder_v1_phase_a_evidence_summary_v1.json"
)

EXPECTED_ASSET_OUTCOMES = {
    "LINK": disposition.OUTCOME_REVISED,
    "XLM": disposition.OUTCOME_REVISED,
    "SOL": disposition.OUTCOME_REVISED,
    "XRP": disposition.OUTCOME_REVISED,
    "HOT": disposition.OUTCOME_REJECTED,
}


def _load_evidence() -> dict:
    return json.loads(EVIDENCE_PATH.read_text())


def test_evidence_summary_covers_exactly_the_frozen_five_asset_universe():
    evidence = _load_evidence()
    assert set(evidence["assets"].keys()) == set(
        disposition.REQUIRED_ASSET_UNIVERSE
    )
    assert set(evidence["assets"].keys()) == set(EXPECTED_ASSET_OUTCOMES)


def test_evidence_summary_asset_configs_match_original_asset_config():
    evidence = _load_evidence()
    for symbol, asset in evidence["assets"].items():
        expected = disposition.original_config_for_asset(symbol)
        assert asset["target_family"] == expected.target_family
        assert Decimal(asset["max_ladder_sell_fraction"]) == expected.max_ladder_sell_fraction


def test_evidence_summary_reproduces_expected_per_asset_disposition():
    evidence = _load_evidence()
    computed = {}
    for symbol, expected_outcome in EXPECTED_ASSET_OUTCOMES.items():
        asset = evidence["assets"][symbol]
        result = disposition.classify_asset_disposition(
            symbol=symbol,
            baseline_evaluable=asset["baseline_evaluable"],
            baseline_reproduced=asset["baseline_reproduced"],
            has_original_bucket=True,
            validation_windows_ok=asset["validation_windows_ok"],
            validation_windows_total=2,
            alpha_positive_ok_window_count=asset["alpha_positive_ok_window_count"],
            bucket_sign_agreement=asset["bucket_sign_agreement"],
            bucket_rank_agreement_all_ok_windows=asset["bucket_rank_agreement_all_ok_windows"],
        )
        assert result.outcome == expected_outcome, symbol
        # The evidence file's own recorded reason must match what the
        # unmodified helper actually returns for these inputs, so a stale or
        # hand-edited "reason" field cannot silently drift from the real
        # disposition logic.
        assert result.reason == asset["reason"], symbol
        computed[symbol] = result


def test_evidence_summary_hot_rejected_reason_is_not_baseline_reproduction_failure():
    evidence = _load_evidence()
    hot = evidence["assets"]["HOT"]
    assert hot["baseline_reproduced"] is True
    # HOT's REJECTED verdict comes from the ladder never beating hold in
    # either post-2022 validation window, not from a failed baseline
    # reproduction — the evidence's stored reason must reflect that.
    assert hot["reason"] != disposition.REASON_BASELINE_REPRODUCTION_FAILED
    assert hot["reason"] is None


def test_evidence_summary_overall_disposition_is_rejected():
    evidence = _load_evidence()
    dispositions = [
        disposition.classify_asset_disposition(
            symbol=symbol,
            baseline_evaluable=asset["baseline_evaluable"],
            baseline_reproduced=asset["baseline_reproduced"],
            has_original_bucket=True,
            validation_windows_ok=asset["validation_windows_ok"],
            validation_windows_total=2,
            alpha_positive_ok_window_count=asset["alpha_positive_ok_window_count"],
            bucket_sign_agreement=asset["bucket_sign_agreement"],
            bucket_rank_agreement_all_ok_windows=asset["bucket_rank_agreement_all_ok_windows"],
        )
        for symbol, asset in evidence["assets"].items()
    ]
    overall = disposition.overall_disposition(dispositions)
    assert overall == disposition.OUTCOME_REJECTED
    assert overall == evidence["overall_disposition"]


def test_evidence_summary_methodology_markers():
    evidence = _load_evidence()
    assert evidence["methodology_classification"] == disposition.METHODOLOGY_CLASSIFICATION
    assert evidence["methodology_promotion_grade"] == 0
    assert evidence["promotion_eligible"] is False
    assert (
        disposition.is_promotion_eligible(disposition_outcome=evidence["overall_disposition"])
        is False
    )
