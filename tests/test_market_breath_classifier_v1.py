from __future__ import annotations

import ast
from pathlib import Path

from src.research.market_breath_classifier_v1 import (
    DEFAULT_MARKET_BREATH_THRESHOLD_PROFILE_V1,
    MarketBreathThresholdProfileV1,
    classify_market_breath_phase_state_v1,
)
from src.research.run_market_breath_analysis_v1 import (
    Asset,
    build_base_observation,
    build_summary,
    parse_ts,
)


MODULE_PATH = Path("src/research/market_breath_classifier_v1.py")
RUNNER_PATH = Path("src/research/run_market_breath_analysis_v1.py")


def test_default_profile_matches_prior_baseline_cases_for_each_branch():
    cases = [
        (
            dict(compression=10.0, expansion=10.0, momentum=-30.0, reversal_pressure=45.0, relative_strength=-5.0),
            ("COLLAPSE_RESET", "RESET"),
        ),
        (
            dict(compression=0.0, expansion=70.0, momentum=60.0, reversal_pressure=50.0, relative_strength=10.0),
            ("OVERBREATH_EXTENSION", "LATE"),
        ),
        (
            dict(compression=0.0, expansion=70.0, momentum=40.0, reversal_pressure=0.0, relative_strength=5.0),
            ("EXHALE_EXPANSION", "CONFIRMED"),
        ),
        (
            dict(compression=0.0, expansion=56.0, momentum=21.0, reversal_pressure=0.0, relative_strength=5.0),
            ("EXHALE_EXPANSION", "FORMING"),
        ),
        (
            dict(compression=80.0, expansion=10.0, momentum=5.0, reversal_pressure=0.0, relative_strength=0.0),
            ("HOLD_COMPRESSION", "CONFIRMED"),
        ),
        (
            dict(compression=65.0, expansion=10.0, momentum=15.0, reversal_pressure=0.0, relative_strength=0.0),
            ("HOLD_COMPRESSION", "FORMING"),
        ),
        (
            dict(compression=50.0, expansion=20.0, momentum=25.0, reversal_pressure=0.0, relative_strength=10.0),
            ("INHALE_ACCUMULATION", "CONFIRMED"),
        ),
        (
            dict(compression=50.0, expansion=20.0, momentum=10.0, reversal_pressure=0.0, relative_strength=10.0),
            ("INHALE_ACCUMULATION", "FORMING"),
        ),
        (
            dict(compression=20.0, expansion=20.0, momentum=0.0, reversal_pressure=0.0, relative_strength=0.0),
            ("NEUTRAL_TRANSITION", "UNKNOWN"),
        ),
    ]
    for features, expected in cases:
        assert classify_market_breath_phase_state_v1(**features) == expected


def test_collapse_boundary_behavior():
    assert classify_market_breath_phase_state_v1(
        compression=0.0,
        expansion=0.0,
        momentum=-25.0,
        reversal_pressure=45.0,
        relative_strength=0.0,
    ) == ("NEUTRAL_TRANSITION", "UNKNOWN")
    assert classify_market_breath_phase_state_v1(
        compression=0.0,
        expansion=0.0,
        momentum=-25.1,
        reversal_pressure=45.0,
        relative_strength=0.0,
    ) == ("COLLAPSE_RESET", "RESET")
    assert classify_market_breath_phase_state_v1(
        compression=0.0,
        expansion=0.0,
        momentum=-30.0,
        reversal_pressure=44.999,
        relative_strength=0.0,
    ) == ("NEUTRAL_TRANSITION", "UNKNOWN")


def test_overbreath_exact_and_just_below_boundaries():
    assert classify_market_breath_phase_state_v1(
        compression=0.0,
        expansion=65.0,
        momentum=55.0,
        reversal_pressure=45.0,
        relative_strength=10.0,
    ) == ("OVERBREATH_EXTENSION", "LATE")
    assert classify_market_breath_phase_state_v1(
        compression=0.0,
        expansion=64.999,
        momentum=55.0,
        reversal_pressure=45.0,
        relative_strength=10.0,
    ) != ("OVERBREATH_EXTENSION", "LATE")
    assert classify_market_breath_phase_state_v1(
        compression=0.0,
        expansion=65.0,
        momentum=54.999,
        reversal_pressure=45.0,
        relative_strength=10.0,
    ) != ("OVERBREATH_EXTENSION", "LATE")
    assert classify_market_breath_phase_state_v1(
        compression=0.0,
        expansion=65.0,
        momentum=55.0,
        reversal_pressure=44.999,
        relative_strength=10.0,
    ) != ("OVERBREATH_EXTENSION", "LATE")


def test_expansion_exact_and_strict_boundaries():
    assert classify_market_breath_phase_state_v1(
        compression=0.0,
        expansion=55.0,
        momentum=21.0,
        reversal_pressure=0.0,
        relative_strength=0.1,
    ) == ("EXHALE_EXPANSION", "FORMING")
    assert classify_market_breath_phase_state_v1(
        compression=0.0,
        expansion=55.0,
        momentum=20.0,
        reversal_pressure=0.0,
        relative_strength=10.0,
    ) == ("NEUTRAL_TRANSITION", "UNKNOWN")
    assert classify_market_breath_phase_state_v1(
        compression=0.0,
        expansion=55.0,
        momentum=21.0,
        reversal_pressure=0.0,
        relative_strength=0.0,
    ) == ("NEUTRAL_TRANSITION", "UNKNOWN")
    assert classify_market_breath_phase_state_v1(
        compression=0.0,
        expansion=70.0,
        momentum=35.0,
        reversal_pressure=0.0,
        relative_strength=0.1,
    ) == ("EXHALE_EXPANSION", "CONFIRMED")


def test_compression_exact_and_strict_boundaries():
    assert classify_market_breath_phase_state_v1(
        compression=60.0,
        expansion=34.999,
        momentum=20.0,
        reversal_pressure=0.0,
        relative_strength=0.0,
    ) == ("HOLD_COMPRESSION", "FORMING")
    assert classify_market_breath_phase_state_v1(
        compression=75.0,
        expansion=34.999,
        momentum=-20.0,
        reversal_pressure=0.0,
        relative_strength=0.0,
    ) == ("HOLD_COMPRESSION", "CONFIRMED")
    assert classify_market_breath_phase_state_v1(
        compression=75.0,
        expansion=34.999,
        momentum=-20.001,
        reversal_pressure=0.0,
        relative_strength=0.0,
    ) == ("NEUTRAL_TRANSITION", "UNKNOWN")
    assert classify_market_breath_phase_state_v1(
        compression=60.0,
        expansion=35.0,
        momentum=20.0,
        reversal_pressure=0.0,
        relative_strength=0.0,
    ) == ("NEUTRAL_TRANSITION", "UNKNOWN")


def test_accumulation_exact_and_strict_boundaries():
    assert classify_market_breath_phase_state_v1(
        compression=45.0,
        expansion=20.0,
        momentum=5.0,
        reversal_pressure=0.0,
        relative_strength=0.1,
    ) == ("INHALE_ACCUMULATION", "FORMING")
    assert classify_market_breath_phase_state_v1(
        compression=45.0,
        expansion=20.0,
        momentum=20.0,
        reversal_pressure=0.0,
        relative_strength=0.1,
    ) == ("INHALE_ACCUMULATION", "CONFIRMED")
    assert classify_market_breath_phase_state_v1(
        compression=45.0,
        expansion=20.0,
        momentum=35.0,
        reversal_pressure=0.0,
        relative_strength=0.1,
    ) == ("INHALE_ACCUMULATION", "CONFIRMED")
    assert classify_market_breath_phase_state_v1(
        compression=45.0,
        expansion=20.0,
        momentum=35.001,
        reversal_pressure=0.0,
        relative_strength=0.1,
    ) == ("NEUTRAL_TRANSITION", "UNKNOWN")
    assert classify_market_breath_phase_state_v1(
        compression=45.0,
        expansion=20.0,
        momentum=20.0,
        reversal_pressure=0.0,
        relative_strength=0.0,
    ) == ("NEUTRAL_TRANSITION", "UNKNOWN")


def test_neutral_near_threshold_fallthrough_cases():
    assert classify_market_breath_phase_state_v1(
        compression=44.999,
        expansion=20.0,
        momentum=5.0,
        reversal_pressure=0.0,
        relative_strength=10.0,
    ) == ("NEUTRAL_TRANSITION", "UNKNOWN")
    assert classify_market_breath_phase_state_v1(
        compression=0.0,
        expansion=54.999,
        momentum=21.0,
        reversal_pressure=0.0,
        relative_strength=10.0,
    ) == ("NEUTRAL_TRANSITION", "UNKNOWN")


def test_overlap_precedence_prefers_earlier_phase_rules():
    assert classify_market_breath_phase_state_v1(
        compression=70.0,
        expansion=20.0,
        momentum=10.0,
        reversal_pressure=0.0,
        relative_strength=10.0,
    ) == ("HOLD_COMPRESSION", "FORMING")
    assert classify_market_breath_phase_state_v1(
        compression=80.0,
        expansion=70.0,
        momentum=60.0,
        reversal_pressure=50.0,
        relative_strength=10.0,
    ) == ("OVERBREATH_EXTENSION", "LATE")


def test_custom_profile_changes_thresholds_without_changing_precedence():
    profile = MarketBreathThresholdProfileV1(exhale_momentum_gt=25.0)
    baseline = classify_market_breath_phase_state_v1(
        compression=0.0,
        expansion=56.0,
        momentum=21.0,
        reversal_pressure=0.0,
        relative_strength=5.0,
    )
    custom = classify_market_breath_phase_state_v1(
        compression=0.0,
        expansion=56.0,
        momentum=21.0,
        reversal_pressure=0.0,
        relative_strength=5.0,
        profile=profile,
    )
    assert baseline == ("EXHALE_EXPANSION", "FORMING")
    assert custom == ("NEUTRAL_TRANSITION", "UNKNOWN")


def test_default_profile_object_matches_baseline_constant_values():
    assert DEFAULT_MARKET_BREATH_THRESHOLD_PROFILE_V1 == MarketBreathThresholdProfileV1()


def test_runner_uses_shared_classifier_helper():
    src = RUNNER_PATH.read_text(encoding="utf-8")
    assert "classify_market_breath_phase_state_v1(" in src
    assert "DEFAULT_MARKET_BREATH_THRESHOLD_PROFILE_V1" in src


def test_no_forbidden_runtime_imports():
    imports: list[str] = []
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    joined = "\n".join(imports)
    assert "decision_gate" not in joined
    assert "execution_planner" not in joined
    assert "executor" not in joined
    assert "broker" not in joined


def test_runner_insufficient_data_and_historical_state_keys_are_preserved():
    row = build_base_observation(
        asset=Asset(asset_id=1, symbol="WLD"),
        candles=[],
        venue="bitvavo",
        interval_code="4h",
        lookback_candles=120,
        asof_ts=parse_ts("2026-05-01T00:00:00Z"),
        btc_r6=None,
        btc_r12=None,
    )
    assert row["market_breath_phase"] == "INSUFFICIENT_DATA"
    assert row["market_breath_state"] == "UNKNOWN"

    summary = build_summary(
        [row],
        venue="bitvavo",
        interval_code="4h",
        asof_ts=parse_ts("2026-05-01T00:00:00Z"),
        output_paths={},
        wrote_files=False,
    )
    assert set(summary["state_counts"].keys()) == {
        "EARLY",
        "FORMING",
        "CONFIRMED",
        "LATE",
        "RESET",
        "UNKNOWN",
    }
    assert summary["state_counts"]["EARLY"] == 0
    assert summary["state_counts"]["UNKNOWN"] == 1
