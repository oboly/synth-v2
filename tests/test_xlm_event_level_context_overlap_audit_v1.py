from __future__ import annotations

import ast
import unittest
from pathlib import Path

from src.research.run_xlm_event_level_context_overlap_audit_v1 import (
    SAFETY_MARKERS,
    build_event_rows,
    build_manifest,
    parse_ts,
)


MODULE_PATH = Path("src/research/run_xlm_event_level_context_overlap_audit_v1.py")


def _event_rows() -> list[dict]:
    return [
        {
            "symbol": "XLM",
            "event_ts_utc_dt": parse_ts("2026-05-01T04:00:00Z"),
            "source_candle_ts_utc": "2026-05-01T04:00:00Z",
            "max_favorable_excursion_pct": 6.0,
            "max_adverse_excursion_pct": -2.0,
            "drawdown_after_event_pct": -1.0,
        }
    ]


def _recompute_known() -> list[dict]:
    return [
        {
            "symbol": "XLM",
            "asof_ts_utc_dt": parse_ts("2026-05-01T04:00:00Z"),
            "breath_phase": "EXPANSION",
            "breath_alignment": "ALIGNED",
            "market_regime": "ALT_STRENGTH",
            "btc_context": "BTC_OK",
            "symbol_regime": "REL_STRENGTH",
        }
    ]


def _recompute_unknown() -> list[dict]:
    return [
        {
            "symbol": "XLM",
            "asof_ts_utc_dt": parse_ts("2026-05-01T04:00:00Z"),
            "breath_phase": "UNKNOWN",
            "breath_alignment": "UNKNOWN",
            "market_regime": "UNKNOWN",
            "btc_context": "UNKNOWN",
            "symbol_regime": "UNKNOWN",
        }
    ]


def _context_rows() -> list[dict]:
    return [
        {
            "symbol": "XLM",
            "asof_ts_utc_dt": parse_ts("2026-05-01T04:00:00Z"),
            "breath_phase": "EXPANSION",
            "breath_alignment": "ALIGNED",
            "market_regime": "ALT_STRENGTH",
            "btc_context": "BTC_OK",
            "symbol_regime": "REL_STRENGTH",
        }
    ]


def _profile_known() -> list[dict]:
    return [
        {
            "symbol": "XLM",
            "breath_phase": "EXPANSION",
            "breath_alignment": "ALIGNED",
            "market_regime": "ALT_STRENGTH",
            "btc_context": "BTC_OK",
            "symbol_regime": "REL_STRENGTH",
        }
    ]


def _profile_unknown() -> list[dict]:
    return [
        {
            "symbol": "XLM",
            "breath_phase": "UNKNOWN",
            "breath_alignment": "UNKNOWN",
            "market_regime": "UNKNOWN",
            "btc_context": "UNKNOWN",
            "symbol_regime": "UNKNOWN",
        }
    ]


class XlmEventLevelContextOverlapAuditV1Tests(unittest.TestCase):
    def test_event_with_known_recompute_context_classifies_event_has_known_context(self) -> None:
        rows = build_event_rows(
            symbol="XLM",
            recompute_rows=_recompute_known(),
            context_rows=_context_rows(),
            profile_rows=_profile_known(),
            event_rows=_event_rows(),
        )
        self.assertEqual(rows[0]["issue_classification"], "EVENT_HAS_KNOWN_CONTEXT")

    def test_aggregate_unknown_but_event_known_classifies_aggregate_profile_lost_context(self) -> None:
        rows = build_event_rows(
            symbol="XLM",
            recompute_rows=_recompute_known(),
            context_rows=_context_rows(),
            profile_rows=_profile_unknown(),
            event_rows=_event_rows(),
        )
        self.assertEqual(rows[0]["issue_classification"], "AGGREGATE_PROFILE_LOST_CONTEXT")

    def test_event_with_unknown_recompute_context_classifies_event_context_unknown(self) -> None:
        rows = build_event_rows(
            symbol="XLM",
            recompute_rows=_recompute_unknown(),
            context_rows=[],
            profile_rows=_profile_unknown(),
            event_rows=_event_rows(),
        )
        self.assertEqual(rows[0]["issue_classification"], "EVENT_CONTEXT_UNKNOWN")

    def test_manifest_contains_safety_markers(self) -> None:
        manifest = build_manifest(
            args=type(
                "Args",
                (),
                {
                    "symbol": "XLM",
                    "recompute_rows": "r.csv",
                    "context_rows": "c.csv",
                    "profile_rows": "p.csv",
                    "event_rows": "e.jsonl",
                },
            )(),
            output_dir=Path("/tmp/out"),
            rows=[],
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
