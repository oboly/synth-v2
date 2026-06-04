from __future__ import annotations

import ast
import unittest
from pathlib import Path

from src.research.run_context_touch_fakeout_robustness_audit_v1 import (
    SAFETY_MARKERS,
    baseline_summary,
    bucket_start,
    build_manifest,
    classify_robustness,
    leave_one_symbol_rows,
    leave_one_time_rows,
    parse_ts,
    target_rows,
)


MODULE_PATH = Path("src/research/run_context_touch_fakeout_robustness_audit_v1.py")


def _row(symbol: str, ts: str, *, r24h: float | None, r4h: float | None = None, mfe: float = 1.0, mae: float = -1.0) -> dict:
    return {
        "symbol": symbol,
        "event_ts_utc_dt": parse_ts(ts),
        "context_quality_tier": "MARKET_ONLY_CONTEXT",
        "reaction_zone_touch": "True",
        "fakeout_flag": "False",
        "forward_return_24h": r24h,
        "forward_return_4h": r4h,
        "max_favorable_excursion_pct": mfe,
        "max_adverse_excursion_pct": mae,
    }


def _non_target(symbol: str, ts: str) -> dict:
    return {
        "symbol": symbol,
        "event_ts_utc_dt": parse_ts(ts),
        "context_quality_tier": "SYMBOL_REGIME_CONTEXT",
        "reaction_zone_touch": "True",
        "fakeout_flag": "False",
        "forward_return_24h": 0.0,
        "forward_return_4h": 0.0,
        "max_favorable_excursion_pct": 1.0,
        "max_adverse_excursion_pct": -1.0,
    }


class ContextTouchFakeoutRobustnessAuditV1Tests(unittest.TestCase):
    def test_leave_one_symbol_out_detects_symbol_concentration(self) -> None:
        rows = [
            _row("XLM", "2026-05-19T00:00:00Z", r24h=8.0),
            _row("XLM", "2026-05-19T04:00:00Z", r24h=7.0),
            _row("XLM", "2026-05-19T08:00:00Z", r24h=6.0),
            _row("FET", "2026-05-22T00:00:00Z", r24h=1.0),
            _row("FET", "2026-05-22T04:00:00Z", r24h=1.0),
        ]
        base = baseline_summary(rows, 1)
        cls = classify_robustness(base, leave_one_symbol_rows(rows, 1), leave_one_time_rows(rows, 1))
        self.assertEqual(cls, "SYMBOL_CONCENTRATED")

    def test_leave_one_time_bucket_out_detects_time_concentration(self) -> None:
        rows = [
            _row("XLM", "2026-05-19T00:00:00Z", r24h=4.0),
            _row("FET", "2026-05-19T04:00:00Z", r24h=4.0),
            _row("TAO", "2026-05-19T08:00:00Z", r24h=4.0),
            _row("WLD", "2026-05-19T12:00:00Z", r24h=4.0),
            _row("ALGO", "2026-05-19T16:00:00Z", r24h=4.0),
            _row("XLM", "2026-05-22T00:00:00Z", r24h=1.0),
            _row("FET", "2026-05-22T04:00:00Z", r24h=1.0),
            _row("TAO", "2026-05-22T08:00:00Z", r24h=1.0),
        ]
        base = baseline_summary(rows, 1)
        cls = classify_robustness(base, leave_one_symbol_rows(rows, 1), leave_one_time_rows(rows, 1))
        self.assertEqual(cls, "TIME_CONCENTRATED")

    def test_balanced_fixture_classifies_robust_enough_for_more_research(self) -> None:
        rows = []
        symbols = ["XLM", "FET", "TAO", "WLD", "ALGO"]
        buckets = ["2026-05-19T00:00:00Z", "2026-05-22T00:00:00Z", "2026-05-25T00:00:00Z"]
        for ts in buckets:
            for symbol in symbols:
                rows.append(_row(symbol, ts, r24h=2.0, r4h=0.5))
                rows.append(_row(symbol, ts.replace("00:00:00", "04:00:00"), r24h=1.5, r4h=0.3))
        base = baseline_summary(rows, 5)
        cls = classify_robustness(base, leave_one_symbol_rows(rows, 5), leave_one_time_rows(rows, 5))
        self.assertEqual(cls, "ROBUST_ENOUGH_FOR_MORE_RESEARCH")

    def test_small_sample_classifies_sample_too_small(self) -> None:
        rows = [_row("XLM", "2026-05-19T00:00:00Z", r24h=1.0), _row("FET", "2026-05-22T00:00:00Z", r24h=1.0)]
        base = baseline_summary(rows, 5)
        cls = classify_robustness(base, leave_one_symbol_rows(rows, 5), leave_one_time_rows(rows, 5))
        self.assertEqual(cls, "SAMPLE_TOO_SMALL")

    def test_not_robust_fixture_classifies_not_robust(self) -> None:
        rows = []
        symbols = ["XLM", "FET", "TAO", "WLD", "ALGO"]
        for symbol in symbols:
            rows.append(_row(symbol, "2026-05-19T00:00:00Z", r24h=10.0))
            rows.append(_row(symbol, "2026-05-22T00:00:00Z", r24h=0.1))
            rows.append(_row(symbol, "2026-05-25T00:00:00Z", r24h=0.1))
            rows.append(_row(symbol, "2026-05-28T00:00:00Z", r24h=0.1))
        base = baseline_summary(rows, 5)
        cls = classify_robustness(base, leave_one_symbol_rows(rows, 5), leave_one_time_rows(rows, 5))
        self.assertEqual(cls, "NOT_ROBUST")

    def test_missing_metrics_do_not_crash(self) -> None:
        rows = [_row("XLM", "2026-05-19T00:00:00Z", r24h=None, r4h=None), _non_target("ALGO", "2026-05-19T00:00:00Z")]
        filtered = target_rows(rows)
        base = baseline_summary(filtered, 1)
        self.assertEqual(base["event_count"], 1)

    def test_safety_markers_present(self) -> None:
        rows = [_row("XLM", "2026-05-19T00:00:00Z", r24h=1.0)]
        base = baseline_summary(rows, 1)
        manifest = build_manifest(
            args=type("Args", (), {"event_level_rows": "events.csv"})(),
            output_dir=Path("/tmp/out"),
            base=base,
            symbol_rows=[],
            time_rows=[],
            robustness_classification="UNKNOWN",
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
