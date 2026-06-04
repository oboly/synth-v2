from __future__ import annotations

import ast
import unittest
from pathlib import Path

from src.research.run_event_bearing_context_alignment_audit_v1 import (
    SAFETY_MARKERS,
    build_alignment_rows,
    build_manifest,
)


MODULE_PATH = Path("src/research/run_event_bearing_context_alignment_audit_v1.py")


def _recompute_known_rows() -> list[dict[str, str]]:
    return [
        {
            "symbol": "WLD",
            "breath_phase": "EXPANSION",
            "breath_alignment": "ALIGNED",
            "market_regime": "ALT_STRENGTH",
            "btc_context": "BTC_OK",
            "symbol_regime": "REL_STRENGTH",
            "fibo_context": "UNKNOWN",
        }
    ]


def _recompute_unknown_rows() -> list[dict[str, str]]:
    return [
        {
            "symbol": "NEAR",
            "breath_phase": "UNKNOWN",
            "breath_alignment": "UNKNOWN",
            "market_regime": "UNKNOWN",
            "btc_context": "UNKNOWN",
            "symbol_regime": "UNKNOWN",
            "fibo_context": "UNKNOWN",
        }
    ]


def _context_rows_for_wld() -> list[dict[str, str]]:
    return [
        {
            "symbol": "WLD",
            "breath_phase": "EXPANSION",
            "breath_alignment": "ALIGNED",
            "market_regime": "ALT_STRENGTH",
            "btc_context": "BTC_OK",
            "symbol_regime": "REL_STRENGTH",
            "fibo_context": "UNKNOWN",
        }
    ]


def _profile_known_wld() -> list[dict[str, str]]:
    return [
        {
            "symbol": "WLD",
            "breath_phase": "EXPANSION",
            "breath_alignment": "ALIGNED",
            "market_regime": "ALT_STRENGTH",
            "btc_context": "BTC_OK",
            "symbol_regime": "REL_STRENGTH",
            "fibo_context": "UNKNOWN",
            "event_count": "10",
        }
    ]


def _profile_unknown_near() -> list[dict[str, str]]:
    return [
        {
            "symbol": "NEAR",
            "breath_phase": "UNKNOWN",
            "breath_alignment": "UNKNOWN",
            "market_regime": "UNKNOWN",
            "btc_context": "UNKNOWN",
            "symbol_regime": "UNKNOWN",
            "fibo_context": "UNKNOWN",
            "event_count": "7",
        }
    ]


class EventBearingContextAlignmentAuditV1Tests(unittest.TestCase):
    def test_known_recompute_rows_with_no_profile_events_classify_known_rows_not_event_bearing(self) -> None:
        rows = build_alignment_rows(
            recompute_rows=_recompute_known_rows(),
            context_rows=[],
            profile_rows=[],
        )
        self.assertEqual(rows[0]["issue_classification"], "KNOWN_ROWS_NOT_EVENT_BEARING")

    def test_profile_unknown_rows_with_no_known_recompute_classify_live_semantics_unknown(self) -> None:
        rows = build_alignment_rows(
            recompute_rows=_recompute_unknown_rows(),
            context_rows=[],
            profile_rows=_profile_unknown_near(),
        )
        self.assertEqual(rows[0]["issue_classification"], "LIVE_SEMANTICS_UNKNOWN")

    def test_overlapping_known_context_and_profile_events_classify_usable_context_overlap(self) -> None:
        rows = build_alignment_rows(
            recompute_rows=_recompute_known_rows(),
            context_rows=_context_rows_for_wld(),
            profile_rows=_profile_known_wld(),
        )
        self.assertEqual(rows[0]["issue_classification"], "USABLE_CONTEXT_OVERLAP")

    def test_manifest_contains_safety_markers(self) -> None:
        manifest = build_manifest(
            args=type(
                "Args",
                (),
                {
                    "recompute_rows": "r.csv",
                    "context_rows": "c.csv",
                    "profile_rows": "p.csv",
                    "context_qualified_audit_rows": "q.csv",
                },
            )(),
            output_dir=Path("/tmp/out"),
            summary={},
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
