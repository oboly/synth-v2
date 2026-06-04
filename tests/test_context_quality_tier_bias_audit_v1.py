from __future__ import annotations

import ast
import unittest
from pathlib import Path

from src.research.run_context_quality_tier_bias_audit_v1 import (
    SAFETY_MARKERS,
    build_breath_rows,
    build_fakeout_touch_rows,
    build_manifest,
    build_symbol_rows,
    build_time_rows,
    parse_ts,
)
from src.research.run_event_level_symbol_reaction_profile_by_context_v1 import (
    TIER_BREATH,
    TIER_MARKET_ONLY,
    TIER_SYMBOL_REGIME,
)


MODULE_PATH = Path("src/research/run_context_quality_tier_bias_audit_v1.py")


def _row(symbol: str, ts: str, tier: str, *, phase: str = "UNKNOWN", alignment: str = "UNKNOWN", r4h: float = 0.0, r24h: float = 0.0, mfe: float = 1.0, mae: float = -1.0, fakeout=None, touch=None) -> dict:
    return {
        "symbol": symbol,
        "event_ts_utc_dt": parse_ts(ts),
        "context_quality_tier": tier,
        "breath_phase": phase,
        "breath_alignment": alignment,
        "forward_return_4h": r4h,
        "forward_return_24h": r24h,
        "max_favorable_excursion_pct": mfe,
        "max_adverse_excursion_pct": mae,
        "fakeout_flag": fakeout,
        "reaction_zone_touch": touch,
    }


def _rows() -> list[dict]:
    return [
        _row("XLM", "2026-05-01T04:00:00Z", TIER_BREATH, phase="EXPANSION", alignment="ALIGNED", r4h=1.0, r24h=2.0, fakeout=False, touch=True),
        _row("XLM", "2026-05-02T04:00:00Z", TIER_BREATH, phase="EXPANSION", alignment="ALIGNED", r4h=0.5, r24h=1.5, fakeout=False, touch=False),
        _row("ALGO", "2026-05-04T04:00:00Z", TIER_SYMBOL_REGIME, r4h=2.0, r24h=3.0, fakeout=True, touch=True),
        _row("ALGO", "2026-05-05T04:00:00Z", TIER_MARKET_ONLY, r4h=3.0, r24h=4.0, fakeout=None, touch=False),
    ]


class ContextQualityTierBiasAuditV1Tests(unittest.TestCase):
    def test_per_symbol_tier_aggregation_works(self) -> None:
        rows = build_symbol_rows(_rows(), min_events=1)
        xlm_breath = next(r for r in rows if r["symbol"] == "XLM" and r["context_quality_tier"] == TIER_BREATH)
        self.assertEqual(xlm_breath["event_count"], 2)
        self.assertEqual(xlm_breath["avg_return_24h_pct"], 1.75)

    def test_time_bucket_aggregation_works(self) -> None:
        rows = build_time_rows(_rows(), min_events=1)
        self.assertTrue(any(r["context_quality_tier"] == TIER_BREATH for r in rows))
        self.assertTrue(all("time_bucket_start_utc" in r for r in rows))

    def test_breath_subtype_split_works(self) -> None:
        rows = build_breath_rows(_rows(), min_events=1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["breath_phase"], "EXPANSION")
        self.assertEqual(rows[0]["event_count"], 2)

    def test_fakeout_touch_crosstab_handles_missing_fields(self) -> None:
        rows = build_fakeout_touch_rows(_rows(), min_events=1)
        self.assertTrue(any(r["fakeout_flag"] == "UNKNOWN" for r in rows))
        self.assertTrue(any(r["reaction_zone_touch"] == "FALSE" for r in rows))

    def test_low_sample_marked_low_or_insufficient(self) -> None:
        rows = build_symbol_rows(_rows(), min_events=5)
        self.assertTrue(all(r["sample_quality"] in {"LOW", "INSUFFICIENT"} for r in rows))

    def test_safety_markers_present(self) -> None:
        manifest = build_manifest(
            args=type("Args", (), {"tier_outcome_rows": "tier.csv", "event_level_rows": "events.csv"})(),
            output_dir=Path("/tmp/out"),
            event_rows=_rows(),
            symbol_rows=[],
            time_rows=[],
            breath_rows=[],
            fakeout_touch_rows=[],
            tier_outcome_rows=[],
        )
        self.assertEqual(manifest["safety_markers"], SAFETY_MARKERS)
        self.assertTrue(manifest["research_only"])

    def test_no_broker_decision_execution_imports(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
