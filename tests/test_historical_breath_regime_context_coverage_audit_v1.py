from __future__ import annotations

import ast
import tempfile
from pathlib import Path

from src.research.run_historical_breath_regime_context_coverage_audit_v1 import (
    SAFETY_MARKERS,
    build_manifest,
    build_summary,
    load_required_csv,
)


def _context_rows_unknown_heavy() -> list[dict[str, str]]:
    return [
        {
            "symbol": "WLD",
            "breath_phase": "UNKNOWN",
            "breath_alignment": "UNKNOWN",
            "market_regime": "UNKNOWN",
            "btc_context": "UNKNOWN",
            "symbol_regime": "UNKNOWN",
            "fibo_context": "UNKNOWN",
            "aplus_context_state": "UNKNOWN",
            "martee_context_state": "UNKNOWN",
            "quality_state": "LOW",
            "confidence_bucket": "UNKNOWN",
        },
        {
            "symbol": "NEAR",
            "breath_phase": "UNKNOWN",
            "breath_alignment": "UNKNOWN",
            "market_regime": "UNKNOWN",
            "btc_context": "BTC_OK",
            "symbol_regime": "UNKNOWN",
            "fibo_context": "UNKNOWN",
            "aplus_context_state": "UNKNOWN",
            "martee_context_state": "UNKNOWN",
            "quality_state": "LOW",
            "confidence_bucket": "UNKNOWN",
        },
    ]


def _context_rows_enriched() -> list[dict[str, str]]:
    return [
        {
            "symbol": "WLD",
            "breath_phase": "RELOAD",
            "breath_alignment": "ALIGNED",
            "market_regime": "ALT_STRENGTH",
            "btc_context": "BTC_OK",
            "symbol_regime": "REL_STRENGTH",
            "fibo_context": "NEAR_SUPPORT",
            "aplus_context_state": "ACCUMULATION",
            "martee_context_state": "UNKNOWN",
            "quality_state": "HIGH",
            "confidence_bucket": "HIGH",
        },
        {
            "symbol": "NEAR",
            "breath_phase": "EXPANSION",
            "breath_alignment": "ALIGNED",
            "market_regime": "RISK_ON",
            "btc_context": "BTC_OK",
            "symbol_regime": "REL_STRENGTH",
            "fibo_context": "MID_RANGE",
            "aplus_context_state": "UNKNOWN",
            "martee_context_state": "UNKNOWN",
            "quality_state": "MEDIUM",
            "confidence_bucket": "MEDIUM",
        },
    ]


def _profile_rows_unknown() -> list[dict[str, str]]:
    return [
        {"symbol": "WLD", "breath_phase": "UNKNOWN", "market_regime": "UNKNOWN", "profile_label": "MIXED", "sample_quality": "LOW"},
        {"symbol": "NEAR", "breath_phase": "UNKNOWN", "market_regime": "UNKNOWN", "profile_label": "MIXED", "sample_quality": "LOW"},
    ]


def _profile_rows_enriched() -> list[dict[str, str]]:
    return [
        {"symbol": "WLD", "breath_phase": "RELOAD", "market_regime": "ALT_STRENGTH", "profile_label": "FAST_REACTOR", "sample_quality": "HIGH"},
        {"symbol": "WLD", "breath_phase": "RELOAD", "market_regime": "ALT_STRENGTH", "profile_label": "FAST_REACTOR", "sample_quality": "HIGH"},
        {"symbol": "NEAR", "breath_phase": "EXPANSION", "market_regime": "RISK_ON", "profile_label": "MIXED", "sample_quality": "MEDIUM"},
    ]


def test_unknown_heavy_fixture_is_flagged():
    _, summary = build_summary(_context_rows_unknown_heavy(), _profile_rows_unknown())
    assert summary["coverage_status"] == "UNKNOWN_HEAVY"


def test_enriched_fixture_is_flagged_as_usable():
    _, summary = build_summary(_context_rows_enriched(), _profile_rows_enriched())
    assert summary["coverage_status"] == "USABLE"


def test_per_symbol_coverage_counted_correctly():
    _, summary = build_summary(_context_rows_enriched(), _profile_rows_enriched())
    rows = {row["symbol"]: row for row in summary["per_symbol_rows"]}
    assert rows["WLD"]["context_row_count"] == 1
    assert rows["WLD"]["profile_row_count"] == 2
    assert rows["NEAR"]["profile_row_count"] == 1


def test_missing_input_file_fails_cleanly():
    with tempfile.TemporaryDirectory() as tmpdir:
        missing = Path(tmpdir) / "missing.csv"
        try:
            load_required_csv(missing, label="context rows")
        except FileNotFoundError as exc:
            assert "Missing context rows file" in str(exc)
        else:
            raise AssertionError("Expected FileNotFoundError")


def test_no_broker_decision_execution_imports():
    src = Path("src/research/run_historical_breath_regime_context_coverage_audit_v1.py").read_text()
    assert "BitvavoClient" not in src
    assert "from src.decision_gate" not in src
    assert "from src.execution_planner" not in src
    assert "from src.executor" not in src
    assert "place_order" not in src
    assert "cancel_order" not in src


def test_manifest_contains_safety_markers():
    _, summary = build_summary(_context_rows_enriched(), _profile_rows_enriched())
    manifest = build_manifest(
        context_rows_path=Path("context.csv"),
        profile_rows_path=Path("profile.csv"),
        output_dir=Path("/tmp/out"),
        summary=summary,
    )
    assert manifest["research_only"] is True
    assert manifest["safety_markers"] == SAFETY_MARKERS


def test_no_broker_like_ast_calls():
    src = Path("src/research/run_historical_breath_regime_context_coverage_audit_v1.py").read_text()
    tree = ast.parse(src)
    forbidden = {"place_order", "cancel_order", "create_order"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in forbidden:
            raise AssertionError(f"Forbidden broker-like call .{node.attr}() found")


def main():
    test_unknown_heavy_fixture_is_flagged()
    test_enriched_fixture_is_flagged_as_usable()
    test_per_symbol_coverage_counted_correctly()
    test_missing_input_file_fails_cleanly()
    test_no_broker_decision_execution_imports()
    test_manifest_contains_safety_markers()
    test_no_broker_like_ast_calls()
    print("ok")


if __name__ == "__main__":
    main()
