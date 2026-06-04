from __future__ import annotations

import ast
from pathlib import Path

from src.research.run_symbol_reaction_profile_by_context_v1 import (
    SAFETY_MARKERS,
    build_manifest,
    build_profile_rows,
    parse_ts,
)


def _context_rows() -> list[dict]:
    return [
        {
            "symbol": "WLD",
            "asof_ts_utc": parse_ts("2026-05-01T00:00:00Z"),
            "breath_phase": "RELOAD",
            "breath_alignment": "ALIGNED",
            "market_regime": "ALT_STRENGTH",
            "btc_context": "BTC_OK",
            "symbol_regime": "REL_STRENGTH",
            "fibo_context": "NEAR_SUPPORT",
            "source_refs": [{"source": "fixture_context"}],
        },
        {
            "symbol": "WLD",
            "asof_ts_utc": parse_ts("2026-05-02T00:00:00Z"),
            "breath_phase": "RELOAD",
            "breath_alignment": "ALIGNED",
            "market_regime": "BTC_DAMAGE",
            "btc_context": "BTC_DAMAGE_HARD",
            "symbol_regime": "LAGGARD",
            "fibo_context": "NEAR_SUPPORT",
            "source_refs": [{"source": "fixture_context"}],
        },
        {
            "symbol": "FET",
            "asof_ts_utc": parse_ts("2026-05-01T00:00:00Z"),
            "breath_phase": "RELOAD",
            "breath_alignment": "EARLY",
            "market_regime": "MIXED",
            "btc_context": "BTC_OK",
            "symbol_regime": "REL_STRENGTH",
            "fibo_context": "MID_RANGE",
            "source_refs": [{"source": "fixture_context"}],
        },
        {
            "symbol": "XLM",
            "asof_ts_utc": parse_ts("2026-05-01T00:00:00Z"),
            "breath_phase": "EXPANSION",
            "breath_alignment": "LATE",
            "market_regime": "MIXED",
            "btc_context": "BTC_OK",
            "symbol_regime": "LOW_BETA",
            "fibo_context": "MID_RANGE",
            "source_refs": [{"source": "fixture_context"}],
        },
    ]


def _event(symbol: str, ts: str, current_price: float, entry_low: float, entry_high: float, returns: dict[str, float], *, mfe: float, mae: float, broke: bool = False, hit: bool = True) -> dict:
    return {
        "symbol": symbol,
        "event_ts_utc": parse_ts(ts),
        "current_price": current_price,
        "entry_zone_low": entry_low,
        "entry_zone_high": entry_high,
        "forward_returns": returns,
        "max_favorable_excursion_pct": mfe,
        "max_adverse_excursion_pct": mae,
        "broke_invalidation_like_move": broke,
        "hit_target_like_move": hit,
    }


def test_fast_reactor_classification():
    events = [
        _event("WLD", "2026-05-01T04:00:00Z", 10.1, 10.0, 10.2, {"15m": 1.0, "30m": 1.5, "1h": 2.0, "4h": 3.0, "24h": 4.0}, mfe=5.0, mae=-2.0),
        _event("WLD", "2026-05-01T08:00:00Z", 10.15, 10.0, 10.2, {"15m": 1.0, "30m": 1.2, "1h": 2.1, "4h": 2.8, "24h": 3.5}, mfe=4.8, mae=-2.0),
        _event("WLD", "2026-05-01T12:00:00Z", 10.18, 10.0, 10.2, {"15m": 0.8, "30m": 1.0, "1h": 1.5, "4h": 2.4, "24h": 3.2}, mfe=4.2, mae=-2.1),
        _event("WLD", "2026-05-01T16:00:00Z", 10.12, 10.0, 10.2, {"15m": 0.9, "30m": 1.3, "1h": 1.8, "4h": 2.6, "24h": 3.1}, mfe=4.4, mae=-2.0),
        _event("WLD", "2026-05-01T20:00:00Z", 10.05, 10.0, 10.2, {"15m": 1.1, "30m": 1.4, "1h": 1.9, "4h": 2.7, "24h": 3.0}, mfe=4.6, mae=-2.2),
    ]
    rows = build_profile_rows(event_rows=events, context_rows=_context_rows(), fibo_by_symbol={}, min_events=5)
    assert len(rows) == 1
    assert rows[0]["profile_label"] == "FAST_REACTOR"


def test_btc_damage_classifies_fakeout_prone():
    events = [
        _event("WLD", "2026-05-02T04:00:00Z", 9.8, 9.5, 9.9, {"15m": -0.5, "30m": 0.2, "1h": 0.1, "4h": 0.0, "24h": -1.0}, mfe=1.2, mae=-3.0, broke=True),
        _event("WLD", "2026-05-02T08:00:00Z", 9.7, 9.5, 9.9, {"15m": -0.3, "30m": 0.1, "1h": -0.2, "4h": -0.5, "24h": -1.5}, mfe=1.0, mae=-3.5, broke=True),
        _event("WLD", "2026-05-02T12:00:00Z", 9.75, 9.5, 9.9, {"15m": -0.2, "30m": 0.2, "1h": 0.0, "4h": -0.4, "24h": -1.1}, mfe=1.1, mae=-3.2, broke=True),
        _event("WLD", "2026-05-02T16:00:00Z", 9.72, 9.5, 9.9, {"15m": -0.4, "30m": -0.1, "1h": -0.2, "4h": -0.3, "24h": -1.2}, mfe=0.9, mae=-3.4, broke=False),
        _event("WLD", "2026-05-02T20:00:00Z", 9.74, 9.5, 9.9, {"15m": -0.1, "30m": 0.0, "1h": -0.1, "4h": -0.2, "24h": -1.0}, mfe=0.8, mae=-3.1, broke=True),
    ]
    rows = build_profile_rows(event_rows=events, context_rows=_context_rows(), fibo_by_symbol={}, min_events=5)
    assert rows[0]["profile_label"] == "FAKEOUT_PRONE"


def test_deep_retracer_classification():
    events = [
        _event("FET", "2026-05-01T04:00:00Z", 10.0, 9.0, 9.4, {"15m": 0.1, "30m": 0.5, "1h": 0.9, "4h": 1.2, "24h": 2.0}, mfe=4.0, mae=-2.0),
        _event("FET", "2026-05-01T08:00:00Z", 10.0, 9.1, 9.4, {"15m": 0.2, "30m": 0.5, "1h": 0.8, "4h": 1.1, "24h": 2.1}, mfe=4.1, mae=-2.1),
        _event("FET", "2026-05-01T12:00:00Z", 10.0, 9.0, 9.3, {"15m": 0.0, "30m": 0.4, "1h": 0.7, "4h": 1.0, "24h": 2.2}, mfe=4.2, mae=-2.2),
        _event("FET", "2026-05-01T16:00:00Z", 10.0, 9.2, 9.4, {"15m": 0.1, "30m": 0.3, "1h": 0.8, "4h": 1.0, "24h": 2.0}, mfe=4.0, mae=-2.0),
        _event("FET", "2026-05-01T20:00:00Z", 10.0, 9.1, 9.4, {"15m": 0.2, "30m": 0.4, "1h": 0.9, "4h": 1.1, "24h": 2.3}, mfe=4.3, mae=-2.2),
    ]
    rows = build_profile_rows(event_rows=events, context_rows=_context_rows(), fibo_by_symbol={}, min_events=5)
    assert rows[0]["profile_label"] == "DEEP_RETRACER"


def test_fakeout_fixture_classifies_fakeout_prone():
    events = [
        _event("XLM", "2026-05-01T04:00:00Z", 4.0, 3.95, 4.05, {"15m": -0.2, "30m": -0.1, "1h": -0.3, "4h": -0.1, "24h": 0.0}, mfe=0.4, mae=-1.5, broke=True),
        _event("XLM", "2026-05-01T08:00:00Z", 4.0, 3.95, 4.05, {"15m": -0.1, "30m": -0.2, "1h": -0.2, "4h": 0.0, "24h": 0.1}, mfe=0.5, mae=-1.4, broke=True),
        _event("XLM", "2026-05-01T12:00:00Z", 4.0, 3.95, 4.05, {"15m": 0.0, "30m": -0.1, "1h": -0.1, "4h": -0.2, "24h": 0.0}, mfe=0.3, mae=-1.6, broke=True),
        _event("XLM", "2026-05-01T16:00:00Z", 4.0, 3.95, 4.05, {"15m": -0.2, "30m": -0.1, "1h": -0.2, "4h": -0.1, "24h": -0.1}, mfe=0.4, mae=-1.5, broke=False),
        _event("XLM", "2026-05-01T20:00:00Z", 4.0, 3.95, 4.05, {"15m": -0.1, "30m": 0.0, "1h": -0.1, "4h": -0.1, "24h": 0.0}, mfe=0.2, mae=-1.6, broke=True),
    ]
    rows = build_profile_rows(event_rows=events, context_rows=_context_rows(), fibo_by_symbol={}, min_events=5)
    assert rows[0]["profile_label"] == "FAKEOUT_PRONE"


def test_low_sample_fixture_classifies_insufficient_sample():
    events = [
        _event("TAO", "2026-05-01T04:00:00Z", 5.0, 4.9, 5.1, {"15m": 0.5}, mfe=1.0, mae=-0.5),
        _event("TAO", "2026-05-01T08:00:00Z", 5.0, 4.9, 5.1, {"15m": 0.4}, mfe=0.8, mae=-0.5),
    ]
    rows = build_profile_rows(event_rows=events, context_rows=[], fibo_by_symbol={}, min_events=5)
    assert rows[0]["profile_label"] == "INSUFFICIENT_SAMPLE"


def test_missing_context_produces_unknown_bucket_not_crash():
    events = [
        _event("ALGO", "2026-05-01T04:00:00Z", 1.0, 0.98, 1.01, {"15m": 0.2, "24h": 0.5}, mfe=0.6, mae=-0.2),
    ]
    rows = build_profile_rows(event_rows=events, context_rows=[], fibo_by_symbol={}, min_events=1)
    assert rows[0]["breath_phase"] == "UNKNOWN"
    assert rows[0]["market_regime"] == "UNKNOWN"


def test_output_has_one_row_per_symbol_context_bucket():
    events = [
        _event("WLD", "2026-05-01T04:00:00Z", 10.1, 10.0, 10.2, {"15m": 1.0, "24h": 4.0}, mfe=5.0, mae=-2.0),
        _event("WLD", "2026-05-02T04:00:00Z", 9.8, 9.5, 9.9, {"15m": -0.5, "24h": -1.0}, mfe=1.2, mae=-3.0, broke=True),
    ]
    rows = build_profile_rows(event_rows=events, context_rows=_context_rows(), fibo_by_symbol={}, min_events=1)
    assert len(rows) == 2


def test_no_broker_decision_execution_imports():
    src = Path("src/research/run_symbol_reaction_profile_by_context_v1.py").read_text()
    assert "BitvavoClient" not in src
    assert "from src.decision_gate" not in src
    assert "from src.execution_planner" not in src
    assert "from src.executor" not in src
    assert "place_order" not in src
    assert "cancel_order" not in src


def test_manifest_has_safety_markers():
    rows = build_profile_rows(
        event_rows=[_event("ALGO", "2026-05-01T04:00:00Z", 1.0, 0.98, 1.01, {"15m": 0.2, "24h": 0.5}, mfe=0.6, mae=-0.2)],
        context_rows=[],
        fibo_by_symbol={},
        min_events=1,
    )
    manifest = build_manifest(
        rows=rows,
        input_rows_path=Path("events.jsonl"),
        fibo_rows_path=Path("fibo.csv"),
        context_rows_path=Path("context.jsonl"),
        output_dir=Path("/tmp/out"),
    )
    assert manifest["research_only"] is True
    assert manifest["safety_markers"] == SAFETY_MARKERS


def test_no_broker_like_ast_calls():
    src = Path("src/research/run_symbol_reaction_profile_by_context_v1.py").read_text()
    tree = ast.parse(src)
    forbidden = {"place_order", "cancel_order", "create_order"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in forbidden:
            raise AssertionError(f"Forbidden broker-like call .{node.attr}() found")


def main():
    test_fast_reactor_classification()
    test_btc_damage_classifies_fakeout_prone()
    test_deep_retracer_classification()
    test_fakeout_fixture_classifies_fakeout_prone()
    test_low_sample_fixture_classifies_insufficient_sample()
    test_missing_context_produces_unknown_bucket_not_crash()
    test_output_has_one_row_per_symbol_context_bucket()
    test_no_broker_decision_execution_imports()
    test_manifest_has_safety_markers()
    test_no_broker_like_ast_calls()
    print("ok")


if __name__ == "__main__":
    main()
