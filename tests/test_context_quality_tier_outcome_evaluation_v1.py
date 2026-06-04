from __future__ import annotations

import ast
import unittest
from pathlib import Path

from src.research.run_context_quality_tier_outcome_evaluation_v1 import (
    ALL_LABEL,
    SAFETY_MARKERS,
    build_manifest,
    build_symbol_tier_rows,
    build_tier_rows,
    load_event_rows,
)


MODULE_PATH = Path("src/research/run_context_quality_tier_outcome_evaluation_v1.py")


def _row(
    symbol: str = "XLM",
    tier: str = "BREATH_CONTEXT",
    *,
    mfe: float = 3.0,
    mae: float = -1.5,
    r4h: float = 1.2,
    r24h: float = 2.0,
    fakeout: str = "False",
    touch: str = "True",
) -> dict:
    return {
        "symbol": symbol,
        "context_quality_tier": tier,
        "max_favorable_excursion_pct": str(mfe),
        "max_adverse_excursion_pct": str(mae),
        "drawdown_after_event_pct": str(mae),
        "forward_return_15m": "0.5",
        "forward_return_30m": "0.8",
        "forward_return_1h": "1.0",
        "forward_return_4h": str(r4h),
        "forward_return_24h": str(r24h),
        "fakeout_flag": fakeout,
        "reaction_zone_touch": touch,
    }


class TierMetricsTests(unittest.TestCase):
    def test_tier_metrics_aggregate_correctly(self) -> None:
        events = [
            _row("XLM", "BREATH_CONTEXT", mfe=4.0, mae=-2.0),
            _row("XLM", "BREATH_CONTEXT", mfe=2.0, mae=-1.0),
        ]
        rows = build_tier_rows(events, min_events=1)
        breath = next(r for r in rows if r["context_quality_tier"] == "BREATH_CONTEXT")
        self.assertEqual(breath["event_count"], 2)
        self.assertAlmostEqual(breath["avg_mfe_pct"], 3.0)
        self.assertAlmostEqual(breath["avg_mae_pct"], -1.5)
        self.assertIsNotNone(breath["mfe_mae_ratio"])
        self.assertEqual(breath["research_only"], True)

    def test_all_baseline_covers_all_events(self) -> None:
        events = [
            _row("XLM", "BREATH_CONTEXT"),
            _row("XLM", "SYMBOL_REGIME_CONTEXT"),
            _row("XLM", "MARKET_ONLY_CONTEXT"),
        ]
        rows = build_tier_rows(events, min_events=1)
        all_row = next(r for r in rows if r["context_quality_tier"] == ALL_LABEL)
        self.assertEqual(all_row["event_count"], 3)

    def test_known_tiers_remain_separate(self) -> None:
        events = [
            _row("XLM", "BREATH_CONTEXT"),
            _row("XLM", "SYMBOL_REGIME_CONTEXT"),
            _row("XLM", "MARKET_ONLY_CONTEXT"),
        ]
        rows = build_tier_rows(events, min_events=1)
        tiers = [r["context_quality_tier"] for r in rows if r["context_quality_tier"] != ALL_LABEL]
        self.assertEqual(len(tiers), 3)
        self.assertIn("BREATH_CONTEXT", tiers)
        self.assertIn("SYMBOL_REGIME_CONTEXT", tiers)
        self.assertIn("MARKET_ONLY_CONTEXT", tiers)
        # No tier covers another's events
        breath = next(r for r in rows if r["context_quality_tier"] == "BREATH_CONTEXT")
        self.assertEqual(breath["event_count"], 1)

    def test_small_sample_becomes_insufficient(self) -> None:
        events = [_row("XLM", "BREATH_CONTEXT")]
        rows = build_tier_rows(events, min_events=10)
        breath = next(r for r in rows if r["context_quality_tier"] == "BREATH_CONTEXT")
        self.assertEqual(breath["sample_quality"], "INSUFFICIENT")

    def test_missing_metric_fields_do_not_crash(self) -> None:
        events = [{"symbol": "XLM", "context_quality_tier": "BREATH_CONTEXT"}]
        rows = build_tier_rows(events, min_events=1)
        breath = next(r for r in rows if r["context_quality_tier"] == "BREATH_CONTEXT")
        self.assertIsNone(breath["avg_mfe_pct"])
        self.assertIsNone(breath["avg_mae_pct"])
        self.assertIsNone(breath["fakeout_rate"])

    def test_per_symbol_tier_rows_aggregate_correctly(self) -> None:
        events = [
            _row("XLM", "BREATH_CONTEXT", mfe=4.0, mae=-2.0),
            _row("XLM", "BREATH_CONTEXT", mfe=2.0, mae=-1.0),
            _row("ALGO", "BREATH_CONTEXT", mfe=1.0, mae=-0.5),
        ]
        rows = build_symbol_tier_rows(events, min_events=1)
        xlm_row = next((r for r in rows if r["symbol"] == "XLM" and r["context_quality_tier"] == "BREATH_CONTEXT"), None)
        self.assertIsNotNone(xlm_row)
        self.assertEqual(xlm_row["event_count"], 2)
        self.assertAlmostEqual(xlm_row["avg_mfe_pct"], 3.0)

        algo_row = next((r for r in rows if r["symbol"] == "ALGO"), None)
        self.assertIsNotNone(algo_row)
        self.assertEqual(algo_row["event_count"], 1)

    def test_manifest_usable_tiers(self) -> None:
        events = [_row("XLM", "BREATH_CONTEXT")] * 10
        tier_rows = build_tier_rows(events, min_events=5)
        sym_rows = build_symbol_tier_rows(events, min_events=5)
        manifest = build_manifest(
            args=type("Args", (), {"event_level_rows": "e.csv", "symbols": None})(),
            output_dir=Path("/tmp/out"),
            tier_rows=tier_rows,
            symbol_rows=sym_rows,
            event_row_count=10,
        )
        self.assertIn("BREATH_CONTEXT", manifest["usable_tiers"])
        self.assertTrue(manifest["research_only"])
        self.assertEqual(manifest["safety_markers"], SAFETY_MARKERS)


class SafetyTests(unittest.TestCase):
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

    def test_safety_markers_all_zero(self) -> None:
        self.assertEqual(SAFETY_MARKERS["broker_calls"], 0)
        self.assertEqual(SAFETY_MARKERS["broker_writes"], 0)
        self.assertEqual(SAFETY_MARKERS["db_writes"], 0)
        self.assertEqual(SAFETY_MARKERS["order_submission"], 0)
        self.assertTrue(SAFETY_MARKERS["research_only"])


if __name__ == "__main__":
    unittest.main()
