from __future__ import annotations

import ast
import unittest
from pathlib import Path

from src.research.run_event_level_symbol_reaction_profile_by_context_v1 import (
    SAFETY_MARKERS,
    TIER_BREATH,
    TIER_SYMBOL_REGIME,
    TIER_MARKET_ONLY,
    TIER_UNKNOWN,
    build_event_level_rows,
    build_manifest,
    context_quality_tier,
    parse_ts,
)


MODULE_PATH = Path("src/research/run_event_level_symbol_reaction_profile_by_context_v1.py")


def _event_rows() -> list[dict]:
    return [
        {
            "symbol": "XLM",
            "event_ts_utc_dt": parse_ts("2026-05-01T04:00:00Z"),
            "current_price": 1.02,
            "entry_zone_low": 1.0,
            "entry_zone_high": 1.04,
            "forward_returns": {"15m": 0.8, "4h": 1.4},
            "max_favorable_excursion_pct": 2.1,
            "max_adverse_excursion_pct": -0.7,
            "drawdown_after_event_pct": -0.3,
            "broke_invalidation_like_move": False,
        }
    ]


def _context_known() -> list[dict]:
    return [
        {
            "symbol": "XLM",
            "asof_ts_utc_dt": parse_ts("2026-05-01T04:00:00Z"),
            "venue": "bitvavo",
            "interval": "4h",
            "breath_phase": "EXPANSION",
            "breath_alignment": "ALIGNED",
            "market_regime": "ALT_STRENGTH",
            "btc_context": "BTC_OK",
            "symbol_regime": "REL_STRENGTH",
            "fibo_context": "MID_RANGE",
            "quality_state": "HIGH",
            "confidence_bucket": "HIGH",
            "source_refs": [{"source": "context_fixture"}],
        }
    ]


def _context_unknown() -> list[dict]:
    return [
        {
            "symbol": "XLM",
            "asof_ts_utc_dt": parse_ts("2026-05-01T04:00:00Z"),
            "venue": "bitvavo",
            "interval": "4h",
            "breath_phase": "UNKNOWN",
            "breath_alignment": "UNKNOWN",
            "market_regime": "UNKNOWN",
            "btc_context": "UNKNOWN",
            "symbol_regime": "UNKNOWN",
            "fibo_context": "UNKNOWN",
            "quality_state": "UNKNOWN",
            "confidence_bucket": "UNKNOWN",
            "source_refs": [{"source": "context_fixture_unknown"}],
        }
    ]


def _recompute_known() -> list[dict]:
    return [
        {
            "symbol": "XLM",
            "asof_ts_utc_dt": parse_ts("2026-05-01T04:00:00Z"),
            "venue": "bitvavo",
            "interval": "4h",
            "breath_phase": "EXPANSION",
            "breath_alignment": "ALIGNED",
            "market_regime": "ALT_STRENGTH",
            "btc_context": "BTC_OK",
            "symbol_regime": "REL_STRENGTH",
            "quality_state": "MEDIUM",
            "confidence_bucket": "MEDIUM",
            "source_refs": [{"source": "recompute_fixture"}],
        }
    ]


class EventLevelSymbolReactionProfileByContextV1Tests(unittest.TestCase):
    def test_event_with_known_context_preserves_phase_and_alignment(self) -> None:
        rows = build_event_level_rows(
            event_rows=_event_rows(),
            context_rows=_context_known(),
            recompute_rows=[],
            fibo_by_symbol={},
        )
        self.assertEqual(rows[0]["breath_phase"], "EXPANSION")
        self.assertEqual(rows[0]["breath_alignment"], "ALIGNED")
        self.assertEqual(rows[0]["context_quality_state"], "HIGH")

    def test_event_with_unknown_context_remains_unknown(self) -> None:
        rows = build_event_level_rows(
            event_rows=_event_rows(),
            context_rows=_context_unknown(),
            recompute_rows=[],
            fibo_by_symbol={},
        )
        self.assertEqual(rows[0]["breath_phase"], "UNKNOWN")
        self.assertEqual(rows[0]["breath_alignment"], "UNKNOWN")

    def test_aggregation_loss_fixture_preserves_event_level_known_context(self) -> None:
        rows = build_event_level_rows(
            event_rows=_event_rows(),
            context_rows=[],
            recompute_rows=_recompute_known(),
            fibo_by_symbol={},
        )
        self.assertEqual(rows[0]["breath_phase"], "EXPANSION")
        self.assertEqual(rows[0]["breath_alignment"], "ALIGNED")
        self.assertEqual(rows[0]["symbol_regime"], "REL_STRENGTH")

    def test_manifest_contains_safety_markers(self) -> None:
        manifest = build_manifest(
            args=type(
                "Args",
                (),
                {
                    "symbols": "XLM",
                    "input_rows": "events.jsonl",
                    "context_rows": "context.csv",
                    "recompute_rows": "recompute.csv",
                    "fibo_rows": "fibo.csv",
                },
            )(),
            output_dir=Path("/tmp/out"),
            rows=[{"symbol": "XLM", "breath_phase": "EXPANSION", "breath_alignment": "UNKNOWN", "symbol_regime": "UNKNOWN"}],
        )
        self.assertEqual(manifest["safety_markers"], SAFETY_MARKERS)
        self.assertTrue(manifest["research_only"])

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


class ContextQualityTierTests(unittest.TestCase):
    def test_breath_known_gives_breath_context(self) -> None:
        self.assertEqual(
            context_quality_tier({"breath_phase": "EXPANSION", "breath_alignment": "UNKNOWN",
                                   "symbol_regime": "UNKNOWN", "market_regime": "UNKNOWN", "btc_context": "UNKNOWN"}),
            TIER_BREATH,
        )

    def test_symbol_regime_without_breath_gives_symbol_regime_context(self) -> None:
        self.assertEqual(
            context_quality_tier({"breath_phase": "UNKNOWN", "breath_alignment": "UNKNOWN",
                                   "symbol_regime": "REL_STRENGTH", "market_regime": "UNKNOWN", "btc_context": "UNKNOWN"}),
            TIER_SYMBOL_REGIME,
        )

    def test_market_only_context_when_no_breath_or_symbol(self) -> None:
        self.assertEqual(
            context_quality_tier({"breath_phase": "UNKNOWN", "breath_alignment": "UNKNOWN",
                                   "symbol_regime": "UNKNOWN", "market_regime": "RISK_ON", "btc_context": "UNKNOWN"}),
            TIER_MARKET_ONLY,
        )

    def test_all_unknown_gives_unknown_context(self) -> None:
        self.assertEqual(
            context_quality_tier({"breath_phase": "UNKNOWN", "breath_alignment": "UNKNOWN",
                                   "symbol_regime": "UNKNOWN", "market_regime": "UNKNOWN", "btc_context": "UNKNOWN"}),
            TIER_UNKNOWN,
        )

    def test_event_level_rows_carry_context_quality_tier(self) -> None:
        rows = build_event_level_rows(
            event_rows=_event_rows(),
            context_rows=_context_known(),
            recompute_rows=[],
            fibo_by_symbol={},
        )
        self.assertIn("context_quality_tier", rows[0])
        self.assertEqual(rows[0]["context_quality_tier"], TIER_BREATH)

    def test_unknown_context_event_gets_unknown_tier(self) -> None:
        rows = build_event_level_rows(
            event_rows=_event_rows(),
            context_rows=_context_unknown(),
            recompute_rows=[],
            fibo_by_symbol={},
        )
        self.assertEqual(rows[0]["context_quality_tier"], TIER_UNKNOWN)

    def test_manifest_contains_tier_distribution(self) -> None:
        rows = build_event_level_rows(
            event_rows=_event_rows(),
            context_rows=_context_known(),
            recompute_rows=[],
            fibo_by_symbol={},
        )
        manifest = build_manifest(
            args=type(
                "Args", (),
                {"symbols": "XLM", "input_rows": "events.jsonl", "context_rows": "context.csv",
                 "recompute_rows": "recompute.csv", "fibo_rows": "fibo.csv"},
            )(),
            output_dir=Path("/tmp/out"),
            rows=rows,
        )
        self.assertIn("tier_distribution", manifest)
        self.assertIn(TIER_BREATH, manifest["tier_distribution"])


if __name__ == "__main__":
    unittest.main()
