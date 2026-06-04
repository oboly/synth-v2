from __future__ import annotations

import ast
import unittest
from pathlib import Path

from src.research.run_context_touch_fakeout_shape_audit_v1 import (
    SAFETY_MARKERS,
    build_manifest,
    build_shape_rows,
    build_symbol_rows,
    build_time_rows,
    bool_bucket,
    parse_ts,
)


MODULE_PATH = Path("src/research/run_context_touch_fakeout_shape_audit_v1.py")


def _row(symbol: str, ts: str, tier: str, *, touch=None, fakeout=None, r24h: float = 0.0, r4h: float = 0.0, mfe: float = 1.0, mae: float = -1.0) -> dict:
    return {
        "symbol": symbol,
        "event_ts_utc_dt": parse_ts(ts),
        "context_quality_tier": tier,
        "reaction_zone_touch": touch,
        "fakeout_flag": fakeout,
        "forward_return_24h": r24h,
        "forward_return_4h": r4h,
        "max_favorable_excursion_pct": mfe,
        "max_adverse_excursion_pct": mae,
    }


def _rows() -> list[dict]:
    return [
        _row("XLM", "2026-05-01T04:00:00Z", "MARKET_ONLY_CONTEXT", touch=True, fakeout=False, r24h=4.0, r4h=1.0),
        _row("XLM", "2026-05-02T04:00:00Z", "MARKET_ONLY_CONTEXT", touch=True, fakeout=False, r24h=5.0, r4h=1.5),
        _row("FET", "2026-05-04T04:00:00Z", "MARKET_ONLY_CONTEXT", touch=True, fakeout=True, r24h=-1.0, r4h=-0.5),
        _row("ALGO", "2026-05-05T04:00:00Z", "SYMBOL_REGIME_CONTEXT", touch=False, fakeout=False, r24h=3.0, r4h=0.8),
        _row("ALGO", "2026-05-06T04:00:00Z", "SYMBOL_REGIME_CONTEXT", touch=None, fakeout=None, r24h=0.0, r4h=0.0),
    ]


class ContextTouchFakeoutShapeAuditV1Tests(unittest.TestCase):
    def test_touch_no_fakeout_bucket_aggregates_correctly(self) -> None:
        rows = build_shape_rows(_rows(), min_events=1)
        target = next(r for r in rows if r["context_quality_tier"] == "MARKET_ONLY_CONTEXT" and r["reaction_zone_touch"] == "TRUE" and r["fakeout_flag"] == "FALSE")
        self.assertEqual(target["event_count"], 2)
        self.assertEqual(target["avg_return_24h_pct"], 4.5)

    def test_fakeout_bucket_aggregates_correctly(self) -> None:
        rows = build_shape_rows(_rows(), min_events=1)
        target = next(r for r in rows if r["fakeout_flag"] == "TRUE")
        self.assertEqual(target["event_count"], 1)
        self.assertEqual(target["avg_return_24h_pct"], -1.0)

    def test_missing_touch_fakeout_become_unknown(self) -> None:
        self.assertEqual(bool_bucket(None), "UNKNOWN")
        rows = build_shape_rows(_rows(), min_events=1)
        self.assertTrue(any(r["reaction_zone_touch"] == "UNKNOWN" for r in rows))
        self.assertTrue(any(r["fakeout_flag"] == "UNKNOWN" for r in rows))

    def test_per_symbol_aggregation_works(self) -> None:
        rows = build_symbol_rows(_rows(), min_events=1)
        target = next(r for r in rows if r["symbol"] == "XLM" and r["fakeout_flag"] == "FALSE")
        self.assertEqual(target["event_count"], 2)

    def test_time_bucket_aggregation_works(self) -> None:
        rows = build_time_rows(_rows(), min_events=1)
        self.assertTrue(all("time_bucket_start_utc" in r for r in rows))
        self.assertTrue(any(r["event_count"] >= 1 for r in rows))

    def test_low_sample_marked_low_or_insufficient(self) -> None:
        rows = build_shape_rows(_rows(), min_events=5)
        self.assertTrue(all(r["sample_quality"] in {"LOW", "INSUFFICIENT"} for r in rows))

    def test_safety_markers_present(self) -> None:
        manifest = build_manifest(
            args=type("Args", (), {"event_level_rows": "events.csv"})(),
            output_dir=Path("/tmp/out"),
            event_rows=_rows(),
            shape_rows=[],
            symbol_rows=[],
            time_rows=[],
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


if __name__ == "__main__":
    unittest.main()
