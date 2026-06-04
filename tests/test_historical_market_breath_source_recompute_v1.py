from __future__ import annotations

import ast
import json
import tempfile
import unittest
from pathlib import Path

from src.research.run_historical_market_breath_source_recompute_v1 import (
    REPORT_NAME,
    SAFETY_MARKERS,
    build_manifest,
    build_recomputed_row,
    parse_ts,
    print_summary,
)


MODULE_PATH = Path("src/research/run_historical_market_breath_source_recompute_v1.py")


class HistoricalMarketBreathSourceRecomputeV1Tests(unittest.TestCase):
    def test_recompute_row_maps_known_raw_phase(self) -> None:
        row = build_recomputed_row(
            {
                "symbol": "WLD",
                "venue": "bitvavo",
                "interval_code": "4h",
                "asof_ts_utc": "2026-05-01T00:00:00Z",
                "market_breath_phase": "EXHALE_EXPANSION",
                "market_breath_state": "CONFIRMED",
                "relative_strength_score": 30.0,
                "momentum_score": 25.0,
                "btc_alignment_score": 12.0,
                "breadth_alignment_score": 5.0,
                "market_breath_confidence": 100.0,
            }
        )
        self.assertEqual(row["breath_phase"], "EXPANSION")

    def test_unknown_raw_phase_remains_unknown(self) -> None:
        row = build_recomputed_row(
            {
                "symbol": "NEAR",
                "venue": "bitvavo",
                "interval_code": "4h",
                "asof_ts_utc": "2026-05-01T00:00:00Z",
                "market_breath_phase": "NEUTRAL_TRANSITION",
                "market_breath_state": "UNKNOWN",
            }
        )
        self.assertEqual(row["breath_phase"], "UNKNOWN")

    def test_unknown_alignment_remains_unknown(self) -> None:
        row = build_recomputed_row(
            {
                "symbol": "HYPE",
                "venue": "bitvavo",
                "interval_code": "4h",
                "asof_ts_utc": "2026-05-01T00:00:00Z",
                "market_breath_phase": "EXHALE_EXPANSION",
                "market_breath_state": "SIDEWAYS",
                "relative_strength_score": 5.0,
                "momentum_score": 15.0,
            }
        )
        self.assertEqual(row["breath_alignment"], "UNKNOWN")

    def test_symbol_regime_uses_existing_helper_thresholds(self) -> None:
        row = build_recomputed_row(
            {
                "symbol": "TAO",
                "venue": "bitvavo",
                "interval_code": "4h",
                "asof_ts_utc": "2026-05-01T00:00:00Z",
                "market_breath_phase": "NEUTRAL_TRANSITION",
                "market_breath_state": "UNKNOWN",
                "relative_strength_score": 25.0,
                "momentum_score": 50.0,
            }
        )
        self.assertEqual(row["symbol_regime"], "REL_STRENGTH")

    def test_missing_source_input_fails_cleanly(self) -> None:
        with self.assertRaises(ValueError):
            build_recomputed_row({"symbol": "WLD"})

    def test_output_includes_source_refs_and_research_only(self) -> None:
        row = build_recomputed_row(
            {
                "symbol": "ALGO",
                "venue": "bitvavo",
                "interval_code": "4h",
                "asof_ts_utc": "2026-05-01T00:00:00Z",
                "market_breath_phase": "COLLAPSE_RESET",
                "market_breath_state": "RESET",
                "relative_strength_score": -25.0,
                "momentum_score": -50.0,
            }
        )
        self.assertTrue(row["research_only"])
        self.assertTrue(row["source_refs"])
        self.assertEqual(row["source_refs"][0]["source"], REPORT_NAME)

    def test_manifest_safety_markers_exist(self) -> None:
        manifest = build_manifest(
            args=type(
                "Args",
                (),
                {
                    "symbols": "WLD",
                    "venue": "bitvavo",
                    "interval": "4h",
                    "start_ts": None,
                    "end_ts": None,
                },
            )(),
            rows=[],
            measures={"breath_phase_distribution": {}, "breath_alignment_distribution": {}, "symbol_regime_distribution": {}, "quality_state_distribution": {}},
            output_paths={},
        )
        self.assertEqual(manifest["safety_markers"], SAFETY_MARKERS)

    def test_print_summary_smoke(self) -> None:
        row = build_recomputed_row(
            {
                "symbol": "WLD",
                "venue": "bitvavo",
                "interval_code": "4h",
                "asof_ts_utc": "2026-05-01T00:00:00Z",
                "market_breath_phase": "EXHALE_EXPANSION",
                "market_breath_state": "CONFIRMED",
                "relative_strength_score": 30.0,
                "momentum_score": 25.0,
                "btc_alignment_score": 12.0,
                "breadth_alignment_score": 5.0,
                "market_breath_confidence": 100.0,
            }
        )
        print_summary(
            rows=[row],
            measures={
                "breath_phase_distribution": {"EXPANSION": 1},
                "breath_alignment_distribution": {"ALIGNED": 1},
                "symbol_regime_distribution": {"REL_STRENGTH": 1},
                "quality_state_distribution": {"HIGH": 1},
            },
        )

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

    def test_no_db_writes(self) -> None:
        text = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn(".commit(", text)
        self.assertNotIn("INSERT INTO", text.upper())
        self.assertNotIn("UPDATE ", text.upper())
        self.assertNotIn("DELETE FROM", text.upper())


if __name__ == "__main__":
    unittest.main()
