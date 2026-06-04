from __future__ import annotations

import ast
import unittest
from pathlib import Path

from src.research.run_symbol_reaction_profile_from_event_level_context_v1 import (
    SAFETY_MARKERS,
    TIER_BREATH,
    TIER_SYMBOL_REGIME,
    TIER_MARKET_ONLY,
    TIER_UNKNOWN,
    build_aggregate_rows,
    build_manifest,
    context_bucket_key,
    context_quality_tier,
)


MODULE_PATH = Path("src/research/run_symbol_reaction_profile_from_event_level_context_v1.py")


def _known_event(symbol: str = "XLM", suffix: str = "") -> dict:
    return {
        "symbol": symbol,
        "breath_phase": "EXPANSION",
        "breath_alignment": "ALIGNED",
        "market_regime": "ALT_STRENGTH",
        "btc_context": "BTC_OK",
        "symbol_regime": "REL_STRENGTH",
        "fibo_context": "MID_RANGE",
        "context_quality_state": "HIGH",
        "max_favorable_excursion_pct": 2.5,
        "max_adverse_excursion_pct": -1.0,
        "drawdown_after_event_pct": -0.5,
        "fakeout_flag": "False",
        "reaction_zone_touch": "True",
        "retrace_to_entry_low_pct": 1.2,
        "retrace_to_entry_mid_pct": 2.4,
        "retrace_to_entry_high_pct": 3.6,
        "forward_return_15m": 0.8,
        "forward_return_30m": 1.0,
        "forward_return_1h": 1.5,
        "forward_return_4h": 2.0,
        "forward_return_24h": 3.0,
        "research_only": "True",
    }


def _unknown_event(symbol: str = "XLM") -> dict:
    return {
        "symbol": symbol,
        "breath_phase": "UNKNOWN",
        "breath_alignment": "UNKNOWN",
        "market_regime": "RISK_ON",
        "btc_context": "BTC_OK",
        "symbol_regime": "UNKNOWN",
        "fibo_context": "UNKNOWN",
        "context_quality_state": "LOW",
        "max_favorable_excursion_pct": 1.0,
        "max_adverse_excursion_pct": -0.5,
        "drawdown_after_event_pct": -0.2,
        "fakeout_flag": "False",
        "reaction_zone_touch": "False",
        "retrace_to_entry_low_pct": 4.0,
        "retrace_to_entry_mid_pct": 5.0,
        "retrace_to_entry_high_pct": 6.0,
        "forward_return_15m": -0.3,
        "forward_return_30m": -0.4,
        "forward_return_1h": 0.1,
        "forward_return_4h": 0.5,
        "forward_return_24h": 1.0,
        "research_only": "True",
    }


class AggregateFromEventLevelContextV1Tests(unittest.TestCase):
    def test_known_context_events_produce_separate_known_bucket(self) -> None:
        rows = build_aggregate_rows(event_rows=[_known_event(), _known_event()], min_events=1)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["known_context"])
        self.assertEqual(rows[0]["breath_phase"], "EXPANSION")
        self.assertEqual(rows[0]["breath_alignment"], "ALIGNED")
        self.assertEqual(rows[0]["event_count"], 2)

    def test_unknown_events_produce_unknown_bucket(self) -> None:
        rows = build_aggregate_rows(event_rows=[_unknown_event(), _unknown_event()], min_events=1)
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["known_context"])
        self.assertEqual(rows[0]["breath_phase"], "UNKNOWN")
        self.assertEqual(rows[0]["symbol_regime"], "UNKNOWN")

    def test_known_and_unknown_are_not_merged(self) -> None:
        rows = build_aggregate_rows(
            event_rows=[_known_event(), _unknown_event()],
            min_events=1,
        )
        self.assertEqual(len(rows), 2)
        keys = {(row["breath_phase"], row["symbol_regime"]) for row in rows}
        self.assertIn(("EXPANSION", "REL_STRENGTH"), keys)
        self.assertIn(("UNKNOWN", "UNKNOWN"), keys)

    def test_xlm_like_fixture_preserves_known_context_event_count_in_aggregate(self) -> None:
        # 3 known events spread across 2 different known buckets + 2 unknown events
        events = [
            _known_event("XLM"),
            _known_event("XLM"),
            {**_known_event("XLM"), "breath_phase": "RELOAD", "symbol_regime": "NEUTRAL"},
            _unknown_event("XLM"),
            _unknown_event("XLM"),
        ]
        rows = build_aggregate_rows(event_rows=events, min_events=1)
        known_rows = [r for r in rows if r["known_context"]]
        unknown_rows = [r for r in rows if not r["known_context"]]
        # known events must appear in known buckets only — sum of event_count equals 3
        self.assertEqual(sum(r["event_count"] for r in known_rows), 3)
        # unknown events appear in unknown buckets only
        self.assertEqual(sum(r["event_count"] for r in unknown_rows), 2)
        # separate buckets: EXPANSION+REL_STRENGTH and RELOAD+NEUTRAL
        self.assertEqual(len(known_rows), 2)

    def test_manifest_contains_safety_markers(self) -> None:
        rows = build_aggregate_rows(
            event_rows=[_known_event(), _unknown_event()],
            min_events=1,
        )
        manifest = build_manifest(
            args=type("Args", (), {"event_level_rows": "events.csv", "symbols": None})(),
            output_dir=Path("/tmp/out"),
            rows=rows,
            event_row_count=2,
        )
        self.assertEqual(manifest["safety_markers"], SAFETY_MARKERS)
        self.assertTrue(manifest["research_only"])
        self.assertEqual(manifest["known_context_aggregate_rows"], 1)
        self.assertEqual(manifest["unknown_aggregate_rows"], 1)

    def test_no_forbidden_imports(self) -> None:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        joined = "\n".join(imports)
        self.assertNotIn("decision_gate", joined)
        self.assertNotIn("execution_planner", joined)
        self.assertNotIn("executor", joined)
        self.assertNotIn("BitvavoClient", joined)
        self.assertNotIn("common.db", joined)


class ContextQualityTierAggregateTests(unittest.TestCase):
    def test_breath_known_row_has_breath_tier(self) -> None:
        rows = build_aggregate_rows(event_rows=[_known_event()], min_events=1)
        self.assertEqual(rows[0]["context_quality_tier"], TIER_BREATH)

    def test_symbol_regime_only_row_has_symbol_regime_tier(self) -> None:
        event = {**_known_event(), "breath_phase": "UNKNOWN", "breath_alignment": "UNKNOWN"}
        rows = build_aggregate_rows(event_rows=[event], min_events=1)
        self.assertEqual(rows[0]["context_quality_tier"], TIER_SYMBOL_REGIME)

    def test_market_only_row_has_market_only_tier(self) -> None:
        event = {
            **_unknown_event(),
            "market_regime": "RISK_ON",
            "btc_context": "BTC_OK",
        }
        rows = build_aggregate_rows(event_rows=[event], min_events=1)
        self.assertEqual(rows[0]["context_quality_tier"], TIER_MARKET_ONLY)

    def test_all_unknown_row_has_unknown_tier(self) -> None:
        all_unknown = {
            **_unknown_event(),
            "market_regime": "UNKNOWN",
            "btc_context": "UNKNOWN",
        }
        rows = build_aggregate_rows(event_rows=[all_unknown], min_events=1)
        self.assertEqual(rows[0]["context_quality_tier"], TIER_UNKNOWN)

    def test_aggregate_groups_preserve_tiers_separately(self) -> None:
        events = [_known_event(), _unknown_event()]
        rows = build_aggregate_rows(event_rows=events, min_events=1)
        tiers = {r["context_quality_tier"] for r in rows}
        self.assertIn(TIER_BREATH, tiers)
        # UNKNOWN_CONTEXT: all fields UNKNOWN (btc_context also unknown in _unknown_event)
        unknown_rows = [r for r in rows if r["context_quality_tier"] == TIER_UNKNOWN]
        known_rows = [r for r in rows if r["context_quality_tier"] != TIER_UNKNOWN]
        self.assertTrue(len(known_rows) >= 1)
        # Tiers must not be merged
        self.assertFalse(any(r["context_quality_tier"] == TIER_BREATH for r in unknown_rows))

    def test_manifest_contains_tier_distribution(self) -> None:
        rows = build_aggregate_rows(
            event_rows=[_known_event(), _unknown_event()], min_events=1
        )
        manifest = build_manifest(
            args=type("Args", (), {"event_level_rows": "events.csv", "symbols": None})(),
            output_dir=Path("/tmp/out"),
            rows=rows,
            event_row_count=2,
        )
        self.assertIn("tier_distribution", manifest)
        self.assertIn(TIER_BREATH, manifest["tier_distribution"])


if __name__ == "__main__":
    unittest.main()
