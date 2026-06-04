from __future__ import annotations

import ast
from datetime import timedelta
from pathlib import Path

from src.research.run_historical_market_breath_densifier_v1 import densify_rows


def _context_rows() -> list[dict]:
    return [
        {
            "symbol": "WLD",
            "venue": "bitvavo",
            "interval": "4h",
            "asof_ts_utc": "2026-05-01T00:00:00Z",
            "asof_ts_utc_dt": __import__("datetime").datetime(2026, 5, 1, 0, 0),
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
            "quality_state": "LOW",
            "confidence_bucket": "UNKNOWN",
            "source_refs": [{"source": "fixture_context"}],
            "research_only": True,
        }
    ]


def _event_rows() -> list[dict]:
    return [
        {"symbol": "WLD", "event_ts_utc": __import__("datetime").datetime(2026, 5, 1, 4, 0), "source_row": {}},
        {"symbol": "FET", "event_ts_utc": __import__("datetime").datetime(2026, 5, 1, 8, 0), "source_row": {}},
    ]


def _market_rows() -> list[dict]:
    return [
        {
            "source_name": "market_breath_outcome_validation_v1",
            "symbol": "WLD",
            "venue": "bitvavo",
            "interval": "4h",
            "asof_ts_utc": __import__("datetime").datetime(2026, 5, 1, 4, 0),
            "source_event_ts_utc": __import__("datetime").datetime(2026, 5, 1, 4, 0),
            "raw_row": {
                "market_breath_phase": "INHALE_ACCUMULATION",
                "market_breath_state": "CONFIRMED",
                "momentum_score": 25.0,
                "relative_strength_score": 30.0,
                "btc_alignment_score": 10.0,
                "breadth_alignment_score": 15.0,
                "market_breath_confidence": 75.0,
            },
            "market_breath_phase": "RELOAD",
            "breath_phase": "RELOAD",
            "breath_alignment": "ALIGNED",
            "market_regime": "ALT_STRENGTH",
            "btc_context": "BTC_OK",
            "symbol_regime": "REL_STRENGTH",
            "relative_strength_bucket": "STRONG",
            "momentum_bucket": "MOMENTUM_POSITIVE",
            "confidence_bucket": "HIGH",
            "source_refs": [{"source": "fixture_market"}],
        }
    ]


def test_unknown_heavy_row_gets_enriched_when_matching_source_exists():
    rows, measures = densify_rows(
        context_rows=_context_rows(),
        event_rows=_event_rows()[:1],
        market_breath_rows=_market_rows(),
        symbols={"WLD"},
        max_rows=10,
    )
    enriched = [row for row in rows if row["symbol"] == "WLD" and row["asof_ts_utc"] == "2026-05-01T04:00:00Z"][0]
    assert enriched["breath_phase"] == "RELOAD"
    assert enriched["market_regime"] == "ALT_STRENGTH"
    assert measures["enriched_rows"] >= 1


def test_row_remains_unknown_when_no_source_exists():
    context_rows = [
        {
            "symbol": "FET",
            "venue": "bitvavo",
            "interval": "4h",
            "asof_ts_utc": "2026-05-01T08:00:00Z",
            "asof_ts_utc_dt": __import__("datetime").datetime(2026, 5, 1, 8, 0),
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
            "quality_state": "LOW",
            "confidence_bucket": "UNKNOWN",
            "source_refs": [{"source": "fixture_context"}],
            "research_only": True,
        }
    ]
    rows, _ = densify_rows(
        context_rows=context_rows,
        event_rows=[_event_rows()[1]],
        market_breath_rows=[],
        symbols={"FET"},
        max_rows=10,
    )
    row = rows[0]
    assert row["symbol"] == "FET"
    assert row["breath_phase"] == "UNKNOWN"
    assert row["market_regime"] == "UNKNOWN"


def test_source_refs_are_preserved_extended():
    rows, _ = densify_rows(
        context_rows=_context_rows(),
        event_rows=_event_rows()[:1],
        market_breath_rows=_market_rows(),
        symbols={"WLD"},
        max_rows=10,
    )
    row = [row for row in rows if row["symbol"] == "WLD" and row["asof_ts_utc"] == "2026-05-01T04:00:00Z"][0]
    sources = {ref["source"] for ref in row["source_refs"]}
    assert "fixture_context" in sources or "historical_market_breath_densifier_v1" in sources
    assert "historical_market_breath_densifier_v1" in sources


def test_output_is_deterministic():
    rows1, measures1 = densify_rows(
        context_rows=_context_rows(),
        event_rows=_event_rows()[:1],
        market_breath_rows=_market_rows(),
        symbols={"WLD"},
        max_rows=10,
    )
    rows2, measures2 = densify_rows(
        context_rows=_context_rows(),
        event_rows=_event_rows()[:1],
        market_breath_rows=_market_rows(),
        symbols={"WLD"},
        max_rows=10,
    )
    assert rows1 == rows2
    assert measures1 == measures2


def test_no_db_writes_or_forbidden_imports():
    src = Path("src/research/run_historical_market_breath_densifier_v1.py").read_text()
    assert "BitvavoClient" not in src
    assert "from src.decision_gate" not in src
    assert "from src.execution_planner" not in src
    assert "from src.executor" not in src
    assert "commit(" not in src


def test_no_broker_like_ast_calls():
    src = Path("src/research/run_historical_market_breath_densifier_v1.py").read_text()
    tree = ast.parse(src)
    forbidden = {"place_order", "cancel_order", "create_order"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in forbidden:
            raise AssertionError(f"Forbidden broker-like call .{node.attr}() found")


def main():
    test_unknown_heavy_row_gets_enriched_when_matching_source_exists()
    test_row_remains_unknown_when_no_source_exists()
    test_source_refs_are_preserved_extended()
    test_output_is_deterministic()
    test_no_db_writes_or_forbidden_imports()
    test_no_broker_like_ast_calls()
    print("ok")


if __name__ == "__main__":
    main()
