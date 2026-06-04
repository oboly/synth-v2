from __future__ import annotations

import ast
from datetime import datetime
from pathlib import Path

from src.research.run_historical_breath_regime_context_builder_v1 import (
    SAFETY_MARKERS,
    build_context_rows,
    build_manifest,
    parse_ts,
)


def _breath_rows() -> list[dict]:
    return [
        {
            "source_name": "market_breath_outcome_validation_v1",
            "symbol": "WLD",
            "venue": "bitvavo",
            "interval": "4h",
            "asof_ts_utc": parse_ts("2026-05-01T00:00:00Z"),
            "source_event_ts_utc": parse_ts("2026-05-01T00:00:00Z"),
            "breath_phase": "RELOAD",
            "breath_alignment": "ALIGNED",
            "market_regime": "ALT_STRENGTH",
            "btc_context": "BTC_OK",
            "symbol_regime": "REL_STRENGTH",
            "fibo_context": "UNKNOWN",
            "aplus_context_state": "UNKNOWN",
            "martee_context_state": "UNKNOWN",
            "relative_strength_bucket": "STRONG",
            "momentum_bucket": "MOMENTUM_POSITIVE",
            "confidence_bucket": "HIGH",
            "source_refs": [{"source": "fixture_breath", "path": "fixture.jsonl"}],
        },
        {
            "source_name": "market_breath_outcome_validation_v1",
            "symbol": "NEAR",
            "venue": "bitvavo",
            "interval": "4h",
            "asof_ts_utc": parse_ts("2026-05-01T04:00:00Z"),
            "source_event_ts_utc": parse_ts("2026-05-01T04:00:00Z"),
            "breath_phase": "UNKNOWN",
            "breath_alignment": "UNKNOWN",
            "market_regime": "UNKNOWN",
            "btc_context": "UNKNOWN",
            "symbol_regime": "UNKNOWN",
            "fibo_context": "UNKNOWN",
            "aplus_context_state": "UNKNOWN",
            "martee_context_state": "UNKNOWN",
            "relative_strength_bucket": "UNKNOWN",
            "momentum_bucket": "UNKNOWN",
            "confidence_bucket": "UNKNOWN",
            "source_refs": [{"source": "fixture_breath", "path": "fixture.jsonl"}],
        },
    ]


def _market_wide_rows() -> list[dict]:
    return [
        {
            "symbol": "*",
            "asof_ts_utc": parse_ts("2026-05-01T00:00:00Z"),
            "market_regime": "RISK_ON",
            "btc_context": "BTC_OK",
            "breath_phase": "EXPANSION",
            "breath_alignment": "ALIGNED",
            "source_refs": [{"source": "fixture_market_wide", "path": "market.jsonl"}],
        }
    ]


def _aplus_rows() -> list[dict]:
    return [
        {
            "symbol": "WLD",
            "asof_ts_utc": parse_ts("2026-04-30T12:00:00Z"),
            "aplus_context_state": "ACCUMULATION_LEADER_CONFIRMED",
            "source_refs": [{"source": "fixture_aplus", "path": "aplus.jsonl"}],
        }
    ]


def test_builder_emits_one_row_per_symbol_time_fixture():
    rows = build_context_rows(
        breath_rows=_breath_rows(),
        aplus_rows=_aplus_rows(),
        symbols=["WLD", "NEAR"],
        venue="bitvavo",
        interval="4h",
    )
    assert len(rows) == 2
    assert [row["symbol"] for row in rows] == ["NEAR", "WLD"]


def test_missing_context_becomes_unknown():
    rows = build_context_rows(
        breath_rows=[],
        symbols=["ALGO"],
        venue="bitvavo",
        interval="4h",
        start_ts=parse_ts("2026-05-01T00:00:00Z"),
        end_ts=parse_ts("2026-05-01T00:00:00Z"),
    )
    assert len(rows) == 1
    assert rows[0]["symbol"] == "ALGO"
    assert rows[0]["breath_phase"] == "UNKNOWN"
    assert rows[0]["market_regime"] == "UNKNOWN"
    assert rows[0]["quality_state"] in {"LOW", "UNKNOWN"}


def test_symbol_specific_context_is_preserved():
    rows = build_context_rows(
        breath_rows=_breath_rows(),
        aplus_rows=_aplus_rows(),
        symbols=["WLD"],
        venue="bitvavo",
        interval="4h",
    )
    row = rows[0]
    assert row["symbol"] == "WLD"
    assert row["breath_phase"] == "RELOAD"
    assert row["market_regime"] == "ALT_STRENGTH"
    assert row["symbol_regime"] == "REL_STRENGTH"
    assert row["aplus_context_state"] == "ACCUMULATION_LEADER_CONFIRMED"


def test_market_wide_context_can_be_applied_to_symbols_with_source_refs():
    rows = build_context_rows(
        breath_rows=[],
        market_context_rows=_market_wide_rows(),
        symbols=["HYPE"],
        venue="bitvavo",
        interval="4h",
        start_ts=parse_ts("2026-05-01T00:00:00Z"),
        end_ts=parse_ts("2026-05-01T00:00:00Z"),
    )
    row = rows[0]
    assert row["market_regime"] == "RISK_ON"
    assert row["btc_context"] == "BTC_OK"
    assert any(ref["source"] == "fixture_market_wide" for ref in row["source_refs"])


def test_manifest_contains_research_only_and_safety_markers():
    rows = build_context_rows(
        breath_rows=_breath_rows(),
        symbols=["WLD"],
        venue="bitvavo",
        interval="4h",
    )
    manifest = build_manifest(rows=rows, output_dir=Path("/tmp/context"), source_paths={"market_breath_rows": "fixture"})
    assert manifest["research_only"] is True
    assert manifest["safety_markers"] == SAFETY_MARKERS


def test_no_db_writes_broker_decision_execution_imports():
    src = Path("src/research/run_historical_breath_regime_context_builder_v1.py").read_text()
    assert "commit(" not in src
    assert "place_order" not in src
    assert "cancel_order" not in src
    assert "from src.decision_gate" not in src
    assert "from src.execution_planner" not in src
    assert "from src.executor" not in src
    assert "BitvavoClient" not in src


def test_no_broker_like_ast_calls():
    src = Path("src/research/run_historical_breath_regime_context_builder_v1.py").read_text()
    tree = ast.parse(src)
    forbidden = {"place_order", "cancel_order", "create_order"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in forbidden:
            raise AssertionError(f"Forbidden broker-like call .{node.attr}() found")


def main():
    test_builder_emits_one_row_per_symbol_time_fixture()
    test_missing_context_becomes_unknown()
    test_symbol_specific_context_is_preserved()
    test_market_wide_context_can_be_applied_to_symbols_with_source_refs()
    test_manifest_contains_research_only_and_safety_markers()
    test_no_db_writes_broker_decision_execution_imports()
    test_no_broker_like_ast_calls()
    print("ok")


if __name__ == "__main__":
    main()
