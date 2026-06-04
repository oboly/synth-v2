from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

from src.research.run_context_qualified_symbol_reaction_profile_audit_v1 import (
    SAFETY_MARKERS,
    build_audit_rows,
    build_manifest,
)


MODULE_PATH = Path("src/research/run_context_qualified_symbol_reaction_profile_audit_v1.py")


def _context_rows() -> list[dict[str, str]]:
    return [
        {
            "symbol": "WLD",
            "breath_phase": "RELOAD",
            "breath_alignment": "ALIGNED",
            "market_regime": "ALT_STRENGTH",
            "btc_context": "BTC_OK",
            "symbol_regime": "REL_STRENGTH",
            "fibo_context": "UNKNOWN",
            "quality_state": "HIGH",
        },
        {
            "symbol": "NEAR",
            "breath_phase": "UNKNOWN",
            "breath_alignment": "UNKNOWN",
            "market_regime": "UNKNOWN",
            "btc_context": "UNKNOWN",
            "symbol_regime": "UNKNOWN",
            "fibo_context": "UNKNOWN",
            "quality_state": "LOW",
        },
    ]


def _profile_rows() -> list[dict[str, str]]:
    return [
        {
            "symbol": "WLD",
            "breath_phase": "RELOAD",
            "breath_alignment": "ALIGNED",
            "market_regime": "ALT_STRENGTH",
            "btc_context": "BTC_OK",
            "symbol_regime": "REL_STRENGTH",
            "fibo_context": "UNKNOWN",
            "event_count": "10",
            "eligible_event_count": "8",
            "avg_mfe_pct": "5.0",
            "avg_mae_pct": "2.0",
            "fakeout_rate": "20.0",
            "reaction_zone_touch_rate": "80.0",
            "sample_quality": "HIGH",
            "profile_label": "FAST_REACTOR",
        },
        {
            "symbol": "NEAR",
            "breath_phase": "UNKNOWN",
            "breath_alignment": "UNKNOWN",
            "market_regime": "UNKNOWN",
            "btc_context": "UNKNOWN",
            "symbol_regime": "UNKNOWN",
            "fibo_context": "UNKNOWN",
            "event_count": "5",
            "eligible_event_count": "2",
            "avg_mfe_pct": "1.0",
            "avg_mae_pct": "4.0",
            "fakeout_rate": "70.0",
            "reaction_zone_touch_rate": "20.0",
            "sample_quality": "LOW",
            "profile_label": "FAKEOUT_PRONE",
        },
    ]


class ContextQualifiedSymbolReactionProfileAuditV1Tests(unittest.TestCase):
    def test_known_context_fixture_counted_in_breath_phase_known(self) -> None:
        rows = build_audit_rows(context_rows=_context_rows(), profile_rows=_profile_rows(), min_events=1)
        bucket = next(row for row in rows if row["bucket"] == "BREATH_PHASE_KNOWN")
        self.assertEqual(bucket["profile_row_count"], 1)
        self.assertEqual(bucket["event_count_sum"], 10)

    def test_unknown_heavy_fixture_counted_in_unknown_heavy(self) -> None:
        rows = build_audit_rows(context_rows=_context_rows(), profile_rows=_profile_rows(), min_events=1)
        bucket = next(row for row in rows if row["bucket"] == "UNKNOWN_HEAVY")
        self.assertEqual(bucket["profile_row_count"], 1)
        self.assertEqual(bucket["event_count_sum"], 5)

    def test_weighted_metrics_calculated_correctly(self) -> None:
        rows = build_audit_rows(context_rows=_context_rows(), profile_rows=_profile_rows(), min_events=1)
        bucket = next(row for row in rows if row["bucket"] == "ALL")
        self.assertAlmostEqual(bucket["avg_mfe_pct_weighted"], 3.666667, places=6)
        self.assertAlmostEqual(bucket["avg_mae_pct_weighted"], 2.666667, places=6)

    def test_empty_bucket_fails_closed_with_skipped_reason(self) -> None:
        rows = build_audit_rows(context_rows=[], profile_rows=[], min_events=1)
        bucket = next(row for row in rows if row["bucket"] == "ALL")
        self.assertEqual(bucket["skipped_reason"], "NO_ROWS_QUALIFY")

    def test_manifest_contains_safety_markers(self) -> None:
        manifest = build_manifest(
            context_rows_path=Path("context.csv"),
            profile_rows_path=Path("profile.csv"),
            output_dir=Path("/tmp/out"),
            audit_rows=[],
        )
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

    def test_no_db_writes(self) -> None:
        text = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn(".commit(", text)
        self.assertNotIn("INSERT INTO", text.upper())
        self.assertNotIn("UPDATE ", text.upper())
        self.assertNotIn("DELETE FROM", text.upper())


if __name__ == "__main__":
    unittest.main()
