from __future__ import annotations

import ast
import json
import tempfile
import unittest
from pathlib import Path

from src.research.run_historical_market_breath_source_enrichment_v1 import (
    SAFETY_MARKERS,
    enrich_rows,
    load_input_rows,
    main,
    normalize_row,
    quality_state_for_row,
)


MODULE_PATH = Path("src/research/run_historical_market_breath_source_enrichment_v1.py")


class HistoricalMarketBreathSourceEnrichmentV1Tests(unittest.TestCase):
    def test_maps_known_market_breath_phase(self) -> None:
        row = normalize_row(
            {
                "symbol": "WLD",
                "venue": "bitvavo",
                "interval_code": "4h",
                "asof_ts_utc": "2026-05-01T00:00:00Z",
                "market_breath_phase": "EXHALE_EXPANSION",
                "market_breath_state": "CONFIRMED",
                "relative_strength_score": 35.0,
                "momentum_score": 28.0,
                "btc_alignment_score": 22.0,
                "breadth_alignment_score": 10.0,
                "market_breath_confidence": 100.0,
            },
            input_path=Path("input.jsonl"),
            default_venue="bitvavo",
            default_interval="4h",
        )
        assert row is not None
        self.assertEqual(row["breath_phase"], "EXPANSION")

    def test_unknown_raw_phase_stays_unknown(self) -> None:
        row = normalize_row(
            {
                "symbol": "WLD",
                "asof_ts_utc": "2026-05-01T00:00:00Z",
                "market_breath_phase": "NEUTRAL_TRANSITION",
                "market_breath_state": "UNKNOWN",
            },
            input_path=Path("input.jsonl"),
            default_venue="bitvavo",
            default_interval="4h",
        )
        assert row is not None
        self.assertEqual(row["breath_phase"], "UNKNOWN")

    def test_unsupported_raw_phase_stays_unknown(self) -> None:
        row = normalize_row(
            {
                "symbol": "NEAR",
                "asof_ts_utc": "2026-05-01T00:00:00Z",
                "market_breath_phase": "SIDEWAYS_DRIFT",
                "market_breath_state": "CONFIRMED",
            },
            input_path=Path("input.jsonl"),
            default_venue="bitvavo",
            default_interval="4h",
        )
        assert row is not None
        self.assertEqual(row["breath_phase"], "UNKNOWN")

    def test_symbol_regime_derived_from_scores(self) -> None:
        row = normalize_row(
            {
                "symbol": "HYPE",
                "asof_ts_utc": "2026-05-01T00:00:00Z",
                "market_breath_phase": "NEUTRAL_TRANSITION",
                "market_breath_state": "UNKNOWN",
                "relative_strength_score": 31.0,
                "momentum_score": 55.0,
                "btc_alignment_score": 12.0,
                "breadth_alignment_score": 4.0,
            },
            input_path=Path("input.jsonl"),
            default_venue="bitvavo",
            default_interval="4h",
        )
        assert row is not None
        self.assertEqual(row["symbol_regime"], "REL_STRENGTH")

    def test_breath_alignment_not_invented_when_raw_unknown(self) -> None:
        row = normalize_row(
            {
                "symbol": "TAO",
                "asof_ts_utc": "2026-05-01T00:00:00Z",
                "market_breath_phase": "EXHALE_EXPANSION",
                "market_breath_state": "UNKNOWN",
                "relative_strength_score": 10.0,
                "momentum_score": 25.0,
            },
            input_path=Path("input.jsonl"),
            default_venue="bitvavo",
            default_interval="4h",
        )
        assert row is not None
        self.assertEqual(row["breath_alignment"], "UNKNOWN")

    def test_unsupported_raw_alignment_stays_unknown(self) -> None:
        row = normalize_row(
            {
                "symbol": "TAO",
                "asof_ts_utc": "2026-05-01T00:00:00Z",
                "market_breath_phase": "EXHALE_EXPANSION",
                "market_breath_state": "SIDEWAYS",
                "relative_strength_score": 10.0,
                "momentum_score": 25.0,
            },
            input_path=Path("input.jsonl"),
            default_venue="bitvavo",
            default_interval="4h",
        )
        assert row is not None
        self.assertEqual(row["breath_alignment"], "UNKNOWN")

    def test_ambiguous_symbol_regime_stays_unknown(self) -> None:
        row = normalize_row(
            {
                "symbol": "ALGO",
                "asof_ts_utc": "2026-05-01T00:00:00Z",
                "market_breath_phase": "NEUTRAL_TRANSITION",
                "market_breath_state": "UNKNOWN",
                "relative_strength_score": 5.0,
                "momentum_score": 15.0,
            },
            input_path=Path("input.jsonl"),
            default_venue="bitvavo",
            default_interval="4h",
        )
        assert row is not None
        self.assertEqual(row["symbol_regime"], "UNKNOWN")

    def test_quality_state_improves_when_fields_known(self) -> None:
        low = quality_state_for_row(
            {
                "breath_phase": "UNKNOWN",
                "symbol_regime": "UNKNOWN",
                "market_regime": "UNKNOWN",
                "btc_context": "UNKNOWN",
            }
        )
        medium = quality_state_for_row(
            {
                "breath_phase": "UNKNOWN",
                "symbol_regime": "REL_STRENGTH",
                "market_regime": "UNKNOWN",
                "btc_context": "UNKNOWN",
            }
        )
        high = quality_state_for_row(
            {
                "breath_phase": "EXPANSION",
                "symbol_regime": "REL_STRENGTH",
                "market_regime": "ALT_STRENGTH",
                "btc_context": "BTC_OK",
            }
        )
        self.assertEqual(low, "LOW")
        self.assertEqual(medium, "MEDIUM")
        self.assertEqual(high, "HIGH")

    def test_missing_input_file_fails_cleanly(self) -> None:
        with self.assertRaises(FileNotFoundError):
            load_input_rows(Path("does-not-exist.jsonl"))

    def test_enrich_rows_is_deterministic(self) -> None:
        rows = [
            {
                "symbol": "WLD",
                "venue": "bitvavo",
                "interval_code": "4h",
                "asof_ts_utc": "2026-05-01T00:00:00Z",
                "market_breath_phase": "EXHALE_EXPANSION",
                "market_breath_state": "CONFIRMED",
                "relative_strength_score": 25.0,
                "momentum_score": 30.0,
                "btc_alignment_score": 18.0,
                "breadth_alignment_score": 8.0,
                "market_breath_confidence": 100.0,
            }
        ]
        first_rows, first_measures = enrich_rows(
            rows,
            input_path=Path("input.jsonl"),
            symbols=None,
            default_venue="bitvavo",
            default_interval="4h",
        )
        second_rows, second_measures = enrich_rows(
            rows,
            input_path=Path("input.jsonl"),
            symbols=None,
            default_venue="bitvavo",
            default_interval="4h",
        )
        self.assertEqual(first_rows, second_rows)
        self.assertEqual(first_measures, second_measures)

    def test_write_files_manifest_contains_safety_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.jsonl"
            input_path.write_text(
                json.dumps(
                    {
                        "symbol": "WLD",
                        "venue": "bitvavo",
                        "interval_code": "4h",
                        "asof_ts_utc": "2026-05-01T00:00:00Z",
                        "market_breath_phase": "EXHALE_EXPANSION",
                        "market_breath_state": "CONFIRMED",
                        "relative_strength_score": 25.0,
                        "momentum_score": 30.0,
                        "btc_alignment_score": 18.0,
                        "breadth_alignment_score": 8.0,
                        "market_breath_confidence": 100.0,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            output_dir = Path(tmpdir) / "out"
            rc = main(
                [
                    "--input-rows",
                    str(input_path),
                    "--write-files",
                    "--output-dir",
                    str(output_dir),
                    "--output",
                    "summary",
                ]
            )
            self.assertEqual(rc, 0)
            manifest = json.loads((output_dir / "manifest_v1.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["safety_markers"], SAFETY_MARKERS)

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

    def test_no_broker_like_ast_calls(self) -> None:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        forbidden = {"place_order", "cancel_order", "create_order"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                self.assertNotIn(node.func.attr, forbidden)


if __name__ == "__main__":
    unittest.main()
